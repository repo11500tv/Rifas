# Criterios funcionales para liberar Google OAuth 2.4.2

## Objetivo de producto
Permitir que participantes se registren y accedan con Google en una entidad concreta sin perder el acceso alternativo por código de correo. Mantener saldos, reservas y operaciones separados por entidad.

## Confirmado en código (no equivale a prueba con Google real)
- El paquete declara módulo `google_oidc` versión 2.4.2 y conserva la versión general de plataforma 2.3.1.
- Hay pruebas sintéticas de registro, inicio de sesión, asociación y sustitución de cuenta Google, aislamiento por entidad, CSRF, tokens, migración y plantilla maestra.
- La inscripción con Google exige introducir móvil, pero el test actual exige explícitamente `phone_verified=0` y ausencia de SMS. **No se ha implementado ni demostrado verificación real del móvil**.
- La validación de Google real, SMTP, URL HTTPS, configuración OAuth y SMS requieren pruebas de integración autorizadas en staging.

## Criterios de aceptación pendientes
1. Acceso Google real: registro, retorno HTTPS, sesión, cierre de sesión y reentrada.
2. Registro con correo: código de acceso válido y expirado, y alternativa funcional sin Google.
3. Móvil: decidir y ejecutar la verificación obligatoria antes de marcar `phone_verified=1`; no confundir teléfono introducido con teléfono verificado.
4. Seguridad: evitar asociación automática de cuentas solo por coincidencia de correo; proteger contra replay, cambio de entidad y callback inválido.
5. Migraciones: plantilla maestra y entidades existentes con mismo esquema y versión.
6. Compatibilidad: confirmar que sorteos, reservas, créditos y Bizum no sufren regresiones.
7. Infraestructura: desplegar solo con autorización, aislamiento de staging y procedimiento único de reversión.

## Puerta de salida
No declarar 2.4.2 lista para producción hasta superar pruebas automáticas y pruebas reales de staging, incluyendo la verificación de móvil exigida por la especificación vigente.
