"""Transacción de infraestructura para staging dentro del coordinador universal."""

import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from deployment.artifact import digest
from deployment.backup_integral import atomic_json, sync
from deployment.backup_sqlite import sha256
from deployment.hooks import probe_status
from deployment.smoke import NoRedirect
from deployment.structure import SYSTEMCTL, command


RECIPE_FIELDS = {"format", "environment", "installation", "files", "steps"}
DEPENDENCY_FIELDS = (
    "Requires", "Requisite", "Wants", "BindsTo", "PartOf", "Conflicts", "ConsistsOf",
    "PropagatesStopTo", "StopPropagatedFrom", "Triggers", "TriggeredBy", "OnFailure", "OnSuccess",
)
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
        fields = RECIPE_FIELDS | {"publication", "unit_scope"} if deployment.name == "staging" else RECIPE_FIELDS
        if (set(recipe) != fields
                or recipe["format"] != 1 or deployment.name not in {"staging", "synthetic"}
                or recipe["environment"] != deployment.name
                or recipe["installation"] != str(deployment.root)
                or set(recipe["steps"]) != STEPS
                or not isinstance(recipe["files"], dict) or not recipe["files"]):
            raise ValueError("Lote de intervención inválido o fuera del ámbito de staging")
        self.publication = recipe.get("publication", [])
        self.unit_scope = recipe.get("unit_scope")
        if deployment.name == "staging":
            self.validate_staging_scope()
        self.files = recipe["files"]
        self.steps = recipe["steps"]
        for name, argv in self.steps.items():
            if (not isinstance(argv, list) or not argv
                    or not all(isinstance(arg, str) for arg in argv) or argv[0] not in self.files):
                raise ValueError(f"Pasos sin ejecutable registrado: {name}")
        for path, fingerprint in self.files.items():
            if not Path(path).is_absolute() or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
                raise ValueError("Entrada de lote inválida")

    def validate_staging_scope(self):
        if not isinstance(self.publication, list) or not self.publication:
            raise ValueError("Enumerar todas las entradas HTTPS de staging revisadas")
        for url in self.publication:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                    or parsed.query or parsed.fragment or not parsed.path or parsed.port == 0):
                raise ValueError("Entrada de staging inválida o con credenciales")
        if len(set(self.publication)) != len(self.publication):
            raise ValueError("Entradas de staging duplicadas")
        scope = self.unit_scope
        structure = self.deployment.structure
        if (structure is None or not isinstance(scope, dict) or
                set(scope) != {"unit", "auxiliary_units", "protected_units"} or
                scope["unit"] != structure.settings["unit"]):
            raise ValueError("El lote debe declarar la unidad de staging del perfil")
        if not all(isinstance(scope[key], list) and all(isinstance(value, str) for value in scope[key])
                   for key in ("auxiliary_units", "protected_units")):
            raise ValueError("Declaración de unidades de la intervención inválida")
        staged = {scope["unit"], *scope["auxiliary_units"]}
        protected = set(scope["protected_units"])
        if (not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*\.(?:service|timer|socket)", name)
                    for name in staged | protected)
                or structure.settings["peer_unit"] not in protected or staged & protected):
            raise ValueError("Las unidades de staging se cruzan con un ámbito protegido")

    def verify_publication(self, expected):
        if self.publication:
            opener = build_opener(ProxyHandler({}), NoRedirect())
            for index, url in enumerate(self.publication, start=1):
                if probe_status(opener, url) != expected:
                    raise ValueError(f"Entrada pública {index}: no se verificó HTTP {expected}")
            self.deployment.event("intervention_publication_checked",
                                  expected=expected, entries=len(self.publication))

    def verify_dependencies(self):
        if self.unit_scope is None:
            return
        protected = set(self.unit_scope["protected_units"])
        for name in [self.unit_scope["unit"], *self.unit_scope["auxiliary_units"]]:
            raw = command(SYSTEMCTL, "--no-pager", "show",
                          "--property=" + ",".join(("Id", "LoadState", *DEPENDENCY_FIELDS)), name)
            values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            if values.get("Id") != name or values.get("LoadState") != "loaded":
                raise ValueError("No se pudo identificar una unidad revisada de staging")
            if any(protected.intersection(values.get(field, "").split()) for field in DEPENDENCY_FIELDS):
                raise ValueError("Dependencia directa de una unidad protegida")
        self.deployment.event("intervention_dependencies_checked")

    def verify_review(self):
        if self.deployment.name == "staging" and (
            self.deployment.config.get("intervention_reviewed_digest") != self.fingerprint
        ):
            raise ValueError("La intervención no coincide con el lote fijado en el perfil de staging")

    def verify_files(self):
        for name, expected in self.files.items():
            path = Path(name)
            resolved = path.resolve()
            if any(resolved.is_relative_to(root) for root in self.deployment.protected):
                raise ValueError("Insumo de intervención dentro de un ámbito protegido")
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

    def finish(self, folder, journal):
        self.verify_dependencies()
        if self.publication:
            # Persistir antes de abrir: un corte aquí deja la barrera sin
            # confirmar incluso si el paso llegó a admitir tráfico.
            journal["publication"] = "unverified"
            self.checkpoint(journal, journal["phase"])
        try:
            self.step("reopen", folder)
            self.verify_publication(401)
        except Exception:
            if self.publication:
                try:
                    self.verify_dependencies()
                    self.step("close", folder)
                    self.verify_publication(503)
                except Exception as closure:
                    self.deployment.event("intervention_reclose_failed", barrier="unverified")
                    raise RuntimeError(
                        "Falló la reapertura y no se verificó el nuevo cierre; intervención pendiente"
                    ) from closure
                journal["publication"] = "closed_verified"
                self.checkpoint(journal, journal["phase"])
                self.deployment.event("intervention_reclose_verified", barrier="closed")
            raise
        self.pending.unlink()
        sync(self.pending.parent)

    def recover(self, journal, folder):
        if journal["phase"] == "changing":
            # Si cerrar o restaurar falla, conservar el estado y la barrera.
            self.verify_dependencies()
            self.step("close", folder)
            self.verify_publication(503)
            self.step("verify_backup", folder)
            self.step("rollback", folder)
            self.step("verify_rollback", folder)
            self.checkpoint(journal, "rolled_back")
        elif journal["phase"] not in {"committed", "rolled_back"}:
            raise ValueError("Fase de intervención desconocida")
        self.finish(folder, journal)

    def execute(self, approval, *, recovering=False):
        deployment = self.deployment
        with deployment.lock():
            if deployment.pending.exists():
                raise ValueError("Hay un despliegue pendiente")
            previous = self.get_pending()
            self.verify_review()
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
            self.verify_dependencies()
            self.verify_publication(401)
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
                self.verify_dependencies()
                self.step("close", folder)
                self.verify_publication(503)
                self.step("apply", folder)
                self.verify_dependencies()
                self.verify_publication(503)
                self.step("verify", folder)
            except Exception:
                self.recover(journal, folder)
                raise
            self.checkpoint(journal, "committed")
            self.finish(folder, journal)
