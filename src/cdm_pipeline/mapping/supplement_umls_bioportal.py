#!/usr/bin/env python3
"""Supplement UMLS + BioPortal mappings into existing mapped_entities.json."""
import json
import os
import sys
import time
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cdm_pipeline.mapping.mappers import map_umls, map_bioportal
from cdm_pipeline.mapping.confidence import resolve_canonical
from cdm_pipeline.config import NER_OUTPUT_DIR

INPUT = NER_OUTPUT_DIR / "mapped_entities.json"
OUTPUT = NER_OUTPUT_DIR / "mapped_entities.json"
CHECKPOINT = NER_OUTPUT_DIR / "umls_bp_checkpoint.json"
MAX_WORKERS = 24
CHECKPOINT_EVERY = 200


def map_supplement(entity):
    """Run only UMLS + BioPortal for one entity."""
    term = entity["term"]
    cdm_type = entity["cdm_type"]
    new_candidates = []
    new_candidates.extend(map_umls(term, cdm_type))
    new_candidates.extend(map_bioportal(term, cdm_type))
    return entity["norm"], new_candidates


def load_checkpoint():
    if CHECKPOINT.exists():
        with open(CHECKPOINT, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}}


def save_checkpoint(cp):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(cp, f)


def main():
    with open(INPUT, encoding="utf-8") as f:
        entities = json.load(f)
    print(f"Loaded {len(entities):,} mapped entities")

    # Load checkpoint
    cp = load_checkpoint()
    done = set(cp["done"].keys())
    todo = [e for e in entities if e["norm"] not in done]
    print(f"Already done: {len(done):,}, remaining: {len(todo):,}")

    if not todo:
        print("Nothing to do.")
    else:
        t0 = time.time()
        processed = 0
        umls_hits = 0
        bp_hits = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(map_supplement, e): e for e in todo}
            for future in as_completed(futures):
                norm, new_candidates = future.result()
                cp["done"][norm] = True

                # Find the entity in our list and merge
                # Build a lookup for efficiency
                # Actually we need to update the entity in-place
                # Since we loaded entities as list of dicts, find by norm
                # This is O(n) per lookup, but we can build an index
                if processed == 0:
                    # Build index on first iteration
                    global _entity_index
                    _entity_index = {e["norm"]: e for e in entities}

                e = _entity_index.get(norm)
                if e:
                    # Add new candidates to all_mappings
                    existing_sources = {(c.get("source"), c.get("concept_id"))
                                       for c in e.get("all_mappings", [])}
                    for c in new_candidates:
                        key = (c.get("source"), c.get("concept_id"))
                        if key not in existing_sources:
                            e["all_mappings"].append(c)
                            existing_sources.add(key)
                            if c["source"] == "umls":
                                umls_hits += 1
                            elif c["source"] == "bioportal":
                                bp_hits += 1

                    # Re-resolve canonical
                    canonical, others = resolve_canonical(e["all_mappings"], e["cdm_type"])
                    e["canonical"] = canonical
                    e["has_mapping"] = canonical is not None

                processed += 1
                if processed % CHECKPOINT_EVERY == 0:
                    save_checkpoint(cp)
                    rate = processed / (time.time() - t0)
                    print(f"  {processed}/{len(todo)} ({rate:.1f}/s) "
                          f"UMLS hits={umls_hits} BP hits={bp_hits}")

        save_checkpoint(cp)
        elapsed = time.time() - t0
        print(f"Done: {processed:,} in {elapsed:.1f}s ({processed/elapsed:.1f}/s)")
        print(f"  UMLS hits: {umls_hits:,}")
        print(f"  BioPortal hits: {bp_hits:,}")

    # Save updated entities
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(entities, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(entities):,} entities to {OUTPUT}")

    # Summary
    umls_mapped = sum(1 for e in entities
                      if any(m.get("source") == "umls" for m in e.get("all_mappings", [])))
    bp_mapped = sum(1 for e in entities
                    if any(m.get("source") == "bioportal" for m in e.get("all_mappings", [])))
    total_mapped = sum(1 for e in entities if e.get("has_mapping"))

    print(f"\n=== SUPPLEMENTARY MAPPING SUMMARY ===")
    print(f"Total entities: {len(entities):,}")
    print(f"Total mapped: {total_mapped:,} ({100*total_mapped/len(entities):.1f}%)")
    print(f"UMLS mapped: {umls_mapped:,}")
    print(f"BioPortal mapped: {bp_mapped:,}")


if __name__ == "__main__":
    main()
