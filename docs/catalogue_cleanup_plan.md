# Data catalogue cleanup plan (v2 → v3)

Status (2026-10-30): **A–D DONE — release `releases/data_catalogue_v3/3.0.0/`
(jobs 28669168 + 28670577 linking, 28670578 finalize; QA PASS, manifest
verified).** **E done as model evaluation (LLM-as-judge, Claude Opus 5.5, not
human):** `outputs/results/catalogue_v3_validation/EVALUATION_REPORT.md` —
strict precision 58.8% (53.8–63.5), usable 85.2%, link precision 68.5%; the
blank `validation_sample.csv` is kept for any later human check.
- **Phase A DONE** — `outputs/results/catalogue_v3_clean/` (`CLEAN_REPORT.md`).
- **Phase C** — `normalize_catalogue_vocab.py` + `src/configs/catalogue_vocab/vocab.yaml`
  reads the Phase B output → `outputs/results/catalogue_v3_vocab/` (the final v3 catalogue) (`VOCAB_REPORT.md`). Body-site ids
  (UBERON/CL) verified against EBI OLS (`ontology_id_check.json`); taxa linked
  to NCBI Taxonomy by exact name (cache `ncbi_taxon_cache.json`). Assay types,
  repositories and finding domains get controlled labels only — no OBI/re3data
  ids, which could not be verified.
- **Phase B** — `link_catalogue.py` + `catalogue_link_a40.sbatch` (in
  `src/scripts/vllm_termpop/`, next to the other launchers) → reads the Phase A
  output, writes `outputs/results/catalogue_v3_linked/`.
- **Phase D** — licences: `fetch_paper_licences.py` (Europe PMC; 445/453 found;
  quotes kept for 289 CC papers that allow excerpts, removed for 164 —
  no-derivatives or no open licence); QA: `qa_catalogue_v3.py` (10 fail-closed
  checks); freeze: `build_catalogue_release.py` → `releases/data_catalogue_v3/3.0.0/`.
- **Phase E** — `make_validation_sample.py make|score`: 400-record stratified
  sheet + reviewer guide in `outputs/results/catalogue_v3_validation/`; scoring
  needs two human curators.
- C, D3, E and the freeze run as one CPU job,
  `catalogue_finalize_v3.sbatch`, chained `--dependency=afterok:` on the
  linking job.

Pipeline: v2 → A `catalogue_v3_clean` → B `catalogue_v3_linked` (GPU) → C
`catalogue_v3_vocab` (final). B and C touch disjoint columns, so C runs last
to keep the GPU step off the NCBI-lookup critical path. Each step writes a new directory and never edits its input.

Corpus rule: everything is over the **453-paper** corpus. The cleaner aborts
unless `papers.csv`, the section texts and the records agree on 453 papers
(`--expected_papers`). HMPAPER_000372 has no extracted record and is covered
only by its corpus BioProject dataset.

Changes from the plan made while running Phase A: `direction` uses the
extraction vocabulary (`NO_ASSOCIATION`, not `NO_CHANGE`); samples are **not**
key-merged (no group label, so different groups looked identical) — exact
duplicates only; implausibly large counts are blanked, with the value kept in
`count_flag`.

## Files

| role | path | touched? |
|---|---|---|
| **Input** (v2, repaired, 60,424 records) | `outputs/results/catalogue_ner_v2/catalogue_records.jsonl` + `catalogue_{findings,assays,cohorts,samples,datasets,data_assets}.csv` | read-only |
| Paper metadata (BioProject, PMCID, licence) | `releases/data_catalogue/tables/papers.csv`, `pipelines/corpus_v2/data/papers.jsonl` | read-only |
| Section text (to re-locate evidence) | `pipelines/corpus_v2/data/sections.jsonl` | read-only |
| Frozen bundles | `releases/data_catalogue/`, `releases/frozen_output/02_data_catalogue/` | **not modified** (checksummed) |
| **New cleaning script** | `src/scripts/vllm_termpop/clean_catalogue.py` | new |
| New vocab tables | `src/configs/catalogue_vocab/*.yaml` | new |
| LLM linking pass (phase B) | `src/scripts/vllm_termpop/link_catalogue.py` + `src/scripts/slurm/catalogue_link_a40.sbatch` | new |
| QA | `src/scripts/vllm_termpop/qa_catalogue.py` (canonical copy of `releases/data_catalogue/scripts/qa_catalogue.py`) | extended |
| **Output** | `outputs/results/catalogue_v3_clean/` | new |
| Tests | `src/tests/test_clean_catalogue.py` | new |

Principle: **never delete a record silently.** Every fix either adds a flag
column or moves the row to a `_removed.jsonl` file with a reason, so every v2
record can be traced to its v3 outcome (`v3_status`: KEPT / MERGED_INTO:<id> /
REMOVED:<reason>).

## Issues → fixes

### Phase A — deterministic (CPU, no model; ~minutes)

| # | Issue (measured on 56,985 set) | Fix | New/changed columns |
|---|---|---|---|
| A1 | ~340 exact duplicate rows | Drop rows identical on (paper, entity, all fields, evidence); keep first | `v3_status` |
| A2 | Integer `0` used as "not extracted" in JSONL (e.g. `participant_count: 0`) | `0` → blank where the schema field is text, or where the evidence has no "0"/"zero" | — |
| A3 | Placeholder strings (`n/a`, `not stated`, `NOT_STATED`, `none`, …) | → blank; one canonical "not extracted" | — |
| A4 | Findings from Discussion / Intro / background (≈30%), 9% quote cited work | Tag from `section_path` + citation regex (`ref17-20`, `[12]`, `et al., 2019`) | `finding_source` = RESULT / ABSTRACT / DISCUSSION / BACKGROUND; `cites_other_work` (bool); `is_primary_finding` |
| A5 | `direction` inconsistent (`not_stated`, `n/a`, `''`, `decrease; increase`) | Normalise to INCREASE / DECREASE / NO_CHANGE / MIXED / NOT_STATED | `direction` |
| A6 | `direction` contradicts evidence (e.g. "not significantly different" → INCREASE) | Rule check: negation / non-significance cues vs direction; flag, don't overwrite | `direction_flag` |
| A7 | 30% of `repository_accession` not an accession ("Table S1", URLs) | Regex validate by accession type (PRJNA/PRJEB/SRR/ERR/GSE/MTBLS/Qiita/…); move non-IDs to `notes` | `accession_valid`, `accession_type` (recomputed) |
| A8 | Accessions missing (35% filled) | Add the paper's BioProject (100% in `papers.csv`) as a dataset row where none matches | `source = bioproject_link` |
| A9 | Implausible counts (1.28 billion, 1.6 M participants) | Flag `participant_count` > 50,000 or sample_count > 500,000 unless evidence contains the number; non-integers (23.2) → blank | `count_flag` |
| A10 | 18–29% evidence quotes not located | Re-locate with whitespace/hyphen/unicode-normalised fuzzy match against `sections.jsonl` (≥0.9 similarity) | `evidence_location`, `evidence_verified` |
| A11 | Repeated records within a paper (samples 53%, assays 43%, cohorts 28%) | Cluster on normalised key fields per paper; merge into one record, union the non-empty fields, keep all evidence | `merged_from` (list of v2 IDs) |

### Phase B — model-assisted (A40 + vLLM, Qwen3.5-4B; one request per paper)

| # | Issue | Fix |
|---|---|---|
| B1 | `dataset_id` / `cohort_id` / `assay_id` 0% filled | Per paper, give the model the paper's own extracted cohorts/samples/assays/datasets (IDs + labels) and ask it to assign each finding/sample/assay to them. IDs constrained to that paper's list; invalid IDs → blank. |
| B2 | Findings A4 couldn't classify (e.g. results restated in Discussion) | Same request: label each ambiguous finding own-result vs cited-background |
| B3 | Direction blank/flagged (A6) | Re-ask direction from evidence sentence only; accept only if evidence supports it |

Every model output is stored next to the deterministic value, not over it (`*_llm`
columns), with the run ID.

### Phase C — controlled vocabularies

| Field | Vocabulary | Ontology |
|---|---|---|
| `assay_type` | 16S amplicon, shotgun metagenomics, metatranscriptomics, qPCR, culture, metabolomics, ITS, … | OBI |
| `repository_name` | SRA, ENA, DDBJ, GEO, MG-RAST, Qiita, MetaboLights, GitHub, Zenodo, Figshare | re3data IDs |
| `body_site` | gut, oral, skin, vaginal, nasal, lung, … | UBERON |
| `sample_type` | extend the existing 13-material table | ENVO / OBI |
| `finding_domain` | taxonomic composition, alpha diversity, beta diversity, functional, metabolite, host phenotype | — |
| `taxon_or_feature` | match to NCBI Taxonomy where it is a taxon | NCBITaxon |

Original text is kept in `*_original`; unmapped values → `REVIEW` queue CSV.

### Phase D — licence and release

1. Per-paper licence from PMC OA metadata → `papers.license_name/url`.
2. For non-OA papers: replace `evidence_text` with location only (char span) in
   the public release; keep full text in an internal copy.
3. Extend `qa_catalogue.py` with checks for every issue above (dup rate,
   placeholder count, accession validity, link fill, located-evidence %).
4. Freeze `outputs/results/catalogue_v3_clean/` as release 3.0.0 with
   `MANIFEST.sha256`; one README with numbers generated from the manifest.

### Phase E — human validation (needs curators)

Stratified sample of ~400 records (findings over-sampled), two curators,
report precision per table + Cohen's κ; compare against the LLM judge to
calibrate it.

## Acceptance targets for v3

| metric | v2 now | target |
|---|---|---|
| exact duplicates | ~340 | 0 |
| placeholder cells | 188 + integer zeros | 0 |
| findings tagged with source | 0% | 100% |
| valid accessions among filled | 70% | ≥ 98% (rest moved to notes) |
| evidence located | 71–82% | ≥ 90% |
| findings linked to a cohort | 0% | ≥ 60% |
| implausible counts unflagged | some | 0 |

## Order

A (all) → QA → C → B → QA → D → E. Phase A and C need no GPU and can be done
and tested before the SLURM job for B.
