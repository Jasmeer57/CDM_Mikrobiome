# Manual review of 500 accepted ontology mappings: protocol (fixed 2026-11-09, before annotation)

**Status:** an exception to the 2026-11-02 development freeze ("no human annotation"); needs the project lead's
approval, recorded in `paper/publication/final_validation/CHANGE_RECORD.md`. Once done, every "no human annotation"
statement in the manuscript must be updated.

## Question
For mappings accepted by two-model agreement (Gemma G9 and DeepSeek-R1 agreed on the relation), how often does a
person judge the mapped concept to be the same concept as the term (EXACT), and how often broader, narrower, related
or wrong? Secondary: is the term a real concept, is its entity type right, and does an in-paper definition define it?

## Population and sample
- Population: the 18,272 `term_concept_map` rows of CDM 3.0.3 with `mapping_disposition_reviewed = 'ACCEPTED'`
  [P05], over 16,750 deduplicated canonical terms [P06]. Of these, the two models agreed on EXACT for 13,540 rows,
  BROADER 598, NARROWER 1,313 and RELATED 2,821 (the CDM data dictionary's "both EXACT" description of ACCEPTED is
  wrong; the code accepts any agreed relation).
- Sample: simple random sample, n = 500, `random.Random(20261109)`, drawn once by
  `src/scripts/final_validation/human_spotcheck_mappings_sample.py`; presentation order random.
- With n = 500 a proportion near 50% has a 95% Wilson interval of about ±4.4 points.

## Procedure
1. Reviewer A annotates all 500 rows (`ANNOTATION_SHEET_A.xlsx`); reviewer B independently annotates the first 100
   (`ANNOTATION_SHEET_B_overlap100.xlsx`).
2. Blinding: no model labels in the sheets; `KEY_model_verdicts.csv` is opened only after both are complete.
3. Definitions are shown only where the source paper is CC BY / CC0 (licence rule); other definitions are not shown.

## Analysis (fixed in advance)
- Reviewer A over 500 rows: share EXACT / BROADER / NARROWER / RELATED / WRONG with 95% Wilson intervals; share
  TERM_IS_CONCEPT = N; TYPE_CORRECT = Y; DEFINITION labels over rows with a definition.
- Agreement A vs B on the 100 overlap rows: observed agreement and Cohen's kappa for MAPPING (5 labels, and EXACT vs
  not).
- Agreement of the models' agreed label with reviewer A: confusion matrix and kappa; and among rows the models
  called EXACT, the share the reviewer calls EXACT.
- Reported as a manual review of a random sample of accepted mappings, not accuracy of all mappings or of the CDM.

## Revision before annotation (2026-11-09)
The sheets were rebuilt before anyone annotated (`human_spotcheck_mappings_revise.py`): the same 500 rows, with
columns added from pipeline outputs (taxonomy from `taxonomy_annotation`, counts from `term_mention`, extraction
models) and the ontology's own definition of each mapped concept (OLS4 / BioPortal / UMLS / NCBI Taxonomy, queried
by concept id only). The v1 hashes are kept in `PREREGISTRATION_v1.sha256`.

## Integrity
`PREREGISTRATION.sha256` holds the SHA-256 of this protocol, the guide, `sample.csv`, both blank sheets and the key,
written when the sample was drawn, before any annotation.
