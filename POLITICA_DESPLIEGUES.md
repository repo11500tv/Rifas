# Política permanente de modificaciones y despliegues — Rifas Benéficas

**Referencia obligatoria para cualquier modificación futura de la aplicación.**
Este documento es la norma operativa del proyecto, no una prueba de que los controles estén instalados en Arsys. Consultarlo junto con [deployment/README.md](deployment/README.md) y [deployment/arsys/README.md](deployment/arsys/README.md) antes de preparar cualquier cambio.

## Reglas invariables

1. **Un solo procedimiento universal y reutilizable** para staging y producción: `deployment.deploy`, con configuración, firmas, validaciones, copias, migraciones, pruebas y recuperación parametrizadas por entorno y paquete. No crear instaladores, coordinadores o secuencias de comprobaciones independientes para cada versión.
2. **Autorización expresa por entorno.** No instalar, migrar, reiniciar, cambiar configuración ni ejecutar pruebas destructivas en staging o producción sin autorización explícita para ese entorno. Autorizar staging nunca autoriza producción. La aplicación histórica `/sorteos/` queda fuera de alcance salvo autorización específica.
3. **Verificación previa y posterior automatizada**, bajo bloqueo: identidad de instalación, rutas canónicas, ámbito de escritura, servicios, puertos, firmas e integridad del artefacto, dependencias, versiones, bases, espacio, coherencia y sondas funcionales. Si falla un control, no continuar.
4. **Respaldo y reversión obligatorios** antes de cambios: captura íntegra y verificable de los componentes afectados, bases SQLite mediante copia coherente, registro de ejecución y procedimiento de recuperación probado. No restaurar datos sobre escrituras nuevas confirmadas tras reabrir el servicio.
5. **Coherencia de entidades y plantilla maestra.** Cualquier cambio estructural o funcional que afecte a nuevas entidades debe actualizar el código, la migración de las entidades existentes, la plantilla maestra SQLite y el procedimiento de alta de entidades. Verificar equivalencia y no declarar el cambio terminado sin ello.
6. **Pruebas específicas por paquete** declaradas en su receta y ejecutadas por el coordinador universal. En producción, las sondas funcionales serán seguras y no destructivas.
7. **Artefacto único, versionado, revisado y firmado**, probado primero en staging y promocionado sin reconstruirlo. El cambio de código, la autorización operativa y las claves de firma tienen responsabilidades separadas.
8. **No confundir controles de software con aislamiento del sistema operativo.** El mismo usuario Unix y la ubicación anidada de staging dentro de producción no prueban aislamiento. Las rutas y barreras del coordinador reducen errores de operación, pero no impiden por sí solas que un proceso con permisos compartidos escriba fuera de su ámbito. Documentar y resolver los riesgos efectivos antes de un ensayo que los requiera.
9. **No duplicar diagnósticos manuales.** Priorizar el estado, plan, auditoría y pruebas del coordinador. Si falta una comprobación recurrente, incorporarla al procedimiento común, no pedir una cadena de comandos ad hoc en cada release.
10. **Trazabilidad en GitHub.** Conservar receta, código, pruebas, documentación, SHA del commit, digest del artefacto, resultado de CI y evidencia de staging. Los secretos, credenciales y datos personales no se incorporan al repositorio.

## Secuencia de trabajo para cada modificación

1. Consultar esta política y las guías enlazadas; identificar estado real de instalación, versión, rama y alcance autorizado.
2. Definir cambio, receta, migración, actualización de plantilla/alta de entidad cuando corresponda, pruebas y reversión.
3. Revisar el cambio en GitHub y ejecutar CI con datos sintéticos.
4. Preparar y firmar un único artefacto; ejecutar `plan` de solo lectura para el entorno autorizado.
5. Confirmar que la instalación real cumple los requisitos de aislamiento, barrera, drenaje, copias y recuperación. **Si no los cumple, registrar el bloqueo y corregir el procedimiento o aprovisionamiento común; no eludir controles.**
6. Con autorización expresa del entorno y aprobación firmada específica de la operación, ejecutar `apply` universal; registrar resultado, pruebas y respaldos.
7. Solo después de validar staging, solicitar **otra** autorización para producción. No inferirla.
8. Documentar resultado, incidencias y mejoras en GitHub para reutilizarlas en la siguiente modificación.

## Estado conocido al 23-11-2026

- GitHub contiene el coordinador universal y la receta `deployment/packages/google_oauth_2.4.2.json` en la rama `feature/google-oauth-242`.
- En Arsys se ha observado `deployment/deploy.py` en `/rifas/staging/prueba_231`, pero no `deployment/approval.py` ni la receta Google OAuth 2.4.2. La ausencia de `.rifas-deploy` en las ubicaciones comprobadas **no demuestra** que no existan registros históricos de otro mecanismo.
- Producción no presenta esos archivos en las ubicaciones comprobadas. Las bases centrales y plantillas de staging y producción son archivos independientes; los servicios comparten propietario Unix y staging está anidado en la raíz de producción.
- **Google OAuth 2.4.2 no consta desplegado en staging.** Existe autorización del usuario para preparar y desplegar **solo en staging**, siempre que se satisfagan las validaciones. Producción no está autorizada.
- Los perfiles Arsys de la guía contienen parámetros pendientes: no asumir que son configuraciones activas ni que los dos despliegues anteriores utilizaron el coordinador actual.

## Comandos de referencia

Usar exclusivamente con perfiles revisados y artefactos firmados, conforme a [la guía universal](deployment/README.md):

```sh
python -B -m deployment.deploy --config "$CONFIG" status
python -B -m deployment.deploy --config "$CONFIG" plan --artifact "$ARTEFACTO"
# apply requiere autorización específica firmada para entorno, instalación y digest:
python -B -m deployment.deploy --config "$CONFIG" apply --artifact "$ARTEFACTO" --approve "$APROBACION"
```

No ejecutar `apply` a partir de este documento sin completar la preparación y aprobación descritas en las guías.
