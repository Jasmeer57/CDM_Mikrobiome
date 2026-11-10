# Introduction — first funnel draft (saved verbatim, 2026-11-07)

*Provenance note: this is the four-paragraph Introduction draft as supplied in
conversation (2026-11-07), saved unchanged for the record. It is draft material,
not submission text — BiB does not accept LLM-drafted prose (see
`BIB_MANUSCRIPT_PLAN.md` §0 and OUP AI policy), so the authors must rewrite the
prose in their own voice before it enters `manuscript.tex`. The scaffold-edited
refinement of this draft is in `INTRODUCTION_DRAFT.md`; the key changes are the
framing-rule fixes flagged at the bottom of this file.*

---

## Introduction

The scale of human microbiome research has expanded exponentially, generating vast repositories of sequencing data. Recent large-scale meta-analyses, such as the comprehensive synthesis of 168,000 samples across 482 BioProjects [1], highlight the immense analytical potential of cross-study comparisons. However, while raw sequencing reads and primary data are readily accessible in public repositories, the vital meta-information and biological context—such as host phenotypes, cohort demographics, clinical interventions, and exact assay conditions—remain largely locked as unstructured text within the referenced publications.

Harmonizing this metadata manually represents a primary rate-limiting step in computational biology. Thoroughly inspecting the source studies referenced in large meta-analyses requires reading, interpreting, and standardizing complex domain-specific language across hundreds of papers. This manual curation is not only prohibitively time-consuming but also prone to human error and inconsistency across annotators. Existing biomedical databases generally either rely on this slow manual curation, which fails to keep pace with the publication rate, or lack the specialized, schema-driven architecture required to capture the specific nuances of human microbiome research.

To address this critical bottleneck, we developed Microbiome-CDM, an automated, large-scale knowledge extraction pipeline and Common Data Model designed specifically for human microbiome literature. The pipeline programmatically resolves unstructured text by first ingesting publications and transforming them into structured Markdown, followed by section-aware segmentation. We then apply an ensemble of Named Entity Recognition (NER) models to extract biological concepts, which are dynamically normalized to generate formal, domain-specific ontologies. Finally, utilizing large language models (LLMs) configured with a strict, human-microbiome-specific schema, we perform knowledge extraction to identify and map complex entity-relation triples.

Here, we present the architecture of the Microbiome-CDM pipeline and its resulting dataset. Operating on a foundational corpus of 453 reference papers, the pipeline processed 4,006 full-text sections to extract, harmonize, and validate 25,788 canonical relations. We detail the multi-phase processing lineage—from initial corpus acquisition through terminology canonicalization to computational evaluation—demonstrating how this framework accurately bridges the gap between unstructured publications and computable data. By replacing manual literature review with automated, LLM-driven knowledge extraction, Microbiome-CDM provides a highly structured resource that enables researchers to programmatically query human microbiome relationships at scale.

---

## Notes from the draft author

* **Placeholder `[1]`:** `[1]` is the Cell 2025 paper (abdill2025), matching the provisional numbering in `../submission_readiness/REFERENCES_BRIEF_BIOINFORM.md`.
* **Vocabulary:** "rate-limiting step" is woven in deliberately — it signals alignment with BiB's stated journal aims.
* **Transition:** the final paragraph's "multi-phase processing lineage" and "corpus of 453 reference papers" set up the first Methods heading (Stage 1: Corpus and sectioning — see `INTRODUCTION_OUTLINE.md` transition table).

## Framing-rule flags to fix during the author rewrite (details in `INTRODUCTION_DRAFT.md`)

1. P4 "to extract, harmonize, and **validate**" — no human validation exists; the judge verdicts are model judgements (concordance, not accuracy). Replace with the bucket counts (SUPPORTED 14,363 / PARTIAL 5,780 / NOT_SUPPORTED 4,618) or wording like "characterize".
2. P4 "**accurately** bridges the gap" — same rule; avoid accuracy language entirely.
3. P3 "generate formal, domain-specific ontologies" — the pipeline produces a canonical terminology + taxonomy with guarded mapping; "formal ontologies" overclaims.
4. Citation map if kept in this order: [3] geistlinger2023, [4] langarica2025minerva, [5][6] MINERVA exchange, [7] hogan2024midred, [8] hong2025dimbre, [9] higashi2024harmonization, [10] chen2025llmbench, [33] zheng2023mtbench attach in P2/P3 per `INTRODUCTION_OUTLINE.md`.
