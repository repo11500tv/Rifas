# Portabilidad de instalaciones — contrato de implementación

Estado: especificación de trabajo, **no implementación ni autorización de despliegue**.
Base: `feature/google-oauth-242`. Esta rama no modifica `main`, staging ni producción.

## Objetivo
El mismo código debe poder instalarse en otro dominio, cuenta Plesk o VPS sin referencias obligatorias a `dealfonso.com`, `dealfonsocom`, rutas de Arsys ni nombres concretos de unidades. `root` representa exclusivamente al administrador local del servidor; no es una identidad ni una ruta de instalación portable.

## Contrato de instalación
- Manifiesto único, validado con esquema y versión: dominio, raíz, usuario/grupo propietario, usuarios de servicio por entorno, rutas de datos, nombres de unidades, puertos, URL/prefijos públicos, proxy, venv, copias, control, marcadores, rutas externas, SMTP/OIDC mediante referencias a secretos externos.
- Prohibir secretos en manifiestos versionados, registros y respaldos exportables sin cifrado.
- Separar plantilla de instalación (sin datos) de manifiesto local generado; no incorporar valores del servidor de origen como valores predeterminados obligatorios.
- Nuevas instalaciones limpias y traslados con datos son procedimientos diferentes, con pruebas de recuperación.

## Responsabilidades
- Administrador del servidor: instalación de paquetes, cuentas, unidades systemd, proxy/Plesk, ACL y permisos restringidos.
- Usuario de proyecto configurable (actualmente `dealfonsocom`): Git, preparación de artefactos y ejecución autorizada del coordinador.
- Usuarios de servicio por entorno: mínimos privilegios y separación real de escrituras; no asumir aislamiento porque los nombres de servicio sean distintos.
- Ningún sudo genérico: acciones privilegiadas revisadas, limitadas por entorno y argumentos cerrados.

## Coordinador universal
- Mantener un solo motor para staging y producción y un solo procedimiento de despliegue: preflight, aprobación explícita por entorno, bloqueo, barrera de escritura, drenaje de procesos, copia consistente, migración, activación, sondas, reversión y auditoría.
- Sustituir rutas fijas en `deployment/backup_external.py` por inventario externo declarado en manifiesto; integrar en el flujo real del coordinador o eliminar módulo redundante.
- Distinguir copias de componentes gestionados y copias de archivos privilegiados externos; verificar hash, ACL, propiedad, permisos, symlinks, restauración y pruebas de recuperación, con mecanismo de privilegios acotado.
- Revisar y parametrizar `deployment/arsys/inspect-*-readonly.sh`, inventarios y ejemplos. Los ejemplos Arsys pueden conservar valores explícitos, pero el motor reutilizable no.
- Asegurar plantilla maestra SQLite, migraciones de entidades existentes y código coherentes para cualquier cambio de esquema.

## Bloqueos obligatorios antes de staging
- Resolver staging anidado bajo producción y permisos compartidos; validar aislamiento de todos los escritores (Gunicorn, coordinador, hooks y tareas).
- Identificar rutas reales Plesk/Nginx, puertos, prefijos, callbacks HTTPS y barrera por cada entrada.
- Completar perfiles sin `*_PENDING`, permisos, copia externa, reversión y pruebas automatizadas.
- Validar versión base de esquema y requisitos Google (SMTP, cliente OAuth real, secreto de vinculación, callback y dependencias) sin imprimir credenciales.
- No modificar staging sin autorización expresa. Producción requiere autorización independiente.

## Criterios de aceptación
1. Pruebas automatizadas de dos instalaciones sintéticas con usuarios, dominios, raíces, puertos y unidades diferentes, sin editar código.
2. Pruebas de denegación de acceso cruzado y de fallo seguro ante solapamientos, perfiles pendientes, secretos o privilegios excesivos.
3. Pruebas de copias externas y restauración íntegra, incluida recuperación tras interrupción.
4. Validaciones previas y posteriores mediante el mismo coordinador; no scripts particulares por versión.
5. Documentación de bootstrap del administrador y operación del usuario de proyecto; procedimiento reproducible para nueva instalación y traslado.
6. Evidencia de pruebas antes de solicitar autorización de despliegue.

## Orden de ejecución
Primero implementar parametrización y tests en esta rama. Después revisar PR, configurar el entorno real de Arsys y solicitar autorización para staging. Google 2.4.2 se probará allí; no tocar producción ni `/sorteos`.
