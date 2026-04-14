from datetime import datetime
import os
import json
from flask import Flask, jsonify, render_template, request  # type: ignore
#implementato login ma non riporta alla dashboard(pagina di prova.)probabile errore nella cartella data
from datetime import datetime
import os
import json
from flask import Flask, jsonify, render_template, request,session  # type: ignore
import requests #type: ignore
from dotenv import load_dotenv # type: ignore
import asyncio
import httpx # type:ignore

app = Flask(__name__)
from shared_modules.sso_middleware import SSOMiddleware, WhitelistManager, RateLimiter

app = Flask(__name__)

whitelist_manager = WhitelistManager("data/whitelist.json")

rate_limiter = RateLimiter(
    max_sessions_per_user=3,
    max_sessions_global=100,
    session_ttl_seconds=28800
)

sso_middleware = SSOMiddleware(
    jwt_secret="test",
    jwt_algorithm="HS256",
    jwt_issuer="sso-portal",
    jwt_audience="mia-app",
    session_timeout=28800,
    portal_url="http://localhost:5000",
    whitelist_manager=whitelist_manager,
    rate_limiter=rate_limiter
)


load_dotenv()
API_TOKEN = os.getenv("API_TOKEN") # Carico il token dal file .env

# Carica le aule dal file JSON
with open('floors.json', 'r', encoding='utf-8') as f:
    aule_dict = json.load(f)

# Crea una lista piatta di tutte le aule
aula = []
for floor, rooms in aule_dict.items():
    aula.extend(rooms)
# print (len(aula))

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/emergenze") # ROTTA EMERGENZE
async def emergenze():

    now = datetime.now()
    #giorno = now.strftime("%Y-%m-%d")
    giorno = 4 #giorno fisso per test

    #ora_reale = now.hour
    ora_reale = 8 #ora fissa per test
    if 8 <= ora_reale <= 14:
        ora = ora_reale-7
    else:
        ora = 1  #ora di default quando fuori orario

    sem = asyncio.Semaphore(50)
    async def fetch_classe(client, aula, API_TOKEN):
        url = f"https://sipal.itispaleocapa.it/api/proxySipal/v1/studenti/classe/{giorno}/{ora}/{aula}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {API_TOKEN}",
            "User-Agent": "Mozilla/5.0"
        }
        
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return {
                "aula": aula,
                "risultato": response.json(),
                "errore": None
            }
        except httpx.HTTPStatusError as e:
            return {"aula": aula,
                    "risultato": None,
                    "errore": f"Errore HTTP {e.response.status_code}"
            }
        except Exception as e:
            return {"aula": aula, 
                    "risultato": None, 
                    "errore": f"Errore generico: {str(e)}"
            }
    
    async with httpx.AsyncClient() as client:
        tasks = [fetch_classe(client, a, API_TOKEN) for a in aula]
        risultati = await asyncio.gather(*tasks) # Esecuzione delle richieste in parallelo
        
        # Aggiungi classe a ciascun risultato e filtra quelli senza corrispondenza
        risultati_filtrati = []
        num_errors = 0
        num_with_class = 0
        for r in risultati:
            classe = r['aula']
            has_class = False
            if r['risultato'] and isinstance(r['risultato'], dict):
                if r['risultato'].get('classe'):
                    classe = r['risultato']['classe']
                    has_class = True
                elif r['risultato'].get('studenti') and len(r['risultato']['studenti']) > 0:
                    primo = r['risultato']['studenti'][0]
                    if isinstance(primo, dict) and primo.get('classe'):
                        classe = primo['classe']
                        has_class = True
            r['classe'] = classe
            if r['errore']:
                num_errors += 1
            elif has_class:
                num_with_class += 1
            if classe != r['aula']:
                risultati_filtrati.append(r)
        
        # Ordina alfanumericamente per classe
        risultati_filtrati.sort(key=lambda x: x['classe'])
        
        total_aule = len(aula)
        return render_template("emergenze.html", risultati=risultati_filtrati, giorno=giorno, ora=ora, total_aule=total_aule, num_with_class=num_with_class)

@app.route("/elencoStudenti/<classe>/<aula>") # ROTTA ELENCO STUDENTI
async def elencoStudenti(classe, aula):
    
    url = f"https://sipal.itispaleocapa.it/api/proxySipal/v1/studenti/classe/elenco/{classe}"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {API_TOKEN}",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
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
    except httpx.HTTPStatusError as e:
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
    return render_template("piantina.html", pdf_path="/static/piantina.pdf")

@app.route("/registri-compilati") # ROTTA REGISTRI COMPILATI
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
#@sso_middleware.sso_login_required
def dashboard():
    if 'user' not in session:
        return "Utente non autenticato", 401
    user = session['user']
    return f"Ciao {user['email']}"

if __name__ == "__main__":
    app.run(debug=True)