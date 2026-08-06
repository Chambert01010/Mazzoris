from __future__ import annotations

import re
from decimal import Decimal

import pandas as pd
import pdfplumber

from .utils import (
    LOGGER,
    StatementProcessingError,
    _dfs_to_excel,
    _group_words_into_lines,
    _money_to_float,
    _normalize_text,
    _read_money,
)


INTERCAM_ACCOUNT_RE = re.compile(
    r"(SERVICIO EMPRESARIAL FX(?: USD)? KAPITAL)\s+([\d-]+)\s+CLABE\s+(\d+)",
    re.IGNORECASE,
)
INTERCAM_PERIOD_RE = re.compile(
    r"Periodo DEL (\d{4}-\d{2}-\d{2}) AL (\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
INTERCAM_MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")
INTERCAM_LINE_TOLERANCE = 2.0


def _required_money(text: str, pattern: str, label: str) -> Decimal:
    match = re.search(pattern, text, re.IGNORECASE)
    value = _read_money(match.group(1)) if match else None
    if value is None:
        raise StatementProcessingError(f"No se encontro {label} en el resumen Intercam.")
    return value


def parse_intercam_account_summary(text: str) -> dict | None:
    normalized = _normalize_text(text)
    account_match = INTERCAM_ACCOUNT_RE.search(normalized)
    if not account_match:
        return None

    account_text = normalized[account_match.start():]
    period_match = INTERCAM_PERIOD_RE.search(normalized)
    currency_match = re.search(r"Moneda\s+(MN|MXN|USD)\b", account_text, re.IGNORECASE)
    if not period_match or not currency_match:
        raise StatementProcessingError("El estado Intercam no contiene periodo o moneda identificable.")

    total_match = re.search(
        r"\bTotal\s+([\d,]+\.\d{2})(?:\s+(?:MN|MXN|USD))?\s+"
        r"([\d,]+\.\d{2})(?:\s+(?:MN|MXN|USD))?\s+"
        r"([\d,]+\.\d{2})(?:\s+(?:MN|MXN|USD))?",
        account_text,
        re.IGNORECASE,
    )
    if not total_match:
        raise StatementProcessingError("No se encontro la fila Total de la cuenta Intercam.")
    total_values = total_match.groups()

    currency = currency_match.group(1).upper()
    if currency == "MN":
        currency = "MXN"

    return {
        "producto": account_match.group(1),
        "cuenta": account_match.group(2),
        "clabe": account_match.group(3),
        "moneda": currency,
        "periodo_inicio": period_match.group(1),
        "periodo_fin": period_match.group(2),
        "saldo_inicial": _required_money(account_text, r"Saldo Inicial\s+([\d,]+\.\d{2})", "saldo inicial"),
        "depositos": _required_money(account_text, r"\+ Depositos\s+([\d,]+\.\d{2})", "depositos"),
        "retiros": _required_money(account_text, r"- Retiros\s+([\d,]+\.\d{2})", "retiros"),
        "saldo_final": _required_money(account_text, r"Saldo Final\s+([\d,]+\.\d{2})", "saldo final"),
        "total_depositos": _read_money(total_values[0]),
        "total_retiros": _read_money(total_values[1]),
        "total_saldo": _read_money(total_values[2]),
    }


def _intercam_amount_column_centers(words: list[dict]) -> tuple[float, float, float] | None:
    centers: dict[str, float] = {}
    for word in words:
        label = _normalize_text(word["text"]).upper()
        if label in {"DEPOSITOS", "RETIROS", "SALDO"}:
            centers[label] = (word["x0"] + word["x1"]) / 2
    if not all(label in centers for label in ("DEPOSITOS", "RETIROS", "SALDO")):
        return None
    return centers["DEPOSITOS"], centers["RETIROS"], centers["SALDO"]


def _extract_intercam_row(words: list[dict], centers: tuple[float, float, float]) -> dict | None:
    if len(words) < 4 or not re.fullmatch(r"\d{1,2}", words[0]["text"]):
        return None
    if not re.fullmatch(r"\d+", words[1]["text"]):
        return None

    amount_words = [word for word in words[2:] if INTERCAM_MONEY_RE.match(word["text"])]
    if not amount_words:
        return None

    deposit_text = None
    withdrawal_text = None
    balance_text = None
    for word in amount_words:
        word_center = (word["x0"] + word["x1"]) / 2
        column = min(enumerate(centers), key=lambda item: abs(word_center - item[1]))[0]
        if column == 0:
            deposit_text = word["text"]
        elif column == 1:
            withdrawal_text = word["text"]
        else:
            balance_text = word["text"]

    if balance_text is None or (deposit_text is None and withdrawal_text is None):
        return None

    amount_ids = {id(word) for word in amount_words}
    concept_words = [word["text"] for word in words[2:] if id(word) not in amount_ids]
    return {
        "dia": int(words[0]["text"]),
        "folio": words[1]["text"],
        "concepto_partes": [" ".join(concept_words)],
        "deposito_text": deposit_text,
        "retiro_text": withdrawal_text,
        "saldo_text": balance_text,
    }


def _is_intercam_ignored_detail_line(text: str) -> bool:
    normalized = _normalize_text(text).upper()
    return (
        not normalized
        or normalized.startswith("HOJA ")
        or normalized.startswith("ESTE DOCUMENTO")
        or normalized.startswith("ESTADO DE CUENTA")
        or normalized.startswith("PERIODO DEL")
        or normalized.startswith("NUMERO ")
        or normalized.startswith("CLIENTE ")
        or normalized.startswith("R.F.C.")
        or normalized.startswith("SUCURSAL ")
        or normalized.startswith("VERSION ")
    )


def _make_intercam_dataframes(summaries: list[dict], extracted_rows: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    movement_columns = [
        "CUENTA",
        "CLABE",
        "MONEDA",
        "MOVIMIENTO",
        "FECHA",
        "FOLIO",
        "CONCEPTO",
        "DEPOSITO",
        "RETIRO",
        "SALDO_PDF",
        "SALDO_CALCULADO",
        "DIFERENCIA_SALDO",
    ]
    movements: list[dict] = []
    summary_rows: list[dict] = []

    for summary in summaries:
        account_rows = [row for row in extracted_rows if row["cuenta"] == summary["cuenta"]]
        running_balance = summary["saldo_inicial"]
        total_deposits = Decimal("0.00")
        total_withdrawals = Decimal("0.00")

        for index, row in enumerate(account_rows, start=1):
            deposit = _read_money(row["deposito_text"]) or Decimal("0.00")
            withdrawal = _read_money(row["retiro_text"]) or Decimal("0.00")
            published_balance = _read_money(row["saldo_text"])
            total_deposits += deposit
            total_withdrawals += withdrawal
            running_balance = (running_balance + deposit - withdrawal).quantize(Decimal("0.01"))
            difference = None if published_balance is None else (published_balance - running_balance).quantize(Decimal("0.01"))
            date_value = f"{summary['periodo_inicio'][:8]}{row['dia']:02d}"
            movements.append({
                "CUENTA": summary["cuenta"],
                "CLABE": summary["clabe"],
                "MONEDA": summary["moneda"],
                "MOVIMIENTO": index,
                "FECHA": date_value,
                "FOLIO": row["folio"],
                "CONCEPTO": " ".join(part for part in row["concepto_partes"] if part).strip(),
                "DEPOSITO": _money_to_float(deposit) if deposit else None,
                "RETIRO": _money_to_float(withdrawal) if withdrawal else None,
                "SALDO_PDF": _money_to_float(published_balance),
                "SALDO_CALCULADO": _money_to_float(running_balance),
                "DIFERENCIA_SALDO": _money_to_float(difference),
            })

        summary_rows.append({
            "PERIODO_INICIO": summary["periodo_inicio"],
            "PERIODO_FIN": summary["periodo_fin"],
            "CUENTA": summary["cuenta"],
            "CLABE": summary["clabe"],
            "MONEDA": summary["moneda"],
            "SALDO_INICIAL_PDF": _money_to_float(summary["saldo_inicial"]),
            "DEPOSITOS_PDF": _money_to_float(summary["depositos"]),
            "RETIROS_PDF": _money_to_float(summary["retiros"]),
            "SALDO_FINAL_PDF": _money_to_float(summary["saldo_final"]),
            "DEPOSITOS_TOTAL_TABLA": _money_to_float(summary["total_depositos"]),
            "RETIROS_TOTAL_TABLA": _money_to_float(summary["total_retiros"]),
            "SALDO_TOTAL_TABLA": _money_to_float(summary["total_saldo"]),
            "DEPOSITOS_EXCEL": _money_to_float(total_deposits),
            "RETIROS_EXCEL": _money_to_float(total_withdrawals),
            "SALDO_FINAL_CALCULADO": _money_to_float(running_balance),
            "MOVIMIENTOS": len(account_rows),
        })

    return pd.DataFrame(movements, columns=movement_columns), pd.DataFrame(summary_rows)


def build_intercam_audit_dataframe(movements_df: pd.DataFrame, summary_df: pd.DataFrame) -> pd.DataFrame:
    checks: list[dict] = []

    def add_check(account: str, currency: str, name: str, expected, calculated, detail: str) -> None:
        missing = pd.isna(expected) or pd.isna(calculated)
        difference = None if missing else Decimal(str(expected)) - Decimal(str(calculated))
        status = "ERROR" if missing or difference != Decimal("0") else "OK"
        checks.append({
            "CUENTA": account,
            "MONEDA": currency,
            "COMPROBACION": name,
            "PDF_ESPERADO": expected,
            "EXCEL_CALCULADO": calculated,
            "DIFERENCIA": _money_to_float(difference),
            "TOLERANCIA": 0.0,
            "ESTADO": status,
            "DETALLE": detail if not missing else f"{detail} Falta un valor obligatorio.",
        })

    for _, summary in summary_df.iterrows():
        account = summary["CUENTA"]
        currency = summary["MONEDA"]
        account_movements = movements_df[movements_df["CUENTA"] == account]
        add_check(account, currency, "Depositos resumen vs total PDF", summary["DEPOSITOS_PDF"], summary["DEPOSITOS_TOTAL_TABLA"], "Los depositos publicados en ambas secciones del PDF deben coincidir.")
        add_check(account, currency, "Retiros resumen vs total PDF", summary["RETIROS_PDF"], summary["RETIROS_TOTAL_TABLA"], "Los retiros publicados en ambas secciones del PDF deben coincidir.")
        add_check(account, currency, "Saldo final resumen vs total PDF", summary["SALDO_FINAL_PDF"], summary["SALDO_TOTAL_TABLA"], "El saldo final publicado en ambas secciones del PDF debe coincidir.")
        add_check(account, currency, "Depositos PDF vs Excel", summary["DEPOSITOS_PDF"], summary["DEPOSITOS_EXCEL"], "La suma de depositos extraidos debe cuadrar a centavos.")
        add_check(account, currency, "Retiros PDF vs Excel", summary["RETIROS_PDF"], summary["RETIROS_EXCEL"], "La suma de retiros extraidos debe cuadrar a centavos.")
        add_check(account, currency, "Saldo final PDF vs Excel", summary["SALDO_FINAL_PDF"], summary["SALDO_FINAL_CALCULADO"], "El saldo final calculado debe cuadrar a centavos.")
        published_count = int(account_movements["SALDO_PDF"].notna().sum())
        matching_count = int((account_movements["DIFERENCIA_SALDO"] == 0).sum())
        add_check(account, currency, "Saldos intermedios", published_count, matching_count, "Todos los saldos publicados deben coincidir con el saldo acumulado.")
        equation = (
            Decimal(str(summary["SALDO_INICIAL_PDF"]))
            + Decimal(str(summary["DEPOSITOS_PDF"]))
            - Decimal(str(summary["RETIROS_PDF"]))
        )
        add_check(account, currency, "Ecuacion del estado", summary["SALDO_FINAL_PDF"], equation, "Saldo inicial + depositos - retiros debe ser igual al saldo final.")

    overall_status = "OK" if all(row["ESTADO"] == "OK" for row in checks) else "ERROR"
    checks.insert(0, {
        "CUENTA": "TODAS",
        "MONEDA": "MULTI",
        "COMPROBACION": "Estado general",
        "PDF_ESPERADO": "OK",
        "EXCEL_CALCULADO": overall_status,
        "DIFERENCIA": None,
        "TOLERANCIA": 0.0,
        "ESTADO": overall_status,
        "DETALLE": "Auditoria completa por cuenta y moneda.",
    })
    return pd.DataFrame(checks)


def _validate_intercam_audit(audit_df: pd.DataFrame) -> None:
    failed = audit_df[audit_df["ESTADO"] != "OK"]
    if failed.empty:
        return
    details = "; ".join(
        f"{row['CUENTA']} {row['COMPROBACION']}"
        for _, row in failed.iterrows()
        if row["COMPROBACION"] != "Estado general"
    )
    raise StatementProcessingError(f"Auditoria Intercam fallida. {details}")


def extract_intercam_data(file_obj) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    summaries: list[dict] = []
    extracted_rows: list[dict] = []
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            summary = parse_intercam_account_summary(text)
            if summary is None:
                continue
            summaries.append(summary)

            centers = None
            current_row = None
            in_detail = False
            words = sorted(
                page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False),
                key=lambda word: (word["top"], word["x0"]),
            )
            for line_words in _group_words_into_lines(words, tolerance=INTERCAM_LINE_TOLERANCE):
                line = " ".join(word["text"] for word in line_words).strip()
                normalized = _normalize_text(line).upper()
                if all(label in normalized for label in ("DIA", "FOLIO", "CONCEPTO", "DEPOSITOS", "RETIROS", "SALDO")):
                    centers = _intercam_amount_column_centers(line_words)
                    in_detail = centers is not None
                    continue
                if not in_detail:
                    continue
                if normalized.startswith("TOTAL "):
                    if current_row is not None:
                        extracted_rows.append({**current_row, "cuenta": summary["cuenta"]})
                        current_row = None
                    break

                row = _extract_intercam_row(line_words, centers)
                if row is not None:
                    if current_row is not None:
                        extracted_rows.append({**current_row, "cuenta": summary["cuenta"]})
                    current_row = row
                    continue
                if current_row is not None and not _is_intercam_ignored_detail_line(line):
                    current_row["concepto_partes"].append(line)

            if current_row is not None:
                extracted_rows.append({**current_row, "cuenta": summary["cuenta"]})

    if not summaries:
        raise StatementProcessingError("No se encontraron cuentas validas en el estado de cuenta Intercam.")
    if len({summary["cuenta"] for summary in summaries}) != len(summaries):
        raise StatementProcessingError("Se detectaron cuentas Intercam duplicadas en el PDF.")

    movements_df, summary_df = _make_intercam_dataframes(summaries, extracted_rows)
    audit_df = build_intercam_audit_dataframe(movements_df, summary_df)
    _validate_intercam_audit(audit_df)
    LOGGER.info(
        "Auditoria Intercam exitosa cuentas=%s movimientos=%s estado=OK",
        len(summary_df),
        len(movements_df),
    )
    return movements_df, summary_df, audit_df


def process_intercam(file_obj):
    movements_df, summary_df, audit_df = extract_intercam_data(file_obj)
    return _dfs_to_excel([
        ("Movimientos", movements_df),
        ("Resumen", summary_df),
        ("Auditoria", audit_df),
    ], style=True)
