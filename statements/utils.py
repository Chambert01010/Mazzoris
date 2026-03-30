from __future__ import annotations

import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Iterable

import pandas as pd
import pdfplumber


DATE_RE = re.compile(r"^\d{2}/[A-Z]{3}$", re.IGNORECASE)
CODE_RE = re.compile(r"^[A-Z0-9]{3}$")
MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")
BBVA_LINE_TOLERANCE = 2.5
BBVA_HEADER_MIN_TOP = 140
BBVA_FOOTER_MAX_TOP = 735
BBVA_AMOUNT_COLUMNS = {
    "cargo": (340, 395),
    "abono": (395, 465),
    "saldo_operacion": (465, 535),
    "saldo_liquidacion": (535, 999),
}
BBVA_IGNORED_CONTINUATIONS = (
    "Estimado Cliente",
    "Su Estado de Cuenta",
    "Tambien le informamos",
    "Con BBVA adelante",
    "La GAT Real",
    "BBVA MEXICO",
    "Av. Paseo de la Reforma",
)


class StatementProcessingError(Exception):
    """Raised when a statement cannot be parsed reliably."""


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip()


def _read_money(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _money_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01")))


def _clean_join(parts: Iterable[str]) -> str:
    text = " ".join(part for part in parts if part)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return text.strip(" |")


def _group_words_into_lines(words: list[dict], tolerance: float = BBVA_LINE_TOLERANCE) -> list[list[dict]]:
    lines: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if not current or abs(word["top"] - current[-1]["top"]) <= tolerance:
            current.append(word)
        else:
            lines.append(sorted(current, key=lambda item: item["x0"]))
            current = [word]
    if current:
        lines.append(sorted(current, key=lambda item: item["x0"]))
    return lines


def parse_bbva_summary_text(text: str) -> dict[str, Decimal | int | None]:
    normalized = _normalize_text(text)
    patterns = {
        "saldo_liquidacion_inicial": r"Saldo de Liquidacion Inicial\s+([\d,]+\.\d{2})",
        "saldo_operacion_inicial": r"Saldo de Operacion Inicial\s+([\d,]+\.\d{2})",
        "depositos_abonos": r"Depositos / Abonos \(\+\)\s+(\d+)\s+([\d,]+\.\d{2})",
        "retiros_cargos": r"Retiros / Cargos \(-\)\s+(\d+)\s+([\d,]+\.\d{2})",
        "saldo_final": r"Saldo Final \(\+\)\s+([\d,]+\.\d{2})",
        "saldo_operacion_final": r"Saldo de Operacion Final\s+([\d,]+\.\d{2})",
    }

    summary: dict[str, Decimal | int | None] = {
        "saldo_liquidacion_inicial": None,
        "saldo_operacion_inicial": None,
        "depositos_abonos": None,
        "depositos_abonos_count": None,
        "retiros_cargos": None,
        "retiros_cargos_count": None,
        "saldo_final": None,
        "saldo_operacion_final": None,
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, normalized)
        if not match:
            continue
        if key == "depositos_abonos":
            summary["depositos_abonos_count"] = int(match.group(1))
            summary["depositos_abonos"] = _read_money(match.group(2))
        elif key == "retiros_cargos":
            summary["retiros_cargos_count"] = int(match.group(1))
            summary["retiros_cargos"] = _read_money(match.group(2))
        else:
            summary[key] = _read_money(match.group(1))

    return summary


def _extract_bbva_summary(pdf: pdfplumber.PDF) -> dict[str, Decimal | int | None]:
    for page in pdf.pages:
        text = page.extract_text() or ""
        summary = parse_bbva_summary_text(text)
        if summary["saldo_liquidacion_inicial"] is not None and summary["saldo_final"] is not None:
            return summary
    return parse_bbva_summary_text("")


def _is_bbva_transaction_start(texts: list[str]) -> bool:
    return (
        len(texts) >= 3
        and DATE_RE.match(texts[0] or "") is not None
        and DATE_RE.match(texts[1] or "") is not None
        and CODE_RE.match(texts[2] or "") is not None
    )


def _should_ignore_bbva_line(text: str) -> bool:
    if not text:
        return True
    return any(text.startswith(prefix) for prefix in BBVA_IGNORED_CONTINUATIONS)


def _append_bbva_amount(row: dict, text: str, x0: float) -> bool:
    if not MONEY_RE.match(text):
        return False
    for field, (min_x, max_x) in BBVA_AMOUNT_COLUMNS.items():
        if min_x <= x0 < max_x:
            row[field] = text
            return True
    return False


def _finalize_bbva_data(rows: list[dict], summary: dict[str, Decimal | int | None]) -> tuple[pd.DataFrame, pd.DataFrame]:
    initial_balance = summary.get("saldo_operacion_inicial") or summary.get("saldo_liquidacion_inicial")
    running_balance = initial_balance if isinstance(initial_balance, Decimal) else None
    total_cargos = Decimal("0.00")
    total_abonos = Decimal("0.00")
    finalized_rows: list[dict] = []

    for index, row in enumerate(rows, start=1):
        cargo = _read_money(row.get("cargo")) or Decimal("0.00")
        abono = _read_money(row.get("abono")) or Decimal("0.00")
        saldo_operacion = _read_money(row.get("saldo_operacion"))
        saldo_liquidacion = _read_money(row.get("saldo_liquidacion"))
        saldo_referencia = saldo_liquidacion or saldo_operacion

        total_cargos += cargo
        total_abonos += abono

        if running_balance is not None:
            running_balance = (running_balance + abono - cargo).quantize(Decimal("0.01"))

        cuadre = None
        diferencia = None
        if running_balance is not None and saldo_referencia is not None:
            diferencia = (saldo_referencia - running_balance).quantize(Decimal("0.01"))
            cuadre = diferencia == Decimal("0.00")

        finalized_rows.append(
            {
                "MOVIMIENTO": index,
                "PAGINA": row["page"],
                "FECHA_OPERACION": row["fecha_operacion"],
                "FECHA_LIQUIDACION": row["fecha_liquidacion"],
                "CODIGO": row["codigo"],
                "DESCRIPCION": _clean_join(row["descripcion_parts"]),
                "REFERENCIA": " | ".join(part for part in row["referencia_parts"] if part),
                "CARGO": _money_to_float(cargo) if cargo else None,
                "ABONO": _money_to_float(abono) if abono else None,
                "SALDO_OPERACION_PDF": _money_to_float(saldo_operacion),
                "SALDO_LIQUIDACION_PDF": _money_to_float(saldo_liquidacion),
                "SALDO_CALCULADO": _money_to_float(running_balance),
                "CUADRA_CON_SALDO_PDF": cuadre,
                "DIFERENCIA_SALDO": _money_to_float(diferencia),
            }
        )

    parsed_final = running_balance
    expected_final = summary.get("saldo_operacion_final") or summary.get("saldo_final")
    final_difference = None
    if isinstance(parsed_final, Decimal) and isinstance(expected_final, Decimal):
        final_difference = (expected_final - parsed_final).quantize(Decimal("0.01"))

    summary_rows = [
        {"METRICA": "Saldo inicial", "PDF": _money_to_float(initial_balance), "CALCULADO": _money_to_float(initial_balance), "DIFERENCIA": 0.0 if initial_balance is not None else None},
        {"METRICA": "Depositos / Abonos", "PDF": _money_to_float(summary.get("depositos_abonos")), "CALCULADO": _money_to_float(total_abonos), "DIFERENCIA": _money_to_float((summary.get("depositos_abonos") - total_abonos) if isinstance(summary.get("depositos_abonos"), Decimal) else None)},
        {"METRICA": "Retiros / Cargos", "PDF": _money_to_float(summary.get("retiros_cargos")), "CALCULADO": _money_to_float(total_cargos), "DIFERENCIA": _money_to_float((summary.get("retiros_cargos") - total_cargos) if isinstance(summary.get("retiros_cargos"), Decimal) else None)},
        {"METRICA": "Saldo final", "PDF": _money_to_float(expected_final), "CALCULADO": _money_to_float(parsed_final), "DIFERENCIA": _money_to_float(final_difference)},
        {"METRICA": "Numero de abonos", "PDF": summary.get("depositos_abonos_count"), "CALCULADO": int(sum(1 for row in finalized_rows if row["ABONO"])), "DIFERENCIA": None},
        {"METRICA": "Numero de cargos", "PDF": summary.get("retiros_cargos_count"), "CALCULADO": int(sum(1 for row in finalized_rows if row["CARGO"])), "DIFERENCIA": None},
    ]

    return pd.DataFrame(finalized_rows), pd.DataFrame(summary_rows)


def extract_bbva_data(file_obj) -> tuple[pd.DataFrame, pd.DataFrame]:
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    with pdfplumber.open(file_obj) as pdf:
        summary = _extract_bbva_summary(pdf)
        rows: list[dict] = []
        current_row: dict | None = None

        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            if not words:
                continue

            for line in _group_words_into_lines(words):
                top = line[0]["top"]
                if top < BBVA_HEADER_MIN_TOP or top > BBVA_FOOTER_MAX_TOP:
                    continue

                texts = [word["text"] for word in line]
                line_text = " ".join(texts).strip()
                if not line_text:
                    continue

                if _is_bbva_transaction_start(texts):
                    if current_row:
                        rows.append(current_row)

                    current_row = {
                        "page": page_number,
                        "fecha_operacion": texts[0],
                        "fecha_liquidacion": texts[1],
                        "codigo": texts[2],
                        "descripcion_parts": [],
                        "referencia_parts": [],
                        "cargo": None,
                        "abono": None,
                        "saldo_operacion": None,
                        "saldo_liquidacion": None,
                    }

                    for word in line[3:]:
                        if _append_bbva_amount(current_row, word["text"], word["x0"]):
                            continue
                        if word["x0"] < 330:
                            current_row["descripcion_parts"].append(word["text"])
                        else:
                            current_row["referencia_parts"].append(word["text"])
                    continue

                if current_row is None:
                    continue

                if _should_ignore_bbva_line(line_text):
                    continue

                if line_text.startswith("No. Cuenta") or line_text.startswith("No. Cliente") or line_text.startswith("FECHA SALDO"):
                    continue

                current_row["referencia_parts"].append(line_text)

        if current_row:
            rows.append(current_row)

    if not rows:
        raise StatementProcessingError("No se encontraron movimientos válidos en el estado de cuenta BBVA.")

    movimientos_df, resumen_df = _finalize_bbva_data(rows, summary)
    return movimientos_df, resumen_df


def _dfs_to_excel(sheets: list[tuple[str, pd.DataFrame]]) -> io.BytesIO:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, dataframe in sheets:
            dataframe.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    output.seek(0)
    return output


def process_bbva(file_obj):
    movimientos_df, resumen_df = extract_bbva_data(file_obj)
    return _dfs_to_excel([
        ("Movimientos", movimientos_df),
        ("Resumen", resumen_df),
    ])


def process_banorte(file_obj):
    movimientos = []
    with pdfplumber.open(file_obj) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto and "DETALLE DE MOVIMIENTOS" in texto:
                lineas = texto.split("\n")
                for linea in lineas:
                    if re.match(r"\d{2}-[A-Z]{3}-\d{2}", linea):
                        partes = linea.split()
                        fecha = partes[0]
                        saldo = partes[-1].replace(",", "")
                        deposito = ""
                        retiro = ""
                        descripcion = " ".join(partes[1:-2])

                        if "." in partes[-2]:
                            if "RECIBIDO" in descripcion or "DEPOSITO" in descripcion:
                                deposito = partes[-2].replace(",", "")
                            else:
                                retiro = partes[-2].replace(",", "")

                        movimientos.append([fecha, descripcion, deposito, retiro, saldo])

    df = pd.DataFrame(movimientos, columns=["FECHA", "DESCRIPCION", "DEPOSITO", "RETIRO", "SALDO"])
    return _df_to_excel(df)


def process_scotiabank(file_obj):
    datos = []
    anio_anterior = "2024"
    anio_actual = "2025"
    regex_fecha = r"^(\d{2})\s(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)"

    with pdfplumber.open(file_obj) as pdf:
        for i, page in enumerate(pdf.pages):
            if i == 0:
                continue
            text = page.extract_text()
            if not text:
                continue
            lines = text.split("\n")
            temp_row = None
            for line in lines:
                match = re.match(regex_fecha, line)
                if match:
                    if temp_row:
                        datos.append(temp_row)
                    dia, mes = match.groups()
                    anio = anio_anterior if mes in ["DIC", "NOV", "OCT"] else anio_actual
                    fecha_completa = f"{anio}-{mes}-{dia}"
                    texto_sin_fecha = line[len(match.group(0)) :].strip()
                    temp_row = {
                        "Fecha": fecha_completa,
                        "Texto_Crudo": texto_sin_fecha,
                        "Pagina": i + 1,
                    }
                elif temp_row:
                    temp_row["Texto_Crudo"] += " " + line
            if temp_row:
                datos.append(temp_row)

    df = pd.DataFrame(datos)

    def extraer_valores(texto):
        montos = re.findall(r"\$[\d,]+\.\d{2}", texto)
        nums = [float(m.replace("$", "").replace(",", "")) for m in montos]
        monto_mov = 0.0
        saldo_linea = 0.0
        if len(nums) >= 2:
            monto_mov = nums[-2]
            saldo_linea = nums[-1]
        elif len(nums) == 1:
            monto_mov = nums[0]
        return pd.Series([monto_mov, saldo_linea])

    if not df.empty:
        df[["Monto_Absoluto", "Saldo_PDF"]] = df["Texto_Crudo"].apply(extraer_valores)

    return _df_to_excel(df)


def process_inbursa(file_obj):
    patron_inicio = re.compile(r"^(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\.?\s+\d{1,2}", re.IGNORECASE)
    patron_monto = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})")
    patron_saldo_inicial = re.compile(r"SALDO (?:ANTERIOR|INICIAL).*?(\d{1,3}(?:,\d{3})*\.\d{2})", re.IGNORECASE)

    def to_float(txt):
        try:
            return float(txt.replace(",", ""))
        except Exception:
            return 0.0

    movimientos = []
    transaccion_actual = {}
    saldo_anterior = 0.0

    with pdfplumber.open(file_obj) as pdf:
        texto_pag1 = pdf.pages[0].extract_text()
        match_saldo = patron_saldo_inicial.search(texto_pag1)
        if match_saldo:
            saldo_anterior = to_float(match_saldo.group(1))

        for i, pagina in enumerate(pdf.pages):
            if i == 0:
                continue
            texto = pagina.extract_text()
            if not texto:
                continue
            lineas = texto.split("\n")
            for linea in lineas:
                linea = linea.strip()
                if "SALDO ANTERIOR" in linea or "Página" in linea or "ESTADO DE CUENTA" in linea:
                    continue
                match_fecha = patron_inicio.match(linea)
                if match_fecha:
                    if transaccion_actual:
                        movimientos.append(transaccion_actual)
                    fecha = match_fecha.group(0)
                    resto = linea[len(fecha) :].strip()
                    montos_encontrados = patron_monto.findall(resto)
                    texto_desc = resto
                    for monto in montos_encontrados:
                        texto_desc = texto_desc.replace(monto, "")
                    transaccion_actual = {
                        "FECHA": fecha,
                        "DESCRIPCION": texto_desc.strip(),
                        "MONTOS_RAW": montos_encontrados,
                    }
                elif transaccion_actual:
                    transaccion_actual["DESCRIPCION"] += " " + linea
        if transaccion_actual:
            movimientos.append(transaccion_actual)

    datos_finales = []
    for mov in movimientos:
        fecha = mov["FECHA"]
        desc = mov["DESCRIPCION"]
        montos = mov["MONTOS_RAW"]
        cargo = 0.0
        abono = 0.0
        saldo_linea = 0.0

        if len(montos) == 1:
            monto_val = to_float(montos[0])
            if "DEPOSITO" in desc.upper() or "ABONO" in desc.upper() or "INTERESES" in desc.upper():
                abono = monto_val
                saldo_anterior += monto_val
            else:
                cargo = monto_val
                saldo_anterior -= monto_val
            saldo_linea = saldo_anterior
        elif len(montos) >= 2:
            saldo_linea = to_float(montos[-1])
            monto_transaccion = to_float(montos[-2])
            diferencia = round(saldo_linea - saldo_anterior, 2)
            if abs(diferencia - monto_transaccion) < 1.0 or abs(diferencia + monto_transaccion) < 1.0:
                if diferencia > 0:
                    abono = monto_transaccion
                else:
                    cargo = monto_transaccion
            else:
                if "DEPOSITO" in desc.upper() or "ABONO" in desc.upper():
                    abono = monto_transaccion
                else:
                    cargo = monto_transaccion
            saldo_anterior = saldo_linea

        str_cargo = f"{cargo:.2f}" if cargo > 0 else ""
        str_abono = f"{abono:.2f}" if abono > 0 else ""
        str_saldo = f"{saldo_linea:.2f}"
        datos_finales.append([fecha, desc, str_cargo, str_abono, str_saldo])

    df = pd.DataFrame(datos_finales, columns=["FECHA", "CONCEPTO", "CARGOS", "ABONOS", "SALDO"])
    return _df_to_excel(df)


def _df_to_excel(df):
    if df.empty:
        df = pd.DataFrame(columns=["Mensaje"])
    return _dfs_to_excel([("Resultado", df)])

