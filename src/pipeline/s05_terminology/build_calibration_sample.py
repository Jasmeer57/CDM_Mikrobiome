#!/usr/bin/env python3
"""Spec 12 — stratified human-review sample for controlled-vocabulary calibration.

The spec requires acceptance thresholds to be calibrated on a *human-reviewed*
sample before anything may be auto-accepted. This stage builds that sample. It
does **not** label it, and it does **not** accept anything: the review columns
ship empty. Machine output and human verification stay separate.

Sampling design
---------------
Rows of ``term_ontology_mappings.jsonl`` are split into three *roles*:

  ``primary``               a candidate that ``auto_accept_eligible`` already
                            marks as qualifying *if a threshold existed*. These
                            drive the accept/reject decision.
  ``non_eligible_control``  a real candidate the current rules would never
                            accept (``RELATED_TO`` / ``AMBIGUOUS``). Sampled to
                            check that the eligibility rule is not discarding
                            correct links.
  ``no_match_control``      a term with no candidate at all. Sampled to check
                            for false negatives (a real term recorded as
                            no-match).

Within each role a *stratum* is ``source_service|mapping_relation``. Selection
is **deterministic**: per stratum the rows are ordered by
``sha1(seed + row_key)`` and the first ``--per_stratum`` are kept. No RNG state
and no builtin ``hash()`` (which is salted per process), so the same seed over
the same input yields the same sample every time.

Each kept row carries ``sampling_weight = rows_in_stratum / rows_kept`` so a
precision estimate can be reweighted back to the full population. A stratum
that fits entirely under the cap has weight ``1.0``.

Outputs (in ``--out_dir``)
--------------------------
    calibration_sample.csv          human review sheet, verdict columns empty
    calibration_sample.jsonl        machine frame, lossless
    _calibration_sample_summary.json
    calibration_review_guide.md

``calibration_sample.jsonl`` is the machine record; the CSV is a view of it. The
BOM on the CSV is only so spreadsheet tools open it as UTF-8. Neither file
contains a verdict.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import itertools
import json
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MAPPINGS = REPO_ROOT / "outputs/results/terminology_v1/term_ontology_mappings.jsonl"

SAMPLE_PREFIX = "HMCAL_"

# The only verdicts ``calibrate_thresholds.py`` will act on. Anything else in a
# submitted sheet is counted as an invalid verdict and excluded (fail-closed).
VERDICTS = ("CORRECT", "INCORRECT", "UNCERTAIN")

# ``human_relation`` may only name a relation from the spec's controlled list.
RELATION_VOCAB = (
    "EXACT_MATCH", "EQUIVALENT_TO", "NARROWER_THAN", "BROADER_THAN",
    "RELATED_TO", "SOURCE_CONCEPT_OF", "NO_MATCH_FOUND", "AMBIGUOUS",
    "CONFLICTING_MAPPINGS", "INVALID_OR_OBSOLETE", "UNVERIFIED",
)

MACHINE_COLS = [
    "sample_id", "sample_role", "stratum", "sampling_weight",
    "mapping_id", "term_id", "term", "term_norm", "cdm_type",
    "source_service", "mapping_relation", "ontology_source",
    "concept_id", "concept_label", "candidate_rank",
    "is_canonical_candidate", "auto_accept_eligible",
    "staged_match_stage", "matched_label", "matched_synonym",
    "competing_candidates", "confidence",
]
HUMAN_COLS = [
    "human_verdict", "human_relation", "human_confidence",
    "human_notes", "reviewer", "reviewed_at",
]
SHEET_COLS = MACHINE_COLS + HUMAN_COLS


def stratum_of(source_service, mapping_relation) -> str:
    """The calibration stratum: one matching route crossed with one relation.

    Shared with ``calibrate_thresholds.py`` so a stratum recorded in the sheet is
    re-derivable from the row it describes.
    """
    return "%s|%s" % (source_service or "none", mapping_relation or "none")


def row_key(rec) -> str:
    """Stable per-row key. Falls back to term identity when there is no candidate."""
    mid = rec.get("mapping_id")
    if mid:
        return str(mid)
    return "nomatch|%s|%s" % (rec.get("term_id") or "", rec.get("term_norm") or "")


def sample_id(seed: str, key: str) -> str:
    """Deterministic sample id — never builtin ``hash()`` (salted per process)."""
    h = hashlib.sha1(("%s\x1f%s" % (seed, key)).encode("utf-8")).hexdigest()
    return SAMPLE_PREFIX + h[:16]


def _order_hash(seed: str, key: str) -> int:
    return int(hashlib.sha1(("%s\x1f%s" % (seed, key)).encode("utf-8")).hexdigest(), 16)


def classify_role(rec) -> str:
    """Which sampling role a projected mapping row belongs to."""
    if rec.get("mapping_relation") == "NO_MATCH_FOUND" or not rec.get("concept_id"):
        return "no_match_control"
    if rec.get("auto_accept_eligible"):
        return "primary"
    return "non_eligible_control"


def _cap_for(role, per_stratum, controls_per_stratum):
    return per_stratum if role == "primary" else controls_per_stratum


def _flatten(rec) -> dict:
    """Row -> review-sheet columns (machine half only)."""
    staged = rec.get("staged_match") or {}
    scores = rec.get("scores") or {}
    return {
        "mapping_id": rec.get("mapping_id"),
        "term_id": rec.get("term_id"),
        "term": rec.get("term"),
        "term_norm": rec.get("term_norm"),
        "cdm_type": rec.get("cdm_type"),
        "source_service": rec.get("source_service"),
        "mapping_relation": rec.get("mapping_relation"),
        "ontology_source": rec.get("ontology_source"),
        "concept_id": rec.get("concept_id"),
        "concept_label": rec.get("concept_label"),
        "candidate_rank": rec.get("candidate_rank"),
        "is_canonical_candidate": rec.get("is_canonical_candidate"),
        "auto_accept_eligible": rec.get("auto_accept_eligible"),
        "staged_match_stage": staged.get("stage"),
        "matched_label": staged.get("matched_label"),
        "matched_synonym": staged.get("matched_synonym"),
        "competing_candidates": rec.get("competing_candidates"),
        "confidence": scores.get("confidence"),
    }


def select(mappings_path: Path, seed: str, per_stratum: int, controls_per_stratum: int):
    """Stream the projection once; keep the ``k`` smallest-hash rows per stratum.

    Returns ``(rows, totals)`` where ``totals[(role, stratum)]`` is the full
    population size of that stratum, not just what was kept.
    """
    totals = defaultdict(int)
    heaps = defaultdict(list)   # (role, stratum) -> max-heap of (-h, i, row)
    counter = itertools.count()

    with mappings_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = classify_role(rec)
            strat = stratum_of(rec.get("source_service"), rec.get("mapping_relation"))
            totals[(role, strat)] += 1

            k = _cap_for(role, per_stratum, controls_per_stratum)
            if k <= 0:
                continue
            key = row_key(rec)
            item = (-_order_hash(seed, key), next(counter), key, _flatten(rec))
            bucket = heaps[(role, strat)]
            heapq.heappush(bucket, item)
            if len(bucket) > k:
                heapq.heappop(bucket)   # drops the largest hash (smallest -h)

    rows = []
    for (role, strat), bucket in sorted(heaps.items()):
        total = totals[(role, strat)]
        kept = len(bucket)
        weight = (total / kept) if kept else 1.0
        for neg_h, _i, key, flat in sorted(bucket):
            row = dict(flat)
            row["sample_id"] = sample_id(seed, key)
            row["sample_role"] = role
            row["stratum"] = strat
            row["sampling_weight"] = round(weight, 6)
            rows.append(row)
    rows.sort(key=lambda r: (r["sample_role"], r["stratum"], r["sample_id"]))
    return rows, totals


GUIDE = """# CV-link calibration review guide (spec 12)

This sheet is the **human-reviewed sample** the specification requires before any
mapping may be `AUTO_ACCEPTED`. Until it is filled in and passed to
`calibrate_thresholds.py`, every mapping stays `REVIEW_REQUIRED`.

## What you are judging

For each row, decide whether the candidate concept is an acceptable link for the
term **in a microbiome-literature context**. You are judging the *link*, not the
term.

Fill in exactly one `human_verdict` per row:

| value | meaning |
|---|---|
| `CORRECT` | the concept is a sound link for this term |
| `INCORRECT` | the concept is a wrong link for this term |
| `UNCERTAIN` | you cannot decide from what is shown (kept, but never counted as correct) |

Leave the cell **empty** if you have not reviewed the row. Empty is not a verdict.

Optional columns:

* `human_relation` — if the link is right but the relation is wrong, name the
  correct one from the controlled list (see `_calibration_sample_summary.json`).
* `human_confidence` — your own 0–1 certainty. This is *your* confidence, not the
  model's `confidence` column.
* `human_notes` — free text; use it for homonyms, strain/species mismatches, etc.
* `reviewer`, `reviewed_at` — who and when.

## What the columns mean

* `sample_role` — `primary` rows are the ones a threshold *could* auto-accept.
  `*_control` rows are sampled only to check the eligibility rule itself; they
  are reported separately and never counted toward an accept decision.
* `sampling_weight` — inverse sampling fraction. A stratum capped at N of M rows
  has weight `M/N`; uncapped strata have weight `1.0`. Calibration reweights by
  this so the estimate describes the whole population, not just the sample.
* `confidence` — the model/lookup score at projection time. It is **not**
  evidence of correctness and must not be treated as one.

## Rules

* Do not edit any column left of `human_verdict`. The machine half is the frame
  that ties your verdict back to a specific candidate.
* Do not reorder or delete rows — a missing row becomes an unlabeled row.
* A verdict of `CORRECT` on a homonym, or on a broader/narrower concept, should
  be `INCORRECT` unless the relation column is corrected to match.

## After review

```
python src/scripts/termpipeline/calibrate_thresholds.py \\
    --review_sheet outputs/results/terminology_v1/calibration_sample.csv \\
    --out_dir outputs/results/terminology_v1
```

The calibration is **fail-closed**: a stratum is only marked acceptable when the
Wilson lower bound of its precision clears the threshold at the required sample
size. Strata that do not clear it remain `REVIEW_REQUIRED` forever.
"""


def main():
    ap = argparse.ArgumentParser(
        description="Spec 12 — build a stratified human-review sample of CV mappings")
    ap.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    ap.add_argument("--out_dir", type=Path, required=True)
    ap.add_argument("--per_stratum", type=int, default=60,
                    help="primary rows kept per stratum (default 60)")
    ap.add_argument("--controls_per_stratum", type=int, default=10,
                    help="control rows kept per stratum (default 10; 0 disables)")
    ap.add_argument("--seed", default="termcal-v1")
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if not args.mappings.exists():
        raise SystemExit("mappings not found: %s" % args.mappings)

    rows, totals = select(args.mappings, args.seed, args.per_stratum,
                          args.controls_per_stratum)

    csv_path = out_dir / "calibration_sample.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)   # human columns absent -> written empty

    jsonl_path = out_dir / "calibration_sample.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    (out_dir / "calibration_review_guide.md").write_text(GUIDE, encoding="utf-8")

    by_stratum = []
    for (role, strat), total in sorted(totals.items()):
        kept = sum(1 for r in rows if r["sample_role"] == role and r["stratum"] == strat)
        if kept == 0:
            continue
        by_stratum.append({
            "sample_role": role,
            "stratum": strat,
            "stratum_population": total,
            "sampled": kept,
            "sampling_weight": round(total / kept, 6),
        })

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "inputs": {"mappings": str(args.mappings), "mappings_exists": True},
        "outputs": {
            "review_sheet": str(csv_path),
            "machine_frame": str(jsonl_path),
            "guide": str(out_dir / "calibration_review_guide.md"),
        },
        "sampling": {
            "seed": args.seed,
            "method": "deterministic sha1 ranking per stratum; no RNG, no builtin hash()",
            "per_stratum": args.per_stratum,
            "controls_per_stratum": args.controls_per_stratum,
        },
        "counts": {
            "mappings_rows_total": sum(totals.values()),
            "sampled_rows": len(rows),
            "primary_rows": sum(1 for r in rows if r["sample_role"] == "primary"),
            "control_rows": sum(1 for r in rows if r["sample_role"] != "primary"),
        },
        "by_stratum": by_stratum,
        "verdict_vocabulary": list(VERDICTS),
        "relation_vocabulary": list(RELATION_VOCAB),
        "human_verdict_state": "UNREVIEWED — every verdict cell ships empty",
        "caveats": [
            "This stage produces no label and no threshold: it only frames the review.",
            "confidence is a lookup score, not evidence of correctness.",
            "Sampling is for estimation and reweighted by sampling_weight; it is not a census.",
            "A stratum too small to sample is still reported with its true population size.",
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    with (out_dir / "_calibration_sample_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps({"counts": summary["counts"], "strata": len(by_stratum)}, indent=2))
    top = [s for s in by_stratum if s["sample_role"] == "primary"]
    print("primary strata: %d" % len(top))
    for s in top:
        print("  %-28s population=%-7d sampled=%-4d weight=%.2f"
              % (s["stratum"], s["stratum_population"], s["sampled"],
                 s["sampling_weight"]))
    print("wrote %s" % csv_path)


if __name__ == "__main__":
    main()
