from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from statements.intercam import process_intercam
from statements.utils import StatementProcessingError


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: py Intercam.py <ruta_pdf> [ruta_salida_xlsx]")
        return 1

    pdf_path = Path(sys.argv[1]).expanduser().resolve()
    if not pdf_path.exists():
        print(f"No existe el archivo: {pdf_path}")
        return 1

    output_path = (
        Path(sys.argv[2]).expanduser().resolve()
        if len(sys.argv) > 2
        else pdf_path.with_name(f"{pdf_path.stem}_intercam.xlsx")
    )
    if not output_path.parent.exists():
        print(f"No existe la carpeta de salida: {output_path.parent}")
        return 1

    try:
        with pdf_path.open("rb") as pdf_file:
            excel_bytes = process_intercam(pdf_file)
    except StatementProcessingError as exc:
        print(f"Error de procesamiento: {exc}")
        return 2

    output_path.write_bytes(excel_bytes.getvalue())
    print(f"Excel generado: {output_path}")
    print("Auditoria Intercam: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
