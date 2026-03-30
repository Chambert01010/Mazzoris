import pdfplumber
import pandas as pd
import re

archivo_pdf = "Periodo_AGO 2025.pdf"

print("--- PROCESANDO INBURSA (EXTRACCIÓN + CLASIFICACIÓN CONTABLE) ---")

# 1. Regex para detectar Fechas y Montos
patron_inicio = re.compile(
    r"^(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\.?\s+\d{1,2}", re.IGNORECASE
)
patron_monto = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})")
patron_saldo_inicial = re.compile(
    r"SALDO (?:ANTERIOR|INICIAL).*?(\d{1,3}(?:,\d{3})*\.\d{2})", re.IGNORECASE
)


# Funciones de limpieza
def to_float(txt):
    try:
        return float(txt.replace(",", ""))
    except:
        return 0.0


# Variables
movimientos = []
transaccion_actual = {}
saldo_anterior = 0.0

with pdfplumber.open(archivo_pdf) as pdf:
    # --- PASO 1: ENCONTRAR SALDO INICIAL (Página 1) ---
    texto_pag1 = pdf.pages[0].extract_text()
    match_saldo = patron_saldo_inicial.search(texto_pag1)
    if match_saldo:
        saldo_anterior = to_float(match_saldo.group(1))
        print(f"Saldo Inicial detectado: ${saldo_anterior:,.2f}")
    else:
        print(
            "⚠️ No se detectó Saldo Inicial automático. Se asumirá 0.0 (Esto afectará la clasificación)."
        )
        # Si prefieres puedes ponerlo manual aquí:
        # saldo_anterior = 147180.92

    # --- PASO 2: EXTRAER MOVIMIENTOS ---
    for i, pagina in enumerate(pdf.pages):
        if i == 0:
            continue  # Saltar resumen

        texto = pagina.extract_text()
        if not texto:
            continue

        lineas = texto.split("\n")

        for linea in lineas:
            linea = linea.strip()
            # Filtros anti-basura
            if (
                "SALDO ANTERIOR" in linea
                or "Página" in linea
                or "ESTADO DE CUENTA" in linea
            ):
                continue

            match_fecha = patron_inicio.match(linea)

            if match_fecha:
                # Guardar anterior
                if transaccion_actual:
                    movimientos.append(transaccion_actual)

                # Nueva transacción
                fecha = match_fecha.group(0)
                resto = linea[len(fecha) :].strip()
                montos_encontrados = patron_monto.findall(resto)

                # Limpiar texto
                texto_desc = resto
                for m in montos_encontrados:
                    texto_desc = texto_desc.replace(m, "")

                transaccion_actual = {
                    "FECHA": fecha,
                    "DESCRIPCION": texto_desc.strip(),
                    "MONTOS_RAW": montos_encontrados,  # Lista temporal
                }

            elif transaccion_actual:
                # Concatenar descripción multilinea
                transaccion_actual["DESCRIPCION"] += " " + linea

    # Guardar último
    if transaccion_actual:
        movimientos.append(transaccion_actual)

print(f"Movimientos extraídos: {len(movimientos)}. Iniciando clasificación...")

# --- PASO 3: CLASIFICACIÓN LÓGICA (CARGO vs ABONO) ---
datos_finales = []

for mov in movimientos:
    fecha = mov["FECHA"]
    desc = mov["DESCRIPCION"]
    montos = mov["MONTOS_RAW"]

    cargo = 0.0
    abono = 0.0
    saldo_linea = 0.0

    # Lógica de clasificación
    if not montos:
        # Caso raro: No hay montos leídos
        pass

    elif len(montos) == 1:
        # Solo hay un número. Asumimos que es el monto del movimiento.
        # Usamos palabras clave porque no tenemos saldo para comparar.
        monto_val = to_float(montos[0])
        if (
            "DEPOSITO" in desc.upper()
            or "ABONO" in desc.upper()
            or "INTERESES" in desc.upper()
        ):
            abono = monto_val
            saldo_anterior += monto_val  # Estimamos nuevo saldo
        else:
            cargo = monto_val
            saldo_anterior -= monto_val
        saldo_linea = saldo_anterior

    else:
        # Hay 2 o más números (El último suele ser el Saldo, el anterior el Monto)
        saldo_linea = to_float(montos[-1])
        monto_transaccion = to_float(montos[-2]) if len(montos) >= 2 else 0.0

        # Matemáticas: ¿Subió o bajó el saldo?
        diferencia = round(saldo_linea - saldo_anterior, 2)

        # Verificamos si la diferencia coincide con el monto extraído (con margen de error de 0.01)
        if (
            abs(diferencia - monto_transaccion) < 1.0
            or abs(diferencia + monto_transaccion) < 1.0
        ):
            if diferencia > 0:
                abono = monto_transaccion
            else:
                cargo = monto_transaccion
        else:
            # Si la matemática falla (ej. faltó leer un movimiento previo), usamos Palabras Clave
            if "DEPOSITO" in desc.upper() or "ABONO" in desc.upper():
                abono = monto_transaccion
            else:
                cargo = (
                    monto_transaccion  # Default a Cargo (pagos, cheques, comisiones)
                )

        # Actualizamos el saldo anterior para la siguiente vuelta
        saldo_anterior = saldo_linea

    # Formatear para Excel (Cadenas vacías si es cero para que se vea limpio)
    str_cargo = f"{cargo:.2f}" if cargo > 0 else ""
    str_abono = f"{abono:.2f}" if abono > 0 else ""
    str_saldo = f"{saldo_linea:.2f}"

    datos_finales.append([fecha, desc, str_cargo, str_abono, str_saldo])

# --- PASO 4: EXPORTAR ---
df = pd.DataFrame(
    datos_finales, columns=["FECHA", "CONCEPTO", "CARGOS", "ABONOS", "SALDO"]
)
archivo_salida = "Inbursa_Clasificado_Final.xlsx"
df.to_excel(archivo_salida, index=False)

print(f"¡LISTO! Archivo limpio generado: {archivo_salida}")
