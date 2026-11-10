"""Ontology mapping runner — maps deduplicated entities to controlled vocabularies.

Reads:  paper/_multi_ner_runs/deduplicated_entities.json
Writes: paper/_multi_ner_runs/mapped_entities.json
        paper/_multi_ner_runs/mapping_checkpoint.json  (resume support)
"""
import sys
import io
import os
import json
import time
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

from ..config import NER_OUTPUT_DIR, MAPPING_DIR, REPO_ROOT, UMLS_API_KEY, BIOPORTAL_API_KEY, ENTREZ_API_KEY
from .mappers import map_ols, map_umls, map_bioportal, map_omop, map_ncbi_taxon
from .confidence import resolve_canonical

INPUT = NER_OUTPUT_DIR / "deduplicated_entities.json"
OUTPUT = MAPPING_DIR / "mapped_entities.json"
CHECKPOINT = MAPPING_DIR / "mapping_checkpoint.json"

MAX_WORKERS = 24
CHECKPOINT_EVERY = 500


def map_one_entity(entity):
    """Map a single entity to all available vocabularies."""
    term = entity["term"]
    cdm_type = entity["cdm_type"]

    candidates = []
    candidates.extend(map_ols(term, cdm_type))
    candidates.extend(map_umls(term, cdm_type))
    candidates.extend(map_bioportal(term, cdm_type))
    candidates.extend(map_omop(term, cdm_type))
    candidates.extend(map_ncbi_taxon(term, cdm_type))

    canonical, others = resolve_canonical(candidates, cdm_type)

    return {
        "term": term,
        "norm": entity["norm"],
        "cdm_type": cdm_type,
        "sources": entity["sources"],
        "paper_count": entity["paper_count"],
        "mention_count": entity["mention_count"],
        "canonical": canonical,
        "all_mappings": candidates,
        "has_mapping": canonical is not None,
    }


def load_checkpoint():
    if CHECKPOINT.exists():
        with open(CHECKPOINT, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "results": []}


def save_checkpoint(cp):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False)


def main():
    with open(INPUT, encoding="utf-8") as f:
        entities = json.load(f)
    print(f"Loaded {len(entities)} deduplicated entities")

    typed = [e for e in entities if e["cdm_type"] != "ENTITY"]
    # Filter: keep entities found in 2+ papers OR by 2+ NER models
    # Single-paper, single-source entities are low-confidence and slow down mapping
    typed = [e for e in typed if e["paper_count"] >= 2 or len(e["sources"]) >= 2]
    entity_by_norm = {e["norm"]: e for e in entities}
    print(f"  Typed (mapped): {len(typed)},  ENTITY-only (skipped): {len(entities) - len(typed)}")

    cp = load_checkpoint()
    results = cp["results"]

    # A cached result is only reusable if it was computed under the *same*
    # cdm_type.  ``cdm_type`` is not decoration: it gates which vocabularies
    # ``_is_type_appropriate`` will accept, feeds ``_confidence``, and makes
    # ``map_ncbi_taxon`` a no-op for anything that is not ORGANISM.  Reusing a
    # result across a type change therefore silently returns another type's
    # candidates.  A re-scoped rebuild re-resolves types from a different model
    # mix, and on the 452 build 35% of the overlapping terms changed type, so
    # the cache is validated per entry instead of trusted wholesale.
    stale = [r for r in results
             if r.get("norm") in entity_by_norm
             and r.get("cdm_type") != entity_by_norm[r["norm"]]["cdm_type"]]
    stale_norms = {r["norm"] for r in stale}
    if stale:
        print(f"  Discarding {len(stale)} cached results whose cdm_type changed "
              f"(re-mapping under the new type)")
    results = [r for r in results if r.get("norm") not in stale_norms]
    done = {k: v for k, v in cp["done"].items() if k not in stale_norms}
    cp["results"] = results
    cp["done"] = done

    for r in results:
        e = entity_by_norm.get(r.get("norm"))
        if e:
            r["sources"] = e["sources"]
            r["paper_count"] = e["paper_count"]
            r["mention_count"] = e["mention_count"]

    todo = [e for e in typed if e["norm"] not in done]
    print(f"Already mapped: {len(done)}, remaining: {len(todo)}")

    if not todo:
        print("Nothing to do.")
    else:
        t0 = time.time()
        mapped = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(map_one_entity, e): e for e in todo}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    cp["done"][result["norm"]] = True
                    mapped += 1
                except Exception as ex:
                    e = futures[future]
                    cp["done"][e["norm"]] = False
                    results.append({
                        "term": e["term"], "norm": e["norm"],
                        "cdm_type": e["cdm_type"], "sources": e["sources"],
                        "paper_count": e["paper_count"], "mention_count": e["mention_count"],
                        "canonical": None, "all_mappings": [], "has_mapping": False,
                    })
                    mapped += 1

                if mapped % CHECKPOINT_EVERY == 0:
                    save_checkpoint(cp)
                    rate = mapped / (time.time() - t0)
                    print(f"  {mapped}/{len(todo)} ({rate:.1f}/s) "
                          f"mapped={sum(1 for r in results if r['has_mapping'])}")

        save_checkpoint(cp)
        elapsed = time.time() - t0
        print(f"Done: {mapped} in {elapsed:.1f}s")

    # Final output — keep only entities present in the current dedup set
    # (stale checkpoint entries from prior runs are dropped)
    valid_norms = set(entity_by_norm.keys())
    results = [r for r in results if r.get("norm") in valid_norms]
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(results)} mapped entities to {OUTPUT}")

    # Summary
    total = len(results)
    mapped_count = sum(1 for r in results if r["has_mapping"])
    by_type = {}
    by_vocab = {}
    for r in results:
        t = r["cdm_type"]
        by_type.setdefault(t, {"total": 0, "mapped": 0})
        by_type[t]["total"] += 1
        if r["has_mapping"]:
            by_type[t]["mapped"] += 1
            v = r["canonical"]["ontology_name"]
            by_vocab[v] = by_vocab.get(v, 0) + 1

    print(f"\n=== MAPPING SUMMARY ===")
    print(f"Total entities: {total}")
    print(f"Mapped: {mapped_count} ({100*mapped_count/total:.1f}%)")
    print(f"\nBy CDM type:")
    for t in sorted(by_type, key=lambda x: -by_type[x]["total"]):
        d = by_type[t]
        print(f"  {t:20s} {d['mapped']:5d}/{d['total']:<5d} ({100*d['mapped']/d['total']:.1f}%)")
    print(f"\nTop mapped vocabularies:")
    for v, c in sorted(by_vocab.items(), key=lambda x: -x[1])[:15]:
        print(f"  {v:20s} {c}")

    # Write summary JSON
    summary = {
        "total": total, "mapped": mapped_count, "rate": 100*mapped_count/total,
        "by_type": by_type, "by_vocab": by_vocab,
        "api_keys_used": {
            "umls": bool(UMLS_API_KEY), "bioportal": bool(BIOPORTAL_API_KEY),
            "entrez": bool(ENTREZ_API_KEY),
        },
    }
    summary_path = MAPPING_DIR / "mapping_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
