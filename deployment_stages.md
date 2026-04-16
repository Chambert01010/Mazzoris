# Plan de despliegue y escalabilidad de accesos

## Etapa 1: Despliegue inmediato

Estado: aplicada en el proyecto.

Objetivo:
- Desplegar la aplicacion actual con una sola credencial compartida, reduciendo riesgos basicos de seguridad y operacion.

Cambios tecnicos ya considerados:
- Configuracion por entorno para produccion.
- Cookies de sesion y CSRF seguras cuando se usa HTTPS.
- Redireccion opcional a HTTPS.
- Soporte para proxy reverso con `X-Forwarded-Proto`.
- HSTS en produccion.
- `STATIC_ROOT` para `collectstatic`.

Checklist operativo antes de publicar:
- Definir una `DJANGO_SECRET_KEY` nueva y privada.
- Poner `DJANGO_DEBUG=False`.
- Configurar `DJANGO_ALLOWED_HOSTS` con el dominio real.
- Configurar `DJANGO_CSRF_TRUSTED_ORIGINS` con `https://tu-dominio`.
- Confirmar que el hosting sirva la app por HTTPS.
- Crear un usuario operativo normal para el trabajo diario.
- Reservar el superusuario solo para administracion.
- Cambiar o eliminar cualquier credencial de prueba antes de abrir acceso.

## Etapa 2: Multiusuario basico

Objetivo:
- Dejar de operar con una sola credencial compartida y entregar una cuenta por persona, sin rehacer el dashboard actual.

Alcance propuesto:
- Crear usuarios individuales desde Django Admin o desde un panel interno simple.
- Mantener el login actual de Django.
- Desactivar la cuenta compartida como acceso principal.
- Registrar actividad minima por usuario.

Cambios sugeridos:
- Modelo o tabla de auditoria para guardar:
  - usuario
  - fecha y hora
  - banco seleccionado
  - nombre original del archivo
  - exito o error del procesamiento
- Vista o seccion administrativa para consultar esa actividad.
- Politica operativa para altas, bajas y cambio de contrasenas.

Resultado esperado:
- Saber quien uso el sistema.
- Retirar acceso a una sola persona sin afectar a los demas.
- Mejorar soporte y control interno.

## Etapa 3: Multiusuario formal

Objetivo:
- Escalar el sistema para trabajo continuo con varios usuarios, trazabilidad real y mejor control operativo.

Alcance propuesto:
- Roles y permisos por tipo de usuario.
- Perfil de usuario con datos del negocio.
- Historial completo de procesos.
- Mejor capacidad operativa si aumenta la concurrencia.

Cambios sugeridos:
- Definir grupos como:
  - administrador
  - operador
  - supervisor
- Agregar perfil de usuario con campos como nombre, area, empresa, activo/inactivo.
- Guardar historico de cargas y resultados por usuario.
- Agregar recuperacion de contrasena y politicas de acceso.
- Evaluar colas de trabajo para procesar PDFs pesados si aumenta el volumen.

Resultado esperado:
- Operacion mas segura y profesional.
- Auditoria completa.
- Mejor base para crecimiento y soporte.
