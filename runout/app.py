from datetime import datetime
from flask import Flask, jsonify, render_template  # type: ignore
import requests #type: ignore
import os
from dotenv import load_dotenv # type: ignore
import asyncio
import httpx

app = Flask(__name__)
# carica il file .env e legge il token
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")


BASE_URL = "https://sipal.itispaleocapa.it/api/proxySipal/swagger/#"

aula = [
    # --- SEDE CENTRALE ---
    "1-5", "1-8", "1-11", "1-12", "1-14", "1-15", "1-17", "1-90", "1-91", "1-92", "1-93", "1-94", "1-95", "1-96", "LAB DIS - 1", "LAB LTO",
    "2-1", "2-2", "2-5", "2-6", "2-7", "2-12", "LAB DIS - 2",
    "3-3", "3-4", "3-5", "3-6", "3-7", "3-8", "3-9", "3-10", "3-11", "3-12", "3-13", "3-14", "3-15", "3-16", "3-17", "3-18", "3-19", "3-20",
    "4-2", "4-3",
    "BASKIN",
    # --- PALAZZINA ELETTRONICA --
    "E1-5", "E1-7", "E1-8", "E1-10",
    "E2-1", "E2-2", "E2-7", "E2-9",
    "E3-1", "E3-2", "E3-5", "E3-6", "E3-8",
    # --- PALAZZINA INFORMATICA ---
    "I1-1", "I1-2", "I1-3", "I1-6", "I1-13",
    "I2-1", "I2-2", "I2-3", "I2-6", "I2-13",
    "I3-1", "I3-2", "I3-3", "I3-6", "I3-13",
    # --- PALAZZINA MECCANICA ---
    "M1-8", "M1-11", "M1-18", "M1-23",
    "M2-1", "M2-3", "M2-4", "M2-7",
    "M3-1", "M3-3", "M3-4", "M3-5", "M3-8", 
    # --- PALAZZINA TESSILE ---
    "T1-6", "T1-7", "T1-12", "T1-13", "T1-14",
    "T2-1", "T2-2", "T2-3", "T2-9",
    "T3-1", "T3-3", "T3-4", "T3-7", "T3-8"
    # --- EDIFICIO PALESTRE ---
    "PALESTRA 1", "PALESTRA 2", "SALA PESI",
]


@app.route("/")
def home():
    return render_template("home.html")

@app.route("/api")
def api_home():
    now = datetime.now()
    giorno = now.isoweekday()
    #ora_reale = now.hour
    ora_reale = 10

    if 8 <= ora_reale <= 16:
        ora_mappata = ora_reale - 7
    else:
        ora_mappata = None

    return jsonify({
        "giorno_settimana": giorno,
        "ora_reale": f"{now.hour}:{now.minute:02d}",
        "ora_mappata": ora_mappata
    })

@app.route("/emergenze")
async def emergenze():

    now = datetime.now()
    #giorno = now.strftime("%Y-%m-%d")
    giorno = 3

    #ora_reale = now.hour
    ora_reale = 10
    if 8 <= ora_reale <= 14:
        ora = ora_reale-7
    else:
        ora = 1  # ora di default quando fuori orario

    async def fetch_classe(client, aula, token):
        url = f"https://sipal.itispaleocapa.it/api/proxySipal/v1/studenti/classe/{giorno}/{ora}/{aula}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status() # Solleva un'eccezione per errori HTTP (4xx, 5xx)
            return {aula: response.json()}
        except httpx.HTTPStatusError as e:
            return {aula: f"Errore API: {e.response.status_code}"}
        except Exception as e:
            return {aula: f"Errore generico: {str(e)}"}

    # Configurazione
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODQ2MjcxNzAsImlhdCI6MTc2Mzg5MTE3MCwiZGF0YSI6eyJ1c2VySWQiOiI2OTIyZDcyZmNmMTZlZWRkYzA2OGY3ZjciLCJlbWFpbCI6ImFsdGF2aWxsYS5tYXR0aWEuc3R1ZGVudGVAaXRpc3BhbGVvY2FwYS5pdCIsInBlcm1pc3Npb25MZXZlbCI6MTh9fQ.QAeTKUGu9FJIdPgup49XGv-fH0A1fhUELBIKe8e_Te4'" # Inserisci qui il tuo token completo
    
    # Utilizziamo un unico Client per tutte le richieste (molto più efficiente)
    async with httpx.AsyncClient() as client:
        tasks = [fetch_classe(client, a, token) for a in aula]
        
        # Esegue tutte le richieste in parallelo
        risultati = await asyncio.gather(*tasks)
        
        return render_template("emergenze.html", risultati=risultati, giorno=giorno, ora=ora)


@app.route("/piantina")
def piantina():
    return render_template("piantina.html")

@app.route("/registri-compilati")
def registri_compilati():
    return render_template("registri_compilati.html")



if __name__ == "__main__":
    app.run(debug=True)
