# Request to the project lead: narrow freeze exception for two public benchmarks

*2026-11-06. Internal decision memo, not manuscript text. Decision needed: approve, approve with changes, or decline.
The cut plan and the decision guide do not depend on the answer.*

## What is asked

Two benchmark runs on **public gold-standard test sets already on disk** (`data/benchmarks_ner/raw/`, checksummed in
`SHA256SUMS`), under the same rules as the approved S1000 run of 2026-11-05:

| | Run | Gold standard | Size |
|---|---|---|---|
| A | **Relation extraction**: our triple extractor (corpus stage 53 prompt, Qwen3.5-4B, as used for CDM 3.0.3) on BioRED test abstracts; and on BC5CDR chemical-induced-disease relations | BioRED test relations (`BioRED_Test.PubTator`); BC5CDR CID relations (`CDR_TestSet.PubTator.txt`) | 100 + 500 abstracts |
| B | **Concept normalisation**: our mapping layer (vocabulary candidates + guards + acceptance rule) on the gold mentions of both test sets; PubTator3 identifiers as the published baseline | BC5CDR MeSH IDs (chemicals, diseases); BioRED IDs (NCBI Gene, MeSH, NCBI Taxonomy, dbSNP / HGVS) | same abstracts |

## Why

- The manuscript's novelty includes a triple layer and a normalisation layer, yet neither has a task-level metric.
  Reviewers who know BC5CDR and BioRED know that both contain relation and identifier gold standards; "no gold
  standard / no baseline exists" would be false (review of 2026-11-06).
- Without the runs, the paper must say these evaluations were **out of scope under the 2026-11-02 validation freeze**.
  That wording is defensible and will be used unless this request is approved.

## Conditions proposed

1. **No production artefact changes.** CDM 3.0.3, terminology 1.0.1, catalogue 3.1.1 and all frozen validation results
   stay untouched. Outputs go only to new dated directories
   (`outputs/results/benchmark/re_benchmark_<date>/`, `nen_benchmark_<date>/`).
2. **Pre-registration.** Protocol, scoring code and metric definitions (pair-level and typed RE F1; NEN accuracy@1 on
   gold mentions, by type) fixed and hashed before any prediction is scored, as for BugSigDB and S1000.
3. **Same models and prompts as production.** The point is to measure the components that built the CDM, not to tune
   them. No prompt changes after seeing test results.
4. **Local models only.** No text sent to external model APIs. The PubTator3 baseline is fetched by PMID (public
   abstracts); no corpus text leaves the cluster.
5. **Reporting.** Results are benchmark performance on public abstracts, never corpus accuracy. They enter the claims
   register and the change record like every other result. Known limits stated with them: BioRED and BC5CDR relation
   types cover only a small share of the corpus pair types (4.9% of corpus triples fall in pair types any curated KG
   covers); abstracts differ from full-text sections; PubTator3 was trained on these corpora (in-domain).
6. **Stop rule.** If either run cannot reproduce the production configuration exactly (missing prompt version, model
   revision or mapping service snapshot), it is not run, and the manuscript keeps the freeze wording.

## Open questions for the lead

- Is the BC5CDR CID relation run wanted in addition to BioRED, or BioRED only?
- Normalisation depends on vocabulary services (OLS, BioPortal, UMLS) whose current answers may differ from the
  production snapshot. Accept current answers (disclosed), or restrict to the local vocabulary copies only?

## Decision

| Option | Consequence for the manuscript |
|---|---|
| Approve | Two pre-registered benchmark results; Limitations narrows to "corpus-level relation and normalisation accuracy not established" |
| Decline | Limitations: "Relation-extraction and normalisation benchmarks on BioRED and BC5CDR were out of scope under the validation freeze; gold standards exist" |
