#!/usr/bin/env python
"""Measure the three expensive harmonization questions about the variant runs.

The cheap per-variant survival numbers are computed directly by
``releases/frozen_output/_build/build_frozen_output.py`` from the CSVs it ships.  The three
questions below need a full pass over ~2M rows (and, for one of them, a second
merge), so they are measured here once and written to
``outputs/results/ner_harmonization_variants/harmonization_probe.json``, which the builder
reads when present.

Q1 registration counterfactual
    ``dedup.MODEL_PRIORITY`` decides which model's label becomes an entity's
    ``cdm_type``.  If the fourteen variant model strings were *not* registered,
    they would fall to the default priority 9 and lose every type conflict — not
    even beating ``en_core_sci_lg``'s generic ``ENTITY`` (tier 4).  This merges the
    variant rows twice (registered vs unregistered) and counts how many entities
    end up with a different ``cdm_type``.

Q2 mapping coverage
    The frozen 334,231-row mapping table keys on ``term_norm``.  This asks what
    fraction of the distinct variant terms that table could even address, per
    variant, so the bundle never implies the new runs are ontology-mapped.

Q3 normalizer gap
    ``cdm_pipeline.utils.norm`` (lowercase + whitespace collapse) is the shipped
    key.  The notebook's ``norm_surface`` adds NFKC + ligature expansion + edge
    punctuation stripping.  This counts how many additional terms would merge.
    Reported as an option, never applied.

Usage:
    PYTHONPATH=src python src/scripts/gen_harmonization_probe.py [--output PATH]

Exit codes:
    0  probe written
    1  a declared variant CSV is missing (nothing written)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import unicodedata

REPO = str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents if (p / ".cdm_root").is_file()))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from cdm_pipeline import dedup as dd  # noqa: E402
from cdm_pipeline.utils import norm  # noqa: E402

_WS = re.compile(r"\s+")

DEFAULT_OUT = os.path.join(REPO, "outputs/results", "ner_harmonization_variants",
                           "harmonization_probe.json")
MAPPINGS = os.path.join(REPO, "outputs/results", "terminology_v1",
                        "term_ontology_mappings.jsonl")

# Ligature fold and edge punctuation transcribed verbatim from
# src/notebooks/pipeline_standalone.ipynb Cell 8b2 (LIG_FOLD / norm_surface).  Do not
# widen the punctuation set: an earlier hand-written version also stripped
# whitespace, dashes, slashes, `#`, `+`, `*` and brackets, which is NOT what the
# notebook does and changed the merge count.
LIG_FOLD = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
            "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"}


def norm_surface(s):
    """The notebook's ``norm_surface``: NFKC, ligatures, edge punctuation, lower."""
    t = unicodedata.normalize("NFKC", s or "")
    for k, v in LIG_FOLD.items():
        t = t.replace(k, v)
    t = _WS.sub(" ", t).strip().strip(".,;:()[]{}\"'").strip()
    return t.lower()


def load_variant_rows():
    """Return ``(rows, missing)`` for every row that passes the label filter.

    Only label-valid rows matter here: an out-of-vocabulary row never becomes an
    entity, so it cannot influence a type resolution or a term count.  ``missing``
    is the first absent variant CSV, or ``None``.
    """
    rows = []
    for rel_dir, filename in dd.VARIANT_CSV_FILES:
        path = dd._variant_dir_path(rel_dir, filename)
        if not path.exists():
            return rows, f"{rel_dir}/{filename}"
        for r in dd.load_csv_safe(path):
            reason, parsed = dd.classify_row(r)
            if reason is None:
                rows.append(((r.get("model") or "").strip(), r, parsed))
    return rows, None


def q1_registration(rows, variant_models):
    """Merge twice: with the real priorities, and with every variant demoted."""

    def merge(demote_variants):
        ents = {}
        for model, r, (k, label) in rows:
            if demote_variants and model in variant_models:
                prio = 9
            else:
                prio = dd.MODEL_PRIORITY.get(model, 9)
            if k not in ents:
                ents[k] = [label, prio]
                continue
            cur_label, cur_prio = ents[k]
            if prio < cur_prio:
                ents[k] = [label, prio]
            elif prio == cur_prio and label != "ENTITY" and cur_label == "ENTITY":
                ents[k] = [label, prio]
        return ents

    real = merge(False)
    demo = merge(True)
    changed = [(k, real[k][0], demo[k][0]) for k in real if real[k][0] != demo[k][0]]
    moves = collections.Counter((a, b) for _, a, b in changed)
    return {
        "entities": len(real),
        "entities_registered": len(real),
        "changed_if_unregistered": len(changed),
        "changed_pct": round(100.0 * len(changed) / len(real), 2) if real else 0.0,
        "top_transitions_if_unregistered": [
            {"from": a, "to": b, "entities": n} for (a, b), n in moves.most_common(12)
        ],
    }


def q2_mapping_coverage(rows):
    """Fraction of each variant's distinct terms the frozen mapping table can key."""
    vocab = set()
    if os.path.exists(MAPPINGS):
        with open(MAPPINGS, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                key = rec.get("term_norm")
                if key:
                    vocab.add(key)
    per = collections.defaultdict(set)
    for model, r, (k, _label) in rows:
        per[dd.SOURCE_NAME.get(model, model)].add(k)
    out = {"mapping_terms": len(vocab), "per_source": []}
    for source in sorted(per):
        terms = per[source]
        hit = len(terms & vocab)
        out["per_source"].append({
            "source": source,
            "distinct_terms": len(terms),
            "mappable": hit,
            "mappable_pct": round(100.0 * hit / len(terms), 2) if terms else 0.0,
        })
    return out


def q3_normalizer(rows):
    """How many extra merges the stricter surface key would buy.

    Reported twice on purpose.  The *all-rows* figure is the raw surface-vocabulary
    collapse, most of which never enters the registry because those rows are junk.
    The *label-valid* figure is the one that matters: it is the actual number of
    additional merges a registry built with the stricter key would contain.  Quoting
    the all-rows number as the registry effect overstates it by roughly 40x.
    """
    ship, surf = set(), set()
    alt_empty = 0
    for rel_dir, filename in dd.VARIANT_CSV_FILES:
        path = dd._variant_dir_path(rel_dir, filename)
        if not path.exists():
            continue
        for r in dd.load_csv_safe(path):
            term = (r.get("term") or "").strip()
            if not term:
                continue
            ship.add(norm(term))
            s = norm_surface(term)
            surf.add(s)
            if not s:
                alt_empty += 1

    keep_ship = {k for _m, _r, (k, _l) in rows}
    keep_surf = {norm_surface((r.get("term") or "").strip()) for _m, r, _p in rows}
    return {
        "shipped_key": "cdm_pipeline.utils.norm (lowercase + whitespace collapse)",
        "alternative_key": "notebook norm_surface (NFKC + ligature + edge-punct strip)",
        "distinct_shipped": len(keep_ship),
        "distinct_alternative": len(keep_surf),
        "extra_merges": len(keep_ship) - len(keep_surf),
        "extra_merges_pct": round(100.0 * (len(keep_ship) - len(keep_surf))
                                  / len(keep_ship), 2) if keep_ship else 0.0,
        "distinct_shipped_all_rows": len(ship),
        "distinct_alternative_all_rows": len(surf),
        "extra_merges_all_rows": len(ship) - len(surf),
        "extra_merges_all_rows_pct": round(100.0 * (len(ship) - len(surf))
                                           / len(ship), 2) if ship else 0.0,
        "alternative_key_empty": alt_empty,
        "applied": False,
    }


def q4_label_vocabulary(rows):
    """How much of the out-of-vocabulary vocabulary is lost permanently?

    A term carried only under a non-CDM label (``DNA``, ``CELLULAR_COMPONENT``, …)
    is dropped by the filter.  That costs *mentions* unconditionally, but it only
    costs a *term* if no other run ever witnesses it under a CDM label.  This
    separates the two, because "we drop 19,272 SciBERT rows" and "we lose 2,383
    terms" are very different claims.
    """
    all_valid = {k for _m, _r, (k, _l) in rows}
    per_label = collections.defaultdict(set)
    dropped = set()
    for rel_dir, filename in dd.VARIANT_CSV_FILES:
        path = dd._variant_dir_path(rel_dir, filename)
        if not path.exists():
            continue
        for r in dd.load_csv_safe(path):
            reason, _ = dd.classify_row(r)
            if reason != "label_not_in_vocabulary":
                continue
            k = norm((r.get("term") or "").strip())
            if not k:
                continue
            label = dd.fix_label(r.get("labels") or r.get("label") or "")
            dropped.add(k)
            per_label[label].add(k)
    both = dropped & all_valid
    detail = []
    for label in sorted(per_label, key=lambda x: -len(per_label[x])):
        terms = per_label[label]
        hit = len(terms & all_valid)
        detail.append({
            "label": label,
            "distinct_terms": len(terms),
            "also_under_cdm_label": hit,
            "pct": round(100.0 * hit / len(terms), 1) if terms else 0.0,
        })
    return {
        "distinct_dropped_terms": len(dropped),
        "also_witnessed_under_cdm_label": len(both),
        "pct_recoverable": round(100.0 * len(both) / len(dropped), 1) if dropped else 0.0,
        "orphan_terms": len(dropped - both),
        "pct_orphan": round(100.0 * len(dropped - both) / len(dropped), 1) if dropped else 0.0,
        "per_label": detail,
        "note": "counts are per distinct normalized term, not per row; a term can "
                "appear under more than one raw label",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", default=DEFAULT_OUT)
    args = ap.parse_args()

    # Materialise once: the three questions sweep the same ~1.8M rows.
    rows, missing = load_variant_rows()
    if missing:
        print(f"MISSING variant CSV: {missing} — nothing written", file=sys.stderr)
        return 1
    if not rows:
        print("no label-valid variant rows — nothing written", file=sys.stderr)
        return 1

    variant_models = {m for m, _r, _p in rows}
    print(f"label-valid variant rows: {len(rows):,} over {len(variant_models)} models")

    probe = {
        "variant_models": sorted(variant_models),
        "rows_label_valid": len(rows),
        "q1_registration": q1_registration(rows, variant_models),
        "q2_mapping_coverage": q2_mapping_coverage(rows),
        "q3_normalizer": q3_normalizer(rows),
        "q4_label_vocabulary": q4_label_vocabulary(rows),
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(probe, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    q1 = probe["q1_registration"]
    print(f"Q1 unregistered variants would change {q1['changed_if_unregistered']:,} "
          f"/{q1['entities']:,} entity types ({q1['changed_pct']}%)")
    q3 = probe["q3_normalizer"]
    print(f"Q3 norm_surface would merge {q3['extra_merges']:,} more "
          f"({q3['extra_merges_pct']}%)")
    for r in probe["q2_mapping_coverage"]["per_source"]:
        print(f"   mapping {r['source'][:26]:26s} {r['mappable']:6,d}/"
              f"{r['distinct_terms']:7,d} ({r['mappable_pct']:5.2f}%)")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
