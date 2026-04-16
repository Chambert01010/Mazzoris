Version estatica lista para Hostinger compartido.

Contenido:
- `index.html`: pagina principal publica.
- `staff/`: acceso staff visual compatible con hosting por archivos.
- `assets/`: estilos e imagenes.
- `.htaccess`: configuracion basica para Apache/Hostinger.

Subida recomendada:
1. Comprime el contenido de `hostinger-static`.
2. En Hostinger, entra al `public_html` del dominio.
3. Sube el ZIP y extraelo para que `index.html` quede directo en `public_html`.
4. Verifica que `public_html/assets` y `public_html/staff` tambien existan.

Importante:
- Esta version funciona en hosting compartido porque es estatica.
- El procesador de PDFs original sigue viviendo en la app Django del proyecto, pero no forma parte de esta subida.
