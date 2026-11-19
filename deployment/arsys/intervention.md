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
