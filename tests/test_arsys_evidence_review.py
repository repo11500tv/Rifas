import json
from pathlib import Path
import unittest

from deployment.arsys.evidence_review import REVIEW_GROUPS, review


class EvidenceReviewTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.matrix = json.loads((root / "deployment/arsys/evidence-and-inverses.example.json").read_text())

    def test_template_preserves_unknowns(self):
        result = review(self.matrix)
        self.assertEqual(result["resolved_competing_routes"], 0)
        self.assertEqual(len(result["open_evidence"]), 31)
        self.assertFalse(result["intervention_authorized"])

    def test_bypass_and_unverified_coverage_cannot_close_route(self):
        route = self.matrix["nginx_candidate_register"][0]
        route.update(disposition="staging_entry", evidence={
            "file_reference": "F01", "line": 42, "effective_match": "M01",
            "target": "staging_8768", "basic_scope": "verified",
            "maintenance_scope": "unverified", "review_evidence": "E01",
        })
        self.assertIn("N01", review(self.matrix)["open_evidence"])
        route["evidence"]["maintenance_scope"] = "verified"
        self.assertNotIn("N01", review(self.matrix)["open_evidence"])
        route["disposition"] = "bypass"
        self.assertIn("N01", review(self.matrix)["open_evidence"])

    def test_complete_evidence_does_not_authorize_and_raw_values_are_not_reported(self):
        for group, fields in REVIEW_GROUPS.items():
            self.matrix[group].update(dict.fromkeys(fields, "E01"))
        for line, route in enumerate(self.matrix["nginx_candidate_register"], start=1):
            route.update(disposition="excluded", evidence={
                "file_reference": "F01", "line": line, "effective_match": "M01",
                "target": "outside_staging", "basic_scope": "not_applicable",
                "maintenance_scope": "not_applicable", "review_evidence": "E01",
            })
        result = review(self.matrix)
        self.assertTrue(result["evidence_complete"])
        self.assertFalse(result["intervention_authorized"])
        self.matrix["identity"]["user"] = "not-a-sanitized-reference"
        result = review(self.matrix)
        self.assertIn("identity.user", result["open_evidence"])
        self.assertNotIn("not-a-sanitized-reference", json.dumps(result))

    def test_one_source_location_cannot_close_multiple_slots(self):
        for row in self.matrix["nginx_candidate_register"][:2]:
            row.update(disposition="excluded", evidence={
                "file_reference": "F01", "line": 42, "effective_match": "M01",
                "target": "outside_staging", "basic_scope": "not_applicable",
                "maintenance_scope": "not_applicable", "review_evidence": "E01",
            })
        result = review(self.matrix)
        self.assertEqual(result["resolved_competing_routes"], 0)
        self.assertIn("N01", result["open_evidence"])
        self.assertIn("N02", result["open_evidence"])
