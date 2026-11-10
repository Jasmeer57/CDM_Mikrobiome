#!/usr/bin/env python
"""Controlled-vocabulary (CV) linking over NER term tables — CPU, no GPU, no LLM.

Links extracted terms to controlled vocabularies via the existing mappers in
``cdm_pipeline.mapping.mappers`` (OLS, UMLS, BioPortal, NCBI Taxonomy) and ranks
candidates with ``cdm_pipeline.mapping.confidence.resolve_canonical``.

Scope (per the agreed work set):

* the CPU NLP ensemble (``paper/_multi_ner_runs/mapped_entities.json``,
  already mapped) is **reused, not re-mapped**;
* the Qwen runs and any other NER output present in the combined terminology
  table are mapped **here** — that is the actual new work.

The combined terminology table (``releases/data_catalogue/terminology/terminology_dedup.csv``)
is a superset: it carries the CPU rows *and* the Qwen rows. So the work set is
exactly

    typed (term_norm, cdm_type) pairs in terminology_dedup.csv
        MINUS the pairs already resolved in the CPU mapping

Generic ``ENTITY`` rows are recorded as skipped-on-purpose (they carry no CDM
type to link against) and never sent to an API.

Outputs (all under ``--out_dir``, default ``outputs/results/cv_linking``):

    cv_mapped_entities.jsonl   one JSON record per typed pair (reuse + new)
    cv_links.csv               flat, one row per (pair, candidate) link
    cv_summary.json            counts, coverage, per-source + per-type breakdown
    cv_checkpoint.json         resume state (written every --checkpoint_every)

Every rerun resumes from the checkpoint; delete it to start over.

Usage:
    python src/scripts/vllm_termpop/cv_link_terms.py --out_dir outputs/results/cv_linking
    python src/scripts/vllm_termpop/cv_link_terms.py --limit 200       # smoke test
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
import warnings
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))

from cdm_pipeline.mapping.mappers import (  # noqa: E402
    map_ols, map_umls, map_bioportal, map_ncbi_taxon,
)
from cdm_pipeline.mapping.confidence import resolve_canonical  # noqa: E402

DEDUP_CSV = REPO_ROOT / "releases/data_catalogue" / "terminology" / "terminology_dedup.csv"
REUSE_JSON = REPO_ROOT / "paper" / "_multi_ner_runs" / "mapped_entities.json"


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def norm_key(term_norm, cdm_type):
    """Canonical work-set key. term_norm is already lowercased/normalized upstream."""
    return ((term_norm or "").strip().lower(), (cdm_type or "").strip())


def map_one(pair):
    """Map one (term_norm, cdm_type) pair across all sources -> record dict."""
    term, cdm_type = pair
    candidates = []
    candidates.extend(map_ols(term, cdm_type))
    candidates.extend(map_umls(term, cdm_type))
    candidates.extend(map_bioportal(term, cdm_type))
    candidates.extend(map_ncbi_taxon(term, cdm_type))
    canonical, others = resolve_canonical(candidates, cdm_type)
    return {
        "term": term,
        "term_norm": term,
        "cdm_type": cdm_type,
        "origin": "new",
        "canonical": canonical,
        "all_mappings": candidates,
        "has_mapping": canonical is not None,
    }


def load_reuse(path):
    """Load the pre-existing CPU mapping as {(norm, cdm_type): record}."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    reuse = {}
    for r in rows:
        c = r.get("canonical")
        if c and c.get("label"):
            c = dict(c, label=c["label"])
        reuse[norm_key(r.get("norm"), r.get("cdm_type"))] = {
            "term": r.get("term"),
            "term_norm": r.get("norm"),
            "cdm_type": r.get("cdm_type"),
            "origin": "reuse_cpu_ensemble",
            "canonical": c,
            "all_mappings": r.get("all_mappings") or [],
            "has_mapping": bool(c),
        }
    return reuse


def load_checkpoint(path):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "results": []}


def save_checkpoint(path, cp):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dedup_csv", default=str(DEDUP_CSV))
    ap.add_argument("--reuse_json", default=str(REUSE_JSON))
    ap.add_argument("--out_dir", default=str(REPO_ROOT / "outputs/results" / "cv_linking"))
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--checkpoint_every", type=int, default=200)
    ap.add_argument("--limit", type=int, default=None,
                    help="Map at most N new pairs (smoke test)")
    ap.add_argument("--include_entity", action="store_true",
                    help="Also emit generic ENTITY rows (never sent to an API)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "cv_checkpoint.json"

    t_start = time.time()
    print("=" * 72)
    print("CV linking — CPU, no GPU")
    print(f"  dedup csv : {args.dedup_csv}")
    print(f"  reuse json: {args.reuse_json}")
    print(f"  out_dir   : {out_dir}")
    print(f"  workers   : {args.workers}")
    print("=" * 72)

    for k in ("UMLS_API_KEY", "BIOPORTAL_API_KEY", "ENTREZ_API_KEY"):
        print(f"  {k}: {'set' if os.environ.get(k) else 'NOT SET'}")

    # ── 1. read the combined terminology table ──
    with open(args.dedup_csv, newline="", encoding="utf-8") as f:
        dedup_rows = list(csv.DictReader(f))
    print(f"\n[1/5] terminology table: {len(dedup_rows)} rows")

    typed, generic = [], []
    seen_typed, seen_generic = set(), set()
    for r in dedup_rows:
        key = norm_key(r.get("term_norm"), r.get("cdm_type"))
        if not key[0] or not key[1]:
            continue
        if key[1] == "ENTITY":
            if key not in seen_generic:
                seen_generic.add(key)
                generic.append(key)
        elif key not in seen_typed:
            seen_typed.add(key)
            typed.append(key)
    print(f"      typed (norm, cdm_type) pairs : {len(typed)}")
    print(f"      generic ENTITY pairs         : {len(generic)}")

    # ── 2. reuse the existing CPU mapping ──
    reuse = load_reuse(Path(args.reuse_json))
    print(f"\n[2/5] reuse: {len(reuse)} pairs in {Path(args.reuse_json).name}")

    reused_hits = [k for k in typed if k in reuse]
    todo = [k for k in typed if k not in reuse]
    print(f"      already mapped (reused)      : {len(reused_hits)}")
    print(f"      new work (mapped here)       : {len(todo)}")
    print("      new work by cdm_type:",
          Counter(t for _, t in todo).most_common())

    # ── 3. map the gap with checkpoint/resume ──
    cp = load_checkpoint(ckpt_path)
    done = set(cp["done"].keys())
    results = cp["results"]
    pending = [k for k in todo if f"{k[0]}\x1f{k[1]}" not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f"\n[3/5] checkpoint: {len(done)} already done, {len(pending)} to map now")

    t0 = time.time()
    n_done = 0
    if pending:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(map_one, k): k for k in pending}
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    rec = fut.result()
                except Exception as ex:
                    rec = {"term": k[0], "term_norm": k[0], "cdm_type": k[1],
                           "origin": "new", "canonical": None, "all_mappings": [],
                           "has_mapping": False, "error": repr(ex)}
                results.append(rec)
                cp["done"][f"{k[0]}\x1f{k[1]}"] = bool(rec.get("has_mapping"))
                n_done += 1
                if n_done % args.checkpoint_every == 0:
                    save_checkpoint(ckpt_path, cp)
                    el = time.time() - t0
                    rate = n_done / el if el else 0
                    eta = (len(pending) - n_done) / rate if rate else 0
                    print(f"      {n_done}/{len(pending)} mapped "
                          f"({rate:.1f}/s, ETA {eta/60:.1f} min)", flush=True)
        save_checkpoint(ckpt_path, cp)

    new_by_key = {}
    for r in results:
        new_by_key[norm_key(r.get("term_norm"), r.get("cdm_type"))] = r

    # ── 4. write unified outputs ──
    print(f"\n[4/5] writing outputs")
    all_records = []
    for k in typed:
        rec = reuse.get(k) or new_by_key.get(k)
        if rec is None:
            continue
        all_records.append(rec)

    jsonl_path = out_dir / "cv_mapped_entities.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    links_path = out_dir / "cv_links.csv"
    FIELDS = ["term", "term_norm", "cdm_type", "origin", "is_canonical",
              "source", "ontology_name", "concept_id", "label", "confidence"]
    n_links = 0
    with open(links_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for rec in all_records:
            canon = rec.get("canonical") or {}
            for c in rec.get("all_mappings") or []:
                w.writerow({
                    "term": rec.get("term"), "term_norm": rec.get("term_norm"),
                    "cdm_type": rec.get("cdm_type"), "origin": rec.get("origin"),
                    "is_canonical": (c.get("concept_id") == canon.get("concept_id")
                                     and c.get("ontology_name") == canon.get("ontology_name")),
                    "source": c.get("source"), "ontology_name": c.get("ontology_name"),
                    "concept_id": c.get("concept_id"), "label": c.get("label"),
                    "confidence": c.get("confidence"),
                })
                n_links += 1
            if not (rec.get("all_mappings")):
                w.writerow({"term": rec.get("term"), "term_norm": rec.get("term_norm"),
                            "cdm_type": rec.get("cdm_type"), "origin": rec.get("origin"),
                            "is_canonical": False})
    print(f"      {jsonl_path}  ({len(all_records)} records)")
    print(f"      {links_path}  ({n_links} links)")

    # ── 5. summary ──
    mapped = [r for r in all_records if r.get("has_mapping")]
    by_source = Counter()
    by_canon_vocab = Counter()
    for r in mapped:
        c = r["canonical"]
        by_canon_vocab[c.get("ontology_name") or "?"] += 1
    for r in all_records:
        for c in r.get("all_mappings") or []:
            by_source[c.get("source") or "?"] += 1

    new_records = [r for r in all_records if r.get("origin") == "new"]
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "inputs": {
            "dedup_csv": str(args.dedup_csv),
            "dedup_csv_sha256": sha256_of(args.dedup_csv),
            "dedup_csv_rows": len(dedup_rows),
            "reuse_json": str(args.reuse_json),
            "reuse_json_sha256": sha256_of(Path(args.reuse_json)) if Path(args.reuse_json).exists() else None,
        },
        "work_set": {
            "typed_pairs_total": len(typed),
            "reused_from_cpu_ensemble": len(reused_hits),
            "newly_mapped": len(new_records),
            "generic_entity_pairs_skipped": len(generic),
        },
        "coverage": {
            "typed_pairs_with_mapping": len(mapped),
            "typed_pairs_without_mapping": len(all_records) - len(mapped),
            "pct_mapped": round(100.0 * len(mapped) / len(all_records), 3) if all_records else 0.0,
            "new_pairs_with_mapping": sum(1 for r in new_records if r.get("has_mapping")),
            "new_pct_mapped": (round(100.0 * sum(1 for r in new_records if r.get("has_mapping"))
                                     / len(new_records), 3) if new_records else 0.0),
        },
        "canonical_by_vocabulary": by_canon_vocab.most_common(60),
        "links_by_source": by_source.most_common(),
        "new_work_by_cdm_type": Counter(t for _, t in todo).most_common(),
        "mapped_by_cdm_type": Counter(r["cdm_type"] for r in mapped).most_common(),
        "elapsed_seconds": round(time.time() - t_start, 1),
        "max_workers": args.workers,
    }
    with open(out_dir / "cv_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[5/5] summary")
    print(json.dumps({k: summary[k] for k in
                      ("work_set", "coverage")}, indent=2))
    print(f"      canonical top-10: {by_canon_vocab.most_common(10)}")
    print(f"\nDone in {summary['elapsed_seconds']}s -> {out_dir}")


if __name__ == "__main__":
    main()
