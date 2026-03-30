import pdfplumber
import pandas as pd
import re

archivo_pdf = "00745013000158794758CH_FEBRERO_2021.pdf"

# --- CONFIGURACIÓN DE ZONAS (COORDENADAS X) ---
# Estas son las posiciones horizontales aproximadas en una hoja carta/A4 estándar.
# Ajustaremos esto si tus columnas están movidas, pero estos valores suelen funcionar para BBVA.
LIMITES_COLUMNAS = {
    "FECHA_MAX": 100,  # Todo texto a la izquierda de 100px es FECHA
    "DESC_MAX": 380,  # Texto entre 100 y 380 es DESCRIPCION
    "CARGO_MIN": 380,  # Números entre 380 y 480 son CARGOS
    "CARGO_MAX": 480,
    "ABONO_MIN": 480,  # Números entre 480 y 550 son ABONOS
    "ABONO_MAX": 550,
    "SALDO_MIN": 550,  # Números a la derecha de 550 son SALDOS
}

# Tolerancia vertical para agrupar palabras en la misma "línea" (3 píxeles)
TOLERANCIA_Y = 3


def limpiar_moneda(texto):
    """Convierte texto de dinero a float"""
    try:
        val = str(texto).replace(",", "").replace("$", "").strip()
        return float(val)
    except:
        return 0.0


print("--- INICIANDO EXTRACCIÓN POR COORDENADAS ---")

lineas_procesadas = []

with pdfplumber.open(archivo_pdf) as pdf:
    for num_pag, pagina in enumerate(pdf.pages):
        # 1. Extraer todas las palabras con sus coordenadas (x0, top, x1, bottom, text)
        palabras = pagina.extract_words()

        # 2. Agrupar palabras en "líneas" visuales (Clusters)
        # Si la diferencia de altura ('top') es menor a TOLERANCIA_Y, es la misma línea.
        lineas_visuales = []
        if not palabras:
            continue

        linea_actual = [palabras[0]]
        for palabra in palabras[1:]:
            ultimo_top = linea_actual[-1]["top"]
            if abs(palabra["top"] - ultimo_top) <= TOLERANCIA_Y:
                linea_actual.append(palabra)
            else:
                lineas_visuales.append(linea_actual)
                linea_actual = [palabra]
        lineas_visuales.append(linea_actual)  # Agregar la última

        # 3. Procesar cada línea visual identificada
        print(f"Procesando página {num_pag + 1} ({len(lineas_visuales)} líneas)...")

        for linea in lineas_visuales:
            # Ordenamos las palabras de izquierda a derecha por seguridad
            linea.sort(key=lambda x: x["x0"])

            fecha = ""
            descripcion_partes = []
            cargos = []
            abonos = []
            saldos = []

            # Recorremos cada palabra de la línea y la clasificamos según su posición X
            texto_linea = " ".join(
                [p["text"] for p in linea]
            )  # Texto completo para regex rápido

            # Filtro rápido: Si no parece tener fecha ni dinero, saltamos (cabeceras, pies de pág)
            es_movimiento = False
            if re.search(r"\d{2}/[A-Z]{3}", texto_linea, re.IGNORECASE):
                es_movimiento = True

            # Clasificación palabra por palabra
            for p in linea:
                x = p["x0"]  # Posición izquierda de la palabra
                texto = p["text"]

                # ZONA FECHA
                if x < LIMITES_COLUMNAS["FECHA_MAX"]:
                    # Solo tomamos si parece fecha (evita basura de margen)
                    if re.match(r"\d{2}/[A-Z]{3}", texto, re.IGNORECASE):
                        if not fecha:
                            fecha = texto  # Tomamos la primera fecha que aparezca

                # ZONA DESCRIPCIÓN
                elif (
                    x >= LIMITES_COLUMNAS["FECHA_MAX"]
                    and x < LIMITES_COLUMNAS["DESC_MAX"]
                ):
                    # Ignoramos fechas repetidas en la zona de descripción
                    if not re.match(r"\d{2}/[A-Z]{3}", texto, re.IGNORECASE):
                        descripcion_partes.append(texto)

                # ZONAS DE DINERO (CARGO, ABONO, SALDO)
                # Solo procesamos si parece número
                elif re.match(r"[\d,]+\.\d{2}", texto):
                    valor = limpiar_moneda(texto)

                    if (
                        LIMITES_COLUMNAS["CARGO_MIN"]
                        <= x
                        < LIMITES_COLUMNAS["CARGO_MAX"]
                    ):
                        cargos.append(valor)
                    elif (
                        LIMITES_COLUMNAS["ABONO_MIN"]
                        <= x
                        < LIMITES_COLUMNAS["ABONO_MAX"]
                    ):
                        abonos.append(valor)
                    elif x >= LIMITES_COLUMNAS["SALDO_MIN"]:
                        saldos.append(valor)

            # --- LÓGICA FINAL DE LA LÍNEA ---
            if fecha or descripcion_partes or cargos or abonos:
                # Si detectamos fecha, es un movimiento nuevo
                if fecha:
                    # Consolidar valores (a veces pdfplumber parte los números, tomamos el mayor o suma)
                    cargo_final = sum(cargos) if cargos else 0.0
                    abono_final = sum(abonos) if abonos else 0.0
                    saldo_final = (
                        saldos[-1] if saldos else 0.0
                    )  # El saldo suele ser el último num a la derecha

                    lineas_procesadas.append(
                        {
                            "FECHA": fecha,
                            "DESCRIPCION": " ".join(descripcion_partes),
                            "CARGO": cargo_final,
                            "ABONO": abono_final,
                            "SALDO": saldo_final,
                        }
                    )

                # Si NO hay fecha pero SÍ hay descripción y ya tenemos movimientos previos
                # significa que es texto continuado de la línea de arriba
                elif descripcion_partes and lineas_procesadas:
                    # Filtros anti-basura (ignorar encabezados que se cuelen)
                    desc_extra = " ".join(descripcion_partes)
                    if "SALDO" not in desc_extra and "BBVA" not in desc_extra:
                        lineas_procesadas[-1]["DESCRIPCION"] += " " + desc_extra

# --- GUARDAR EXCEL ---
df = pd.DataFrame(lineas_procesadas)

if not df.empty:
    archivo_salida = "BBVA_Final_Coordenadas.xlsx"
    df.to_excel(archivo_salida, index=False)
    print(f"\n¡ÉXITO TOTAL! Se extrajeron {len(df)} líneas.")
    print(f"Archivo guardado: {archivo_salida}")
    print(
        "Verifica las columnas. Si los Cargos salen en Abonos, ajusta los valores de LIMITES_COLUMNAS al inicio del script."
    )
else:
    print("No se extrajo nada. Verifica que el PDF no sea imagen.")
