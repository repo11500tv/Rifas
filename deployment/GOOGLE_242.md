# Google OIDC 2.4.2 — recuperación e integración

## Origen de la recuperación

Archivo recibido: `rifas_google_242_candidato_revision.zip`.
SHA-256 del ZIP: `8e6dc0333f753122091beea130c3b868eac8302a41bbf47ddecf620b98416bc0`.
Se comprobó el CRC y el SHA-256 declarado de los 94 archivos del
manifiesto. La coincidencia acredita la integridad del contenido recibido.
El hash indicado en el manifiesto para el archivo de origen corresponde a
un artefacto diferente y no confirma por sí solo su procedencia.

La comparación fue contra el commit de GitHub
`1aab1f1a38afa93f5050b1eaa56525f44b30ec44` de
`phase-1/universal-deployment`.

| Comparación de los 94 archivos | Decisión |
| --- | --- |
| 74 idénticos | Se conservó el código versionado. |
| 12 módulos nuevos | Se recuperaron los 11 `participant_google_*.py` y `participant_session_shared.py`. |
| 3 pruebas nuevas | Se recuperaron sus escenarios HTTP y SQLite en `tests/test_google_oauth.py`. Las pruebas que dependían de una base externa ahora crean fixtures locales; las claves y direcciones son ficticias. |
| 1 nota nueva | Se dejó fuera `LEEME.txt`. |
| 4 archivos distintos | Se integró el registro condicional de Google de `__init__.py` preservando la configuración de la rama base. Se descartaron las sustituciones de `entity_smtp.py` y `update_center.py` que deshacían el uso de `RIFAS_DATA_ROOT`, y el cambio de espacios en `participant_raffle_purchases.py`. |

El manifiesto de revisión y el ZIP quedan fuera del repositorio. No se
incorporaron claves, bases, entornos virtuales ni valores de configuración
del servidor. Las rutas de pruebas recuperadas hacia una plantilla de
desarrollo quedaron fuera. La auditoría de literales y patrones no detectó
credenciales reales en los archivos incorporados; las sustituciones de
claves de sesión de las pruebas se rehacen con claves efímeras.

## Comportamiento

El portal ofrece Google como primera opción cuando se habilita, y conserva
registro y acceso con código por correo. El código base no incluye
transporte SMS de participantes. Se conserva su esquema y no se simula
entrega: el móvil es obligatorio al registrarse y queda con
`phone_verified=0`. Las URLs anteriores de OTP siguen disponibles.

La identidad estable de Google se guarda en la base de la entidad.
Un sujeto desconocido no autentica ni vincula cuentas por correo. La
vinculación y sustitución son explícitas, con sesión de esa entidad,
POST protegido contra CSRF, devolución OIDC y OTP al correo de la
cuenta existente. El OTP se consume en SQLite con la vinculación. El alta
usa un contexto provisional en la base de la entidad y guarda participante,
identidad y auditoría en una transacción. No se persisten tokens de Google.

Authlib usa un callback único fijo por instalación, Authorization Code,
PKCE S256, `state` y `nonce`. El callback verifica el flujo local antes del
intercambio y exige el ID token validado por Authlib. Los errores del
proveedor se traducen en respuestas genéricas. El cierre de sesión y los
accesos exitosos eliminan contextos provisionales de participante.

## Dependencias, SQLite y configuración

`requirements-google.txt` fija Authlib 1.9.9, joserfc 1.8.0 y requests
2.34.2. La receta `packages/google_oauth_2.4.2.json` incluye ese archivo
en el artefacto firmado. El preflight universal comprueba las versiones
del intérprete de ejecución. La preparación autorizada del runtime es
externa al coordinador. La plataforma conserva la versión 2.3.1 y Google
se versiona por separado como módulo 2.4.2.

Partir de una instalación con Sorteos 2.4.0 verificado en sus bases y plantilla.
La misma migración crea las cuatro tablas de Google y registra
`module_versions.google_oidc=2.4.2` en una transacción por base. El
coordinador aplica el contrato a las entidades existentes y a la
plantilla maestra, valida la paridad e incluye la base central en el
inventario y respaldo. La receta no migra la base central. El alta desde
la plantilla comprueba el contrato si Google está habilitado. El lote
rechaza un esquema de participantes que carezca de columnas requeridas.

Activación deshabilitada por defecto. La opción
`RIFAS_GOOGLE_OAUTH_ENABLED=1` exige configurar fuera de Git:

- `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` del cliente de la instalación.
- `GOOGLE_REDIRECT_URI` HTTPS con el prefijo público y el callback
  `/participantes/google/retorno`, idéntico al registrado en Google.
- `GOOGLE_BINDING_OTP_SECRET` independiente de la llave de sesión y de
  al menos 32 bytes.

No activar registros de depuración del cliente OAuth. Confirmar que los
logs del proxy no retienen parámetros del callback. Configurar la prueba
del paquete `google-oidc` en el perfil del coordinador universal antes de
autorizarlo. El lote mantiene Google desactivado hasta completar la prueba
de configuración y la autorización de activación.

## Evidencia local y condiciones pendientes

`python -B -m unittest discover -s tests -v` cubre rechazo por firma,
emisor, audiencia, nonce y caducidad con Authlib y JWT sintéticos.
También cubre sesiones, registro con teléfono, aislamiento entre
entidades, vinculación y sustitución explícitas, replay de OTP, OTP de
correo previo y clonación de la plantilla.

Para un futuro despliegue queda probar el callback y las cookies con un
cliente Google real en un entorno expresamente autorizado; verificar
HTTPS, proxy y prefijo públicos; comprobar entrega SMTP en ese entorno;
validar esquemas históricos y la plantilla autorizada; y ejecutar el
paquete y la prueba de restauración por el coordinador existente. No se ha
accedido a Arsys ni migrado bases reales. Esta evidencia local no acredita
un despliegue ni permite activar Google en staging o producción.
