# Separacion frontend/backend para Hostinger

## Objetivo

Subir a Hostinger solo el frontend publico de Mazzoris, dejando fuera el backend
Django y el procesamiento de estados de cuenta. Esto permite una subida simple
por File Manager o FTP/SFTP al directorio `public_html`.

## Frontend publicable

Carpeta: `hostinger-static/`

Sube el contenido de esa carpeta a `public_html`:
- `index.html`
- `assets/`
- `.htaccess`

Tambien se genera el archivo `hostinger-static-upload.zip`, pensado para subirlo
y extraerlo dentro de `public_html`.

## Backend separado

El backend se queda en el proyecto Django:
- `manage.py`
- `mazzoris_project/`
- `statements/`
- `templates/`
- `static/`
- `db.sqlite3`
- `requirements.txt`
- scripts de automatizacion bancaria

No subas esos archivos al hosting estatico si solo quieres publicar la pagina.
El panel real y el procesamiento de PDFs necesitan Python, Django y librerias
del servidor, asi que no funcionan como archivos HTML/CSS/JS sueltos.

## Regenerar el frontend

Cuando cambies la pagina principal en Django, ejecuta:

```powershell
.\scripts\export_hostinger_frontend.ps1
```

Si PowerShell bloquea scripts en tu equipo, usa:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_hostinger_frontend.ps1
```

Ese script exporta `templates/index.html` a `hostinger-static/index.html`,
convierte los tags de Django a rutas relativas y copia los assets desde
`static/` hacia `hostinger-static/assets/`.

## Regla practica para Hostinger

Para que el dominio abra directo la pagina, `index.html` debe quedar en la raiz
de `public_html`, no en `public_html/hostinger-static/index.html`.
