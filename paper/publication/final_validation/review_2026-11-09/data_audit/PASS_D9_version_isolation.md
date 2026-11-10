# PASS D9 — Version isolation: the 444 / 452 / 453 paper universes (and their DBs)

Date: 2026-11-09. Targets compared (all read-only, `mode=ro&immutable=1` +
`PRAGMA query_only=ON` for DBs):

1. `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` — current frozen CDM ("453 universe")
2. `releases/frozen_output/03_common_data_model/database/microbiome_cdm.db` — v2-era shipped CDM
3. `paper/_multi_ner_runs/cdm_output/microbiome_cdm.db` — the documented **444-paper** extraction build behind the manuscript's totals
4. `releases/frozen_output/01_corpus/data/*.jsonl` — HMCV2 2.1.0 extraction build
5. `releases/data_catalogue_v3/3.1.1/records/catalogue_records.jsonl` — catalogue source
6. `pipelines/corpus_v2/releases/2.2.0/` — corpus layer (reference docs)

No paper text read (id/count/category columns only). Result: **10 checks, all
PASS; 0 discrepancies.** The universes are cleanly isolated and every
cross-build number ties to its own denominator.

## 1. The three Universes, measured

| universe | artifact | papers | headline counts |
|---|---|---|---|
| **453 (CDM 3.0.3)** | 3.0.3 DB | paper 453 / section 4,006 / term_mention 2,505,684 across **453** papers | dataset 2,976 / data_asset 1,992 / cohort 7,085 / sample 7,530 / assay 8,545 / claim 45,667 (24,272 catalogue_v3_1 + 21,395 corpus_stage52) |
| **453-marc (v2 shipped CDM)** | frozen_output 03 DB | projects **453** | entities 110,981 / relationships 24,910 / edge_evidence 337,829 / entity_project_mentions 3,523,531 |
| **444 (manuscript build)** | `paper/_multi_ner_runs/cdm_output/microbiome_cdm.db` | projects **444** | entities 113,517 / relationships 858,145 / entity_project_mentions 73,632 |

The 444 build is **present and confirmed** — contrary to frozen_output's
05_evidence README L15 ("no longer in this bundle": true, it was moved out of
the *bundle*, but it survives in `paper/_multi_ner_runs/`).

## 2. Non-interchangeable entity counts — all documented

* Manuscript's **34,818** entities come from the **444 build** (05_evidence
  README L3–L8: "441 of the 452 corpus papers, plus HMPAPER_000372 … plus 2
  accessions outside the corpus; stated explicitly in Abstract, §3.2, Table 8").
* HMCV2 2.1.0 `entities.jsonl` = **37,907** — a different, later build; README
  L9–L11 says exactly this.
* Working 444 DB raw entities = 113,517 (multi-NER union rows; a different
  denominator again — see DATA_SEMANTICS.md "cite the number for the state you
  mean").
* All three observed values recorded with sources; none conflated.

## 3. Inside 3.0.3: per-table paper coverage is data absence, not loss

| table | rows | distinct papers | missing from 453 |
|---|---:|---:|---|
| claim (all) | 45,667 | 451 | HMPAPER_000075, HMPAPER_000372 |
| — catalogue_v3_1 | 24,272 | 451 | same 2 |
| — corpus_stage52 | 21,395 | 383 | (only 383 papers produced findings; ties findings.jsonl 21,395 exactly) |
| dataset | 2,976 | 451 | HMPAPER_000172, HMPAPER_000378 |
| data_asset | 1,992 | 417 | — |
| cohort | 7,085 | 450 | — |
| sample | 7,530 | 443 | — |
| assay | 8,545 | 439 | — |

* The four absent papers are all in corpus_v2 2.2.0's
  `papers_without_eligible_sections` (49-paper list): 000075, 000372, 000378
  present; 000172 present.
* Catalogue side agrees: 000075 and 000372 have **zero findings records**
  (just 1 dataset record each); the catalogue has 453 distinct papers overall,
  so no paper was dropped at load.
* 000172 and 000378 **do** have claims (159 / 50 records incl. 82 stage52 rows
  for 172) but genuinely zero catalogue dataset records.
* **0 orphans**: every claim/dataset paper_id ⊆ section papers (453).

## 4. Cross-build ties (independent routes, exact)

* 52,400 family total: DB census (2,976+1,992+7,085+7,530+8,545+24,272) =
  **52,400** = catalogue jsonl entity_type census (datasets 2,976 + data_assets
  1,992 + cohorts 7,085 + samples 7,530 + assays 8,545 + findings 24,272) —
  two independent routes agree exactly (re-confirms D7).
* `triple_mentions.jsonl` 34,416 == 3.0.3 `relation_evidence` 34,416;
  `canonical_triples.jsonl` 32,713 (ties D5 headline).
* `findings.jsonl` 21,395 == `claim[claim_source='corpus_stage52']` 21,395.

## 5. HMPAPER_000427 recovered sidecars — isolated by design

`triple_mentions_000427_recovered.jsonl` (33) and
`canonical_triples_000427_recovered.jsonl` (32) ship in a **disjoint id
namespace** (HMCV2-CT-RECOVERED-00001..00032 vs frozen HMCV2-CT-00001..32713,
0 collisions, per BUNDLE_INFO.json). They are **not merged into the frozen 2.2.0
counters** (explicitly documented) and are **absent from 3.0.3
relation_evidence** (0 rows for 427 — verified), and absent from the mainline
jsonls (0 HMPAPER_000427 lines in either). Root cause documented (duplicated
abstract → all sections over token cap → standalone re-run, max_tokens 8000).
Characterization: the 3.0.3 relation layer inherited the mainline only; the
sidecar remains a separate, clearly-labeled universe.

## 6. Char-count states (DATA_SEMANTICS.md §1) — verified present

26,874,831 (manifest) vs 26,871,587 (markdown bodies) vs 26,867,649
(terminology validator) — the nesting is documented with per-unit measurement
(Δ3,244 + Δ3,938); rule confirmed: cite the number for the state you mean.

## Checks

See `checks_D9.sql`. No paper text read; DB queries restricted to
id/enum/count columns and 4 specific paper_ids' row counts (never content).
