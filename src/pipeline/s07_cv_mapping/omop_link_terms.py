#!/usr/bin/env python
"""Offline OMOP linking over the NER term table — CPU only, separate view.

Links typed NER terms to OMOP concepts using the local Athena index built by
``build_omop_index.py``. No network calls, no API key, no GPU, no LLM.

Per the agreed scope this is a **separate view**: results are written to their
own artifact and are *not* merged into the canonical mapping produced by
``cv_link_terms.py``, and OMOP is *not* added to ``config.VOCAB_PRIORITY``. That
keeps OMOP from silently displacing existing UMLS / MESH / NCBITaxon canonicals
and keeps the two stages independently evaluable.

Input is the same combined table the CV-linking stage uses, so the two artifacts
join one-to-one on ``(term_norm, cdm_type)``:

    releases/data_catalogue/terminology/terminology_dedup.csv

Generic ``ENTITY`` rows carry no CDM type and are skipped-on-purpose.

Outputs (under ``--out_dir``, default ``outputs/results/omop_linking``):

    omop_links.csv        one row per (pair, OMOP concept) hit
    omop_terms.jsonl      one JSON record per input pair (hit or miss)
    omop_summary.json     counts, coverage, per-domain / per-vocab breakdown

Usage:
    python src/scripts/vllm_termpop/omop_link_terms.py --out_dir outputs/results/omop_linking
    python src/scripts/vllm_termpop/omop_link_terms.py --limit 100   # smoke test
"""
import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.s07_cv_mapping.omop_local import DEFAULT_INDEX, available, lookup, stats  # noqa: E402

DEDUP_CSV = REPO_ROOT / "releases/data_catalogue" / "terminology" / "terminology_dedup.csv"


def norm_key(term_norm, cdm_type):
    return ((term_norm or "").strip().lower(), (cdm_type or "").strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dedup_csv", default=str(DEDUP_CSV))
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    ap.add_argument("--out_dir", default=str(REPO_ROOT / "outputs/results" / "omop_linking"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max_per_term", type=int, default=5)
    ap.add_argument("--allow_non_standard", action="store_true", default=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    print("=" * 72)
    print("OMOP linking (CPU, offline, separate view)")
    print(f"  dedup_csv : {args.dedup_csv}")
    print(f"  index     : {args.index}")
    print(f"  out_dir   : {out_dir}")
    print("=" * 72)

    if not available(args.index):
        print(f"ERROR: OMOP index not found: {args.index}\n"
              f"       build it first with src/scripts/vllm_termpop/build_omop_index.py",
              file=sys.stderr)
        return 2
    print("index stats:", json.dumps(stats(args.index)))

    # ── build the typed work set ──
    with open(args.dedup_csv, newline="", encoding="utf-8") as f:
        dedup_rows = list(csv.DictReader(f))
    typed, generic = [], set()
    for r in dedup_rows:
        k = norm_key(r.get("term_norm"), r.get("cdm_type"))
        if not k[0] or not k[1]:
            continue
        if k[1] == "ENTITY":
            generic.add(k)
        else:
            typed.append(k)
    # stable dedupe, preserve order
    seen, pairs = set(), []
    for k in typed:
        if k not in seen:
            seen.add(k)
            pairs.append(k)
    if args.limit:
        pairs = pairs[:args.limit]
    print(f"\n[1/3] typed pairs: {len(pairs)} "
          f"(+{len(generic)} generic ENTITY skipped)")

    # ── link ──
    print("[2/3] linking")
    t0 = time.time()
    records, n_links = [], 0
    dom_counts, vocab_counts = Counter(), Counter()
    for i, (term, cdm_type) in enumerate(pairs, 1):
        hits = lookup(term, cdm_type, index_path=args.index,
                      limit=args.max_per_term,
                      include_non_standard=args.allow_non_standard)
        for h in hits:
            dom_counts[h.get("omop_domain") or "?"] += 1
            vocab_counts[h.get("omop_vocab") or "?"] += 1
        n_links += len(hits)
        records.append({"term_norm": term, "cdm_type": cdm_type,
                        "origin": "omop_local",
                        "n_hits": len(hits), "hits": hits})
        if i % 5000 == 0 or i == len(pairs):
            el = time.time() - t0
            print(f"    {i}/{len(pairs)} pairs, {n_links:,} links "
                  f"({i/el:.0f}/s, {el:.0f}s)", flush=True)
    print(f"    done: {n_links:,} links in {time.time()-t0:.1f}s")

    # ── write ──
    print("[3/3] writing outputs")
    links_csv = out_dir / "omop_links.csv"
    FIELDS = ["term_norm", "cdm_type", "concept_id", "label", "ontology_name",
              "omop_domain", "omop_concept_class", "omop_standard",
              "omop_matched_via", "omop_standard_concept_id",
              "omop_standard_concept_name"]
    with open(links_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            for h in rec["hits"]:
                w.writerow(dict(h, term_norm=rec["term_norm"],
                                cdm_type=rec["cdm_type"]))

    terms_jsonl = out_dir / "omop_terms.jsonl"
    with open(terms_jsonl, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    n_mapped = sum(1 for r in records if r["n_hits"])
    with_std = sum(1 for r in records
                   if any(h.get("omop_standard_concept_id") for h in r["hits"]))
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stage": "omop_linking",
        "view": "separate — NOT merged into cv_link canonicals, "
                "OMOP NOT added to VOCAB_PRIORITY",
        "inputs": {"dedup_csv": str(args.dedup_csv),
                   "dedup_csv_rows": len(dedup_rows),
                   "index": str(args.index)},
        "index_stats": stats(args.index),
        "work_set": {"typed_pairs": len(pairs),
                     "generic_entity_skipped": len(generic)},
        "coverage": {
            "pairs_with_omop_hit": n_mapped,
            "pct_mapped": round(100.0 * n_mapped / len(pairs), 3) if pairs else 0.0,
            "pairs_with_standard_concept": with_std,
            "pct_with_standard_concept": (round(100.0 * with_std / len(pairs), 3)
                                          if pairs else 0.0),
            "total_links": n_links,
        },
        "by_omop_domain": dom_counts.most_common(40),
        "by_omop_vocabulary": vocab_counts.most_common(40),
        "mapped_by_cdm_type": Counter(
            r["cdm_type"] for r in records if r["n_hits"]).most_common(),
        "misses_by_cdm_type": Counter(
            r["cdm_type"] for r in records if not r["n_hits"]).most_common(),
        "top_mapped_terms": [
            {"term_norm": r["term_norm"], "cdm_type": r["cdm_type"],
             "concept_id": r["hits"][0]["concept_id"],
             "label": r["hits"][0]["label"],
             "domain": r["hits"][0].get("omop_domain")}
            for r in records if r["n_hits"]][:30],
        "caveats": [
            "Exact normalized string match only — no fuzzy or embedding match. "
            "A miss means 'no exact OMOP name/synonym', not 'not in OMOP'.",
            "OMOP is reported as a separate view and does not change any "
            "canonical mapping produced by the CV-linking stage.",
            "Administrative/pricing vocabularies (NDC, SPL, EDI, CPT4, drug "
            "code bundles) are excluded as mapping targets.",
        ],
        "elapsed_seconds": round(time.time() - t_start, 1),
    }
    with open(out_dir / "omop_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"  {links_csv}  ({n_links:,} links)")
    print(f"  {terms_jsonl}  ({len(records):,} records)")
    print(f"  {out_dir/'omop_summary.json'}")
    print(json.dumps(summary["coverage"], indent=2))
    print(f"\nDone in {summary['elapsed_seconds']}s -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
