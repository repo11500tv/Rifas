"""Aislamiento del perfil de Arsys con rutas y supervisor sintéticos."""

from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from deployment import backup_integral, schema
from deployment.deploy import Deployment
from deployment.hooks import Hooks


class ArsysProfileTest(unittest.TestCase):
    def test_production_scope_excludes_nested_staging_and_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deployment = Deployment.__new__(Deployment)
            deployment.root = root / "rifas"
            deployment.state = deployment.root / ".rifas-deploy"
            stage = deployment.root / "staging" / "prueba_231"
            legacy = root / "sorteos"
            deployment.protected = (stage, legacy)
            deployment.check_scope(deployment.root, ["ops"])
            for extra in ("staging", "staging/prueba_231/entidades"):
                with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "solapada"):
                    deployment.check_scope(deployment.root, [extra])
            with self.assertRaisesRegex(ValueError, "solapada"):
                deployment.check_scope(legacy, [])
            deployment.root = stage
            deployment.state = stage / ".rifas-deploy"
            deployment.protected = (root / "rifas" / "platform_app",)
            with self.assertRaisesRegex(ValueError, "solapada"):
                deployment.check_scope(root / "rifas", [])

    def test_rejects_aliased_data_and_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "central").mkdir()
            (root / "entidades").mkdir()
            private = root / "other.sqlite"
            private.touch()
            path = root / schema.CENTRAL
            os.link(private, path)
            with self.assertRaisesRegex(ValueError, "compartido"):
                schema.safe_database(root, schema.CENTRAL, True)
            with self.assertRaisesRegex(ValueError, "enlaces físicos"):
                backup_integral.inventory(root, None, [], [schema.CENTRAL])
            path.unlink()
            path.touch()
            path.with_name(path.name + "-wal").symlink_to(private)
            with self.assertRaisesRegex(ValueError, "compartido"):
                schema.safe_database(root, schema.CENTRAL, False)
            deployment = Deployment.__new__(Deployment)
            deployment.root = root
            deployment.state = root / ".rifas-deploy"
            deployment.state.mkdir()
            deployment.protected = ()
            (deployment.state / "runs").symlink_to(root / "entidades")
            with self.assertRaisesRegex(ValueError, "Estado"):
                deployment.check_scope(None, [])

    def test_systemd_scope_and_public_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = json.loads((Path(__file__).resolve().parents[1] / "deployment/arsys/"
                                  "staging.hooks.example.json").read_text())
            profile.update(gate=str(root / "gate"), target=str(root / "target"),
                           closed_url="https://sandbox.invalid/staging/health",
                           additional_closed_urls=["https://sandbox.invalid/alias/health"],
                           private_url="http://127.0.0.1:8766/health")
            profile["scope"].update(data_root=str(root), baseline=str(root))
            profile["gunicorn"]["python"] = "/usr/bin/python3"
            hooks = Hooks(profile)
            good = {"RIFAS_DEPLOY_ENVIRONMENT": "staging", "RIFAS_DATA_ROOT": str(root),
                    "RIFAS_RELEASE_ROOT": str(root)}
            with patch.dict(os.environ, {**good, "RIFAS_DEPLOY_ENVIRONMENT": "production"}), \
                    patch("deployment.hooks.subprocess.run") as control:
                with self.assertRaisesRegex(ValueError, "otro entorno"):
                    hooks.drain()
                control.assert_not_called()
                self.assertFalse(hooks.gate.exists())
            with patch.dict(os.environ, {**good, "RIFAS_RELEASE_ROOT": str(root.parent)}):
                with self.assertRaisesRegex(ValueError, "release"):
                    hooks.activate()
            with patch.dict(os.environ, good), patch.object(hooks, "wait") as wait, \
                    patch("deployment.hooks.subprocess.run") as control:
                hooks.drain()
                self.assertEqual([call.args for call in wait.call_args_list],
                                 [(url, 503) for url in hooks.public_urls])
                control.assert_called_once_with(["/usr/bin/systemctl", "stop", "rifas-pruebas.service"],
                                                check=True, timeout=40)
            hooks.target.write_text(json.dumps({"data": str(root.parent), "release": str(root)}))
            with patch("deployment.hooks.os.execve") as execute:
                with self.assertRaisesRegex(ValueError, "datos"):
                    hooks.serve()
                execute.assert_not_called()
