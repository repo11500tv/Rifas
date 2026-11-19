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

## Cierre de 2E — Datos incorporados

El [inventario reutilizable](inventory.json) conserva las dos inspecciones
comunicadas. La referencia a 8768, el listener local y el diagnóstico de
`getfacl` ya se registraron. Los dos bloques de inspección quedan como
referencia reproducible. Para preparar el lote basta resolver las comprobaciones
que siguen abiertas en la segunda inspección.

### Permisos que debe verificar el lote

| Ámbito | Diseño mínimo y criterio de aceptación |
| --- | --- |
| Padres del vhost, Rifas y staging | La cuenta dedicada dispone solo del tránsito necesario y carece de escritura en los ancestros. Conservar los modos 0755 observados si permiten el tránsito y no hay ACL contrarias. Evitar cambios recursivos en el padre común. |
| Staging, datos y entorno de ejecución | Dar lectura o tránsito en código, recursos y runtime. Limitar escritura a los directorios de datos de staging y a los persistentes declarados. Los directorios de SQLite deben permitir crear sus auxiliares. Plesk y Nginx conservan solo los permisos de lectura o tránsito que necesiten. Validar también ACL por defecto y permisos de descendientes. |
| Directorio de control | Aprovisionar `/srv/rifas-deploy/staging/control` en el lote autorizado. El operador de staging controla el marcador y el selector; Nginx puede consultar el marcador sin escribirlo. El entorno de producción tiene un control independiente. |
| Producción y aplicación histórica | Denegar escritura, cambio de permisos y administración de sus servicios desde las identidades de staging y los procesos auxiliares. Conservar las protecciones que excluyen el subárbol de staging en el perfil de producción. Verificar grupos, ACL, montajes y delegación efectiva, además de las rutas. |
| systemd | Mantener `KillMode=control-group`; añadir el confinamiento revisado con `ProtectSystem=strict`, rutas de escritura explícitas y ámbitos ajenos inaccesibles. Comprobar que Plesk y los procesos auxiliares siguen operativos. Una inspección sin referencias directas a otros servicios no descarta acoplamientos indirectos ni tareas programadas. |

### Criterio para autorizar la transacción

Mantener un único lote `intervene` con validación, respaldo comprobado,
cierre, aplicación, verificación y reversión. Además de la firma de
intervención, el perfil local de staging exige que su
`intervention_reviewed_digest` coincida con el SHA-256 del lote exacto.
Se rechazan insumos que resuelven dentro de los ámbitos protegidos.
Las pruebas locales verifican estos rechazos y que una reversión sintética
conserva intactos los archivos vecinos de producción y `/sorteos`.
Estas defensas controlan selección e insumos. Los comandos administrativos
requieren su propia delegación acotada y hay que comprobarla en Arsys
para demostrar el aislamiento efectivo.

Los marcadores del ejemplo permanecen intencionadamente sin resolver.
Antes de firmar el lote faltan: los permisos efectivos de la futura identidad;
la publicación y la barrera efectivas, incluidas las entradas alternativas;
el inventario de trabajos y dependencias indirectas; la cuenta y
delegación concretas; y la lista exacta y verificable de cambios y
restauración. El ensayo de recuperación externa sigue siendo requisito
previo al despliegue.

Las autorizaciones son separadas: (1) inspección puntual de lectura;
(2) captura de configuración y permisos para reversión; (3) creación
de la identidad y control de staging, cambios de ACL, unidad y proxy,
parada y reapertura de staging; (4) cualquier recarga compartida de
Nginx, Plesk o Apache, si se demuestra imprescindible; (5) prueba de
recuperación externa y eventual despliegue. La aprobación firmada debe
vincularse al lote final y su digest; si hace falta recuperar una
interrupción, se requiere `recover-intervention` vinculada a su ejecución.

## Segunda inspección de 2E — Decisiones para el lote

La segunda salida diagnostica `getfacl` como `executable_missing`.
Se observaron atributos POSIX de acceso y por defecto ausentes en los
directorios existentes examinados. No hace falta repetir ese diagnóstico
ni instalar la herramienta para continuar la revisión. La ausencia de
atributos en esa muestra no prueba los permisos efectivos de la futura
identidad en los descendientes, montajes ni grupos. El directorio padre
de control de staging tampoco existe. El lote debe inventariarlo como
ausente antes de aprovisionarlo y retirar únicamente lo que haya creado
si revierte.

El bloque literal de Nginx se ancla en `vhost_nginx.conf`: `location`
en la línea 38, `auth_basic` en la 39 y `proxy_pass` a 8768 en la 42,
con una coincidencia. **Conservar la autenticación existente**, incluidos
directivas, ámbito, fichero de credenciales y permisos. Registrar su
configuración de referencia por huella o metadatos dentro del respaldo
protegido, sin publicar valores. Si la barrera existente cubre íntegramente
las entradas y devuelve 503, reutilizarla. Solo si se demuestra que hace
falta otro cambio, proponer una regla acotada de mantenimiento para las
rutas de staging, sin reemplazar `auth_basic` ni regenerar o recargar
configuración compartida sin autorización.

Antes de fijar el digest final:

1. Confirmar el virtual host efectivo, su orden de includes y herencia y
   la precedencia de los posibles `location` competidores. Enumerar las
   entradas alternativas, incluidos alias y redirecciones HTTP a HTTPS,
   y verificar que todas terminan en la misma protección o quedan
   explícitamente bloqueadas. Confirmar que no existe una entrada directa
   externa a 8768. Guardar solo evidencias saneadas.
2. Enumerar procesos y tareas de staging en systemd, cron de la identidad
   que los ejecuta y planificador Plesk. Revisar dependencias indirectas,
   acciones de parada y reinicio y procesos fuera de la unidad. Identificar
   la unidad histórica si la hay; si su supervisor es otro, verificar
   por separado que la delegación y los comandos no pueden controlarlo.
   Incluir la evidencia y el inventario de tareas entre los insumos
   revisados del lote. Nada de esto se deduce de una consulta de
   dependencias directas.
3. Completar los pasos ya establecidos de cuenta y grupo dedicados,
   tránsito sin escritura en los padres, escritura limitada a staging,
   directorio de control, confinamiento y delegación. Validar el cambio
   de forma dirigida, respaldar y verificar configuración, propietarios y
   permisos, conservar el inventario de ausencias y especificar el inverso
   de cada cambio. La muestra de ACL observada no sustituye este control.

El lote firmado incluye `publication` con las sondas finales HTTPS de
todas las entradas protegidas y `unit_scope` con la unidad de staging,
sus auxiliares systemd revisados y las unidades protegidas. Producción
debe figurar en las protegidas. Indicar la unidad histórica solo si se
confirma; una lista vacía de auxiliares no equivale a haberlos descartado.
El coordinador comprueba dependencias **directas** entre esas unidades
antes de cerrar y antes de reabrir, y comprueba las sondas sin credenciales
ni seguimiento de redirecciones. Exige `401` con desafío `Basic` antes de
intervenir y al reabrir, y `503` con mantenimiento. Una reapertura que no
confirma Basic vuelve a cerrar la publicación si el cierre es viable y
conserva el estado pendiente. El paso revisado de reapertura debe ser
repetible incluso si el cierre anterior detuvo el backend. La sonda
privada sigue exigiendo `200` y no pasa por la autenticación pública.

Estas comprobaciones se ejecutan **solo dentro de una intervención
posteriormente autorizada**. Una respuesta anónima no prueba por sí sola
que la ruta llega al backend previsto, que todas las variantes quedaron
incluidas ni que una sesión autenticada se conserva. La revisión de
publicación y un ensayo autorizado con la autenticación existente siguen
siendo necesarios. El [lote de ejemplo](intervention.example.json) conserva
marcadores hasta completar esos datos y los comandos efectivos,
incluida la reversión. No se ha autorizado ni ejecutado ningún cambio.

## Inspector final de cierre operativo

Para esta revisión, ejecutar **solo** el contenido completo de
[inspect-route-acl-readonly.sh](inspect-route-acl-readonly.sh) en la sesión
PuTTY autorizada. El nombre histórico se conserva para no abrir otro
procedimiento. La versión final ya no ejecuta los bloques de diagnóstico
de ACL ni el inventario de SQLite. Entrega JSON por pantalla; no redirigir
la salida a un archivo en Arsys. No usa sudo, no escribe archivos, no abre
SQLite, no ejecuta HTTP ni recargas. El sistema puede registrar la sesión
o actualizar metadatos de acceso según su configuración.

| Salida | Evidencia de lectura y límite |
| --- | --- |
| `include_order`, `staging_route_candidate`, `competing_route_hint`, `alternative_review_hint` | Recorre los includes absolutos visibles y acotados a Nginx y al vhost Plesk, en orden estático, desde la ruta visible del proceso maestro si se reconoce y está dentro del ámbito, o desde `/etc/nginx/nginx.conf` como referencia. Localiza proxies directos a 8768 y upstreams nominales, reglas de sus bloques y posibles competidores. Los archivos reciben números, con referencias al include padre, y se omiten hostnames, credenciales, rutas privadas y argumentos. Algunos candidatos de Apache se indican por línea. No determina si el proceso cargó esos mismos archivos, usa otro prefijo o una versión anterior, o cómo resuelven includes externos o rutas dinámicas. |
| `effective_route_hint`, `conditional_route_hint`, `publication` | Señala autenticación, reglas de acceso, indicios de `503` y la presencia del marcador conocido. Un marcador o `return 503` es evidencia estática. Falta demostrar su alcance y precedencia sobre Basic para cada entrada. |
| `writer_hint`, `cron_hint`, `dependency_hit` | Identifica descriptores de escritura y mapeos compartidos observables, coincidencias de cron del sistema y del usuario activo, y el grafo systemd de staging con límites de profundidad y volumen. Omite nombres de cuenta, comandos y contenido de trabajos. Una muestra parcial o vacía no descarta escritores inactivos. Confirmar tareas Plesk con su vista de solo lectura autorizada y revisar trabajos indirectos y fuera de systemd. |
| `permission_hint`, `mount_hint`, `delegation_hint` | Muestra permisos respecto del lector, relación de las identidades actuales, montajes relevantes e indicios estáticos de sudo/polkit. No acredita los permisos de una identidad aún no provisionada, los montajes de su namespace ni la autorización efectiva de una delegación. |

### Criterios objetivos para cerrar el lote

1. Disponer de un mapa revisado del virtual host cargado y su cadena de
   includes, con cada hostname, puerto, prefijo, redirección, ruta directa
   y entrada alternativa que pueda llegar a staging. Justificar los
   descartes, incluidos Apache y 8768. Acordar las sondas con ese mapa.
2. Vincular cada escritor o planificador a su identidad y mecanismo
   de pausa o drenaje. Confirmar que parar staging no arrastra producción
   ni `/sorteos`. Una lectura con límites de visibilidad no permite
   declarar ausentes los escritores.
3. Confirmar los ámbitos efectivos de la futura cuenta, los grupos, ACL,
   montajes, namespace y delegación exacta. El ensayo autorizado debe
   verificar que staging solo escribe sus propios datos y controla su
   unidad, sin realizar escrituras de prueba en producción ni `/sorteos`.
4. Verificar en un ensayo autorizado la barrera para **todas** las entradas
   del mapa y confirmar que la autenticación existente funciona después de
   reabrir. Las sondas `401 Basic` y `503` solo prueban las URLs consultadas.
   No demuestran cobertura de alias, acceso directo ni prioridad de
   reglas. Conservar y reutilizar la barrera existente si pasa el ensayo.
5. Revisar el inventario exacto de cambios, copias e inversos, las pruebas
   de recuperación acordadas y el digest del lote. Mantener marcadores
   pendientes si falta cualquiera de estas evidencias. Las autorizaciones
   de inspección, cambios, prueba de recuperación y despliegue son
   independientes.

Si fallan la reapertura y el cierre de contingencia, el coordinador
conserva la intervención pendiente y registra
`publication=unverified`. También se mantiene pendiente si el comando de
cierre vuelve con éxito pero no se verifica el `503`. Un cierre verificado
puede quedar como `closed_verified` sin que ello signifique que la
reapertura o recuperación terminó. No ejecutar un release mientras este
estado siga pendiente. Revisar la barrera y usar el mismo lote con la
autorización independiente de recuperación.
