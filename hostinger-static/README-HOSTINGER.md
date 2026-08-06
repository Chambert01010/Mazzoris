Version frontend estatica lista para Hostinger.

Esta carpeta es el paquete que se puede subir solo a Hostinger. No depende de
Python, Django, SQLite ni de las librerias de procesamiento de PDFs.

Contenido para subir a `public_html`:
- `index.html`: pagina publica exportada desde `templates/index.html`.
- `assets/`: CSS e imagenes copiadas desde `static/`.
- `.htaccess`: ajustes basicos para Apache/Hostinger.

Subida recomendada:
1. Abre Hostinger hPanel y entra al File Manager del dominio.
2. Entra a `public_html`.
3. Sube `hostinger-static-upload.zip` y extraelo ahi, o arrastra el contenido
   de esta carpeta directamente.
4. Confirma que `index.html` quede directo en `public_html`, no dentro de una
   subcarpeta adicional.
5. Confirma que tambien exista `public_html/assets`.

Para regenerar esta carpeta desde el proyecto Django:

```powershell
.\scripts\export_hostinger_frontend.ps1
```

Si PowerShell bloquea scripts en tu equipo:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_hostinger_frontend.ps1
```

Notas de compatibilidad:
- Hostinger documenta que los archivos del sitio deben quedar en `public_html`.
- Hostinger permite subir por File Manager o FTP/SFTP.
- Si el sitio no usa base de datos, se omite la importacion de base de datos.
- El backend Django y el procesador de estados de cuenta quedan fuera de esta
  subida porque requieren servidor Python y dependencias.

Fuentes oficiales revisadas:
- https://www.hostinger.com/tutorials/how-to-upload-your-website
- https://www.hostinger.com/support/4548688-basic-actions-in-the-file-manager-in-hostinger/
- https://www.hostinger.com/support/node-js-hosting-options-at-hostinger/
