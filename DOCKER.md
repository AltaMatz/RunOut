# RunOut Docker Setup

Guida per eseguire l'applicazione RunOut usando Docker Compose.

## Prerequisiti

- Docker (versione 20.10 o superiore)
- Docker Compose (versione 1.29 o superiore)

Installa da: https://www.docker.com/products/docker-desktop

## Configurazione

### 1. Configurare le variabili d'ambiente

Copia il file `.env.example` in `.env`:

```bash
cp .env.example .env
```

Modifica il file `.env` con le tue configurazioni:

```env
FLASK_SECRET_KEY=your-super-secret-key-change-this-in-production
SSO_JWT_SECRET=your-jwt-secret-from-sso-portal
SSO_JWT_ISSUER=sso-portal
SSO_JWT_AUDIENCE=mia-app
SSO_PORTAL_URL=http://sso-portal:5000  # Aggiorna con l'URL del tuo SSO
API_TOKEN=your-api-token-here
```

## Utilizzo

### Avviare l'applicazione

```bash
docker-compose up -d
```

L'applicazione sarà disponibile su: **http://localhost:3020**

### Visualizzare i log

```bash
# Log in tempo reale
docker-compose logs -f app

# Log delle ultime 50 righe
docker-compose logs --tail=50 app
```

### Stoppare l'applicazione

```bash
docker-compose down
```

### Ricostruire l'immagine Docker (dopo cambiamenti)

```bash
docker-compose build --no-cache
docker-compose up -d
```

## Gestione dei Volumi

I seguenti volumi sono mappati per la persistenza dei dati:

```
- ./data/          → /app/data              (whitelist e dati)
- ./floors.json    → /app/floors.json       (configurazione piani)
- ./presenze.json  → /app/presenze.json     (dati presenze)
- ./puntiraccolta.json → /app/puntiraccolta.json (punti raccolta)
```

## Troubleshooting

### L'applicazione non risponde

Controlla i log:

```bash
docker-compose logs app
```

### Porte in conflitto

Se la porta 3020 è già in uso, modifica nel `docker-compose.yml`:

```yaml
ports:
  - "8080:3020"  # Cambierebbe da localhost:3020 a localhost:8080
```

### Ricostruire da zero

```bash
docker-compose down -v  # Rimuove anche i volumi
docker-compose build --no-cache
docker-compose up -d
```

## Deployment in Produzione

### Checklist

- [ ] Cambia `DEBUG=false` in `docker-compose.yml`
- [ ] Genera un nuovo `FLASK_SECRET_KEY` sicuro
- [ ] Configura credenziali SSO reali
- [ ] Usa un reverse proxy (Nginx) davanti a Flask
- [ ] Configura HTTPS/SSL
- [ ] Configura i backup per il volume `./data/`
- [ ] Monitora i log dell'applicazione

### Deployment con Nginx (Reverse Proxy)

Se vuoi aggiungere un reverse proxy Nginx, aggiorna il `docker-compose.yml`:

```yaml
version: '3.8'

services:
  nginx:
    image: nginx:latest
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl/:/etc/nginx/ssl/:ro
    depends_on:
      - app
    networks:
      - runout-network

  app:
    # ... resto della configurazione
```

## Note

- L'applicazione usa la porta **3020** (configurabile in `config.py`)
- Database: l'app non usa database esterno (file-based)
- Session timeout: 8 ore (configurabile con `SESSION_LIFETIME_SECONDS`)
- Health check abilitato: verifica ogni 30 secondi
