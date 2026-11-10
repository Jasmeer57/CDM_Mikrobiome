# Human microbiome data catalogue — v3.1.1

**453 papers, 52,400 machine-extracted records** in six linked tables, cleaned, linked within each paper, and mapped to controlled vocabularies.

> **Status: machine-extracted, not yet human-validated.** A validation sample and reviewer guide exist (`outputs/results/catalogue_v3_validation/`); precision figures will be added once curators have scored it.

## Tables

| table | rows |
|---|---:|
| papers | 453 |
| datasets | 2,976 |
| data_assets | 1,992 |
| cohorts | 7,085 |
| samples | 7,530 |
| assays | 8,545 |
| findings | 24,272 |

Join key: `paper_id` (`HMPAPER_######`). Within a paper, `dataset_id`, `cohort_id` and `assay_id` link records to each other (several ids are `; `-separated); every link is checked to point at a record of the same paper.

## Quality (from `provenance/qa_report.json`)

- All 10 integrity checks: **PASS**.
- Evidence sentence located in the paper: datasets 88.0%, data_assets 96.2%, cohorts 91.7%, samples 94.7%, assays 95.1%, findings 96.9%.
- Link fill: data_assets: dataset_id 95.9%; cohorts: dataset_id 90.4%; samples: dataset_id 95.4%, cohort_id 97.2%; assays: dataset_id 91.4%; findings: dataset_id 89.8%, cohort_id 92.8%, assay_id 93.5%.
- Findings that are the paper's own result (`is_primary_finding`): YES 19,969, NO 4,143, REVIEW 160.
- Taxa linked to NCBI Taxonomy: NOT_A_TAXON_RANK 14,796, LINKED 6,026, NOT_FOUND 1,883, NO_TAXON_NAME 1,322, PARTIAL 235, AMBIGUOUS 9, NOT_LOOKED_UP 1.

## Licence of quoted evidence

Quotes are shipped only for papers whose licence allows it (Europe PMC licence: KEEP 274, REDACT 164, KEEP_NC 15 papers). 18,502 rows from other papers have `evidence_text` removed (`evidence_redacted` = LICENCE); their `evidence_location` still points to the exact section and character span.

## How it was built

| step | script | output |
|---|---|---|
| extraction (v2, Qwen3.5-4B) | `catalogue_ner.py` | `catalogue_ner_v2` |
| A — deterministic cleanup | `clean_catalogue.py` | `catalogue_v3_clean` |
| B — within-paper linking (Qwen/Qwen3.5-4B) | `link_catalogue.py` | `catalogue_v3_linked` |
| C — controlled vocabularies | `normalize_catalogue_vocab.py` | `catalogue_v3_vocab` |
| v3.1 gap pipeline — field completion with NOT_REPORTED (G1), paper fields (G2), record verify-and-repair Gemma+Llama (G3), strict relinking (G4), interventions (G5) | `gap_stages.py`, `link_catalogue.py --prompt_version v3` | `gap_runs/` |
| D — licences, QA, freeze | `fetch_paper_licences.py`, `qa_catalogue_v3.py`, `build_catalogue_release.py` | this release |

Every v2 record is accounted for in `provenance/_v2_to_v3_map.csv` (KEPT, MERGED_INTO, DUPLICATE_OF); folded records are in `provenance/_removed.jsonl`.

## Columns to know

- `*_normalized`, `*_ontology_id`: controlled values next to the original text (never replacing it).
- `finding_source`, `cites_other_work`, `is_primary_finding` (+ `_source` RULE/LLM).
- `direction_flag` / `direction_llm`: rule and model second opinions; `direction` itself is as extracted, spelling-normalised.
- `count_flag`, `accession_valid`, `evidence_match`, `link_status`: why a value was changed or how reliable it is.
- An empty cell means *not extracted*, not *absent from the paper*.

## Verify

```bash
sha256sum -c MANIFEST.sha256
```
