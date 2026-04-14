from datetime import datetime
import os
import secrets
import json
from functools import wraps
from flask import Flask, jsonify, render_template, render_template_string, request, session, redirect, url_for  # type: ignore
import requests #type: ignore
from dotenv import load_dotenv # type: ignore
import asyncio
import httpx # type:ignore

from config import (
    FLASK_SECRET_KEY, SESSION_LIFETIME_SECONDS,
    SSO_MODE, DEV_USER_EMAIL, DEV_DOCENTE_EMAIL,
    SSO_JWT_SECRET, SSO_JWT_ISSUER, SSO_JWT_AUDIENCE, SSO_PORTAL_URL,
    MAX_SESSIONS_PER_USER, MAX_SESSIONS_GLOBAL,
    WHITELIST_FILE, WHITELIST_STUDENTI_FILE, API_TOKEN, DEBUG, SSO_CONFIG
)
from shared_modules.sso_middleware import SSOMiddleware, WhitelistManager, RateLimiter, RoleManager

app = Flask(__name__)

# Configurazione Flask
app.secret_key = FLASK_SECRET_KEY
app.permanent_session_lifetime = SESSION_LIFETIME_SECONDS
app.debug = DEBUG

# Inizializza manager della whitelist
whitelist_manager = WhitelistManager(WHITELIST_FILE)

# Inizializza role manager (per assegnare ruoli in base all'email)
role_manager = RoleManager(WHITELIST_FILE, WHITELIST_STUDENTI_FILE)

# Inizializza rate limiter
rate_limiter = RateLimiter(
    max_sessions_per_user=MAX_SESSIONS_PER_USER,
    max_sessions_global=MAX_SESSIONS_GLOBAL,
    session_ttl_seconds=SESSION_LIFETIME_SECONDS
)

# Inizializza middleware SSO
sso_middleware = SSOMiddleware(
    jwt_secret=SSO_JWT_SECRET,
    jwt_algorithm="HS256",
    jwt_issuer=SSO_JWT_ISSUER,
    jwt_audience=SSO_JWT_AUDIENCE,
    session_timeout=SESSION_LIFETIME_SECONDS,
    portal_url=SSO_PORTAL_URL,
    whitelist_manager=whitelist_manager,
    rate_limiter=rate_limiter
)

API_TOKEN = API_TOKEN  # Carico il token dal config

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
        giorno = now.weekday() + 1  # Lunedì=1 … Venerdì=5 (per API)
        
        # Nomi dei giorni della settimana
        giorni_nomi = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica']
        giorno_nome = giorni_nomi[now.weekday()]  # Nome del giorno della settimana
        
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
            "giorno_nome": giorno_nome,
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
# UTILITY & DECORATORS
# ============================================================

def get_username(email: str) -> str:
    return email.split('@')[0]


def role_required(allowed_roles):
    """
    Decorator per proteggere le rotte in base al ruolo dell'utente.
    
    Uso:
        @role_required('docente')
        def my_route():
            ...
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = session.get('user', None)
            if not user:
                app.logger.warning("Accesso senza sessione")
                return redirect(url_for('home'))
            
            user_role = user.get('role', 'guest')
            if user_role not in allowed_roles:
                app.logger.warning(f"Accesso vietato per ruolo '{user_role}' a {request.path}")
                return render_template_string(
                    """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <title>Accesso Vietato</title>
                        <style>
                            body { font-family: Arial; background: #f5f5f5; padding: 20px; }
                            .error-container { max-width: 600px; margin: 100px auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); text-align: center; }
                            .error-icon { font-size: 64px; margin-bottom: 20px; }
                            h1 { color: #d32f2f; margin: 0 0 12px; }
                            p { color: #666; margin: 12px 0; }
                            .user-role { background: #f0f0f0; padding: 12px; border-radius: 6px; margin: 20px 0; font-family: monospace; }
                            a { display: inline-block; margin-top: 20px; padding: 10px 24px; background: #667eea; color: white; text-decoration: none; border-radius: 6px; }
                            a:hover { background: #5568d3; }
                        </style>
                    </head>
                    <body>
                        <div class="error-container">
                            <div class="error-icon">🚫</div>
                            <h1>Accesso Vietato</h1>
                            <p>Non hai il permesso di accedere a questa pagina.</p>
                            <p>Ruoli consentiti: <strong>{{ allowed }}</strong></p>
                            <div class="user-role">Il tuo ruolo: <strong>{{ your_role }}</strong></div>
                            <a href="{{ home_url }}">← Torna alla Home</a>
                        </div>
                    </body>
                    </html>
                    """,
                    allowed=", ".join(allowed_roles),
                    your_role=user_role,
                    home_url=url_for('home')
                ), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route("/")
def home():
    """Home page - mostra scelta email in dev mode, oppure home normale."""
    user = session.get('user', None)
    
    # In dev mode, mostra direttamente la scelta di email se non autenticato
    if SSO_MODE == 'dev' and not user:
        return render_template("dev_login_choice.html",
                             student_email=DEV_USER_EMAIL,
                             docente_email=DEV_DOCENTE_EMAIL)
    
    # Altrimenti mostra la home normale
    return render_template("home.html", user=user, sso_mode=SSO_MODE)


# ============================================================
# DEV MODE - SCELTA EMAIL
# ============================================================

@app.route('/dev/login-choice')
def dev_login_choice():
    """
    (Solo in DEV mode) Pagina per scegliere quale email usare per il login di test.
    """
    if SSO_MODE != 'dev':
        return redirect(url_for('home'))
    
    return render_template("dev_login_choice.html", 
                         student_email=DEV_USER_EMAIL,
                         docente_email=DEV_DOCENTE_EMAIL)


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

    # 1. Determina il ruolo e verifica autorizzazione
    role, is_authorized = role_manager.get_role(email)
    if not is_authorized:
        app.logger.warning(f"Accesso negato - Utente non autorizzato: {email} (role: {role})")
        return render_sso_error(
            f"Il tuo account ({email}) non è autorizzato ad accedere a questa applicazione. "
            "Contatta l'amministratore se ritieni sia un errore.",
            SSO_CONFIG['portal_url'],
            status_code=403,
            title="Account Non Autorizzato",
            icon="🚫"
        )
    
    app.logger.info(f"Utente autorizzato: {email} con ruolo '{role}'")

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

    # 3. Crea sessione Flask (con ruolo)
    sso_middleware.create_session(user_data, session, session_id=session_id, role=role)

    # 4. Precarica i dati emergenze in background (se la cache è scaduta)
    if _cache_is_stale():
        _refresh_cache_in_background()

    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    """Logout - termina la sessione e reindirizza al portale SSO o home."""
    if session.get('session_id'):
        rate_limiter.remove_session(session.get('session_id'))
    session.clear()
    app.logger.info("Logout effettuato")
    return redirect(url_for('home'))


@app.route("/emergenze") # ROTTA EMERGENZE
@role_required('docente')  # Solo docenti possono accedere
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
        giorno_nome=c["giorno_nome"],
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
    """Dashboard - pagina principale per utenti autenticati."""
    if 'user' not in session:
        return redirect(url_for('home'))
    user = session['user']
    return render_template("dashboard.html", user=user)


# Precarica la cache all'avvio (funziona con qualsiasi WSGI server)
with app.app_context():
    _refresh_cache_in_background()

if __name__ == "__main__":
    _refresh_cache_in_background()  # Precarica i dati appena il server parte
    app.run(debug=True)