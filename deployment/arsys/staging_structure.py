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
    def __init__(self, settings, root, state, protected, components, profile, control_root=None):
        super().__init__(settings, root, state, protected, components, profile, control_root)
        if (profile["environment"] != "staging" or root != STAGE or self.control_root != CONTROL
                or settings.get("unit") != UNIT or settings.get("peer_unit") != "rifas-platform.service"
                or self.port != 8768 or self.writable != {STAGE / "central", STAGE / "entidades"}
                or settings.get("writer_groups")):
            raise ValueError("El modo de aislamiento Arsys solo admite PRUEBAS y sus bases")
        self.group = None

    def report(self, action):
        result = read_report(action.encode("ascii"))
        if not isinstance(result, dict) or result.get("environment") != "staging" or result.get("unit") != UNIT:
            raise ValueError("Informe de servicio ajeno a PRUEBAS")
        return result

    def evidence(self, *, review=False):
        policy = self.report("policy-report")["policy"]
        if not isinstance(policy, str) or not re.fullmatch(r"[a-f0-9]{64}", policy):
            raise ValueError("Huella de política de PRUEBAS inválida")
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
        expected_uid = pwd.getpwnam("dealfonsocom").pw_uid
        read_only = (
            DOMAIN / "rifas", *self.protected, COORDINATOR / "checkout",
            COORDINATOR / "config", COORDINATOR / "trust",
        )
        runtime = Path(self.profile["runtime_python"]).parent.parent
        checks = {
            "coordinador_aislado": os.getpid() == 1 and os.geteuid() == expected_uid
            and status.get("NoNewPrivs", "").strip() == "1" and int(status.get("CapEff", "1"), 16) == 0,
            "rutas_ajenas_y_configuracion_solo_lectura": all(path.exists() and not os.access(path, os.W_OK)
                                                           for path in read_only),
            "estado_y_control_escribibles": all(path.is_dir() and os.access(path, os.W_OK)
                                                for path in (self.state, CONTROL, *self.writable)),
            "runtime_seleccionado": (COORDINATOR / "runtime/current").resolve() == runtime,
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
        expected_mounts = {**{str(path): "ro" for path in PROTECTED}, str(STAGE): "rw"}
        if (report.get("gunicorn_uid") != pwd.getpwnam("dealfonsocom").pw_uid
                or report.get("mounts") != expected_mounts
                or report.get("group") != "/system.slice/" + UNIT):
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
