"""Prepare the existing PRUEBAS profile without authorizing deployment."""

import argparse
import json
import os
from pathlib import Path

from deployment.backup_integral import atomic_json
from deployment.deploy import Deployment
from deployment.hooks import Hooks
from deployment.arsys.staging_google_checks import BASE_URL, STAGE
from deployment.arsys.staging_structure import MODE


COORDINATOR = Path("/var/www/vhosts/dealfonso.com/rifas-deployment/staging")
CONTROL = Path("/var/lib/rifas-pruebas-control")
UNIT = "rifas-pruebas.service"
BUNDLE = COORDINATOR / "artifacts/google-oauth-2.4.2-7423ba2"
DIGEST = "3a47192e59ce7ffc218eb026d809b60a45ab5a0aa8f405fae326a6cf665f7367"
PYTHON = COORDINATOR / "runtime/google-oauth-2.4.2-7423ba2/bin/python"
PROFILE = COORDINATOR / "config/deployment.json"
HOOKS_FILE = COORDINATOR / "config/google-2.4.2.hooks.json"


def configuration(profile):
    if (profile.get("environment") != "staging" or profile.get("data_root") != str(STAGE)
            or profile.get("control_root") != str(CONTROL) or profile.get("structure", {}).get("unit") != UNIT):
        raise ValueError("El perfil existente no corresponde a PRUEBAS")
    python = ["/usr/bin/env", f"PYTHONPATH={COORDINATOR / 'checkout'}", str(PYTHON), "-P", "-B", "-m"]
    bridge = [*python, "deployment.arsys.staging_service_bridge", "request"]
    settings = {
        "scope": {"environment": "staging", "data_root": str(STAGE),
                  "baseline": str(STAGE), "control_root": str(CONTROL)},
        "systemd_unit": UNIT,
        "gate": str(CONTROL / "maintenance"),
        "target": str(CONTROL / "release.json"),
        "closed_url": "https://dealfonso.com/rifas-pruebas/health",
        "private_url": BASE_URL + "/health",
        "public_open_status": 401,
        "service_control": bridge,
        "gunicorn": {
            "python": str(PYTHON),
            "arguments": ["--workers", "2", "--bind", "127.0.0.1:8768",
                          "--access-logfile", "-", "--error-logfile", "-"],
        },
    }
    hook = [*python, "deployment.hooks", "--config", str(HOOKS_FILE)]
    probe = [*python, "deployment.arsys.staging_google_checks"]
    structure = dict(profile["structure"], expected_fingerprint="REVIEW_REQUIRED", mode=MODE,
                     writer_observer=[*bridge, "writer-report"])
    structure["review_files"] = sorted(set(structure.get("review_files", ())) | {str(HOOKS_FILE)})
    updated = dict(
        profile, baseline=str(STAGE), runtime_python=str(PYTHON), structure=structure,
        hooks={**{name: [*hook, name] for name in ("drain", "activate", "resume")}, "ready": [*probe, "ready"]},
        checks={**profile["checks"], "google-oidc": [*probe, "google-oidc"]},
    )
    return updated, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-profile", action="store_true")
    args = parser.parse_args()
    if (PROFILE.is_symlink() or HOOKS_FILE.is_symlink()
            or PROFILE.parent.resolve(strict=True) != PROFILE.parent):
        parser.error("Directorio o archivo de configuración de PRUEBAS no canónico")
    profile = json.loads(PROFILE.read_text())
    if profile.get("structure", {}).get("expected_fingerprint") != "REVIEW_REQUIRED":
        parser.error("Solo se admite el perfil provisional de PRUEBAS")
    if PROFILE.stat().st_uid != os.geteuid():
        parser.error("Ejecutar como el propietario del perfil de PRUEBAS")
    updated, settings = configuration(profile)
    Hooks(settings)
    deployment = Deployment(updated)
    deployment.ensure_no_intervention()
    if deployment.pending.exists():
        parser.error("Hay un despliegue pendiente de recuperación")
    manifest, digest, databases, _, _ = deployment.preflight(BUNDLE, dry=True)
    if digest != DIGEST or manifest["package"] != "google-oauth" or manifest["version"] != "2.4.2":
        parser.error("Artefacto distinto de Google OAuth 2.4.2 revisado")
    if args.write_profile:
        if HOOKS_FILE.exists() and json.loads(HOOKS_FILE.read_text()) != settings:
            parser.error("Ya existe un perfil de hooks diferente")
        if not HOOKS_FILE.exists():
            atomic_json(HOOKS_FILE, settings)
        atomic_json(PROFILE, updated)
    print(json.dumps({"environment": "staging", "digest": digest, "databases": len(databases),
                      "profile_written": args.write_profile, "structural_review": "pending"}))


if __name__ == "__main__":
    main()
