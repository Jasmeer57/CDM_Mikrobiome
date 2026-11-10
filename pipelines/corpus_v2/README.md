# Corpus v2 — LLM-ready human-microbiome corpus (template-compliant)

Versioned corpus build over the 453 `HMPAPER_*` papers in
`../segmented_sections_markdown/`, following
`../template/human_microbiome_corpus_building_template.md` (§1–§9) and
`../template/corpus_template.json` (`schema_version 1.1.0`).

All compute runs through Slurm. Every stage refuses to run outside a Slurm job
(`common.require_slurm`, override only with `--allow-no-slurm` for debugging).

## Layout
```
config/      corpus.yaml (manifest, query, eligibility, LLM, resources)
             secrets.env (chmod 600; sourced by jobs, never written to the corpus)
schema/      paper, section, processing_event, validation (JSON Schema)
scripts/     stage10..stage70 (restartable, event-logged, tqdm progress)
slurm/       _env.sh, 10 sbatch wrappers, submit_all.sh (afterok chain)
data/        papers/sections/segments/llm_terms/validation_per_paper .jsonl
             corpus_tracking.csv (§2), curation_log.csv (§5), eligibility decisions
raw/         write-once API payloads (Entrez / Semantic Scholar)
checkpoints/ per-stage JSONL resume state (keyed by stable record id)
validation/  per-stage reports, artifact hashes, reconciliation
logs/        <stage>.log (tqdm mirrored line-by-line) + logs/slurm/*.out|err
releases/    <corpus_version>/ frozen bundle + MANIFEST.sha256
```

## Stages
| Stage | Script | Partition | What it proves |
|---|---|---|---|
| 10 | `stage10_ingest.py` | `intelsr_short` | exact source bytes hashed; UTF-8/NUL defects recorded; file set reconciled against `_conversion_report.json` |
| 20 | `stage20_metadata.py` | `intelsr_short` | Entrez + Semantic Scholar identifiers, title-matched (≥0.90) with per-field provenance |
| 21 | `stage21_bioproject_link.py` | `intelsr_short` | exact BioProject join to the 168000-samples bundle: DOI/PMID/PMCID/abstract by accession, not title guess; conflicts recorded |
| 30 | `stage30_dedup.py` | `intelsr_short` | duplicate groups via DOI/PMID/normalized title; canonical chosen deterministically; nothing deleted |
| 40 | `stage40_sectionize.py` | `intelsr_short` | SEGMENT→section reconstruction, hierarchy from numbered headings only, coverage vs conversion report |
| 45 | `stage45_section_validation.py` | `intelsr_short` | hashes recomputed from stored text; marker leakage/NUL/duplicate-block checks; token counts |
| 46 | `stage46_fulltext_crosscheck.py` | `intelsr_short` | independent check against original JATS XML: title, abstract, and every substantive section must be present; downgrade-only |
| 50 | `stage50_llm_enrich.py` | `mlgpu_short` (`gpu:a40:1`) | Qwen3.5-4B via in-job vLLM, thinking off, terms only in `llm_*` fields, truncation flagged |
| 51 | `stage51_studies_extract.py` | `mlgpu_short` (`gpu:a40:1`) | template §3G study metadata: compendium-deterministic > LLM > not_reported; conflicts recorded, deterministic kept |
| 52 | `stage52_findings_extract.py` | `mlgpu_short` (`gpu:a40:1`) | template §4 findings from Abstract/Results/Discussion: verbatim quotes, no invented statistics; zero-finding sections valid |
| 53 | `stage53_triples_extract.py` | `sgpu_short` (`gpu:a100:2`) | knowledge-triple *mentions* per section (79-predicate frozen schema): per-triple quote verification, unknown enums downgraded visibly (OTHER_RELATION/D25), one merge record per mention; sharded 2×A100, fail-closed `--merge` |
| 54 | `stage54_paper_summaries.py` | `sgpu_short` (`gpu:a100:2`, same job) | one summary per paper from Abstract+Results+Discussion; flagged `llm_generated_unverified_paraphrase`, vacuous (no eligible sections) via `unavailable_no_eligible_source_sections` |
| 55 | `stage55_findings_verify.py` | `intelsr_short` | deterministic quote recoverability (`verified_exact`/`verified_normalized`/`unresolved_not_in_source`); unresolved kept & flagged |
| 56 | `stage56_triples_canonicalize.py` + `entity_linker.py` | `intelsr_short` | canonical triples + entity registry + cross-paper evidence; linking cascade OMOP T0 exact / T1 rapidfuzz (≥95 lexical still needs embed confirm) / T2 MiniLM rerank (0.75–0.80 → `review_required`) / T3 Entrez→OLS→UMLS→BioPortal; every candidate recorded in `candidate_entity_mappings.jsonl`, budget-capped, downgrade-only |
| 60 | `stage60_validate.py` | `intelsr_short` | schema + cross-artifact reconciliation (papers↔sections↔segments↔LLM↔studies↔findings↔cross-check) |
| 70 | `stage70_finalize.py` | `intelsr_short` | frozen release: manifest, tracking table, studies.csv, findings_index.csv, curation log, terminology inventory, schemas, quality report, checksums |

## Run
```bash
cd ~/Microbiome-CDM/corpus_v2

bash slurm/submit_all.sh --dry-run    # inspect the chain
bash slurm/submit_all.sh              # submit 10→70 with afterok dependencies
bash slurm/submit_all.sh --from 40    # resume the chain at a stage

squeue -u $USER -o '%.10i %.14j %.10P %.10T %.10M %R'
tail -f logs/stage40_sectionize.log   # same lines as the tqdm bar
```

Resume: every stage reads `checkpoints/<stage>.jsonl` and skips completed
records. A killed or timed-out job can simply be resubmitted.

## Integrity model (why statuses are trustworthy)
- **Fail-closed gate** (`common.fail_closed`): `CRIT_*` failure → `FAILED`,
  `PART_*` → `PARTIAL`, `WARN_*` → `REVIEW_REQUIRED`. `COMPLETE` requires every
  check to pass and the evidence string is stored with the record.
- **Three separate questions**: `full_text_availability` (does text exist?) ≠
  `full_text_parse_status` (did we reconstruct it?) ≠ `full_text_completeness`
  (is it verified complete?). They are never derived from each other.
- **Original text is immutable**: `section_text_original` is verbatim;
  `section_text_cleaned` (with `cleaning_operations`) is a separate, documented
  field and is currently unused.
- **Known upstream defects are recorded, never repaired**: NUL bytes
  (`000120/000187/000240/000446`), sections skipped by the upstream converter
  (`000123/000138/000341`), and clamped-overlap warnings.
- **LLM output is namespaced**: `llm_*` keys carry model, prompt version and
  source text hash; a truncated response is `PARTIAL`, never silently accepted.
- **Reconciliation is exact**: section/segment character totals, section counts
  and LLM coverage must add up or the run is reported as inconsistent.
- **Independent verification**: stage 46 re-parses the original JATS XML for
  every paper that has one and downgrades completeness if the reconstructed
  text is missing a substantive section. PDF-only and local-text-only papers
  are recorded as `not_available`, never assumed complete.

## Release
`releases/<corpus_version>/` contains `corpus_manifest.json`, `corpus_tracking.csv`,
`curation_log.csv`, `quality_report.md`, `terminology_inventory.csv`,
`findings_index.csv` (explicitly empty — findings are not extracted in v2.0.0),
the data artifacts, and `MANIFEST.sha256`.

Schema validity is **not** scientific correctness: extracted terminology is
`extracted_unverified` until a human review pass is recorded.
