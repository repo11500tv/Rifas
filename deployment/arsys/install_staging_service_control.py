#!/usr/bin/python3
"""Aprovisionamiento transaccional del control systemd limitado a staging.

Solo instala el ejecutor y su regla sudoers; NO para/arranca servicios,
NO despliega aplicaciones, NO modifica producción. Ejecutar como root desde
una copia revisada y root-owned, nunca desde un checkout escribible por la app.
"""
import argparse
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile

DEST = Path("/usr/local/sbin/rifas-staging-service")
POLICY = Path("/etc/sudoers.d/61-rifas-staging-service")
UNIT = Path("/etc/systemd/system/rifas-pruebas.service")
USER = "dealfonsocom"
SERVICE = "rifas-pruebas.service"
HELPER = """#!/usr/bin/python3
import subprocess
import sys

ACTIONS = frozenset(("start", "stop", "status"))
if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
    raise SystemExit(64)
action = "is-active" if sys.argv[1] == "status" else sys.argv[1]
raise SystemExit(subprocess.run(
    ["/usr/bin/systemctl", action, "--", "rifas-pruebas.service"],
    cwd="/", env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
    close_fds=True, check=False,
).returncode)
"""
RULE = (
    "dealfonsocom ALL=(root) NOPASSWD: "
    "/usr/local/sbin/rifas-staging-service start, "
    "/usr/local/sbin/rifas-staging-service stop, "
    "/usr/local/sbin/rifas-staging-service status\n"
)


def require_safe_parent(path):
    for part in (Path("/"), *reversed(path.parents)):
        st = part.stat()
        if st.st_uid != 0 or st.st_mode & 0o022:
            raise RuntimeError(f"Directorio no protegido: {part}")
        if part.is_symlink():
            raise RuntimeError(f"Directorio enlazado: {part}")


def atomic_install(path, content, mode):
    fd, name = tempfile.mkstemp(prefix=".rifas-setup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(name, 0, 0)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "apply"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Se requiere root")
    if not UNIT.is_file() or UNIT.is_symlink():
        raise RuntimeError("No se ha verificado la unidad staging")
    if pwd.getpwnam(USER).pw_uid == 0:
        raise RuntimeError("Usuario de aplicación inválido")
    for target in (DEST, POLICY):
        require_safe_parent(target)
        if target.is_symlink():
            raise RuntimeError(f"Destino enlazado: {target}")
        if target.exists():
            raise RuntimeError(f"Ya existe {target}: no sobrescribir automáticamente")
    with tempfile.NamedTemporaryFile(mode="w", prefix="rifas-sudoers-", delete=False) as f:
        f.write(RULE)
        temp_policy = f.name
    try:
        check = subprocess.run(["/usr/sbin/visudo", "-cf", temp_policy], capture_output=True, text=True)
        if check.returncode:
            raise RuntimeError(f"Regla sudoers inválida: {check.stderr.strip()}")
    finally:
        os.unlink(temp_policy)
    print("Destino:", DEST)
    print("Sudoers:", POLICY)
    print("Unidad única:", SERVICE)
    print("Usuario autorizado:", USER)
    print("Acciones: start, stop, status")
    if args.action == "plan":
        print("PLAN: sin cambios")
        return
    try:
        atomic_install(DEST, HELPER, 0o755)
        atomic_install(POLICY, RULE, 0o440)
        subprocess.run(["/usr/sbin/visudo", "-cf", str(POLICY)], check=True)
        subprocess.run(["/usr/sbin/visudo", "-c"], check=True)
    except Exception:
        # Solo se eliminan los dos destinos que esta ejecución creó.
        POLICY.unlink(missing_ok=True)
        DEST.unlink(missing_ok=True)
        raise
    print("INSTALADO. No se ha ejecutado ninguna acción sobre servicios.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
