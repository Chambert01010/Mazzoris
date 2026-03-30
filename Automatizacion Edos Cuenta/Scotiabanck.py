from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from statements.utils import StatementProcessingError, extract_scotiabank_data


def main(pdf_path: str) -> int:
    source = Path(pdf_path)
    if not source.exists():
        print(f"No se encontro el PDF: {source}")
        return 1

    with source.open("rb") as handle:
        movimientos_df, resumen_df = extract_scotiabank_data(handle)

    base_name = source.with_suffix("")
    xlsx_path = base_name.with_name(f"{base_name.name}_scotiabank.xlsx")
    csv_path = base_name.with_name(f"{base_name.name}_scotiabank.csv")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        movimientos_df.to_excel(writer, index=False, sheet_name="Movimientos")
        resumen_df.to_excel(writer, index=False, sheet_name="Resumen")

    movimientos_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"Archivo procesado: {source}")
    print(f"Excel generado: {xlsx_path}")
    print(f"CSV generado: {csv_path}")
    print("\nResumen:")
    print(resumen_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: py Scotiabanck.py <ruta_pdf>")
        raise SystemExit(1)

    try:
        raise SystemExit(main(sys.argv[1]))
    except StatementProcessingError as exc:
        print(f"Error de procesamiento: {exc}")
        raise SystemExit(2)
