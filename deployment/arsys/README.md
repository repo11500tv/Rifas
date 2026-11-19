# Rifas 2.x en Arsys — preparación de la fase 2B

**Estado de los perfiles.** Son plantillas para revisar en el laboratorio.
Los valores `*_PENDING` impiden su uso directo. Esta fase no instala los
perfiles, cambia unidades ni autoriza un despliegue. Aplicar siempre el flujo
del [coordinador universal](../README.md).

## Compatibilidad y ajustes

Según el inventario facilitado, Ubuntu 24.04, Python 3.12.3 y SQLite 3.45.1
encajan con el runtime esperado. El inventario declara Nginx 1.30.6 y Plesk
Obsidian 18.0.82.3. Quedan por comprobar los imports del entorno Python y la
configuración efectiva de Plesk. Los servicios observados son
`rifas-pruebas.service` (staging) y `rifas-platform.service` (producción).
Los puertos 8766, 8767 y 8768 son observaciones sin asignación verificada.
La aplicación anterior bajo `/var/www/vhosts/dealfonso.com/sorteos` queda
excluida. Los perfiles contienen las raíces facilitadas; son parámetros,
no rutas incorporadas al coordinador.

| Prioridad | Ajuste |
| --- | --- |
| Imprescindible | Resolver puerto, prefijo y rutas públicas de cada unidad. Limitar Gunicorn al backend privado. Configurar en Plesk/Nginx la barrera antes del proxy en cada entrada, sin caché para la sonda. Completar `additional_closed_urls` con una sonda por entrada alternativa que devuelva 200 en operación normal. Comprobar también accesos directos que no pasan por Nginx. |
| Imprescindible | Aislar las escrituras de **Gunicorn, el coordinador, los hooks y los trabajos**. Preferir identidades distintas y permisos exclusivos, o un aislamiento de montaje que la cuenta compartida no pueda evitar. Restringir el control de systemd a la unidad exacta del entorno, sin conceder sudo genérico. Verificar el aislamiento desde el contexto real de cada proceso, incluidas rutas de montaje y archivos compartidos. |
| Imprescindible | Usar un marcador, selector, cookies, venv, estado y claves de aprobación independientes por entorno. La clave de firma del artefacto puede compartirse como confianza de lectura. El usuario de Nginx debe poder comprobar el marcador sin poder modificarlo. La unidad debe arrancar el hook `serve` desde el checkout revisado, con un selector inicial que apunte al baseline. |
| Imprescindible | Declarar una copia local revisada y sin secretos externos de configuración, unidades, hooks y dependencias reproducibles dentro de `ops-reviewed`, u otro componente explícito. Inventariar aparte archivos externos, ACL, atributos, montajes y almacenamiento de recuperación. Verificar espacio en los volúmenes de datos y respaldo. |
| Imprescindible | Identificar y drenar todos los escritores, incluidas tareas programadas. Configurar `pause_jobs` y `resume_jobs` cuando proceda. Confirmar que el stop de systemd espera el cierre de los workers y sus procesos descendientes. Alinear el tiempo de parada con el límite del hook. |
| Opcional | Enviar el registro de operaciones a un destino restringido y automatizar la retención. Añadir sondas de observabilidad que no muten datos. |

Staging está anidado en la raíz de producción y ambos servicios usan
`dealfonsocom:psacln` según el inventario. **Esto impide dar por establecido
el aislamiento.** `protected_paths` rechaza solapamientos con los ámbitos
gestionados, incluso si se incluye por error un directorio padre. El
inventario rechaza enlaces simbólicos y físicos en los ámbitos gestionados.
El hook comprueba entorno, datos y release antes de accionar la barrera
o la unidad. Estos controles detectan errores de configuración. La cuenta
compartida, los bind mounts y los permisos efectivos requieren control y
verificación a nivel del sistema. El proceso web tampoco debe poder editar
los perfiles, el lanzador ni las claves de aprobación.

## Configuración parametrizada

Los cuatro archivos `*.example.json` forman un par coordinador/hooks por
entorno. Completar una **copia local de revisión**. El valor
`PRIVATE_BASE_PENDING` de las sondas del coordinador es la URL base privada,
sin `/health`. En el perfil de hooks, `private_url` y `closed_url` apuntan
a las sondas completas. Confirmar la versión y seleccionar un sorteo de
referencia sin datos personales. El marcador del sorteo es texto público
de prueba. Ajustar las opciones de Gunicorn y los contadores
`RIFAS_PROXY_*` a los encabezados realmente sobrescritos por el proxy.
Conservar el alcance y nombre de cookie de producción si la revisión
confirma que son correctos.

El lanzador existente del perfil debe resolver el checkout fijo del
coordinador y llamar a `python -B -m deployment.hooks --config … "$@"`.
Para el supervisor, usar ese mismo lanzador con `serve`; los hooks de
activación y parada usan `systemctl` sobre el servicio nombrado en el perfil.
El artefacto firmado no controla la unidad ni los comandos de servicio.

La barrera y el selector quedan fuera de los ámbitos restaurables para
evitar que restaurar un archivo reabra el tráfico. Validar y respaldar
fuera del host los perfiles operativos y el estado que se necesite para
reconstruir ambos controles. Las copias creadas por el coordinador durante
`apply` se conservan en `.rifas-deploy/runs/<id>/backup`, protegidas por
el directorio de estado. El respaldo local cubre código anterior, SQLite,
medios, configuración incluida y permisos POSIX básicos. Establecer
retención y recuperación externa antes del ensayo real; no restaurar un
snapshot sobre escrituras ya reabiertas.

## Plantilla, entidades y base central

El catálogo central define el inventario. El contrato verifica integridad
y claves foráneas y compara el esquema del módulo en plantilla, entidades
y código firmado. La receta de Sorteos migra cada base de entidad y la
plantilla con la misma función y actualiza su marca de versión. El alta de
entidades clona la plantilla validada. La receta actual no migra la base
central: se valida su integridad, se usa para conciliar el catálogo y se
incluye en el respaldo. Si el esquema observado exige una migración
central, detener la preparación de este artefacto hasta revisar ese
cambio como otro contrato.

No se observó WAL/SHM en el inventario facilitado. Esta observación no
establece el estado durante el despliegue. La simulación exige bases
estables sin archivos auxiliares activos; realizarla sobre una copia
coherente y autorizada. No preparar copias de datos personales reales para
esta fase. En el laboratorio, usar esquema representativo y datos
sintéticos para comparar identificadores, compras de prueba y alta desde
la plantilla.

## Comprobaciones mínimas fuera del repositorio

1. Mapa unidad–proceso–puerto–ruta pública y configuración efectiva de
   Plesk/Nginx, incluidos bypass, caché y permisos del marcador.
2. Identidad, grupos, ACL, enlaces, montajes y rutas compartidas. Demostrar
   que un proceso y operador de staging no pueden escribir en producción
   ni en `/sorteos` y tampoco pueden controlar sus unidades.
3. Todos los escritores y mecanismos de parada, esquema y versiones de
   cada SQLite, correspondencia catálogo–archivos, espacio de trabajo y
   componentes necesarios para recuperación externa.
4. Runtime y baseline reales y resultado de una restauración integral en
   laboratorio, incluida la reapertura tras fallos.

## Primer ensayo en staging — requiere autorización expresa

1. Aprobar previamente la inspección pendiente y cualquier cambio de
   aprovisionamiento, Plesk/Nginx, systemd o permisos. Usar las plantillas
   primero en un laboratorio aislado con datos sintéticos. Probar también
   que rutas y servicios protegidos quedan fuera del alcance. Si falla
   cualquiera de las cuatro comprobaciones, detener el ensayo.
2. Firmar y fijar el digest del artefacto revisado. Ejecutar `status` y
   `plan` mediante el coordinador. Revisar catálogo, esquema, capacidad y
   componentes de respaldo. Comprobar que la copia externa se puede
   restaurar antes de abrir la ventana de cambios.
3. Tras recibir una autorización firmada para `apply` en staging sobre
   ese digest, usar el comando documentado en la guía universal. Esperar
   el 503 de todas las sondas, drenaje confirmado, copia verificada,
   migración, verificación funcional privada y reapertura HTTP 200.
   Conservar digest, identificador, registro y ubicación del respaldo.
4. Ante fallo anterior a la reapertura, conservar la barrera y comprobar la
   reversión automática. Si el proceso se interrumpe, consultar `status`
   y usar `recover` con autorización separada para el identificador
   pendiente. Tras `committed` o `rolled_back`, la recuperación reintenta
   la reapertura. Un defecto posterior que precise restaurar datos exige
   reconciliar primero las escrituras confirmadas.
5. Aceptar solo con todas las comprobaciones del coordinador superadas,
   catálogo y plantilla coherentes y el portal y sorteo esperados
   operativos. La prueba de staging no autoriza una promoción a
   producción. La aplicación anterior queda fuera de ambos perfiles.
