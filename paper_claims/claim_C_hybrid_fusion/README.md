# Claim C — Hybrid (5-source) fusion > either single method on KG quality

## Claim statement

> The 5-source knowledge-graph construction pipeline (ChEBI metabolic + UMLS scispaCy + NCBI Taxonomy + paper LLM + scientific LLM, fused into a single graph with type-pair constraint enforcement) produces a higher-coverage, lower-noise, more-mechanistically-grounded knowledge graph than either the LLM-only or spaCy-only approach alone — measured on entity count, triple count, ontology coverage, dedup rate, and case-study queryable biology.

## Why this is the load-bearing claim

This is **the main paper contribution**. The 5-source fusion is the architectural innovation, not the individual extractors. The paper's headline numbers come from this:
- 9,126 entities (vs. ~3,000 from LLM-only, ~6,000 from spaCy-only)
- 839 relationships with mechanistic evidence (ChEBI, KEGG, EC numbers)
- ETEC diarrhea-scope subgraph with curable, queryable biology

## Test design

Three KG configurations:

| Config | Entities | Relationships | Source |
|---|---|---|---|
| **LLM-only** | LLM pipeline's `*.cdm_entities.json` output | LLM-relationship-extractor output | `llm_terms/core/relationship_extractor.py` |
| **spaCy-only** | spaCy pipeline's `step5_final_selection_*.csv` | spaCy's per-paper co-occurrence edges (no semantic RE) | `spacy_terms/src/modules/terms_extractor.py` + `spacy_terms/output/` |
| **Hybrid (5-source)** | `Output_final/entities/*.json` (9,126) | `Output_final/relationships_extracted/*.json` (839) + co-occurrence | `llm_terms/scripts/build_knowledge_graph.py` |

For each config, report:
- **Entity count** (raw + after canonicalization)
- **Entity type distribution** (ORGANISM, CHEMICAL, DISEASE, ...)
- **Triple count** (after type-pair constraint enforcement)
- **Ontology coverage**: fraction of entities with UMLS_CUI / ChEBI / NCBITaxon / OMOP mapping
- **Cross-paper evidence**: fraction of relationships supported by ≥2 papers
- **Confidence distribution**: mean / median / 10th percentile
- **Dedup rate**: how many raw extractions collapse into one canonical entity

## Case studies (3-5 queryable biology questions)

These are the **qualitative** evidence — concrete queries against the KG that biologists would actually want to run.

1. **"Which organisms are associated with inflammatory bowel disease (IBD)?"**
   - Expected: `Faecalibacterium prausnitzii`, `Akkermansia muciniphila`, etc., with `correlates_with` or `treats` edges to IBD.
2. **"What bacteria produce butyrate?"**
   - Expected: ChEBI-derived edges: `Faecalibacterium prausnitzii -produces→ butyrate`, `Eubacterium rectale -produces→ butyrate`, `Roseburia spp. -produces→ butyrate`.
3. **"Which antibiotics disrupt the gut microbiome?"**
   - Expected: `vancomycin -disrupts→ gut microbiome`, etc.
4. **"What is the taxonomic lineage of Faecalibacterium prausnitzii?"**
   - Expected: NCBI Taxonomy-derived hierarchy: `Bacteria → Firmicutes → Clostridia → ... → F. prausnitzii`.
5. **"What chemicals are treatments for Crohn's disease?"**
   - Expected: `infliximab -treats→ Crohn's`, `adalimumab -treats→ Crohn's`, `5-ASA -treats→ Crohn's`.

For each case study, the script prints a Cypher query and the expected answer pattern.

## Where the data lives

- **Canonical hybrid output:** `llm_terms/Output_final/entities/*.json` and `relationships_extracted/*.json` (gitignored, 85MB entities + 28KB relationships)
- **LLM pipeline raw output:** re-run via `python llm_terms/main.py --input papers_txt/<file>.txt` per paper
- **spaCy pipeline raw output:** `spacy_terms/output/step5_final_selection_*.csv` (or re-run)
- **ChEBI curated list:** hardcoded in `llm_terms/scripts/extract_chebi_relationships.py` (10 metabolites)
- **Microbiome curated list:** hardcoded in `spacy_terms/src/modules/microbiome_components.py` (55+ terms)
- **Type-pair constraints:** `llm_terms/config/type_normalization.py:VALID_TYPE_PAIRS`

## Verdict

- Hybrid gets >2× the triple count of LLM-only AND >2× the UMLS coverage of spaCy-only: **claim supported**
- Hybrid wins on ≥3 of the 6 metrics: **claim supported**
- Hybrid wins on 1-2 metrics: **claim weak**
- LLM-only or spaCy-only wins on most metrics: **claim falsified; something's wrong with the fusion logic**

## What the script produces

Running `benchmark.py` produces:
- `results/config_comparison.csv` — per-config metrics table
- `results/entity_type_distribution.csv` — per-config type breakdown
- `results/case_study_queries.cypher` — 5 Neo4j Cypher queries
- Prints case-study expected answers

## Manual review

The 5 case-study queries are the paper's qualitative evidence. For each:
- Run the query against the Neo4j-loaded hybrid graph (see `llm_terms/scripts/load_neo4j_full.py`)
- Compare the results against the "Expected" answer
- If the answer matches, that's a piece of evidence the KG works.
- If not, that's a calibration point — maybe the KG has a coverage gap that needs a case study.
