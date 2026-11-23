# Contrato de roles y autorizaciones — Rifas Benéficas

Estado: **política versionada y pruebas automatizadas; conexión con identidad real y despliegue pendiente**. No implica autorización para cambiar staging ni producción.

## Principio de control

El propietario del dominio es el responsable de su instalación y autoriza cualquier operación que cambie código o datos. El administrador del servidor prepara la infraestructura y delega capacidades específicas; no necesita intervenir en actualizaciones ordinarias. El administrador de entidad no administra el servidor ni la plataforma.

| Rol | Ámbito | Operaciones |
| --- | --- | --- |
| Administrador del servidor | Alojamiento | Aprovisionar usuario, supervisor, proxy/TLS, aislamiento y delegaciones acotadas. No obtiene por ese hecho autorización para desplegar. |
| Propietario del dominio | Instalación concreta | Configurar la instalación, gestionar la plataforma, planificar, autorizar y ejecutar actualizaciones y recuperación, respaldar/restaurar datos propios. |
| Administrador de plataforma | Interfaz administrativa | Gestionar plataforma y entidades según permisos de aplicación; no autoriza despliegues ni administra infraestructura. |
| Administrador de entidad | Una entidad | Operaciones de esa entidad, sin acceso a otras entidades, despliegue o servidor. |
| Participante | Cuenta propia | Participar, según las reglas de negocio. |
| Servicio web | Proceso de ejecución | Atender solicitudes, sin escribir perfiles, firmas, artefactos ni controles del coordinador. |

## Autorización de operaciones

- `plan` es de solo lectura y corresponde al propietario del dominio; no se interpreta como aprobación de `apply`.
- `apply`, `recover`, `intervene` y `recover-intervention` requieren propietario del dominio, instalación y entorno correctos, **y firma válida, de un solo uso, con digest, operación, plazo y ejecución**. La verificación criptográfica existente reside en `deployment/approval.py`; `deployment/authorization_policy.py` expresa la política de roles, **no sustituye** esa verificación.
- La firma de artefactos de publicación es independiente de la firma del propietario que aprueba la instalación. Las claves privadas no se guardan en el servidor de destino.
- `root` no ejecuta el coordinador de actualizaciones ordinarias. Las operaciones de Nginx, systemd y cuentas se presentan como instrucciones de aprovisionamiento al administrador del servidor, sujetas a aprobación independiente.
- La cuenta de ejecución web y la cuenta operadora del dominio deben tener UIDs diferentes. Staging y producción también necesitan aislamiento efectivo de escrituras. El simple control de roles Python no constituye una barrera del sistema operativo.

## Requisitos antes de habilitar la política en producción o staging

1. **Identidad verificable**: enlazar el rol `domain_owner` a una identidad autenticada del operador y al dominio efectivo; no aceptar `role`, `domain` ni `signature_verified` desde un formulario, petición HTTP o variable no confiable.
2. **Comprobación de permisos efectiva**: distinguir cuenta del dominio y servicio; servicio con acceso de lectura al selector, sin escritura en control, checkout, claves o autorizaciones; Nginx solo lectura del marcador.
3. **Integración sin duplicación**: invocar la política desde los puntos de entrada del coordinador universal; conservar `approval.verified()` y los bloqueos existentes. No crear otro coordinador ni mecanismo paralelo.
4. **Aprovisionamiento reversible**: el administrador del servidor prepara exclusivamente cuentas, rutas y supervisor, y documenta lo que ha delegado. La cuenta del dominio puede ejecutar `plan` y las operaciones autorizadas sin `root`.
5. **Pruebas negativas**: operador de staging, proceso web y tareas programadas no pueden escribir en producción ni `/sorteos/`. Verificar firmas caducadas, reutilizadas, digest distinto, dominio distinto, entidad distinta, rol equivocado y selector inaccesible.
6. **Validación final**: ejecutar CI, ensayo sintético de respaldo/restauración y aprobación expresa antes de cualquier modificación real de staging. Producción requiere otra aprobación.

## Código relacionado

- `deployment/authorization_policy.py`: matriz denegar-por-defecto, ámbito de dominio y entidad, requisito de firma.
- `deployment/approval.py`: firma SSHSIG y restricciones de operación, entorno, instalación, digest, nonce y caducidad.
- `deployment/role_check.py`: comprobación de UID y permisos observables.
- `tests/test_authorization_policy.py`, `tests/test_role_check.py`: pruebas unitarias.
- `.github/workflows/deployment-role-checks.yml`: ejecución automatizada en GitHub.

**No declarar la integración terminada** hasta conectar y probar las identidades reales, la autorización del coordinador y el aislamiento del sistema operativo.
