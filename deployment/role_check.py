"""Comprobaciones de privilegios sin root para una instalación Rifas.

Ejecutar como propietario del dominio o como identidad de servicio, nunca como
root. No cambia permisos ni servicios. El perfil es el JSON de hooks vigente.
"""
import argparse
import json
import os
import stat
from pathlib import Path


def _path(value):
    path = Path(value)
    if not path.is_absolute() or path == Path("/") or path.is_relative_to("/root"):
        raise ValueError(f"Ruta de instalación no permitida: {path}")
    return path


def _readable(path):
    return path.is_file() and os.access(path, os.R_OK)


def _writable_directory(path):
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def check(settings, role):
    if os.geteuid() == 0:
        raise ValueError("No ejecutar esta verificación como root")
    scope = settings["scope"]
    data = _path(scope["data_root"])
    control = _path(scope["control_root"])
    gate = _path(settings["gate"])
    selector = _path(settings["target"])
    if scope["environment"] not in ("staging", "production"):
        raise ValueError("El perfil debe identificar staging o producción")
    if gate.parent != control or selector.parent != control or gate == selector:
        raise ValueError("Barrera y selector deben pertenecer al control de su entorno")
    if data == control or data.is_relative_to(control) or control.is_relative_to(data):
        raise ValueError("Control y datos no pueden solaparse")
    failures = []
    def require(ok, message):
        if not ok:
            failures.append(message)
    require(data.is_dir(), "La raíz de datos no existe")
    require(control.is_dir(), "El directorio de control no es accesible")
    if role == "service":
        require(_readable(selector), "El servicio no puede leer el selector release.json")
        require(not _writable_directory(control), "El servicio puede modificar el control")
        if selector.exists():
            mode = selector.stat().st_mode
            require(stat.S_ISREG(mode) and not selector.is_symlink(), "Selector no regular o enlazado")
            require(not mode & stat.S_IWOTH, "Selector escribible por cualquiera")
        for name in ("allowed_signers", "approval_signers"):
            # Los archivos de confianza son opcionales en el perfil de hooks.
            if name in settings:
                require(not os.access(_path(settings[name]), os.W_OK),
                        f"El servicio puede modificar {name}")
    elif role == "owner":
        require(_writable_directory(data), "El propietario no puede mantener los datos")
        require(_writable_directory(control), "El propietario no puede actualizar el control")
    else:
        raise ValueError("Rol desconocido")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--role", required=True, choices=("owner", "service"))
    args = parser.parse_args()
    try:
        errors = check(json.loads(args.config.read_text()), args.role)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, f"BLOQUEADO: {exc}\n")
    if errors:
        parser.exit(1, "BLOQUEADO:\n- " + "\n- ".join(errors) + "\n")
    print(f"OK: permisos básicos para rol {args.role}. No se han realizado cambios.")
    print("ATENCIÓN: no sustituye las pruebas negativas de aislamiento entre entornos.")


if __name__ == "__main__":
    main()
