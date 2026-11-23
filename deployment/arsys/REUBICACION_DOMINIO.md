# Reubicación obligatoria bajo dealfonso.com

**Regla invariable:** ninguna instalación Rifas debe depender de directorios de trabajo, checkout, estado, perfiles, firmas, claves públicas, respaldos o venv ubicados fuera de `/var/www/vhosts/dealfonso.com/`. Los binarios del sistema operativo y las unidades de systemd son infraestructura externa, no datos propios de Rifas. No modificar `/sorteos`.

## Distribución propuesta

- `/var/www/vhosts/dealfonso.com/rifas-deployment/staging/`: checkout, venv, config, control, trust, backups y estado del coordinador de pruebas.
- `/var/www/vhosts/dealfonso.com/rifas-deployment/production/`: recursos de despliegue independientes para producción, **sin migrarlos ni activarlos en la fase de staging**.
- `/var/www/vhosts/dealfonso.com/rifas/staging/prueba_231/`: instalación de pruebas existente.
- `/var/www/vhosts/dealfonso.com/rifas/`: instalación de producción existente.

La ubicación `rifas-deployment` es hermana de `rifas` **dentro del mismo dominio** porque el coordinador exige que el control no esté dentro de la raíz restaurable de la instalación. Ponerlo en `rifas/deployment` solaparía los ámbitos y comprometería la reversión.

## Secuencia obligatoria para staging

1. El administrador de infraestructura realiza un inventario **de solo lectura** de `/srv/rifas-deploy/staging`, los archivos abiertos, enlaces, permisos y las referencias efectivas de systemd/Nginx; confirma rutas y espacio libre. No asumir que los ejemplos son perfiles reales.
2. El propietario del dominio aprueba la operación de migración de infraestructura en staging. Generar respaldo íntegro y verificable, con manifest y hashes, **antes de mover o copiar**. Registrar la ubicación y método de recuperación.
3. Preparar el directorio nuevo y las identidades distintas de propietario y servicio web. No usar chmod 777 ni copiar claves privadas al destino. Copiar preservando metadatos y validar hashes; **no eliminar el origen**.
4. Revisar todas las referencias efectivas, incluidos supervisor, hooks, checkout, venv, perfiles, estado, selector y barrera. Los entornos virtuales pueden contener rutas absolutas: recrearlos de forma reproducible, no suponer que basta con moverlos.
5. Verificar la política `deployment/domain_layout.py` para perfiles de staging; ejecutar el coordinador universal con el mismo procedimiento de preflight, respaldo, rollback y postflight.
6. **Antes de activar**: demostrar desde el UID del proceso web y desde el UID operador que no existe capacidad de escritura sobre producción ni `/sorteos`. Mientras el servicio comparta UID con producción, la migración debe detenerse.
7. Tras pruebas positivas, cambiar únicamente la unidad de staging y los permisos delegados necesarios. Comprobar respuesta privada y pública, barrera y selector, permisos negativos, reinicio y reversión. Mantener copia del origen hasta aceptación.
8. No activar ni modificar producción, sus unidades, sus perfiles ni sus datos. La migración de producción requiere autorización independiente.

## Estado de ejecución

**Solo se han actualizado los archivos de GitHub.** Este documento no acredita que el servidor esté migrado, que los perfiles estén activos ni que el aislamiento se haya comprobado. No ejecutar un `mv` directo desde `/srv`: el estado real todavía no está inventariado y podría romper la unidad activa.
