# Despliegue y recuperación de Rifas

Un coordinador para instalaciones Linux con volumen local y bloqueo `flock`.
Requiere Python 3.12, Git, OpenSSH con SSHSIG y un runtime con Flask, Werkzeug,
Pillow, ReportLab, cryptography y Gunicorn. Ejecutar el coordinador desde un
checkout revisado, separado del código que sirve la aplicación.

## Artefacto y autorización

Construir desde el SHA completo de un commit revisado. El generador lee los
blobs de Git, incluida la receta, e ignora los cambios locales. La receta
histórica conserva las dos discrepancias detectadas en el manifiesto anterior.
El formato 2 empaqueta el árbol Flask y WSGI junto con la receta y las huellas.
Reconstruir el candidato en CI desde el mismo SHA y comparar los resultados.
Firmar y promocionar exactamente el mismo artefacto.

```sh
python -B -m deployment.artifact --commit "$COMMIT_REVISADO" \
  --recipe deployment/packages/sorteos_2.4.0.json --output "$ARTEFACTO"
ssh-keygen -Y sign -f "$CLAVE_RELEASE" -n rifas-deploy-v1 "$ARTEFACTO/manifest.json"
python -B -m deployment.deploy --config "$CONFIG" plan --artifact "$ARTEFACTO"
```

El plan imprime el digest, la raíz canónica, el inventario de bases, los
componentes de respaldo y las pruebas. Opera sin escribir en el destino ni
ejecutar hooks. Requiere bases estables sin WAL, SHM ni journal activo. En
ese caso, usar una copia coherente de revisión. La aprobación debe indicar
la raíz canónica **del destino**. La comprobación autoritativa se hace
bajo bloqueo al aplicar, y se revalida el inventario tras drenar escritores.

La firma de release acredita el artefacto. Una firma distinta autoriza
la operación, el entorno, la instalación, el digest y una ejecución concreta.
Generar y firmar la solicitud en una estación o sistema de aprobación separado
del destino. Usar cuentas y claves privadas distintas para staging y
producción y para firma de releases. En cada instalación provisionar su
`approval_signers` con las claves de operadores autorizados **solo** para ese
entorno. Usar una línea `rifas-operator ssh-ed25519 CLAVE_PUBLICA` por operador,
o añadir la restricción OpenSSH `namespaces="rifas-approval-v1-ENTORNO"`.
El archivo `allowed_signers` de releases usa la identidad `rifas-release`.
Las claves privadas y la capacidad de escribir esos archivos quedan fuera
del alcance de la aplicación y del envío de artefactos.

```sh
python -B -m deployment.approval apply --environment "$ENTORNO" \
  --installation "$RAIZ_CANONICA" --digest "$DIGEST" > "$APROBACION"
ssh-keygen -Y sign -f "$CLAVE_OPERADOR" \
  -n "rifas-approval-v1-$ENTORNO" "$APROBACION"
python -B -m deployment.deploy --config "$CONFIG" apply \
  --artifact "$ARTEFACTO" --approve "$APROBACION"
```

El destino recibe el JSON y el fichero `.sig` adyacente. Cada aprobación
caduca en una hora y se consume una sola vez, bajo bloqueo y antes de actuar.
Conservar `used-approvals` en el estado local y en el plan de recuperación;
perder ese estado permitiría reutilizar solicitudes firmadas aún vigentes.
Un intento que ya consumió la aprobación exige una solicitud nueva.

## Configurar una instalación

Los perfiles de staging y producción para Arsys y sus requisitos de
aislamiento están en la [guía de Arsys](arsys/README.md).

- Preparar una raíz independiente por instalación con `central/`, la plantilla
  y las bases de entidades. Crear `.rifas-deploy/` con modo 0700 y un archivo
  `environment` con el nombre exacto del entorno. Mantener estado, datos y
  código fuera de las rutas públicas. El catálogo central debe coincidir con
  las bases en disco.
- En la primera transición de una instalación existente, `baseline` apunta
  al código previo. Un alta sin código activo requiere bases aprovisionadas
  y una receta con `null` en `platform_from`. La fase 1 no crea una base central.
- Declarar en `backup_components` rutas relativas adicionales a `central` y
  `entidades`. Incluir configuración de proxy, supervisor, hooks, inventario
  de servicio y el fichero con las dependencias fijadas, o sus fuentes
  declarativas bajo control local. Las rutas concretas deben existir y no
  solaparse. La barrera y el selector operativo de release quedan fuera del
  inventario restaurable, para que restaurar archivos no reabra el tráfico.
- Controlar el acceso al checkout del coordinador, los perfiles, los hooks,
  los binarios, las raíces y los archivos de confianza. Mantener el runtime
  aislado, con identidad capaz de leer el código y restaurar los UID, GID y
  modos declarados. El proceso WSGI escucha solo en el backend privado.
  Asegurar que Plesk y el proxy sobrescriban los encabezados reenviados que
  confía Flask. Fijar `RIFAS_SESSION_COOKIE_NAME`, `RIFAS_SESSION_COOKIE_PATH`
  y los contadores `RIFAS_PROXY_X_FOR`, `RIFAS_PROXY_X_PROTO`,
  `RIFAS_PROXY_X_HOST` y `RIFAS_PROXY_X_PREFIX` por entorno. Los valores
  predeterminados conservan el comportamiento previo.

La configuración del coordinador declara `environment`, `data_root`,
`baseline` opcional, `allowed_signers`, `approval_signers`,
`runtime_python`, `backup_components`, `hooks` y `checks`.
`hooks` registra exactamente `drain`, `activate`, `ready` y `resume`.
`checks` registra las pruebas de cada paquete. Todos son listas de
argumentos con ejecutable absoluto. El paquete puede seleccionar nombres
de pruebas registradas. Mantener la verificación funcional de producción
de solo lectura. Para Sorteos, usar `deployment/smoke.py` con una entidad y
un sorteo de referencia, y validar la versión y el portal como sonda separada.

### Adaptador de proxy y supervisor

`deployment/hooks.py` implementa `drain`, `activate`, `resume` y `serve`.
Usar un lanzador local que ejecute `python -B -m deployment.hooks` desde
el checkout revisado:

```sh
#!/bin/sh
cd /ruta/checkout || exit 1
exec /ruta/python -B -m deployment.hooks --config /ruta/hooks.json "$@"
```

Ejemplo de configuración del coordinador para el mismo perfil sintético:

```json
{
  "environment": "synthetic",
  "data_root": "/srv/rifas-sintetico/data",
  "baseline": "/srv/rifas-sintetico/codigo-anterior",
  "allowed_signers": "/srv/rifas-sintetico/trust/releases",
  "approval_signers": "/srv/rifas-sintetico/trust/synthetic",
  "runtime_python": "/srv/rifas-sintetico/venv/bin/python",
  "backup_components": ["ops"],
  "hooks": {
    "drain": ["/srv/rifas-sintetico/bin/hook", "drain"],
    "activate": ["/srv/rifas-sintetico/bin/hook", "activate"],
    "ready": ["/srv/rifas-sintetico/venv/bin/python", "/ruta/checkout/deployment/smoke.py",
              "--base", "http://127.0.0.1:18081", "--version", "2.3.1", "--slug", "demo"],
    "resume": ["/srv/rifas-sintetico/bin/hook", "resume"]
  },
  "checks": {
    "sorteos": ["/srv/rifas-sintetico/venv/bin/python", "/ruta/checkout/deployment/smoke.py",
                "--base", "http://127.0.0.1:18081", "--version", "2.3.1", "--slug", "demo",
                "--raffle-id", "1", "--marker", "Sorteo de prueba"]
  }
}
```

Registrar el lanzador absoluto con el nombre de cada hook. Usar también
`lanzador serve` como comando del supervisor. Ejemplo de configuración del
adaptador en una instalación sintética:

```json
{
  "gate": "/srv/rifas-sintetico/control/maintenance",
  "target": "/srv/rifas-sintetico/control/release.json",
  "closed_url": "http://127.0.0.1:18080/health",
  "private_url": "http://127.0.0.1:18081/health",
  "stop": ["/ruta/supervisorctl", "stop", "rifas-sintetico"],
  "start": ["/ruta/supervisorctl", "start", "rifas-sintetico"],
  "gunicorn": {
    "python": "/srv/rifas-sintetico/venv/bin/python",
    "arguments": ["--bind", "127.0.0.1:18081"],
    "environment": {
      "RIFAS_SESSION_COOKIE_NAME": "rifas_sintetico_session",
      "RIFAS_SESSION_COOKIE_PATH": "/",
      "RIFAS_PROXY_X_FOR": "1"
    }
  }
}
```

En la ubicación Nginx que sirva la aplicación, hacer que la existencia de
`gate` devuelva 503 antes de enviar tráfico al backend. Ejemplo de directiva
dentro de esa ubicación:

```nginx
if (-f /srv/rifas-sintetico/control/maintenance) { return 503; }
```

El proxy debe consultar el marcador en cada petición y su usuario debe
poder atravesar el directorio de control. Validar la ubicación, las rutas
alternativas y las reglas de caché. El coordinador verifica HTTP 503 antes
de detener el servicio. Configurar también `pause_jobs` y `resume_jobs` si
hay escritores fuera de Gunicorn. El supervisor debe confirmar que el stop
espera a que terminen los workers y aceptar repeticiones de start y stop
sin error cuando el objetivo ya se cumpla. Adaptar los comandos si el
supervisor devuelve errores en esos estados. El selector persistente
permite que `serve` reciba el release aunque el supervisor no herede el
entorno del hook. `activate` confirma el backend privado, `ready` comprueba
versión, acceso a datos y portal, y `resume` verifica la reapertura pública.

Los ensayos usan Gunicorn real y un proxy y supervisor sintéticos. Las rutas
de Plesk, el mecanismo de aprovisionamiento de Nginx, el supervisor concreto,
las ACL y la separación de usuarios deben validarse sobre una copia
autorizada. No aplicar esas directivas directamente a una instalación real.

## Recuperar

Los logs están en `.rifas-deploy/events.jsonl`. Los respaldos y el artefacto
se conservan en `.rifas-deploy/runs/<id>/`. El respaldo integral del coordinador sustituye el formato anterior. La captura inventaría archivos y
directorios, UID, GID, modos, tamaños y huellas. Copia SQLite a través de su
API y verifica el inventario y todos los componentes antes de restaurar.
Reinstala archivos atómicamente, repone ausentes y elimina los añadidos
dentro de los ámbitos gestionados. Un reintento usa la misma captura.
Antes de migrar, recuperar vuelve a arrancar el código anterior sin copiar
datos. Si el proceso termina abruptamente, la barrera queda activa y el
estado se conserva. Para reanudar tras la muerte del coordinador:

```sh
python -B -m deployment.deploy --config "$CONFIG" status
python -B -m deployment.approval recover --environment "$ENTORNO" \
  --installation "$RAIZ_CANONICA" --digest "$DIGEST" --run "$RUN" > "$APROBACION"
ssh-keygen -Y sign -f "$CLAVE_OPERADOR" \
  -n "rifas-approval-v1-$ENTORNO" "$APROBACION"
python -B -m deployment.deploy --config "$CONFIG" recover --approve "$APROBACION"
```

Mientras `changing` siga pendiente, la reversión se repite con los
escritores detenidos. Tras `committed` o `rolled_back` solo se reintenta
`resume`, aunque un intento anterior haya reabierto el tráfico y aceptado
escrituras. Ante un defecto posterior a la apertura, usar un release
compatible o reconciliar cambios antes de autorizar una recuperación
manual. Si falta el runtime, el supervisor permanece indisponible o el
inventario no se verifica, conservar mantenimiento y escalar.

La captura cubre los ámbitos locales declarados y los permisos POSIX
básicos. ACL, atributos extendidos, enlaces, unidades externas y
reconstrucción del runtime quedan a cargo del aprovisionamiento. Para
pérdida del volumen se requiere una copia externa cifrada y un ensayo de
restauración con los perfiles, medios, claves, dependencias y estado de
aprobaciones. El respaldo local contiene datos personales y secretos.
Protegerlo y fijar su retención antes de usar una instalación real.

## Añadir paquetes y ejecutar pruebas

La receta describe versiones de origen y destino, módulo, tablas y
referencias a constantes DDL en el payload firmado. El destino contrasta la
plantilla, las entidades y el código. Una migración selecciona un archivo,
función y argumentos declarados en la receta. Debe ser autónoma, usar la
conexión que recibe, escribir solo su base y actualizar esquema y versión en
una transacción. Otra receta puede declarar un módulo distinto sin cambiar
el coordinador. OAuth 2.4.2 queda fuera de esta fase.

```sh
python -B -m unittest discover -s tests -v
```

La suite crea claves, Git, copias SQLite y servicios desechables en local.
Requiere loopback y `ssh-keygen`. Prueba firma, transferencia entre entornos,
reutilización, migraciones de dos módulos, detención del servicio, fallos
antes y durante la migración, recuperación parcial y preservación de una
escritura confirmada por HTTP después de reabrir.
