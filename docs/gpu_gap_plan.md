# GPU execution plan — closing the CDM and catalogue gaps

Status: PLAN (2026-10-30). Nothing below has been run. Gap evidence:
`docs/template_gap_analysis.md`. Corpus: 453 papers throughout.

## Ground rules (apply to every stage)

- **Models on disk** (no downloads needed): Qwen/Qwen3.5-4B (the extractor),
  google/gemma-4-E4B-it-qat-w4a16-ct (different family — used for checking),
  Llama-3.1-8B-Instruct-AWQ (tie-breaker), all-MiniLM-L6-v2 (embeddings).
  **Extraction-type stages use Qwen; verification-type stages use Gemma**, so no
  model checks its own output.
- Same launcher pattern as `catalogue_link_a40.sbatch`: one A40, in-job vLLM,
  prompt-hash cache, resumable, `--dry_run`, 3-paper smoke test before every
  full run.
- **Never overwrite.** Model outputs go in `*_llm` columns or new records with
  `source = <stage>`; a deterministic acceptance rule decides what is promoted,
  and the original value is kept. Each stage writes a new directory.
- **Every proposed value needs an exact quote** that passes
  `text[char_start:char_end] == quote` (template rule 5) or it is rejected.
- **Fail closed:** a stage with failed batches or a paper count ≠ 453 does not
  feed the next stage (`afterok` chain).
- Measure, don't assume: G10 plus a re-score of the same 400-record sample
  (Claude Opus 5.5, LLM-as-judge) gives before/after precision.

## Stages

Request counts from the current data; time from observed A40 throughput
(~33 requests/min at ~10k-char prompts, 32-way parallel).

| ID | Gap closed (template) | Model | Unit of work | Requests | A40 time |
|---|---|---|---|---:|---:|
| **G1** | Missing-data vocabulary + sparse fields (M6, catalogue) | Qwen | per paper × field group (Methods + Data availability sections) | ~2,700 | ~3 h |
| **G2** | Paper fields: keywords, primary_research_domain, human_study_design, data availability (M1) | Qwen | per paper (abstract + methods head) | 453 | ~20 min |
| **G3** | Record verify-and-repair (types, field misuse, primary, direction) (M6/M7) | **Gemma** | 15 records/request with their source windows | ~3,700 | ~3–4 h |
| **G4** | Link repair; required `dataset_id` on assets (M6/M10) | Qwen | per paper, flagged items only | ~1,500 | ~1 h |
| **G5** | INTERVENTION entity (M6, PLANNED) | Qwen | 40 exposure strings/request | ~700 | ~30 min |
| **G6** | RELATION: link triple subject/object to canonical terms (M7, PLANNED) | MiniLM + Gemma | embed 32,713 triples' entities; Gemma adjudicates ambiguous | ~600 | ~40 min |
| **G7** | Crosswalk harmonization (L3→L2 69%, type agreement 16.8%) (M4/M5) | MiniLM + Gemma | embed 12,271 unmatched; adjudicate ~22,800 type conflicts, 50/request | ~700 | ~45 min |
| **G8** | Definition coverage (1,150 → corpus-wide) (M4) | Qwen | per section (`extract_definitions.py`, existing) | ~4,000 | ~3 h |
| **G9** | Mapping validity (38.9%) (M5) | Gemma | 30 kept mappings/request with term context | ~10,500 | ~6 h |
| **G10** | Full-census evaluation of v3.1 catalogue (M9 EVALUATION_RUN) | Gemma (existing `s11_evidence_judge`) | every record | ~55,000 items | ~5 h |

Total ≈ 23 GPU-hours on one A40; ~10 h wall-clock with two A40s.

### G1 — field completion with NOT_REPORTED
For each paper and each field group, the model gets the relevant sections and the
catalogue's current values, and returns for every field either
`{value, quote}` or `NOT_REPORTED` (with the sections it checked).
- Field groups: **assays** (platform, region, primers, extraction kit, pipeline,
  taxonomic DB); **cohorts** (country, participant count, age, sex, health
  status, inclusion/exclusion); **samples** (collection, storage, preservation,
  timepoint); **datasets** (repository, accession, availability, licence).
- Acceptance: a value fills an empty field only with an exact quote; it never
  replaces an extracted value (disagreement → `CONFLICTING` + both kept);
  `NOT_REPORTED` is written only if every candidate section was sent whole (no
  truncation).
- Compendium cross-fill (CPU, before G1): amplicon, kit, sample type and
  condition from `projects.csv`, tagged `source = compendium`.

### G2 — paper-level fields
Keywords (as stated by the paper only), primary research domain and human study
design from controlled lists in the template, data-availability status with
quote. Fills the five 0%-filled `papers` columns.

### G3 — verify-and-repair (the precision lever)
Targets the error classes found in the 400-record evaluation: non-records (table
rows, legends, methods text, reagents, figures as datasets), field misuse,
own-result vs cited, direction. Gemma returns per record:
`valid_type` (yes/no + reason), per-field `ok`/`fix` with quote, `primary`
YES/NO, `direction`. Acceptance: invalid → `v3_status = REMOVED:INVALID_<type>`
(kept in `_removed.jsonl`); field fixes only with a quote; when Gemma and the
current value disagree on direction/primary, Llama-3.1-8B breaks the tie, else
`CONFLICTING`.

### G4 — link repair
Re-run linking for (a) findings with `cites_other_work = YES` or source
BACKGROUND/DISCUSSION, (b) records with >1 linked id per field, (c) assets with
no `dataset_id`. Prompt v3: pick the single best id unless the text names a
comparison; cited results get NONE. Same id-validation as Phase B.

### G5 — INTERVENTION
Classify `comparison_or_exposure` and studies' exposure strings into a fixed list
(diet/fibre, probiotic, prebiotic, antibiotic, FMT, drug, surgery, vaccine,
lifestyle, infection, none), with the drug/compound name kept for a later
ChEBI/MeSH lookup (CPU, cached, verified ids only).

### G6 / G7 — relations and harmonization
MiniLM embeddings on GPU for candidate generation (top-5 canonical terms);
Gemma adjudicates only the candidates under the similarity threshold. Type
conflicts between L3 and L2 decided with term + two context sentences;
`UNRESOLVED` allowed.

### G8 — definitions
Run the existing `extract_definitions.py` over all 4,006 sections (it was
smoke-capped at 30 papers). Definitions must be source spans (SOURCE_DERIVED).

### G9 — mapping re-adjudication
For the 314,772 kept mappings, adjudicate canonical candidates only (~1 per term,
~165k) at 30/request with relation EXACT/BROADER/NARROWER/RELATED/REJECTED.
Never invents ids: Gemma can only accept, demote or reject an existing candidate.

### G10 — evaluation
Full-census Gemma judge on v3.1 (all records, same C1 rubric as v2 for
comparability) plus the 400-record Claude re-score. Report both, labelled as
model evaluations.

## Order and chaining

```
CPU prep:  C1 compendium samples/tags + publications table + compendium cross-fill
           ↓
GPU chain A (catalogue):  G2 → G1 → G3 → G4 → G5
           ↓ (CPU: vocab pass, exact-quote re-anchoring, QA, freeze v3.1.0)
           G10 evaluation
GPU chain B (CDM/terminology, independent of A):  G8 → G7 → G6 → G9
           ↓
CPU:  C2 build template-shaped CDM (M1–M10) from v3.1 + terminology + relations
      → QA → freeze CDM 3.0
```
Chains A and B can run on two A40s at the same time. Each arrow is an
`--dependency=afterok` job; a finalize job freezes each release only if QA passes.

## Acceptance targets

| Measure | Now | Target |
|---|---:|---:|
| Catalogue strict precision (400-sample, Claude) | 58.8% | ≥ 75% |
| Catalogue link precision | 68.5% | ≥ 80% |
| Fields holding a value or a missing-data code | blank-only | 100% of G1 fields |
| Papers columns filled (keywords, domain, design, availability) | 0% | ≥ 90% (or NOT_REPORTED) |
| Assets with `dataset_id` | 92.8% | 100% (or NOT_APPLICABLE) |
| Template entities present as DB tables | 0 of 34 | all POPULATED or PARTIAL with reason |
| Triples linked to canonical terms | 0% | ≥ 70% |
| Definitions | 1,150 | corpus-wide |

## Not GPU (still needed)

- C3 accession verification against NCBI/ENA (login node, network).
- C4 ontology hierarchy for the 14 types + external class mappings.
- Human review (template rule 3: only humans set ACCEPTED). LLM evaluations are
  reported as such.

## Files to be written

`src/scripts/vllm_termpop/`: `complete_fields.py` (G1/G2),
`verify_repair_catalogue.py` (G3), `link_catalogue.py` v3 prompt (G4),
`classify_interventions.py` (G5), `link_triples.py` (G6), `harmonize_types.py`
(G7), `adjudicate_mappings.py` (G9); one sbatch per stage and
`submit_gap_chain.sh` (chains A and B with afterok). G8 and G10 reuse existing
scripts.

## Run log (2026-10-31)

- Chain A/B ran on up to 8 A40 + 4 A100; every GPU stage finished with 0 failed requests.
- G1 acceptance tightened after a sample audit (affiliation countries, persons-as-sample-count,
  vague storage text); a field with an unverified model proposal is left blank, never NOT_REPORTED.
- The first v3.1 finalize **failed the QA gate** (links to G3-removed records, placeholders and
  text counts from G3 fixes); finalize now repairs these deterministically and logs each change.
- `releases/data_catalogue_v3/3.1.0` is **superseded by 3.1.1**: 3.1.0's placeholder repair also
  blanked bookkeeping columns (`direction_original`, `finding_source`, `direction_llm`). 3.1.1 limits
  the repair to data fields (11 values). 3.1.0 is kept unmodified (frozen).
- DeepSeek-R1-Distill-Qwen-7B review (terms, mappings, definitions, triples) runs as
  `deepseek_review.py` with the AWQ 4-bit build (vLLM 0.32 cannot load the unsloth bnb-4bit build);
  outputs are new files in `outputs/results/deepseek_review/`.
- **CDM 3.0.1** (`releases/cdm_v3/3.0.1`, supersedes 3.0.0, which is kept frozen): `term_mention` keyed by
  mention_id|extraction_model (2,505,684 rows; 3.0.0 lost 557k rows of competing models' mentions);
  `term_concept_map` keyed by `mapping_row_id` (331,394 rows; upstream `mapping_id` missing on 11,477, shared on
  7,603; reviews now attach on mapping_id + term_id + concept_id); flags for rows pointing at removed/unknown
  terms; `evidence_anchor_status` + exact `evidence_span` on catalogue tables; `load_audit`; QA
  (`qa_cdm_v3.py`) PASS. Known upstream issue: ~6% of terminology mention / definition offsets are shifted by one
  character (terminology 1.0.0).
- **Terminology 1.0.1** (`releases/terminology/1.0.1`): mention/definition offsets corrected in 75 shifted sections
  (156,884 mentions, 63 definitions; 85 unanchored); `canonical_term_id` (null on every 1.0.0 mention) linked by
  term_norm for 2,198,809 of 2,505,735 mentions.
- **G11/G11B taxonomy** (Qwen + Gemma, 8 A40, 0 failed): of 162,409 terms 22,590 agree on subcategory and 15,150 on
  category only (37,740 classified, 23%); 58,996 both UNCERTAIN; 54,979 one model only; 10,694 conflicting.
- **CDM 3.0.2** (`releases/cdm_v3/3.0.2`, supersedes 3.0.1): terminology 1.0.1 + taxonomy; QA PASS; only HUMAN_REVIEW empty.
