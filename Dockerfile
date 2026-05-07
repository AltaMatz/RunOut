# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /app

# Installa le dipendenze di build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements e installa dipendenze Python
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Installa curl per healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia dipendenze Python dal builder
COPY --from=builder /root/.local /root/.local

# Imposta il PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copia l'applicazione
COPY . .

# Crea directory per i dati se non esiste
RUN mkdir -p data

# Espone la porta (quella configurata in config.py)
EXPOSE 3020

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:3020/ || exit 1

# Comando di avvio
CMD ["python", "app.py"]
