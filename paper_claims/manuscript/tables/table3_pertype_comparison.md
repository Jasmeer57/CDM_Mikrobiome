# Table 3. Per-CDM-type method comparison (50-paper LLM / 50-paper spaCy cohort, v2 filtered KG).

Counts are unique normalized terms per method. spaCy counts are the union of 4 models (`en_core_sci_lg`, `en_ner_craft_md`, `en_ner_bc5cdr_md`, `en_ner_jnlpba_md`); `en_core_sci_lg` is retained but contributes mostly generic `ENTITY` labels mapped to UNKNOWN. "LLM-only" means no spaCy model produces this type.

| CDM type | LLM n | spaCy union n | LLM-only? |
|---|---|---|---|
| ORGANISM | 523 | 311 | no |
| CHEMICAL | 223 | 778 | no |
| DISEASE | 241 | 768 | no |
| PROTEIN | 68 | 1,208 | no |
| DNA_RNA | 24 | 805 | no |
| CELL_TYPE | 15 | 412 | no |
| PATHWAY | 64 | 0 | **yes (LLM-only)** |
| LAB_METHOD | 64 | 0 | **yes (LLM-only)** |
| DATA_ANALYSIS | 213 | 0 | **yes (LLM-only)** |
| SAMPLE_METHOD | 59 | 0 | **yes (LLM-only)** |
| EXPERIMENTAL_METHOD | 29 | 0 | **yes (LLM-only)** |
| CLINICAL | 20 | 0 | **yes (LLM-only)** |
| GENOMICS | 14 | 0 | **yes (LLM-only)** |
| STUDY_DESIGN | 7 | 0 | **yes (LLM-only)** |
| UNKNOWN | 0 | 92 | (spaCy artifact) |
| **Total** | **1,564** | **4,359 + 503 cross** | |

**Findings:**
- **8 of 14 CDM types** (PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, GENOMICS, STUDY_DESIGN) are produced by the LLM only; no spaCy model has labels for these.
- spaCy produces 4,862 total unique terms (4,359 spaCy-only + 503 cross-source) vs the LLM's 1,564 — a 3.1× volume gap in spaCy's favor on the 6 types where both are present.
- The **Jaccard overlap** between LLM and spaCy union is 503 / 5,923 = **0.085** — the two methods are largely disjoint, so combining them captures substantially more entities than either alone.
