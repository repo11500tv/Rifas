# Primera intervención de infraestructura en Arsys

**Pendiente de autorización.** La intervención habilita aislamiento en el
staging existente con el código y las bases de partida. Usa Plesk,
systemd y el coordinador existentes. No instala releases ni migra datos.
Producción y la aplicación de 8766 quedan fuera del lote.

## Aislamiento mínimo

Usar una cuenta no privilegiada de staging, distinta de producción,
sin permisos de escritura por grupos compartidos o ACL sobre producción
o `/sorteos`. Conceder tránsito por los directorios padre y mantener a
Plesk y Nginx el acceso específico que necesiten. El UID del proceso
systemd puede separarse del usuario del vhost Plesk si los permisos y
las tareas de mantenimiento del vhost lo permiten. Comprobarlo con la
configuración efectiva. Verificar también ACL y montajes.

Aplicar `ProtectSystem=strict`, `NoNewPrivileges=yes`,
`KillMode=control-group`, vías de escritura explícitas y ámbitos ajenos
inaccesibles. El operador y los trabajadores de staging solo deben
controlar `rifas-pruebas.service`. Los procesos auxiliares quedan
sujetos a permisos equivalentes. Puede usarse la misma identidad
dedicada dentro de staging para leer el release privado y observar
sus procesos. El confinamiento de la unidad no cubre al operador ni
a los trabajos lanzados fuera de ella. En producción, conservar la
exclusión de todo `/rifas/staging` y limitar las raíces gestionadas a
subdirectorios, sin incluir el padre común en modos de escritura.
[Drop-in de ejemplo](staging-isolation.service.example)

## Transacción de mantenimiento

Preparar un único lote en la automatización administrativa existente,
con acciones de validación, captura, aplicación y reversión. El
manifiesto del lote debe enumerar exactamente los archivos, permisos,
ACL, cuentas, delegaciones y unidades afectadas. Registrar el estado
anterior, qué objetos no existían y los pasos inversos. El control de
errores debe activar los inversos desde el primer cambio escrito.

| Orden | Operación y salida exigida para continuar |
| --- | --- |
| Validar | Confirmar host, unidad, backend 8768, baseline, publicación efectiva y rutas alternativas. Validar las configuraciones candidatas y limitar el lote a staging. Si el mecanismo efectivo de cierre sigue sin conocerse, detener el lote. |
| Capturar | Respaldar las fuentes Plesk, drop-ins y perfiles afectados, con modos, propietarios, ACL y estado previo de servicio. Verificar inventario y hashes. Guardar copia e inversos fuera del árbol gestionado, con acceso restringido. |
| Bloquear | Cerrar todas las entradas de staging y comprobar HTTP 503. Detener solo staging y sus escritores. Exigir unidad inactiva, puerto libre y ausencia de escritores observables. |
| Aplicar | Aprovisionar identidad y permisos de staging, instalar el drop-in y actualizar la configuración Plesk solo si está en el lote aprobado. Mantener el release anterior. Verificar sintaxis antes de recargar la configuración y arrancar solo staging. Cualquier recarga compartida de Nginx requiere autorización explícita. |
| Verificar | Comprobar permisos efectivos de operador, servicio y trabajos, delegación de unidad, PID y UID del backend privado, portal, barrera y ausencia de bypass. Obtener evidencia estructural y observar que producción y 8766 conservan su estado. Reabrir solo si todas las pruebas pasan. |
| Revertir | Mantener mantenimiento, detener staging si procede, restaurar los elementos inventariados y retirar solo lo creado por el lote cuando sea seguro. Verificar hashes, modos y ACL, regenerar la configuración efectiva y restaurar el estado previo de staging. Reabrir tras verificar el baseline. Si falla la reversión, mantener la barrera y escalar. |

El lote queda preparado como procedimiento parametrizado y condición de
aceptación. Los comandos efectivos de Plesk, la lista de ACL y las rutas
de la barrera dependen de la comprobación pendiente de publicación.
Todavía no es un lote ejecutable en Arsys. Usar el mecanismo
administrativo existente una vez completados y revisados esos datos,
sin incorporar otro instalador al proyecto.

## Evidencia y habilitación del coordinador

Completar el perfil y los archivos de revisión. Configurar el observador
con un comando de solo lectura de argumentos fijos que invoque
`/usr/bin/python3 -I -B /ruta/coordinador/deployment/structure.py`
seguido de las raíces gestionadas. Su vista de `/proc` debe cubrir el
host. Si la visibilidad es insuficiente, el coordinador bloquea el
flujo. Delegar la lectura de forma acotada, sin elevar todo el
coordinador ni permitir shell genérica.

Obtener la evidencia con
`python -B -m deployment.deploy --config "$CONFIG" structure` desde
la cuenta operativa. Revisar los resultados y fijar el digest en
`expected_fingerprint` en un perfil protegido. El comando no imprime
las propiedades efectivas ni los secretos. Para una eventual
autorización de release independiente, superar `plan` con la evidencia
vigente y el artefacto firmado. La prueba autorizada de recuperación
externa sigue siendo un requisito separado.

## Fase 2E — Cierre de las incógnitas

No se repite el mapa de unidades y puertos ni el inventario SQLite. Las
incógnitas restantes son la precedencia efectiva de virtual hosts, includes,
redirecciones y proxy entre Plesk, Nginx y Apache; los alias o accesos que
podrían evitar el cierre; el tránsito y las ACL para una identidad de
staging distinta; y las dependencias, planificadores y tareas que pueden
arrancar escritores o arrastrar otra unidad al detener staging.

Ejecutar en **una sola operación desde PuTTY**, con la sesión de lectura ya
autorizada, el contenido completo de
[inspect-pending-readonly.sh](inspect-pending-readonly.sh). Pegar el bloque
directamente y recoger su JSON desde PuTTY, sin guardar un script ni redirigir
stdout en el servidor. No usar elevación genérica. El bloque no invoca
pruebas de sintaxis del servidor web que puedan abrir logs, no abre SQLite
y no realiza peticiones HTTP ni acciones sobre servicios. Puede aparecer
en los registros o el historial de la sesión según la política del host.
No ejecutarlo si esa persistencia automática tampoco está permitida.

- `proxy_hint` identifica archivo y línea, tipo de directiva y referencias
  a los backends conocidos. No imprime hostnames, destinos completos ni
  argumentos. Resolver la cadena de includes y el orden efectivo de las
  rutas con esas referencias. Los includes externos, los destinos dinámicos
  y los accesos fuera del vhost siguen pendientes si no son observables.
- `permissions` registra modos y recuentos de entradas ACL sin nombres ni
  identificadores de usuarios. La visibilidad parcial del lector y los
  permisos de una identidad futura no se pueden certificar con este paso.
- `dependency` y `scheduled` señalan acoplamientos, trabajos y políticas de
  la unidad de staging. Un resultado vacío no descarta cron de usuario,
  trabajos Plesk ni procesos externos. `limits` enumera lo pendiente.

### Automatización de la transacción

El coordinador incorpora `intervene` y `recover-intervention` para este
lote de infraestructura. Reutiliza su bloqueo, aprobaciones de un solo
uso y registro. Impide aplicar o recuperar un release mientras la
intervención esté pendiente. Estos comandos aceptan staging y fixtures
sintéticos. No aceptan el perfil de producción.

El [lote de ejemplo](intervention.example.json) fija el formato. Antes de
autorizarlo, sustituir los marcadores por el inventario aprobado, los
comandos y archivos efectivamente verificados y sus SHA-256. Incluir
scripts, políticas, manifiesto de rutas, archivos de entrada y ejecutables
del lote. Mantener estos insumos de revisión separados de los archivos
activos que la transacción va a modificar. El coordinador verifica sus
huellas antes de cada paso. El ámbito de cada comando delegado debe
quedar limitado por los permisos del sistema y por la revisión del lote.
El coordinador no infiere ni restringe los archivos que un comando
administrativo puede modificar. No ejecutar el coordinador como root
ni concederle acceso general a sudo, Plesk o systemd.

Cada paso recibe `RIFAS_INTERVENTION_BACKUP`, un directorio privado de la
ejecución. Los comandos deben preservar el baseline y tener este contrato:

| Paso | Garantía exigida al lote aprobado |
| --- | --- |
| `validate` | Verifica destino, identidad, dependencias, rutas, sintaxis candidata y ausencia de efectos sobre producción y `/sorteos`. Solo lectura. |
| `backup` / `verify_backup` | Capturan y verifican inventario, estados previos, ficheros, permisos, ACL y huellas. La captura debe ser durable y registrar también los destinos antes inexistentes. |
| `close` | Cierra todas las entradas y detiene solo la unidad y escritores de staging. Es repetible y confirma el cierre antes de devolver éxito. |
| `apply` / `verify` | Aplican exclusivamente los cambios autorizados y validan aislamiento, baseline, unidad, rutas y ausencia de efectos en los otros servicios. La publicación externa sigue cerrada. |
| `rollback` / `verify_rollback` | Restauran solo los elementos inventariados, retiran los creados por el lote y verifican el estado anterior antes de abrir. Son repetibles. |
| `reopen` | Restablece las entradas y escritores autorizados para el resultado verificado. Es repetible y confirma servicio y publicación. |

Tras verificar la copia, el coordinador persiste el estado antes de cerrar.
Un fallo durante cierre, aplicación o verificación activa la reversión.
Si la reversión falla, el estado queda pendiente para reintento. Tras
confirmar el resultado, un fallo de reapertura solo permite repetir
`reopen`; no restaura configuración sobre un servicio que pudo haber vuelto
a admitir tráfico. Los logs guardan los nombres de los pasos y resultados,
sin la salida cruda del comando.

La aprobación usa el SHA-256 del JSON revisado y las claves de
`intervention_signers`, distintas de las de release y despliegue. El
comando previsto tras la autorización es
`python -B -m deployment.deploy --config "$CONFIG" intervene --recipe "$LOTE" --approve "$APROBACION"`.
Tras una interrupción, `status` muestra el identificador y estado. Para
recuperar se exige el lote idéntico y una nueva aprobación
`recover-intervention` ligada a ese identificador.

El ejemplo **no es ejecutable**. Faltan los comandos efectivos de Plesk,
el inventario de cambios de permisos, la delegación y las pruebas de
efectividad en Arsys. La fase 2E valida la transacción con fixtures.
Autorizar por separado la inspección real, la captura de configuración
y ACL, cualquier cambio de identidad, unidad, proxy o delegación, la
parada y reapertura de staging y cualquier recarga compartida de Nginx
o Apache. Un ensayo de recuperación externa y un despliegue posterior
tienen autorizaciones propias. El perfil de release continúa bloqueado
hasta comprobar aislamiento y recuperación.
