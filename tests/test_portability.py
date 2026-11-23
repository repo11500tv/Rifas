"""Portable installation tests. Run: python -m unittest discover -s tests -p 'test_portability.py'."""
import json
import tempfile
import unittest
from pathlib import Path

from deployment.installation import load_installation
from deployment.backup_external import backup_external, verify_external


class PortableInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.external = self.base / "service.conf"
        self.external.write_text("unit=test\n")
        self.config = {
            "format": "rifas-installation-v1",
            "domain": "example.org",
            "project": {"user": "owner", "group": "webgroup", "root": str(self.base / "project")},
            "environments": {
                "staging": {"root": str(self.base / "stage"), "service_user": "stageapp",
                            "unit": "stage.service", "port": 8768,
                            "external_files": [str(self.external)]},
                "production": {"root": str(self.base / "prod"), "service_user": "prodapp",
                               "unit": "prod.service", "port": 8767,
                               "external_files": [str(self.external)]},
            },
        }
        self.manifest = self.base / "installation.json"

    def load(self):
        self.manifest.write_text(json.dumps(self.config))
        return load_installation(self.manifest)

    def test_two_independent_installations(self):
        self.load()
        self.config["domain"] = "other.example.net"
        self.config["project"]["user"] = "anotherowner"
        self.config["environments"]["staging"]["port"] = 9978
        self.assertEqual(self.load()["project"]["user"], "anotherowner")

    def test_nested_environments_rejected(self):
        self.config["environments"]["staging"]["root"] = str(self.base / "prod" / "staging")
        with self.assertRaises(ValueError):
            self.load()

    def test_shared_service_user_rejected(self):
        self.config["environments"]["staging"]["service_user"] = "prodapp"
        with self.assertRaises(ValueError):
            self.load()

    def test_unknown_secret_field_rejected(self):
        self.config["password"] = "should-not-be-here"
        with self.assertRaises(ValueError):
            self.load()

    def test_external_backup_and_integrity(self):
        self.load()
        dest = self.base / "backup"
        backup_external("staging", dest, self.manifest)
        self.assertTrue(verify_external(dest))
        (dest / "0_service.conf").write_text("tampered")
        with self.assertRaises(RuntimeError):
            verify_external(dest)


if __name__ == "__main__":
    unittest.main()
