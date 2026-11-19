# Despliegue de Rifas

Fase 1. Ejecutar desde un checkout revisado del coordinador, con Python 3.12,
Git y OpenSSH con soporte de SSHSIG. Las operaciones mutables también requieren
Linux, un volumen local con bloqueo `flock`, SQLite y sincronización de directorios.
Los ejemplos requieren un entorno aislado y una configuración propia.

## Construir, revisar y firmar

1. Revisar el commit completo y su receta en `deployment/packages/`. El JSON
   histórico `sorteos_2.4.0.legacy.json` conserva los hashes discrepantes de
   `entity_routes.py` y `participant_raffle_purchases.py` como evidencia de la
   auditoría. El coordinador utiliza el formato nuevo.
2. Construir desde el SHA revisado. El generador lee los blobs del commit y no
   incorpora cambios locales. Incluye el árbol completo de código Flask y WSGI.
   La receta declara compatibilidad, contrato SQLite, migración y pruebas.
3. Reconstruir de forma independiente desde el mismo commit y comparar el
   manifiesto completo y los hashes. Revisar el diff de código, migración y
   receta antes de firmar. Conservar artefacto, firma y SHA-256 del manifiesto
   en almacenamiento controlado. Promocionar exactamente ese artefacto.
4. Firmar fuera del servidor de aplicación mediante una clave Ed25519 de
   releases. Configurar en cada instalación un fichero de confianza
   `allowed_signers`, con una línea `rifas-release ssh-ed25519 CLAVE_PUBLICA`.
   La clave privada permanece en la estación o sistema de firma.

```sh
python -B -m deployment.artifact --commit "$COMMIT_REVISADO" \
  --recipe deployment/packages/sorteos_2.4.0.json --output "$ARTEFACTO"
ssh-keygen -Y sign -f "$CLAVE_DE_RELEASE" -n rifas-deploy-v1 "$ARTEFACTO/manifest.json"
```

El digest impreso por el generador identifica el manifiesto firmado. En el
destino se verifican firma, inventario exacto y huellas del payload. La firma
certifica la revisión y procedencia declarada por el firmante. El coordinador
no necesita un checkout Git del artefacto para verificar la firma.

## Preparar cada entorno

- Usar una raíz de datos independiente por instalación. Debe contener
  `central/plataforma.sqlite`, `central/plantillas/entidad_maestra.sqlite3`,
  las claves locales y `entidades/`. Preparar `.rifas-deploy` bajo esta raíz,
  propiedad del usuario operativo y con modo 0700. Crear dentro un archivo
  `environment` con el nombre exacto de esa instalación (`synthetic`,
  `staging` o `production`) para detectar configuraciones cruzadas. Mantener el código y el
  puntero `.rifas-deploy/current` fuera de las rutas públicas.
- Configurar una instalación existente con `baseline` apuntando al código
  previo, preservado durante la transición. Un primer arranque sin código
  activo requiere una receta que acepte `null` en `platform_from` y bases
  previamente aprovisionadas. Esta fase no crea una base central desde cero.
- Proporcionar un intérprete de runtime con Flask, Werkzeug, Pillow, ReportLab,
  cryptography y Gunicorn. El preflight verifica imports. Fijar el entorno
  Python y sus dependencias con la política de instalación del servidor.
- Mantener la configuración, claves, binarios y scripts operativos bajo control
  del administrador. La configuración establece los argumentos de cada hook
  como un array, con ejecutable absoluto. El paquete solo puede seleccionar
  pruebas registradas localmente. Separar credenciales, rutas, puertos, nombres
  de servicio y acceso por ambiente. El token de aprobación expresa alcance e
  intención; el sistema de permisos local determina quién puede invocar apply.

Ejemplo de configuración sintética. Sustituir rutas y hooks tras revisar el
entorno. `baseline` puede omitirse en una instalación nueva.

```json
{
  "environment": "synthetic",
  "data_root": "/srv/rifas-sintetico/data",
  "baseline": "/srv/rifas-sintetico/codigo-anterior",
  "allowed_signers": "/srv/rifas-sintetico/allowed_signers",
  "runtime_python": "/srv/rifas-sintetico/venv/bin/python",
  "hooks": {
    "drain": ["/srv/rifas-sintetico/hooks/drain"],
    "activate": ["/srv/rifas-sintetico/hooks/activate"],
    "ready": ["/srv/rifas-sintetico/hooks/ready"],
    "resume": ["/srv/rifas-sintetico/hooks/resume"]
  },
  "checks": {
    "sorteos": ["/srv/rifas-sintetico/hooks/test-sorteos"]
  }
}
```

Los hooks reciben `RIFAS_DATA_ROOT`, `RIFAS_RELEASE_ROOT` y
`RIFAS_DEPLOY_ENVIRONMENT`. Se ejecutan desde la raíz del código activo, o la de
datos si no hay código. Deben ser idempotentes, devolver un código distinto de
cero al fallar y terminar dentro de 120 segundos. El estado de mantenimiento
debe sobrevivir a la muerte del coordinador.

| Hook | Contrato |
| --- | --- |
| `drain` | Cerrar el paso público a escrituras, esperar peticiones en curso y detener escritores y trabajos de fondo de toda la instalación. Mantener la barrera cerrada. |
| `activate` | Arrancar o recargar WSGI desde `RIFAS_RELEASE_ROOT` con `RIFAS_DATA_ROOT` en el entorno del servicio. Con ruta vacía, detener el servicio. El endpoint privado puede responder, con la barrera pública y los trabajos aún cerrados. |
| `ready` | Verificar versión y lectura de un portal del servicio candidato o restaurado. Usar `deployment/smoke.py --base URL --version VERSION --slug ENTIDAD` desde una ruta absoluta del coordinador revisado. |
| `checks.sorteos` | Usar el mismo script con `--raffle-id ID --marker TEXTO` para un sorteo publicado y reservado de prueba. El hook debe ser de solo lectura. En CI, añadir compras concurrentes, fotos y pruebas de altas con fixtures. |
| `resume` | Reabrir el tráfico y reactivar los trabajos de manera idempotente. Con ruta vacía mantener la aplicación detenida. |

El proceso de Flask debe poder leer releases bajo el directorio privado y
acceder a los datos con el usuario documentado por el operador. La integración
con el supervisor y el proxy queda en los hooks del entorno.

## Simular, aplicar y recuperar

```sh
python -B -m deployment.deploy --config "$CONFIG" plan --artifact "$ARTEFACTO"
```

El plan no ejecuta hooks ni escribe en el destino. Requiere una copia estable
de las bases sin WAL, SHM ni journal activo; ante estos archivos, usar una
copia coherente concedida para la revisión. La comprobación autoritativa de
escritura ocurre con bloqueo y se repite tras el drenaje si el estado pudo
cambiar. El inventario exige coincidencia entre catálogo y disco.

Solo con aprobación expresa para **esa instalación y ese digest**:

```sh
python -B -m deployment.deploy --config "$CONFIG" apply --artifact "$ARTEFACTO" \
  --approve "apply:${ENTORNO}:${DIGEST}"
```

El coordinador registra resultados en `.rifas-deploy/events.jsonl`. Las
copias, el artefacto preparado y el código quedan en
`.rifas-deploy/runs/<id>/`. El código anterior se conserva como otro release
o como `baseline`. El respaldo previo incluye SQLite central, plantilla y
entidades. El alcance transaccional de esta fase se limita a código y bases.
Los hooks y paquetes deben preservar configuración y medios compartidos.
Mantener por separado la política de copia externa cifrada de datos, medios,
configuración y claves. Probar su restauración y definir retención antes de
operar una instalación real.

`pending.json` registra las fases duraderas. Antes de `committed`, un fallo
detectado revierte las bases y el código si hubo cambios. Una interrupción
brusca conserva el punto de recuperación. Para continuar con autorización de
recuperación independiente:

```sh
python -B -m deployment.deploy --config "$CONFIG" recover \
  --approve "recover:${ENTORNO}:${DIGEST}"
```

`recover` retoma la reversión con los escritores detenidos. Tras
`committed` o `rolled_back` solo reintenta reabrir el servicio. Esta
distinción protege las escrituras que pudieron entrar durante un intento de
`resume`. Si se detecta un defecto después de reabrir, preparar un release
correctivo compatible o reconciliar las escrituras antes de autorizar una
restauración manual. Ante inventario corrupto, fallo de restauración o
indisponibilidad del supervisor, conservar mantenimiento y escalar con el
registro de la ejecución.

## Contrato SQLite y siguiente fase

Sorteos reutiliza `migrate_raffles` desde el payload firmado. La plantilla y
cada entidad pasan por la misma transacción de migración, que incorpora las
columnas y la marca 2.4.0. El postflight comprueba integridad, claves foráneas,
contrato SQL de `raffles` contra el código y paridad de las tablas, índices
y disparadores de Sorteos con la plantilla. Una divergencia bloquea el corte.
El contrato es conservador ante diferencias de DDL y debe probarse con una
copia autorizada del esquema real. La plantilla sigue siendo la fuente del
alta de entidades.

Para OAuth 2.4.2, añadir una receta firmada, un migrador aditivo y su contrato
al registro SQLite, junto con una prueba funcional OIDC declarada. Usar
fixtures locales para el proveedor y validar callback, `state`, `nonce`,
aislamiento por entidad, vinculación y continuidad de OTP. Configurar
clientes, secretos y callbacks por entorno fuera del artefacto. La opción de
acceso arrancaría desactivada. El coordinador y el flujo de recuperación se
reutilizan.

## Pruebas aisladas

Ejecutar con las dependencias del runtime y `ssh-keygen` en PATH:

```sh
python -B -m unittest discover -s tests -v
```

La suite crea repositorio Git, clave de firma, instalaciones y bases de
prueba temporales. Incluye una interrupción SIGKILL tras la primera base
migrada. Validar los hooks específicos del supervisor, proxy, disco y
retención con autorización independiente antes de cualquier uso real.
