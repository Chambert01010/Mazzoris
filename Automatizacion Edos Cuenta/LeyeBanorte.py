import pdfplumber
import pandas as pd
import re

# Archivo de entrada
archivo_pdf = "Periodo_ENE 2025.pdf"

movimientos = []

with pdfplumber.open(archivo_pdf) as pdf:
    for pagina in pdf.pages:
        texto = pagina.extract_text()
        if texto and "DETALLE DE MOVIMIENTOS" in texto:
            lineas = texto.split("\n")
            for linea in lineas:
                # Buscar las filas que empiezan con FECHA tipo dd-MMM-yy
                if re.match(r"\d{2}-[A-Z]{3}-\d{2}", linea):
                    partes = linea.split()

                    # Fecha siempre es la primera columna
                    fecha = partes[0]

                    # Saldo siempre es el último número
                    saldo = partes[-1].replace(",", "")

                    # Detectar si hay depósito o retiro
                    deposito = ""
                    retiro = ""
                    descripcion = " ".join(partes[1:-2])

                    # Revisamos si penúltimo valor es depósito o retiro
                    if "." in partes[-2]:  # si es un número
                        # Puede ser depósito o retiro
                        if "RECIBIDO" in descripcion or "DEPOSITO" in descripcion:
                            deposito = partes[-2].replace(",", "")
                        else:
                            retiro = partes[-2].replace(",", "")

                    movimientos.append([fecha, descripcion, deposito, retiro, saldo])

# Crear DataFrame ordenado
df = pd.DataFrame(
    movimientos, columns=["FECHA", "DESCRIPCION", "DEPOSITO", "RETIRO", "SALDO"]
)

# Guardar en Excel y TXT
df.to_excel("movimientos_banorte.xlsx", index=False)
df.to_csv("movimientos_banorte.txt", sep="\t", index=False, encoding="utf-8")

print("✅ Exportación completada: movimientos_banorte.xlsx y movimientos_banorte.txt")
