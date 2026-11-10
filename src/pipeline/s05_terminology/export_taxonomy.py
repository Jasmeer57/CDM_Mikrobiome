#!/usr/bin/env python3
"""Stage 4 — semantic classification: taxonomy export.

Emits ``terminology_taxonomy.json``: the versioned two-level taxonomy rendered
as JSON, together with the counts and the term-level classification rollup when
a classifier output is supplied.

The taxonomy itself is **read, never re-invented**. The 16 upper categories (plus
the reserved, non-hierarchical ``UNCERTAIN``) already exist in
``term_taxonomy_v1.yaml``; this stage only exports them and joins any
classifier output onto ``canonical_terms.jsonl``.

The term-level classification is an **LLM-assisted draft**: rows keep
``category_verification_status`` from the classifier and are never promoted to
verified here.

Outputs (in ``--out_dir``)
--------------------------
    terminology_taxonomy.json
    taxonomy_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

TAXONOMY_YAML = (REPO_ROOT / "releases/data_catalogue" / "terminology" / "taxonomy"
                 / "term_taxonomy_v1.yaml")
TAXONOMY_CSV = (REPO_ROOT / "releases/data_catalogue" / "terminology" / "taxonomy"
                / "term_taxonomy_v1.csv")

# Reserved, non-hierarchical: a term that cannot be placed must be flagged
# rather than forced into an upper category.
RESERVED = {"UNCERTAIN", "REVIEW_REQUIRED"}


def load_taxonomy(path: Path):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("PyYAML is required to read the taxonomy YAML") from exc
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cats = raw.get("categories") or []
    upper = [c for c in cats
             if c.get("hierarchy_level") == "UPPER"
             and c.get("category_id") not in RESERVED]
    subs = [c for c in cats if c.get("hierarchy_level") == "SUB"]
    return raw, cats, upper, subs


def load_classifications(path: Path):
    """(term_norm, cdm_type) -> classification dict, from a classifier csv/jsonl."""
    out = {}
    if not path or not path.exists():
        return out
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tn = (r.get("normalized_term") or r.get("term_norm") or "").strip()
                out[(tn, (r.get("legacy_cdm_type") or r.get("cdm_type") or "").strip())] = r
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            tn = (r.get("normalized_term") or r.get("term_norm") or "").strip()
            out[(tn, (r.get("legacy_cdm_type") or r.get("cdm_type") or "").strip())] = r
    return out


def main():
    ap = argparse.ArgumentParser(description="Stage 4 — export the taxonomy")
    ap.add_argument("--taxonomy_yaml", type=Path, default=TAXONOMY_YAML)
    ap.add_argument("--taxonomy_csv", type=Path, default=TAXONOMY_CSV)
    ap.add_argument("--classifications", type=Path, default=None,
                    help="classifier output (csv or jsonl) to summarise")
    ap.add_argument("--canonical_terms", type=Path, default=None,
                    help="Stage 2 canonical_terms.jsonl to count coverage against")
    ap.add_argument("--out_dir", type=Path, required=True)
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if not args.taxonomy_yaml.exists():
        raise SystemExit(f"missing taxonomy: {args.taxonomy_yaml}")
    raw, cats, upper, subs = load_taxonomy(args.taxonomy_yaml)
    if not upper:
        raise SystemExit("taxonomy has no upper categories — refusing to export")

    subs_by_parent = defaultdict(list)
    for s in subs:
        subs_by_parent[s.get("parent_category_id")].append(s.get("category_id"))

    exported = {
        "taxonomy_id": raw.get("taxonomy_id"),
        "version": str(raw.get("version", "")),
        "created": raw.get("created"),
        "status": raw.get("status"),
        "description": raw.get("description"),
        "scope": raw.get("scope"),
        "owner": raw.get("owner"),
        "conventions": raw.get("conventions"),
        "decisions": raw.get("decisions"),
        "reserved_categories": sorted(
            c["category_id"] for c in cats if c.get("category_id") in RESERVED),
        "n_upper_categories": len(upper),
        "n_subcategories": len(subs),
        "upper_categories": [
            {
                "category_id": c.get("category_id"),
                "category_label": c.get("category_label"),
                "category_definition": c.get("category_definition"),
                "inclusion_criteria": c.get("inclusion_criteria"),
                "exclusion_criteria": c.get("exclusion_criteria"),
                "positive_examples": c.get("positive_examples"),
                "negative_examples": c.get("negative_examples"),
                "ontology_source": c.get("ontology_source"),
                "ontology_version": c.get("ontology_version"),
                "mapping_status": c.get("mapping_status"),
                "review_status": c.get("review_status"),
                "subcategory_ids": subs_by_parent.get(c.get("category_id"), []),
            }
            for c in upper
        ],
        "subcategories": [
            {
                "category_id": s.get("category_id"),
                "category_label": s.get("category_label"),
                "category_definition": s.get("category_definition"),
                "parent_category_id": s.get("parent_category_id"),
                "positive_examples": s.get("positive_examples"),
                "review_status": s.get("review_status"),
            }
            for s in subs
        ],
        "source_files": {
            "yaml": str(args.taxonomy_yaml),
            "csv": str(args.taxonomy_csv) if args.taxonomy_csv.exists() else None,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out_path = out_dir / "terminology_taxonomy.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(exported, f, indent=2, ensure_ascii=False)

    # ── classification rollup ────────────────────────────────────────────────
    cls = load_classifications(args.classifications)
    n_terms = None
    if args.canonical_terms and args.canonical_terms.exists():
        n_terms = 0
        by_type = Counter()
        with args.canonical_terms.open(encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                n_terms += 1
                by_type[t.get("cdm_type")] += 1

    upper_ids = {c.get("category_id") for c in upper}
    by_cat = Counter()
    by_sub = Counter()
    n_clean = 0
    n_invented = 0
    for r in cls.values():
        cid = (r.get("primary_category_id") or "").strip()
        by_cat[cid] += 1
        by_sub[(r.get("subcategory_id") or "").strip()] += 1
        if cid and cid not in upper_ids and cid not in RESERVED:
            n_invented += 1
        elif cid in upper_ids:
            n_clean += 1

    summary = {
        "generated_at": exported["generated_at"],
        "outputs": {"terminology_taxonomy": str(out_path)},
        "taxonomy": {
            "taxonomy_id": exported["taxonomy_id"],
            "version": exported["version"],
            "status": exported["status"],
            "n_upper_categories": exported["n_upper_categories"],
            "n_subcategories": exported["n_subcategories"],
            "reserved_categories": exported["reserved_categories"],
        },
        "classification": {
            "classified_terms_file": str(args.classifications) if args.classifications else None,
            "n_classified_terms": len(cls),
            "n_clean_upper_assignments": n_clean,
            "n_invented_categories_flagged": n_invented,
            "by_primary_category": by_cat.most_common(),
            "by_subcategory_top20": by_sub.most_common(20),
        },
        "coverage": {
            "canonical_terms": n_terms,
            "classified_terms": len(cls),
            "pct_classified": (round(100.0 * len(cls) / n_terms, 4)
                               if n_terms else None),
        },
        "caveats": [
            "The taxonomy is exported as-is; this stage does not invent categories.",
            "UNCERTAIN is reserved and non-hierarchical: uncategorisable terms are flagged, never forced.",
            "Classifier output is an LLM-assisted draft; rows keep their own verification status.",
            "A classification pass over the full term table has not been run for every term.",
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    with (out_dir / "taxonomy_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps(summary["taxonomy"], indent=2))
    print(json.dumps(summary["classification"], indent=2)[:600])
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
