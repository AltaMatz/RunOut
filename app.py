from datetime import datetime
import os
import secrets
import json
from flask import Flask, jsonify, render_template, request, session, redirect, url_for  # type: ignore
import requests #type: ignore
from dotenv import load_dotenv # type: ignore
import asyncio
import httpx # type:ignore

from shared_modules.sso_middleware import SSOMiddleware, WhitelistManager, RateLimiter

app = Flask(__name__)

load_dotenv()

# Necessario per far funzionare le sessioni Flask (cookie firmati).
# Impostalo in .env come FLASK_SECRET_KEY=...
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
app.permanent_session_lifetime = 28800

whitelist_manager = WhitelistManager("data/whitelist.json")

# Modalità SSO
SSO_MODE = os.getenv('SSO_MODE', 'dev').lower()
DEV_USER_EMAIL = os.getenv('DEV_USER_EMAIL', 'vivo.ciro.studente@itispaleocapa.it')

rate_limiter = RateLimiter(
    max_sessions_per_user=3,
    max_sessions_global=100,
    session_ttl_seconds=28800
)

sso_middleware = SSOMiddleware(
    jwt_secret=os.getenv("SSO_JWT_SECRET", "test"),
    jwt_algorithm="HS256",
    jwt_issuer=os.getenv("SSO_JWT_ISSUER", "sso-portal"),
    jwt_audience=os.getenv("SSO_JWT_AUDIENCE", "mia-app"),
    session_timeout=28800,
    portal_url=os.getenv("SSO_PORTAL_URL", "http://localhost:5000"),
    whitelist_manager=whitelist_manager,
    rate_limiter=rate_limiter
)

API_TOKEN = os.getenv("API_TOKEN") # Carico il token dal file .env

# Carica le aule dal file JSON
with open('floors.json', 'r', encoding='utf-8') as f:
    aule_dict = json.load(f)

# Crea una lista piatta di tutte le aule
aula = []
for floor, rooms in aule_dict.items():
    aula.extend(rooms)
# print (len(aula))

# ============================================================
# CACHE EMERGENZE
# ============================================================

_emergenze_cache = {
    "risultati_filtrati": [],
    "giorno": None,
    "ora": None,
    "total_aule": 0,
    "num_with_class": 0,
    "last_update": None,
    "loading": False,
}
CACHE_TTL_SECONDS = 300  # Aggiorna la cache ogni 5 minuti


async def _fetch_emergenze_data():
    """Recupera i dati delle emergenze dalle API e aggiorna la cache in memoria."""
    global _emergenze_cache

    if _emergenze_cache["loading"]:
        return  # Evita fetch paralleli
    _emergenze_cache["loading"] = True

    try:
        now = datetime.now()
        giorno = now.weekday() + 1  # Lunedì=1 … Venerdì=5
        ora_reale = now.hour
        ora = (ora_reale - 7) if 8 <= ora_reale <= 14 else 1

        async def fetch_classe(client, a):
            url = f"https://sipal.itispaleocapa.it/api/proxySipal/v1/studenti/classe/{giorno}/{ora}/{a}"
            headers = {
                "accept": "application/json",
                "Authorization": f"Bearer {API_TOKEN}",
                "User-Agent": "Mozilla/5.0",
            }
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return {"aula": a, "risultato": response.json(), "errore": None}
            except httpx.HTTPStatusError as e:
                return {"aula": a, "risultato": None, "errore": f"Errore HTTP {e.response.status_code}"}
            except Exception as e:
                return {"aula": a, "risultato": None, "errore": f"Errore generico: {str(e)}"}

        async with httpx.AsyncClient() as client:
            tasks = [fetch_classe(client, a) for a in aula]
            risultati = await asyncio.gather(*tasks)

        risultati_filtrati = []
        num_with_class = 0
        for r in risultati:
            classe = r["aula"]
            has_class = False
            if r["risultato"] and isinstance(r["risultato"], dict):
                if r["risultato"].get("classe"):
                    classe = r["risultato"]["classe"]
                    has_class = True
                elif r["risultato"].get("studenti") and len(r["risultato"]["studenti"]) > 0:
                    primo = r["risultato"]["studenti"][0]
                    if isinstance(primo, dict) and primo.get("classe"):
                        classe = primo["classe"]
                        has_class = True
            r["classe"] = classe
            if has_class:
                num_with_class += 1
            if classe != r["aula"]:
                risultati_filtrati.append(r)

        risultati_filtrati.sort(key=lambda x: x["classe"])

        _emergenze_cache.update({
            "risultati_filtrati": risultati_filtrati,
            "giorno": giorno,
            "ora": ora,
            "total_aule": len(aula),
            "num_with_class": num_with_class,
            "last_update": datetime.now(),
            "loading": False,
        })
        app.logger.info(f"Cache emergenze aggiornata: {num_with_class} classi trovate")

    except Exception as e:
        _emergenze_cache["loading"] = False
        app.logger.error(f"Errore aggiornamento cache emergenze: {e}")


def _cache_is_stale() -> bool:
    last = _emergenze_cache["last_update"]
    if last is None:
        return True
    return (datetime.now() - last).total_seconds() > CACHE_TTL_SECONDS


def _refresh_cache_in_background():
    """Lancia il refresh della cache in un thread separato senza bloccare la risposta."""
    import threading

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_fetch_emergenze_data())
        finally:
            loop.close()

    threading.Thread(target=run, daemon=True).start()


# ============================================================
# UTILITY
# ============================================================

def get_username(email: str) -> str:
    return email.split('@')[0]

@app.route("/")
def home():
    return render_template("home.html")





# ============================================================
# ROUTE SSO
# ============================================================

@app.route('/sso/login')
def sso_login():
    """
    Endpoint SSO. Il portale checkin chiama questa URL passando il JWT.
    Questo è l'unico punto di ingresso autenticato nell'applicazione.
    """
    token = request.args.get('token')

    # --- Modalità DEV: simula il login senza portale reale ---
    if SSO_MODE == 'dev' and not token:
        dev_email = request.args.get('email') or DEV_USER_EMAIL
        app.logger.info(f"DEV MODE: login simulato per {dev_email}")
        user_data = {
            'email': dev_email,
            'name': get_username(dev_email).replace('.', ' ').title(),
            'googleId': 'dev-user-id',
            'picture': ''
        }
        return _complete_login(user_data)

    if not token:
        return render_sso_error(
            "Token SSO mancante. Accedi tramite il portale.",
            SSO_CONFIG['portal_url']
        )

    try:
        user_data = sso_middleware.validate_jwt(token)
        return _complete_login(user_data)
    except Exception as e:
        app.logger.error(f"Errore validazione SSO: {e}")
        return render_sso_error(
            f"Token SSO non valido o scaduto. Effettua nuovamente il login.",
            SSO_CONFIG['portal_url']
        )


def _complete_login(user_data: dict):
    """
    Logica comune post-validazione JWT:
    1. Verifica whitelist
    2. Verifica rate limit
    3. Crea sessione e redirect alla dashboard
    """
    email = user_data.get('email', '')

    # 1. Controllo whitelist
    if not whitelist_manager.is_authorized(email):
        app.logger.warning(f"Accesso negato da whitelist: {email}")
        return render_sso_error(
            f"Il tuo account ({email}) non è autorizzato ad accedere a questa applicazione. "
            "Contatta l'amministratore se ritieni sia un errore.",
            SSO_CONFIG['portal_url'],
            status_code=403,
            title="Account Non Autorizzato",
            icon="🚫"
        )

    # 2. Controllo rate limit - registra la nuova sessione
    session_id = secrets.token_hex(32)
    allowed, reason = rate_limiter.register_session(session_id, email)
    if not allowed:
        app.logger.warning(f"Rate limit raggiunto per: {email}")
        return render_sso_error(
            reason,
            SSO_CONFIG['portal_url'],
            status_code=429,
            title="Troppe Sessioni Attive",
            icon="⏱️"
        )

    # 3. Crea sessione Flask
    sso_middleware.create_session(user_data, session, session_id=session_id)

    # 4. Precarica i dati emergenze in background (se la cache è scaduta)
    if _cache_is_stale():
        _refresh_cache_in_background()

    return redirect(url_for('dashboard'))


@app.route("/emergenze") # ROTTA EMERGENZE
def emergenze():
    # Se la cache è vuota (primo avvio senza login), avvia il fetch e aspetta
    if _emergenze_cache["last_update"] is None:
        import threading, time
        _refresh_cache_in_background()
        # Aspetta al massimo 10 secondi che la cache si popoli
        for _ in range(20):
            if _emergenze_cache["last_update"] is not None:
                break
            time.sleep(0.5)
    # Se la cache è scaduta, aggiorna in background e servi i dati vecchi
    elif _cache_is_stale():
        _refresh_cache_in_background()

    c = _emergenze_cache
    return render_template(
        "emergenze.html",
        risultati=c["risultati_filtrati"],
        giorno=c["giorno"],
        ora=c["ora"],
        total_aule=c["total_aule"],
        num_with_class=c["num_with_class"],
    )

@app.route("/api/emergenze/refresh", methods=["POST"])
def refresh_emergenze():
    """Forza il ricalcolo della cache emergenze (es. da un pulsante nella UI)."""
    _refresh_cache_in_background()
    return jsonify({"success": True, "message": "Aggiornamento cache avviato"}), 202


@app.route("/elencoStudenti/<classe>/<aula>") # ROTTA ELENCO STUDENTI
def elencoStudenti(classe, aula):
    
    url = f"https://sipal.itispaleocapa.it/api/proxySipal/v1/studenti/classe/elenco/{classe}"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {API_TOKEN}",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        dati_classe = response.json()
            
        studenti = []
        if isinstance(dati_classe, dict):
            if classe in dati_classe and isinstance(dati_classe.get(classe), list):
                studenti = dati_classe.get(classe) or []
            
        return render_template(
            "elenco_studenti.html",
            classe=classe,
            aula=aula,
            studenti=studenti,
            giorno=None,
            ora=None,
            errore=None
        )
    except requests.HTTPError as e:
        return render_template(
            "elenco_studenti.html",
            classe=classe,
            aula=aula,
            studenti=[],
            giorno=None,
            ora=None,
            errore=f"Errore HTTP {e.response.status_code}"
        )
    except Exception as e:
        return render_template(
            "elenco_studenti.html",
            classe=classe,
            aula=aula,
            studenti=[],
            giorno=None,
            ora=None,
            errore=f"Errore generico: {str(e)}"
        )

@app.route("/piantina") # ROTTA PIANTINA
def piantina():
    return render_template("piantina.html")

@app.route("/registri-compilati") # ROTTA REGISTRI COMPILATI
def registri_compilati():
    return render_template("registri_compilati.html")

@app.route("/api/emergenze", methods=["POST"])
def salva_presenze():
    """
    Salva le presenze degli studenti in un file JSON.
    Struttura del file: presenze.json contiene un array di oggetti, uno per ogni salvataggio.
    """
    try:
        data = request.get_json()
        
        if not data or 'classe' not in data or 'presenze' not in data:
            return jsonify({"error": "Dati mancanti: classe e presenze sono obbligatori"}), 400
        
        classe = data['classe']
        presenze = data['presenze']
        
        # Prepara il record da salvare
        now = datetime.now()
        record = {
            "classe": classe,
            "data": now.strftime("%Y-%m-%d"),
            "ora": now.strftime("%H:%M:%S"),
            "timestamp": now.isoformat(),
            "presenze": presenze
        }
        
        # Leggi il file esistente (se presente)
        # Usa il percorso relativo alla directory del progetto
        file_path = os.path.join(os.path.dirname(__file__), "presenze.json")
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    all_presenze = json.load(f)
                except json.JSONDecodeError:
                    all_presenze = []
        else:
            all_presenze = []
        
        # Aggiungi il nuovo record
        all_presenze.append(record)
        
        # Salva il file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(all_presenze, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            "success": True,
            "message": f"Presenze salvate per la classe {classe}",
            "record": record
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Errore durante il salvataggio: {str(e)}"}), 500

@app.route("/dashboard")
@sso_middleware.sso_login_required
def dashboard():
    if 'user' not in session:
        return "Utente non autenticato", 401
    user = session['user']
    return f"Ciao {user['email']}"


# Precarica la cache all'avvio (funziona con qualsiasi WSGI server)
with app.app_context():
    _refresh_cache_in_background()

if __name__ == "__main__":
    _refresh_cache_in_background()  # Precarica i dati appena il server parte
    app.run(debug=True)