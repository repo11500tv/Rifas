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
