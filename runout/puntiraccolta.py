import json
from openpyxl import load_workbook # type: ignore

def xlsx_to_json_by_point(puntiraccolta, output_file):
    wb = load_workbook(puntiraccolta)
    ws = wb.active

    # Intestazioni colonne (prima riga)
    col_headers = [cell.value for cell in ws[1]]

    # Intestazioni righe (prima colonna)
    row_headers = [row[0].value for row in ws.iter_rows(min_row=2, min_col=1, max_col=7)]

    # Primo passaggio: lettura normale
    raw = {}
    for r_idx, row_header in enumerate(row_headers, start=2):
        if row_header is None:
            row_header = "null"
        raw[row_header] = {}
        for c_idx, col_header in enumerate(col_headers[1:], start=2):
            cell_value = ws.cell(row=r_idx, column=c_idx).value
            if cell_value is None:
                parsed = []
            else:
                parsed = [line.strip() for line in str(cell_value).split("\n") if line.strip()]
            raw[row_header][col_header] = parsed

    # Secondo passaggio: inverti la struttura
    reordered = {}

    for piano, punti in raw.items():
        for punto, elenco in punti.items():
            if punto not in reordered:
                reordered[punto] = {}
            reordered[punto][piano] = elenco

    # Scrivi JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(reordered, f, ensure_ascii=False, indent=4)

    print(f"File JSON creato: {output_file}")


# ESEMPIO USO
if __name__ == "__main__":
    xlsx_to_json_by_point("puntiraccolta.xlsx", "puntiraccolta.json")