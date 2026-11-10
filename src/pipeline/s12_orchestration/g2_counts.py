"""G2 — three-way count reconciliation for terminology releases.

For each countable artifact the gate compares:

    coverage.<alias>  ==  artifacts[<file>].records  ==  physical lines

The coverage block in the 1.0.0 freeze uses legacy key names (``mention_records``,
``canonical_terms``, ``definition_rows``, ``mapping_rows``) rather than a uniform
``<name>_records`` spelling, so aliases are tried explicitly.

Known defect (expected, do not repair the frozen artifact):
    term_mentions.jsonl coverage.mention_records = 2,505,736
    term_mentions.jsonl artifacts.records        = 2,505,735
    term_mentions.jsonl physical lines           = 2,505,735
"""

from __future__ import annotations

from pathlib import Path

from pipeline.s12_orchestration._common import FAIL, MISSING, PASS, SKIPPED, count_physical_lines, is_terminology_release, load_json, target_result

GATE = "G2"

ARTIFACTS = [
    ("term_mentions.jsonl", ("mention_records",)),
    ("canonical_terms.jsonl", ("canonical_terms_records", "canonical_terms")),
    ("term_definitions.jsonl", ("definition_records", "definition_rows")),
    ("term_ontology_mappings.jsonl", ("mapping_records", "mapping_rows")),
]

KNOWN_MENTIONS = (2505736, 2505735, 2505735)


def _artifact_records(manifest: dict) -> dict:
    """Normalise ``artifacts`` whether the manifest uses a list or a mapping."""
    artifacts = manifest.get("artifacts")
    out = {}
    if isinstance(artifacts, list):
        for item in artifacts:
            if isinstance(item, dict) and item.get("name"):
                out[item["name"]] = item.get("records")
    elif isinstance(artifacts, dict):
        for name, item in artifacts.items():
            out[name] = item.get("records") if isinstance(item, dict) else item
    return out


def run(target: Path) -> dict:
    target = Path(target)
    if not target.is_dir():
        return target_result(GATE, target, MISSING, {"reason": "target directory missing"})
    if not is_terminology_release(target):
        return target_result(
            GATE,
            target,
            SKIPPED,
            {"reason": "not a terminology release (no terminology_extraction_manifest.json)"},
        )

    manifest_path = target / "terminology_extraction_manifest.json"
    try:
        manifest = load_json(manifest_path)
    except Exception as exc:  # fail closed
        return target_result(GATE, target, MISSING, {"reason": f"cannot read manifest: {exc}"})

    coverage = manifest.get("coverage") or {}
    artifact_records = _artifact_records(manifest)

    rows = {}
    missing_inputs = []
    mismatches = []
    known_defect = False

    for name, aliases in ARTIFACTS:
        coverage_key = next((key for key in aliases if key in coverage), None)
        coverage_value = coverage.get(coverage_key) if coverage_key else None
        declared = artifact_records.get(name)
        path = target / name
        physical = count_physical_lines(path) if path.is_file() else None

        rows[name] = {
            "coverage_key": coverage_key,
            "coverage": coverage_value,
            "artifact_records": declared,
            "physical_lines": physical,
        }

        if not path.is_file():
            missing_inputs.append(f"{name}: MISSING file")
            continue
        if coverage_key is None:
            mismatches.append(f"{name}: coverage key missing (tried {list(aliases)})")
        if declared is None:
            mismatches.append(f"{name}: artifacts.records missing")
        if coverage_value is not None and declared is not None and physical is not None:
            if not (coverage_value == declared == physical):
                mismatches.append(
                    f"{name}: coverage={coverage_value} artifact={declared} physical={physical}"
                )
                if name == "term_mentions.jsonl" and (
                    coverage_value,
                    declared,
                    physical,
                ) == KNOWN_MENTIONS:
                    known_defect = True

    if missing_inputs:
        status = MISSING
    elif mismatches:
        status = FAIL
    else:
        status = PASS

    details = {
        "manifest": str(manifest_path),
        "artifacts": rows,
        "missing_inputs": missing_inputs,
        "mismatches": mismatches,
        "known_defect": known_defect,
    }
    if known_defect:
        details["note"] = (
            "G2 FAIL (expected) — 2,505,736 vs 2,505,735 — known defect, deferred "
            "to the next build; do NOT repair the frozen artifact."
        )
    return target_result(GATE, target, status, details)
