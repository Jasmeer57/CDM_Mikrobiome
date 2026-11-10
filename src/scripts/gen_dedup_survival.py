#!/usr/bin/env python
"""Measure how much of each variant run survives the Stage-2 dedup filter.

The filter itself lives in :func:`cdm_pipeline.dedup.classify_row`, so this report
cannot drift from the thing it measures.  For each of the fourteen variant CSVs
this writes:

* ``dedup_survival_by_variant.csv`` — per-variant rows / kept / drop reasons
* ``dedup_survival_summary.json``  — the same numbers plus combined totals

Two numbers need care:

``kept``
    Rows whose label is already a CDM type (or a ``LABEL_FIX`` key).  These are
    the rows that become candidate registry entities.

``kept_if_LABEL_TO_CDM``
    A *counterfactual*, not a plan: the same filter with ``common.LABEL_TO_CDM``
    applied as a second-chance fold.  It answers "how much is the unwired
    ``LABEL_TO_CDM`` worth?" — it is deliberately NOT applied anywhere in
    production, so this column must never be read as the shipped behaviour.

Rows are counted, not entities; survival is per-mention.  A row that survives
here can still lose to another row's type in the merged registry.

Usage:
    PYTHONPATH=src python src/scripts/gen_dedup_survival.py [--output-dir DIR]

Exit codes:
    0  artifacts written
    1  a declared variant CSV is missing (nothing written)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter

REPO = str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents if (p / ".cdm_root").is_file()))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from cdm_pipeline import dedup as dd  # noqa: E402
from cdm_pipeline.utils import load_csv_safe  # noqa: E402

import common  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "outputs/results", "ner_harmonization_variants")

CSV_FIELDS = [
    "csv", "models", "rows", "kept", "kept_pct",
    "dropped_junk", "dropped_over_len", "dropped_label",
    "kept_if_LABEL_TO_CDM", "kept_pct_if_LABEL_TO_CDM", "dropped_labels",
]


def counterfactual_keep(row, reason):
    """Would ``common.LABEL_TO_CDM`` rescue this row from the label filter?

    Only the label gate is counterfactual; the junk/length/norm gates are not
    negotiable.  ``reason`` comes from the caller's ``classify_row`` so the row is
    classified once, not twice.
    """
    if reason != "label_not_in_vocabulary":
        return False
    folded = dd.fix_label(row.get("labels") or row.get("label") or "")
    return common.LABEL_TO_CDM.get(folded) in dd.VALID_TYPES


def measure(rel_dir, filename):
    path = dd._variant_dir_path(rel_dir, filename)
    if not path.exists():
        return None
    rows = load_csv_safe(path)
    drops = Counter()
    labels = Counter()
    models = Counter()
    rescued = 0
    for r in rows:
        models[(r.get("model") or "").strip()] += 1
        reason, _ = dd.classify_row(r)
        if reason is None:
            continue
        drops[reason] += 1
        if reason == "label_not_in_vocabulary":
            labels[(r.get("labels") or r.get("label") or "").strip()] += 1
        # Every dropped row gets the counterfactual check, not just the non-label
        # ones: a label-dropped row is exactly the case LABEL_TO_CDM could rescue,
        # so gating this behind `elif` made the column silently equal `kept`.
        if counterfactual_keep(r, reason):
            rescued += 1
    kept = len(rows) - sum(drops.values())
    return {
        "csv": f"{rel_dir}/{filename}",
        "models": "|".join(sorted(m for m in models if m)),
        "rows": len(rows),
        "kept": kept,
        "kept_pct": round(100.0 * kept / len(rows), 2) if rows else 0.0,
        "dropped_junk": drops["junk_or_short"],
        "dropped_over_len": drops["over_max_length"],
        "dropped_label": drops["label_not_in_vocabulary"],
        "kept_if_LABEL_TO_CDM": kept + rescued,
        "kept_pct_if_LABEL_TO_CDM": round(100.0 * (kept + rescued) / len(rows), 2) if rows else 0.0,
        "dropped_labels": "|".join(f"{k}:{v}" for k, v in labels.most_common()),
        "empty_norm": drops["empty_norm"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output-dir", default=DEFAULT_OUT)
    args = ap.parse_args()

    per_variant, missing = [], []
    for rel_dir, filename in dd.VARIANT_CSV_FILES:
        m = measure(rel_dir, filename)
        if m is None:
            missing.append(f"{rel_dir}/{filename}")
        else:
            per_variant.append(m)

    if missing:
        print("MISSING variant CSVs — nothing written:", file=sys.stderr)
        for p in missing:
            print("  - " + p, file=sys.stderr)
        return 1

    os.makedirs(args.output_dir, exist_ok=True)

    out_csv = os.path.join(args.output_dir, "dedup_survival_by_variant.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(per_variant)

    total_rows = sum(m["rows"] for m in per_variant)
    total_kept = sum(m["kept"] for m in per_variant)
    summary = {
        "filter": {
            "max_term_length": dd.MAX_TERM_LENGTH,
            "valid_types": sorted(dd.VALID_TYPES),
            "label_fix": dd.LABEL_FIX,
            "normalizer": "cdm_pipeline.utils.norm (lowercase + whitespace collapse)",
            "counterfactual": "kept_if_LABEL_TO_CDM applies common.LABEL_TO_CDM; NOT wired in production",
        },
        "total": {
            "rows": total_rows,
            "kept": total_kept,
            "kept_pct": round(100.0 * total_kept / total_rows, 2) if total_rows else 0.0,
            "kept_if_LABEL_TO_CDM": sum(m["kept_if_LABEL_TO_CDM"] for m in per_variant),
        },
        "per_variant": per_variant,
    }
    out_json = os.path.join(args.output_dir, "dedup_survival_summary.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"rows {total_rows:,} -> kept {total_kept:,} ({summary['total']['kept_pct']}%)")
    print(f"wrote {out_csv}")
    print(f"wrote {out_json}")
    for m in per_variant:
        print(f"  {m['models'][:28]:28s} {m['rows']:8,d} -> {m['kept']:8,d} "
              f"({m['kept_pct']:6.2f}%)  junk {m['dropped_junk']:7,d}  "
              f"label {m['dropped_label']:6,d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
