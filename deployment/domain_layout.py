"""Verificación de que TODOS los recursos de Rifas pertenecen al dominio.

Se ejecuta antes de cualquier migración. No cambia archivos ni servicios.
Se admite el directorio del dominio, pero no rutas externas ni enlaces
simbólicos que escapen de él. Las rutas inexistentes se comprueban por
resolución de sus padres existentes.
"""
import argparse
import json
from pathlib import Path


def validate_path(domain_root, candidate):
    domain = Path(domain_root)
    path = Path(candidate)
    if not domain.is_absolute() or not path.is_absolute():
        raise ValueError("Las rutas deben ser absolutas")
    domain = domain.resolve(strict=True)
    if not domain.is_dir() or domain == Path("/") or not domain.is_relative_to("/var/www/vhosts"):
        raise ValueError("Raíz de dominio inválida")
    resolved = path.resolve(strict=False)
    if resolved == domain or not resolved.is_relative_to(domain):
        raise ValueError(f"Ruta fuera del dominio: {path}")
    return resolved


def validate_profile(profile, domain_root):
    """Valida rutas de despliegue y hooks, incluidos recursos de confianza."""
    keys = ("data_root", "control_root", "allowed_signers", "approval_signers",
            "gate", "target", "checkout", "venv", "backup_root")
    found = {}
    for key in keys:
        if key in profile:
            found[key] = str(validate_path(domain_root, profile[key]))
    scope = profile.get("scope", {})
    for key in ("data_root", "baseline", "control_root"):
        if key in scope:
            found["scope." + key] = str(validate_path(domain_root, scope[key]))
    gunicorn = profile.get("gunicorn", {})
    if "python" in gunicorn:
        found["gunicorn.python"] = str(validate_path(domain_root, gunicorn["python"]))
    for key in ("backup_components", "protected_paths"):
        # protected_paths puede contener instalaciones protegidas externas
        # al dominio: se valida su forma, pero NO se les concede acceso.
        if key == "protected_paths":
            continue
        for item in profile.get(key, []):
            if isinstance(item, dict):
                candidate = item.get("path")
                if candidate is None:
                    raise ValueError("Componente de respaldo sin ruta")
            else:
                candidate = item
            validate_path(domain_root, candidate)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain-root", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        validated = validate_profile(json.loads(args.profile.read_text()), args.domain_root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"BLOQUEADO: {exc}\n")
    print(json.dumps({"status": "OK", "domain_root": args.domain_root, "paths": validated},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
