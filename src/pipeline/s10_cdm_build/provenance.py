"""Step 5: Build provenance trace for the CDM pipeline."""
import json
from datetime import datetime, timezone

from pipeline.config import CDM_OUTPUT_DIR

OUT = CDM_OUTPUT_DIR


def build_provenance(corpus):
    print("\n" + "=" * 60)
    print("STEP 5: Building provenance trace")
    print("=" * 60)

    provenance = {
        "metadata": {
            "name": "Microbiome CDM Provenance",
            "version": "2.0.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "pipeline": [
                {"step": 1, "name": "NER extraction", "models": ["GLiNER", "PubTator3", "BioBERT"],
                 "papers": corpus["metadata"]["source_papers"]},
                {"step": 2, "name": "Entity deduplication", "method": "case-insensitive normalize + junk filter",
                 "unique_entities": len(corpus["entities"])},
                {"step": 3, "name": "Ontology mapping", "services": ["OLS", "OMOP Athena", "NCBI Taxonomy"],
                 "mapped": corpus["metadata"]["entities_with_external_mapping"]},
                {"step": 4, "name": "Relationship extraction", "method": "co-occurrence within papers, meaningful type pairs"},
                {"step": 5, "name": "Schema creation", "tables": 8, "indexes": 24, "views": 8},
            ],
        },
        "entities": [],
    }

    for e in corpus["entities"]:
        canon = e.get("canonical_mapping") or {}
        method = "none"
        if canon:
            if canon.get("confidence", 0) >= 0.95:
                method = "vocab_exact"
            elif canon.get("source") == "umls":
                method = "ner_link"
            else:
                method = "fuzzy_match"

        provenance["entities"].append({
            "raw_term": e["entity"],
            "resolved_term": e["entity"],
            "entity_type": e["entity_type"],
            "canonical_id": canon.get("concept_id", ""),
            "canonical_vocab": canon.get("ontology_name", ""),
            "normalization": {"method": method, "confidence": canon.get("confidence", 0)},
            "paper_count": e["paper_count"],
            "source_papers": e["papers"][:5],
            "ner_sources": e.get("sources", []),
        })

    prov_path = OUT / "cdm_provenance.json"
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False)
    print(f"  Provenance saved to {prov_path} ({len(provenance['entities'])} records)")
