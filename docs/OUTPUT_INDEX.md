# Output index — data products

Every major artifact this repository produces, with its producer, identity,
status, and intended consumer. **Status describes processing state, never
scientific validity.** Nothing here is human-verified unless it says so, and
nothing currently does.

Status vocabulary:

| Status | Meaning |
|---|---|
| `CURRENT` | the artifact downstream work should read |
| `FROZEN` | immutable, checksummed, do not edit — new work means a new version |
| `SUPERSEDED` | replaced by a later version; kept for provenance only |
| `REVIEW_REQUIRED` | machine output with known gaps; not fit for a scientific claim |
| `UNVERIFIED` | no human review at any stage |
| `PILOT` | small exploratory run, not a corpus-wide product |

---

## 1. Corpus releases — `corpus_v2/releases/`

| Product | Path | Producer | Build | Version | Status | Consumer |
|---|---|---|---|---|---|---|
| Corpus release | `corpus_v2/releases/2.2.0/` | `corpus_v2/slurm/submit_all.sh` (stages 10→70) | generated `2026-10-25T15:51:35Z` | 2.2.0 | **CURRENT** | corpus NER, terminology, catalogue work |
| Corpus release | `corpus_v2/releases/2.1.0/` | same | — | 2.1.0 | SUPERSEDED | provenance |
| Corpus release | `corpus_v2/releases/2.0.0/` | same | — | 2.0.0 | SUPERSEDED | embedded in the catalogue |

`2.2.0`: 453 papers (447 canonical, 6 duplicate-excluded), 4,006 sections,
4,006 segments, **26,874,831 characters**, 7,909,432 tokens.
Validation `{REVIEW_REQUIRED 392, COMPLETE 46, PARTIAL 15}`.
Integrity: `MANIFEST.sha256`, 42 files, verified.

## 2. Segmented Markdown — `segmented_sections_markdown/`

| Field | Value |
|---|---|
| Producer | `scripts/segment_all_to_markdown.py` |
| Inputs | `data/corpus/records/HMPAPER_*.json` + `data/corpus/text/HMPAPER_*.txt` |
| Size | 453 `.md` files, 4,006 section units, **26,871,587 characters** |
| Status | FROZEN input (derived, but treated as fixed) |
| Consumer | section-level NER, terminology pipeline |

0 uncovered chars, 8 papers / 13 warnings (`_conversion_report.json`).
453 of the 4,006 units are zero-character `front/(preamble)` placeholders —
`NOT_APPLICABLE`, not failures.

## 3. Canonical corpus records — `data/corpus/`

| Field | Value |
|---|---|
| Contents | `records/`, `text/` (453 each), `corpus_tracking.csv`, `id_map.csv`, `annotations/findings.csv` |
| Findings | 1,485 over 31 papers, **all `verification_status=pending`** |
| Status | UNVERIFIED |
| Consumer | corpus_v2 ingest |

## 4. Data catalogue — `data_catalogue/`

| Field | Value |
|---|---|
| Producer | `scripts/vllm_termpop/catalogue_ner.py` → `catalogue_finalize.sbatch` |
| Generated | `2026-10-23T20:30:51+00:00` |
| Size | **453 papers / 56,985 records** — findings 21,439, assays 12,116, cohorts 9,575, samples 8,484, datasets 3,228, data_assets 2,143 |
| Coverage | 3,443/4,006 sections, 90.857% of chars, 127 failed segments |
| Status | **REVIEW_REQUIRED** (checksummed bundle, 1,003 files, 1003/1003 verified) |
| Consumer | terminology (L1), catalogue review |

Embeds a `corpus_v2/` tree pinned at **2.0.0**. All rows machine-extracted and
unverified. Do not edit — corrections belong in a new versioned catalogue.

## 5. Terminology build — `results/terminology_v1/`

| Field | Value |
|---|---|
| Producer | `scripts/slurm/termpipe_v1.sbatch` (T1 → T5) |
| Job | **28619916** (pipeline `v1`, manifest `1.0.0`) |
| Generated | `2026-10-25T17:45:38` |
| Size | 2,505,735 mentions · 165,991 canonical terms · 1,150 definitions · 334,231 mappings |
| Status | UNVERIFIED; `auto_accepted = 0`; calibration **NOT_CALIBRATED** |
| Consumer | frozen release, crosswalk, CV/OMOP linking |

Validation `COMPLETE` **structurally** (453/453 papers, 3,553 sections, 100%
mentions resolved to a section). Structural completeness ≠ accuracy.

## 6. Frozen terminology release — `releases/terminology/1.0.0/`

| Field | Value |
|---|---|
| Origin | byte-identical copy of build 28619916 |
| Files | 22 (+ `MANIFEST.sha256`), `chmod -R a-w` |
| Manifest digest | `a5c1ae90393008d83b85dc93752fc74a2d950996e9cbe00915e6af9151cb2b48` |
| Quarantine | `calibration_v0_pre_fix/` — drawn against 334,275 rows, superseded |
| Status | **FROZEN** |
| Consumer | citation, reproduction, crosswalk |

Gate report: `releases/terminology/release_gate_report.json` (8 PASS, 1 expected
FAIL — see `scripts/release_gates/README.md`).

## 7. Terminology crosswalk — `docs/crosswalk/`

| Field | Value |
|---|---|
| Producer | `scripts/build_terminology_crosswalk.py` |
| Inputs | L1 dedup, L2 canonical, L3 corpus inventory (2.2.0) |
| Outputs | `inventory_to_canonical.csv` (39,869 rows), `dedup_to_canonical.csv` (166,012), `_collisions.json` (19 groups), `_summary.json`, `_sources.json` |
| Status | UNVERIFIED analysis |
| Consumer | reviewers reconciling the three inventories |

## 8. Controlled-vocabulary linking

| Product | Path | Producer | Build | Size | Status |
|---|---|---|---|---|---|
| CV linking | `results/cv_linking/` | `cv_link_terms.py` + `cv_link.sbatch` | `2026-10-24T01:46:43` | 71,538 typed pairs, 35,063 reused, 36,475 net-new | UNVERIFIED |
| OMOP linking | `results/omop_linking/` | `omop_link_terms.py` + `omop_link.sbatch` | `2026-10-23T23:45:38` | 9,615/71,538 (13.44%), 6,713 standard concepts, 21,881 links | UNVERIFIED, **separate view** |
| MeSH gazetteer NER | `results/mesh_ner/` | `mesh_gazetteer_ner.py` + `mesh_ner.sbatch` | `2026-10-23T23:45:44`, 52 s | 248,088 rows / 8,652 distinct terms | UNVERIFIED |

OMOP is deliberately **not** merged into CV canonicals and **not** added to
`VOCAB_PRIORITY`. Its `confidence` is fixed at 1.0 because it is exact-match
only — that is a matching property, not a correctness score.

## 9. LLM NER outputs

| Product | Path | Producer | Size | Status |
|---|---|---|---|---|
| Qwen vLLM full-body NER | `results/llm_ner_body/` | `qwen_sections_vllm.py` (`Qwen/Qwen3.5-4B`, prompt `cdm-ner-v1-vllm-fullsec`) | 366,123 rows, 2,817 sections, 4,051 segments, 0 failed | UNVERIFIED |
| Qwen Ollama section NER (historical) | `zenodo_v1/qwen_sections_ner/` | `qwen3.5:4b` | 2,601 sections, 186,024 located rows | UNVERIFIED, historical |

## 10. Zenodo artifacts — `zenodo_v1/`

| Field | Value |
|---|---|
| Created | `2026-10-20T17:10:22+02:00` |
| Producer jobs | SLURM **418086** (CPU ensemble), **418089** (Qwen 3.5:4b) |
| Contents | CPU ensemble NER (1,705,501 rows, 7 models), Qwen section NER, sha256 `MANIFEST_v1.txt` |
| Status | **FROZEN export** — do not modify in place |

## 11. Taxonomy — `data_catalogue/terminology/taxonomy/`

`term_taxonomy_v1.{yaml,csv}` — 16 upper + 66 subcategories, plus reserved
`UNCERTAIN`. `status: DRAFT`. Classifier pilot applied to 500 terms only; a
full-table pass has **not** been run.

## 12. External reference sources — `data/reference_kg/`

Downloaded, checksummed, read-only third-party data used to measure this
repository against sources it did not produce. Each source has its own
subdirectory with `SHA256SUMS` and `DOWNLOADED_AT`.

| Product | Path | Producer | Size | Status |
|---|---|---|---|---|
| Source decisions, licences, taxonomy-cell grammar | `data/reference_kg/SOURCES.md` | manual, licence read in-band per source | 8 sections, 2.1–2.11 accepted / rejected table | reference |
| **BugSigDB** (human gold standard) | `data/reference_kg/raw/bugsigdb/full_dump.csv` | BugSigDB dump `2026-11-03T07:58Z`, sha256 `b106dafa…ce81c` | 16,662 rows × 57 cols, 37 MB, **CC BY 4.0** | **FROZEN input** |
| NCBI Taxonomy | `data/reference_kg/raw/{nodes,merged,delnodes}.dmp` | NCBI taxdump | `merged` 102,666, `delnodes` 774,949 | FROZEN input |
| OBO ontologies | `data/reference_kg/raw/obo/*.obo` | 12 current release downloads, hashed | 209 MB | FROZEN input |
| MeSH 2026 | `data/reference_kg/raw/mesh/` | `desc2026.xml` + `supp2026.xml` | 31,110 + 324,046 records | FROZEN input |
| Comparators | `data/reference_kg/raw/{gutmd_disorder,gmrepo,midred,dimbre,microbiorel,minerva}` + `raw/{CTD_*.tsv.gz,disbiome_experiment.json}` | per-source download scripts in `outputs/scratch/reference_kg_download/` | see §2 of `SOURCES.md` | profiling only |
| **BugSigDB validation report** | `docs/reports/bugsigdb_validation/bugsigdb_validation.md` | `compare_bugsigdb_v5.py` → `build_validation_report.py` | 2,060 reporting units / 47 papers | **UNVERIFIED, mixed** |

**Same-paper overlap, which is the only test that makes a source able to
validate this build:** BugSigDB 47 of 453 studies; gutMDisorder v3 14; GMrepo 33
(CC BY-NC); DiMB-RE 2; MiDRED 1; MicrobioRel 0; Disbiome and MINERVA have no
paper linkage at all. Only BugSigDB supports a per-finding comparison.

Result reported there, with its denominator: **directional agreement 28/28
(Wilson 95% CI 0.879–1.000) on 1.36% of comparable units, across 10 of the 47
papers**; permissive-rule upper bound 64/78 = 82.1% [0.721, 0.890] quoted beside
it; curated-taxon recall 361/1,517 = 23.8% [0.217, 0.260]. 28/28 is a selected
subset and must never be quoted as corpus-wide. Identifier currency: 24,446 of
24,481 cited OBO identifiers resolve against current releases (99.86%),
NCBITaxon 100% after `merged.dmp` remap.

## 13. Release control

| Artifact | Purpose |
|---|---|
| `releases/RELEASES.md` | append-only ledger; manifest digest is the integrity control |
| `releases/terminology/release_gate_report.json` | latest gate run |
| `corpus_v2/releases/release_gate_report.json` | corpus gate run |
| `logs/gates/data_catalogue_release_gate_report.json` | catalogue gate run |
| `logs/p0_summary.md` | freeze acceptance record |

## What is missing on purpose

No precision, recall, or F1 figure appears anywhere for the **453-paper build**,
because no human-labelled reference sample covers it. Model-to-model agreement
and offset verification are recorded in their own documents and are **not**
accuracy.

The BugSigDB comparison (§12) is the one place where external human curation is
involved, and it is deliberately narrow: 47 of 453 papers, 10 of those yielding a
strictly scorable unit, 1.36% of comparable units scored. It yields a concordance
measurement on that subset, not a precision/recall estimate for the build.
