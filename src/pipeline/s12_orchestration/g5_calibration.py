"""G5 — calibration state for terminology releases.

Fail conditions
---------------
* ``auto_accepted > 0`` and no calibration file (thresholds) was supplied.
* Any accepted row is not ``auto_accept_eligible``.
* Any accepted row lacks a cleared calibration verdict.

The 1.0.0 freeze is expected to be ``NOT_CALIBRATED`` with an empty human review
sheet and zero accepted rows, so G5 passes while recording the stale calibration
sample (drawn against 334,275 mapping rows; current table has 334,231).
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from pipeline.s12_orchestration._common import FAIL, MISSING, PASS, SKIPPED, is_terminology_release, iter_jsonl, load_json, target_result

GATE = "G5"

HUMAN_COLUMNS = (
    "human_verdict",
    "human_relation",
    "human_confidence",
    "human_notes",
    "reviewer",
    "reviewed_at",
)

ACCEPTED_DISPOSITIONS = {"AUTO_ACCEPTED", "ACCEPTED"}
CLEARED_VERDICTS = {"CORRECT", "CLEARED", "AUTO_ACCEPT", "ACCEPT"}


def _truthy(value) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "accepted", "auto_accepted"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


def _mapping_path(target: Path, repo_root: Path) -> Path | None:
    candidates = (
        target / "term_ontology_mappings.jsonl",
        repo_root / "outputs/results" / "terminology_v1" / "term_ontology_mappings.jsonl",
    )
    return next((p for p in candidates if p.is_file()), None)


def run(target: Path, repo_root: Path) -> dict:
    target = Path(target)
    repo_root = Path(repo_root)
    if not target.is_dir():
        return target_result(GATE, target, MISSING, {"reason": "target directory missing"})
    if not is_terminology_release(target):
        return target_result(
            GATE,
            target,
            SKIPPED,
            {"reason": "not a terminology release (no terminology_extraction_manifest.json)"},
        )

    mappings_path = _mapping_path(target, repo_root)
    if mappings_path is None:
        return target_result(GATE, target, MISSING, {"reason": "term_ontology_mappings.jsonl missing"})

    calibration_dir = repo_root / "outputs/results" / "terminology_v1" / "calibration"
    summary_path = calibration_dir / "_calibration_sample_summary.json"
    sheet_path = calibration_dir / "calibration_sample.csv"
    thresholds_path = calibration_dir / "calibration_thresholds.json"

    if not summary_path.is_file():
        return target_result(
            GATE,
            target,
            MISSING,
            {"reason": "calibration summary missing", "path": str(summary_path)},
        )
    if not sheet_path.is_file():
        return target_result(
            GATE,
            target,
            MISSING,
            {"reason": "calibration review sheet missing", "path": str(sheet_path)},
        )

    eligible = accepted = accepted_ineligible = accepted_without_cleared = 0
    scanned = 0
    dispositions = Counter()
    review_statuses = Counter()
    acceptance_fields = Counter()

    for row in iter_jsonl(mappings_path):
        scanned += 1
        is_eligible = _truthy(row.get("auto_accept_eligible"))
        if is_eligible:
            eligible += 1

        is_accepted = False
        for field in ("auto_accepted", "accepted"):
            if _truthy(row.get(field)):
                is_accepted = True
                acceptance_fields[field] += 1
        disposition = str(row.get("mapping_disposition") or "").upper()
        review_status = str(row.get("review_status") or "").upper()
        if disposition in ACCEPTED_DISPOSITIONS:
            is_accepted = True
            acceptance_fields["mapping_disposition"] += 1
        if review_status in ACCEPTED_DISPOSITIONS:
            is_accepted = True
            acceptance_fields["review_status"] += 1

        if is_accepted:
            accepted += 1
            if not is_eligible:
                accepted_ineligible += 1
            verdict = str(row.get("calibration_verdict") or row.get("verdict") or "").upper()
            if verdict not in CLEARED_VERDICTS:
                accepted_without_cleared += 1

        dispositions[str(row.get("mapping_disposition"))] += 1
        review_statuses[str(row.get("review_status"))] += 1

    try:
        summary = load_json(summary_path)
    except Exception as exc:  # fail closed
        return target_result(
            GATE,
            target,
            MISSING,
            {"reason": f"cannot read calibration summary: {exc}", "path": str(summary_path)},
        )

    summary_keys = list(summary.keys())
    build_keys = [
        key
        for key in ("job_id", "build_id", "run_id", "producing_build", "source_build", "build")
        if key in summary
    ]
    names_producing_build = any(summary.get(key) for key in build_keys)
    summary_total = (summary.get("counts") or {}).get("mappings_rows_total")

    sheet_rows = 0
    human_nonempty_cells = 0
    with open(sheet_path, encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sheet_rows += 1
            for column in HUMAN_COLUMNS:
                if (row.get(column) or "").strip():
                    human_nonempty_cells += 1

    calibration_file_supplied = thresholds_path.is_file()
    calibration_status = "CALIBRATED" if calibration_file_supplied else "NOT_CALIBRATED"

    problems = []
    if accepted > 0 and not calibration_file_supplied:
        problems.append(f"auto_accepted={accepted} with no calibration file supplied")
    if accepted_ineligible > 0:
        problems.append(f"{accepted_ineligible} accepted row(s) not auto_accept_eligible")
    if accepted_without_cleared > 0:
        problems.append(f"{accepted_without_cleared} accepted row(s) lack a cleared verdict")

    status = PASS if not problems else FAIL
    details = {
        "mappings_path": str(mappings_path),
        "mapping_rows_scanned": scanned,
        "auto_accept_eligible": eligible,
        "auto_accepted": accepted,
        "accepted_ineligible": accepted_ineligible,
        "accepted_without_cleared_verdict": accepted_without_cleared,
        "acceptance_fields_seen": dict(acceptance_fields),
        "mapping_dispositions": dict(dispositions),
        "review_statuses": dict(review_statuses),
        "calibration_summary": str(summary_path),
        "calibration_summary_keys": summary_keys,
        "calibration_summary_names_producing_build": names_producing_build,
        "calibration_summary_build_keys": build_keys,
        "calibration_summary_mappings_rows_total": summary_total,
        "calibration_summary_matches_current_table": summary_total == scanned,
        "calibration_status": calibration_status,
        "calibration_file_supplied": calibration_file_supplied,
        "thresholds_path": str(thresholds_path),
        "review_sheet": str(sheet_path),
        "review_sheet_rows": sheet_rows,
        "review_sheet_human_nonempty_cells": human_nonempty_cells,
        "review_sheet_empty": human_nonempty_cells == 0,
        "problems": problems,
    }
    return target_result(GATE, target, status, details)
