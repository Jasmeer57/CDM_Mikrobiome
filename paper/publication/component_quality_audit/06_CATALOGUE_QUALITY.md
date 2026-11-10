# Component F — Data Catalogue Quality

**Audited object:** all **52,400** catalogue records in CDM 3.0.3 — cohort 7,085 / sample 7,530 / assay 8,545 / dataset 2,976 / data_asset 1,992 / claim (catalogue half) 24,272 — plus the same 52,400 records as shipped in catalogue release 3.1.1 (`releases/data_catalogue_v3/3.1.1/tables/*.csv`), which is the only place several columns survive.
**Evidence base:** `diagnostics/results/d18_catalogue_quality.json`, `d06_value_grounding.json`, `d04_duplication.json`, `d19_cdm_schema_quality.json` *[corrected 2026-11-05: cited as `d19_cdm_shape.json`, a filename that does not exist; recorded as **CC-02** in `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md` §7]*; and six purpose-built probes — `cqa_catalogue_metrics.json` (row-level recount of every anchor and flag), `cqa_gap_evidence_grounding.json`, `cqa_catalogue_provenance_gap.json`, `cqa_catalogue_redaction{,2,3}.json`, `cqa_storage_signloss.json`; plus `paper/publication/final_validation/evidence_judge/` and catalogue 3.1.1 `provenance/QA_REPORT.md` + `scripts/qa_catalogue_v3.py`.
**Independence:** every headline number below is recomputed over all 52,400 rows against `section.section_text_original` (hash-verified, keyed on `(paper_id, section_id_original)`). The release's own `QA_REPORT.md` figures were **re-derived from its published formula** and then compared to the recount; they disagree (see CQA-F-04). No prior report supplied any of these quantities.

> **Measurement discipline.** The corpus has **no human-annotated gold standard** for catalogue records: `human_review` = 0 rows, `review_status` is `UNVERIFIED` on 100% of all six tables, and `verification_status` is either absent, single-valued, or 100% blank. Nothing in this report is called precision, recall, accuracy or completeness. Two model judges exist; they are treated below strictly as a *model-behaviour measurement*, never as an accuracy filter and never as annotation (see §4.3).

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **ADEQUATE** | 52,400 rows, 6/6 tables with PostgreSQL-style natural keys, **0 duplicate PK groups / 0 redundant rows** in all six (`cqa_catalogue_metrics.json:pk_uniqueness`); CSV↔DB row counts match exactly 6/6 (`csv_db_count_agreement`); semicolon parent lists (`sample.cohort_id`, `sample.dataset_id`, `assay.dataset_id`, `data_asset.dataset_id`) resolve **100%** on every part (D18) | PK duplication 0.00%; parent-list resolution 100%; but 190 duplicate dataset groups / 437 redundant rows on real accession keys (36.54%) and 1,092 dataset orphans (D02) | No FOREIGN KEY constraints exist in the DB (D19); the semicolon list is a schema-shape defect with no junction table, so referential closure cannot be enforced | High |
| Provenance | **CRITICAL** | 18,502 LICENCE-redacted cells ship as full text in the CDM (`cqa_catalogue_redaction3.json`, 5,328,140 chars restored); **15,402 `field_sources` entries lost across 7,640 records** because assay/data_asset/claim have no provenance columns (`cqa_catalogue_provenance_gap.json`); `evidence_redacted`, `intervention_category`, `intervention_agent` dropped on all six tables | Provenance preserved 59,993/75,395 entries = 79.6%; redaction flag present in CDM **0 columns** | `extraction_run_id`/`extraction_model` **are** populated (100% on cohort/sample/assay, 95.2% on dataset), so record-level provenance is intact; it is *cell-level* provenance that is lost | High |
| Internal consistency | **WEAK** | Two evidence flags disagree on **802/52,400 rows (1.53%)**: `evidence_verified=0` yet anchor located on **698**, `evidence_verified=1` yet anchor NOT located on **104**; release QA_REPORT's `evidence_located_pct` sits **~6.9 points above** the same quantity recomputed from the same rows; `claim` carries **two disjoint evidence vocabularies**, each 100% NULL on the other half | Flag contradiction rate 1.53%; QA-vs-recount gap 6.9 pts; 1,588 rows uncounted by the release formula | The `evidence_verified` flag is internally consistent with itself (`verified=1` ∧ `NOT_FOUND` = 0, ∧ empty `evidence_text` = 0) — the contradiction is *between* flag and anchor, not within the flag | High |
| Evidence support | **WEAK** | Recount over all 52,400: offsets-verbatim (EXACT+WHITESPACE) **38,295 = 73.08%**; project-verbatim verb set (+NORMALISED+RELOCATED) **46,233 = 88.23%**; content-located (+FUZZY) **50,412 = 96.21%**; NOT_FOUND **2,392 = 4.56%**; NO_QUOTE 190; UNANCHORED 1,798 | Strict set (EXACT/NORMALISED/FUZZY\*/RELOCATED, WHITESPACE excluded) **20,029 = 38.22%**; WHITESPACE-only **30,383 = 57.98%** | Locating a string does not establish that the string *supports the value*; that is measured separately in §4.2 and is much lower for several columns | High |
| External concordance | **NOT EVALUATED** | No external catalogue reference exists to compare against. Accession values could in principle be resolved against repositories, but no such resolution was performed for this audit and the release records none (`dataset.link_status` = `NO_CANDIDATES` on 100% of 2,976 rows) | Concordance measurable: **no** | Doi/accession validity is *format*-checked in the clean layer (`dataset_accessions_valid_pct` 100.0 post-clean) but never *resolved* against the registry | High |
| Semantic quality | **WEAK** | `assay.sequencing_platform`: **216 rows are not sequencing platforms** (LC-MS, plate readers, LightCycler, "shotgun sequencing", "GS FLX+"); `assay.assay_type` has **4,156 distinct surfaces**; `sample.sample_type` 1,577; `dataset.duplicate` 190 groups / 437 redundant (36.54% of real rows); `storage_condition` sign-dropped on 147 rows / 9 surfaces | Non-platform rate 216/1,837 = 11.8% of non-sentinel platform rows; assay_type vocabulary explosion 4,156 surfaces over 7,434 non-sentinel rows | Several "errors" are inherited: the sign loss is upstream (see CQA-F-11), not an extraction formatting fault | High |
| Coverage | **ADEQUATE** | **453/453 papers** carry ≥1 record; total 52,400; median 99, mean 115.67, min 1, max 768; but **130 papers hold 50%** of all records and 278 hold 80% | Per-field effective completeness means: sample 79.8, cohort 71.3, data_asset 69.7, dataset 65.4, assay 63.1, claim 46.8 (sentinels excluded) | Several scientifically central fields are near-empty: `positive_controls` 1.3%, `contamination_handling` 1.3%, `functional_database` 1.9%, `negative_controls` 2.2%, `normalization_method` 5.1%, `quality_control` 7.5% | High |
| Reproducibility | **WEAK** | Clean-layer build is instrumented and re-runnable (`CATCLEAN_20261030T173958`, 60,424 → 54,986 records, elapsed 393.9 s, `provenance/CLEAN_REPORT.md`); extraction run IDs are `CATNER_20261030T092214_1923898` / `Qwen/Qwen3.5-4B` | Reproducible artefacts: clean report + per-run event log **exist**; but the CDM ships the **pre-clean** record population, so the instrumented layer is not the audited one | The clean layer's own report JSON carries only run/count keys — the per-step detail lives in a Markdown file, not machine-readable | High |
| Reusability | **WEAK** | A reuser cannot tell verified from unverified (flag unusable), cannot see which cells were licence-redacted, cannot see field-level provenance for 3 of 6 tables, and gets 4,156 spellings of `assay_type` | Reusable-as-is for counting records: yes; for filtering on quality: no | The shipped public bundle (`releases/zenodo_frozen/`) avoids the redaction problem by withholding 179 papers entirely — a different mitigation than fixing the cells | High |

**No averaged score is computed.** The nine ratings are independent judgements over different evidence and are not commensurable.

---

## 2. Population decomposition

### 2.1 Record population

| Table | Rows in CDM | Rows in CSV | Match | Non-sentinel key rows | Distinct natural keys |
|---|---:|---:|---|---:|---:|
| cohort | 7,085 | 7,085 | ✔ | — | 7,085 |
| sample | 7,530 | 7,530 | ✔ | — | 7,530 |
| assay | 8,545 | 8,545 | ✔ | — | 8,545 |
| dataset | 2,976 | 2,976 | ✔ | 1,196 `repository_accession` | 759 |
| data_asset | 1,992 | 1,992 | ✔ | — | 1,992 |
| claim (catalogue half) | 24,272 | 24,272 | ✔ | — | 24,272 |
| **total** | **52,400** | **52,400** | **6/6** | | |

`claim` holds 45,667 rows in the CDM; only the 24,272 with `claim_source='catalogue_v3_1'` are catalogue records. The other 21,395 (`corpus_stage52`) are corpus-stage findings and belong to component A's population, not this one.

### 2.2 Why there are three defensible locatability numbers

The release anchors every record against section text using a seven-value vocabulary (`EXACT`, `WHITESPACE`, `RELOCATED`, `NORMALISED`, `FUZZY`, `UNANCHORED`, `NO_EVIDENCE`), and separately stores a five-value `evidence_match` (`AS_EXTRACTED`, `NORMALIZED`, `FUZZY_<score>`, `NOT_FOUND`, `NO_QUOTE`). Both were recounted row-by-row over all 52,400:

| Anchor | Rows | Share | Tier |
|---|---:|---:|---|
| `WHITESPACE` | 30,383 | 57.98% | offsets-verbatim (whitespace-insensitive) |
| `EXACT` | 7,912 | 15.10% | offsets-verbatim |
| `NORMALISED` | 4,872 | 9.30% | project-verbatim |
| `FUZZY` | 4,179 | 7.98% | content-located |
| `RELOCATED` | 3,066 | 5.85% | project-verbatim |
| `UNANCHORED` | 1,798 | 3.43% | not located |
| `NO_EVIDENCE` | 190 | 0.36% | no quote at all |

- **Tier 1 — offsets-verbatim** (`EXACT`+`WHITESPACE`): **38,295 / 52,400 = 73.08%**
- **Tier 2 — project-verbatim** (adds `RELOCATED`+`NORMALISED`; this is the verb set the project itself uses, `src/scripts/final_validation/claims_register.py:38`): **46,233 = 88.23%**
- **Tier 3 — content-located** (adds `FUZZY`): **50,412 = 96.21%**
- **Strict set** (`EXACT`/`NORMALISED`/`FUZZY*`/`RELOCATED`, i.e. **excluding** whitespace-only): **20,029 = 38.22%**

`evidence_match` recount agrees with the anchor recount at the level of "locatable / not": AS_EXTRACTED 41,584 (79.36%) + NORMALIZED 4,621 (8.82%) + FUZZY\* 3,613 (6.90%) = **49,818 locatable = 95.07%**; NOT_FOUND 2,392 (4.56%); NO_QUOTE 190 (0.36%). The 0.6-pt difference from Tier 3 is the `FUZZY` anchor rows whose similarity score fell below the match threshold.

Per table:

| Table | Rows | Content-located | Strict | EXACT | WHITESPACE | NORMALISED | FUZZY | RELOCATED | UNANCHORED | NO_EVIDENCE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cohort | 7,085 | 94.21% | 41.47% | 16.94% | 52.75% | 9.40% | 9.54% | 5.59% | 5.79% | 0 |
| sample | 7,530 | 95.94% | 36.51% | 14.41% | 59.43% | 8.38% | 7.04% | 6.68% | 4.06% | 0 |
| assay | 8,545 | 96.50% | 41.22% | 13.60% | 55.28% | 9.99% | 10.16% | 7.47% | 3.50% | 2 |
| dataset | 2,976 | 90.02% | 41.87% | 13.61% | 48.15% | 12.74% | 10.42% | 5.11% | 9.98% | 142 |
| data_asset | 1,992 | 96.49% | 48.44% | 27.61% | 48.04% | 10.19% | 6.28% | 4.37% | 3.51% | 0 |
| claim | 24,272 | 97.50% | 35.47% | 14.46% | 62.03% | 8.81% | 6.88% | 5.31% | 2.50% | 46 |

`dataset` is weakest on both unanchored (9.98%, dominated by the 142 `corpus_bioproject_link` rows that carry no quote) and content-located (90.02%). `claim` is weakest on strict (35.47%) because 62% of claim evidence matches only after whitespace normalisation.

---

## 3. Issues

### CQA-F-01 — 18,502 licence-redacted cells ship as full text in the CDM
- **Severity:** **CRITICAL**
- **Type:** Confirmed defect (rights/provenance)
- **Evidence:** Catalogue 3.1.1 CSV carries an `evidence_redacted` column valued `LICENCE` on **18,502 rows** across 6 tables (cohort 2,580 / sample 2,739 / assay 3,326 / dataset 928 / data_asset 478 / claim 8,451) covering **164 papers / 18,502 flagged records**. *[corrected by `CQA-F-AMEND-2026-11-05-1` — this sentence previously read "15,582 catalogue records"; see the amendment note in §7]* The CDM has **no `evidence_redacted` column at all**. `cqa_catalogue_redaction2.json` matched each of the 18,502 CSV rows to its CDM row and found `evidence_text` **non-empty on every one**, and **different from the redacted CSV cell on every one** — i.e. the unredacted original. Total restored text: **5,328,140 characters**. **3,529** of those rows also still carry CDM `gap_evidence` (cohort 1,533 / sample 1,720 / dataset 276) — CDM-carried quotes on redacted records.
- **Reconciliation:** 18,582 rows sit on REDACT-policy papers; minus the 80 rows whose `evidence_match='NO_QUOTE'` (dataset 63, claim 17) = **18,502 exactly, residual 0**. This is the complete population, not a sample.
- **Affected:** 18,502 / 52,400 rows = **35.3%** of all catalogue records; 164 / 453 papers = **36.2%** of the corpus.
- **Scientific impact:** none — the CDM data are complete, which is what an internal analytical database should be.
- **Publication impact:** **major and two-sided.** (a) Any statement that the CDM applies the catalogue's licence redaction is false. (b) Any statement that the *catalogue release* is the redacted artefact but the CDM is not is currently unstated anywhere, so a reader comparing the two will find 18,502 cells that differ with no documented reason. (c) The shipped public bundle (`releases/zenodo_frozen/`) sidesteps this by withholding the 179 papers wholesale, so the leak is confined to the internal DB — but the internal DB is what an archive deposit of "the CDM" would ship.
- **Recommended action:** Add an explicit `evidence_redacted` column to the CDM (values `LICENCE` / `NULL`) and document that the DB is deliberately unredacted and must be redacted on export; or, if the DB must itself be publishable, mask those 18,502 cells plus the 3,529 `gap_evidence` rows at load. Either way, state the 18,502 figure in the data dictionary so the CDM↔catalogue difference is explained rather than discovered.
- **Blocking:** blocks any deposit of the CDM that mirrors the catalogue's redaction policy. Does not block the existing public bundle, which redacts by paper.

### CQA-F-02 — Cell-level provenance is silently dropped for 3 of 6 tables
- **Severity:** **HIGH**
- **Type:** Confirmed defect (provenance loss at load)
- **Evidence:** `cqa_catalogue_provenance_gap.json`. The CSVs carry `field_sources` / `gap_changes` / `gap_evidence` for all six tables, totalling **75,395 provenance entries**. `cohort` (30,583), `sample` (22,903) and `dataset` (6,507) load with 0 entries lost. **`assay` (12,159 entries / 4,552 rows), `data_asset` (37 / 37) and `claim` (3,206 / 3,051) have no such columns in the CDM at all** — **15,402 entries lost across 7,640 records**. The CDM also drops `evidence_redacted`, `intervention_category` and `intervention_agent` on all six tables.
- **Affected:** 15,402 / 75,395 provenance entries = **20.4%**; 7,640 / 52,400 records = **14.6%**.
- **Scientific impact:** For every assay record — the table carrying DNA extraction, platform, primer, library prep and pipeline fields — there is no record of whether a value was extracted, gap-filled, reverted, or blanked by finalisation. The same is true of all catalogue claims and all data assets. Provenance is exactly the information a reviewer needs to judge gap-filling, and it exists upstream but not downstream.
- **Publication impact:** "Field-level provenance is retained" cannot be said for the CDM. It can be said for the CSV release.
- **Recommended action:** Load the three columns for `assay`, `data_asset` and `claim` in the next build (they parse cleanly — `csv_unparsable` = 0 in every table). Until then, document which tables lost them and point readers to the CSV release for assay/claim provenance.
- **Blocking:** blocks a provenance claim scoped to the CDM. Not blocking if scoped to the CSV release.

### CQA-F-03 — Two evidence flags contradict the anchor on 802 rows
- **Severity:** **HIGH**
- **Type:** Confirmed inconsistency
- **Evidence:** Cross-tab of `evidence_verified` × anchor-located over all 52,400 rows: (`verified=0`, located) **698**; (`verified=0`, `NO_EVIDENCE`) 190; (`verified=0`, NOT located) 1,694; (`verified=1`, located) 49,714; (`verified=1`, NOT located) **104**. Total 52,400 ✓. Per table — cohort 190/0/399/6,485/11; sample 106/0/292/7,118/14; assay 129/2/284/8,117/13; dataset 69/142/147/2,610/8; data_asset 9/0/67/1,913/3; claim 195/46/505/23,471/55 (order: v0-located / v0-noev / v0-not / v1-located / v1-not).
- **Affected:** 802 / 52,400 = **1.53%**; the 698 "verified=0 but locatable" rows are **3.48%** of the strict-set denominator (20,029).
- **Scientific impact:** Modest in volume, important in kind: the two flags are supposed to describe the same property and they do not. The 698 are records whose quote *is* findable but which are marked unverified — if a consumer filters `evidence_verified=1`, they lose 698 good records. The 104 are marked verified but their quote cannot be found — if a consumer trusts the flag, they accept 104 unlocatable records.
- **Publication impact:** Any quality statement keyed on `evidence_verified` inherits a 1.53% misclassification in both directions. The direction matters: the flag *understates* locatability by 698 and *overstates* it by 104.
- **Recommended action:** Document that `evidence_verified` is the upstream flag and `evidence_anchor_status` the CDM's own recomputation, that they disagree on 802 rows, and which one to use (the anchor, since it is recomputable). Do not reconcile by overwriting either column in the frozen DB.
- **Blocking:** blocks an unqualified "all evidence verified" statement.

### CQA-F-04 — The release's own locatability figure is a flag rate and overstates locatability by ~6.9 points
- **Severity:** **HIGH**
- **Type:** Confirmed defect (self-reported metric)
- **Evidence:** `QA_REPORT.md` in catalogue 3.1.1 reports `evidence_located_pct` of 88.0 / 96.2 / 91.7 / 94.7 / 95.1 / 96.9. `provenance/scripts/qa_catalogue_v3.py:180` computes it as `sum(evidence_verified)/n` — a **flag rate, not a locatability rate**. Recomputed **same quantity** (verified count / row count) gives cohort 91.69, sample 94.71, assay 95.14, dataset 87.97, data_asset 96.18, claim 96.93, which reproduces the published numbers to rounding. But the independently recomputed **locatability** rates are lower: content-located cohort 94.21, sample 95.94, assay 96.50, dataset 90.02, data_asset 96.49, claim 97.50 — and the *strict* rates are far lower (35–48%). The formula is also blind to **1,588 rows** whose `evidence_verified` is 0 without a counted anchor (`UNANCHORED` 1,798 minus the 190 `NO_EVIDENCE` overlap structure). `evidence_verified=1` ∧ `NOT_FOUND` = 0 and ∧ empty `evidence_text` = 0, so the flag is *self*-consistent; it simply measures something other than what its name says.
- **Affected:** all six tables; the published figure is 6.9 points above the same quantity recomputed from the same rows in the cohort table, and the gap widens against any stricter definition.
- **Scientific impact:** A reader taking `evidence_located_pct: 96.9` for claims as "96.9% of claim evidence was located in the source" is reading the wrong quantity. The true content-located rate is 97.50% (agreeing by accident) but the strict rate is 35.47%.
- **Publication impact:** The QA table cannot be quoted as a locatability measure. If it is quoted, it must be described as "share of rows bearing the upstream verified flag".
- **Recommended action:** Rename the metric in the next release (`evidence_flagged_verified_pct`), publish the anchor distribution alongside it, and publish the strict figure with the WHITESPACE class broken out. Do not re-derive the frozen QA_REPORT.
- **Blocking:** blocks quoting `evidence_located_pct` as a validation result.

### CQA-F-05 — Strict literal correspondence is 38.22%; 58% of records rest on whitespace-only matches
- **Severity:** **HIGH**
- **Type:** Confirmed property (measurement)
- **Evidence:** Of 52,400 rows, **30,383 (57.98%)** anchor only under `WHITESPACE` — the quote matches after whitespace normalisation but not byte-exactly. **20,029 (38.22%)** fall in the strict set (`EXACT`/`NORMALISED`/`FUZZY*`/`RELOCATED`). **2,392 (4.56%)** are `NOT_FOUND`. For the catalogue claim half specifically, D18's independent `finding_literal_correspondence` gives offset-exact 3,510 (14.46%) / normalised 15,195 (62.60%) / mismatch 4,821 (19.86%) / absent 700 (2.88%) / no_evidence 46 (0.19%) — the same shape from a different code path.
- **Affected:** 30,383 rows for the whitespace-only class; 2,392 for outright failure.
- **Scientific impact:** Whitespace normalisation is a *weak* verb. It absorbs line-wrap, ligature collapse, hyphenation and reflow — and on this corpus it also absorbs the control-byte damage documented in CQA-F-11 (6,027 control characters across 122 papers). A whitespace match therefore does not distinguish "the quote is in the paper" from "the quote is in the paper modulo downstream corruption". The strict rate is the honest one.
- **Publication impact:** "Evidence quotes were verified against source text" is defensible at 96.21% (content-located) only if the verb set is disclosed; at 38.22% strict, the same sentence needs the qualifier.
- **Recommended action:** Report the three tiers with counts and the verb set for each, exactly as in §2.2. Do not report a single locatability number.
- **Blocking:** blocks a single-number locatability claim.

### CQA-F-06 — Sample counts exceed participant counts on 42% of testable papers
- **Severity:** **HIGH**
- **Type:** Confirmed inconsistency (count consistency)
- **Evidence:** Summing `sample.sample_count` and `cohort.participant_count` per paper: **433 papers** carry both; **431 are multi-cohort** (which is the normal design here — one participant contributes many samples, so a raw sum test is not the right instrument). The defensible test is therefore per-paper sum vs participant total: `sum(sample_count) > 1.5 × sum(participant_count)` fires on **184 / 433 = 42.5%**. The naive max-based test (`sample_sum > 1.5 × max(participant_count)`) fires on 364/433 and is **not** defensible on a multi-cohort corpus — the summary figure of 364 must not be used. **2 papers** have sample counts with no participant count; **13** the reverse. Separately, `sample.sample_count` is numeric on 5,246 rows (median 40, **max 481,803**), and 15 rows carry the downstream annotation `IMPLAUSIBLY_LARGE` plus hundreds of `sample_count=<n>:NOT_IN_SOURCE_TEXT` annotations.
- **Affected:** 184 / 433 testable papers; a hard outlier tail (max 481,803 samples in a paper).
- **Scientific impact:** A 1.5× ratio is expected and benign (repeated sampling); the problem is the **tail**, where values exceed plausible designs by orders of magnitude, and the 15 papers flagged `IMPLAUSIBLY_LARGE` by the pipeline itself. `HMPAPER_000084` reports 670,328 samples against 210 participants, `HMPAPER_000417` 482,108 / 65, `HMPAPER_000222` 215,742 / 23 — these are reads or OTUs, not samples.
- **Publication impact:** Any total-sample-count statement (the kind a reader will want, e.g. "N samples across 453 papers") is not supportable from this column without an outlier cut, and any cut would be arbitrary. The paper must not report a corpus-wide sample total.
- **Recommended action:** Publish the ratio distribution and the flag, not a threshold. If a total is needed, report it with the 1.5× filter and its exclusion count, or report per-table medians instead of sums.
- **Blocking:** blocks any corpus-wide sample-count total.

### CQA-F-07 — 190 duplicate dataset groups, 437 redundant rows, on real accession keys
- **Severity:** **HIGH**
- **Type:** Confirmed defect (duplication)
- **Evidence:** Over the **1,196** dataset rows with a real (non-sentinel, non-empty, upper-normalised) `repository_accession`, there are **759 distinct keys**, **190 groups with >1 row** and **437 redundant rows = 36.54% of real rows**. Excluding sentinels (`NOT_REPORTED`, `''`, …) is essential: the raw count including 1,412 sentinel-keyed rows gives 194/444/14.92%, which understates the rate by conflating sentinels into one bucket. All other five tables are clean on their natural keys (0 groups). Cross-table `data_asset` duplication is 69 groups / 80 redundant.
- **Affected:** 437 / 1,196 = 36.54% of real dataset rows; 190 accession keys.
- **Scientific impact:** The same accession is claimed by the same paper more than once, usually with different `dataset_title` / `dataset_role` values. This is not a load bug — the CSV and DB agree — it is upstream extraction producing one record per mention rather than one per dataset. A consumer counting datasets per paper over-counts by up to 1.79×.
- **Publication impact:** "2,976 datasets" is a record count, not a dataset count. The distinct-real-accession count is 759.
- **Recommended action:** Report the dataset population as "2,976 records / 759 distinct repository accessions" and expose the duplicate groups. Do not merge in the frozen DB.
- **Blocking:** blocks quoting a dataset total as a dataset count.

### CQA-F-08 — `verification_status`, `review_status` and `link_status` carry no information
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (placeholder fields shipped as data)
- **Evidence:** `verification_status` is **absent** from cohort/sample/assay/data_asset; on `dataset` it holds only `UNVERIFIED` 2,834 / `LINKED_FROM_CORPUS` 142; a full-cell scan of the CSVs returned **0 hits in every table**, so the column is DB-synthesised. `review_status` is `UNVERIFIED` on **100% of all 52,400 rows**. `dataset.link_status` is `NO_CANDIDATES` on **100% of 2,976 rows**. `v3_status` is `KEPT` on 100% (dataset +`ADDED` 142). `dataset.last_verified` is `''` on all 2,976 rows; `dataset.data_dictionary_url` / `study_registration` / `link_run_id` are 0.0% filled.
- **Affected:** 52,400 rows (`review_status`), 2,976 (`link_status`, `verification_status`, `last_verified`).
- **Scientific impact:** Three columns that read as quality state are constants. `dataset.link_status = NO_CANDIDATES` in particular looks like a completed accession-resolution step that found nothing; in fact no resolution was attempted.
- **Publication impact:** A data dictionary must not present these as informative. Any filter on them is a no-op.
- **Recommended action:** Document them as reserved/constant columns with their fixed values, or drop them from the published data dictionary. `link_status` for `dataset` should say "not attempted", not "no candidates".
- **Blocking:** neither, if documented.

### CQA-F-09 — Type columns are uncontrolled free text
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (vocabulary)
- **Evidence:** `assay.assay_type` has **4,156 distinct surfaces** over 7,434 non-sentinel rows (top: `''` 1,111, `16S rRNA gene sequencing` 392, `sequencing` 132, `16S rRNA sequencing` 114). `sample.sample_type` 1,577 distinct (`stool` 320 / `fecal samples` 287 / `microbiota` 265 / `fecal` 187). `data_asset.asset_type` 506. `dataset.dataset_type` 597 (`microbiome` 672). By contrast `dataset.dataset_role` has only **5** values (`primary_study_data` 1,788 / `linked_data` 1,025 / `''` 152, plus 2 case-variant `PRIMARY_STUDY_DATA`) and `cohort.cohort_role` is clean on 6 — so the pipeline *can* normalise when it does.
- **Affected:** 7,434 assay type cells; 5,809 sample type cells; 597 dataset type cells.
- **Scientific impact:** The module carries `assay_type_normalized` (73.0% effective) and `sample_type_normalized` (32.2% effective) alongside the raw columns, so normalised values exist — but only for part of the population and never for `dataset_type` or `asset_type`. Any grouping by assay or sample type over the raw column collapses into hundreds of near-synonym buckets.
- **Publication impact:** A table of "assay types across the corpus" cannot be built from the raw column. It can be built from `assay_type_normalized` at 73% coverage with the residual disclosed.
- **Recommended action:** Document that the normalised columns are the analysis-ready ones, with their coverage; treat the raw columns as verbatim source strings.
- **Blocking:** blocks unqualified type aggregation over raw columns.

### CQA-F-10 — 216 values in `assay.sequencing_platform` are not sequencing platforms
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (classification)
- **Evidence:** 1,837 non-sentinel rows / **419 distinct surfaces**. **216 rows are not sequencing platforms at all** — LC-MS, plate readers, LightCycler instruments, "shotgun sequencing", "GS FLX+". **179 distinct surfaces** are not parsed by the platform regex. `CONFLICTING` appears 162 times. The distribution is dominated by fragmentation of one instrument: `Illumina MiSeq` 482 / `Illumina` 116 / `MiSeq` 94.
- **Affected:** 216 / 1,837 = **11.8%** of non-sentinel platform rows.
- **Scientific impact:** The column mixes technology class (sequencing vs mass spectrometry), vendor, instrument and assay name. A platform-stratified analysis is not possible without manual recoding. Note also `sequencing_platform` is only 21.5% effective overall (fill 23.8%).
- **Publication impact:** A "sequencing platforms used across the corpus" figure must disclose that 11.8% of populated values are not platforms.
- **Recommended action:** Publish the 419-surface list with a class column (`INSTRUMENT` / `TECHNOLOGY` / `NOT_A_PLATFORM` / `CONFLICTING`), or restrict to the parsed subset and state the exclusion.
- **Blocking:** blocks a platform breakdown.

### CQA-F-11 — Storage temperature signs are destroyed for 147 rows, and the cause is upstream
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (data corruption, inherited)
- **Evidence:** `sample.storage_condition` has 3,647 non-sentinel rows over 284 distinct surfaces. **147 rows / 9 distinct surfaces** have a sign-dropped temperature: `stored at 80°C` (36), `80°C` (33), `stored at 80°C until shipment on dry ice` (29), `stored at 20C until …` (13), `frozen at 20C within 30 min …` (13), `80 °C` (3), `80 C` (3), `frozen (<=20°C)` (1), plus one long surface (16). Provenance chain, from `cqa_storage_signloss.json`: `evidence_text` non-empty on 112/147; a minus token appears somewhere in 58/147 (39.46%); the field-level `gap_evidence['storage_condition']` quote exists on **136/147**, all 136 verbatim in their own section, but only **2** of those quotes contain any minus at all and **0** have a minus adjacent to a 20/80 token. Of the 136, **107 (78.68%)** have a control character or a true minus immediately before the 20/80 token, and the remaining **29** have control bytes elsewhere in the quote; **neither-case = 0**.
- **Affected:** 147 rows / 3,647 = **4.03%** of populated storage values; 9 surfaces.
- **Scientific impact:** `80°C` and `-80°C` are the two most different storage conditions in microbiology (freezer vs ambient/incubator). A row reading "stored at 80°C" is not merely imprecise, it inverts the meaning. Root cause is established and is **not** the extractor: the minus glyph became a control byte during PDF→text extraction — 6,027 control characters across 122 papers, **220 inside a temperature token across 44 papers**, 982 immediately before a digit across 55 papers. The extractor faithfully copied what was in its input.
- **Publication impact:** Any storage-condition analysis must exclude or flag these 147 rows. Quoting "samples were stored at -80°C" as a corpus finding is safe for the 3,500 correct rows; a quantitative distribution by storage temperature is not.
- **Recommended action:** Report the 147 rows as a known upstream corpus artifact with the control-byte explanation and the 44 affected papers; exclude them from temperature analyses. Fixing belongs to corpus segmentation, not the catalogue, and must not be done by rewriting frozen markdown (hash-pinned by corpus 2.2.0).
- **Blocking:** blocks a storage-temperature distribution. Does not block qualitative statements about cold-chain practice.

### CQA-F-12 — `gap_evidence` quotes are perfectly verbatim but unevenly grounded in the value they accompany
- **Severity:** **MODERATE**
- **Type:** Confirmed property (relevance, not validity)
- **Evidence:** `gap_evidence` is a dict keyed by field with value `{section_id, char_start, char_end, quote}` or `{"conflict": "A | B"}`. Totals: cohort 7,332 entries (6,213 quote / 1,119 conflict-only), sample 8,162 (6,938 / 1,224), dataset 1,554 (1,487 / 67) = **17,048 entries, 14,638 quotes, 2,410 conflict-only**; **0 unparsable**. Every quote is **verbatim in its own section: 100%** on all three tables. But the *value* is not always inside its own quote (whitespace-collapsed substring test): cohort 5,069/6,197 = **81.8%**, sample 5,891/6,935 = **84.95%**, dataset 839/1,487 = **56.42%**. Weakest fields: `dataset.data_availability_status` **98/673 = 14.56%**, `cohort.exclusion_criteria` 52.69%, `cohort.inclusion_criteria` 60.93%, `cohort.age_summary` 77.11%, `dataset.access_conditions` 59.48%. Strongest: `dataset.repository_accession` 98.59%, `cohort.participant_count` 97.59%, `sample.sample_count` 95.4%, `sample.preservation_method` 92.74%, `dataset.repository_name` 92.67%, `cohort.country_or_region` 96.09%.
- **Affected:** 1,510 of 6,197 cohort checks, 1,044 of 6,935 sample checks, 648 of 1,487 dataset checks fail the value-in-quote test.
- **Scientific impact:** A verbatim quote proves the quote exists, not that it supports the value. For `data_availability_status` the quote is nearly always in the right *section* but almost never contains the status word — consistent with the value being *inferred* ("data are available in SRA under PRJNA…" ⇒ `PUBLIC`) rather than quoted. That is a legitimate inference pattern, but it must not be described as quote-supported.
- **Publication impact:** "Every field is backed by a verbatim quote from the source" is **true** at the quote level (100%) and **misses the point** at the value level (56–85%). The two must be stated separately.
- **Recommended action:** Publish the value-in-quote rate per field alongside the quote-verbatim rate, and mark `data_availability_status` as an inferred field. This is exactly the literal-correspondence vs evidence-relevance separation the brief requires (§4.1 vs §4.2).
- **Blocking:** blocks describing all fields as quote-supported.

### CQA-F-13 — `claim` carries two disjoint evidence vocabularies and two different locatability rates
- **Severity:** **MODERATE**
- **Type:** Confirmed schema inconsistency
- **Evidence:** Catalogue half (`claim_source='catalogue_v3_1'`, 24,272 rows) uses `evidence_anchor_status`: WHITESPACE 15,057 / EXACT 3,510 / NORMALISED 2,139 / FUZZY 1,670 / RELOCATED 1,290 / UNANCHORED 560 / NO_EVIDENCE 46 — **locatable 23,526 = 96.93%**. Corpus half (`corpus_stage52`, 21,395 rows) uses `evidence_locator_status`: `verified_normalized` 16,602 / `unresolved_not_in_source` 2,788 / `verified_exact` 2,005 — **locatable 18,607 = 86.97%**. Each column is **100% NULL on the other half** (D18). Combined: **42,133 / 45,667 = 92.26%**.
- **Affected:** 100% of `claim` rows; the two halves differ by 10 points.
- **Scientific impact:** A single `claim` locatability figure is a weighted average of two differently-defined measurements. The 10-point gap is real and reflects genuinely weaker grounding in the corpus-stage half.
- **Publication impact:** Any claim-level evidence statistic must name the column and the half.
- **Recommended action:** Publish the two halves separately with their own vocabularies and a documented crosswalk; do not merge the columns.
- **Blocking:** blocks a single claim-level locatability statement.

### CQA-F-14 — Cross-paper accession reuse is a contamination risk that was checked and not confirmed
- **Severity:** **LOW**
- **Type:** Untested assumption (checked, risk only)
- **Evidence:** Of 711 distinct repository accessions, **38 appear in more than one paper** (e.g. `ERP019369` in three papers). `claim_evidence` cross-paper = **0**; `relation_evidence` cross-paper = **0**; parent-link cross-paper resolution is per-paper and clean.
- **Affected:** 38 / 711 accessions = 5.3%; no evidence rows affected.
- **Scientific impact:** Shared consortium studies legitimately appear in multiple papers, so reuse is expected. But it also means an accession cannot be treated as a paper identifier — the dataset key must be `(paper_id, repository_accession)`, not the accession alone.
- **Publication impact:** none, if the 38 are disclosed as a checked risk.
- **Recommended action:** State that cross-paper accession reuse was measured at 38/711, is consistent with shared consortia, and was not adjudicated per accession. Do not describe it as contamination.
- **Blocking:** neither.

### CQA-F-15 — Two residual single-record artifacts
- **Severity:** **LOW**
- **Type:** Confirmed artifacts
- **Evidence:** (a) `HMPAPER_000372` — the HTML redirect stub excluded from the 452-paper analysis universe — nonetheless carries **exactly one** catalogue record in the CDM: dataset `HMDATA_BP_000123`, accession `PRJNA644520`, `record_source='LINKED_FROM_CORPUS'`, `accession_valid='YES'`, `evidence_match='NO_QUOTE'`. (b) The **142** dataset rows with empty `evidence_text` are exactly the `corpus_bioproject_link` records (`evidence_anchor_status='NO_EVIDENCE'`); they originate in `corpus_bioproject_link`, not in extraction (D18 confirms 142 of the Q4 accession set are link records).
- **Affected:** 1 paper / 1 record; 142 records (4.77% of dataset).
- **Scientific impact:** Both are correctly labelled; the stub record is honest about having no quote. The only risk is a consumer counting 453 papers with records and not noticing that one of them contributes a single link-derived record.
- **Publication impact:** `papers_with_any_record` = 453 is technically correct but should not be read as "453 papers yielded extraction output".
- **Recommended action:** Report 452 extraction papers + 1 link-only paper; classify the 142 dataset rows as corpus-linked rather than extracted.
- **Blocking:** neither.

### CQA-F-16 — The instrumented clean layer is not the layer that shipped
- **Severity:** **LOW**
- **Type:** Documentation/provenance gap
- **Evidence:** Clean build `CATCLEAN_20261030T173958` (in `outputs/results/catalogue_v3_clean`) folded 60,424 → **54,986 records**, brought papers-with-records 452 → 453, folded 5,580, added 142, elapsed 393.9 s, and materially changed every QA number (datasets 3,234 → 3,064, cohorts 9,591 → 7,451, assays 12,116 → 9,292; `evidence_located_pct` 71.0 → 87.8 etc.; placeholder cells 3,038 → 8; `dataset_accessions_valid_pct` 64.8 → 100.0). The CDM carries **52,400** records — neither the 60,424 pre-clean population nor the 54,986 post-clean one. Its `dataset` split is 2,834 `CATNER_…` + 142 `CATCLEAN_…`.
- **Affected:** the whole record population; 52,400 ≠ 54,986 ≠ 60,424.
- **Scientific impact:** The CDM is a *third* population, apparently pre-clean with the 142 clean-added links grafted on. Without knowing which cleaning steps were applied, a reader cannot map the CDM's 52,400 onto the clean layer's 54,986.
- **Publication impact:** Any comparison to the clean layer's QA figures (87.8% dataset locatability, 100% accession validity) does not transfer to the CDM. The clean layer's own report JSON also lacks `steps`/`evidence_match` objects — that detail lives only in `provenance/CLEAN_REPORT.md`.
- **Recommended action:** Document the three populations and their relationship, and state which cleaning steps are in the CDM. Do not present clean-layer numbers as CDM numbers.
- **Blocking:** blocks citing clean-layer QA figures for the CDM.

---

## 4. The five measures, kept separate

The brief requires literal correspondence, evidence relevance, model-judge verdicts, cross-method agreement and unresolved cases to be reported separately and never collapsed into one accuracy score. They are four different questions answered by four different instruments, and one of them (judges) is not usable as a quality oracle at all.

### 4.1 Literal correspondence — "does the quoted text exist where the record says?"
Answered by the anchor recomputation (§2.2). Offsets-verbatim **73.08%**; project-verbatim **88.23%**; content-located **96.21%**; strict **38.22%**; `NOT_FOUND` **2,392 = 4.56%**; `NO_QUOTE` 190 = 0.36%. This measure says nothing about whether the record's *value* is right.

### 4.2 Evidence relevance — "does the located text support the value?"
Answered by the value-token probes (D06 `lexical_grounding`, D18 `field_relevance_probe`, and the `gap_evidence` grounding). Rates are far below the locatability rates and vary enormously by field:

| Field | Value in own evidence | Value absent | No value | BASIS |
|---|---:|---:|---:|---|
| `assay.assay_type` | 82.55% (n 7,432) | 17.45% | 1,111 sentinel | field_relevance_probe |
| `sample.sample_type` | 63.20% (n 5,809) | 37.48% | 1,721 | field_relevance_probe |
| `dataset.repository_accession` | 56.83% (n 1,054) | 43.17% | 1,780 | field_relevance_probe |
| `assay.sequencing_platform` | 46.95% (n 1,836) | 53.05% | 6,707 | field_relevance_probe |
| `sample.body_site` | 43.68% (n 7,243) | 56.32% | 287 | field_relevance_probe |
| `cohort.country_or_region` | 24.84% (n 3,334) | 75.17% | 3,751 | field_relevance_probe |
| `cohort.cohort_role` | 19.19% (n 7,076) | 80.81% | 9 | field_relevance_probe |

Over the full row denominator (D06), the same picture: `assay.sequencing_platform` IN 9.34% / ABSENT 14.41% / NO_VALUE 76.23% of 8,545; `cohort.country_or_region` IN 8.23% / ABSENT 66.68% / NO_VALUE 25.10%; `dataset.repository_name` IN 26.31% / ABSENT 59.54% of 2,976. Two readings are both defensible: low support means the value was inferred (a country can be correctly inferred from an affiliation even when the word never appears in the evidence quote), or it means the value is wrong. **This audit cannot distinguish those, and does not.** What it can say is that the values are not, in general, quote-supported, so "extracted verbatim from the text" is the wrong description for most fields.

### 4.3 Model-judge verdicts — a model-behaviour measurement, not an annotation
Two LLM judges (llama, mistral) scored the same 52,397 records. `judge_summary.json` reports **exact agreement 81.15%** and **Cohen κ = 0.2321** over the 242,158 cells where both produced a valid verdict. *[superseded by `CQA-F-AMEND-2026-11-05-2`: those three values belong to no scope reproducible from the shards — see §7. On the `text_value` scope the shipped file reports observed agreement **0.477** and **κ = 0.084** over **351,792** pairs (all verdict classes), and observed agreement **0.85** and **κ = 0.282** over the **194,479** both-valid pairs.]* That κ is *fair-to-poor*: agreement at this level on a heavily PASS-skewed rubric is what chance plus a permissive rubric produces. Supporting diagnostics: rubric compliance of *text_value* judgments is 0.992 for llama vs **0.554** for mistral; mistral returns `INVALID` on **284,325** cells *[superseded by `CQA-F-AMEND-2026-11-05-2`: `284,325` is an **all-fields** variant (mistral-inventory iteration, union record set, link-verdict applied to `cohort_id`/`assay_id`/`dataset_id`; 544,992 cells). On the `text_value` scope the same computation gives mistral `INVALID` **157,011** of 351,792 and llama **2,877**.]* against llama's much smaller count; the cross-tab is dominated by `PASS|PASS` 159,680 and `PASS|INVALID` 132,890, i.e. the disagreement is systematic-by-judge rather than record-specific. *[The two crosstab cells are verified and unchanged: both are exact `judge_agreement_text_values` cells on the `text_value` scope.]* One judge has 120 errored and 13 truncated lines; the other 6 and 5.
**Conclusion:** the judge layer is **not a quality oracle** and is not used here to accept or reject any record. It is used in exactly two ways: (i) as evidence that inter-model verdict agreement on this task is weak (κ **0.282** on the both-valid text-value pairs; **0.084** across all verdict classes), *[corrected by `CQA-F-AMEND-2026-11-05-2` — previously "κ 0.232"]* which is itself a finding about the reliability of LLM-as-judge validation on this data; (ii) as a *priority sampling frame* — the 2,023 judge-field pairs where both judges failed (`BOTH_JUDGES_FAIL.csv`, 1,730 distinct records) are worth a human's attention first. They are **not** an error set. Their distribution is sample 658 / cohort 544 / assay 474 / claim 275 / dataset 53 / data_asset 19; 702 of them have deterministic `FOUND` text (i.e. a deterministic check disagreed with both judges), which makes them the highest-yield starting point for review. **Note the unit:** these 2,023 are *field* pairs, not records — `CQA-F-AMEND-2026-11-05-2` records that §4.5 previously called them "records".

### 4.4 Cross-method agreement — "do two independent instruments give the same answer?"
The instruments available are: the anchor recomputation, the `evidence_verified` flag, the `evidence_match` enum, the `gap_evidence` quote, the deterministic checks, and the two judges. They agree in the main and disagree at the margins, which is the useful signal:
- anchor vs `evidence_verified`: **disagree on 802 rows (1.53%)** — CQA-F-03.
- anchor vs `evidence_match`: agree on locatability to 0.6 pt (§2.2) — consistent, and these two are computed from the same pass, so agreement is not independent confirmation.
- `gap_evidence` value-in-quote vs `field_relevance_probe`: **independent** code paths, different populations; both show the same ranking (accession/sample_count strong, country/role/availability weak). That convergence is meaningful.
- deterministic check vs both judges: 702 records where the judges failed but a deterministic `FOUND` test succeeded — disagreement concentrated exactly where the judges are weakest.
- The one measure that is *not* cross-method agreement and must never be called accuracy: agreement between two LLM judges (κ 0.282 both-valid text-value, 0.084 across all classes) measures model similarity, not truth. *[corrected by `CQA-F-AMEND-2026-11-05-2` — previously "κ 0.232"]*

### 4.5 Unresolved cases — what this audit could not decide
- **2,392 rows `NOT_FOUND`** (4.56%) — quote not present in the section. Not adjudicated: could be a mis-assigned section, an upstream text loss, or a fabricated quote. No instrument here distinguishes them.
- **4,179 `FUZZY` rows** (7.98%) — matched at a similarity score, not exactly. Whether each is a legitimate reflow or a different sentence was not determined per row.
- **1,798 `UNANCHORED`** (3.43%) and **190 `NO_QUOTE`** (0.36%) — nothing to anchor against.
- **1,510 cohort / 1,044 sample / 648 dataset** value-not-in-quote cases — inferred-vs-wrong undetermined (§4.2).
- **2,023 both-judges-failed judge-field pairs** (1,730 distinct records) — no disposition. *[corrected by `CQA-F-AMEND-2026-11-05-2`: the unit is a (record, field) pair, not a record]*
- **11,477 `NO_MATCH_FOUND` mappings**, **10,680 `UNRESOLVED` dispositions**, **560 claim `UNABLE_TO_VERIFY`** — cross-component unresolved cases counted in D18 `catalogue_unresolved`; they belong to components D/F jointly and are not newly generated here.
- **81.7% of papers** whose `sample_sum > 1.5 × max_participant` — the max-based test is not defensible on a multi-cohort corpus, so those 364 cases are neither confirmed nor dismissed; only the sum-based 184 are treated as a finding.

---

## 5. What this component demonstrates, and what it does not

**Demonstrates (independently verified):**
- The record inventory is exact and stable: 52,400 rows, 6/6 CSV↔DB counts match, 0 duplicate primary keys, 0 duplicate natural keys in five of six tables.
- Locatability is quantified at three defensible tiers (73.08 / 88.23 / 96.21%) with the strict figure (38.22%) and the outright-failure figure (4.56%) both stated.
- The 18,502-row redaction leak is fully reconciled (18,582 on REDACT papers − 80 `NO_QUOTE` = 18,502, residual 0), so it is a proven population, not an estimate.
- The release's own `evidence_located_pct` is provably a flag rate computed by `qa_catalogue_v3.py:180`, and the discrepancy is a naming/formula defect, not a crime.
- The storage-temperature sign loss is traced to PDF-extraction control bytes (107/136 immediate, 29/136 elsewhere, 0/136 unexplained), so the defect is inherited, not introduced.
- Every `gap_evidence` quote is verbatim in its own section (100% on 17,048 entries, 14,638 quotes).
- Judges are demonstrably unreliable as an oracle (κ **0.282** on the 194,479 both-valid text-value pairs; **0.084** on all 351,792 verdict pairs) and are used only as a sampling frame. *[corrected by `CQA-F-AMEND-2026-11-05-2` — previously "κ 0.2321" without a scope]*
- The two judge agreement blocks in `judge_summary.json` were **recomputed from the raw shards** (`diagnostics/cqa_f_judge.py`, `diagnostics/results/cqa_f_judge.json`) and reproduce exactly: 351,792 / 0.477 / 0.084 and 194,479 / 0.85 / 0.282, both `reproduces: true`. Every figure in §4.3 is therefore either traceable to a reproduced scope or explicitly marked superseded.

**Does not establish:**
- That any specific catalogue value is correct. There is no gold standard, `review_status` is 100% `UNVERIFIED`, and `human_review` is empty.
- That the 216 non-platforms, the 4,156 assay-type surfaces, or the 437 redundant dataset rows are *errors* in the sense of being wrong about the paper — they are wrong about being *typed*, *controlled*, or *deduplicated*.
- That the 184 sample/participant ratios above 1.5× indicate wrong counts; repeated sampling legitimately produces them, and only the flagged tail is clearly implausible.
- Any precision, recall, accuracy, or completeness figure for the catalogue, in any table, for any field.

---

## 6. Component verdict

The catalogue is the largest and most consequential data component — 52,400 records over all 453 papers, carrying the cohort, sample, assay, dataset and finding facts the CDM exists to hold — and its **skeleton is sound**: complete paper coverage, exact row counts against its own release, perfect primary keys, and parent links that resolve 100% once the semicolon convention is understood. The **quote layer is also unusually disciplined**: every `gap_evidence` quote is verbatim, and the anchor vocabulary is both recomputable and honestly labelled.

What it cannot survive is being read as validated data. The two evidence flags contradict each other on 802 rows; the release's headline locatability figure is a flag rate that overstates its own quantity by ~7 points; strict literal correspondence is 38.2% with 58% of records resting on whitespace-only matches; values are quote-supported for 83% of assay types but only 19% of cohort roles and 15% of dataset availability statuses; 20% of cell-level provenance never reaches the database; 37% of real dataset rows are duplicates; sample counts produce impossible totals on the flagged tail; and 18,502 cells that the catalogue redacted for licence reasons ship in full in the CDM with no flag to say so.

The last item is the one that must be fixed before anything else is said about this component, because it is the only finding here that is simultaneously a data-integrity defect, a rights defect, and a silent divergence between two artefacts that are publicly described as the same data. Everything else is a disclosure problem; that one is a decision problem.

---

## 7. Amendment record

### `CQA-F-AMEND-2026-11-05-1` — `CQA-F-01` record count corrected (reporting only)
- **Date:** 2026-11-05
- **Location:** §3, `CQA-F-01`, Evidence line.
- **Was:** "covering **164 papers / 15,582 catalogue records**".
- **Now:** "covering **164 papers / 18,502 flagged records**".
- **Why:** `15,582` is **not reproducible from any table or table combination**. Recomputed directly from
  `releases/data_catalogue_v3/3.1.1/tables/*.csv`, the `evidence_redacted='LICENCE'` population is
  **18,502 rows over 164 papers** (`findings` 8,451 / `assays` 3,326 / `samples` 2,739 / `cohorts` 2,580 /
  `datasets` 928 / `data_assets` 478). The difference `18,502 − 15,582 = 2,920` corresponds to no table
  row count and no table pair (`findings` alone is 24,272; the six tables total 52,400).
- **Scope of the correction:** the sentence only. Every other figure in `CQA-F-01` is unchanged and
  independently reproducible: 18,502 flagged rows, per-table split, 164 papers, 5,328,140 restored
  characters, 3,529 `gap_evidence` rows (cohort 1,533 / sample 1,720 / dataset 276), and the
  `18,582 − 80 NO_QUOTE = 18,502` reconciliation with residual 0.
- **Consequential figures checked:** "18,502 / 52,400 = 35.3%" (correct), "164 / 453 = 36.2%" (correct).
  No other report quotes `15,582` (`grep -rn "15,582"` over the audit tree returns this amendment record
  and no other occurrence).
- **Type:** reporting defect in this audit, **not** a data defect. No artefact, release, count or rating
  changes. The component's ratings and its CRITICAL severity are unaffected.
- **Reconciliation source:** `diagnostics/results/cqa_n_rights.json:flag_semantics` and
  `over_redaction`, plus a direct recount of the six catalogue CSVs.

### `CQA-F-AMEND-2026-11-05-2` — judge-scope clarification (reporting only; four figures re-scoped, none fabricated)
- **Date:** 2026-11-05
- **Location:** §4.3 (two sentences), §4.4 (one bullet), §4.5 (one bullet), §5 (one bullet).
- **What was wrong.** §4.3 named one scope (`text_value` cells where both judges produced a
  valid verdict) and then quoted figures that come from *three different* scopes in the same
  sentence. Nothing was invented; the numbers exist, but the sentence attributes them to the
  wrong denominators. `judge_summary.json` is complete and correct, and the whole of §4.3 is
  now reproducible in one command.
- **Verified and unchanged (§4.3 crosstab).** `PASS|PASS` **159,680** and `PASS|INVALID`
  **132,890** are exact cells of `judge_agreement_text_values` (the `text_value` scope, all
  verdict classes, 351,792 pairs). They stay. The disagreement being *systematic-by-judge*
  rather than record-specific follows from these cells and is unaffected.
- **Superseded (wrong scope).** *[superseded by `CQA-F-AMEND-2026-11-05-2`]*
  - "exact agreement **81.15%** and Cohen **κ = 0.2321** over the **242,158** cells where both
    produced a valid verdict" — attributed to no reproducible scope. The shipped file's own
    numbers are:
    | Block | pairs | observed agreement | Cohen κ |
    |---|---:|---:|---:|
    | `judge_agreement_text_values` (all classes, `text_value`) | 351,792 | **0.477** | **0.084** |
    | `judge_agreement_text_values_both_valid` (`text_value`, both valid) | 194,479 | **0.850** | **0.282** |
    | all-fields, both valid, no link-verdict coercion (near-variant) | 241,148 | 0.8135 | 0.2267 |
  - `242,158` is **not reproducible**. It is 1,010 cells above the nearest reproducible
    both-valid tabulation (241,148, all-fields without link-verdict coercion) and is not
    produced by any of the 128 `NOT_TEXT`/`LINKS` field-drop subsets × 2 link-verdict modes,
    nor by any record-set / field-inventory / error-inclusion combination tested. `0.8115` and
    `0.2321` likewise match no tested scope (`0.8135`/`0.2267` at 241,148 is the closest).
    This is recorded as **missing provenance**, not as a data error: no shipped artefact
    contains these three values, so they were computed somewhere that left no trace.
  - "mistral returns `INVALID` on **284,325** cells" — this one **is** reproducible, but on the
    **all-fields** scope: mistral-inventory field iteration over the union record set with
    link-verdict applied to `cohort_id`/`assay_id`/`dataset_id` gives exactly 284,325 `INVALID`
    of 544,992 cells. On the sentence's own `text_value` scope the same computation gives
    mistral **157,011** of 351,792 (llama **2,877**). Both are now stated.
- **`INVALID` is a computed class, not a judge output.** `judge_analysis.py:cls()` maps
  anything outside `{PASS, FAIL_NOT_SUPPORTED, FAIL_WRONG_FIELD, FAIL_CONTRADICTED,
  UNCERTAIN}` to `INVALID` — including a missing field, a dict, or a value the judge copied
  from the source text. Mistral emits 60,223 distinct field values (it echoes source text);
  llama emits 159. That asymmetry, not a differing error rate, is what drives
  157,011 / 284,325. The amendment states this because "mistral returns INVALID on N cells"
  reads as a judgement about mistral's behaviour when it is also a statement about its
  output format.
- **Unit correction (§4.5).** The 2,023 both-failed entries are **(record, field) pairs over
  1,730 distinct records**, not 2,023 records. `BOTH_JUDGES_FAIL.csv` has one row per field.
  Per-table distribution (sample 658 / cohort 544 / assay 474 / claim 275 / dataset 53 /
  data_asset 19) and the 702 `deterministic_check = FOUND` count are unchanged — they were
  always pair counts.
- **Consequential figures checked.** κ 0.232 appeared in three places (§4.3, §4.4, §5) and all
  three now carry the corrected pair of values; §6's verdict prose quotes no judge statistic.
  No other report in the audit quotes a judge agreement figure (`grep -rn "0.232\|0.2321"
  *.md` returns 06 only).
- **Type:** reporting defect in this audit, **not** a data defect. No artefact, release, count
  or rating changes. `CQA-F-01` and the component's CRITICAL severity are unaffected; the
  "judges are not an oracle" conclusion holds under every scope (κ ≤ 0.282).
- **Reproducer (permanent, was missing).** `diagnostics/cqa_f_judge.py` recomputes both shipped
  blocks from the raw shards and emits `diagnostics/results/cqa_f_judge.json`, including
  `shipped_file_reproduces` (`true`/`true`), the two-scope table, the 24-variant sweep and
  `disputed_figure_provenance`. Run: `python3
  paper/publication/component_quality_audit/diagnostics/cqa_f_judge.py` (~6 s, stdlib only).

