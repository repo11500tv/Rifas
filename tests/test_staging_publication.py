"""Protección Basic y dependencias del lote de staging."""

from email.message import Message
import io
from unittest import TestCase
from unittest.mock import ANY, Mock, patch
from urllib.error import HTTPError

from deployment.hooks import Hooks, probe_status
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
        journal = {"phase": "committed"}
        with (patch.object(self.transaction, "checkpoint"), patch.object(self.transaction, "verify_dependencies"),
              patch.object(self.transaction, "step") as step,
              patch.object(self.transaction, "verify_publication",
                           side_effect=[ValueError("lost Basic"), None]) as publication):
            with self.assertRaisesRegex(ValueError, "lost Basic"):
                self.transaction.finish("fixture", journal)
        self.assertEqual([call.args[0] for call in step.call_args_list], ["reopen", "close"])
        self.assertEqual([call.args[0] for call in publication.call_args_list], [401, 503])
        self.transaction.pending.unlink.assert_not_called()
        self.assertEqual(journal["publication"], "closed_verified")

    def test_failed_second_close_keeps_journal_and_reports_unverified(self):
        for close_fails in (True, False):
            with self.subTest(close_fails=close_fails):
                journal = {"phase": "committed", "run": "fixture", "digest": "fixture"}
                self.transaction.pending = Mock()
                self.transaction.deployment.reset_mock()
                with (patch.object(self.transaction, "checkpoint") as checkpoint,
                      patch.object(self.transaction, "verify_dependencies"),
                      patch.object(self.transaction, "step") as step,
                      patch.object(self.transaction, "verify_publication") as publication):
                    step.side_effect = [None, RuntimeError("close failed") if close_fails else None]
                    publication.side_effect = [ValueError("lost Basic"), ValueError("still public")]
                    with self.assertRaisesRegex(RuntimeError, "no se verificó el nuevo cierre"):
                        self.transaction.finish("fixture", journal)
                    checkpoint.assert_called_once_with(ANY, "committed")
                self.assertEqual(journal["publication"], "unverified")
                self.transaction.pending.unlink.assert_not_called()
                self.transaction.deployment.event.assert_called_once_with(
                    "intervention_reclose_failed", barrier="unverified",
                )

    def test_release_hook_also_fails_if_both_reopen_and_reclose_fail(self):
        hook = Hooks.__new__(Hooks)
        hook.settings = {"private_url": "http://127.0.0.1:8768/health"}
        hook.public_urls = self.transaction.publication
        hook.public_open_status = 401
        hook.gate = Mock()
        hook.check_invocation = Mock()
        hook.run = Mock()
        hook.wait = Mock(side_effect=[None, RuntimeError("lost Basic")])
        hook.close_gate = Mock(side_effect=RuntimeError("no 503"))
        with (patch.dict("os.environ", {"RIFAS_RELEASE_ROOT": "/fixture"}),
              patch("deployment.hooks.sync")):
            with self.assertRaisesRegex(RuntimeError, "no se completó el nuevo cierre"):
                hook.resume()
        hook.close_gate.assert_called_once()
