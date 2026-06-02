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
    DEV_RSPP_EMAIL, DEV_DIRIGENTE_EMAIL, DEV_UFFICIO_TECNICO_EMAIL,
    SSO_JWT_SECRET, SSO_JWT_ISSUER, SSO_JWT_AUDIENCE, SSO_PORTAL_URL,
    MAX_SESSIONS_PER_USER, MAX_SESSIONS_GLOBAL,
    WHITELIST_FILE, API_TOKEN, DEBUG, SSO_CONFIG
)
from shared_modules.sso_middleware import SSOMiddleware, RateLimiter, RoleManager, render_sso_error

app = Flask(__name__)

# Configurazione Flask
app.secret_key = FLASK_SECRET_KEY
app.permanent_session_lifetime = SESSION_LIFETIME_SECONDS
app.debug = DEBUG

# Inizializza role manager (assegna ruoli in base alla forma dell'email e whitelist.json)
role_manager = RoleManager(WHITELIST_FILE)

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
# GESTIONE EMERGENZE - STATO ATTIVO/INATTIVO
# ============================================================

EMERGENZA_STATUS_FILE = 'emergenza_status.json'

def _get_emergenza_status():
    """Legge lo stato dell'emergenza dal file."""
    try:
        if os.path.exists(EMERGENZA_STATUS_FILE):
            with open(EMERGENZA_STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        app.logger.error(f"Errore lettura stato emergenza: {e}")
    
    # Default se file non esiste o errore
    return {"active": False, "started_at": None, "ended_at": None}


def _set_emergenza_status(active: bool):
    """Imposta lo stato dell'emergenza nel file."""
    try:
        status = {
            "active": active,
            "started_at": datetime.now().isoformat() if active else None,
            "ended_at": datetime.now().isoformat() if not active else None,
        }
        with open(EMERGENZA_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        app.logger.info(f"Stato emergenza: {'ATTIVA' if active else 'TERMINATA'}")
        return status
    except Exception as e:
        app.logger.error(f"Errore scrittura stato emergenza: {e}")
        return _get_emergenza_status()


# ============================================================
# UTILITY & DECORATORS
# ============================================================

def get_username(email: str) -> str:
    return email.split('@')[0]


def get_dev_roles():
    """
    Ritorna i 5 ruoli disponibili in modalità DEV con le loro email.
    """
    return {
        'studente': DEV_USER_EMAIL,
        'docente': DEV_DOCENTE_EMAIL,
        'rspp': DEV_RSPP_EMAIL,
        'dirigente': DEV_DIRIGENTE_EMAIL,
        'ufficio_tecnico': DEV_UFFICIO_TECNICO_EMAIL,
    }


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
#@role_required('docente')
def home():
    """Home page - mostra scelta ruoli in dev mode, oppure home normale."""
    user = session.get('user', None)
    
    # In dev mode, mostra direttamente la scelta di ruoli se non autenticato
    if SSO_MODE == 'dev' and not user:
        dev_roles = get_dev_roles()
        return render_template("dev_login_choice.html", dev_roles=dev_roles)
    
    # Altrimenti mostra la home normale
    return render_template("home.html", user=user, sso_mode=SSO_MODE)


# ============================================================
# DEV MODE - SCELTA EMAIL
# ============================================================

@app.route('/dev/login-choice')
def dev_login_choice():
    """
    (Solo in DEV mode) Pagina per scegliere quale ruolo usare per il login di test.
    """
    if SSO_MODE != 'dev':
        return redirect(url_for('home'))
    
    dev_roles = get_dev_roles()
    return render_template("dev_login_choice.html", dev_roles=dev_roles)


# ============================================================
# ROUTE SSO
# ============================================================

@app.route('/sso/login')
def sso_login():
    """
    Endpoint SSO. Il portale checkin chiama questa URL passando il JWT.
    In DEV mode, accetta il parametro role per simulare i diversi ruoli.
    Questo è l'unico punto di ingresso autenticato nell'applicazione.
    """
    token = request.args.get('token')

    # --- Modalità DEV: simula il login senza portale reale ---
    if SSO_MODE == 'dev' and not token:
        dev_role = request.args.get('role', 'studente')
        dev_roles = get_dev_roles()
        
        if dev_role not in dev_roles:
            return render_sso_error(
                f"Ruolo DEV non valido: {dev_role}. Ruoli disponibili: {', '.join(dev_roles.keys())}",
                SSO_CONFIG['portal_url'],
                status_code=400
            )
        
        dev_email = dev_roles[dev_role]
        app.logger.info(f"DEV MODE: login simulato per ruolo '{dev_role}' con email {dev_email}")
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
@role_required(['docente', 'rspp', 'dirigente', 'ufficio_tecnico'])  # Docenti e staff
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
    emergenza_status = _get_emergenza_status()
    user = session.get('user', {})
    user_role = user.get('role', '')
    
    # Se emergenza non attiva, nessuno vede l'elenco delle classi
    if not emergenza_status["active"]:
        return render_template(
            "emergenze.html",
            risultati=[],
            giorno=c["giorno"],
            giorno_nome=c["giorno_nome"],
            ora=c["ora"],
            total_aule=0,
            num_with_class=0,
            emergenza_attiva=emergenza_status["active"],
            is_ufficio_tecnico=(user_role == 'ufficio_tecnico'),
        )
    
    return render_template(
        "emergenze.html",
        risultati=c["risultati_filtrati"],
        giorno=c["giorno"],
        giorno_nome=c["giorno_nome"],
        ora=c["ora"],
        total_aule=c["total_aule"],
        num_with_class=c["num_with_class"],
        emergenza_attiva=emergenza_status["active"],
        is_ufficio_tecnico=(user_role == 'ufficio_tecnico'),
    )

@app.route("/api/emergenze/refresh", methods=["POST"])
@role_required(['docente', 'rspp', 'dirigente', 'ufficio_tecnico'])  # Docenti e staff
def refresh_emergenze():
    """Forza il ricalcolo della cache emergenze (es. da un pulsante nella UI)."""
    _refresh_cache_in_background()
    return jsonify({"success": True, "message": "Aggiornamento cache avviato"}), 202


@app.route("/elencoStudenti/<classe>/<aula>") # ROTTA ELENCO STUDENTI
@role_required(['docente', 'rspp', 'dirigente', 'ufficio_tecnico'])  # Docenti e staff
def elencoStudenti(classe, aula):
    # Verifica che l'emergenza sia attiva
    emergenza_status = _get_emergenza_status()
    if not emergenza_status["active"]:
        return redirect(url_for('emergenze'))
    
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
            errore=None,
            emergenza_attiva=emergenza_status["active"]
        )
    except requests.HTTPError as e:
        return render_template(
            "elenco_studenti.html",
            classe=classe,
            aula=aula,
            studenti=[],
            giorno=None,
            ora=None,
            errore=f"Errore HTTP {e.response.status_code}",
            emergenza_attiva=emergenza_status["active"]
        )
    except Exception as e:
        return render_template(
            "elenco_studenti.html",
            classe=classe,
            aula=aula,
            studenti=[],
            giorno=None,
            ora=None,
            errore=f"Errore generico: {str(e)}",
            emergenza_attiva=emergenza_status["active"]
        )

@app.route("/piantina") # ROTTA PIANTINA
@sso_middleware.sso_login_required  # Accessibile a tutti i ruoli loggati
def piantina():
    return render_template("piantina.html", pdf_path="/static/piantina.pdf")

@app.route("/registri-compilati") # ROTTA REGISTRI COMPILATI
@role_required(['rspp', 'dirigente', 'ufficio_tecnico'])  # Solo staff
def registri_compilati():
    import sqlite3
    
    db_path = "runout.db"
    registri_per_classe = {}
    compilazioni_per_classe = {}
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query che recupera i registri raggruppati per classe con informazioni di stato
        query = """
        SELECT 
            c.ClasseID,
            c.Anno,
            c.Sezione,
            r.StudenteID,
            r.Nome,
            r.Cognome,
            r.Stato,
            s.NomeStato,
            s.Descrizione
        FROM Registri r
        JOIN Classi c ON r.Classe = c.ClasseID
        LEFT JOIN Stati s ON r.Stato = s.StatoID
        ORDER BY c.Anno ASC, c.Sezione ASC, r.Cognome ASC, r.Nome ASC
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT sl1.Classe, sl1.Data, sl1.Ora, sl1.Timestamp
            FROM SyncLog sl1
            WHERE sl1.Timestamp = (
                SELECT MAX(sl2.Timestamp)
                FROM SyncLog sl2
                WHERE sl2.Classe = sl1.Classe
            )
            """
        )
        sync_rows = cursor.fetchall()
        for row in sync_rows:
            data_value = row["Data"] or ''
            ora_value = row["Ora"] or ''

            if data_value:
                try:
                    data_value = datetime.strptime(data_value, "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError:
                    pass

            if ora_value:
                try:
                    ora_value = datetime.strptime(ora_value, "%H:%M:%S").strftime("%H:%M")
                except ValueError:
                    pass

            compilazioni_per_classe[str(row["Classe"]).strip().upper()] = {
                'data': data_value,
                'ora': ora_value,
                'timestamp': row["Timestamp"] or ''
            }
        
        # Raggruppa i dati per classe
        for row in rows:
            classe_key = f"{row['Anno']}{row['Sezione']}"
            
            if classe_key not in registri_per_classe:
                registri_per_classe[classe_key] = {
                    'anno': row['Anno'],
                    'sezione': row['Sezione'],
                    'studenti': [],
                    'data_compilazione': compilazioni_per_classe.get(classe_key, {}).get('data', ''),
                    'ora_compilazione': compilazioni_per_classe.get(classe_key, {}).get('ora', '')
                }
            
            studente = {
                'nome': row['Nome'] or '',
                'cognome': row['Cognome'] or '',
                'stato': row['NomeStato'] or 'Non definito',
                'stato_id': row['Stato'],
                'descrizione': row['Descrizione'] or ''
            }
            registri_per_classe[classe_key]['studenti'].append(studente)

            if not registri_per_classe[classe_key].get('data_compilazione'):
                registri_per_classe[classe_key]['data_compilazione'] = compilazioni_per_classe.get(classe_key, {}).get('data', '')
            if not registri_per_classe[classe_key].get('ora_compilazione'):
                registri_per_classe[classe_key]['ora_compilazione'] = compilazioni_per_classe.get(classe_key, {}).get('ora', '')
        
        # Ordina il dizionario per anno (crescente) e sezione (alfabetica)
        registri_per_classe = dict(sorted(registri_per_classe.items(), key=lambda x: (x[1]['anno'], x[1]['sezione'])))
        
        conn.close()
    except Exception as e:
        print(f"Errore nel recupero dei registri: {e}")
    
    return render_template("registri_compilati.html", registri_per_classe=registri_per_classe)

@app.route("/api/emergenze", methods=["POST"])
@role_required(['docente', 'rspp', 'dirigente', 'ufficio_tecnico'])  # Docenti e staff
def salva_presenze():
    """
    Salva le presenze degli studenti nel database SQLite.
    """
    import sqlite3
    
    try:
        # Controlla se l'emergenza è attiva
        emergenza_status = _get_emergenza_status()
        if not emergenza_status["active"]:
            return jsonify({
                "error": "Nessuna emergenza in corso",
                "message": "Non puoi compilare la rotta emergenze. Avvia prima un'emergenza."
            }), 400
        
        data = request.get_json()
        
        if not data or 'classe' not in data or 'presenze' not in data:
            return jsonify({"error": "Dati mancanti: classe e presenze sono obbligatori"}), 400
        
        classe = data['classe']
        presenze = data['presenze']
        studenti_attesi = data.get('studenti_attesi', [])
        stati_validi = {"PRESENTE", "ASSENTE", "DISPERSO"}
        
        # Controlla che tutti gli studenti abbiano uno stato compilato
        if not isinstance(presenze, dict) or len(presenze) == 0:
            return jsonify({"error": "Nessuno studente presente nella classe"}), 400
        
        # Verifica che il payload contenga tutti gli studenti attesi
        studenti_mancanti = []
        for nome_studente in studenti_attesi:
            if nome_studente not in presenze:
                studenti_mancanti.append(nome_studente)
            elif not presenze.get(nome_studente) or str(presenze.get(nome_studente)).strip() == "":
                studenti_mancanti.append(nome_studente)
        
        if studenti_mancanti:
            return jsonify({
                "error": "Compilazione incompleta",
                "message": f"I seguenti studenti non hanno uno stato assegnato: {', '.join(studenti_mancanti)}",
                "studenti": studenti_mancanti
            }), 400

        # Verifica che ogni stato sia uno dei valori ammessi
        stati_non_validi = []
        for nome_studente, stato in presenze.items():
            stato_norm = str(stato).strip().upper()
            if stato_norm not in stati_validi:
                stati_non_validi.append(nome_studente)

        if stati_non_validi:
            return jsonify({
                "error": "Stati non validi",
                "message": f"Gli stati di questi studenti non sono validi: {', '.join(stati_non_validi)}",
                "studenti": stati_non_validi
            }), 400
        
        # Salva nel database SQLite
        now = datetime.now()
        db_path = "runout.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            # Estrae anno e sezione dalla classe (es. "1A" -> anno=1, sezione="A")
            anno = classe[0]
            sezione = classe[1:].upper()
            
            # Verifica se la classe esiste
            cursor.execute("SELECT ClasseID FROM Classi WHERE Anno = ? AND Sezione = ?", (anno, sezione))
            classe_row = cursor.fetchone()
            
            if not classe_row:
                return jsonify({
                    "error": "Classe non trovata",
                    "message": f"La classe {classe} non esiste nel database"
                }), 400
            
            classe_id = classe_row[0]
            
            # Cancella i vecchi record per questa classe (per evitare duplicati)
            cursor.execute("DELETE FROM Registri WHERE Classe = ?", (classe_id,))
            
            # Mappa degli stati: PRESENTE=1, ASSENTE=2, DISPERSO=3
            stato_mapping = {
                "PRESENTE": 1,
                "ASSENTE": 2,
                "DISPERSO": 3
            }
            
            # Inserisci i nuovi record
            for nome_studente, stato_str in presenze.items():
                stato_id = stato_mapping.get(str(stato_str).strip().upper(), 0)
                
                # Separa cognome e nome (formato "Cognome Nome")
                parti = nome_studente.split(' ', 1)
                cognome = parti[0] if len(parti) > 0 else ""
                nome = parti[1] if len(parti) > 1 else ""
                
                cursor.execute("""
                    INSERT INTO Registri (Classe, Cognome, Nome, Stato)
                    VALUES (?, ?, ?, ?)
                """, (classe_id, cognome, nome, stato_id))
            
            # Registra il sync log
            cursor.execute("""
                INSERT INTO SyncLog (Classe, Data, Ora, Timestamp, ImportedAt)
                VALUES (?, ?, ?, ?, ?)
            """, (classe_id, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), now.isoformat(), now.isoformat()))
            
            conn.commit()
            
            return jsonify({
                "success": True,
                "message": f"Presenze salvate per la classe {classe}",
                "record": {
                    "classe": classe,
                    "data": now.strftime("%Y-%m-%d"),
                    "ora": now.strftime("%H:%M:%S"),
                    "studenti_salvati": len(presenze)
                }
            }), 200
        
        finally:
            conn.close()
        
    except Exception as e:
        return jsonify({"error": f"Errore durante il salvataggio: {str(e)}"}), 500


@app.route("/api/emergenze/avvia", methods=["POST"])
@role_required(['ufficio_tecnico'])  # Solo Ufficio Tecnico
def avvia_emergenza():
    """
    API per avviare un'emergenza. Solo RSPP può accedere.
    """
    try:
        status = _set_emergenza_status(active=True)
        return jsonify({
            "success": True,
            "message": "Emergenza avviata",
            "status": status
        }), 200
    except Exception as e:
        return jsonify({"error": f"Errore durante l'avvio dell'emergenza: {str(e)}"}), 500


@app.route("/api/emergenze/termina", methods=["POST"])
@role_required(['ufficio_tecnico'])  # Solo Ufficio Tecnico
def termina_emergenza():
    """
    API per terminare un'emergenza. Solo RSPP può accedere.
    """
    try:
        status = _set_emergenza_status(active=False)
        return jsonify({
            "success": True,
            "message": "Emergenza terminata",
            "status": status
        }), 200
    except Exception as e:
        return jsonify({"error": f"Errore durante la terminazione dell'emergenza: {str(e)}"}), 500

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
    from config import PORT
    _refresh_cache_in_background()  # Precarica i dati appena il server parte
    app.run(host='0.0.0.0', port=PORT, debug=DEBUG)