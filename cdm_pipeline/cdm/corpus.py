"""Step 1: Build unified entity corpus from mapped entities + NER mentions."""
import json
from collections import defaultdict
from datetime import datetime, timezone

from ..config import (
    CDM_TYPES, VOCAB_PRIORITY, EXACT_MATCH_FLOOR,
    NER_OUTPUT_DIR, CDM_OUTPUT_DIR, PAPERS_DIR,
)
from ..utils import is_junk, norm, load_csv_safe

MAPPED_PATH = NER_OUTPUT_DIR / "mapped_entities.json"
GLINER_CSV = NER_OUTPUT_DIR / "gliner_ner.csv"
PUBTATOR_CSV = NER_OUTPUT_DIR / "pubtator3_ner.csv"

OUT = CDM_OUTPUT_DIR


def build_corpus():
    print("=" * 60)
    print("STEP 1: Building unified entity corpus")
    print("=" * 60)

    with open(MAPPED_PATH, encoding="utf-8") as f:
        mapped = json.load(f)

    # Load per-paper mentions from GLiNER CSV
    paper_mentions = defaultdict(lambda: defaultdict(list))  # paper -> norm -> [(term, type, pos)]
    gliner_rows = load_csv_safe(GLINER_CSV)
    for r in gliner_rows:
        t = r["term"].strip()
        if len(t) < 2:
            continue
        k = norm(t)
        paper_mentions[r["paper"]][k].append((t, r["labels"], int(r.get("char_start", 0))))

    # Build paper -> entity mapping
    entity_papers = defaultdict(set)  # norm -> set of papers
    for paper, mentions in paper_mentions.items():
        for k in mentions:
            entity_papers[k].add(paper)

    # Add PubTator3 paper associations
    pubtator_rows = load_csv_safe(PUBTATOR_CSV)
    for r in pubtator_rows:
        t = r["term"].strip()
        if len(t) < 2:
            continue
        k = norm(t)
        entity_papers[k].add(r["paper"])

    # Build corpus entities with canonical mappings
    entities = []
    skipped_junk = 0
    for m in mapped:
        if is_junk(m["term"]):
            skipped_junk += 1
            continue
        k = m["norm"]
        papers = sorted(entity_papers.get(k, set()))

        # Resolve canonical + SKOS relations from all_mappings
        all_maps = m.get("all_mappings", [])
        canonical = m.get("canonical")
        related = []

        if canonical and all_maps:
            canonical_words = set(canonical.get("label", "").lower().split())
            for c in all_maps:
                if c is canonical:
                    continue
                if c.get("confidence", 0) >= EXACT_MATCH_FLOOR:
                    relation = "exactMatch"
                else:
                    c_words = set(c.get("label", "").lower().split())
                    if c_words and canonical_words and c_words < canonical_words:
                        relation = "broadMatch"
                    elif c_words and canonical_words and canonical_words < c_words:
                        relation = "narrowMatch"
                    else:
                        relation = "relatedMatch"
                related.append({**c, "relation": relation})

        # Group mappings by source
        umls_maps = [c for c in all_maps if c.get("source") == "umls"]
        bp_maps = [c for c in all_maps if c.get("source") == "bioportal"]
        ols_maps = [c for c in all_maps if c.get("source") == "ols"]
        omop_maps = [c for c in all_maps if c.get("source") == "omop"]
        ncbi_maps = [c for c in all_maps if c.get("source") == "ncbi_taxon"]

        entities.append({
            "entity": m["term"],
            "norm": k,
            "entity_type": m["cdm_type"],
            "paper_count": len(papers),
            "papers": papers[:100],  # cap for file size
            "total_occurrences": m.get("mention_count", 0),
            "sources": m.get("sources", []),
            "has_any_external_mapping": canonical is not None,
            "canonical_mapping": canonical,
            "related_mappings": related,
            "umls_mappings": umls_maps,
            "bioportal_mappings": bp_maps,
            "ols_mappings": ols_maps,
            "omop_mappings": omop_maps,
            "ncbi_taxon_mappings": ncbi_maps,
        })

    entities.sort(key=lambda e: (-e["paper_count"], e["entity_type"], e["entity"].lower()))
    print(f"  Filtered {skipped_junk} junk entities, kept {len(entities)}")

    corpus = {
        "metadata": {
            "name": "Microbiome Common Data Model Entity Corpus",
            "version": "2.0.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "source_papers": len(paper_mentions),
            "unique_entities": len(entities),
            "entities_with_external_mapping": sum(1 for e in entities if e["has_any_external_mapping"]),
            "cdm_types": CDM_TYPES,
            "ner_models": ["GLiNER", "PubTator3", "BioBERT"],
            "mapping_services": ["OLS", "OMOP Athena", "NCBI Taxonomy"],
            "vocab_priority": {k: v for k, v in VOCAB_PRIORITY.items()},
        },
        "entities": entities,
    }

    corpus_path = OUT / "unified_entity_corpus.json"
    with open(corpus_path, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)
    print(f"  Corpus: {len(entities)} entities, {corpus['metadata']['entities_with_external_mapping']} mapped")
    print(f"  Saved to {corpus_path}")

    return corpus, entity_papers
