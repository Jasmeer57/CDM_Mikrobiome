# Human microbiome data catalogue — v3.0.0

**453 papers, 54,986 machine-extracted records** in six linked tables, cleaned, linked within each paper, and mapped to controlled vocabularies.

> **Status: machine-extracted, not yet human-validated.** A validation sample and reviewer guide exist (`outputs/results/catalogue_v3_validation/`); precision figures will be added once curators have scored it.

## Tables

| table | rows |
|---|---:|
| papers | 453 |
| datasets | 3,064 |
| data_assets | 2,041 |
| cohorts | 7,451 |
| samples | 8,461 |
| assays | 9,292 |
| findings | 24,677 |

Join key: `paper_id` (`HMPAPER_######`). Within a paper, `dataset_id`, `cohort_id` and `assay_id` link records to each other (several ids are `; `-separated); every link is checked to point at a record of the same paper.

## Quality (from `provenance/qa_report.json`)

- All 10 integrity checks: **PASS**.
- Evidence sentence located in the paper: datasets 87.8%, data_assets 96.1%, cohorts 91.7%, samples 94.3%, assays 94.9%, findings 96.8%.
- Link fill: data_assets: dataset_id 92.8%; cohorts: dataset_id 93.0%; samples: dataset_id 95.4%, cohort_id 98.7%; assays: dataset_id 93.0%; findings: dataset_id 83.9%, cohort_id 93.5%, assay_id 93.9%.
- Findings that are the paper's own result (`is_primary_finding`): YES 18,272, NO 5,833, REVIEW 572.
- Taxa linked to NCBI Taxonomy: NOT_A_TAXON_RANK 15,125, LINKED 6,071, NOT_FOUND 1,909, NO_TAXON_NAME 1,329, PARTIAL 234, AMBIGUOUS 9.

## Licence of quoted evidence

Quotes are shipped only for papers whose licence allows it (Europe PMC licence: KEEP 274, REDACT 164, KEEP_NC 15 papers). 19,537 rows from other papers have `evidence_text` removed (`evidence_redacted` = LICENCE); their `evidence_location` still points to the exact section and character span.

## How it was built

| step | script | output |
|---|---|---|
| extraction (v2, Qwen3.5-4B) | `catalogue_ner.py` | `catalogue_ner_v2` |
| A — deterministic cleanup | `clean_catalogue.py` | `catalogue_v3_clean` |
| B — within-paper linking (Qwen/Qwen3.5-4B) | `link_catalogue.py` | `catalogue_v3_linked` |
| C — controlled vocabularies | `normalize_catalogue_vocab.py` | `catalogue_v3_vocab` |
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
