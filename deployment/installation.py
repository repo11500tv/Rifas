"""Validated, server-independent installation identity (no credentials)."""
import json
import re
from pathlib import Path

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_-]*$")
DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")


def _absolute(value, field):
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"{field} debe ser una ruta absoluta")
    path = Path(value)
    if str(path) != value or ".." in path.parts or path == Path("/"):
        raise ValueError(f"{field} no es una ruta canónica")
    return path


def load_installation(filename):
    """Load a versioned local manifest; reject unknown fields and embedded secrets."""
    path = Path(filename)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Manifiesto ausente o simbólico")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"format", "domain", "project", "environments"}:
        raise ValueError("Campos de instalación incompatibles")
    if data["format"] != "rifas-installation-v1" or not isinstance(data["domain"], str) or not DOMAIN.fullmatch(data["domain"]):
        raise ValueError("Formato o dominio incorrecto")
    project = data["project"]
    if not isinstance(project, dict) or set(project) != {"user", "group", "root"}:
        raise ValueError("Proyecto incompleto")
    for field in ("user", "group"):
        if not isinstance(project[field], str) or not IDENTIFIER.fullmatch(project[field]):
            raise ValueError(f"Identificador {field} inválido")
    _absolute(project["root"], "project.root")
    envs = data["environments"]
    if not isinstance(envs, dict) or set(envs) != {"staging", "production"}:
        raise ValueError("Se requieren staging y production")
    paths = []
    units = []
    ports = []
    for name, config in envs.items():
        if not isinstance(config, dict) or set(config) != {"root", "service_user", "unit", "port", "external_files"}:
            raise ValueError(f"Campos de {name} incompatibles")
        paths.append(_absolute(config["root"], name + ".root"))
        if not isinstance(config["service_user"], str) or not IDENTIFIER.fullmatch(config["service_user"]):
            raise ValueError("Usuario de servicio inválido")
        unit = config["unit"]
        if not isinstance(unit, str) or not re.fullmatch(r"[a-zA-Z0-9_.@-]+\.service", unit):
            raise ValueError("Unidad inválida")
        units.append(unit)
        if type(config["port"]) is not int or not 1024 <= config["port"] <= 65535:
            raise ValueError("Puerto inválido")
        ports.append(config["port"])
        files = config["external_files"]
        if not isinstance(files, list) or not files or len(files) != len(set(map(str, files))):
            raise ValueError("Inventario externo vacío o duplicado")
        for entry in files:
            _absolute(entry, "external_files")
    if len(set(units)) != 2 or len(set(ports)) != 2:
        raise ValueError("Unidades y puertos deben ser independientes")
    if paths[0] == paths[1] or paths[0].is_relative_to(paths[1]) or paths[1].is_relative_to(paths[0]):
        raise ValueError("Los entornos no pueden solaparse")
    if envs["staging"]["service_user"] == envs["production"]["service_user"]:
        raise ValueError("Los entornos requieren identidades de servicio distintas")
    return data

def validate_deployment_profile(profile):
    """Bind a deployment profile to its declared installation (fail closed).

    Optional for historical profiles; mandatory for newly provisioned profiles.
    This check does not grant permission to deploy or replace structural review.
    """
    manifest_path = profile.get("installation_manifest")
    if manifest_path is None:
        return None
    installation = load_installation(manifest_path)
    environment = profile.get("environment")
    if environment not in installation["environments"]:
        raise ValueError("Entorno ajeno al manifiesto de instalación")
    declared = installation["environments"][environment]
    if Path(profile.get("data_root", "")) != Path(declared["root"]):
        raise ValueError("Raíz de despliegue diferente del manifiesto")
    structure = profile.get("structure")
    if not isinstance(structure, dict):
        raise ValueError("El manifiesto requiere revisión estructural")
    for field, expected in (
        ("unit", declared["unit"]),
        ("port", declared["port"]),
        ("working_directory", declared["root"]),
    ):
        if structure.get(field) != expected:
            raise ValueError(f"Desajuste estructural en {field}")
    if structure.get("peer_unit") != installation["environments"][
        "production" if environment == "staging" else "staging"
    ]["unit"]:
        raise ValueError("Unidad par distinta del manifiesto")
    if not profile.get("control_root"):
        raise ValueError("Falta el directorio de control")
    return installation
