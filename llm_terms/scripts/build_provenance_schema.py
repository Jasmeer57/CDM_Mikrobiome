#!/usr/bin/env python3
"""
Unifies the two separate provenance signals this pipeline already produces -
mapping resolution (UMLS/OLS/BioPortal/OMOP, via canonical_mapping from
vocabulary_precedence.py) and dedup resolution (fuzzy fast-merge / LLM
contextual judgment, from run_biomedical_dedup.py's merge log) - into one
per-entity record with a single resolution-method taxonomy:

    vocab_exact     - canonical mapping is an exact string match (confidence 1.0)
    fuzzy_match     - canonical mapping OR a dedup merge resolved via rapidfuzz
                       word/string similarity below exact-match confidence
    ner_link        - canonical mapping came from UMLS's semantic-type-aware
                       search API (acts as an entity linker, not a plain string
                       matcher, unlike the OLS/BioPortal keyword search calls)
    llm_expansion   - dedup merge resolved via the LLM's contextual judgment
                       (BioMistralDeduplicator / _get_bio_contextual_similarity)
    none            - no external mapping and no dedup merge found

This does NOT invent new resolution logic - it labels decisions the pipeline
already made (in mappers/confidence_scoring.py and
core/biomedical_deduplicator.py) with the taxonomy name matching what
produced them, so provenance is traceable without re-deriving anything.

Usage:
    python scripts/build_provenance_schema.py \
        --corpus <unified_entity_corpus.json (has canonical_mapping from build_ontology_from_corpus.py)> \
        --dedup_log <F_biomedical_dedup.log, optional - parses MERGE/FAST-MERGE lines> \
        --output <provenance.json>
"""
import argparse
import json
import re


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", required=True)
    p.add_argument("--dedup_log", default=None,
                   help="Optional: run_biomedical_dedup.py log file, to attach dedup provenance.")
    p.add_argument("--output", required=True)
    return p.parse_args()


MERGE_RE = re.compile(
    r"MERGE: '(?P<dup>.+?)' -> '(?P<canon>.+?)' \(bio_score=(?P<bio>[\d.]+), "
    r"emb_score=(?P<emb>[\d.]+|None), fuzzy_score=(?P<fuzzy>[\d.]+)\)"
)
FAST_MERGE_RE = re.compile(
    r"FAST-MERGE \(fuzzy=(?P<fuzzy>[\d.]+)\): '(?P<dup>.+?)' -> '(?P<canon>.+?)'"
)


def parse_dedup_log(path):
    """Returns {duplicate_term_lower: {"method": ..., "confidence": ..., "canonical": ...}}"""
    merges = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = FAST_MERGE_RE.search(line)
            if m:
                merges[m.group("dup").lower()] = {
                    "method": "fuzzy_match", "confidence": float(m.group("fuzzy")),
                    "canonical": m.group("canon"),
                }
                continue
            m = MERGE_RE.search(line)
            if m:
                merges[m.group("dup").lower()] = {
                    "method": "llm_expansion", "confidence": float(m.group("bio")),
                    "canonical": m.group("canon"),
                }
    return merges


def classify_mapping_method(canonical):
    if not canonical:
        return None, None
    if canonical["source"] == "umls":
        return "ner_link", canonical["confidence"]
    if canonical["confidence"] >= 0.999:
        return "vocab_exact", canonical["confidence"]
    return "fuzzy_match", canonical["confidence"]


def main():
    args = parse_args()
    with open(args.corpus, "r", encoding="utf-8") as f:
        data = json.load(f)

    dedup_merges = parse_dedup_log(args.dedup_log) if args.dedup_log else {}

    records = []
    for e in data["entities"]:
        canonical = e.get("canonical_mapping")
        norm_method, norm_conf = classify_mapping_method(canonical)

        dedup_info = dedup_merges.get(e["entity"].lower())

        records.append({
            "raw_term": e["entity"],
            "resolved_term": dedup_info["canonical"] if dedup_info else e["entity"],
            "entity_type": e["entity_type"],
            "canonical_id": canonical["concept_id"] if canonical else None,
            "canonical_vocab": canonical["ontology_name"] if canonical else None,
            "normalization": {
                "method": norm_method,
                "confidence": norm_conf,
            } if norm_method else None,
            "dedup": {
                "method": dedup_info["method"],
                "confidence": dedup_info["confidence"],
            } if dedup_info else None,
            "paper_count": e["paper_count"],
            "source_papers": e["papers"][:5],  # truncated, full list stays in unified_entity_corpus.json
        })

    method_counts = {}
    for r in records:
        m = r["normalization"]["method"] if r["normalization"] else "none"
        method_counts[m] = method_counts.get(m, 0) + 1
    dedup_method_counts = {}
    for r in records:
        m = r["dedup"]["method"] if r["dedup"] else "none"
        dedup_method_counts[m] = dedup_method_counts.get(m, 0) + 1

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "total_entities": len(records),
                "normalization_method_counts": method_counts,
                "dedup_method_counts": dedup_method_counts,
            },
            "records": records,
        }, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(records)} provenance records to {args.output}")
    print("Normalization methods:", method_counts)
    print("Dedup methods:", dedup_method_counts)


if __name__ == "__main__":
    main()
