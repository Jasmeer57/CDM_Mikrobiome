#!/usr/bin/env python3
"""Spec 12 — turn a *human-reviewed* sheet into calibrated accept/reject thresholds.

Reads the review sheet produced by ``build_calibration_sample.py`` once a human
has filled in ``human_verdict``, and computes, per stratum, a precision estimate
with a Wilson score interval. A stratum is marked ``ACCEPTABLE`` only when:

  * at least ``--min_n`` verdicts were given for it, and
  * the **Wilson lower bound** of its precision clears ``--min_wilson_lower``.

Everything else stays ``REVIEW_REQUIRED``. The stage is **fail-closed**:

  * no verdicts at all            -> ``NOT_CALIBRATED``, no stratum accepted
  * a stratum below the sample    -> ``INSUFFICIENT_SAMPLE``
    floor
  * ``UNCERTAIN`` verdicts are    -> excluded from precision (never counted as
    correct)
  * an unrecognised verdict value -> counted as invalid and excluded
  * a missing file / bad header   -> ``NOT_CALIBRATED``

The output is a *proposal* derived from the labels actually supplied. It is not a
verdict, and it does not claim correctness beyond the sample it was computed on.

Outputs (in ``--out_dir``)
--------------------------
    calibration_thresholds.json    per-stratum decision + parameters + provenance
    calibration_report.md          human-readable summary

``calibration_thresholds.json`` carries ``accept_strata`` as the only thing
``project_mappings.py`` is allowed to act on.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_calibration_sample import (  # noqa: E402
    RELATION_VOCAB, VERDICTS, stratum_of,
)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())

# 95% two-sided normal quantile. Kept as a literal so the interval is defined
# without pulling in scipy (this stage must run offline on a CPU node).
Z_95 = 1.959963984540054


def wilson_interval(k: int, n: int, z: float = Z_95):
    """Wilson score interval for ``k`` successes in ``n`` trials.

    Returns ``(lower, upper)``; ``(None, None)`` when ``n == 0``. The Wilson
    interval is used instead of ``k/n`` alone because it stays honest at small
    ``n`` — a 10/10 stratum does not get treated as certainly perfect.
    """
    if n <= 0:
        return None, None
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "t")


def load_sheet(path: Path):
    """Read the review sheet; return ``(rows, invalid_verdicts, unlabeled)``.

    ``rows`` only contains rows carrying a valid verdict, so a row the reviewer
    skipped can never be silently promoted.
    """
    rows, invalid, unlabeled = [], [], 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "human_verdict" not in reader.fieldnames:
            raise ValueError("review sheet has no human_verdict column: %s" % path)
        for r in reader:
            raw = (r.get("human_verdict") or "").strip()
            if not raw:
                unlabeled += 1
                continue
            verdict = raw.upper()
            if verdict not in VERDICTS:
                invalid.append({"sample_id": r.get("sample_id"), "value": raw})
                continue
            r["_verdict"] = verdict
            rows.append(r)
    return rows, invalid, unlabeled


def summarize_stratum(rows, seed_stratum, min_n, min_wilson_lower):
    """Per-stratum precision with Wilson CI and a fail-closed decision."""
    n_correct = sum(1 for r in rows if r["_verdict"] == "CORRECT")
    n_incorrect = sum(1 for r in rows if r["_verdict"] == "INCORRECT")
    n_uncertain = sum(1 for r in rows if r["_verdict"] == "UNCERTAIN")
    n_labeled = n_correct + n_incorrect           # UNCERTAIN excluded on purpose
    n_reviewed = n_labeled + n_uncertain
    precision = (n_correct / n_labeled) if n_labeled else None
    lo, hi = wilson_interval(n_correct, n_labeled)

    # Reweight to the stratum population using the inverse sampling fraction.
    w_correct = sum(float(r.get("sampling_weight") or 1.0) for r in rows
                    if r["_verdict"] == "CORRECT")
    w_labeled = sum(float(r.get("sampling_weight") or 1.0) for r in rows
                    if r["_verdict"] in ("CORRECT", "INCORRECT"))
    weighted = (w_correct / w_labeled) if w_labeled else None

    if n_labeled == 0:
        decision, reason = "NO_LABELS", "only UNCERTAIN/blank verdicts"
    elif n_labeled < min_n:
        decision, reason = "INSUFFICIENT_SAMPLE", "n_labeled < min_n"
    elif lo is not None and lo >= min_wilson_lower:
        decision, reason = "ACCEPTABLE", "wilson_lower >= threshold"
    else:
        decision, reason = "BELOW_THRESHOLD", "wilson_lower < threshold"

    return {
        "stratum": seed_stratum,
        "n_reviewed": n_reviewed,
        "n_labeled": n_labeled,
        "n_correct": n_correct,
        "n_incorrect": n_incorrect,
        "n_uncertain": n_uncertain,
        "precision_point": None if precision is None else round(precision, 6),
        "precision_weighted": None if weighted is None else round(weighted, 6),
        "wilson_lower": None if lo is None else round(lo, 6),
        "wilson_upper": None if hi is None else round(hi, 6),
        "decision": decision,
        "reason": reason,
    }


def _split_stratum(stratum: str):
    """``"bioportal|EXACT_MATCH"`` -> ``("bioportal", "EXACT_MATCH")``."""
    svc, _, rel = stratum.partition("|")
    return (svc or None, rel or None)


def main():
    ap = argparse.ArgumentParser(
        description="Spec 12 — calibrate CV-link acceptance thresholds from a "
                    "human-reviewed sheet")
    ap.add_argument("--review_sheet", type=Path, required=True)
    ap.add_argument("--out_dir", type=Path, required=True)
    ap.add_argument("--min_n", type=int, default=30,
                    help="minimum labeled rows per stratum to decide (default 30)")
    ap.add_argument("--min_wilson_lower", type=float, default=0.98,
                    help="required Wilson lower bound for ACCEPTABLE (default 0.98)")
    ap.add_argument("--confidence", type=float, default=0.95,
                    help="nominal interval level (the z used is fixed at 95%%; "
                         "recorded for provenance)")
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    notes, invalid, unlabeled = [], [], 0
    rows = []
    sheet_sha = None
    if not args.review_sheet.exists():
        notes.append("review sheet not found: %s" % args.review_sheet)
    else:
        sheet_sha = hashlib.sha256(args.review_sheet.read_bytes()).hexdigest()
        try:
            rows, invalid, unlabeled = load_sheet(args.review_sheet)
        except ValueError as ex:
            notes.append(str(ex))

    # Recompute the stratum from the row rather than trusting the column, and
    # surface any mismatch instead of quietly grouping on a stale value.
    mismatches = 0
    primary, controls = defaultdict(list), defaultdict(list)
    for r in rows:
        recomputed = stratum_of(r.get("source_service"), r.get("mapping_relation"))
        if (r.get("stratum") or "") != recomputed:
            mismatches += 1
        bucket = primary if (r.get("sample_role") or "") == "primary" else controls
        bucket[recomputed].append(r)
    if mismatches:
        notes.append("%d row(s) had a stratum column inconsistent with the row; "
                     "grouped by the recomputed value" % mismatches)
    if invalid:
        notes.append("%d row(s) carried an unrecognised human_verdict value and "
                     "were EXCLUDED from precision (they are never counted as "
                     "correct); re-check the sheet if this count is unexpected"
                     % len(invalid))

    strata = [summarize_stratum(rows_, s, args.min_n, args.min_wilson_lower)
              for s, rows_ in sorted(primary.items())]
    control_stats = [summarize_stratum(rows_, s, args.min_n, args.min_wilson_lower)
                     for s, rows_ in sorted(controls.items())]

    accept_strata = [s for s in strata if s["decision"] == "ACCEPTABLE"]
    if not rows:
        overall = "NOT_CALIBRATED"
        overall_reason = "no valid human verdicts present"
    elif accept_strata and len(accept_strata) == len(strata):
        overall = "CALIBRATED"
        overall_reason = "every primary stratum cleared the threshold"
    elif accept_strata:
        overall = "PARTIALLY_CALIBRATED"
        overall_reason = "%d/%d primary strata cleared the threshold" % (
            len(accept_strata), len(strata))
    else:
        overall = "NOT_CALIBRATED"
        overall_reason = "no primary stratum cleared the threshold"

    enabled = overall in ("CALIBRATED", "PARTIALLY_CALIBRATED") and bool(accept_strata)

    thresholds = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": overall,
        "reason": overall_reason,
        "auto_accept_enabled": enabled,
        "parameters": {
            "min_n": args.min_n,
            "min_wilson_lower": args.min_wilson_lower,
            "interval_level": args.confidence,
            "z_used": Z_95,
            "precision_denominator": "CORRECT + INCORRECT (UNCERTAIN excluded)",
            "reweighting": "inverse sampling fraction (sampling_weight)",
        },
        "inputs": {
            "review_sheet": str(args.review_sheet),
            "review_sheet_sha256": sheet_sha,
        },
        "counts": {
            "valid_labeled_rows": len(rows),
            "unlabeled_rows": unlabeled,
            "invalid_verdict_rows": len(invalid),
            "primary_strata": len(strata),
            "control_strata": len(control_stats),
        },
        "invalid_verdicts": invalid[:50],
        # The ONLY key project_mappings.py acts on.
        "accept_strata": [
            {
                "source_service": _split_stratum(s["stratum"])[0],
                "mapping_relation": _split_stratum(s["stratum"])[1],
                "n_labeled": s["n_labeled"],
                "precision_point": s["precision_point"],
                "wilson_lower": s["wilson_lower"],
            }
            for s in accept_strata
        ],
        "accept_pair_keys": [
            "%s|%s" % (_split_stratum(s["stratum"])[0] or "none",
                       _split_stratum(s["stratum"])[1] or "none")
            for s in accept_strata
        ],
        "strata": strata,
        "control_strata": control_stats,
        "relation_vocabulary": list(RELATION_VOCAB),
        "caveats": [
            "A threshold is a property of the labelled sample, not proof of "
            "correctness on the unlabelled population.",
            "No stratum is accepted below the min_n floor regardless of how "
            "clean its sample looks.",
            "UNCERTAIN verdicts were excluded from precision; they never "
            "count as correct.",
            "Control strata are reported but never accepted: they exist to "
            "audit the eligibility rule.",
        ] + notes,
    }
    with (out_dir / "calibration_thresholds.json").open("w", encoding="utf-8") as f:
        json.dump(thresholds, f, indent=2)

    def _table(entries):
        if not entries:
            return "| _(none)_ | | | | |\n"
        out = ""
        for s in entries:
            out += ("| `%s` | %d | %.3f | %s | %s |\n"
                    % (s["stratum"], s["n_labeled"],
                       -1.0 if s["precision_point"] is None else s["precision_point"],
                       "n/a" if s["wilson_lower"] is None else "%.3f" % s["wilson_lower"],
                       s["decision"]))
        return out

    report = [
        "# CV-link calibration report (spec 12)",
        "",
        "Generated: %s" % thresholds["generated_at"],
        "",
        "**Status: `%s`** — %s" % (overall, overall_reason),
        "**Auto-accept enabled: `%s`**" % enabled,
        "",
        "Parameters: `min_n=%d`, `min_wilson_lower=%.3f`, interval `%.0f%%` "
        "(Wilson, z=%.6f). Precision denominator excludes `UNCERTAIN`."
        % (args.min_n, args.min_wilson_lower, args.confidence * 100, Z_95),
        "",
        "Review sheet: `%s`  " % args.review_sheet,
        "sha256: `%s`" % (sheet_sha or "n/a"),
        "",
        "Labeled rows: %d (unlabeled %d, invalid verdicts %d)."
        % (len(rows), unlabeled, len(invalid)),
        "",
        "## Primary strata",
        "",
        "| stratum | n_labeled | precision | wilson_lower | decision |",
        "|---|---|---|---|---|",
        _table(strata).rstrip("\n"),
        "",
        "## Control strata (audit only — never accepted)",
        "",
        "| stratum | n_labeled | precision | wilson_lower | decision |",
        "|---|---|---|---|---|",
        _table(control_stats).rstrip("\n"),
        "",
        "## Caveats",
        "",
    ] + ["* %s" % c for c in thresholds["caveats"]] + [
        "",
        "Nothing is auto-accepted by this report alone: the only artifact "
        "`project_mappings.py` reads is `calibration_thresholds.json`, and only "
        "when `auto_accept_enabled` is true.",
        "",
    ]
    (out_dir / "calibration_report.md").write_text("\n".join(report), encoding="utf-8")

    print(json.dumps({"status": overall, "auto_accept_enabled": enabled,
                      "primary_strata": len(strata), "accepted": len(accept_strata),
                      "labeled_rows": len(rows), "unlabeled_rows": unlabeled,
                      "invalid_verdicts": len(invalid)}, indent=2))
    if not enabled:
        print("nothing auto-accepted: calibration not established "
              "(this is the expected state until labels exist)")
    print("wrote %s" % (out_dir / "calibration_thresholds.json"))


if __name__ == "__main__":
    main()
