# Rifas — estado real de integración de staging (23-11-2026)

## Alcance y regla de trabajo

GitHub es la fuente del código. No crear más instaladores de un solo uso ni subir scripts sueltos a la raíz de `dealfonso.com`. El coordinador universal de `deployment/` es el único motor de despliegue para staging y producción. La preparación del sistema operativo (systemd, proxy, permisos) es distinta de un despliegue de aplicación. No tocar producción ni `/sorteos/`; no aplicar cambios en staging sin autorización expresa para la operación concreta.

## Verificado por salidas del operador (no por acceso remoto directo)

- Staging: `/var/www/vhosts/dealfonso.com/rifas/staging/prueba_231`; servicio `rifas-pruebas.service`, puerto 8768, HTTP 200.
- Producción: `/var/www/vhosts/dealfonso.com/rifas`; servicio `rifas-platform.service`, activo. Aplicación histórica `/sorteos/` excluida.
- Ambos servicios usan `dealfonsocom`, sin `ProtectSystem`, `ReadWritePaths` ni `InaccessiblePaths`. La cuenta tiene permisos de escritura en las tres raíces. **No hay aislamiento de escritura demostrado**.
- El ejecutor restringido `/usr/local/sbin/rifas-staging-service` responde `active` mediante sudo limitado; `sudo -i` denegado a `dealfonsocom`.
- Checkout de código del coordinador descargado en `/srv/rifas-deploy/staging/checkout`, commit `e9140463e8f45febe853b860a8490c121c14fb68`. No se ha configurado ni activado.
- Directorios `/srv/rifas-deploy/staging/{control,trust,config}` creados con propietario root y modo 0700.
- No existe `.rifas-deploy` en staging; tampoco perfiles operativos, firmas de confianza, barrera HTTP, selector ni `hook serve` en el servicio.
- En staging existen base central, plantilla maestra y una base de entidad; no se detectaron archivos WAL, SHM ni journal en la muestra. El `venv` de staging es enlace simbólico y debe resolverse.
- Espacio libre observado: 74,62 GB. Git, OpenSSH y Python 3.12 disponibles.
- En la configuración Nginx inspeccionada hay una referencia al puerto 8768, pero **no se ha demostrado** la barrera HTTP 503 ni todas las rutas de acceso.
- La rama contiene la receta `deployment/packages/google_oauth_2.4.2.json`; la ejecución CI 45159247173 fue satisfactoria para el commit de checkout.
- El operador ha hecho **público temporalmente** el repositorio. Antes de volver a privado, configurar lectura autenticada; revisar exposición de secretos en el historial. No almacenar claves privadas ni credenciales en GitHub.

## Trabajo pendiente, en un solo flujo versionado

1. **Integración operativa revisada en GitHub**: definir perfiles reales de staging, acceso al checkout protegido, confianza SSHSIG y firma externa, barrera Nginx de todas las entradas, `hook serve` de la unidad staging, directorios de estado y selector, runtime y enlaces. No introducir nuevos scripts temporales en el vhost.
2. **Aislamiento efectivo**: resolver o demostrar mediante confinamiento que procesos y operadores de staging no pueden escribir en producción ni en `/sorteos/`. No modificar rutas o permisos de producción como atajo. Cualquier ajuste de systemd, Nginx o identidades requiere revisión y autorización.
3. **Respaldo y recuperación**: inventario de escritores, cobertura de código y SQLite, plantilla maestra y entidades, configuración revisada, copia externa y ensayo de restauración con datos sintéticos.
4. **Validación automatizada**: pruebas del coordinador, de migración Google OAuth 2.4.2, consistencia entre código, plantilla y entidades, y verificaciones funcionales sin datos personales.
5. **Despliegue**: fijar commit y artefacto firmado; ejecutar `plan`; solicitar autorización independiente y firmada para `apply` en staging; aplicar con copia, comprobaciones y reversión automática. Producción no participa.

## Higiene de servidor

Los diagnósticos e instaladores temporales previamente depositados en la raíz de `dealfonso.com` no forman parte de la instalación operativa. Inventariarlos y verificar que no son usados antes de proponer su retirada; **no eliminarlos automáticamente ni sin autorización**. No crear una auditoría separada que retrase el despliegue: integrar el inventario y la limpieza segura en el flujo de aprovisionamiento.

## Estado final

**No desplegado.** Google OAuth 2.4.2 no está activo en staging. Checkout y directorios de control preparados; integración de servicio/proxy/firmas, aislamiento y recuperación pendientes. La comprobación de lectura no sustituye una prueba de recuperación.


## Modelo de responsabilidades y privilegios (criterio del propietario, 23-11-2026)

**Principio obligatorio para cualquier dominio de destino:** separar al administrador del servidor (root o equivalente) del propietario/gestor del dominio y de los administradores de entidades. El propietario del dominio debe controlar y autorizar el ciclo de vida de la aplicación sin acceso root habitual.

- **Administrador del servidor:** aprovisionamiento inicial y cambios de infraestructura que exijan privilegios (usuario/cuenta del dominio, aislamiento Unix, servicio o supervisor, proxy/TLS, permisos de sistema y delegaciones restringidas). Debe poder entregar una instalación preparada sin conservar tareas de actualización ordinaria.
- **Propietario del dominio:** configuración y secretos propios de Rifas, administración superior, autorización de despliegues, instalación de versiones verificadas, migraciones, respaldos y restauración de datos de la aplicación, y mantenimiento ordinario mediante un coordinador único ejecutado con su identidad delegada. Sus privilegios no se extienden a otros dominios.
- **Administrador de entidad:** únicamente funciones de su entidad, sin acceso al sistema operativo, al coordinador ni a los datos de otras entidades.
- **Servicio web/Gunicorn:** identidad de ejecución con permisos mínimos, sin capacidad de alterar artefactos, aprobaciones, código confiable, controles del despliegue ni datos de otros entornos.
- **Cambios privilegiados posteriores:** se documentan como solicitudes concretas al administrador del servidor; no se resuelven exigiendo root al propietario del dominio ni ampliando sudo de forma general.

**Implicaciones para la integración pendiente:** el directorio root 0700 actualmente previsto para `control` no puede ser el único punto de lectura de `release.json` para Gunicorn. Rediseñar el selector con separación de permisos: el coordinador autorizado por el propietario escribe de forma atómica en una ubicación operativa protegida; el servicio solo lee lo imprescindible. Los perfiles, autorizaciones y firmas deben permanecer fuera de escritura del proceso web. No solucionar mediante chmod indiscriminado ni ejecutar el coordinador como root. Separar también staging y producción a nivel de identidades/permisos antes del despliegue.

**Criterio de aceptación reutilizable:** una vez terminado el aprovisionamiento, demostrar en pruebas que el propietario del dominio puede ejecutar `plan`, aprobar y aplicar una actualización de staging, realizar respaldo y recuperación sin root, mientras Gunicorn no puede alterar el control y staging no puede escribir en producción. Cualquier excepción debe quedar documentada como tarea de infraestructura para el administrador del servidor.

Este apartado es especificación de arquitectura, no autorización para alterar servicios o permisos en Arsys.
