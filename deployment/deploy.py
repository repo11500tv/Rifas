"""Coordinador de releases Rifas. Ejecutar con python -m deployment.deploy."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

from deployment import schema
from deployment.artifact import IDENTITY, MANIFEST, NAMESPACE, SIGNATURE, digest, payload_path, platform_version
from deployment.backup_sqlite import backup_database, sha256, verify_sqlite, write_inventory

HOOKS = {"drain", "activate", "ready", "resume"}


def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    sync(path.parent)


def validate_artifact(bundle, trusted_signers):
    manifest_path = bundle / MANIFEST
    signature = bundle / SIGNATURE
    if any(not path.is_file() or path.is_symlink() for path in (manifest_path, signature)):
        raise ValueError("Faltan manifiesto o firma regulares")
    if manifest_path.stat().st_size > 256_000 or signature.stat().st_size > 20_000:
        raise ValueError("Manifiesto o firma demasiado grandes")
    raw = manifest_path.read_bytes()
    subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(trusted_signers), "-I", IDENTITY,
         "-n", NAMESPACE, "-s", str(signature)], input=raw, check=True,
        stdout=subprocess.DEVNULL, timeout=20,
    )
    manifest = json.loads(raw)
    if set(manifest) != {"format", "package", "version", "commit", "recipe", "files",
                         "platform_from", "platform_to", "schema", "migration", "checks"} or manifest["format"] != 1:
        raise ValueError("Formato de manifiesto incompatible")
    version = r"[0-9]+\.[0-9]+\.[0-9]+"
    if (not re.fullmatch(r"[a-f0-9]{40}", manifest["commit"])
            or not re.fullmatch(r"[a-z][a-z0-9_-]*", manifest["package"])
            or not re.fullmatch(r"deployment/packages/[a-zA-Z0-9_.-]+\.json", manifest["recipe"])
            or not re.fullmatch(version, manifest["version"])
            or not re.fullmatch(version, manifest["platform_to"])
            or not isinstance(manifest["platform_from"], list) or not manifest["platform_from"]
            or any(item is not None and not re.fullmatch(version, item) for item in manifest["platform_from"])
            or not isinstance(manifest["checks"], list) or not manifest["checks"]
            or len(set(manifest["checks"])) != len(manifest["checks"])
            or manifest["schema"] not in schema.CONTRACTS
            or manifest["migration"] not in schema.MIGRATIONS):
        raise ValueError("Metadatos de paquete incompatibles")
    if manifest["migration"] == "sorteos-2.4.0" and (
        manifest["package"], manifest["version"], manifest["checks"]
    ) != ("sorteos", "2.4.0", ["sorteos"]):
        raise ValueError("Contrato de Sorteos 2.4.0 incompatible")
    payload = bundle / "payload"
    if payload.is_symlink() or not payload.is_dir():
        raise ValueError("Payload inválido")
    files = manifest["files"]
    required = {"wsgi.py", "platform_app/__init__.py", "platform_app/raffle_schema.py"}
    if manifest["migration"]:
        required.add("platform_app/raffle_migration.py")
    if not isinstance(files, dict) or not required <= files.keys():
        raise ValueError("Faltan archivos obligatorios")
    observed = set()
    for path in payload.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"Entrada irregular en el artefacto: {path.name}")
        if path.is_file():
            observed.add(path.relative_to(payload).as_posix())
    if observed != files.keys():
        raise ValueError("El inventario del artefacto no coincide")
    for name, expected in files.items():
        path = payload / payload_path(name)
        if not re.fullmatch(r"[a-f0-9]{64}", expected) or sha256(path) != expected:
            raise ValueError(f"SHA-256 incorrecto: {name}")
        if path.suffix == ".py":
            compile(path.read_bytes(), str(path), "exec")
    if platform_version((payload / "platform_app/__init__.py").read_bytes()) != manifest["platform_to"]:
        raise ValueError("Versión de código incompatible")
    return manifest, digest(raw)


class Deployment:
    def __init__(self, config):
        self.config = config
        self.name = config["environment"]
        if self.name not in {"synthetic", "staging", "production"}:
            raise ValueError("Entorno desconocido")
        self.root = Path(config["data_root"]).resolve(strict=True)
        self.state = self.root / ".rifas-deploy"
        self.signers = Path(config["allowed_signers"]).resolve(strict=True)
        if (self.root.is_relative_to("/root") or self.root == Path("/") or not self.root.is_dir()
                or not self.signers.is_file() or self.state.is_symlink()):
            raise ValueError("Rutas de instalación no admitidas")
        self.hooks = config["hooks"]
        self.checks = config["checks"]
        self.runtime_python = Path(config["runtime_python"])
        if not self.runtime_python.is_absolute() or not os.access(self.runtime_python, os.X_OK):
            raise ValueError("El intérprete runtime_python debe ser absoluto y ejecutable")
        self.baseline = None
        if config.get("baseline"):
            self.baseline = Path(config["baseline"]).resolve(strict=True)
            if self.baseline.is_relative_to("/root") or self.baseline.is_relative_to(self.state):
                raise ValueError("Ruta de versión anterior no admitida")
        if set(self.hooks) != HOOKS:
            raise ValueError("Se requieren drain, activate, ready y resume")
        for command in (*self.hooks.values(), *self.checks.values()):
            if (not isinstance(command, list) or not command
                    or any(not isinstance(item, str) for item in command)
                    or not Path(command[0]).is_absolute() or not os.access(command[0], os.X_OK)):
                raise ValueError("Los hooks requieren argv con ejecutable absoluto")
        marker = self.state / "environment"
        if marker.is_symlink() or not marker.is_file() or marker.read_text().strip() != self.name:
            raise ValueError("La raíz no está registrada para el entorno de la configuración")
        self.pending = self.state / "pending.json"
        self.current = self.state / "current"

    def event(self, phase, **details):
        record = {"at": datetime.now(timezone.utc).isoformat(), "environment": self.name,
                  "phase": phase, **details}
        with (self.state / "events.jsonl").open("a") as log:
            log.write(json.dumps(record, sort_keys=True) + "\n")
            log.flush()
            os.fsync(log.fileno())

    @contextmanager
    def lock(self):
        if (not self.state.is_dir() or self.state.stat().st_uid != os.geteuid()
                or self.state.stat().st_mode & 0o077):
            raise ValueError("Preaprovisionar .rifas-deploy con propietario operativo y modo 0700")
        with (self.state / "lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Otro despliegue tiene el bloqueo") from None
            yield

    def active(self):
        if self.current.is_symlink():
            target = self.current.resolve(strict=True)
            if (target.parent.parent.parent != self.state or target.parent.parent.name != "runs"
                    or target.name != "payload"):
                raise ValueError("Puntero de release fuera del inventario")
            return target
        if self.current.exists():
            raise ValueError("El puntero current debe ser simbólico")
        return self.baseline

    def point_to(self, target):
        if target is None or target == self.baseline:
            self.current.unlink(missing_ok=True)
        else:
            temporary = self.state / f".current-{uuid4().hex}"
            temporary.symlink_to(target)
            os.replace(temporary, self.current)
        sync(self.state)

    def hook(self, label, command, active):
        self.event("hook_started", hook=label)
        process_env = {**os.environ, "RIFAS_DATA_ROOT": str(self.root),
                       "RIFAS_DEPLOY_ENVIRONMENT": self.name,
                       "RIFAS_RELEASE_ROOT": str(active) if active else "",
                       "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            subprocess.run(command, cwd=active or self.root, env=process_env, timeout=120, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            self.event("hook_failed", hook=label, error=type(error).__name__,
                       returncode=getattr(error, "returncode", None))
            raise
        self.event("hook_passed", hook=label)

    def preflight(self, bundle, *, dry):
        manifest, fingerprint = validate_artifact(bundle, self.signers)
        active = self.active()
        prior = platform_version((active / "platform_app/__init__.py").read_bytes()) if active else None
        if prior not in manifest["platform_from"]:
            raise ValueError(f"Versión de plataforma de origen incompatible: {prior}")
        if not set(manifest["checks"]) <= self.checks.keys():
            raise ValueError("Faltan pruebas funcionales declaradas")
        subprocess.run(
            [str(self.runtime_python), "-I", "-B", "-c",
             "import flask, werkzeug, PIL.Image, reportlab, cryptography.fernet, gunicorn"],
            timeout=30, check=True,
        )
        expected = schema.expected_raffles(bundle / "payload")
        databases = schema.validate(
            self.root, manifest["schema"], expected=expected,
            target=manifest["migration"] is None, dry=dry,
        )
        payload_size = sum((bundle / "payload" / name).stat().st_size for name in manifest["files"])
        database_size = sum(
            file.stat().st_size for relative in databases
            for file in (self.root / relative, self.root / (str(relative) + "-wal"))
            if file.is_file()
        )
        if shutil.disk_usage(self.state if self.state.is_dir() else self.root).free < payload_size + 2 * database_size:
            raise ValueError("Espacio insuficiente para release y respaldo SQLite")
        return manifest, fingerprint, databases, active, expected

    def plan(self, bundle):
        if self.pending.exists():
            raise ValueError("Hay una ejecución pendiente de recuperar")
        manifest, fingerprint, databases, _, _ = self.preflight(bundle, dry=True)
        return {"environment": self.name, "mode": "read-only", "digest": fingerprint,
                "package": manifest["package"], "commit": manifest["commit"],
                "databases": [str(path) for path in databases], "checks": manifest["checks"]}

    def approve(self, operation, fingerprint, approval):
        if approval != f"{operation}:{self.name}:{fingerprint}":
            raise ValueError("Se requiere aprobación explícita para operación, entorno y digest")

    def checkpoint(self, journal, phase):
        journal["phase"] = phase
        atomic_json(self.pending, journal)
        self.event(phase, run=journal["run"], digest=journal["digest"])

    def backup(self, paths, folder):
        folder.mkdir(mode=0o700)
        records = []
        for relative in paths:
            destination = folder / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            records.append(backup_database(self.root / relative, destination))
            sync(destination)
            self.event("backed_up", database=str(relative))
        inventory = folder / "inventory.json"
        write_inventory(records, inventory)
        for directory, _, _ in os.walk(folder, topdown=False):
            sync(Path(directory))
        sync(folder.parent)

    def restore(self, journal, folder):
        inventory = json.loads((folder / "inventory.json").read_text())
        expected = {str(self.root / relative): folder / relative for relative in journal["databases"]}
        records = inventory["databases"]
        if len(records) != len(expected) or {record["source"] for record in records} != expected.keys():
            raise ValueError("Inventario de restauración incompleto")
        for record in records:
            source = expected[record["source"]]
            if sha256(source) != record["sha256"]:
                raise ValueError("Huella de respaldo incorrecta")
            verify_sqlite(source)
        for record in records:
            destination = Path(record["source"])
            relative = destination.relative_to(self.root)
            schema.safe_database(self.root, relative, False)
            with closing(schema.connect(expected[str(destination)], "mode=ro")) as source:
                with closing(schema.connect(destination, "mode=rw")) as target:
                    source.backup(target)
                    schema.inspect(target)
            self.event("restored", database=str(relative))

    def finish(self, journal):
        active = self.active()
        try:
            self.hook("resume", self.hooks["resume"], active)
        except Exception as error:
            self.event("resume_failed", run=journal["run"], error=type(error).__name__)
            raise
        self.event("finished", run=journal["run"], outcome=journal["phase"])
        self.pending.unlink()
        sync(self.state)

    def recover_pending(self, journal):
        phase = journal["phase"]
        if phase in {"committed", "rolled_back"}:
            self.finish(journal)
            return
        if phase not in {"draining", "backed_up", "changing"}:
            raise ValueError("Fase de recuperación desconocida")
        previous = Path(journal["previous"]) if journal["previous"] else None
        self.hook("drain", self.hooks["drain"], self.active())
        if phase == "changing":
            self.restore(journal, self.state / "runs" / journal["run"] / "backup")
            schema.validate(self.root, journal["schema"])
        self.point_to(previous)
        if phase == "changing":
            self.hook("activate", self.hooks["activate"], previous)
        if previous:
            self.hook("ready", self.hooks["ready"], previous)
        self.checkpoint(journal, "rolled_back")
        self.finish(journal)

    def recover(self, approval):
        with self.lock():
            journal = json.loads(self.pending.read_text())
            self.approve("recover", journal["digest"], approval)
            self.event("recovery_started", run=journal["run"], digest=journal["digest"])
            try:
                self.recover_pending(journal)
            except Exception as error:
                self.event("recovery_failed", run=journal["run"], error=type(error).__name__)
                raise

    def stage(self, bundle, original, fingerprint, folder):
        for name in (MANIFEST, SIGNATURE, *(f"payload/{name}" for name in original["files"])):
            destination = folder / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bundle / name, destination, follow_symlinks=False)
        manifest, actual, paths, previous, expected = self.preflight(folder, dry=False)
        if actual != fingerprint:
            raise ValueError("El artefacto cambió durante la preparación")
        payload = folder / "payload"
        for directory, _, names in os.walk(folder, topdown=False):
            for name in names:
                sync(Path(directory) / name)
            sync(Path(directory))
        sync(folder.parent)
        sync(self.state)
        return manifest, paths, previous, expected, payload

    def apply(self, bundle, approval):
        # Verificar el paquete antes de crear estado y volver a verificar la copia privada.
        original, fingerprint = validate_artifact(bundle, self.signers)
        self.approve("apply", fingerprint, approval)
        with self.lock():
            if self.pending.exists():
                raise ValueError("Recuperar la ejecución pendiente antes de aplicar")
            run = uuid4().hex
            folder = self.state / "runs" / run
            folder.mkdir(parents=True, mode=0o700)
            self.event("approved", run=run, digest=fingerprint, commit=original["commit"])
            try:
                manifest, paths, previous, expected, payload = self.stage(
                    bundle, original, fingerprint, folder
                )
            except Exception as error:
                self.event("preflight_failed", run=run, error=type(error).__name__)
                raise
            self.event("preflight_passed", run=run, databases=len(paths))
            journal = {"run": run, "digest": fingerprint, "previous": str(previous) if previous else None,
                       "schema": manifest["schema"], "databases": [str(path) for path in paths]}
            self.checkpoint(journal, "draining")
            try:
                self.hook("drain", self.hooks["drain"], previous)
                if schema.validate(
                    self.root, manifest["schema"], expected=expected,
                    target=manifest["migration"] is None,
                ) != paths:
                    raise ValueError("El inventario cambió durante el drenaje")
                self.backup(paths, folder / "backup")
                self.checkpoint(journal, "backed_up")
                self.checkpoint(journal, "changing")
                schema.migrate(self.root, paths, manifest["migration"], payload, self.event)
                if schema.validate(self.root, manifest["schema"], expected=expected, target=True) != paths:
                    raise ValueError("El inventario cambió durante la migración")
                self.point_to(payload)
                self.hook("activate", self.hooks["activate"], payload)
                self.hook("ready", self.hooks["ready"], payload)
                for check in manifest["checks"]:
                    self.hook(f"package:{check}", self.checks[check], payload)
            except Exception as error:
                self.event("failed", run=run, error=type(error).__name__)
                self.recover_pending(json.loads(self.pending.read_text()))
                raise
            self.checkpoint(journal, "committed")
            self.finish(journal)
            return fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for action in ("plan", "apply"):
        command = commands.add_parser(action)
        command.add_argument("--artifact", type=Path, required=True)
        if action == "apply":
            command.add_argument("--approve", required=True)
    commands.add_parser("recover").add_argument("--approve", required=True)
    args = parser.parse_args()
    try:
        deployment = Deployment(json.loads(args.config.read_text()))
        if args.command == "plan":
            print(json.dumps(deployment.plan(args.artifact.resolve()), sort_keys=True))
        elif args.command == "apply":
            print(deployment.apply(args.artifact.resolve(), args.approve))
        else:
            deployment.recover(args.approve)
    except Exception as error:
        print(f"Despliegue: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
