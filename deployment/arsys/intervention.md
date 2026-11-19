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

## Cierre definitivo de 2E

### A. Comprobaciones ya resueltas

El [inventario estructural](inventory.json) conserva las dos lecturas
comunicadas desde Arsys. La unidad y el puerto de cada entorno, la
separación de las bases, la referencia literal hacia 8768, `auth_basic`
en el fragmento y el diagnóstico `getfacl: executable_missing` se
reutilizan. La ausencia de ACL en la muestra no acredita permisos de
una identidad futura. Esta revisión no vuelve a ejecutar esas consultas.

### B. Datos pendientes de la última inspección

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

### C. Comprobaciones que requieren un ensayo autorizado

Comprobar en ejecución el aislamiento del operador, el servicio y los
trabajos de staging; la efectividad de una delegación limitada a
`rifas-pruebas.service`; el drenaje de escritores; y la barrera en
cada entrada del mapa, incluida la autenticación después de reabrir.
Un `401 Basic` o `503` por sí solo no descarta rutas alternativas.
La recuperación externa sigue pendiente. Las autorizaciones para
inspección, cambios, ensayo de recuperación y despliegue son separadas.

### D. Condiciones necesarias para considerar ejecutable el lote

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

En la reapertura del release, un error al retirar o sincronizar el
marcador también activa el segundo cierre de staging. Se intenta pausar
los trabajos aunque ese cierre falle. El error se propaga al coordinador,
que conserva la recuperación pendiente. Las pruebas sintéticas verifican
la persistencia de la intervención incluso tras un reintento autorizado
fallido y comprueban archivos vecinos de producción y `/sorteos`.

## Preparación del lote definitivo — inspección ejecutada como root

Del último informe se incorporan dos datos: la sonda se ejecutó como
root y se contabilizaron **15 rutas competidoras**. En esa salida
`writable_by_probe=true` describe la identidad lectora privilegiada.
Queda descartado como prueba de escritura general o de la futura
cuenta de staging. La salida del inspector identifica ahora ese contexto.
No se repite la inspección. El coordinador rechaza una intervención de
staging ejecutada como root, aunque el digest coincida.

### Identidad, permisos y delegación

- **Identidad propuesta:** cuenta de servicio y grupo exclusivos de staging,
  cuyos nombres y UID/GID se fijarán tras comprobar colisiones y dependencias
  de Plesk. Gunicorn y los trabajos de staging quedan sin grupos compartidos
  que concedan escritura en producción o en la aplicación histórica. El
  operador usa una identidad de staging no privilegiada. Los comandos
  administrativos se delegan por acción y destino.
- **Padres y datos:** los ancestros del árbol facilitan tránsito, sin escritura
  para staging. Dar lectura a código, runtime y recursos. Dar escritura solo
  a las rutas canónicas revisadas de datos de staging, incluidos los
  directorios donde SQLite crea auxiliares. Inventariar grupos, ACL de
  acceso y por defecto, montajes y alias antes de decidir el cambio.
  Sin cambios recursivos de propiedad sobre el árbol compartido.
- **Control y unidad:** crear solo el control de staging ausente con
  propietario operativo y acceso de consulta del marcador para Nginx,
  sin escritura del proxy. Aplicar a `rifas-pruebas.service` el confinamiento
  definido en el [drop-in de ejemplo](staging-isolation.service.example).
  Revisar la unidad activa y la prioridad de sus drop-ins antes de fijar el
  nombre del fichero nuevo o reemplazado. Conservar el mismo baseline.
- **Delegación:** conceder exclusivamente las acciones de parada y arranque
  requeridas para `rifas-pruebas.service`, con argumentos cerrados.
  Denegar producción, `/sorteos`, recargas compartidas y control genérico
  de systemd. Las operaciones de aprovisionamiento con privilegios son
  aprobadas y acotadas aparte. Ningún permiso de root general se transfiere
  al coordinador. Demostrar la denegación desde el contexto efectivo del
  operador, servicio y trabajadores, sin intentar modificar ámbitos ajenos.

### Clasificación de rutas y escritores

Las 15 rutas son un recuento, no quince rutas identificadas en la información
recibida. La [matriz de revisión](evidence-and-inverses.example.json) reserva
15 posiciones pendientes. Conciliar cada posición con el informe saneado
hasta disponer de archivo y línea, precedencia real, destino y alcance de
Basic y mantenimiento. Clasificar como entrada de staging, descarte probado
o pendiente. Para cada entrada de staging, incluir la sonda HTTPS final;
para cada descarte, conservar su evidencia. Revisar alias, redirecciones,
servidores predeterminados, `location` por expresión o nombrados, includes
heredados, proxy indirecto y acceso directo a 8768 antes de cerrar el mapa.

En Apache queda por contrastar la configuración efectiva de Plesk, incluidas
reglas personalizadas y rutas que esquiven Nginx. En Plesk queda por verificar
la vista autorizada de tareas programadas y contrastarla con cron de usuario
y con el grafo indirecto de systemd: arranque, parada, reinicio, timers y
sockets. Vincular cada escritor con una pausa comprobable. Un vínculo no
resuelto con producción o `/sorteos` bloquea el lote.

### Inventario del lote y recuperación

La matriz registra los objetivos, metadatos que deben capturarse y el
inverso de cada cambio. Cada objetivo debe convertirse en una ruta o acción
exacta antes de firmar. Registrar existencia previa, contenido o huella,
permisos y ACL y, cuando aplique, estado activo y de habilitación. El
respaldo privado incluye el manifiesto y sus huellas verificadas antes del
cierre. Seleccionar y comprobar previamente el mecanismo capaz de restaurar
ambos tipos de ACL: el diagnóstico de `getfacl` ausente no autoriza a omitirlas
ni a instalar una herramienta. Conservar originales e inversos fuera del
ámbito modificado. No volcar credenciales de Nginx ni su fichero Basic al
informe.

Completar el ejemplar de esa matriz como
`/srv/rifas-deploy/staging/reviewed/evidence-and-inverses.json` y añadir su
huella al [lote único](intervention.example.json) junto con las huellas de
los insumos efectivos. Es evidencia de revisión que el coordinador existente
verificará como archivo del lote. No despliega ni ejecuta acciones por sí
misma. No sustituir `REVIEW_REQUIRED`, el digest fijado ni las URLs
pendientes con supuestos.

El lote conserva `auth_basic` y reutiliza la barrera existente solo si su
alcance se demuestra. Verificar cierre, drenaje, aislamiento y reapertura
desde todas las entradas del mapa. Un fallo conserva la intervención
pendiente; si la barrera no se confirma, registrar `publication=unverified`.
La recuperación restaura el inventario anterior, elimina solo lo creado
si es seguro y comprueba el baseline y la autenticación antes de reabrir.
La copia externa y su recuperación siguen siendo condiciones separadas.

Antes de poder ejecutar, faltan la matriz de rutas con Apache, el mapa de
escritores con Plesk, los permisos y delegación efectivos, la cobertura
de la barrera y la lista final de cambios e inversos con respaldo
verificable. Solo entonces se fija el digest y se solicita aprobación
expresa. Una recarga compartida requiere su propia autorización, y una
recuperación o despliegue posterior requieren las suyas.

## Revisión complementaria de evidencias — una sola pasada

Partir de las tres salidas ya registradas y la
[matriz de evidencias e inversos](evidence-and-inverses.example.json).
La referencia a 8768, la separación de las bases, el diagnóstico de
`getfacl` y el recuento de las 15 rutas se reutilizan. El anclaje literal de
Nginx se registra aparte: mientras falte la correspondencia, no asignarlo
a N01–N15. No repetir los inspectores ni usar `writable_by_probe` de root
como evidencia de la futura identidad.

### Decidir primero si bastan los datos saneados

| Evidencia pendiente | Cuándo bastan los datos saneados | Si no bastan |
| --- | --- | --- |
| N01–N15 y precedencia | Cada `location` se puede relacionar con una línea, la cadena de includes, su contexto y su destino, con pruebas de por qué alcanza staging o queda descartada. | El custodio verifica solo el bloque y las directivas de selección, herencia o reescritura que faltan en la configuración del vhost. Registra su conclusión por referencia, sin exportar los bloques. Si depende de lo cargado, de un valor dinámico o de una ruta externa que la lectura no demuestra, dejar la comprobación de comportamiento para el ensayo autorizado. |
| Apache/Plesk y acceso a 8768 | Los fragmentos y metadatos existentes permiten seguir el destino de cada entrada y descartar una ruta directa o alternativa. | Revisar en la vista de solo lectura del vhost afectado de Plesk los includes y reglas de Apache, y contrastar la exposición en cada frontera aplicable. Un listener loopback descarta una escucha remota en ese socket, pero no un proxy o reenvío alternativo. No repetir la medida del listener ni lanzar tráfico para resolver la duda. |
| Escritores, Plesk y systemd | Existe evidencia de identidad, destino y mecanismo de pausa para el trabajo concreto y de que su parada no arrastra otra unidad. | Revisar solo las tareas del vhost en el planificador Plesk y los trabajos de la identidad implicada. Para una arista pendiente, consultar las propiedades pertinentes de esa unidad con `systemctl show`, sin `Environment`, `ExecStart` ni volcados de unidades. Registrar origen, destino, tipo de dependencia y ámbito de escritura. Un escritor intermitente ausente de la muestra sigue pendiente. |
| Identidad, grupos y delegación | Los modos, grupos y permisos registrados bastan para rechazar o delimitar una propuesta. | Comparar solo los ancestros y destinos afectados y la delegación aplicable al operador, servicio y procesos auxiliares. El custodio solo comunica roles, operaciones permitidas y ámbitos excluidos. El acceso efectivo de una identidad que aún no existe, las ACL heredadas y la capacidad de stop/start requieren un ensayo posterior. |

### Capturar solo la diferencia pendiente

1. Abrir una única revisión autorizada, con el custodio de Arsys. Enumerar
   primero los campos abiertos de una copia local de la matriz mediante
   el comando de abajo. Cruzar sus identificadores con las evidencias ya
   conservadas. Leer únicamente la fuente o propiedad que falte.
2. Mantener en el entorno privado del custodio un registro de referencias:
   `F01` identifica un archivo, `M01` el contexto y criterio de selección
   de una ruta, y `E01` la fuente, revisión y conclusión que la respaldan.
   Usar la vista local autorizada de Plesk y los puntos exactos de
   configuración localizados en las salidas anteriores. No copiar
   configuraciones ni bloques completos al chat, a Git o al informe.
   No abrir archivos de contraseñas, volcar variables de entorno, leer
   registros de usuarios ni mostrar el comando crudo de una tarea. Si una
   directiva de enrutamiento o tarea mezcla datos necesarios con secretos,
   el custodio la revisa en origen y anota únicamente el destino por
   ámbito, la prioridad y el efecto. Si no puede aislarlos con seguridad,
   dejar el campo pendiente. Los destinos y comandos exactos que necesite
   el lote se mantienen en sus insumos privados revisados, sin credenciales.
3. Asociar una sola ubicación `Fxx` y línea a cada N01–N15, con su testigo
   `Mxx` y su referencia `Exx`. Para `staging_entry`, usar destino
   `staging_8768` y confirmar por separado Basic y mantenimiento con
   `verified`. Para `excluded`, documentar precedencia y destino ajeno
   (`outside_staging`) y usar `not_applicable` en esas dos columnas.
   Un bypass queda como `bypass` y bloquea. Una hipótesis queda
   `unclassified` con la evidencia faltante a `null`. No cerrar una ruta
   solo con un `401` o `503`.
4. Los campos de identidad, publicación y escritores en la copia saneada
   reciben referencias `Exx`, incluidos `verified_https_urls` y los datos
   de identidad. El registro privado asociado a esa referencia conserva
   la lista HTTPS real y la identidad que se incorporarán al lote
   protegido. No poner esos valores en la matriz publicada. Volver a
   validar únicamente la matriz local. El verificador muestra códigos
   fijos, cuenta rutas y detecta la misma ubicación y contexto asignados a más de un
   competidor. Comprueba formato y completitud, no verifica la verdad de
   la evidencia ni concede autorización.

Desde el checkout local, sin conexión a Arsys:

```sh
python -B -m deployment.arsys.evidence_review /ruta/local/matriz-saneada.json
```

El resultado sale con código 1 si falta evidencia y 2 si la matriz es
inválida. Código 0 indica que los campos revisados tienen referencias
válidas. `intervention_authorized` permanece en `false`. Los controles de
huellas, copias y reversión siguen en el coordinador universal.

### Separar aprovisionamiento y operación

El administrador del host debe autorizar y, si se necesita, aprovisionar
la cuenta y grupo dedicados, el tránsito por los padres, los permisos y
ACL de los destinos de staging, el directorio de control y sus
propietarios, las dependencias o *drop-ins* de systemd y la política de
delegación. Debe revisar también qué cuenta puede capturar y restaurar ACL,
propiedad y configuración. El acceso temporal a fuentes administrativas
para verificar una incógnita se limita a lectura y no habilita cambios.
Cualquier modificación de proxy o recarga compartida se aprueba aparte
solo si se demuestra imprescindible.

Tras ese aprovisionamiento, la identidad operativa de staging ejecutará
el coordinador sin root. La delegación se limita a las operaciones
revisadas sobre `rifas-pruebas.service`; el control de producción,
`/sorteos` y los privilegios generales quedan fuera. Los auxiliares
privilegiados que realmente necesite el lote requieren ámbito fijo,
revisión separada e inverso. El ensayo autorizado debe confirmar el
aislamiento, el drenaje, la autenticación y la barrera para todas las
entradas, además de la recuperación externa. Con las evidencias
pendientes, las rutas, el mecanismo de restauración ACL y las
autorizaciones siguen bloqueados y el lote conserva sus marcadores.
