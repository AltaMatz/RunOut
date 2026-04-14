#!/usr/bin/env python3
"""
Test Client - Simula il Portale SSO e genera JWT validi per testare il flusso login.

Uso:
    python test_sso_client.py
    
Questo script:
1. Genera JWT firmati validi (come farebbe il portale SSO reale)
2. Invia le richieste HTTP al server della tua app
3. Verifica il flusso completo: JWT → Validazione → Whitelist → Rate Limit → Sessione
"""

import requests
import jwt
import json
import time
import sys
from datetime import datetime, timedelta
from typing import Dict, Any

# Configurazione - deve corrispondere a .env
SSO_JWT_SECRET = "cambia-questa-stringa-con-un-segreto-sicuro-IMPORTANTE"
SSO_JWT_ISSUER = "sso-portal"
SSO_JWT_AUDIENCE = "mia-app"
APP_BASE_URL = "http://localhost:3020"
SSO_PORTAL_URL = "http://localhost:5000"

# Utenti di test (simula i dati che il portale SSO genererebbe)
TEST_USERS = {
    # === STUDENTI ===
    "ciro": {
        "email": "vivo.ciro.studente@itispaleocapa.it",
        "name": "Ciro Vivo",
        "googleId": "google-ciro-11111",
        "picture": "https://example.com/ciro.jpg",
        "role_type": "student"
    },
    "mario_student": {
        "email": "mario.rossi.studente@itispaleocapa.it",
        "name": "Mario Rossi (Studente)",
        "googleId": "google-mario-22222",
        "picture": "https://example.com/mario_student.jpg",
        "role_type": "student"
    },
    # === DOCENTI ===
    "alice": {
        "email": "alice.rossi@itispaleocapa.it",
        "name": "Alice Rossi",
        "googleId": "google-alice-12345",
        "picture": "https://example.com/alice.jpg",
        "role_type": "docente"
    },
    "anna": {
        "email": "anna.bianchi@itispaleocapa.it",
        "name": "Anna Bianchi",
        "googleId": "google-anna-67890",
        "picture": "https://example.com/anna.jpg",
        "role_type": "docente"
    },
    # === RSPP ===
    "rspp": {
        "email": "rspp.responsabile@itispaleocapa.it",
        "name": "RSPP Responsabile",
        "googleId": "google-rspp-33333",
        "picture": "https://example.com/rspp.jpg",
        "role_type": "rspp"
    },
    # === DIRIGENTE ===
    "dirigente": {
        "email": "dirigente.scolastico@itispaleocapa.it",
        "name": "Preside Scolastico",
        "googleId": "google-dirigente-44444",
        "picture": "https://example.com/dirigente.jpg",
        "role_type": "dirigente"
    },
    # === UFFICIO TECNICO ===
    "tecnico": {
        "email": "tecnico.scuola@itispaleocapa.it",
        "name": "Tecnico Scuola",
        "googleId": "google-tecnico-55555",
        "picture": "https://example.com/tecnico.jpg",
        "role_type": "ufficio_tecnico"
    },
    # === UTENTE NON AUTORIZZATO ===
    "bob": {
        "email": "bob.bianchi@itispaleocapa.it",
        "name": "Bob Bianchi (Non Autorizzato)",
        "googleId": "google-bob-67890",
        "picture": "https://example.com/bob.jpg",
        "role_type": "unauthorized"
    }
}


class SSOTestClient:
    """Client che simula il portale SSO per testing."""
    
    def __init__(self, app_url: str, jwt_secret: str, jwt_issuer: str, jwt_audience: str):
        self.app_url = app_url
        self.jwt_secret = jwt_secret
        self.jwt_issuer = jwt_issuer
        self.jwt_audience = jwt_audience
        self.session = requests.Session()
        self.session.allow_redirects = False  # Intercettiamo i redirect
    
    def generate_jwt(self, user_data: Dict[str, Any], exp_minutes: int = 15) -> str:
        """Genera un JWT valido firmato (come farebbe il portale SSO)."""
        now = datetime.utcnow()
        exp = now + timedelta(minutes=exp_minutes)
        
        payload = {
            "iss": self.jwt_issuer,
            "aud": self.jwt_audience,
            "sub": user_data["email"],
            "email": user_data["email"],
            "name": user_data["name"],
            "googleId": user_data["googleId"],
            "picture": user_data["picture"],
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp())
        }
        
        token = jwt.encode(
            payload,
            self.jwt_secret,
            algorithm="HS256"
        )
        
        return token
    
    def test_login(self, user_key: str, expect_success: bool = True) -> bool:
        """
        Testa il flusso di login SSO completo per un utente.
        
        Flusso:
        1. Genera JWT per l'utente
        2. Richiede GET /sso/login?token=<JWT>
        3. Verifica redirect a /dashboard
        4. Verifica creazione cookie di sessione
        
        Returns:
            True se il test passa
        """
        if user_key not in TEST_USERS:
            print(f"❌ Utente '{user_key}' non trovato in TEST_USERS")
            return False
        
        user_data = TEST_USERS[user_key]
        print(f"\n{'='*70}")
        print(f"🔐 TEST LOGIN: {user_data['name']} ({user_data['email']})")
        print(f"{'='*70}")
        
        # Step 1: Genera JWT
        token = self.generate_jwt(user_data)
        print(f"✓ JWT generato (scade tra 15 minuti)")
        print(f"  Token (first 50 chars): {token[:50]}...")
        
        # Step 2: Effettua POST al endpoint SSO
        login_url = f"{self.app_url}/sso/login"
        params = {"token": token}
        
        try:
            response = self.session.get(login_url, params=params)
            print(f"✓ Richiesta inviata: GET {login_url}?token=...")
            print(f"  Status Code: {response.status_code}")
            print(f"  Location Header: {response.headers.get('Location', 'N/A')}")
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Errore connessione: {e}")
            print(f"   Assicurati che l'app sia in esecuzione su {self.app_url}")
            return False
        
        # Step 3: Verifica il redirect
        if response.status_code == 302:
            location = response.headers.get('Location', '')
            if 'dashboard' in location:
                print(f"✓ Redirect a dashboard: {location}")
            else:
                print(f"⚠️  Redirect non atteso: {location}")
        elif response.status_code == 200:
            if 'error' in response.text.lower():
                print(f"❌ Errore nella risposta: {response.text[:200]}")
                return False
            else:
                print(f"✓ Risposta 200 OK")
        else:
            print(f"❌ Status code inatteso: {response.status_code}")
            return False
        
        # Step 4: Verifica i cookie
        cookies = self.session.cookies.get_dict()
        if 'session' in cookies:
            print(f"✓ Cookie di sessione ricevuto: {cookies['session'][:30]}...")
            return True
        else:
            print(f"⚠️  Nessun cookie di sessione ricevuto")
            if expect_success:
                return False
            else:
                return True
    
    def test_rate_limiting(self, user_key: str, num_sessions: int = 4):
        """
        Testa il rate limiting: prova a creare più sessioni dello stesso utente.
        """
        if user_key not in TEST_USERS:
            print(f"❌ Utente '{user_key}' non trovato")
            return
        
        user_data = TEST_USERS[user_key]
        print(f"\n{'='*70}")
        print(f"⏱️  TEST RATE LIMITING: {num_sessions} sessioni simultanee")
        print(f"{'='*70}")
        
        sessions = []
        for i in range(num_sessions):
            print(f"\n[{i+1}/{num_sessions}] Tentativo login #{i+1}...")
            
            token = self.generate_jwt(user_data)
            client = requests.Session()
            client.allow_redirects = False
            
            try:
                response = client.get(f"{self.app_url}/sso/login", params={"token": token})
                
                if response.status_code == 302:
                    print(f"  ✓ Sessione creata (Status: 302)")
                    sessions.append(client)
                elif response.status_code == 429:
                    print(f"  🛑 Rate limit raggiunto! (Status: 429)")
                    print(f"  Messaggio: {response.text[:100]}...")
                    break
                else:
                    print(f"  ⚠️  Status: {response.status_code}")
                    if 'sessioni' in response.text.lower():
                        print(f"  Messaggio: {response.text[:100]}...")
                        break
            except Exception as e:
                print(f"  ❌ Errore: {e}")
                break
        
        print(f"\n✓ Test completato: {len(sessions)} sessioni create prima del limite")
    
    def print_info(self):
        """Stampa info di configurazione."""
        print(f"\n{'='*70}")
        print("📋 CONFIGURAZIONE")
        print(f"{'='*70}")
        print(f"App URL: {self.app_url}")
        print(f"SSO JWT Secret: {self.jwt_secret}")
        print(f"SSO JWT Issuer: {self.jwt_issuer}")
        print(f"SSO JWT Audience: {self.jwt_audience}")
        print()
        print("📚 UTENTI DI TEST DISPONIBILI:")
        print()
        for key, user in TEST_USERS.items():
            email = user["email"]
            role_type = user.get("role_type", "unknown")
            role_display = {
                "student": "👨‍🎓 Studente",
                "docente": "👨‍🏫 Docente",
                "rspp": "👷 RSPP",
                "dirigente": "👔 Dirigente",
                "ufficio_tecnico": "🔧 Ufficio Tecnico",
                "unauthorized": "❌ Non autorizzato"
            }.get(role_type, role_type)
            print(f"  {key:20} → {email:45} [{role_display}]")
        print()


def main():
    """Funzione principale - menu interattivo."""
    client = SSOTestClient(
        app_url=APP_BASE_URL,
        jwt_secret=SSO_JWT_SECRET,
        jwt_issuer=SSO_JWT_ISSUER,
        jwt_audience=SSO_JWT_AUDIENCE
    )
    
    client.print_info()
    
    while True:
        print(f"\n{'='*70}")
        print("MENU - QUALE TEST VUOI ESEGUIRE?")
        print(f"{'='*70}")
        print("━━ LOGIN SINGOLI ━━")
        print("1. Test login (Ciro - Studente)")
        print("2. Test login (Alice - Docente)")
        print("3. Test login (RSPP)")
        print("4. Test login (Dirigente)")
        print("5. Test login (Ufficio Tecnico)")
        print("6. Test login (Bob - NON Autorizzato)")
        print()
        print("━━ BATCH TEST ━━")
        print("7. Test login tutti gli studenti")
        print("8. Test login tutti i docenti")
        print("9. Test login tutte le categorie")
        print()
        print("━━ STRESS TEST ━━")
        print("10. Test rate limiting (3+ sessioni stesso utente)")
        print()
        print("━━ VALIDAZIONE ━━")
        print("11. Test JWT scaduto")
        print("12. Test JWT errato")
        print()
        print("0. Esci")
        print()
        
        choice = input("Scegli (0-12): ").strip()
        
        if choice == "1":
            client.test_login("ciro")
        elif choice == "2":
            client.test_login("alice")
        elif choice == "3":
            client.test_login("rspp")
        elif choice == "4":
            client.test_login("dirigente")
        elif choice == "5":
            client.test_login("tecnico")
        elif choice == "6":
            client.test_login("bob")
        elif choice == "7":
            print("\n🎓 TEST: Studenti")
            for user in ["ciro", "mario_student"]:
                if user in TEST_USERS:
                    client.test_login(user)
                    time.sleep(1)
        elif choice == "8":
            print("\n👨‍🏫 TEST: Docenti")
            for user in ["alice", "anna"]:
                if user in TEST_USERS:
                    client.test_login(user)
                    time.sleep(1)
        elif choice == "9":
            print("\n🌍 TEST: Tutti gli utenti autorizzati")
            for user in ["ciro", "mario_student", "alice", "anna", "rspp", "dirigente", "tecnico"]:
                if user in TEST_USERS:
                    client.test_login(user)
                    time.sleep(1)
        elif choice == "10":
            client.test_rate_limiting("alice", num_sessions=4)
        elif choice == "11":
            print("\n🔄 Test JWT scaduto...")
            user_data = TEST_USERS["alice"]
            # Genera JWT scaduto (-1 minuto)
            now = datetime.utcnow()
            payload = {
                "iss": client.jwt_issuer,
                "aud": client.jwt_audience,
                "sub": user_data["email"],
                "email": user_data["email"],
                "name": user_data["name"],
                "exp": int((now - timedelta(minutes=1)).timestamp())
            }
            expired_token = jwt.encode(payload, client.jwt_secret, algorithm="HS256")
            
            response = client.session.get(
                f"{client.app_url}/sso/login",
                params={"token": expired_token}
            )
            if response.status_code != 200:
                print(f"✓ JWT scaduto correttamente rifiutato (Status: {response.status_code})")
            else:
                print(f"❌ JWT scaduto accettato! Status: {response.status_code}")
        elif choice == "12":
            print("\n🔄 Test JWT errato (firmato con secret sbagliato)...")
            user_data = TEST_USERS["alice"]
            wrong_secret = "WRONG_SECRET_123456789"
            payload = {
                "iss": client.jwt_issuer,
                "aud": client.jwt_audience,
                "email": user_data["email"],
                "exp": int((datetime.utcnow() + timedelta(minutes=15)).timestamp())
            }
            wrong_token = jwt.encode(payload, wrong_secret, algorithm="HS256")
            
            response = client.session.get(
                f"{client.app_url}/sso/login",
                params={"token": wrong_token}
            )
            if response.status_code != 200 or 'error' in response.text.lower():
                print(f"✓ JWT errato correttamente rifiutato (Status: {response.status_code})")
            else:
                print(f"❌ JWT errato accettato! Status: {response.status_code}")
        elif choice == "0":
            print("\n👋 Arrivederci!")
            break
        else:
            print("❌ Scelta non valida")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrotto dall'utente")
        sys.exit(0)
