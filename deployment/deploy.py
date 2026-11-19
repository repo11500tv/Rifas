"""Coordinador de releases Rifas. Ejecutar con python -m deployment.deploy."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

from deployment import approval, backup_integral as snapshot, schema
from deployment.artifact import IDENTITY, MANIFEST, NAMESPACE, SIGNATURE, digest, payload_path, platform_version, verify_signature
from deployment.backup_sqlite import sha256
from deployment.backup_integral import atomic_json, sync

HOOKS = {"drain", "activate", "ready", "resume"}


def signing_keys(path):
    keys = set(re.findall(r"(?m)^[^#\n][^\n]*?\bssh-ed25519\s+([A-Za-z0-9+/=]+)(?=\s|$)",
                          path.read_text()))
    if not keys:
        raise ValueError(f"No hay claves Ed25519 en {path.name}")
    return keys


def validate_artifact(bundle, trusted_signers):
    raw = verify_signature(bundle / MANIFEST, bundle / SIGNATURE, trusted_signers, IDENTITY, NAMESPACE)
    manifest = json.loads(raw)
    if set(manifest) != {"format", "package", "version", "commit", "recipe", "files",
                         "platform_from", "platform_to", "schema", "migration", "checks"} or manifest["format"] != 2:
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
            or len(set(manifest["checks"])) != len(manifest["checks"])):
        raise ValueError("Metadatos de paquete incompatibles")
    payload = bundle / "payload"
    if payload.is_symlink() or not payload.is_dir():
        raise ValueError("Payload inválido")
    files = manifest["files"]
    required = {"wsgi.py", "platform_app/__init__.py"} | schema.referenced_files(
        manifest["schema"], manifest["migration"]
    )
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
        self.approvers = Path(config["approval_signers"]).resolve(strict=True)
        self.backup_components = config["backup_components"]
        if not isinstance(self.backup_components, list):
            raise ValueError("backup_components debe ser una lista de rutas gestionadas")
        if (self.root.is_relative_to("/root") or self.root == Path("/") or not self.root.is_dir()
                or not self.signers.is_file() or not self.approvers.is_file() or self.state.is_symlink()):
            raise ValueError("Rutas de instalación no admitidas")
        if signing_keys(self.approvers) & signing_keys(self.signers):
            raise ValueError("La confianza de aprobación debe ser independiente de la firma de releases")
        protected = config.get("protected_paths", [])
        if not isinstance(protected, list):
            raise ValueError("protected_paths debe ser una lista de rutas absolutas")
        self.protected = tuple(Path(path) for path in protected)
        for path in self.protected:
            if not path.is_absolute() or path.resolve() != path:
                raise ValueError(f"Ruta protegida no canónica: {path}")
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
        self.check_scope(self.baseline, self.backup_components)
        marker = self.state / "environment"
        if marker.is_symlink() or not marker.is_file() or marker.read_text().strip() != self.name:
            raise ValueError("La raíz no está registrada para el entorno de la configuración")
        self.pending = self.state / "pending.json"
        self.current = self.state / "current"
        self.run = None

    def check_scope(self, previous, components):
        scopes = snapshot.roots(self.root, previous, components)
        paths = [self.state]
        for name in ("lock", "events.jsonl", "pending.json", "runs", "used-approvals"):
            path = self.state / name
            if path.is_symlink() or (path.is_file() and path.stat().st_nlink != 1):
                raise ValueError(f"Estado del coordinador compartido o inseguro: {path}")
        for base, relatives in scopes.values():
            paths.extend(base / relative for relative in relatives)
        for path in paths:
            if path.resolve() != path:
                raise ValueError(f"Ruta gestionada no canónica: {path}")
            if any(path.is_relative_to(protected) or protected.is_relative_to(path)
                   for protected in self.protected):
                raise ValueError(f"Ruta gestionada solapada con otro ámbito: {path}")

    def event(self, phase, **details):
        record = {"at": datetime.now(timezone.utc).isoformat(), "environment": self.name,
                  "phase": phase, "run": self.run, **details}
        with (self.state / "events.jsonl").open("a") as log:
            log.write(json.dumps(record, sort_keys=True) + "\n")
            log.flush()
            os.fsync(log.fileno())

    @contextmanager
    def lock(self):
        self.check_scope(self.baseline, self.backup_components)
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
            subprocess.run(command, cwd=(active or self.root) if label != "drain" else self.root, env=process_env, timeout=120, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            self.event("hook_failed", hook=label, error=type(error).__name__,
                       returncode=getattr(error, "returncode", None))
            raise
        self.event("hook_passed", hook=label)

    def preflight(self, bundle, *, dry):
        manifest, fingerprint = validate_artifact(bundle, self.signers)
        active = self.active()
        self.check_scope(active, self.backup_components)
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
        expected = schema.expected_schema(bundle / "payload", manifest["schema"])
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
        managed = snapshot.inventory(self.root, active, self.backup_components, databases)
        managed_size = sum(item["size"] for item in managed
                           if item["kind"] != "directory" and
                           (item["group"] != "data" or Path(item["path"]) not in databases))
        if shutil.disk_usage(self.state if self.state.is_dir() else self.root).free < payload_size + managed_size + 2 * database_size:
            raise ValueError("Espacio insuficiente para release y respaldo SQLite")
        return manifest, fingerprint, databases, active, expected

    def plan(self, bundle):
        if self.pending.exists():
            raise ValueError("Hay una ejecución pendiente de recuperar")
        manifest, fingerprint, databases, _, _ = self.preflight(bundle, dry=True)
        return {"environment": self.name, "mode": "read-only", "digest": fingerprint,
                "package": manifest["package"], "commit": manifest["commit"],
                "databases": [str(path) for path in databases], "checks": manifest["checks"],
                "backup_components": ["central", "entidades", *self.backup_components],
                "installation": str(self.root)}

    def status(self):
        if not self.pending.exists():
            return {"environment": self.name, "installation": str(self.root), "pending": None}
        journal = json.loads(self.pending.read_text())
        return {"environment": self.name, "installation": str(self.root), "pending": {
            key: journal[key] for key in ("run", "digest", "phase")
        }}

    def approve(self, operation, fingerprint, document, run=None):
        return approval.verified(
            document, self.approvers, operation, self.name, self.root, fingerprint, run
        )

    def consume(self, grant):
        receipts = self.state / "used-approvals"
        receipts.mkdir(mode=0o700, exist_ok=True)
        try:
            with (receipts / grant["nonce"]).open("x") as receipt:
                json.dump(grant, receipt, sort_keys=True)
                receipt.flush()
                os.fsync(receipt.fileno())
        except FileExistsError:
            raise ValueError("Aprobación ya utilizada") from None
        sync(receipts)
        sync(self.state)

    def checkpoint(self, journal, phase):
        journal["phase"] = phase
        atomic_json(self.pending, journal)
        self.event(phase, run=journal["run"], digest=journal["digest"])

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
        self.check_scope(previous, journal["components"])
        self.hook("drain", self.hooks["drain"], previous)
        if phase == "changing":
            snapshot.restore(
                self.root, previous, journal["components"], [Path(path) for path in journal["databases"]],
                self.state / "runs" / journal["run"] / "backup", journal["snapshot"], self.event,
            )
            schema.validate(self.root, journal["schema"])
        self.point_to(previous)
        self.hook("activate", self.hooks["activate"], previous)
        if previous:
            self.hook("ready", self.hooks["ready"], previous)
        self.checkpoint(journal, "rolled_back")
        self.finish(journal)

    def recover(self, approval):
        with self.lock():
            journal = json.loads(self.pending.read_text())
            grant = self.approve("recover", journal["digest"], approval, journal["run"])
            self.consume(grant)
            self.run = journal["run"]
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
        grant = self.approve("apply", fingerprint, approval)
        with self.lock():
            if self.pending.exists():
                raise ValueError("Recuperar la ejecución pendiente antes de aplicar")
            self.consume(grant)
            self.run = run = grant["run"]
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
                       "schema": manifest["schema"], "components": self.backup_components,
                       "databases": [str(path) for path in paths]}
            self.checkpoint(journal, "draining")
            try:
                self.hook("drain", self.hooks["drain"], previous)
                self.check_scope(previous, self.backup_components)
                if schema.validate(
                    self.root, manifest["schema"], expected=expected,
                    target=manifest["migration"] is None,
                ) != paths:
                    raise ValueError("El inventario cambió durante el drenaje")
                journal["snapshot"] = snapshot.capture(
                    self.root, previous, self.backup_components, paths, folder / "backup", self.event
                )
                snapshot.verify(folder / "backup", journal["snapshot"])
                self.checkpoint(journal, "backed_up")
                self.checkpoint(journal, "changing")
                schema.migrate(self.root, paths, manifest["schema"], manifest["migration"], payload, self.event)
                if schema.validate(self.root, manifest["schema"], expected=expected, target=True) != paths:
                    raise ValueError("El inventario cambió durante la migración")
                self.point_to(payload)
                self.hook("activate", self.hooks["activate"], payload)
                self.hook("ready", self.hooks["ready"], payload)
                for check in manifest["checks"]:
                    self.hook(f"package:{check}", self.checks[check], payload)
            except Exception as error:
                try:
                    self.event("failed", run=run, error=type(error).__name__)
                finally:
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
            command.add_argument("--approve", type=Path, required=True)
    commands.add_parser("recover").add_argument("--approve", type=Path, required=True)
    commands.add_parser("status")
    args = parser.parse_args()
    try:
        deployment = Deployment(json.loads(args.config.read_text()))
        if args.command == "plan":
            print(json.dumps(deployment.plan(args.artifact.resolve()), sort_keys=True))
        elif args.command == "status":
            print(json.dumps(deployment.status(), sort_keys=True))
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
