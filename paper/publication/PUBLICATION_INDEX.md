# Publication index — Microbiome-CDM

**Status (2026-11-02):** development frozen; publication execution phase.

**Validation decision:** no human annotation will be performed. Validation is computational only; the decision matrix and its limits are in `final_validation/MASTER_VALIDATION_REPORT.md`.

**Rule:** every number in the manuscript must trace to a file below and to `final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (80 / 80 numeric claims recompute). Public-availability statements may be added only once they exist.

## Frozen inputs and releases

| Item | Location | Fingerprint | Status |
|---|---|---|---|
| Corpus (453 papers, 4,006 sections) | `pipelines/corpus_v2/data/papers.jsonl`, `sections.jsonl` | sha256 `82b6ef13…` / `bc6d8199…`; 4,006 / 4,006 section hashes verified | frozen |
| Terminology 1.0.1 | `releases/terminology/1.0.1/` | manifest sha256 `2ddc5706…` (23 files) | frozen |
| Data catalogue 3.1.1 | `releases/data_catalogue_v3/3.1.1/` | manifest sha256 `671b672b…` (45 files) | frozen |
| CDM 3.0.2 (historical) | `releases/cdm_v3/3.0.2/` | manifest verified unchanged | frozen |
| **CDM 3.0.3 (current)** | `releases/cdm_v3/3.0.3/` | manifest sha256 `9e71d509…` (36 files); read-only | frozen 2026-11-02; promoted from `outputs/results/cdm_v3_3.0.3_rc1` (kept) by `src/scripts/cdm_remediation/promote_303.sh` |

## Evidence

| Evidence | Location | Status |
|---|---|---|
| Publication-readiness audit, claim tracing | `outputs/audit/2026-11-02/` (`CLAIMS_TO_EVIDENCE.csv`, `audit_facts.json`) | done |
| CDM 3.0.3 verification (preservation, reversibility, regression) | `releases/cdm_v3/3.0.3/remediation/VERIFICATION_303.json` | PASS |
| Data dictionary (866 columns), vocabularies | `releases/cdm_v3/3.0.3/remediation/` | generated; 644 definitions need the expert |
| CDM structural / provenance / interoperability validation | `outputs/human_validation/gate4_2026-11-02/CDM_VALIDATION/` | done (on 3.0.2); 3.0.3 results in `releases/cdm_v3/3.0.3/remediation/regression/` |
| Public NER benchmark (27 configurations) | `outputs/results/ner_fair_bench/FAIR_NER_BENCHMARK.md`, `fair_ner_metrics.json` | final |
| Corpus NER benchmark (26 configurations, external references) | `outputs/results/ner_corpus_bench/`; analysis `final_validation/BENCHMARK_FINAL_ANALYSIS.md` | final |
| **Final computational validation (Workstreams A–I)** | `paper/publication/final_validation/` (master report, 9 workstream reports, claims register, blockers) | done |
| Catalogue evidence assessment (deterministic + two model judges) | `final_validation/CATALOGUE_EVIDENCE_ASSESSMENT.md`, `evidence_judge/` (incl. `BOTH_JUDGES_FAIL.csv` worklist) | done; model judgements, not accuracy |
| Human validation (500 items) | `outputs/human_validation/gate4_2026-11-02/` | **not performed (by decision)**; package kept as a computational audit sample only |
| Source-first coverage (accessions, platforms, 16S regions) | `final_validation/SOURCE_FIRST_COVERAGE_REPORT.md` | done (regex extractor; coverage, not recall) |
| Independent CDM review | `releases/cdm_v3/3.0.3/remediation/EXPERT_REVIEW_PACKAGE.md` | **reviewer not yet recruited** |
| Research query demonstrations | `final_validation/CDM_USABILITY_REPORT.md`, `queries/QUERY_COMPARISON.csv` | 8 queries compared with keyword retrieval |
| Rights matrix | `paper/publication/rights/` | proposal; 179 papers need legal confirmation |
| Manuscript drafts | `paper/publication/manuscript_draft/` | Introduction, Methods + Resource, Results, Discussion drafted (Results/Discussion v0.1–0.2); figure plan; references and contribution bullets still to do |

## Validation freeze (2026-11-02)

Validation results are frozen and read-only: `final_validation/FINAL_VALIDATION_MANIFEST.sha256` (119 files, incl. benchmark outputs). Do not revise them to improve presentation; corrections go in a new dated file plus `final_validation/CHANGE_RECORD.md`. Living files: claims register, number audit (`MANUSCRIPT_NUMBER_AUDIT.csv`, 279 numbers, 0 untraced), blockers.

## Next steps, in order

1. ~~Freeze validation results~~ (done).
2. Complete the manuscript: references (`manuscript_draft/REFERENCES_NEEDED.md`; none chosen yet), then re-run `claims_register.py` and `manuscript_number_audit.py` after every edit.
3. Use `evidence_judge/BOTH_JUDGES_FAIL.csv` (2,023 values) to prioritise a *future* catalogue release; 3.1.1 stays unchanged; no judge verdict is definitive.
4. Independent CDM expert review (B5); the most important remaining scientific review.
5. Rights: legal/library review of 179 papers → licence → redacted build → verify → DOI (B1–B4).
6. Submit, after confirming the target journal's data-availability requirements.

No further extraction, models or validation pipelines.

## Submission readiness (2026-11-02)

`submission_readiness/`: B15 decision (closed, false positive); verified references (41 / 41) with a reference-to-claim mapping; CDM expert review package; legal/library review package (179 papers); final manuscript QA; submission checklist. New blockers B16–B20 (code availability, journal/article type, reviewer data access, 6 papers without DOI or title, pre-submission enquiry).

## Claims that must NOT appear yet

- Any accuracy, recall or "validated" claim. No human annotation exists; the 92.2% (Gemma) and 59% (Claude) figures are model judgements on earlier releases. Model-judge agreement (κ 0.28) is not inter-annotator agreement.
- "LLMs beat NLP methods". The benchmark does not support it.
- The DeepSeek-V4-Flash judging (`manuscript_draft/04_supplement_llm_judged_precision.md`, 2026-11-03) described as "expert review", "expert validation" or accuracy. It is a model-based quality screen; the human CDM expert review (B5) is still outstanding.
- "Independent judges confirmed the catalogue", "most values are consistent with their evidence", "semantically coherent", "ready for adoption", "legally cleared", or source-first figures described as recall/coverage.
- "Publicly available" or a DOI. The rights review and the redacted build come first.
- "Scientifically validated CDM". The expert review is outstanding.
- Any results on the 168k compendium samples themselves. Only "156,330 of 168,464 compendium samples belong to the corpus BioProjects" is allowed.
- Claim F's 100%, which is circular.
