from datetime import datetime
import os
import json
from flask import Flask, jsonify, render_template, request  # type: ignore
import requests #type: ignore
from dotenv import load_dotenv # type: ignore
import asyncio
import httpx # type:ignore

app = Flask(__name__)
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
    ora_reale = 13 #ora fissa per test
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
                # Formato 1 (atteso in altri endpoint): {"studenti": [...]}
                if isinstance(dati_classe.get("studenti"), list):
                    studenti = dati_classe.get("studenti") or []
                # Formato 2 (quello che hai mostrato): {"3IA": ["NOME...", ...]}
                elif classe in dati_classe and isinstance(dati_classe.get(classe), list):
                    studenti = dati_classe.get(classe) or []
                else:
                    # Fallback robusto: prendo il primo valore che sia una lista
                    for v in dati_classe.values():
                        if isinstance(v, list):
                            studenti = v
                            break
            elif isinstance(dati_classe, list):
                studenti = dati_classe
            
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

if __name__ == "__main__":
    app.run(debug=True)