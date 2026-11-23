#!/usr/bin/env python3
"""Control privilegiado mínimo de un servicio systemd autorizado.

Instalar root:root 0755 en una ruta protegida, FUERA del árbol modificable
por el usuario de la aplicación. No recibe nombres de servicios ni rutas
del solicitante. Configuración de unidad fijada por el administrador.
"""
import os
import subprocess
import sys

# Al instalar, sustituir este literal por la unidad exacta del entorno.
UNIT = "rifas-pruebas.service"
ACTIONS = {"stop": "stop", "start": "start", "status": "is-active"}

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        print("Uso: rifas-service-control {stop|start|status}", file=sys.stderr)
        return 64
    # No ejecutar código desde la instalación Flask ni invocar un shell.
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"}
    action = ACTIONS[sys.argv[1]]
    result = subprocess.run(
        ["/usr/bin/systemctl", action, "--", UNIT],
        env=env, cwd="/", close_fds=True, check=False,
    )
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
