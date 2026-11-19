"""Comprobación local de la matriz saneada. No consulta servidores."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

REVIEW_REFERENCE = r"E[0-9]{2,4}"
ROUTE_FIELDS = {
    "file_reference", "line", "effective_match", "target",
    "basic_scope", "maintenance_scope", "review_evidence",
}
REVIEW_GROUPS = {
    "identity": (
        "user", "group", "operator", "delegation_policy",
        "effective_permission_evidence", "mount_namespace_evidence",
    ),
    "publication": (
        "ordered_includes_review", "apache_review", "direct_8768_review",
        "verified_https_urls", "basic_preservation", "maintenance_coverage",
    ),
    "writers": (
        "systemd_transitive_review", "user_cron_review", "plesk_scheduler_review",
        "pause_and_drain_evidence",
    ),
}


def reference(value, pattern=REVIEW_REFERENCE):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def route_resolved(row):
    evidence = row.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != ROUTE_FIELDS:
        return False
    if (not reference(evidence["file_reference"], r"F[0-9]{2,4}")
            or type(evidence["line"]) is not int or evidence["line"] < 1
            or not reference(evidence["effective_match"], r"M[0-9]{2,4}")
            or not reference(evidence["review_evidence"])):
        return False
    if row.get("disposition") == "staging_entry":
        return (evidence["target"] == "staging_8768"
                and evidence["basic_scope"] == "verified"
                and evidence["maintenance_scope"] == "verified")
    if row.get("disposition") == "excluded":
        return (evidence["target"] == "outside_staging"
                and evidence["basic_scope"] == "not_applicable"
                and evidence["maintenance_scope"] == "not_applicable")
    return False


def review(matrix):
    """Devolver únicamente códigos fijos y recuentos, sin reproducir entradas."""
    rows = matrix.get("nginx_candidate_register")
    expected = {f"N{index:02d}" for index in range(1, 16)}
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or not all(isinstance(row, dict) and isinstance(row.get("review_slot"), str) for row in rows)
            or {row["review_slot"] for row in rows} != expected
            or matrix.get("nginx_candidates_count") != len(expected)):
        raise ValueError("registro_de_rutas_invalido")
    resolved = [row for row in rows if route_resolved(row)]
    source_fields = ("file_reference", "line", "effective_match")
    sources = {
        row["review_slot"]: tuple(row["evidence"][key] for key in source_fields)
        for row in resolved
    }
    occurrences = Counter(sources.values())
    closed = {slot for slot, source in sources.items() if occurrences[source] == 1}
    blockers = sorted(expected - closed)
    for group, fields in REVIEW_GROUPS.items():
        evidence = matrix.get(group)
        for field in fields:
            value = evidence.get(field) if isinstance(evidence, dict) else None
            if not reference(value):
                blockers.append(f"{group}.{field}")
    return {
        "resolved_competing_routes": len(closed),
        "open_evidence": blockers,
        "evidence_complete": not blockers,
        "intervention_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    args = parser.parse_args()
    try:
        matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
        if not isinstance(matrix, dict):
            raise ValueError("matrix")
        result = review(matrix)
    except (OSError, ValueError):
        print(json.dumps({"error": "matriz_no_legible_o_invalida"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["evidence_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
