"""Guardas estructurales con systemd y sockets simulados."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment.structure import Structure


class StructureTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        self.root = parent / "staging"
        self.state = self.root / ".rifas-deploy"
        self.control = parent / "control"
        self.foreign = parent / "production"
        self.proxy = parent / "proxy.conf"
        for path in (self.state, self.root / "central", self.root / "entidades", self.foreign, self.control):
            path.mkdir(parents=True, exist_ok=True)
        self.proxy.write_text("fixture proxy")
        self.settings = {
            "unit": "staging.service", "peer_unit": "production.service",
            "port": 8768, "working_directory": str(self.root),
            "review_files": [str(self.proxy)], "writer_observer": ["/fixture/observer"],
        }
        self.profile = Structure(
            self.settings, self.root, self.state, [self.foreign], [], {"environment": "synthetic"}, self.control
        )
        self.current = {
            "Id": "staging.service", "User": "stage", "WorkingDirectory": str(self.root),
            "InaccessiblePaths": str(self.foreign), "ReadWritePaths": str(self.root / "central"),
            "ProtectSystem": "strict", "NoNewPrivileges": "yes", "KillMode": "control-group",
            "ActiveState": "active", "MainPID": "42", "ControlGroup": "/stage",
        }
        self.peer = {"Id": "production.service", "User": "prod"}
        self.mocks = [
            patch("deployment.structure.unit", side_effect=lambda name:
                  self.current if name == self.settings["unit"] else self.peer),
            patch("deployment.structure.os.geteuid", return_value=1000),
            patch("deployment.structure.os.access", return_value=False),
        ]
        for mock in self.mocks:
            mock.start()
            self.addCleanup(mock.stop)

    def test_fingerprint_survives_service_stop_but_invalidates_proxy_change(self):
        review = self.profile.evidence(review=True)
        self.assertTrue(all(review["checks"].values()))
        self.settings["expected_fingerprint"] = review["digest"]
        self.current.update(ActiveState="inactive", MainPID="0", ControlGroup="")
        self.assertEqual(self.profile.evidence()["digest"], review["digest"])
        self.proxy.write_text("changed proxy")
        with self.assertRaisesRegex(ValueError, "Cambió"):
            self.profile.evidence()

    def test_new_proxy_include_invalidates_reviewed_directory(self):
        includes = self.proxy.parent / "includes"
        includes.mkdir()
        self.settings["review_files"].append(str(includes))
        self.settings["expected_fingerprint"] = self.profile.evidence(review=True)["digest"]
        self.profile.evidence()
        (includes / "new.conf").write_text("new include")
        with self.assertRaisesRegex(ValueError, "Cambió"):
            self.profile.evidence()

    def test_shared_identity_and_broad_writable_tree_block(self):
        self.peer["User"] = self.current["User"]
        self.current["ReadWritePaths"] = str(self.root)
        self.assertFalse(self.profile.evidence(review=True)["checks"]["identidades_separadas"])
        with self.assertRaisesRegex(ValueError, "identidades_separadas.*escrituras_limitadas"):
            self.profile.evidence()

    def test_listener_must_be_private_and_belong_to_unit_and_disappear_on_stop(self):
        with patch("deployment.structure.command", return_value=(
            'LISTEN 0 128 127.0.0.1:8768 0.0.0.0:* users:(("gunicorn",pid=42,fd=3))'
        )) as query, patch("deployment.structure.listener_identity", return_value=True) as identity:
            self.profile.service()
            identity.return_value = False
            with self.assertRaisesRegex(ValueError, "Identidad o cgroup"):
                self.profile.service()
            identity.return_value = True
            query.return_value = query.return_value.replace("127.0.0.1", "0.0.0.0")
            with self.assertRaisesRegex(ValueError, "no atribuible"):
                self.profile.service()
            self.current.update(ActiveState="inactive", MainPID="0")
            with self.assertRaisesRegex(ValueError, "siguen activos"):
                self.profile.service(stopped=True)
            query.return_value = ""
            self.profile.service(stopped=True)

    def test_writers_fail_closed_when_foreign_present_during_drain_or_unobservable(self):
        report = {"complete": True, "paths": sorted(map(str, self.profile.writable)),
                  "writers": [{"group": "/stage"}]}
        with patch("deployment.structure.command", side_effect=lambda *_: json.dumps(report)):
            self.assertEqual(self.profile.writers(), 1)
            with self.assertRaisesRegex(ValueError, "escritores no autorizados"):
                self.profile.writers(drained=True)
            report["writers"][0]["group"] = "/foreign"
            with self.assertRaisesRegex(ValueError, "escritores no autorizados"):
                self.profile.writers()
            report.update(writers=[], complete=False)
            with self.assertRaisesRegex(ValueError, "Visibilidad incompleta"):
                self.profile.writers(drained=True)
            report["complete"] = True
            self.assertEqual(self.profile.writers(drained=True), 0)
