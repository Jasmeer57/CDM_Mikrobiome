# Data catalogue

Assembled biomedical data catalogue over the 453-paper human-microbiome corpus:
**453 papers, 51,941 machine-extracted records** across six entity types, with the
corpus build and term taxonomy that produced them.

> **Status: machine-extracted, unverified.** Every row is a candidate for human
> curation. Read [Quality & limitations](#quality--limitations) before using it.

## Layout

```
data_catalogue/
├── tables/             the catalogue itself — one CSV per entity
│   ├── papers.csv          453 papers: identifiers, bibliographic metadata,
│   │                       BioProject, per-paper record counts, coverage
│   ├── datasets.csv        3,209 datasets
│   ├── data_assets.csv     2,143 files/accessions within datasets
│   ├── cohorts.csv         9,501 study populations
│   ├── samples.csv         8,421 sample groups
│   ├── assays.csv         12,060 assays / sequencing runs
│   └── findings.csv       16,607 reported findings
├── records/
│   └── catalogue_records.jsonl   row-level source of truth with provenance
├── terminology/
│   ├── terminology_dedup.csv         166,012 deduplicated terms (classification input)
│   ├── terminology_exact_dedup.csv   exact-duplicate collapse
│   ├── taxonomy/term_taxonomy_v1.{yaml,csv}   16 upper categories + 66 subcategories
│   └── catalogue_remapping.json      legacy → current table/column mapping
├── corpus_v2/          the 453-paper corpus build the extraction ran over
│   ├── data/                 papers.jsonl, sections.jsonl, segments.jsonl, …
│   ├── raw/                  original Entrez / Semantic Scholar API payloads
│   ├── validation/           per-paper and corpus-wide validation reports
│   └── releases/2.0.0/       frozen corpus release + MANIFEST.sha256
├── quality/
│   ├── quality_report.md        human-readable findings
│   ├── integrity_report.json    every check and its verdict
│   ├── summary.json             extraction run summary (raw)
│   ├── coverage.csv             per-section extraction status (4,006 rows)
│   ├── sample_type_normalization.json   vocabulary + rule counts
│   ├── sample_type_review_queue.csv     values deliberately not coerced
│   └── compendium_validation.*  agreement vs the 168K-samples paper ground truth
├── provenance/
│   ├── run.log                  full extraction log
│   └── vllm_server.log          model server log
├── scripts/            the code that produced this bundle
│   └── finalize_catalogue.sh     one-command rebuild of tables + QA + manifest
├── slurm/              the launchers that ran it
│   ├── catalogue_ner_a40.sbatch      stage 1 extraction (A40 + vLLM)
│   ├── taxonomy_pilot_a40.sbatch     stage 2 classification pilot
│   └── catalogue_finalize.sbatch     CPU re-assembly + QA
├── MANIFEST.sha256     checksum of every file
└── MANIFEST.json       counts, provenance, per-file hashes
```

## How it was built

| stage | what | where |
|---|---|---|
| 1 | Corpus assembly — metadata, sections, validation | `corpus_v2/` |
| 2 | Catalogue extraction — Qwen3.5-4B via vLLM, one request per (section × entity type) | `scripts/catalogue_ner.py` |
| 3 | Assembly + integrity checks | `scripts/build_papers_table.py`, `scripts/qa_catalogue.py` |
| 4 | Term inventory dedup + subject taxonomy (v1, not yet applied) | `terminology/` |
| 5 | Deterministic `sample_type` normalization + review queue | `scripts/normalize_sample_types.py` |

Extraction (stage 2) and classification of the term inventory against the
taxonomy (stage 4) are **separate stages with separate evaluation**. Stage 4 has
so far produced a *pilot* classification only; ambiguous terms are emitted as
`UNCERTAIN` and queued for review rather than forced into a category.

**Every section of every paper is extracted in full.** Sections over the context
limit are split at sentence boundaries so every character is processed exactly
once; a section that cannot be completed is reported incomplete rather than
partially extracted, and the run's overall verdict stays `REVIEW_REQUIRED` until
coverage is whole.

## How to read the tables

- `paper_id` (`HMPAPER_######`) is the join key to `papers.csv` and to
  everything in `corpus_v2/`.
- Primary keys are prefixed by entity: `HMDATA_…`, `HMASSET_…`, `HMCOHORT_…`,
  `HMSAMPLE_…`, `HMASSAY_…`, `HMFINDING_…`.
- Column order follows the authoritative schema,
  `template/data_catalogue/human_microbiome_data_catalogue.schema.json`.
  Three columns are appended beyond it: `evidence_text` (the model's supporting
  sentence), `evidence_location` (where it was found, with a character span when
  it could be re-located), and `paper_id` on `data_assets` (the asset template
  omits it).
- An empty cell means *not extracted*, not *absent in the paper*.

## Quality & limitations

Full detail in `quality/quality_report.md`; machine-readable in
`quality/integrity_report.json`.

- **Unverified.** No row has been human-reviewed. Model confidence is not
  correctness.
- **Coverage incomplete.** 3,241/4,006 sections extracted completely; 80.0% of
  corpus characters processed; 341 segments failed (context overflow; a
  recursive retry was scheduled). See `quality/coverage.csv`.
- **Cross-entity links are empty.** `dataset_id` / `cohort_id` / `assay_id`
  foreign keys are not populated by the model, so records link to their paper
  but not to each other. Do not join on them.
- **Evidence unlocated for some rows.** Where the quote could not be re-found in
  its section, it is kept but not counted as verified.
- **Free-text fields are heterogeneous** (e.g. `sample_type`: `stool` vs
  `fecal`). A deterministic normalization pass over `samples.sample_type` has
  already run: 2,724/8,421 (32.4%) rows now carry a controlled-vocabulary value
  from 13 materials + 6 environmental/non-material rules. The remaining values
  are **not** coerced — 5,697 rows are queued in
  `quality/sample_type_review_queue.csv`
  (populations, methods, molecules, communities and empty cells that must not be
  treated as specimen material). See `quality/sample_type_normalization.json`.

## Verify

```bash
sha256sum -c MANIFEST.sha256          # from inside data_catalogue/
python3 scripts/qa_catalogue.py       # re-run every integrity check
```

## Not in this bundle

`data/catalogue/terminology_raw.csv` (203 MB pre-dedup working file) is left in
place; its hash is recorded in `terminology/terminology_raw.csv.sha256`.
`corpus_v2/config/secrets.env` is deliberately excluded (API keys).
