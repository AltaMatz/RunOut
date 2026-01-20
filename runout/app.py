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

aula = [
    # --- SEDE CENTRALE ---
    "1-5", "1-8", "1-11", "1-12", "1-14", "1-15", "1-17", "1-32", "1-90", "1-91", "1-92", "1-93", "1-94", "1-95", "1-96", "LTO",
    "2-1", "2-2", "2-5", "2-6", "2-7", "2-8", "2-12",
    "3-3", "3-4", "3-5", "3-6", "3-7", "3-8", "3-9", "3-10", "3-11", "3-12", "3-13", "3-14", "3-15", "3-16", "3-17", "3-18", "3-19", "3-20",
    "4-2", "4-3", "4-11", "4-12", "4-13",
    "PBAS",
    # --- PALAZZINA ELETTRONICA --
    "E0-1", "E0-2", "E0-3", 
    "E1-5", "E1-7", "E1-8", "E1-10",
    "E2-1", "E2-2", "E2-7", "E2-9",
    "E3-1", "E3-2", "E3-5", "E3-6", "E3-8",
    # --- PALAZZINA INFORMATICA ---
    "I0-1", "I0-2", "I0-3", "I0-4", "I0-5",
    "I1-1", "I1-2", "I1-3", "I1-6", "I1-13",
    "I2-1", "I2-2", "I2-3", "I2-6", "I2-13",
    "I3-1", "I3-2", "I3-3", "I3-6", "I3-13",
    # --- PALAZZINA MECCANICA ---
    "M0-1", "M0-2", "M0-3",
    "M1-8", "M1-11", "M1-18", "M1-23",
    "M2-1", "M2-3", "M2-4", "M2-7",
    "M3-1", "M3-3", "M3-4", "M3-5", "M3-8", 
    # --- PALAZZINA TESSILE ---
    "T0-1",
    "T1-6", "T1-7", "T1-12", "T1-13", "T1-14",
    "T2-1", "T2-2", "T2-3", "T2-9",
    "T3-1", "T3-3", "T3-4", "T3-7", "T3-8",
    # --- EDIFICIO PALESTRE ---
    "PAL1", "PAL2", "PALF",
]

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/emergenze") # ROTTA EMERGENZE
async def emergenze():

    now = datetime.now()
    #giorno = now.strftime("%Y-%m-%d")
    giorno = 1 #giorno fisso per test

    #ora_reale = now.hour
    ora_reale = 9 #ora fissa per test
    if 8 <= ora_reale <= 14:
        ora = ora_reale-7
    else:
        ora = 1  #ora di default quando fuori orario

    sem = asyncio.Semaphore(5)
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
        
        return render_template("emergenze.html", risultati=risultati, giorno=giorno, ora=ora)

@app.route("/elencoStudenti/<classe>") # ROTTA ELENCO STUDENTI
async def elencoStudenti(classe):
    # La classe viene passata dall'URL quando clicchi su una card
    # Esempio: /elencoStudenti/5AIT -> classe = "5AIT"
    
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
            
            # Estraggo gli studenti dal risultato
            studenti = []
            if isinstance(dati_classe, dict):
                if 'studenti' in dati_classe:
                    studenti = dati_classe['studenti']
                elif isinstance(dati_classe.get('studenti'), list):
                    studenti = dati_classe['studenti']
            elif isinstance(dati_classe, list):
                studenti = dati_classe
            
            return render_template(
                "elenco_studenti.html",
                classe=classe,
                studenti=studenti,
                giorno=None,
                ora=None,
                errore=None
            )
    except httpx.HTTPStatusError as e:
        return render_template(
            "elenco_studenti.html",
            classe=classe,
            studenti=[],
            giorno=None,
            ora=None,
            errore=f"Errore HTTP {e.response.status_code}"
        )
    except Exception as e:
        return render_template(
            "elenco_studenti.html",
            classe=classe,
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

@app.route("/api/salva-presenze", methods=["POST"])
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