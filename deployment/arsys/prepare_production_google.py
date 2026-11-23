"""Prepare and verify the signed Google OAuth production release without applying it."""

import argparse
import json
import os
from pathlib import Path
import pwd

from deployment.arsys.production_serve import CONTROL, COORDINATOR, ROOT
from deployment.arsys.production_structure import FOREIGN, MODE, PEER, UNIT
from deployment import backup_integral
from deployment.deploy import Deployment
from deployment.hooks import Hooks


DIGEST = "da9395e5d67f12ab6aa0e87f79bad5f1086f966340ac15b7d0d5e684821f432b"
BUNDLE = COORDINATOR / "artifacts/google-oauth-2.4.2-c9799a5"
PYTHON = COORDINATOR / "runtime/google-oauth-2.4.2-c9799a5/bin/python"
PROFILE = COORDINATOR / "config/deployment.json"
HOOKS_FILE = COORDINATOR / "config/google-2.4.2.hooks.json"


def configuration():
    python = ["/usr/bin/env", f"PYTHONPATH={COORDINATOR / 'checkout'}", str(PYTHON), "-P", "-B", "-m"]
    bridge = [*python, "deployment.arsys.production_service_bridge", "request"]
    probe = [*python, "deployment.arsys.production_google_checks"]
    hook = [*python, "deployment.hooks", "--config", str(HOOKS_FILE)]
    settings = {
        "scope": {"environment": "production", "data_root": str(ROOT),
                  "baseline": str(ROOT), "control_root": str(CONTROL)},
        "systemd_unit": UNIT,
        "gate": str(CONTROL / "maintenance"),
        "target": str(CONTROL / "release.json"),
        "closed_url": "https://dealfonso.com/rifas/health",
        "private_url": "http://127.0.0.1:8767/health",
        "public_open_status": 200,
        "service_control": bridge,
        "gunicorn": {"python": str(PYTHON), "arguments": ["--bind", "127.0.0.1:8767"]},
    }
    profile = {
        "environment": "production", "data_root": str(ROOT), "baseline": str(ROOT),
        "control_root": str(CONTROL), "protected_paths": list(map(str, FOREIGN)),
        "allowed_signers": str(COORDINATOR / "trust/release-signers"),
        "approval_signers": str(COORDINATOR / "trust/approval-signers"),
        "runtime_python": str(PYTHON), "backup_components": [],
        "hooks": {**{name: [*hook, name] for name in ("drain", "activate", "resume")}, "ready": [*probe, "ready"]},
        "checks": {"google-oidc": [*probe, "google-oidc"]},
        "structure": {
            "mode": MODE, "unit": UNIT, "peer_unit": PEER, "port": 8767,
            "working_directory": str(ROOT), "writer_observer": [*bridge, "writer-report"],
            "review_files": [str(HOOKS_FILE)], "expected_fingerprint": "REVIEW_REQUIRED",
        },
    }
    return profile, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-profile", action="store_true")
    args = parser.parse_args()
    if pwd.getpwuid(os.geteuid()).pw_name != "dealfonsocom":
        parser.error("Ejecutar como dealfonsocom")
    if (PROFILE.parent.resolve(strict=True) != PROFILE.parent or PROFILE.is_symlink() or HOOKS_FILE.is_symlink()):
        parser.error("Rutas de configuración no canónicas")
    profile, settings = configuration()
    Hooks(settings)
    deployment = Deployment(profile)
    deployment.ensure_no_intervention()
    if deployment.pending.exists():
        parser.error("Hay una recuperación pendiente")
    manifest, digest, databases, baseline, _ = deployment.preflight(BUNDLE, dry=True)
    if digest != DIGEST or manifest["package"] != "google-oauth" or manifest["version"] != "2.4.2" or baseline != ROOT:
        parser.error("El paquete o la instalación no coinciden con la primera actualización revisada")
    for entry in backup_integral.inventory(ROOT, baseline, [], databases):
        if entry["kind"] != "directory":
            try:
                with (ROOT / entry["path"]).open("rb") as stream:
                    stream.read(1)
            except PermissionError:
                parser.error(f"No se puede respaldar {entry['group']}/{entry['path']}")
    if args.write_profile:
        for path, candidate in ((HOOKS_FILE, settings), (PROFILE, profile)):
            if path.exists() and json.loads(path.read_text()) != candidate:
                parser.error(f"Ya existe otro perfil: {path.name}")
        for path, candidate in ((HOOKS_FILE, settings), (PROFILE, profile)):
            if not path.exists():
                backup_integral.atomic_json(path, candidate)
    print(json.dumps({"environment": "production", "digest": digest, "databases": len(databases),
                      "profile_written": args.write_profile, "structural_review": "pending"}))


if __name__ == "__main__":
    main()
