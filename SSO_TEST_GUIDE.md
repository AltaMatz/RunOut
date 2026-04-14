# 🔐 Guida Test - Flusso SSO in Production

## 📋 Sommario

Questa guida spiega come testare l'applicazione in **modalità production** con il flusso SSO completo:

```
Utente → Portale SSO (token generato)
         ↓
      JWT Firmato
         ↓
   https://app/sso/login?token=<JWT>
         ↓
   App valida JWT + Whitelist + Rate Limit
         ↓
   Crea sessione Flask
         ↓
   Redirect a /dashboard
```

---

## 🚀 Quick Start (2 minuti)

### 1. **Avvia l'App in Production**

```bash
cd c:\Users\vivox\OneDrive\Desktop\RunOut
python app.py
```

L'app ascolta su `http://localhost:3020`

### 2. **In un altro terminale, esegui i test**

```bash
cd c:\Users\vivox\OneDrive\Desktop\RunOut
python test_sso_client.py
```

Vedrai un menu interattivo. Scegli un test!

---

## ⚙️ Configurazione Production

### Setup Iniziale

**File: `.env`** - Variabili di configurazione

I parametri chiave per production sono:

```env
# ✅ Questo DEVE corrispondere al portale SSO!
SSO_MODE=production              # Attiva flusso JWT reale
SSO_JWT_SECRET=<segreto-condiviso>  # DEVE essere identico al portale!
SSO_JWT_ISSUER=sso-portal
SSO_JWT_AUDIENCE=mia-app

# Sicurezza
FLASK_SECRET_KEY=<stringa-casuale-lunga>
APP_ENV=production

# Rate limiting
MAX_SESSIONS_PER_USER=3
MAX_SESSIONS_GLOBAL=100
```

### Generare Secret Sicuri

Production richiede secret sicuri. Genera con Python:

```bash
python -c "import secrets; print('SSO_JWT_SECRET=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('FLASK_SECRET_KEY=' + secrets.token_urlsafe(32))"
```

Copia i risultati nel `.env`

---

## 🧪 Flusso Completo di Test

### Test 1: Login Singolo Utente

```
Menu → Opzione 1 (Alice)

Cosa accade:
✓ Script genera JWT valido
✓ Invia GET /sso/login?token=<JWT>
✓ App valida JWT
✓ App verifica whitelist
✓ App registra sessione (rate limit)
✓ Crea cookie session
✓ Redirect a /dashboard
```

**Output atteso:**
```
✓ JWT generato (scade tra 15 minuti)
✓ Richiesta inviata: GET /sso/login?token=...
✓ Redirect a dashboard: http://localhost:3020/dashboard
✓ Cookie di sessione ricevuto
```

### Test 2: Rate Limiting

```
Menu → Opzione 5

Cosa accade:
- Tenta 4 login simultanei dello stesso utente
- Dopo 3 sessioni, i successivi sono rifiutati
- Verifica il limite MAX_SESSIONS_PER_USER=3
```

**Output atteso:**
```
[1/4] ✓ Sessione creata (Status: 302)
[2/4] ✓ Sessione creata (Status: 302)
[3/4] ✓ Sessione creata (Status: 302)
[4/4] 🛑 Rate limit raggiunto! (Status: 429)
```

### Test 3: JWT Scaduto

```
Menu → Opzione 6

Cosa accade:
- Genera JWT con exp=now-1min
- Invia al server
- Server deve rifiutare (JWT scaduto)
```

**Output atteso:**
```
✓ JWT scaduto correttamente rifiutato (Status: 401)
```

### Test 4: JWT Errato (secret sbagliato)

```
Menu → Opzione 7

Cosa accade:
- Genera JWT con secret SBAGLIATO
- Server non può decifrare (signature non valida)
- Rifiuta accesso
```

**Output atteso:**
```
✓ JWT errato correttamente rifiutato (Status: 401)
```

---

## 🔧 Whitelist Management

### Abilitare/Disabilitare Whitelist

**File: `data/whitelist.json`**

```json
{
  "enabled": false,
  "emails": [
    "alice.rossi@itispaleocapa.it",
    "bob.bianchi@itispaleocapa.it"
  ]
}
```

- `enabled: false` → Tutti gli utenti SSO sono autorizzati ✅
- `enabled: true` → Solo emails nella lista sono autorizzate

### Test Whitelist

1. **Per permettere solo Alice:**

```json
{
  "enabled": true,
  "emails": ["alice.rossi@itispaleocapa.it"]
}
```

2. **Run Menu → Test 4 (alice + bob + ciro)**

   - Alice: ✅ Autorizzato
   - Bob: ❌ Rifiutato (non in whitelist)
   - Ciro: ❌ Rifiutato

**Output per Bob rifiutato:**
```
❌ Errore nella risposta:
   Il tuo account non è autorizzato ad accedere a questa applicazione
```

---

## 📊 Monitoraggio & Debug

### Debug Mode

Per abilitare log dettagliati, modifica `.env`:

```env
APP_ENV=development
DEBUG=True
```

Riavvia l'app per vedere:
- Validazione JWT step-by-step
- Rate limit decisions
- Whitelist checks
- Dettagli sessione

### Controllare le Sessioni Attive

Nel codice sso_middleware.py:

```python
# Stampa stats in qualunque route protetta:
stats = rate_limiter.get_stats()
print(f"Sessioni attive: {stats['total_sessions']}")
print(f"Per utente: {stats['sessions_by_user']}")
```

### Verifica JWT Validi

```bash
python -c "
import jwt
from config import SSO_JWT_SECRET, SSO_JWT_ISSUER, SSO_JWT_AUDIENCE

token = '<token-ricevuto-dal-server>'

try:
    payload = jwt.decode(
        token,
        SSO_JWT_SECRET,
        algorithms=['HS256'],
        issuer=SSO_JWT_ISSUER,
        audience=SSO_JWT_AUDIENCE
    )
    print('✓ JWT Valido!')
    print(payload)
except jwt.ExpiredSignatureError:
    print('❌ JWT Scaduto')
except jwt.InvalidSignatureError:
    print('❌ Firma Non Valida')
"
```

---

## 🌍 Migrazione a Portale SSO Reale

Quando disponi di un portale SSO reale:

### 1. Aggiorna il Secret Condiviso

Il portale SSO e questa app devono usare lo **stesso `SSO_JWT_SECRET`**.

```env
# Accordati con l'admin del portale SSO!
SSO_JWT_SECRET=<segreto-identico-portale>
SSO_JWT_AUDIENCE=mia-app
```

### 2. Cambia la Modalità

```env
SSO_MODE=production
```

### 3. Ottieni Redirect URL dal Portale

Il portale avrà bisogno di sapere dove reindirizzare dopo autenticazione:

```
https://your-domain.com/sso/login
```

Fornisci questo URL all'admin del portale.

### 4. Test con il Portale Reale

Accedi al portale → Effettua login → Dovrebbe reindirizzare alla tua app → Dashboard ✅

---

## ⚠️ Problemi Comuni

### Problema: "Token SSO mancante"

**Causa:** Non è stato passato il parametro `?token=<JWT>`

**Soluzione:**
- Verifica che il portale stia reindirizzando a `/sso/login?token=...`
- Esegui test manualmente: `python test_sso_client.py`

### Problema: "Token SSO non valido"

**Cause possibili:**
1. Secret diverso tra portale e app
2. JWT scaduto
3. JWT firmato con algoritmo diverso

**Soluzione:**
- Verifica `SSO_JWT_SECRET` in `.env`
- Verifica che `SSO_JWT_ISSUER` corrisponda
- Verifica data/ora del server (sync con NTP)

### Problema: "Account non autorizzato"

**Causa:** Email non in whitelist e `enabled: true`

**Soluzione:**
```json
{
  "enabled": false,
  "emails": []
}
```

Oppure aggiungi l'email alla lista.

### Problema: "Troppe sessioni attive"

**Causa:** Raggiunto limite MAX_SESSIONS_PER_USER

**Soluzione:**
- Aumenta il valore in `.env`: `MAX_SESSIONS_PER_USER=10`
- O chiudi altre sessioni dell'utente

---

## 📚 Architettura SSO

```
┌─────────────────────────────────────────────────────────────┐
│                    PORTALE SSO REALE                        │
│  (o script di test che simula il portale)                   │
├─────────────────────────────────────────────────────────────┤
│ 1. User clicca "Login"                                       │
│ 2. Portale autentica l'utente (LDAP/Google/Custom)          │
│ 3. Portale genera JWT:                                       │
│    - Firma con SSO_JWT_SECRET                               │
│    - Issuer = SSO_JWT_ISSUER                                │
│    - Audience = SSO_JWT_AUDIENCE                            │
│ 4. Redirect: GET /sso/login?token=<JWT>                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ↓
        ┌─────────────────────────────────────┐
        │  TUA APP - Endpoint /sso/login       │
        ├─────────────────────────────────────┤
        │ 1. Estrae token dal query string     │
        │ 2. Valida JWT:                      │
        │    - Firma (SSO_JWT_SECRET)         │
        │    - Issuer                         │
        │    - Audience                       │
        │    - Scadenza (exp)                 │
        │ 3. Estrae email dal JWT             │
        │ 4. Verifica whitelist                │
        │ 5. Registra sessione (rate limit)   │
        │ 6. Crea cookie Flask                │
        │ 7. Redirect a /dashboard            │
        └─────────────────────────────────────┘
                       │
                       ↓
        ┌─────────────────────────────────────┐
        │  UTENTE AUTENTICATO                 │
        │  - Cookie di sessione valido        │
        │  - Accesso a /dashboard             │
        └─────────────────────────────────────┘
```

---

## 🔒 Checklist Sicurezza Production

- [ ] SSO_MODE=production (non dev)
- [ ] SSO_JWT_SECRET = stringa casuale 32+ char
- [ ] FLASK_SECRET_KEY = stringa casuale 32+ char
- [ ] HTTPS abilitato (non HTTP)
- [ ] DEBUG=False
- [ ] Whitelist abilitata se necessario
- [ ] Rate limiting configurato
- [ ] Secret key sincronizzato con portale
- [ ] CORS configurato correttamente
- [ ] Logged access/errors per audit

---

## 📞 Support

Se riscontri problemi:

1. Abilita DEBUG=True e controlla i log
2. Esegui `python test_sso_client.py` per test dettagliati
3. Verifica i secret condivisi con il portale SSO
4. Controlla che i nomi di issuer/audience siano identici

Buon testing! 🚀
