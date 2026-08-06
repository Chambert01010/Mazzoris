# Compatibilidad de formatos de estados de cuenta

El proyecto debe aceptar las diferentes versiones de un estado de cuenta que publique cada banco, siempre que el PDF conserve información suficiente para comprobar los movimientos y saldos.

## Reglas de implementación

- La selección del procesador se realiza por banco, pero cada procesador debe detectar la variante de formato a partir del contenido y la geometría del PDF.
- No se deben asumir posiciones absolutas únicas para todas las páginas o versiones. Cuando el documento incluya encabezados de columnas, estos deben ser la referencia principal para interpretar importes.
- Los límites fijos solo pueden usarse como respaldo para formatos antiguos conocidos y deben estar cubiertos por pruebas.
- Una variante nueva debe agregarse sin romper las variantes previamente soportadas.
- La extracción solo se considera exitosa cuando la auditoría reconcilia a centavos el saldo inicial, abonos, cargos, saldo final y todos los saldos intermedios publicados.
- No se debe reducir la exigencia de la auditoría para aceptar un formato nuevo. Si la estructura no puede interpretarse con certeza, el archivo debe rechazarse con un error claro.

## Inbursa

Las versiones observadas pueden desplazar horizontalmente las columnas `CARGOS`, `ABONOS` y `SALDO` entre la primera página y las páginas siguientes. También pueden colocar movimientos inmediatamente debajo del encabezado, por encima de límites verticales usados por versiones anteriores.

El procesador Inbursa debe:

1. Detectar en cada página los centros de las columnas monetarias mediante sus encabezados.
2. Clasificar cada importe por cercanía al encabezado correspondiente.
3. Empezar a leer movimientos después del encabezado de detalle de esa página, sin depender de un límite vertical mínimo global.
4. Mantener límites de respaldo para documentos antiguos que no expongan encabezados utilizables.
5. Generar el Excel únicamente cuando la hoja `Auditoria` tenga `Estado general = OK` y no contenga comprobaciones con estado `ERROR`.


## Intercam

Los estados Intercam pueden contener varias cuentas y monedas dentro del mismo PDF. El procesador debe auditar cada cuenta por separado para evitar compensaciones entre MXN, USD u otras monedas.

El procesador Intercam debe:

1. Detectar cada cuenta, CLABE, moneda y periodo.
2. Interpretar depósitos, retiros y saldos mediante los encabezados reales de columnas.
3. Comparar los totales del resumen del producto contra la fila `Total` del PDF.
4. Comparar ambos totales del PDF contra las sumas extraídas al Excel.
5. Validar todos los saldos intermedios y la ecuación `saldo inicial + depósitos - retiros = saldo final`.
6. Rechazar el archivo completo si cualquier cuenta o moneda tiene una diferencia.
