"""Protección Basic y dependencias del lote de staging."""

from email.message import Message
import io
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from deployment.hooks import probe_status
from deployment.intervention import Intervention


class StagingPublicationTest(TestCase):
    def setUp(self):
        self.transaction = Intervention.__new__(Intervention)
        self.transaction.deployment = Mock()
        self.transaction.deployment.structure.settings = {
            "unit": "staging.service", "peer_unit": "production.service",
        }
        self.transaction.publication = ["https://staging.example.invalid/rifas/health",
                                        "https://alias.example.invalid/rifas/health"]
        self.transaction.unit_scope = {
            "unit": "staging.service", "auxiliary_units": ["jobs.timer"],
            "protected_units": ["production.service", "legacy.service"],
        }

    def test_requires_https_without_embedded_credentials(self):
        self.transaction.validate_staging_scope()
        self.transaction.publication.append("https://fixture:secret@staging.example.invalid/health")
        with self.assertRaisesRegex(ValueError, "credenciales"):
            self.transaction.validate_staging_scope()

    def test_anonymous_probe_only_accepts_basic_challenge(self):
        opener = Mock()
        url = self.transaction.publication[0]
        for challenge, expected in ((None, None), ("Bearer fixture", None),
                                    ('Basic realm="fixture"', 401)):
            headers = Message()
            if challenge:
                headers["WWW-Authenticate"] = challenge
            opener.open.side_effect = HTTPError(url, 401, "Unauthorized", headers, io.BytesIO())
            self.assertEqual(probe_status(opener, url), expected)
            opener.open.assert_called_with(url, timeout=2)

    def test_publication_checks_every_reviewed_alias(self):
        with patch("deployment.intervention.probe_status", side_effect=[401, 200]):
            with self.assertRaisesRegex(ValueError, "Entrada pública 2"):
                self.transaction.verify_publication(401)
        with patch("deployment.intervention.probe_status", side_effect=[503, 503]) as probe:
            self.transaction.verify_publication(503)
            self.assertEqual([call.args[1] for call in probe.call_args_list], self.transaction.publication)

    def test_direct_coupling_to_protected_unit_blocks(self):
        results = ["Id=staging.service\nLoadState=loaded\n", "Id=jobs.timer\nLoadState=loaded\n"]
        with patch("deployment.intervention.command", side_effect=results) as command:
            self.transaction.verify_dependencies()
            self.assertEqual([call.args[-1] for call in command.call_args_list], ["staging.service", "jobs.timer"])
        with patch("deployment.intervention.command", return_value=(
            "Id=staging.service\nLoadState=loaded\nPropagatesStopTo=legacy.service\n"
        )):
            with self.assertRaisesRegex(ValueError, "unidad protegida"):
                self.transaction.verify_dependencies()

    def test_exposed_reopen_recloses_without_erasing_pending_state(self):
        self.transaction.pending = Mock()
        with (patch.object(self.transaction, "verify_dependencies"),
              patch.object(self.transaction, "step") as step,
              patch.object(self.transaction, "verify_publication",
                           side_effect=[ValueError("lost Basic"), None]) as publication):
            with self.assertRaisesRegex(ValueError, "lost Basic"):
                self.transaction.finish("fixture")
        self.assertEqual([call.args[0] for call in step.call_args_list], ["reopen", "close"])
        self.assertEqual([call.args[0] for call in publication.call_args_list], [401, 503])
        self.transaction.pending.unlink.assert_not_called()
