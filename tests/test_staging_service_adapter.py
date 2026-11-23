"""Pruebas del adaptador de control de servicio; no ejecutan systemctl ni sudo."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deployment.hooks import Hooks


class RestrictedServiceControlTests(unittest.TestCase):
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
            "gunicorn": {"python": "/usr/bin/python3", "arguments": ["-m", "gunicorn"]},
            "closed_url": "http://127.0.0.1:18080/health",
            "private_url": "http://127.0.0.1:18081/health",
        }

    def test_restricted_adapter_is_used_for_start_and_stop(self):
        with tempfile.TemporaryDirectory(prefix="rifas-hook-") as temp:
            root = Path(temp).resolve()
            (root / "data").mkdir()
            (root / "control").mkdir()
            with patch("deployment.hooks.subprocess.run") as run:
                hooks = Hooks(self.settings(root))
                hooks.run("stop")
                hooks.run("start")
            self.assertEqual(run.call_args_list[0].args[0],
                             ["/usr/bin/sudo", "-n", "/usr/local/sbin/rifas-staging-service", "stop"])
            self.assertEqual(run.call_args_list[1].args[0],
                             ["/usr/bin/sudo", "-n", "/usr/local/sbin/rifas-staging-service", "start"])

    def test_adapter_rejected_without_systemd_unit(self):
        with tempfile.TemporaryDirectory(prefix="rifas-hook-") as temp:
            root = Path(temp).resolve()
            (root / "data").mkdir()
            settings = self.settings(root)
            settings.pop("systemd_unit")
            with self.assertRaises(ValueError):
                Hooks(settings)


if __name__ == "__main__":
    unittest.main()
