"""Contrato de lectura del selector por el servicio no privilegiado.

Estas pruebas no cambian permisos reales ni invocan systemd. Evitan activar
perfiles de staging cuyo selector sea ilegible para Gunicorn.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deployment.hooks import Hooks


class SelectorPermissionsTests(unittest.TestCase):
    def settings(self, root):
        return {
            "gate": str(root / "control" / "maintenance"),
            "target": str(root / "control" / "release.json"),
            "scope": {
                "environment": "staging",
                "data_root": str(root / "data"),
                "baseline": str(root / "data"),
                "control_root": str(root / "control"),
            },
            "systemd_unit": "rifas-pruebas.service",
            "service_control": ["/usr/bin/sudo", "-n", "/usr/local/sbin/rifas-staging-service"],
            "gunicorn": {"python": "/usr/bin/python3", "arguments": ["--bind", "127.0.0.1:8768"]},
            "closed_url": "http://127.0.0.1:18080/health",
            "private_url": "http://127.0.0.1:8768/health",
        }

    def test_serve_requires_selector_readability(self):
        with tempfile.TemporaryDirectory(prefix="rifas-selector-") as tmp:
            root = Path(tmp).resolve()
            (root / "control").mkdir()
            (root / "data").mkdir()
            selector = root / "control" / "release.json"
            selector.write_text(json.dumps({"release": str(root / "data"), "data": str(root / "data")}))
            hooks = Hooks(self.settings(root))
            with patch.object(Path, "read_text", side_effect=PermissionError("selector inaccessible")):
                with self.assertRaises(PermissionError):
                    hooks.serve()

    def test_example_has_distinct_control_and_data_roots(self):
        example = Path(__file__).resolve().parents[1] / "deployment/arsys/staging.hooks.example.json"
        settings = json.loads(example.read_text())
        scope = settings["scope"]
        self.assertNotEqual(scope["control_root"], scope["data_root"])
        self.assertEqual(settings["systemd_unit"], "rifas-pruebas.service")
        self.assertTrue(settings["gate"].startswith(scope["control_root"] + "/"))
        self.assertTrue(settings["target"].startswith(scope["control_root"] + "/"))


if __name__ == "__main__":
    unittest.main()
