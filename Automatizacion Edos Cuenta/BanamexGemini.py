import pdfplumber
import pandas as pd
import logging
import re
import os

# Configuración de log
logging.basicConfig(level=logging.INFO, format='%(message)s')
logging.getLogger("pdfminer").setLevel(logging.WARNING)

# --- VALORES DE CONTROL EXACTOS DE TU PDF ---
CONTROL_SALDO_INICIAL = 5396.69
CONTROL_DEPOSITOS = 510474.68
CONTROL_RETIROS = 485950.89
CONTROL_SALDO_FINAL = 29920.48

def limpiar_cantidad(valor_str):
    if not valor_str or pd.isna(valor_str): return 0.0
    valor_limpio = str(valor_str).replace('$', '').replace(',', '').strip()
    if valor_limpio == '': return 0.0
    valor_limpio = re.sub(r'[^\d\.\-]', '', valor_limpio)
    if valor_limpio.endswith('-'): valor_limpio = '-' + valor_limpio[:-1]
    try: return round(float(valor_limpio), 2)
    except ValueError: return 0.0

def es_monto_contable(texto):
    """Valida estrictamente si una palabra es un monto financiero"""
    t = re.sub(r'[^\d\.\-\,]', '', texto)
    return bool(re.match(r'^\-?\d{1,3}(?:,\d{3})*\.\d{2}\-?$', t))

def agrupar_en_lineas(palabras, tolerancia_y=5):
    lineas = []
    palabras_ordenadas = sorted(palabras, key=lambda w: w['top'])
    if not palabras_ordenadas: return lineas
    
    linea_actual = [palabras_ordenadas[0]]
    for palabra in palabras_ordenadas[1:]:
        if abs(palabra['top'] - linea_actual[-1]['top']) <= tolerancia_y:
            linea_actual.append(palabra)
        else:
            lineas.append(linea_actual)
            linea_actual = [palabra]
            
    if linea_actual: lineas.append(linea_actual)
    return lineas

def procesar_estado_cuenta(pdf_path, excel_path):
    if not os.path.exists(pdf_path):
        logging.error(f"No se encontró el archivo: {pdf_path}")
        return

    logging.info("==================================================")
    logging.info(" INICIANDO EXTRACCIÓN MAESTRA (MEMORIA CONTINUA)")
    logging.info("==================================================")
    
    datos_extraidos = []
    terminar_lectura = False
    
    # ¡CLAVE! La memoria de la transacción se queda FUERA del ciclo de páginas
    # para que pueda "saltar" y continuar en la siguiente hoja.
    transaccion_actual = None 

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i in range(1, len(pdf.pages)):
                if terminar_lectura: break
                
                pagina = pdf.pages[i]
                num_pagina = i + 1
                palabras = pagina.extract_words(keep_blank_chars=False)
                lineas = agrupar_en_lineas(palabras)
                
                en_tabla = False # Reiniciamos el radar al principio de cada hoja
                
                for linea_palabras in lineas:
                    linea_palabras = sorted(linea_palabras, key=lambda w: w['x0'])
                    texto_completo = " ".join([w['text'] for w in linea_palabras]).upper()
                    
                    if "GLOSARIO" in texto_completo or "SALONES BEYOND" in texto_completo or "DISPOSICIONES EN CAJERO" in texto_completo:
                        terminar_lectura = True
                        break
                        
                    # Encendemos el radar exactamente después de leer la cabecera
                    if "FECHA" in texto_completo and "CONCEPTO" in texto_completo and "RETIROS" in texto_completo:
                        en_tabla = True
                        continue
                        
                    # Si no hemos llegado a la tabla de esta hoja, ignoramos el texto (Resúmenes, etc.)
                    if not en_tabla: continue

                    # Ignoramos la basura que se cruce dentro de la tabla
                    if "DETALLE DE OPERACIONES" in texto_completo: continue
                    if "PÁGINA" in texto_completo and "DE" in texto_completo: continue
                    if "SALDO ANTERIOR" in texto_completo: continue
                    if "SALVO BUEN COBRO" in texto_completo: continue

                    fila_dict = {"FECHA": [], "CONCEPTO": [], "RETIROS": [], "DEPÓSITOS": [], "SALDO": []}
                    
                    for w in linea_palabras:
                        texto = w['text'].strip()
                        x_center = (w['x0'] + w['x1']) / 2 
                        
                        es_monto = es_monto_contable(texto)
                        
                        # Asignación segura basada en centro de gravedad
                        if es_monto and x_center >= 330:
                            if x_center < 425:
                                fila_dict["RETIROS"].append(texto)
                            elif x_center < 515:
                                fila_dict["DEPÓSITOS"].append(texto)
                            else:
                                fila_dict["SALDO"].append(texto)
                        else:
                            if w['x0'] < 80:
                                fila_dict["FECHA"].append(texto)
                            else:
                                fila_dict["CONCEPTO"].append(texto)
                        
                    fecha = " ".join(fila_dict["FECHA"]).strip()
                    concepto = " ".join(fila_dict["CONCEPTO"]).strip()
                    retiro = " ".join(fila_dict["RETIROS"]).strip()
                    deposito = " ".join(fila_dict["DEPÓSITOS"]).strip()
                    saldo = " ".join(fila_dict["SALDO"]).strip()
                    
                    if not any([fecha, concepto, retiro, deposito, saldo]): continue

                    es_nueva_fecha = bool(re.match(r"^\d{2}\s+[a-zA-Z]{3}", fecha))
                    
                    if es_nueva_fecha:
                        if transaccion_actual: datos_extraidos.append(transaccion_actual)
                        transaccion_actual = {
                            "PÁGINA": num_pagina,
                            "FECHA": fecha, 
                            "CONCEPTO": concepto, 
                            "RETIROS": limpiar_cantidad(retiro), 
                            "DEPÓSITOS": limpiar_cantidad(deposito), 
                            "SALDO": limpiar_cantidad(saldo)
                        }
                    elif transaccion_actual:
                        tiene_nuevo_monto = bool(retiro or deposito)
                        
                        if tiene_nuevo_monto and (transaccion_actual["RETIROS"] != 0.0 or transaccion_actual["DEPÓSITOS"] != 0.0):
                            # Nace una sub-transacción
                            datos_extraidos.append(transaccion_actual)
                            transaccion_actual = {
                                "PÁGINA": num_pagina,
                                "FECHA": transaccion_actual["FECHA"], 
                                "CONCEPTO": concepto, 
                                "RETIROS": limpiar_cantidad(retiro), 
                                "DEPÓSITOS": limpiar_cantidad(deposito), 
                                "SALDO": limpiar_cantidad(saldo)
                            }
                        else:
                            # Se añade a la fila actual
                            if concepto: transaccion_actual["CONCEPTO"] += f" {concepto}"
                            if retiro and transaccion_actual["RETIROS"] == 0.0: transaccion_actual["RETIROS"] = limpiar_cantidad(retiro)
                            if deposito and transaccion_actual["DEPÓSITOS"] == 0.0: transaccion_actual["DEPÓSITOS"] = limpiar_cantidad(deposito)
                            if saldo: transaccion_actual["SALDO"] = limpiar_cantidad(saldo)

        # Al terminar de leer todas las 37 páginas, guardamos el remanente
        if transaccion_actual:
            datos_extraidos.append(transaccion_actual)

    except Exception as e:
        logging.error(f"Error procesando PDF: {e}", exc_info=True)

    # --- MOTOR DE CUADRE CONTABLE ---
    logging.info("\n==================================================")
    logging.info(" REPORTE DE CUADRE ARITMÉTICO DETALLADO")
    logging.info("==================================================")
    
    saldo_calculado = CONTROL_SALDO_INICIAL
    suma_retiros = 0.0
    suma_depositos = 0.0
    descuadres_encontrados = 0

    for i, fila in enumerate(datos_extraidos):
        retiro = fila['RETIROS']
        deposito = fila['DEPÓSITOS']
        saldo_leido = fila['SALDO']
        
        suma_retiros += retiro
        suma_depositos += deposito
        saldo_calculado = round(saldo_calculado - retiro + deposito, 2)
        
        if saldo_leido != 0.0:
            diferencia = round(abs(saldo_calculado - saldo_leido), 2)
            if diferencia > 0.01:
                logging.warning(f"[!] DESCUADRE en Fila {i+1} (Pág {fila['PÁGINA']} - {fila['FECHA']}): {fila['CONCEPTO'][:20]}...")
                logging.warning(f"    -> Calculado: ${saldo_calculado:,.2f} | Leído en PDF: ${saldo_leido:,.2f} | Diferencia: ${diferencia:,.2f}")
                descuadres_encontrados += 1
                saldo_calculado = saldo_leido 

    logging.info("\n==================================================")
    logging.info(" RESUMEN FINAL DEL PERIODO")
    logging.info("==================================================")
    
    logging.info(f"Total Registros Extraídos : {len(datos_extraidos)}")
    logging.info(f"Depósitos Extraídos       : ${suma_depositos:,.2f} (Esperado: ${CONTROL_DEPOSITOS:,.2f})")
    logging.info(f"Retiros Extraídos         : ${suma_retiros:,.2f} (Esperado: ${CONTROL_RETIROS:,.2f})")
    logging.info(f"Saldo Final Calculado     : ${saldo_calculado:,.2f} (Esperado: ${CONTROL_SALDO_FINAL:,.2f})")
    
    if descuadres_encontrados == 0 and round(suma_depositos, 2) == CONTROL_DEPOSITOS and round(suma_retiros, 2) == CONTROL_RETIROS:
        logging.info("\n[✔ VISTO BUENO] CUADRE PERFECTO. Todos los centavos, retiros y depósitos coinciden. ¡Listo para contabilidad!")
    else:
        logging.warning(f"\n[X ADVERTENCIA] Se encontraron descuadres menores. Revisa los montos exportados.")

    df = pd.DataFrame(datos_extraidos)
    if not df.empty:
        columnas_orden = ["PÁGINA", "FECHA", "CONCEPTO", "RETIROS", "DEPÓSITOS", "SALDO"]
        df = df[columnas_orden]
        df.to_excel(excel_path, index=False)
        logging.info(f"\nArchivo contable final guardado en: {excel_path}")

if __name__ == "__main__":
    archivo_pdf = "Estado de Cuenta.pdf"
    archivo_excel = "Estado_de_Cuenta_Extraido.xlsx"
    procesar_estado_cuenta(archivo_pdf, archivo_excel)