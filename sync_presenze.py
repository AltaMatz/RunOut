"""Carica nel database solo i dati presenti in presenze.json."""

import json
import sqlite3

DB_PATH = "runout.db"
PRESENZE_FILE = "presenze.json"

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
    """Usa il primo token come Cognome e il resto come Nome."""
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


def reset_tables(conn):
    """Pulisce i dati per mantenere nel DB solo quanto presente nel JSON."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Registri")
    cursor.execute("DELETE FROM Classi")
    cursor.execute("DELETE FROM Stati")
    conn.commit()


def insert_stati(conn):
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO Stati (StatoID, NomeStato, Descrizione) VALUES (?, ?, ?)",
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


def build_latest_status_by_student(records):
    """Tiene l'ultimo stato disponibile per ogni studente nella classe."""
    ordered = sorted(records, key=lambda r: r.get("timestamp", ""))
    by_student = {}

    for record in ordered:
        classe = str(record.get("classe", "")).upper().strip()
        presenze = record.get("presenze", {})
        if not classe or not isinstance(presenze, dict):
            continue

        for full_name, stato in presenze.items():
            stato_norm = str(stato).upper().strip()
            if stato_norm not in STATO_MAPPING:
                continue
            key = (classe, " ".join(str(full_name).split()).upper())
            by_student[key] = stato_norm

    return by_student


def insert_registri_from_json(conn, latest_status):
    cursor = conn.cursor()
    next_id = cursor.execute("SELECT COALESCE(MAX(StudenteID), 0) FROM Registri").fetchone()[0] + 1
    inserted = 0

    for (classe_name, full_name), stato_norm in sorted(latest_status.items()):
        classe_id = upsert_classe(conn, classe_name)
        nome, cognome = split_full_name(full_name)
        stato_id = STATO_MAPPING[stato_norm]

        cursor.execute(
            """
            INSERT INTO Registri (StudenteID, Nome, Cognome, Classe, Stato)
            VALUES (?, ?, ?, ?, ?)
            """,
            (next_id, nome, cognome, classe_id, stato_id),
        )
        next_id += 1
        inserted += 1

    conn.commit()
    return inserted


def sync_presenze_only_json():
    print("\n🔄 Caricamento DB da presenze.json (solo dati JSON)...\n")
    records = load_presenze_json()

    conn = sqlite3.connect(DB_PATH)
    try:
        reset_tables(conn)
        insert_stati(conn)

        latest_status = build_latest_status_by_student(records)
        studenti = insert_registri_from_json(conn, latest_status)

        cursor = conn.cursor()
        classi = cursor.execute("SELECT COUNT(*) FROM Classi").fetchone()[0]
        registri = cursor.execute("SELECT COUNT(*) FROM Registri").fetchone()[0]

        print("✅ Completato")
        print(f"   Record presenze letti: {len(records)}")
        print(f"   Classi inserite: {classi}")
        print(f"   Studenti inseriti: {studenti}")
        print(f"   Registri in tabella: {registri}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    sync_presenze_only_json()
