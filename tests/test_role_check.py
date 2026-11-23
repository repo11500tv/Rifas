"""Pruebas sin root ni cambios en servicios del control de roles."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deployment.role_check import check


class RoleCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rifas-roles-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / "data"
        self.control = self.root / "control"
        self.data.mkdir()
        self.control.mkdir()
        self.selector = self.control / "release.json"
        self.selector.write_text(json.dumps({"release": str(self.data), "data": str(self.data)}))
        self.settings = {
            "scope": {"environment": "staging", "data_root": str(self.data),
                      "control_root": str(self.control)},
            "gate": str(self.control / "maintenance"),
            "target": str(self.selector),
            "identities": {"owner_uid": 1000, "service_uid": 1001},
        }

    def test_rejects_root(self):
        with patch("deployment.role_check.os.geteuid", return_value=0):
            with self.assertRaisesRegex(ValueError, "root"):
                check(self.settings, "owner")

    def test_owner_can_manage_owned_directories(self):
        with patch("deployment.role_check.os.geteuid", return_value=1000):
            self.assertEqual(check(self.settings, "owner"), [])

    def test_service_must_not_write_control(self):
        with patch("deployment.role_check.os.geteuid", return_value=1001):
            self.assertIn("El servicio puede modificar el control",
                          check(self.settings, "service"))

    def test_shared_uid_is_rejected(self):
        self.settings["identities"]["service_uid"] = 1000
        with patch("deployment.role_check.os.geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "compartir UID"):
                check(self.settings, "owner")

    def test_wrong_uid_is_rejected(self):
        with patch("deployment.role_check.os.geteuid", return_value=1002):
            with self.assertRaisesRegex(ValueError, "identidad de ejecución"):
                check(self.settings, "owner")

    def test_selector_symlink_is_rejected(self):
        self.selector.unlink()
        self.selector.symlink_to(self.data / "missing")
        with patch("deployment.role_check.os.geteuid", return_value=1001):
            self.assertIn("El servicio no puede leer el selector release.json",
                          check(self.settings, "service"))

    def test_rejects_overlapping_paths(self):
        self.settings["scope"]["control_root"] = str(self.data)
        with patch("deployment.role_check.os.geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "solaparse"):
                check(self.settings, "owner")


if __name__ == "__main__":
    unittest.main()
