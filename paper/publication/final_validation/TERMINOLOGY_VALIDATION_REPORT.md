# Terminology validation report — external-reference concordance

**Source:** `term_triple/term_triple_summary.json`, produced by `src/scripts/final_validation/term_triple_validation.py`.

**References:**
- NCBI Taxonomy (5.0 M names);
- NCBI Gene, human and mouse (0.9 M names, short symbols case-sensitive);
- CTD/MeSH diseases, Mondo and HPO (0.25 M names);
- CTD/MeSH chemicals (0.72 M names).

**What this measures:** whether a term string resolves in an external vocabulary of its assigned type. This is **concordance, not accuracy.** Real entities may be absent from a vocabulary, and a match can be a coincidental synonym. Nothing in terminology 1.0.1 or CDM 3.0.3 was changed.

## Grounding of typed canonical terms

| CDM type | Terms | Resolve in a same-type vocabulary | Same-type, weighted by mentions | Resolve only under another type |
|---|---:|---:|---:|---:|
| ORGANISM | 12,026 | 12.2% | 48.5% | 123 |
| CHEMICAL | 9,488 | 18.5% | 50.0% | 329 |
| PROTEIN | 8,472 | 11.1% | 27.6% | 171 |
| DISEASE | 7,055 | 16.1% | 54.5% | 168 |
| DNA_RNA | 5,838 | 1.2% | 16.8% | 52 |

The other nine CDM types (cell type, methods, study design, clinical and so on) have no matching reference vocabulary here and are **not evaluated**.

**Reading the two columns:**
- **By distinct term, concordance is low.** The terms most often unresolved are generic words or noise assigned a type: "infants", "microbial", "associated with" typed as ORGANISM; "patients", "group", "results" typed as DISEASE.
- **By mention, about half of organism, chemical and disease mentions resolve.** Frequent real entities ground; the long tail of rare strings is dominated by noise, abbreviations ("C. difficile", "UC") and variants.

**Conclusion:** the typed terminology contains a large share of non-entity or non-normalised strings. This is consistent with the generic-ENTITY finding below and must be stated as a limitation.

## The 55% generic ENTITY terms

| Resolution of the 89,799 ENTITY terms | Terms |
|---|---:|
| no reference vocabulary | 88,266 (98.3%) |
| organism only | 459 |
| gene/protein only | 381 |
| chemical only | 301 |
| disease only | 278 |
| several | 114 |

**Proposal only (not applied):**
- 1,419 ENTITY terms could be retyped from a single unambiguous reference match.
- The remaining 98% are mostly not resolvable named entities. They are better treated as an "unclassified" layer than as CDM terms.
- Any retyping belongs in a future terminology release, after review.

## Mapping candidates vs accepted mappings

| Disposition (guard-kept rows) | Rows | Concept label equals the term |
|---|---:|---:|
| ACCEPTED (two-model agreement) | 18,272 | 6,672 (36.5%) |
| REVIEW_REQUIRED (models disagree) | 36,505 | 1,300 (3.6%) |
| REMOVED (both models: wrong) | 4,460 | 21 (0.5%) |
| NOT REVIEWED (non-top candidates) | 255,535 | 49,724 (19.5%; 10,680 have no concept label) |

**Services:**
- Accepted: BioPortal 9,042, OLS 8,082, NCBI Taxonomy 624, UMLS 524.
- Unreviewed candidates: all six services.

**Interpretation:** exact label agreement is much higher among accepted mappings than among removed ones. That is consistent with the model adjudication tracking lexical evidence, but it does not prove the accepted mappings are correct. Synonym-level matches (the label differs) are 63.5% of accepted rows. Their semantic correctness is unassessed.

## Definitions

- 6,773 definitions for 3,397 terms: 6,185 from the G8 language-model pass (Qwen), 588 from rule patterns.
- All are anchored verbatim in their section: 6,460 at the stated offsets, 313 relocated.
- Whether a passage actually *defines* its term is not assessed.

## Decision

| Dimension | Decision |
|---|---|
| Structural integrity of terminology | PASS (`EXHAUSTIVE_INTEGRITY_REPORT.md`) |
| External-reference concordance | CONDITIONAL: about 50% by mention for organisms, chemicals and diseases; low by distinct term; 9 types unevaluable |
| Type consistency | FAIL as a quality claim: 55% ENTITY, and many typed terms are non-entities |
| Mapping correctness | NOT EVALUATED (model agreement only) |
| Scientific accuracy | NOT EVALUATED |
