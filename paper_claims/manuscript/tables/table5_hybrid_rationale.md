# Table 5. Why hybrid? — Quantitative complementarity between LLM and scispaCy (v2, 50-paper cohort).

## Jaccard overlap (normalized term sets)

| comparison | Jaccard | shared | LLM-only | spaCy-only |
|---|---|---|---|---|
| LLM vs spaCy union | **0.085** | **503** | **1,061** | **4,359** |

## Type complementarity

- **8 LLM-only CDM types:** PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, GENOMICS, STUDY_DESIGN
- **6 types covered by both:** ORGANISM, CHEMICAL, DISEASE, PROTEIN, DNA_RNA, CELL_TYPE
- **The Jaccard is 0.085** — only 8.5% of the union is shared. The two methods are largely disjoint, so the hybrid captures substantially more entities than either alone.
