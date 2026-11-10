#!/usr/bin/env python3
"""
Mapping-only pass over an already-extracted entity corpus (main.py's
--input/--output JSON shape). Runs mappers/mapping.py's ComprehensiveMapper
(UMLS + OLS + BioPortal; OMOP local mapper included but degrades to empty
mappings when no OMOP_VOCAB_DIR is configured).

Two-pass design to avoid redundant network calls and to parallelize the
I/O-bound mapping calls:
  1. Scan every corpus file, collect the set of UNIQUE (entity, entity_type)
     pairs across the whole corpus (the same organism/chemical/etc. shows up
     in dozens of papers - map it once, not once per occurrence).
  2. Map that unique set concurrently (ThreadPoolExecutor - each mapping call
     is 1-3 sequential HTTP requests to BioPortal/OLS/UMLS, so this is
     network-latency bound, not CPU bound - threads help a lot here).
  3. Re-walk the corpus files and attach the precomputed mapping to every
     occurrence, writing <name>.mapped.json per file.

Usage:
    python scripts/map_existing_corpus.py --input_dir <dir of *.cdm_entities.json> --output_dir <dir> [--workers 10]

Reads UMLS_API_KEY / BIOPORTAL_API_KEY from the environment (never from argv,
so keys don't end up in shell history / process listings).
"""
import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mappers.mapping import ComprehensiveMapper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(description="Map an already-extracted entity corpus to UMLS/OLS/BioPortal/OMOP.")
    p.add_argument("--input_dir", required=True, help="Directory of *.cdm_entities.json files from main.py.")
    p.add_argument("--output_dir", required=True, help="Directory to write <name>.mapped.json files.")
    p.add_argument("--limit", type=int, default=None, help="Only process the first N files (for smoke testing).")
    p.add_argument("--workers", type=int, default=10, help="Concurrent mapping threads.")
    return p.parse_args()


def main():
    args = parse_args()
    umls_key = os.environ.get("UMLS_API_KEY")
    bioportal_key = os.environ.get("BIOPORTAL_API_KEY")
    if not umls_key:
        logger.warning("UMLS_API_KEY not set - UMLS mapping will be skipped for all entities.")
    if not bioportal_key:
        logger.warning("BIOPORTAL_API_KEY not set - BioPortal mapping will be skipped for all entities.")

    mapper = ComprehensiveMapper(
        umls_api_key=umls_key,
        bioportal_api_key=bioportal_key,
        use_local_omop=True,
        omop_vocab_dir=os.environ.get("OMOP_VOCAB_DIR"),  # None -> OMOPLocalMapper logs a warning and stays empty
        fuzzy_threshold=90,
        max_matches=3,
        cache_mappings=True,
    )

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*.json"))
    if args.limit:
        files = files[: args.limit]
    logger.info(f"Found {len(files)} corpus files to map.")

    # Pass 1: collect unique (term, entity_type) pairs across the whole corpus.
    corpora = {}
    unique_pairs = set()
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        corpora[fp] = data
        cdm_entities = data.get("results", {}).get("cdm_entities", {})
        for entity_type, entities in cdm_entities.items():
            for ent in entities:
                term = ent.get("entity")
                if term:
                    unique_pairs.add((term, entity_type))

    logger.info(f"{len(unique_pairs)} unique (entity, type) pairs to map across {len(files)} files "
                f"(with --workers {args.workers}).")

    # Pass 2: map the unique set concurrently.
    mapping_lookup = {}
    start = time.time()
    done = 0

    def _map_one(pair):
        term, entity_type = pair
        return pair, mapper.map_entity_comprehensive(term, entity_type)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_map_one, pair): pair for pair in unique_pairs}
        for future in as_completed(futures):
            pair, result = future.result()
            mapping_lookup[pair] = result
            done += 1
            if done % 50 == 0 or done == len(unique_pairs):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed else 0
                remaining = (len(unique_pairs) - done) / rate if rate else 0
                logger.info(f"Mapped {done}/{len(unique_pairs)} unique pairs "
                            f"({rate:.2f}/s, ~{remaining/60:.1f} min remaining)")

    # Pass 3: reattach mappings to every occurrence and write per-file output.
    total_entities = 0
    total_with_mapping = 0
    for fp, data in corpora.items():
        cdm_entities = data.get("results", {}).get("cdm_entities", {})
        file_total = 0
        file_mapped = 0
        for entity_type, entities in cdm_entities.items():
            new_list = []
            for ent in entities:
                term = ent.get("entity")
                if not term:
                    new_list.append(ent)
                    continue
                mapping = mapping_lookup.get((term, entity_type), {})
                new_list.append({**ent, "comprehensive_mapping": mapping})
                file_total += 1
                if mapping.get("has_any_mapping"):
                    file_mapped += 1
            cdm_entities[entity_type] = new_list

        total_entities += file_total
        total_with_mapping += file_mapped

        out_fp = output_dir / (fp.stem.replace(".cdm_entities", "") + ".mapped.json")
        with open(out_fp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(
        f"DONE. {len(files)} files, {len(unique_pairs)} unique pairs mapped, "
        f"{total_entities} total entity instances, {total_with_mapping} with >=1 mapping "
        f"({(100*total_with_mapping/total_entities if total_entities else 0):.1f}% overall)."
    )


if __name__ == "__main__":
    main()
