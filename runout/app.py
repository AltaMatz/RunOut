from datetime import datetime
import os
import json
from flask import Flask, jsonify, render_template  # type: ignore
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
    ora_reale = 12 #ora fissa per test
    if 8 <= ora_reale <= 14:
        ora = ora_reale-7
    else:
        ora = 1  #ora di default quando fuori orario

    sem = asyncio.Semaphore(20)
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
                if 'studenti' in dati_classe:
                    studenti = dati_classe['studenti']
                elif isinstance(dati_classe.get('studenti'), list):
                    studenti = dati_classe['studenti']
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

if __name__ == "__main__":
    app.run(debug=True)