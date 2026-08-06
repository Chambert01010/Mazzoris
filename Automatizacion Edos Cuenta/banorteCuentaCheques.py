from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from statements.utils import extract_banorte_cuenta_cheques_data, process_banorte_cuenta_cheques  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: py banorteCuentaCheques.py <ruta_pdf> [ruta_salida_xlsx]")
        return 1

    pdf_path = Path(sys.argv[1]).expanduser().resolve()
    if not pdf_path.exists():
        print(f"No existe el archivo: {pdf_path}")
        return 1

    output_xlsx = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else pdf_path.with_name(f"{pdf_path.stem}_banorteCuentaCheques.xlsx")
    output_csv = output_xlsx.with_suffix(".csv")
    output_log = output_xlsx.with_suffix(".log")

    with pdf_path.open("rb") as pdf_file:
        movimientos_df, resumen_df, auditoria_df, debug_df = extract_banorte_cuenta_cheques_data(pdf_file)

    with pdf_path.open("rb") as pdf_file:
        excel_bytes = process_banorte_cuenta_cheques(pdf_file)

    output_xlsx.write_bytes(excel_bytes.getvalue())
    movimientos_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    output_log.write_text(debug_df.to_string(index=False), encoding="utf-8")

    print(f"Excel generado: {output_xlsx}")
    print(f"CSV generado: {output_csv}")
    print(f"Log debug generado: {output_log}")
    print(resumen_df.to_string(index=False))
    print("Filas de auditoria:", len(auditoria_df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
