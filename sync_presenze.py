"""Sincronizza automaticamente il DB quando cambia presenze.json."""

import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

DB_PATH = "runout.db"
PRESENZE_FILE = "presenze.json"
POLL_SECONDS = 2

STATO_MAPPING = {
    "PRESENTE": 1,
    "ASSENTE": 2,
    "DISPERSO": 3,
}


def parse_classe_name(classe_name):
    """Converte una classe come 3IA in (3, IA)."""
    if not classe_name or len(classe_name) < 2:
        return 0, str(classe_name or "")
    try:
        return int(classe_name[0]), classe_name[1:].upper()
    except ValueError:
        return 0, classe_name.upper()


def split_full_name(full_name):
    """Primo token in Cognome, il resto in Nome."""
    clean = " ".join(str(full_name).split()).upper()
    if not clean:
        return "", ""
    parts = clean.split(" ")
    cognome = parts[0]
    nome = " ".join(parts[1:])
    return nome, cognome


def load_presenze_json():
    with open(PRESENZE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("presenze.json deve contenere una lista di record")
    return data


def ensure_support_tables(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS SyncLog (
            RecordKey TEXT PRIMARY KEY,
            Classe TEXT NOT NULL,
            Timestamp TEXT,
            Data TEXT,
            Ora TEXT,
            ImportedAt TEXT NOT NULL
        )
        """
    )
    cursor.execute("PRAGMA table_info(SyncLog)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "Data" not in existing_columns:
        cursor.execute("ALTER TABLE SyncLog ADD COLUMN Data TEXT")
    if "Ora" not in existing_columns:
        cursor.execute("ALTER TABLE SyncLog ADD COLUMN Ora TEXT")
    conn.commit()


def insert_stati_if_missing(conn):
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT OR IGNORE INTO Stati (StatoID, NomeStato, Descrizione) VALUES (?, ?, ?)",
        [
            (1, "Presente", "Studente presente"),
            (2, "Assente", "Studente assente"),
            (3, "Disperso", "Studente disperso"),
        ],
    )
    conn.commit()


def upsert_classe(conn, classe_name):
    anno, sezione = parse_classe_name(classe_name)
    cursor = conn.cursor()
    cursor.execute("SELECT ClasseID FROM Classi WHERE Anno = ? AND Sezione = ?", (anno, sezione))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("INSERT INTO Classi (Anno, Sezione) VALUES (?, ?)", (anno, sezione))
    conn.commit()
    return cursor.lastrowid


def next_student_id(conn):
    cursor = conn.cursor()
    return cursor.execute("SELECT COALESCE(MAX(StudenteID), 0) + 1 FROM Registri").fetchone()[0]


def make_record_key(record):
    payload = {
        "classe": str(record.get("classe", "")).strip().upper(),
        "timestamp": str(record.get("timestamp", "")).strip(),
        "presenze": record.get("presenze", {}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_already_imported(conn, record_key):
    cursor = conn.cursor()
    row = cursor.execute("SELECT 1 FROM SyncLog WHERE RecordKey = ?", (record_key,)).fetchone()
    return row is not None


def mark_record_imported(conn, record_key, classe, timestamp_value, data_value, ora_value):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO SyncLog (RecordKey, Classe, Timestamp, Data, Ora, ImportedAt) VALUES (?, ?, ?, ?, ?, ?)",
        (record_key, classe, timestamp_value, data_value, ora_value, datetime.now().isoformat()),
    )


def upsert_studente(conn, classe_id, nome, cognome, stato_id, new_id):
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT StudenteID
        FROM Registri
        WHERE Classe = ? AND UPPER(Cognome) = ? AND UPPER(Nome) = ?
        """,
        (classe_id, cognome.upper(), nome.upper()),
    ).fetchone()

    if row:
        cursor.execute("UPDATE Registri SET Stato = ? WHERE StudenteID = ?", (stato_id, row[0]))
        return False

    cursor.execute(
        """
        INSERT INTO Registri (StudenteID, Nome, Cognome, Classe, Stato)
        VALUES (?, ?, ?, ?, ?)
        """,
        (new_id, nome, cognome, classe_id, stato_id),
    )
    return True


def sync_once():
    records = load_presenze_json()
    ordered = sorted(records, key=lambda r: str(r.get("timestamp", "")))

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_support_tables(conn)
        insert_stati_if_missing(conn)

        # Allinea il database allo stato corrente del JSON.
        # Questo rimuove anche studenti/classi che non sono più presenti nel file.
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Registri")
        cursor.execute("DELETE FROM Classi")
        cursor.execute("DELETE FROM SyncLog")

        inserted_students = 0
        updated_students = 0
        new_records = 0
        next_id = next_student_id(conn)

        for record in ordered:
            classe = str(record.get("classe", "")).strip().upper()
            presenze = record.get("presenze", {})
            timestamp_value = str(record.get("timestamp", "")).strip()
            data_value = str(record.get("data", "")).strip()
            ora_value = str(record.get("ora", "")).strip()

            if not classe or not isinstance(presenze, dict):
                continue

            classe_id = upsert_classe(conn, classe)

            for full_name, stato in presenze.items():
                stato_norm = str(stato).upper().strip()
                if stato_norm not in STATO_MAPPING:
                    continue

                nome, cognome = split_full_name(full_name)
                was_inserted = upsert_studente(
                    conn,
                    classe_id,
                    nome,
                    cognome,
                    STATO_MAPPING[stato_norm],
                    next_id,
                )
                if was_inserted:
                    inserted_students += 1
                    next_id += 1
                else:
                    updated_students += 1

            new_records += 1

            record_key = make_record_key(record)
            mark_record_imported(conn, record_key, classe, timestamp_value, data_value, ora_value)

        conn.commit()

        print("✅ Sync eseguita")
        print(f"   Record nuovi: {new_records}")
        print(f"   Studenti inseriti: {inserted_students}")
        print(f"   Studenti aggiornati: {updated_students}")
    finally:
        conn.close()


def watch_presenze_file():
    file_path = Path(PRESENZE_FILE)
    print(f"👀 Monitoraggio attivo su {file_path.name} (CTRL+C per uscire)")

    last_mtime = None
    while True:
        try:
            if not file_path.exists():
                print("⚠️ presenze.json non trovato, attendo...")
                time.sleep(POLL_SECONDS)
                continue

            current_mtime = file_path.stat().st_mtime
            if last_mtime is None or current_mtime > last_mtime:
                print("\n🔄 File aggiornato, avvio sincronizzazione...")
                sync_once()
                last_mtime = current_mtime

            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\n👋 Monitoraggio interrotto")
            break
        except Exception as e:
            print(f"❌ Errore nel monitoraggio: {e}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        sync_once()
    else:
        watch_presenze_file()
