"""Backfill NCBITaxon mappings for ORGANISM entities lacking any NCBITaxon hit.

Reads mapped_entities.json, runs map_ncbi_taxon (3-tier Entrez search) for
ORGANISM entities with no NCBITaxon mapping, updates all_mappings + canonical,
and writes back. Rate-limited to 3 req/s (NCBI limit without API key).

Usage:
    python -m cdm_pipeline.mapping.backfill_ncbitaxon
"""
import json
import sys
import time
from pathlib import Path

from ..config import NER_OUTPUT_DIR
from .mappers import map_ncbi_taxon
from .confidence import resolve_canonical

MAPPED_PATH = NER_OUTPUT_DIR / "mapped_entities.json"
RATE_LIMIT_DELAY = 0.35  # ~3 req/s


def main():
    with open(MAPPED_PATH, encoding="utf-8") as f:
        mapped = json.load(f)

    organisms = [e for e in mapped if e.get("cdm_type") == "ORGANISM"]
    need_backfill = [
        e for e in organisms
        if not any(
            "NCBITAXON" in m.get("ontology_name", "").upper()
            for m in e.get("all_mappings", [])
        )
    ]
    print(f"Total ORGANISM entities: {len(organisms)}")
    print(f"Already have NCBITaxon: {len(organisms) - len(need_backfill)}")
    print(f"Need backfill: {len(need_backfill)}")
    print()

    if not need_backfill:
        print("Nothing to do.")
        return

    t0 = time.time()
    new_count = 0
    for i, entity in enumerate(need_backfill):
        term = entity["term"]
        cdm_type = entity["cdm_type"]

        results = map_ncbi_taxon(term, cdm_type)
        time.sleep(RATE_LIMIT_DELAY)

        if results:
            entity["all_mappings"].extend(results)
            canonical, others = resolve_canonical(
                entity["all_mappings"], cdm_type
            )
            if canonical:
                entity["canonical"] = canonical
            entity["has_mapping"] = True
            new_count += 1
            tier = results[0].get("mapping_tier", "?")
            if (i + 1) % 200 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                print(f"  {i+1}/{len(need_backfill)} ({rate:.1f}/s) "
                      f"new NCBITaxon: {new_count} (last tier: {tier})")

    elapsed = time.time() - t0
    print(f"\nDone: {new_count}/{len(need_backfill)} new NCBITaxon mappings "
          f"in {elapsed:.0f}s")

    with open(MAPPED_PATH, "w", encoding="utf-8") as f:
        json.dump(mapped, f, ensure_ascii=False)
    print(f"Saved to {MAPPED_PATH}")

    total_ncbi = sum(
        1 for e in mapped
        if e.get("cdm_type") == "ORGANISM"
        and any(
            "NCBITAXON" in m.get("ontology_name", "").upper()
            for m in e.get("all_mappings", [])
        )
    )
    total_org = sum(1 for e in mapped if e.get("cdm_type") == "ORGANISM")
    print(f"\nNCBITaxon coverage: {total_ncbi}/{total_org} "
          f"({100*total_ncbi/total_org:.1f}%)")


if __name__ == "__main__":
    main()
