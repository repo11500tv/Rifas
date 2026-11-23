"""Structural guard for the verified Arsys staging launcher."""

import hashlib
import json
import os
from pathlib import Path
import pwd
import re

from deployment.arsys.inspect_staging_isolation import DOMAIN, PROTECTED, STAGE, UNIT
from deployment.arsys.staging_service_bridge import read_report
from deployment.structure import Structure, checked_path


CONTROL = Path("/var/lib/rifas-pruebas-control")
COORDINATOR = DOMAIN / "rifas-deployment/staging"
MODE = "arsys-isolated-staging"


class ArsysStagingStructure(Structure):
    environment = "staging"
    application = STAGE
    control = CONTROL
    coordinator = COORDINATOR
    unit_name = UNIT
    peer_name = "rifas-platform.service"
    service_port = 8768
    service_read_only = PROTECTED
    service_writable = (STAGE,)
    foreign_root = DOMAIN / "rifas"

    def __init__(self, settings, root, state, protected, components, profile, control_root=None):
        super().__init__(settings, root, state, protected, components, profile, control_root)
        if (profile["environment"] != self.environment or root != self.application or self.control_root != self.control
                or settings.get("unit") != self.unit_name or settings.get("peer_unit") != self.peer_name
                or self.port != self.service_port or self.writable != {root / "central", root / "entidades"}
                or settings.get("writer_groups")):
            raise ValueError("El modo de aislamiento Arsys no coincide con el entorno y sus bases")
        self.group = None

    @classmethod
    def report(cls, action):
        result = read_report(action.encode("ascii"))
        if (not isinstance(result, dict) or result.get("environment") != cls.environment
                or result.get("unit") != cls.unit_name):
            raise ValueError("Informe de servicio ajeno al entorno")
        return result

    def evidence(self, *, review=False):
        policy = self.report("policy-report")["policy"]
        if not isinstance(policy, str) or not re.fullmatch(r"[a-f0-9]{64}", policy):
            raise ValueError("Huella de política de PRUEBAS inválida")
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
        expected_uid = pwd.getpwnam("dealfonsocom").pw_uid
        read_only = (
            self.foreign_root, *self.protected, self.coordinator / "checkout",
            self.coordinator / "config", self.coordinator / "trust",
        )
        runtime = Path(self.profile["runtime_python"]).parent.parent
        checks = {
            "coordinador_aislado": os.getpid() == 1 and os.geteuid() == expected_uid
            and status.get("NoNewPrivs", "").strip() == "1" and int(status.get("CapEff", "1"), 16) == 0,
            "rutas_ajenas_y_configuracion_solo_lectura": all(path.exists() and not os.access(path, os.W_OK)
                                                           for path in read_only),
            "estado_y_control_escribibles": all(path.is_dir() and os.access(path, os.W_OK)
                                                for path in (self.state, self.control, *self.writable)),
            "runtime_seleccionado": (self.coordinator / "runtime/current").resolve() == runtime,
        }
        names = {*self.settings["review_files"], self.profile["allowed_signers"], self.profile["approval_signers"]}
        records = {}
        for name in sorted(names):
            path = checked_path(name)
            if not path.is_file() or os.access(path, os.W_OK):
                raise ValueError(f"Archivo de revisión ausente o escribible: {path}")
            records[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        payload = {"policy": policy, "profile": self.profile, "files": records, "checks": checks}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if not review:
            failures = [name for name, passed in checks.items() if not passed]
            if failures:
                raise ValueError("Aislamiento estructural insuficiente: " + ", ".join(failures))
            if fingerprint != self.settings.get("expected_fingerprint"):
                raise ValueError("Cambió la evidencia estructural o falta aprobarla")
        return {"digest": fingerprint, "checks": checks}

    def service(self, *, stopped=False):
        if stopped:
            if self.report("stopped-report").get("stopped") is not True:
                raise ValueError("No se confirmó la parada de PRUEBAS")
            self.group = None
            return
        report = self.report("isolation-report")
        expected_mounts = {**{str(path): "ro" for path in self.service_read_only},
                           **{str(path): "rw" for path in self.service_writable}}
        if (report.get("gunicorn_uid") != pwd.getpwnam("dealfonsocom").pw_uid
                or report.get("mounts") != expected_mounts
                or report.get("group") != "/system.slice/" + self.unit_name):
            raise ValueError("El proceso web no acredita el aislamiento de PRUEBAS")
        self.group = report["group"]

    def writers(self, *, drained=False):
        report = read_report(b"writer-report")
        if report.get("complete") is not True or report.get("paths") != sorted(map(str, self.writable)):
            raise ValueError("Visibilidad incompleta de los escritores de PRUEBAS")
        rows = report["writers"]
        if not isinstance(rows, list) or (not drained and self.group is None):
            raise ValueError("Informe de escritores sin contexto de servicio")
        if any(not isinstance(row, dict) or drained or row.get("group") != self.group for row in rows):
            raise ValueError("Se detectaron escritores no autorizados en PRUEBAS")
        return len(rows)
