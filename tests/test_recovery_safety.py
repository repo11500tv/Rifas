"""Recovery safety tests with a synthetic coordinator; never touches a live service."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deployment.deploy import Deployment


class RecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.deploy = Deployment.__new__(Deployment)
        self.deploy.name = "staging"
        self.deploy.state = Path(self.temp.name)
        self.deploy.installation_manifest = str(self.deploy.state / "installation.json")
        self.deploy.hooks = {"drain": ["/bin/true"], "activate": ["/bin/true"],
                             "ready": ["/bin/true"], "resume": ["/bin/true"]}
        self.deploy.run = "synthetic-run"

    def journal(self, phase):
        return {"phase": phase, "run": "synthetic-run", "digest": "synthetic",
                "external_snapshot": True, "previous": None, "components": [],
                "databases": [], "schema": {}, "snapshot": {}}

    def test_changing_recovery_blocks_before_drain_on_external_drift(self):
        with patch("deployment.deploy.backup_external.assert_external_unchanged",
                   side_effect=RuntimeError("external drift")) as verify, \
             patch.object(self.deploy, "hook") as hook, \
             patch.object(self.deploy, "check_scope") as scope, \
             patch("deployment.deploy.snapshot.restore") as restore:
            with self.assertRaisesRegex(RuntimeError, "external drift"):
                self.deploy.recover_pending(self.journal("changing"))
        verify.assert_called_once()
        hook.assert_not_called()
        scope.assert_not_called()
        restore.assert_not_called()

    def test_committed_recovery_blocks_resume_on_external_drift(self):
        with patch("deployment.deploy.backup_external.assert_external_unchanged",
                   side_effect=RuntimeError("external drift")), \
             patch.object(self.deploy, "finish") as finish:
            with self.assertRaisesRegex(RuntimeError, "external drift"):
                self.deploy.recover_pending(self.journal("committed"))
        finish.assert_not_called()

    def test_recovery_without_external_snapshot_uses_existing_path(self):
        journal = self.journal("committed")
        journal.pop("external_snapshot")
        with patch("deployment.deploy.backup_external.assert_external_unchanged") as verify, \
             patch.object(self.deploy, "finish") as finish:
            self.deploy.recover_pending(journal)
        verify.assert_not_called()
        finish.assert_called_once_with(journal)


    def test_changing_recovery_restores_snapshot_and_resumes(self):
        journal = self.journal("changing")
        journal["external_snapshot"] = False
        calls = []
        self.deploy.root = self.deploy.state / "data"
        self.deploy.root.mkdir()
        with patch.object(self.deploy, "check_scope") as scope, \
             patch.object(self.deploy, "hook", side_effect=lambda name, *_: calls.append(name)), \
             patch.object(self.deploy, "check_operation") as operation, \
             patch("deployment.deploy.snapshot.restore", side_effect=lambda *_: calls.append("restore")) as restore, \
             patch("deployment.deploy.schema.validate", return_value=[]) as validate, \
             patch.object(self.deploy, "point_to", side_effect=lambda *_: calls.append("point_to")), \
             patch.object(self.deploy, "checkpoint", side_effect=lambda *args: calls.append("checkpoint")), \
             patch.object(self.deploy, "finish", side_effect=lambda *_: calls.append("finish")):
            self.deploy.recover_pending(journal)
        restore.assert_called_once()
        validate.assert_called_once()
        self.assertEqual(calls, ["drain", "restore", "point_to", "activate",
                                 "checkpoint", "finish"])

if __name__ == "__main__":
    unittest.main()
