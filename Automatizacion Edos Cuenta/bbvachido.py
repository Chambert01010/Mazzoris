from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from statements.utils import extract_bbva_data, process_bbva  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: py bbvachido.py <ruta_pdf> [ruta_salida_xlsx]")
        return 1

    pdf_path = Path(sys.argv[1]).expanduser().resolve()
    if not pdf_path.exists():
        print(f"No existe el archivo: {pdf_path}")
        return 1

    output_xlsx = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else pdf_path.with_name(f"{pdf_path.stem}_bbva.xlsx")
    output_csv = output_xlsx.with_suffix(".csv")

    with pdf_path.open("rb") as pdf_file:
        movimientos_df, resumen_df = extract_bbva_data(pdf_file)

    with pdf_path.open("rb") as pdf_file:
        excel_bytes = process_bbva(pdf_file)

    output_xlsx.write_bytes(excel_bytes.getvalue())
    movimientos_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"Excel generado: {output_xlsx}")
    print(f"CSV generado: {output_csv}")

    saldo_inicial = resumen_df.loc[resumen_df["METRICA"] == "Saldo inicial", "PDF"].iloc[0]
    depositos = resumen_df.loc[resumen_df["METRICA"] == "Depositos / Abonos", "CALCULADO"].iloc[0]
    retiros = resumen_df.loc[resumen_df["METRICA"] == "Retiros / Cargos", "CALCULADO"].iloc[0]
    saldo_final = resumen_df.loc[resumen_df["METRICA"] == "Saldo final", "CALCULADO"].iloc[0]

    print(f"Saldo inicial: {saldo_inicial}")
    print(f"Depositos: {depositos}")
    print(f"Retiros: {retiros}")
    print(f"Saldo final: {saldo_final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
