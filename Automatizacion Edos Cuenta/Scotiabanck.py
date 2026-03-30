import pdfplumber
import pandas as pd
import re


# ==========================================
# 1. FUNCIÓN DE EXTRACCIÓN (Lee el PDF)
# ==========================================
def procesar_scotiabank(ruta_pdf):
    print(f"Leyendo archivo: {ruta_pdf}...")
    datos = []

    # Configuración de años (Ajustar según el Estado de Cuenta)
    # [cite_start]Como tu PDF [cite: 10] es de Enero 2025, Diciembre pertenece a 2024.
    anio_anterior = "2024"
    anio_actual = "2025"

    # Regex para detectar inicio de movimiento (Ej: "17 DIC" o "02 ENE")
    regex_fecha = r"^(\d{2})\s(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)"

    with pdfplumber.open(ruta_pdf) as pdf:
        for i, page in enumerate(pdf.pages):

            # --- AJUSTE 1: IGNORAR PORTADA ---
            # Saltamos la página 0 (Portada) para evitar leer saldos generales como movimientos
            if i == 0:
                continue

            text = page.extract_text()
            if not text:
                continue

            lines = text.split("\n")
            temp_row = None

            for line in lines:
                # Buscamos si la línea empieza con fecha
                match = re.match(regex_fecha, line)

                if match:
                    # Si ya teníamos una fila en memoria, la guardamos
                    if temp_row:
                        datos.append(temp_row)

                    # Iniciamos nueva transacción
                    dia, mes = match.groups()

                    # Asignar año correcto
                    if mes in ["DIC", "NOV", "OCT"]:
                        anio = anio_anterior
                    else:
                        anio = anio_actual

                    fecha_completa = f"{anio}-{mes}-{dia}"

                    # Limpiamos la fecha del inicio del texto para dejar solo el concepto
                    texto_sin_fecha = line[len(match.group(0)) :].strip()

                    temp_row = {
                        "Fecha": fecha_completa,
                        "Texto_Crudo": texto_sin_fecha,  # Guardamos texto para buscar montos luego
                        "Pagina": i + 1,
                    }

                elif temp_row:
                    # Si no es fecha, es continuación del concepto anterior (multilínea)
                    temp_row["Texto_Crudo"] += " " + line

            # --- AJUSTE 2: CAPTURAR ÚLTIMO MOVIMIENTO ---
            # Guardamos la última fila que quedó en memoria al terminar la página
            if temp_row:
                datos.append(temp_row)

    return pd.DataFrame(datos)


# ==========================================
# 2. FUNCIÓN DE LIMPIEZA (Extrae Dinero con Lógica Inteligente)
# ==========================================
def limpiar_y_estructurar(df):

    def extraer_valores(texto):
        # Busca patrones de dinero: $1,234.56
        montos = re.findall(r"\$[\d,]+\.\d{2}", texto)
        # Limpiar símbolos para convertir a float
        nums = [float(m.replace("$", "").replace(",", "")) for m in montos]

        monto_mov = 0.0
        saldo_linea = 0.0

        # --- AJUSTE 3: LÓGICA INTELIGENTE DE MONTOS ---
        # [cite_start]Scotiabank [cite: 20] pone: [Monto Movimiento] [Saldo Final]
        # Si hay 2 montos -> El penúltimo es el Movimiento, el último es el Saldo.
        if len(nums) >= 2:
            monto_mov = nums[-2]
            saldo_linea = nums[-1]
        # Si hay 1 monto -> Asumimos que es el Movimiento (y que el saldo no se leyó o es 0)
        elif len(nums) == 1:
            monto_mov = nums[0]
            saldo_linea = 0.0

        return pd.Series([monto_mov, saldo_linea])

    # Aplicar la función a cada fila
    if not df.empty:
        df[["Monto_Absoluto", "Saldo_PDF"]] = df["Texto_Crudo"].apply(extraer_valores)
    return df


# ==========================================
# 3. EL TESTER (Valida Cargos vs Abonos)
# ==========================================
def aplicar_tester_contable(df, saldo_inicial):
    print("--- Ejecutando Tester Contable ---")

    saldo_calculado = saldo_inicial
    resultados = []

    for index, row in df.iterrows():
        monto = row["Monto_Absoluto"]
        saldo_pdf = row["Saldo_PDF"]
        fecha = row["Fecha"]
        concepto = row["Texto_Crudo"]

        cargo = 0.0
        abono = 0.0
        tipo = "REVISAR"  # Default si no cuadra

        # Margen de error de 10 centavos para lecturas difíciles
        margen = 0.10

        # PRUEBA 1: ¿Es Retiro? (Saldo Anterior - Monto = Nuevo Saldo)
        if abs((saldo_calculado - monto) - saldo_pdf) <= margen:
            tipo = "Retiro"
            cargo = monto
            saldo_calculado -= monto

        # PRUEBA 2: ¿Es Depósito? (Saldo Anterior + Monto = Nuevo Saldo)
        elif abs((saldo_calculado + monto) - saldo_pdf) <= margen:
            tipo = "Depósito"
            abono = monto
            saldo_calculado += monto

        # PRUEBA 3: Si el PDF no trajo saldo (0.0), usamos el texto para inferir o marcar
        elif saldo_pdf == 0.0:
            # Por defecto lo marcamos como 'Posible Retiro' para que lo valides visualmente
            tipo = "Sin Saldo PDF (Asumido Retiro)"
            cargo = monto
            saldo_calculado -= monto

        else:
            # Si no cuadra, forzamos el saldo del PDF para no arrastrar error a las siguientes filas
            tipo = "ERROR MATEMÁTICO"
            saldo_calculado = saldo_pdf

        # Limpieza visual del concepto (cortar textos muy largos)
        concepto_corto = concepto[:80] + "..." if len(concepto) > 80 else concepto

        resultados.append(
            {
                "Fecha": fecha,
                "Concepto": concepto_corto,
                "Retiro": cargo,
                "Depósito": abono,
                "Saldo_Calculado": saldo_calculado,
                "Saldo_PDF": saldo_pdf,
                "Validación": tipo,
                "Pagina": row["Pagina"],
            }
        )

    return pd.DataFrame(resultados)


# ==========================================
# 4. EJECUCIÓN
# ==========================================

# RUTA CORRECTA (Basada en tu captura de pantalla anterior)
archivo_pdf = "11 CELINA EDO DE CTA NOV.pdf"

# Saldo Inicial (Dato manual del PDF )
saldo_inicial_dic = 218457.70

try:
    # 1. Extraer
    df_raw = procesar_scotiabank(archivo_pdf)

    # 2. Limpiar
    df_clean = limpiar_y_estructurar(df_raw)

    # 3. Testear
    df_final = aplicar_tester_contable(df_clean, saldo_inicial_dic)

    # 4. Mostrar en pantalla (Primeras 10 filas)
    print("\n--- VISTA PREVIA ---")
    print(df_final[["Fecha", "Concepto", "Retiro", "Depósito", "Validación"]].head(10))

    # 5. Guardar en Excel
    nombre_excel = "Scotiabank_Procesado_Final0202.xlsx"
    df_final.to_excel(nombre_excel, index=False)
    print(f"\n¡Éxito! Archivo guardado como: {nombre_excel}")

except FileNotFoundError:
    print(f"ERROR: No encontré el archivo en la ruta:\n{archivo_pdf}")
except Exception as e:
    print(f"Ocurrió un error inesperado: {e}")
