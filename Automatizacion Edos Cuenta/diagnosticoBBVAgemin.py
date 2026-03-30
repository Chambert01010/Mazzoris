import pdfplumber
import pandas as pd
import re

archivo_pdf = "00745013000158794758CH_MARZO_2021.pdf"
print(
    "ADVERTENCIA: Esta aplicacion tiene fallas , asegurarse si el resultado es correcto"
)
# --- CALIBRACIÓN DE PRECISIÓN (Basada en tus coordenadas) ---
LIMITES_COLUMNAS = {
    "FECHA_MAX": 90,  # Las fechas están en 15 y 50. Cortamos en 90.
    "DESC_MAX": 380,  # La descripción va hasta antes de los cargos (384).
    # ZONA CARGOS (Vimos valores en 384 y 395)
    "CARGO_MIN": 380,
    "CARGO_MAX": 415,  # Cortamos antes de que lleguen los abonos (que empiezan en 439)
    # ZONA ABONOS (Vimos valores fijos en 439)
    "ABONO_MIN": 415,
    "ABONO_MAX": 465,  # Cortamos antes de los saldos (que empiezan en 491)
    # ZONA SALDOS (Vimos valores en 491 y 563)
    "SALDO_MIN": 465,
}

TOLERANCIA_Y = 3


def limpiar_moneda(texto):
    try:
        val = str(texto).replace(",", "").replace("$", "").strip()
        return float(val)
    except:
        return 0.0


print("--- INICIANDO EXTRACCIÓN CALIBRADA ---")

lineas_procesadas = []

with pdfplumber.open(archivo_pdf) as pdf:
    for num_pag, pagina in enumerate(pdf.pages):
        palabras = pagina.extract_words()

        # Agrupar palabras en "líneas" visuales
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
        lineas_visuales.append(linea_actual)

        print(f"Procesando página {num_pag + 1}...")

        for linea in lineas_visuales:
            linea.sort(key=lambda x: x["x0"])

            fecha = ""
            descripcion_partes = []
            cargos = []
            abonos = []
            saldos = []

            # Clasificación por Coordenada X
            for p in linea:
                x = p["x0"]
                texto = p["text"]

                # FECHA
                if x < LIMITES_COLUMNAS["FECHA_MAX"]:
                    if re.match(r"\d{2}/[A-Z]{3}", texto, re.IGNORECASE):
                        if not fecha:
                            fecha = texto

                # DESCRIPCIÓN
                elif LIMITES_COLUMNAS["FECHA_MAX"] <= x < LIMITES_COLUMNAS["DESC_MAX"]:
                    # Evitar que se cuelen fechas repetidas en la descripción
                    if not re.match(r"\d{2}/[A-Z]{3}", texto, re.IGNORECASE):
                        descripcion_partes.append(texto)

                # DINERO (Solo si parece número)
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

            # --- LÓGICA DE GUARDADO ---
            if fecha:
                # Si hay varios valores en una celda, sumamos (raro en bancos, pero seguro)
                # Ojo: Saldo tomamos el último (el de la derecha), que suele ser el definitivo
                cargo_final = sum(cargos) if cargos else 0.0
                abono_final = sum(abonos) if abonos else 0.0
                saldo_final = saldos[-1] if saldos else 0.0

                lineas_procesadas.append(
                    {
                        "FECHA": fecha,
                        "DESCRIPCION": " ".join(descripcion_partes),
                        "CARGO": cargo_final,
                        "ABONO": abono_final,
                        "SALDO": saldo_final,
                    }
                )

            elif descripcion_partes and lineas_procesadas:
                # Líneas de continuación de texto
                texto_extra = " ".join(descripcion_partes)
                # Filtros de basura típicos de BBVA
                if (
                    "SALDO" not in texto_extra
                    and "BBVA" not in texto_extra
                    and "PAGINA" not in texto_extra
                ):
                    lineas_procesadas[-1]["DESCRIPCION"] += " " + texto_extra

# --- EXPORTAR ---
if not lineas_procesadas:
    print("Error: No se extrajeron líneas.")
else:
    df = pd.DataFrame(lineas_procesadas)
    archivo_salida = "BBVA_Final_Calibrado.xlsx"
    df.to_excel(archivo_salida, index=False)
    print(f"\n¡ÉXITO! Se extrajeron {len(df)} movimientos.")
    print(f"Archivo guardado: {archivo_salida}")
