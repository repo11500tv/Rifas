# Integración staging Arsys: estado verificable y bloqueo de despliegue

Fecha de referencia: 2026-11-23. Rama de trabajo: `feature/google-oauth-242`.

## Hechos verificados en el servidor (salidas facilitadas por operador)

- `rifas-pruebas.service` está activo; consulta ejecutada como `dealfonsocom`.
- `sudo -n /usr/local/sbin/rifas-staging-service status` devuelve `active`.
- `sudo -i` para `dealfonsocom` está denegado.
- El instalador de permisos informó `INSTALACIÓN CORRECTA` y `visudo -c` sin errores.
- El instalador no actuó sobre los servicios.
- El repositorio es privado y no debe hacerse público.
- Producción y staging comparten usuario Unix `dealfonsocom`; staging está anidado bajo la ruta de producción.

## Cambios en el repositorio, todavía NO instalados en Arsys

- `deployment/hooks.py`: admite `service_control` opcional como argv fijo para start/stop; el comportamiento anterior con systemctl permanece cuando se omite.
- `deployment/arsys/staging.hooks.example.json`: declara `["/usr/bin/sudo", "-n", "/usr/local/sbin/rifas-staging-service"]`.
- `tests/test_staging_service_adapter.py`: pruebas sin invocar sudo/systemd real.

**No hay evidencia de que esas pruebas se hayan ejecutado en CI tras el último commit.**

## Bloqueos obligatorios antes de staging

1. **Aislamiento de escritura**: demostrar con pruebas negativas, desde los contextos reales de operador, coordinador, Gunicorn y tareas programadas, que ninguno puede escribir en producción ni `/sorteos`. La restricción sudo no satisface este requisito: el UID compartido aún puede escribir donde tenga permisos.
2. **Topología**: preferir separar staging fuera del árbol de producción y asignarle un UID propio, con ACL/montajes comprobados. Esto requiere un plan de migración reversible de staging y autorización separada. No cambiar propietario o permisos del árbol de producción para resolverlo.
3. **Supervisor**: adaptar únicamente `rifas-pruebas.service` para servir el release seleccionado mediante el hook `serve`, con venv y directorios propios; verificar comportamiento de parada, reinicio y recuperación. Requiere autorización.
4. **Proxy**: identificar todas las entradas públicas a staging y establecer barrera 503 efectiva sin alterar las ubicaciones de producción; probar bypass y cache. Requiere autorización.
5. **Coordinador protegido**: checkout, perfiles, aprobaciones y claves fuera del alcance de escritura de Gunicorn; estado `.rifas-deploy` separado, respaldo externo cifrado y recuperación probada.
6. **Datos**: comprobar inventario y migraciones SQLite de entidades existentes, plantilla maestra y código, con copias coherentes y prueba de restauración.
7. **Pruebas**: ejecutar suite automatizada y ensayo sintético; solo después generar paquete firmado OAuth 2.4.2, solicitar autorización específica y ejecutar `plan` antes de `apply`.

## Próxima decisión de infraestructura

Recomendación: **aislar staging con un usuario Unix distinto y raíz propia fuera del árbol de producción**, conservando producción y `/sorteos` intactos. Antes de ejecutar, preparar inventario de permisos, unidad systemd, Plesk/Nginx, puertos, cron y rutas, junto con copia y rollback. La autorización previa de instalar el ejecutor restringido **no autoriza** esta reubicación ni el despliegue de OAuth.

No crear instaladores por versión. Toda acción de despliegue debe pasar por el coordinador universal; el aprovisionamiento de infraestructura es una operación separada, auditable y reversible.
