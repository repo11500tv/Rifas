# Control restringido del servicio de staging (preparación)

El archivo `rifas_service_control.py` es un **adaptador reutilizable** de control systemd, no un coordinador alternativo. El coordinador universal sigue siendo `deployment.deploy`. Su objetivo es sustituir llamadas directas privilegiadas de los hooks por una operación mínima con unidad fija. Este cambio **no está instalado ni probado en Arsys**.

## Modelo de privilegios

- El ejecutor se instala con propietario `root:root` y sin permiso de escritura para `dealfonsocom`, **fuera** de `/var/www/vhosts/dealfonso.com/rifas` y de cualquier ruta modificable por la aplicación.
- La unidad se fija en el ejecutor para cada instalación, por ejemplo `rifas-pruebas.service`; no se acepta una unidad arbitraria, un archivo de configuración proporcionado por la aplicación ni comandos de shell.
- Un archivo sudoers, también `root:root` y modo 0440, debe permitir a `dealfonsocom` **solo** las tres invocaciones exactas de ese ejecutor: `stop`, `start` y `status`, con `NOPASSWD` y sin comodines.
- No se concede `systemctl` genérico, `sudo -i`, escritura sobre unidades systemd, ni control de `rifas-platform.service` o de `/sorteos/`.
- El ejecutor **no es una barrera de seguridad suficiente** si el mismo usuario puede editar código o configuraciones privilegiadas, controlar otros servicios, modificar producción o alterar los archivos del coordinador. Revisar la cadena completa de permisos y las comprobaciones de aislamiento documentadas en [README.md](README.md).
- El mecanismo es parametrizable para otros dominios mediante aprovisionamiento de una copia revisada por instalación; el instalador portable completo sigue aplazado.

## Preparación antes de instalar

1. Revisar que el usuario no pueda escribir en la ubicación de instalación, el ejecutor, la unidad systemd, los perfiles del coordinador, los hooks y los archivos de confianza.
2. Revisar que `rifas-pruebas.service` es la unidad efectiva de staging y que el comando de stop de systemd espera el cierre de escritores.
3. Revisar el código del ejecutor y su ruta absoluta con `root`; instalar desde un commit revisado, nunca ejecutando directamente código de un checkout escribible por la aplicación.
4. Validar el archivo sudoers con `visudo -cf` antes de activarlo; comprobar como `dealfonsocom` las autorizaciones exactas y las denegaciones de otros comandos. No realizar todavía `start` o `stop` hasta tener autorizada la ventana de pruebas.
5. Integrar el adaptador en los hooks del **coordinador universal** y comprobar barrera, copias, pruebas, recuperación y aislamiento con un entorno de ensayo. No invocar el helper manualmente como sustituto de `deployment.deploy`.

## Ejemplo de política sudoers para revisión (NO instalar sin validar)

```sudoers
dealfonsocom ALL=(root) NOPASSWD: /usr/local/sbin/rifas-staging-service stop, /usr/local/sbin/rifas-staging-service start, /usr/local/sbin/rifas-staging-service status
```

La ruta es un ejemplo de destino **root-owned**. El operador debe verificar que la cadena de directorios no sea escribible por usuarios no privilegiados. Especificar una huella de ejecutable con sintaxis sudoers cuando la versión instalada lo permita.

## Estado

Preparado en GitHub; pendiente de revisión, integración con hooks, prueba automatizada y aprobación para instalar en Arsys. **No modificar producción.**
