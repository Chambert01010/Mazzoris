import argparse
import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import pandas as pd
import pdfplumber


# =========================
# CONFIG
# =========================
DEFAULT_PDF_FILE = "downloadMobile_260311104958.pdf"
DEFAULT_OUT_FILE = "EstadoCuenta_MP_OK_visual.xlsx"
DEBUG = False

FECHA_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
DIGITS_RE = re.compile(r"\d+")
MONEY_CLEAN_RE = re.compile(r"[^\d,\.\-]")

# Límites visuales aproximados de columnas en este estado de cuenta.
# Si un día Mercado Pago cambia su layout, solo habría que ajustar esto.
DATE_X_MAX = 90
DESC_X_MIN = 90
DESC_X_MAX = 213
ID_X_MIN = 213
ID_X_MAX = 285
VALOR_X_MIN = 285
VALOR_X_MAX = 360
SALDO_X_MIN = 360
SALDO_X_MAX = 430

# Recortes verticales para ignorar encabezado y pie de página.
TOP_CUTOFF = 55
BOTTOM_CUTOFF = 610

# Ventanas verticales alrededor del "ancla" de fecha
DESC_TOP_OFFSET = -12
DESC_BOTTOM_OFFSET = 16
ID_TOP_OFFSET = -6
ID_BOTTOM_OFFSET = 8
MONEY_TOP_OFFSET = -4
MONEY_BOTTOM_OFFSET = 4


@dataclass
class Movimiento:
    fecha: str
    descripcion: str
    id_operacion: str
    monto: Optional[float]
    saldo: Optional[float]
    pagina: int
    top: float


def debug_print(*args):
    if DEBUG:
        print(*args)


def limpiar_moneda(texto: str) -> Optional[float]:
    if not texto:
        return None
    t = MONEY_CLEAN_RE.sub("", texto)
    if not t:
        return None
    try:
        return float(t.replace(",", ""))
    except Exception:
        return None


def texto_unido(words: List[Dict], line_tol: float = 3.0) -> str:
    """
    Une palabras respetando el orden visual y conservando renglones cercanos.
    """
    if not words:
        return ""

    words_ordenadas = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lineas: List[str] = []

    linea_actual: List[str] = []
    top_actual: Optional[float] = None

    for w in words_ordenadas:
        top = float(w["top"])
        txt = str(w["text"]).strip()
        if not txt:
            continue

        if top_actual is None or abs(top - top_actual) <= line_tol:
            linea_actual.append(txt)
            if top_actual is None:
                top_actual = top
            else:
                top_actual = (top_actual + top) / 2
        else:
            if linea_actual:
                lineas.append(" ".join(linea_actual).strip())
            linea_actual = [txt]
            top_actual = top

    if linea_actual:
        lineas.append(" ".join(linea_actual).strip())

    return " ".join(x for x in lineas if x)


def filtrar_palabras_utiles(page) -> List[Dict]:
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    utiles = [w for w in words if TOP_CUTOFF <= float(w["top"]) <= BOTTOM_CUTOFF]
    return utiles


def extraer_anclas_fecha(words: List[Dict]) -> List[Dict]:
    anclas = [
        w for w in words
        if float(w["x0"]) < DATE_X_MAX and FECHA_RE.match(str(w["text"]).strip())
    ]
    return sorted(anclas, key=lambda w: float(w["top"]))


def palabras_en_rango(
    words: List[Dict],
    x_min: float,
    x_max: float,
    top_min: float,
    top_max: float,
) -> List[Dict]:
    return [
        w for w in words
        if x_min <= float(w["x0"]) < x_max and top_min <= float(w["top"]) <= top_max
    ]


def construir_movimiento_desde_ancla(
    words: List[Dict],
    ancla_fecha: Dict,
    pagina_num: int,
    carry_desc: str = "",
) -> Movimiento:
    top = float(ancla_fecha["top"])
    fecha = str(ancla_fecha["text"]).strip()

    desc_words = palabras_en_rango(
        words,
        DESC_X_MIN,
        DESC_X_MAX,
        top + DESC_TOP_OFFSET,
        top + DESC_BOTTOM_OFFSET,
    )
    id_words = palabras_en_rango(
        words,
        ID_X_MIN,
        ID_X_MAX,
        top + ID_TOP_OFFSET,
        top + ID_BOTTOM_OFFSET,
    )
    valor_words = palabras_en_rango(
        words,
        VALOR_X_MIN,
        VALOR_X_MAX,
        top + MONEY_TOP_OFFSET,
        top + MONEY_BOTTOM_OFFSET,
    )
    saldo_words = palabras_en_rango(
        words,
        SALDO_X_MIN,
        SALDO_X_MAX,
        top + MONEY_TOP_OFFSET,
        top + MONEY_BOTTOM_OFFSET,
    )

    descripcion = texto_unido(desc_words)
    if carry_desc:
        descripcion = f"{carry_desc} {descripcion}".strip()

    id_operacion = "".join(DIGITS_RE.findall(texto_unido(id_words)))
    monto = limpiar_moneda(texto_unido(valor_words))
    saldo = limpiar_moneda(texto_unido(saldo_words))

    mov = Movimiento(
        fecha=fecha,
        descripcion=descripcion,
        id_operacion=id_operacion,
        monto=monto,
        saldo=saldo,
        pagina=pagina_num,
        top=top,
    )
    debug_print(
        f"[MOV] pág={pagina_num} top={top:.1f} fecha={mov.fecha} "
        f"id={mov.id_operacion} monto={mov.monto} saldo={mov.saldo} "
        f"desc={mov.descripcion!r}"
    )
    return mov


def extraer_carry_descripcion(words: List[Dict], anclas: List[Dict]) -> str:
    """
    Detecta texto colgado al final de la página dentro de la columna de descripción.
    Suele ocurrir cuando una operación se parte entre dos páginas.
    """
    if not anclas:
        return ""

    last_top = float(anclas[-1]["top"])
    trailing_desc = [
        w for w in words
        if DESC_X_MIN <= float(w["x0"]) < DESC_X_MAX and float(w["top"]) > last_top + 18
    ]

    trailing_id = [
        w for w in words
        if ID_X_MIN <= float(w["x0"]) < ID_X_MAX and float(w["top"]) > last_top + 18
    ]
    trailing_val = [
        w for w in words
        if VALOR_X_MIN <= float(w["x0"]) < VALOR_X_MAX and float(w["top"]) > last_top + 18
    ]
    trailing_saldo = [
        w for w in words
        if SALDO_X_MIN <= float(w["x0"]) < SALDO_X_MAX and float(w["top"]) > last_top + 18
    ]

    # Si después de la última fecha solo hay texto en descripción,
    # casi seguro es una operación partida de página.
    if trailing_desc and not trailing_id and not trailing_val and not trailing_saldo:
        carry = texto_unido(trailing_desc).strip()
        debug_print(f"[CARRY DETECTADO] {carry!r}")
        return carry

    return ""


def procesar_mp_visual(pdf_path: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    movimientos: List[Movimiento] = []
    auditoria: List[Dict] = []
    carry_desc = ""

    with pdfplumber.open(pdf_path) as pdf:
        for pagina_num, page in enumerate(pdf.pages, start=1):
            words = filtrar_palabras_utiles(page)
            anclas = extraer_anclas_fecha(words)

            debug_print(f"\n=== PÁGINA {pagina_num} ===")
            debug_print(f"Anclas fecha: {len(anclas)}")

            if not anclas:
                if carry_desc:
                    auditoria.append({
                        "pagina": pagina_num,
                        "tipo": "carry_sin_destino",
                        "detalle": carry_desc,
                    })
                continue

            for idx, ancla in enumerate(anclas):
                prefijo = carry_desc if idx == 0 and carry_desc else ""
                mov = construir_movimiento_desde_ancla(
                    words=words,
                    ancla_fecha=ancla,
                    pagina_num=pagina_num,
                    carry_desc=prefijo,
                )
                movimientos.append(mov)
                if prefijo:
                    debug_print(f"[CARRY APLICADO] pág={pagina_num} -> {prefijo!r}")
                    carry_desc = ""

            carry_desc = extraer_carry_descripcion(words, anclas)

    if carry_desc:
        auditoria.append({
            "pagina": "EOF",
            "tipo": "carry_final_sin_destino",
            "detalle": carry_desc,
        })

    df = pd.DataFrame([{
        "Fecha": m.fecha,
        "Descripción": m.descripcion,
        "ID Operación": m.id_operacion,
        "Monto": m.monto,
        "Saldo": m.saldo,
    } for m in movimientos])

    if not df.empty:
        df["Descripción"] = (
            df["Descripción"]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
        df["ID Operación"] = (
            df["ID Operación"]
            .fillna("")
            .astype(str)
            .str.replace(r"\.0$", "", regex=True)
            .str.strip()
        )

    audit_rows: List[Dict] = []
    for i, row in df.iterrows():
        flags = []
        if not row["Fecha"]:
            flags.append("sin_fecha")
        if not row["Descripción"]:
            flags.append("sin_descripcion")
        if not row["ID Operación"]:
            flags.append("sin_id")
        if pd.isna(row["Monto"]):
            flags.append("sin_monto")
        if pd.isna(row["Saldo"]):
            flags.append("sin_saldo")
        if flags:
            audit_rows.append({
                "fila_df": i + 2,
                "tipo": ",".join(flags),
                "detalle": str(row.to_dict()),
            })

    audit_rows.extend(auditoria)
    df_audit = pd.DataFrame(audit_rows)

    return df, df_audit


def guardar_excel(df: pd.DataFrame, df_audit: pd.DataFrame, out_file: str) -> str:
    archivo_guardado = out_file
    try:
        with pd.ExcelWriter(archivo_guardado, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="movimientos")
            if not df_audit.empty:
                df_audit.to_excel(writer, index=False, sheet_name="auditoria")
    except PermissionError:
        archivo_guardado = out_file.replace(".xlsx", "_NUEVO.xlsx")
        with pd.ExcelWriter(archivo_guardado, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="movimientos")
            if not df_audit.empty:
                df_audit.to_excel(writer, index=False, sheet_name="auditoria")
        print(f"⚠️ El archivo estaba abierto. Guardé una copia como: {archivo_guardado}")

    return archivo_guardado


def main():
    parser = argparse.ArgumentParser(
        description="Extrae movimientos de estados de cuenta de Mercado Pago usando coordenadas visuales."
    )
    parser.add_argument("pdf_file", nargs="?", default=DEFAULT_PDF_FILE, help="Ruta del PDF")
    parser.add_argument("out_file", nargs="?", default=DEFAULT_OUT_FILE, help="Ruta del Excel de salida")
    parser.add_argument("--debug", action="store_true", help="Activa logs de depuración")
    args = parser.parse_args()

    global DEBUG
    DEBUG = args.debug

    df, df_audit = procesar_mp_visual(args.pdf_file)
    archivo_guardado = guardar_excel(df, df_audit, args.out_file)

    print("===================================")
    print("✅ EXTRACCIÓN TERMINADA")
    print("===================================")
    print("Archivo:", archivo_guardado)
    print("Filas extraídas:", len(df))
    print("Filas de auditoría:", len(df_audit))


if __name__ == "__main__":
    main()
