# RunOut

Applicazione Flask per la gestione delle emergenze scolastiche con autenticazione SSO, controllo accessi basato su ruoli, compilazione presenze e consultazione registri.

## Indice

- [Panoramica](#panoramica)
- [Funzionalita-principali](#funzionalita-principali)
- [Architettura](#architettura)
- [Prerequisiti](#prerequisiti)
- [Installazione](#installazione)
- [Configurazione ambiente](#configurazione-ambiente)
- [Avvio applicazione](#avvio-applicazione)
- [Ruoli e autorizzazioni](#ruoli-e-autorizzazioni)
- [Endpoint principali](#endpoint-principali)
- [Dati e persistenza](#dati-e-persistenza)
- [Script utili](#script-utili)
- [Testing SSO](#testing-sso)
- [Troubleshooting](#troubleshooting)
- [Sicurezza e produzione](#sicurezza-e-produzione)

## Panoramica

RunOut supporta il personale scolastico nella gestione operativa durante emergenze:

- recupera in tempo reale classi/studenti per aula da API esterne;
- consente ai docenti di compilare lo stato studenti (Presente, Assente, Disperso);
- salva le compilazioni in JSON e permette sincronizzazione su database SQLite;
- espone dashboard e pagine operative protette da autenticazione SSO.

## Funzionalita principali

- Login con token JWT SSO (modalita produzione) o login simulato (modalita sviluppo).
- Gestione ruoli da whitelist:
	- studenti;
	- docente;
	- rspp;
	- dirigente;
	- ufficio tecnico.
- Rate limiting delle sessioni:
	- limite sessioni per utente;
	- limite sessioni globali.
- Pagina emergenze con cache in memoria (TTL 5 minuti) e refresh manuale.
- Visualizzazione elenco studenti per classe/aula.
- Salvataggio presenze su file `presenze.json`.
- Pagina registri compilati con lettura da `runout.db`.

## Architettura

- `app.py`: entrypoint Flask, route HTTP, cache emergenze, logica applicativa.
- `config.py`: configurazione centralizzata da variabili ambiente.
- `shared_modules/sso_middleware.py`: middleware SSO, gestione sessioni, whitelist e ruoli.
- `templates/`: interfaccia web (Jinja2).
- `static/`: CSS e asset statici.
- `data/`: whitelist staff e studenti.
- `sync_presenze.py`: sincronizzazione `presenze.json` -> `runout.db`.
- `test_sso_client.py`: client di test per il flusso SSO/JWT.

## Prerequisiti

- Python 3.10+
- pip
- Ambiente virtuale consigliato (`venv`)
- Connessione alle API esterne (per funzionalita emergenze)

## Installazione

1. Clona la repository e apri la cartella progetto.
2. Crea e attiva un ambiente virtuale.
3. Installa le dipendenze.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configurazione ambiente

Crea un file `.env` nella root del progetto.

Esempio minimo:

```env
# Ambiente
APP_ENV=development

# Flask
FLASK_SECRET_KEY=change-me-in-production
SESSION_LIFETIME_SECONDS=28800

# SSO
SSO_MODE=dev
SSO_JWT_SECRET=test-secret-change-in-production
SSO_JWT_ISSUER=sso-portal
SSO_JWT_AUDIENCE=mia-app
SSO_PORTAL_URL=http://localhost:5000

# Utenti di test in dev
DEV_USER_EMAIL=vivo.ciro.studente@itispaleocapa.it
DEV_DOCENTE_EMAIL=luca.todaro@itispaleocapa.it

# Rate limiting
MAX_SESSIONS_PER_USER=3
MAX_SESSIONS_GLOBAL=100

# API esterna
API_TOKEN=your_api_token_here

# Porta applicazione (valore configurato, non usato direttamente da app.py)
PORT=3020
```

Note:

- in modalita `dev`, e possibile simulare il login senza token reale;
- in modalita `production`, il token JWT deve essere firmato con lo stesso `SSO_JWT_SECRET` del portale SSO;
- `API_TOKEN` e necessario per chiamare le API studenti.

## Avvio applicazione

Avvio diretto:

```powershell
python app.py
```

Poi apri il browser su:

- `http://127.0.0.1:5000`

Nota importante: attualmente `app.py` non usa la variabile `PORT` e avvia Flask sulla porta di default 5000.

## Ruoli e autorizzazioni

La logica ruoli e definita in `RoleManager`:

- email contenente `.studente@` -> ruolo `student` (verifica in `data/whitelist_studenti.json`);
- altri utenti -> lookup in `data/whitelist.json` in base al ruolo (`docente`, `rspp`, `dirigente`, `ufficio_tecnico`).

Se la whitelist e abilitata (`"enabled": true`), solo gli utenti presenti sono autorizzati.

## Endpoint principali

### Pubblici

- `GET /` Home
- `GET /sso/login` Login SSO (token JWT via querystring)
- `GET /dev/login-choice` Scelta utente in dev mode
- `GET /logout` Logout

### Protetti / Operativi

- `GET /dashboard` Dashboard utente autenticato
- `GET /emergenze` Vista emergenze (solo docente)
- `POST /api/emergenze/refresh` Refresh cache emergenze
- `GET /elencoStudenti/<classe>/<aula>` Elenco studenti classe
- `POST /api/emergenze` Salvataggio presenze classe
- `GET /registri-compilati` Elenco registri da SQLite (solo docente)
- `GET /piantina` Piantina edificio

## Dati e persistenza

### File JSON

- `floors.json`: mapping piani -> aule.
- `puntiraccolta.json`: mapping punti di raccolta -> aule.
- `presenze.json`: storico compilazioni presenze.
- `data/whitelist.json`: autorizzazioni staff per ruolo.
- `data/whitelist_studenti.json`: autorizzazioni studenti.

### Database SQLite

File: `runout.db`.

La pagina registri legge principalmente da:

- `Classi`
- `Registri`
- `Stati`
- `SyncLog`

## Script utili

### Generazione JSON da Excel

```powershell
python puntiraccolta.py
```

Converte `puntiraccolta.xlsx` in:

- `puntiraccolta.json`
- `floors.json`

### Sincronizzazione presenze su SQLite

Esecuzione singola:

```powershell
python sync_presenze.py --once
```

Monitor continuo del file `presenze.json`:

```powershell
python sync_presenze.py
```

## Testing SSO

Per testare il flusso JWT completo usa il client interattivo:

```powershell
python test_sso_client.py
```

Il test client simula il portale SSO e verifica:

- login validi;
- token scaduti o con firma errata;
- comportamento whitelist;
- rate limiting sessioni.

Per una guida estesa consulta `SSO_TEST_GUIDE.md`.

## Troubleshooting

- Errore 401 su login:
	- verifica `SSO_JWT_SECRET`, `SSO_JWT_ISSUER`, `SSO_JWT_AUDIENCE`.
- Errore 403 (account non autorizzato):
	- controlla `data/whitelist.json` o `data/whitelist_studenti.json`.
- Errore 429 (troppe sessioni):
	- rivedi `MAX_SESSIONS_PER_USER` e `MAX_SESSIONS_GLOBAL`.
- Pagina emergenze vuota:
	- verifica `API_TOKEN` e raggiungibilita API esterna.
- Registri non aggiornati:
	- esegui `python sync_presenze.py --once` e verifica stato di `runout.db`.

## Sicurezza e produzione

Prima di andare in produzione:

- imposta `APP_ENV=production`;
- usa secret robusti per `FLASK_SECRET_KEY` e `SSO_JWT_SECRET`;
- imposta `SSO_MODE=production`;
- abilita whitelist e limita gli account autorizzati;
- esegui l'app dietro reverse proxy HTTPS;
- evita di versionare file con dati sensibili e token reali.

## Stato progetto

Progetto attivo con focus su:

- hardening del flusso SSO in produzione;
- gestione whitelist;
- miglioramento automazioni di sincronizzazione dati.

