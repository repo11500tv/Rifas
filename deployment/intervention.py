"""Transacción de infraestructura para staging dentro del coordinador universal."""

import json
import os
from pathlib import Path
import re
import subprocess

from deployment.artifact import digest
from deployment.backup_integral import atomic_json, sync
from deployment.backup_sqlite import sha256

STEPS = {
    "validate", "backup", "verify_backup", "close", "apply", "verify",
    "rollback", "verify_rollback", "reopen",
}


class Intervention:
    def __init__(self, deployment, recipe_path):
        self.deployment = deployment
        self.pending = deployment.state / "intervention.json"
        raw = recipe_path.read_bytes()
        self.fingerprint = digest(raw)
        recipe = json.loads(raw)
        if (set(recipe) != {"format", "environment", "installation", "files", "steps"}
                or recipe["format"] != 1 or deployment.name not in {"staging", "synthetic"}
                or recipe["environment"] != deployment.name
                or recipe["installation"] != str(deployment.root)
                or set(recipe["steps"]) != STEPS
                or not isinstance(recipe["files"], dict) or not recipe["files"]):
            raise ValueError("Lote de intervención inválido o fuera del ámbito de staging")
        self.files = recipe["files"]
        self.steps = recipe["steps"]
        for name, argv in self.steps.items():
            if (not isinstance(argv, list) or not argv
                    or not all(isinstance(arg, str) for arg in argv) or argv[0] not in self.files):
                raise ValueError(f"Pasos sin ejecutable registrado: {name}")
        for path, fingerprint in self.files.items():
            if not Path(path).is_absolute() or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
                raise ValueError("Entrada de lote inválida")

    def verify_files(self):
        for name, expected in self.files.items():
            path = Path(name)
            if not path.is_file() or sha256(path) != expected:
                raise ValueError("Cambió un fichero revisado de la intervención")

    def get_pending(self):
        if self.pending.is_symlink() or (self.pending.exists() and (
            not self.pending.is_file() or self.pending.stat().st_nlink != 1
        )):
            raise ValueError("Estado de intervención inseguro")
        return json.loads(self.pending.read_text()) if self.pending.exists() else None

    def checkpoint(self, journal, phase):
        journal["phase"] = phase
        atomic_json(self.pending, journal)
        self.deployment.event("intervention_checkpoint", stage=phase)

    def step(self, name, folder):
        self.verify_files()
        env = {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "RIFAS_INTERVENTION_BACKUP": str(folder),
            "RIFAS_DATA_ROOT": str(self.deployment.root),
            "RIFAS_DEPLOY_ENVIRONMENT": self.deployment.name,
        }
        self.deployment.event("intervention_step", step=name, outcome="started")
        try:
            subprocess.run(self.steps[name], env=env, cwd=self.deployment.root, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        except (OSError, subprocess.SubprocessError):
            self.deployment.event("intervention_step", step=name, outcome="failed")
            raise RuntimeError(f"Falló el paso de intervención: {name}") from None
        self.deployment.event("intervention_step", step=name, outcome="passed")

    def finish(self, folder):
        self.step("reopen", folder)
        self.pending.unlink()
        sync(self.pending.parent)

    def recover(self, journal, folder):
        if journal["phase"] == "changing":
            # Si cerrar o restaurar falla, conservar el estado y la barrera.
            self.step("close", folder)
            self.step("verify_backup", folder)
            self.step("rollback", folder)
            self.step("verify_rollback", folder)
            self.checkpoint(journal, "rolled_back")
        elif journal["phase"] not in {"committed", "rolled_back"}:
            raise ValueError("Fase de intervención desconocida")
        self.finish(folder)

    def execute(self, approval, *, recovering=False):
        deployment = self.deployment
        with deployment.lock():
            if deployment.pending.exists():
                raise ValueError("Hay un despliegue pendiente")
            previous = self.get_pending()
            self.verify_files()
            if recovering:
                if previous is None or previous["digest"] != self.fingerprint:
                    raise ValueError("La recuperación exige el lote exacto de la intervención pendiente")
                grant = deployment.approve("recover-intervention", self.fingerprint, approval, previous["run"])
                deployment.consume(grant)
                deployment.run = previous["run"]
                self.recover(previous, deployment.state / "interventions" / previous["run"])
                return
            if previous is not None:
                raise ValueError("Recuperar la intervención pendiente antes de continuar")
            grant = deployment.approve("intervene", self.fingerprint, approval)
            deployment.consume(grant)
            deployment.run = grant["run"]
            folder = deployment.state / "interventions" / grant["run"]
            folder.mkdir(parents=True, mode=0o700)
            self.step("validate", folder)
            self.step("backup", folder)
            self.step("verify_backup", folder)
            sync(folder)
            sync(folder.parent)
            journal = {"run": grant["run"], "digest": self.fingerprint}
            # Registrar antes de cerrar el tráfico: incluso un cierre
            # parcialmente ejecutado debe poder recuperarse.
            self.checkpoint(journal, "changing")
            try:
                self.step("close", folder)
                self.step("apply", folder)
                self.step("verify", folder)
            except Exception:
                self.recover(journal, folder)
                raise
            self.checkpoint(journal, "committed")
            self.finish(folder)
