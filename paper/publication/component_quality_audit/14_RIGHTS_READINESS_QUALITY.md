# Component N — Rights Readiness and Redaction Integrity

**Audited object:** the rights posture of the four frozen artefacts taken together — `paper/publication/rights/`
(`PAPER_RIGHTS_MATRIX.csv`, 453 × 22; `rights_summary.json`; `RIGHTS_ASSESSMENT.md`), the live catalogue
`releases/data_catalogue_v3/3.1.1/` (`provenance/paper_licences.csv`, six `tables/*.csv` carrying
`quote_policy` and `evidence_redacted`), the frozen CDM `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db`
(open `mode=ro`), and the shipped public bundle `releases/zenodo_frozen/` (274 `TEXT_INCLUDED` / 179
`TEXT_WITHHELD_PENDING_RIGHTS_REVIEW`).
**Evidence base:** `diagnostics/results/cqa_n_rights.json` (single regenerating probe, ~72 s wall), plus
`d12_rights_readiness.json`; and the release's own `VERIFICATION_RIGHTS_SCAN.json`, `MANIFEST.sha256`,
`RELEASE_REDACTION_LOG.csv`, `TECHNICAL_VALIDATION.md`, `ZENODO_UPLOAD_METADATA.json`,
`cdm/CDM_COLUMN_DICTIONARY.csv`, and `src/scripts/release/build_zenodo_frozen.py`.
**Independence:** every number below was recomputed from the artefacts, not read from a report. The
redaction log was reconciled cell-by-cell against observed source→public deltas; the shipped-catalogue
deltas were reconciled separately; the flag semantics were recomputed under four explicit scopes; the
window guarantee was re-derived by stride-1 scan rather than trusting the builder's own stride-10 probe.

> **Scope.** This component judges **whether the rights decisions are made, applied consistently, and
> truthfully described**. It does **not** make a legal determination, does not substitute for a rights
> holder or counsel, and does not treat any automated scan as legal clearance. Substantive correctness
> of the data is components A–G; packaging is component M. Where a rights defect and a data defect are
> the same defect (notably `CQA-F-01`), it is cross-referenced rather than re-argued.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Policy consistency across layers | **STRONG** | Matrix `quote_policy_applied_in_catalogue_3_1_1` equals catalogue `quote_policy` on **453 / 453**; `quote_policy × proposed_release_decision` is a clean bijection (`KEEP|INCLUDE_TEXT` 274, `REDACT|WITHHOLD_TEXT` 164, `KEEP_NC|RESTRICTED_NC_LAYER` 15); `text_layer` in `PAPER_LICENCES.csv` maps exactly to the matrix decision; matrix vs catalogue vs zenodo licence values are **0 real mismatches** (the 135 apparent differences are `""` vs the `NONE_FOUND` sentinel — semantically identical) | layer agreement **453 / 453 = 100%** | Consistency shows the pipeline applied one rule everywhere; it does not show the rule is right. The rule itself is the legal question (see CQA-N-01) | High |
| Legal adjudication completeness | **CRITICAL WEAKNESS** | `rights_reviewer`, `final_decision`, `publisher`, `decision_evidence` are **empty on 453 / 453 rows**. `needs_legal_confirmation = yes` on **179 / 453 = 39.5%** (135 quotation/database-rights, 29 derivative, 12 NC-compatibility, 3 share-alike) and **not one has been adjudicated**. All 179 are shipped as `TEXT_WITHHELD_PENDING_RIGHTS_REVIEW` | adjudicated papers **0 / 179 = 0%**; rows with a named reviewer **0 / 453** | The audit can report that the decisions are *unaudited by a rights holder*. It cannot report what the correct decision is, and must not pretend the `PENDING` state is conservative enough to be a finding of safety | High |
| Licence evidence traceability | **ADEQUATE** | Every licence row carries `licence_evidence` sourced to Europe PMC / PMC: `pmcid` 353, `pmid` 88, `NOT_IN_EUROPE_PMC` 10, `doi` 2. `no_licence_but_in_pmc` = **71** — i.e. 71 of the 135 `none_found` papers *are* in PMC but expose no machine-readable licence | evidence source stated **453 / 453 = 100%**; unresolvable **10 / 453 = 2.2%** | Traceable ≠ adjudicated. "Europe PMC reports no licence" is a fact about an index, not a statement that redistribution is unencumbered — and the absence of a licence is legally *worse* than a restrictive one | High |
| Withheld-layer redaction completeness | **WEAK** | Independent scan: `pass: true`, 299 files, **6,136,425** strings, 179 withheld papers, **`unexplained_hits: 0`**, `hits: []`, `hits_by_location {}`. The builder's own stride-10 probe over the same public DB returns **0** hits on 1,057,538 candidate cells. **But** a stride-1 re-scan finds **403** shipped non-KEEP catalogue cells across **122 papers / 42 file-column pairs** holding a true contiguous **50–58**-character verbatim run from their own withheld paper (**397** unique to withheld wording, 6 shared boilerplate), and **759** public-DB non-TEXT cells across **64 table-column pairs** (**735** non-shared). `cells_with_run_ge_59` = **0**; max run **58** | zero runs at the *effective* threshold **≥59: 0 / 403**; runs at the *documented* threshold ≥50: **403** | The withheld set holds no passage of 59 characters or more from a withheld paper. The README's promise is **50** characters, and 403 cells violate it. Whether 50–58 characters is a legally meaningful excerpt is a question for counsel — this component records the discrepancy, not a legal verdict | High |
| Redaction precision (no collateral loss) | **WEAK** | **225** cells nulled on **93 *INCLUDED* papers** across **41 `(table, column)` pairs** / **174 detail rows** — all R3 artefacts where a 50-char window shared with a *withheld* paper triggered removal. Top pairs `term_mention.normalized_mention` 34, `assay.evidence_text` 30, `relation_evidence.source_sentence` 14, `claim.evidence_text` 12, `claim_evidence.evidence_text` 12. Top papers `HMPAPER_000421` 14, `HMPAPER_000313` 11, `HMPAPER_000304` 9. All **34** of the included-paper `normalized_mention` losses are cross-paper (own-paper window hits 0/34), lengths 50–112, median 80 | included-paper cells lost **225**; over-redaction rate **225 / non-KEEP-cleared cells** — bounded, but non-zero and undocumented | Only **93 / 225** are attributable to an individually logged pair value; the remaining R3 subsets fold into the aggregate `R2-R4_VERBATIM` rule, so per-paper over-redaction is **not individually logged**. The loss is not recoverable from the public bundle — the source values survive only in the internal CDM | High |
| Redaction log integrity and reproducibility | **STRONG** | DB↔log: **156** `(table, column)` pairs, logged **2,072,254** cells = observed **2,072,254**, **0 mismatched**, `columns_absent_in_source_schema: []`, `reconciles: true`. Attribution: 225 to included papers + **2,028,338** withheld + **43,691** unattributed — the latter are exactly **15 pairs on tables with no `paper_id`** (`type_harmonization.context` 40,141; `relation.object_display_label` 892; `canonical_term.term` 927 + `term_norm` 338; etc.), which is a schema property, not a leak. Shipped catalogue: **81** logged pairs / **27,226** cells = **77 exact (21,838)** + **4 partial (5,388)**; **0 observed-only pairs**, `rowcount_problems: []`, `reconciles: true`. Manifest **299 / 299** OK | reconciliation exact on both layers; unexplained observed cells **0** | The log proves the *logged* rules ran exactly once over the stated population. It cannot claim completeness beyond the log's own rule set — which is precisely what CQA-N-03 exploits | High |
| Flag propagation across artefacts | **CRITICAL WEAKNESS** | `evidence_redacted` exists **only in the six catalogue CSVs**. It is absent from the source CDM schema **and** from the public DB — a substring search for `redact` across all 44 source / 46 public tables returns nothing. The public DB instead has two side tables, `release_rights` (453 rows) and `release_redaction` (263 rows), and a consumer joining `assay → release_redaction` must re-derive which cells were redacted. The CDM keeps the **unredacted original** in all 18,502 cases | flag presence **CSV yes / DB no / public DB no**; 18,502 CDM cells with no on-row redaction marker | This is the same defect as `CQA-F-01` seen from the rights side: the artefact that ships full text has no per-row marker saying it is privileged. Any consumer that exports "the CDM" re-publishes 18,502 flagged cells and cannot detect it | High |
| Declared invariants vs measured behaviour | **WEAK** | `validation/TECHNICAL_VALIDATION.md:3` states "Redaction removes text only; it changes no identifier, value count or link." Measured source→public losses: ≥63 accession/URL cells (`dataset.repository_accession` 1, `repository_accession_original` 6, `data_asset.accession_original` 6, `dataset.dataset_url` 36, `data_asset.repository_url` 37, `paper.full_text_url` 1), **164** `dataset.dataset_title`, **17/5** `license_or_terms`, **927** `canonical_term.term`, **338** `term_norm`, **570/892** `*_display_label`, 12,891 `source_sentence` | falsified invariants **1 of 1 declared**; identified lost cells **≥2,136** | The claim is the release's own, so this is a truthfulness defect rather than a data defect — but a reuser who plans around "identifiers are preserved" will be wrong on 927 canonical terms alone | High |
| Release-readiness documentation | **WEAK** | `ZENODO_UPLOAD_METADATA.json` carries **7 `TODO`** placeholders: `_instructions`, `metadata.publication_date`, three `creators[].orcid`, `metadata.license` (`TODO: confirm (proposed cc-by-4.0)`), and one `related_identifiers[].identifier` (`TODO: DOI of the article (after acceptance)`). Shipped `README.md` contains `**[AUTHORS: add the article citation and this dataset's DOI after deposit.]**` and `[AUTHORS TO CONFIRM BEFORE UPLOAD]` (7,249 B vs the 7,475 B source). `CDM_COLUMN_DICTIONARY.csv` covers **866 columns over 44 tables** and documents **0** columns of `release_rights` / `release_redaction`; **644 / 866 = 74.4%** of columns are `NEEDS_EXPERT_REVIEW` | unfilled upload fields **7**; undocumented shipped tables **2 / 46**; un-defined columns **74.4%** | The bundle is internally complete enough to deposit and not complete enough to deposit correctly: the licence field, the ORCIDs and the article DOI are all unresolved, and the two tables that encode the rights decisions are the only two with zero documentation | High |

**No averaged score is computed.**

---

## 2. The denominators, stated once

The rights numbers in circulation differ by an order of magnitude because four different populations are
being counted. Every report in this audit that quotes a figure from this component uses the definition below.

| Figure | Population | What it counts |
|---|---|---|
| **18,502** | `evidence_redacted='LICENCE'` rows in the six catalogue 3.1.1 CSVs | Records *flagged as redacted* in the source catalogue: findings 8,451 / assays 3,326 / samples 2,739 / cohorts 2,580 / datasets 928 / data_assets 478. 164 papers. Distinct primary keys per table equal the row count, so this is **18,502 rows and 18,502 record ids**. |
| **18,582** | All catalogue rows on REDACT-policy papers | The REDACT population before the flag is applied. `18,582 − 80` rows whose `evidence_match='NO_QUOTE'` (datasets 63 + findings 17) `= 18,502`, residual **0**. |
| **2,103,395** | Cells emptied across all targets | DB **2,072,254** + catalogue **27,226** + terminology **3,914** + cdm **1**. |
| **20,232** | Flagged cells in the shipped catalogue | assays 3,603 / cohorts 2,824 / samples 2,964 / datasets 1,060 / data_assets 526 / findings 9,255. Every non-KEEP record row is flagged; note this exceeds 18,502 by **1,730** newly flagged cells — the shipped build flags the whole non-KEEP population, the source flags only the REDACT subset. |

`06_CATALOGUE_QUALITY.md` previously quoted `15,582` records in `CQA-F-01`. That figure is **not
reproducible from any table or table combination** (18,502 − 15,582 = 2,920, which matches no table row
count and no table pair) and has been corrected under `CQA-F-AMEND-2026-11-05-1`. The correct figures are
**18,502 flagged rows over 164 papers**, or **18,582 rows on REDACT-policy papers**.

### 2.1 Flag semantics, exact and reproducible

The four scopes below are the complete answer to "what does `evidence_redacted` mean". All four are
recomputed in `cqa_n_rights.json:flag_semantics`.

| Scope | cells |
|---|---|
| source / all CSVs | `KEEP\|unflagged` 32,442 · `REDACT\|flagged` 18,502 · `KEEP_NC\|unflagged` 1,665 · `REDACT\|unflagged` **244** |
| source / record tables only (excl. `papers.csv`) | `KEEP\|unflagged` 32,168 · `REDACT\|flagged` 18,502 · `KEEP_NC\|unflagged` 1,650 · `REDACT\|unflagged` **80** |
| shipped / all CSVs | `KEEP\|unflagged` 32,442 · `REDACT\|flagged` 18,582 · `KEEP_NC\|flagged` 1,650 · `REDACT\|unflagged` 164 · `KEEP_NC\|unflagged` 15 |
| shipped / record tables only | `KEEP\|unflagged` 32,168 · `REDACT\|flagged` 18,582 · `KEEP_NC\|flagged` 1,650 · `REDACT\|unflagged` **0** |

The **244** is therefore fully explained: **164** are `papers.csv` rows on REDACT papers (paper-level
metadata, never redacted) **+ 80** `NO_QUOTE` records. In the shipped bundle every one of the 20,232
non-KEEP record rows is flagged, and the only unflagged REDACT/NC rows are the 179 `papers.csv` rows.

### 2.2 The NC asymmetry

`rights_summary.json` names three decisions — `INCLUDE_TEXT` 274 / `WITHHOLD_TEXT` 164 /
`RESTRICTED_NC_LAYER` 15 — but **no `RESTRICTED_NC_LAYER` artefact exists on disk**. `build_zenodo_frozen.py:131`
defines the withheld set as `proposed_release_decision != "INCLUDE_TEXT"`, so the 12 `cc by-nc` and
3 `cc by-nc-sa` papers are withheld exactly like the `none_found` ones. Meanwhile the **live catalogue**
keeps 1,650 `KEEP_NC` rows unflagged and 1,645 `evidence_text` cells in place, because `KEEP_NC` is a
quotation-permitted policy.

This is not a leak and not an inconsistency in the rule; it is a **naming** inconsistency: a third
decision category is recorded in the summary JSON that the build does not implement as a distinct layer.
A reader of `rights_summary.json` will look for an NC layer and not find one.

### 2.3 The log's own footprint

`release_redaction` holds **263 rows over 36 targets**. Four rules: `R2-R4_VERBATIM` 226,
`R1_TEXT_COLUMN` 32, `R1_QUOTES_REMOVED` 4, `R4_ALL_ROWS_NO_PAPER_ID` 1. Four targets are terminology
files deleted at finalize — `canonical_terms.jsonl` 1,313, `term_definitions.jsonl` 418,
`term_ontology_mappings.jsonl` 1,944, `.provenance` 239 = **3,914** cells, all `exists=False` — after
which `finalize_zenodo_frozen.py:61-64` re-exports them from the public DB as `.csv.gz`. The 3,914 are a
descriptive split of the same data, not an additional 3,914 removed cells.

---

## 3. Issues

### CQA-N-01 — 179 papers ship withheld pending a rights review that has not happened
- **Severity:** **CRITICAL**
- **Type:** Confirmed gap (governance, not data)
- **Evidence:** `needs_legal_confirmation = yes` on **179 / 453** papers: 135 "quotation exceptions and database rights depend on jurisdiction", 29 "is sectioned/re-segmented text a derivative?", 12 "release licence must be NC-compatible", 3 "share-alike may bind derived layers". `rights_reviewer`, `final_decision`, `publisher`, `decision_evidence` are empty on **453 / 453** rows. `PAPER_LICENCES.csv` records all 179 as `TEXT_WITHHELD_PENDING_RIGHTS_REVIEW`.
- **Affected:** 179 / 453 papers = **39.5%** of the corpus; 1,367 / 4,006 sections; **9,974,210** characters of withheld text (`WITHHOLD_TEXT` 9,188,416 + `RESTRICTED_NC_LAYER` 785,794) = **37.2%** of all section text. *[corrected by `CQA-N-AMEND-2026-11-05-1` — this sentence previously quoted only the single `WITHHOLD_TEXT` class (9,188,416), omitting the 785,794 characters on the 15 NC/NC-SA papers; see §6.C]*
- **Scientific impact:** none directly — the withheld layer is complete in the internal CDM and every analytical result in this audit was computed over all 453 papers. The impact is that **39.5% of the corpus cannot be shown to a reader**, so any published claim resting on those papers is unreproducible from the public artefact.
- **Publication impact:** **major.** A methods section that says "the corpus is publicly available" is false for 39.5% of it. The correct statement is that the derived annotations ship for all 453 and the source text for 274.
- **Recommended action:** Commission the review. The 179 are not homogeneous — 135 are a *licence*-determination problem (quotable under exceptions, jurisdiction-dependent), 29 a *derivative*-work problem, 15 an *NC-compatibility* problem. They need different expertise and should not be routed as one queue. Until reviewed, describe them as `PENDING` in the manuscript, not as "restricted".
- **Blocking:** blocks the public data release from being called *complete*. Does not block the current bundle, which is internally consistent and correctly labelled.

### CQA-N-02 — The redaction flag lives only in CSVs; neither database can mark a redacted cell
- **Severity:** **CRITICAL**
- **Type:** Confirmed defect (schema)
- **Evidence:** `evidence_redacted` is present in all six `releases/data_catalogue_v3/3.1.1/tables/*.csv`. A substring search for `redact` across **all 44 source tables and all 46 public-DB tables finds nothing**. The public DB adds `release_rights` (453 rows) and `release_redaction` (263 rows), which record the decisions and the log but do not mark rows. The 18,502 flagged CDM cells carry the **unredacted original**.
- **Affected:** 18,502 cells / 164 papers unmarked in the CDM; 0 columns in either DB.
- **Scientific impact:** none — the CDM is meant to hold complete data.
- **Publication impact:** **major.** This is the same defect as `CQA-F-01`; from the rights side the consequence is sharper: an archive deposit of "the CDM" re-publishes 18,502 cells that the catalogue deliberately redacted, and **no query over the deposited database can detect it**. The bundle's protection is a separate artefact (`release_redaction`), not a property of the data.
- **Recommended action:** Add `evidence_redacted` (or a whole-row `redaction_state`) to the six tables and backfill from the catalogue flag; document the 18,502 figure in the column dictionary. Alternatively state in the deposit metadata that the DB is unredacted by design and must be masked on export — but state it, rather than leaving a consumer to discover the divergence.
- **Blocking:** blocks any deposit that mirrors the catalogue's policy. Does not block the existing public bundle, which redacts by paper and holds at ≥59 characters.

### CQA-N-03 — The documented 50-character guarantee is really 59, and 403 shipped cells violate the documented one
- **Severity:** **HIGH**
- **Type:** Confirmed defect (specification vs implementation)
- **Evidence:** `build_zenodo_frozen.py:43` sets `W, STRIDE = 50, 10`, and `Rules.leaks()` probes every 10th character window. A contiguous run of 50–58 characters that starts off-grid is invisible to the builder **and** to `verify_zenodo_frozen.py`, which shares the identical W/STRIDE pair and additionally skips values with `len(v) < W + STRIDE = 60`. A stride-1 scan finds **403** shipped non-KEEP catalogue cells (122 papers, 42 file-column pairs) containing a true contiguous **50–58**-character verbatim run from their own withheld paper — **397** unique to withheld wording, 6 shared with an included paper (permitted). Length buckets 50–54: 291, 55–58: 112. `cells_with_run_ge_59` = **0**, longest run **58**. The same scan finds **759** public-DB non-TEXT cells over 64 table-column pairs (**735** non-shared), led by `term_mention.normalized_mention` 167. The builder's stride-10 probe over that same database returns **0** — proving the blind spot is the stride, not the data.
- **Affected:** 403 catalogue cells / 122 papers; 759 public-DB cells / 735 non-shared. Top catalogue pairs `assays.gap_changes` 67, `cohorts.population_description` 38, `findings.finding_text` 33, `datasets.dataset_description` 28, `findings.author_interpretation` 25.
- **Examples (verbatim, from withheld papers):** `HMPAPER_000006` — "significantly higher in centenarians than controls" (51), "pathway for isoalloLCA had not been described previously" (57), "microbes, including multidrug-resistant pathogens" (50); `HMPAPER_000023` — "animals exposed to both the CRON1 and CRON5 microbiota" (55).
- **Scientific impact:** none.
- **Publication impact:** **major, and asymmetric.** `releases/zenodo_frozen/README.md:67` promises removal of "any other value that reproduces a passage of the paper's wording of 50 characters or more", and line 71 says the independent scan "found no remaining verbatim passage". Both statements are **overstated by 9 characters**. The measured guarantee is **≥59**. A 50–58-character phrase is short; whether it is a legally meaningful excerpt is for counsel, not for this audit. What is documented as verified is not what was verified, and the verification was performed with the same blind spot as the build.
- **Recommended action:** Either (a) change `W, STRIDE` to `50, 1` and re-run the builder and verifier — the cost is a stride-10 → stride-1 slowdown on 1.06 M cells, which is minutes, not hours — or (b) leave the build alone and correct the README to state the guarantee as "59 characters or more" with the stride disclosed. Do not do neither. If the second, the 403 cells should be listed in the release so the residual is disclosed rather than claimed absent.
- **Blocking:** blocks any claim that the release has been verified to the stated threshold. Does not block deposit if the README is corrected.

### CQA-N-04 — Redaction nulls 225 cells on 93 papers that were cleared for inclusion
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (over-redaction)
- **Evidence:** **225** cells across **93 `TEXT_INCLUDED`** papers, **41 `(table, column)` pairs**, **174** detail rows. Cause is rule R3: when a 50-character window at the redaction point also occurs in a *withheld* paper, the value is nulled on the included paper too. Top pairs `term_mention.normalized_mention` 34, `assay.evidence_text` 30, `relation_evidence.source_sentence` 14, `claim.evidence_text` 12, `claim_evidence.evidence_text` 12, `assay.statistical_methods` 8, `claim.taxon_or_feature` 8, `dataset.evidence_text` 8. Top papers `HMPAPER_000421` 14, `HMPAPER_000313` 11, `HMPAPER_000304` 9, `HMPAPER_000031` 7, `HMPAPER_000187` 7. All **34** included-paper `normalized_mention` losses are cross-paper (own-paper window hits 0/34), lengths 50–112, median 80. `HMPAPER_000406` loses 4 cells this way — including `dataset.dataset_url` = `https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA687360` — through a window shared with withheld `HMPAPER_000367`.
- **Affected:** 225 cells; **93 / 274 = 33.9%** of included papers touched.
- **Scientific impact:** small but real: 30 nulled `assay.evidence_text` and 34 nulled `normalized_mention` cells reduce the evidence base for papers a reader *is* allowed to read.
- **Publication impact:** minor; the loss is not visible in any shipped report and no aggregate count changes materially.
- **Recommended action:** Narrow R3 to require the window to fall inside the *withheld* paper's own quote span, rather than anywhere in its text; re-run and diff. Failing that, log R3 subsets per paper so the 132 unlogged cells are attributable. Note the values are **not recoverable from the public bundle** — they survive only in the internal CDM, so this must be fixed before any future rebuild, not after.
- **Blocking:** neither.

### CQA-N-05 — `TECHNICAL_VALIDATION.md` states an invariant that is false
- **Severity:** **HIGH**
- **Type:** Confirmed defect (truthfulness)
- **Evidence:** `validation/TECHNICAL_VALIDATION.md:3` — "Redaction removes text only; it changes no identifier, value count or link." Measured source→public losses, all from withheld papers except two, total **≥2,136** identified cells: `dataset.repository_accession` 1, `repository_accession_original` 6, `data_asset.accession_original` 6, `dataset.dataset_url` 36 (35 withheld + 1 included), `data_asset.repository_url` 37 (36 + 1), `paper.full_text_url` 1, `dataset.license_or_terms` 17, `data_asset.license_or_terms` 5, `dataset.dataset_title` **164**, `relation.subject_display_label` 25,788 → 25,218 (570), `object_display_label` → 24,896 (892), `canonical_term.term` **927**, `term_norm` **338**. Additionally `type_harmonization.context` 40,141 → 0 in the public DB.
- **Affected:** ≥2,136 identified cells, spanning identifiers, URLs, titles and term labels.
- **Scientific impact:** **moderate** — 927 canonical terms lose their surface label in the public DB, so a term-level join into the public release is ambiguous for 927 / 162,409 = 0.57% of terms.
- **Publication impact:** **major.** The statement is in the bundle's own validation document. A reader who relies on it will assume a 1:1 cell mapping between source and public, which is false on at least 63 accession/URL cells and 927 term labels.
- **Recommended action:** Correct the sentence to the measured form: text removal, plus a bounded set of identifier/value losses on withheld papers, with the table. The 927 / 338 `canonical_term` losses are **unattributed to any paper** (tables without `paper_id`), so they need their own explanation, not inclusion in the "withheld papers" bucket.
- **Blocking:** neither, but it should not ship as-is.

### CQA-N-06 — `RESTRICTED_NC_LAYER` is a decision category with no artefact
- **Severity:** **MODERATE**
- **Type:** Documentation gap
- **Evidence:** `rights_summary.json` reports `RESTRICTED_NC_LAYER` 15 (12 `cc by-nc` + 3 `cc by-nc-sa`); `build_zenodo_frozen.py:131` withholds everything where `proposed_release_decision != "INCLUDE_TEXT"`, so the 15 are indistinguishable from the 164 in the shipped bundle. No `KEEP_NC` token appears anywhere in the build code; there is no NC layer on disk. Meanwhile the live catalogue retains **1,650** `KEEP_NC` rows unflagged and **1,645** `evidence_text` cells in place.
- **Affected:** 15 papers / 3.3% of the corpus; 1,650 catalogue rows.
- **Scientific impact:** none.
- **Publication impact:** minor — but a reader of the summary JSON will look for a layer that does not exist, and the 15 NC papers are described as "restricted" in one document and "withheld" in another.
- **Recommended action:** Either implement the layer (ship NC text under an NC-compatible licence) or drop the category from `rights_summary.json` and describe the 15 as withheld with reason `NC_INCOMPATIBLE`. The second is cheaper and honest. Also document why the live catalogue keeps 1,650 `KEEP_NC` rows while the release withholds the same papers — the two policies are defensible (quotation vs full text) but the difference is currently unexplained.
- **Blocking:** neither.

### CQA-N-07 — Non-KEEP `gap_evidence` is re-serialised and silently loses its `quote` key
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (data loss masked as formatting)
- **Evidence:** source `gap_evidence` is uniformly **invalid JSON** — Python `repr`, `json_invalid` on all rows: KEEP 8,687, `KEEP_NC` 454, REDACT 4,933. Source `has_quote`: KEEP 7,501 / `KEEP_NC` 409 / REDACT 4,097. Shipped: KEEP still `json_invalid` 8,686 (`has_quote` 7,500); **`KEEP_NC` 454 are now valid JSON with 0 invalid and 0 `quote`**; **REDACT 4,933 valid JSON, 0 `quote`**. The `quote` and `conflict` keys are stripped by `clean_gap_evidence()` in `build_zenodo_frozen.py`.
- **Affected:** 5,387 shipped rows (`KEEP_NC` 454 + REDACT 4,933) that were pyrepr at source and are JSON at ship; **4,506** rows that had a `quote` at source and have none shipped.
- **Scientific impact:** none for included papers.
- **Publication impact:** minor, but it is a trap for schema consumers: the same column is pyrepr for 274 papers and JSON for 179, so a single parser cannot read the column across the bundle. `KEEP_NC` survivors (454: cohorts 153 / samples 135 / assays 154 / datasets 12) are pure `{field: {section_id, char_start, char_end}}` offset maps with **0 quotes** — which is correct behaviour, but indistinguishable from "no quote was found".
- **Recommended action:** Serialise `gap_evidence` as JSON uniformly in the source build, and add a `quote_suppressed: true` marker on the non-KEEP rows rather than dropping the key. One line each; the alternative is a permanently unparseable column.
- **Blocking:** neither.

### CQA-N-08 — 946 extracted values survive in withheld papers, 85 of them verbatim excerpts
- **Severity:** **MODERATE**
- **Type:** Confirmed residual (bounded)
- **Evidence:** Non-KEEP `gap_changes` cells whose `'new'` value is ≥30 characters: **946** over all six change-log tables (assays 454 / cohorts 226 / samples 232 / datasets 17 / findings 16 / data_assets 1). *[corrected by `CQA-N-AMEND-2026-11-05-1` — this sentence previously read "**930**" with the breakdown "cohorts 226 / samples 232 / assays 454 / datasets 17 / data_assets 1", which enumerated five tables and omitted `findings.csv`; findings contributes 16 cells. See §6]* Maximum in the non-KEEP set is **480** characters (`HMPAPER_000079`, `cohorts.exclusion_criteria`; the 1,490 maximum belongs to a KEEP row). Length buckets: 30–39: **513**, 40–49: **208**, 50–59: **117**, 60+: 108. *[corrected by `CQA-N-AMEND-2026-11-05-1` — previously 501 / 205 / 116 / 108, the same five-table subset]* Of the **225** non-KEEP values ≥50 characters, **85 are verbatim substrings of their own paper's `section_text_original`**, representing **33 distinct strings across 28 papers** (e.g. `HMPAPER_000123` "PowerSoil DNA isolation kit (MoBio, Carlsbad, California)", 57 chars, 9 cells; `HMPAPER_000138` "MoBio Powersoil DNA extraction kits (MoBio, Carlsbad, CA)", 57 chars). *[corrected by `CQA-N-AMEND-2026-11-05-1` — previously "**224** … **84**", the same five-table subset; findings contributes 1 cell ≥50, which is also verbatim]* **1** of the 85 also occurs in an included paper; **140** are not verbatim (reformatted, sentence-cased, or abbreviated). Separately, **103** distinct `(file, column)` pairs / **35,928** cells in withheld papers carry ≥50-character values; excluding `papers.csv` — whose 9 pairs / 917 cells are all bibliographic metadata in `EXEMPT_COLS` — gives **94** pairs / **35,011** cells, which is the scope previously reported without the exclusion being stated. *[corrected by `CQA-N-AMEND-2026-11-05-1` — the sentence previously quoted "94 distinct `(file, column)` pairs / 35,011 cells" as if it were the whole population; see §6]* The population is dominated by `findings.extraction_method` 9,255 — a single 54-character constant `LLM:Qwen/Qwen3.5-4B:cdm-catalogue-ner-v2-noplaceholder`, i.e. provenance, not prose.
- **Affected:** **946** cells ≥30 chars; **85** verbatim own-paper excerpts ≥50 chars, 33 distinct strings. *[corrected by `CQA-N-AMEND-2026-11-05-1` — previously "930 cells ≥30 chars; 84 verbatim own-paper excerpts"]*
- **Scientific impact:** none.
- **Publication impact:** **minor but real.** The 85 verbatim excerpts are short phrases embedded in a change-log structure — they are not bulk text, and they reduce to 33 distinct strings. **All 85 are under 60 characters**, longest 57 (`<60`: 85, `≥60`: 0), which is exactly why the release's stride-10 scan, which skips strings shorter than 60, did not catch them. *[corrected by `CQA-N-AMEND-2026-11-05-1` — previously "84 … All 84 are under 60 characters (`<60`: 84, `≥60`: 0)"]* Whether they matter is a judgement for counsel.
- **Recommended action:** Add `gap_changes` to the redaction rule set for non-KEEP papers — the column is a change log, not evidence, and it currently escapes `TEXT_COLS` entirely. Alternatively null the `new` field on non-KEEP rows and keep `original`/`source`, which preserves the audit trail (what changed, and by which pass) without the value.
- **Blocking:** neither. Note the 85 are a subset of the CQA-N-03 phenomenon, not a separate class. *[corrected by `CQA-N-AMEND-2026-11-05-1` — previously "84"]*

### CQA-N-09 — 849 REDACT and 68 KEEP_NC `finding_text` cells survive, 218 of them ≥50 characters
- **Severity:** **MODERATE**
- **Type:** Confirmed residual (bounded, partially explained)
- **Evidence:** `finding_text` is **not in `TEXT_COLS`** — only the W=50 window rule applies to it. Shipped survivors: REDACT **849** (min 5 / median 39 / p95 95 / max 234; 218 ≥50, 178 ≥59); `KEEP_NC` **68** (min 5 / median 38 / p95 69 / max 122; 9 ≥50, 6 ≥59); KEEP 15,012 (min 3 / median 141 / max 3,007). Source REDACT `finding_text` was 8,458 non-empty rows (min 5 / median 140 / max 2,598; 7,827 ≥50), so 90.0% were removed.
- **Affected:** 917 surviving cells / 164+15 papers; 227 at ≥50 characters.
- **Scientific impact:** none.
- **Publication impact:** minor. The 178 REDACT survivors at ≥59 characters are *not* verbatim runs (CQA-N-03's stride-1 scan covers them and finds 0 at ≥59), so they are extracted-and-reformatted findings, not quotations. That is a defensible position for a derived annotation, but it is not the position the README takes for `finding_text`, which is treated as text.
- **Recommended action:** Decide whether `finding_text` is text or annotation. If annotation, say so in the README and stop applying the 50-char rule to it; if text, add it to `TEXT_COLS` — which would remove all 917. The current state is a rule applied inconsistently by column.
- **Blocking:** neither.

### CQA-N-10 — The upload metadata still carries 7 `TODO` placeholders and the README has author blanks
- **Severity:** **MODERATE**
- **Type:** Confirmed incompleteness
- **Evidence:** `releases/ZENODO_UPLOAD_METADATA.json` — `_instructions`, `metadata.publication_date` (`TODO (date of upload)`), `metadata.creators[0..2].orcid` (`TODO (add)`), `metadata.license` (`TODO: confirm (proposed cc-by-4.0)`), `metadata.related_identifiers[1].identifier` (`TODO: DOI of the article (after acceptance)`). Shipped `releases/zenodo_frozen/README.md` differs from `src/scripts/release/ZENODO_README.md` **only at lines 104–106**, where the shipped copy has `**[AUTHORS: add the article citation and this dataset's DOI after deposit.]**` in place of the full citation/DOI/code block; it also contains `[AUTHORS TO CONFIRM BEFORE UPLOAD]` (7,249 B vs 7,475 B).
- **Affected:** 7 metadata fields; 2 README placeholders.
- **Scientific impact:** none.
- **Publication impact:** **blocking for deposit only.** In particular `metadata.license` is unresolved: a bundle containing 274 third-party papers under mixed CC variants cannot be deposited under a single blanket licence without deciding what that licence covers.
- **Recommended action:** Resolve all 7 before upload. The licence question is the substantive one — the bundle contains (a) third-party paper metadata, (b) third-party paper text under per-paper CC licences, and (c) this project's own derived annotations. These are three different licensing regimes and the deposit needs to say which applies to which, rather than proposing `cc-by-4.0` for the whole.
- **Blocking:** blocks the deposit. Does not block the audit or the manuscript.

### CQA-N-11 — The two tables that encode the rights decisions are the only undocumented ones
- **Severity:** **MODERATE**
- **Type:** Confirmed documentation gap
- **Evidence:** `cdm/CDM_COLUMN_DICTIONARY.csv` has **866 rows over 44 tables** and **0 rows** for `release_rights` or `release_redaction`, which are the two tables the public DB adds. Across the 866 documented columns, `definition_status` is `NEEDS_EXPERT_REVIEW` **644 (74.4%)**, `DEFINED_IN_CODE` 143, `DOCUMENTED` 33, `EXTERNAL_SOURCE_DEFINITION` 26, `SOURCE_DOCUMENTED_MEANING_NEEDS_REVIEW` 20.
- **Affected:** 2 / 46 shipped tables undocumented (100% of the rights tables); 74.4% of columns un-defined.
- **Scientific impact:** none.
- **Publication impact:** minor on its own, but it compounds CQA-N-02: the *only* mechanism by which a consumer can learn that a cell was redacted is a table with no documentation.
- **Recommended action:** Document `release_rights` and `release_redaction` first — they are small, load-bearing, and the least ambiguous. The 644 `NEEDS_EXPERT_REVIEW` columns are a longer project and should not gate the release.
- **Blocking:** neither.

### CQA-N-12 — 3,914 logged cells point at terminology files that were deleted at finalize
- **Severity:** **LOW**
- **Type:** Confirmed artefact (benign, undocumented)
- **Evidence:** `release_redaction` targets `terminology/canonical_terms.jsonl` (1,313), `term_definitions.jsonl` (418), `term_ontology_mappings.jsonl` (1,944) and `.provenance` (239) — 3,914 cells, all `exists=False`. `finalize_zenodo_frozen.py:61-64` deletes these files and re-exports the same tables from the public DB as `.csv.gz`.
- **Affected:** 3,914 of the 2,103,395 logged cells (0.19%).
- **Scientific impact:** none.
- **Publication impact:** none; the log's own 3,914 + 27,226 + 2,072,254 + 1 = 2,103,395 total is arithmetic, not four independent removals.
- **Recommended action:** Mark the four deleted targets as `superseded_by: <csv.gz path>` in the log so the sum is not read as additive. One line in the README would do.
- **Blocking:** neither.

### CQA-N-13 — Withheld section rows keep their source text hash, which fingerprints the withheld text
- **Severity:** **LOW**
- **Type:** Potential risk (disclosed rather than mitigated)
- **Evidence:** source `section` n=4,006: `sha256(b"")` sentinel 453, real hash 3,553. Public included n=2,639: empty 274, real 2,365. Public withheld n=1,367: text NULL on **1,367 / 1,367**, `text_hash_sha256` retained on **1,367 / 1,367** (empty-state 179, real 1,188). `included_hash_mismatches` **0**, `included_text_length_mismatches` **0**.
- **Affected:** 1,188 withheld sections retain a real content hash.
- **Scientific impact:** none.
- **Publication impact:** negligible — a hash is not the text, and verifying a candidate against it requires already possessing the text.
- **Recommended action:** none required. Record it as a deliberate design choice: retaining the hash is what lets a reuser prove that a reconstructed text matches the withheld original, which is a *useful* property. The only caveat is that it confirms membership, so a party holding a suspect corpus can confirm inclusion.
- **Blocking:** neither.

### CQA-N-14 — 927 public `canonical_term.term` and 338 `term_norm` values are null, and none is attributable to a paper
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (unattributed loss)
- **Evidence:** `canonical_term.term` source 162,409 → public 161,482 (**927 lost**); `term_norm` → 162,071 (**338 lost**, a subset). Both are recorded as `lost_by_layer: UNATTRIBUTED_no_paper_id` — `canonical_term` has no `paper_id`, so the redaction log cannot say which withheld paper (or which included paper) caused the loss. Also `term_concept_map.mapping_provenance` 331,394 → 331,142 (252 lost), same class.
- **Affected:** 927 / 162,409 = **0.57%** of canonical terms have no surface label in the public DB; 338 have no normalised form.
- **Scientific impact:** **moderate** — a term without a surface label cannot be displayed or matched by string; a consumer must fall back to `term_id`, which the bundle does provide.
- **Publication impact:** minor for the audit, moderate for reuse: term-level joins between the public DB and the terminology release (`canonical_terms.jsonl`, 165,991 rows = 162,409 live + 3,582 `removed_canonical_term`) silently drop 927 rows on the `term` key.
- **Recommended action:** Either restore the 927 labels (they are derived terms, not quotations — the loss looks like an over-broad rule applied to a key column, which is exactly the CQA-N-05 failure mode) or document the null as `REDACTED_UNATTRIBUTED`. The 43,691 unattributed cells in total deserve one paragraph in the README.
- **Blocking:** neither.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates:**
- One rule was applied everywhere: matrix → catalogue → shipped layer agrees **453 / 453**, with **0** real licence mismatches and a clean `quote_policy × decision` bijection.
- The `evidence_redacted` flag is fully understood: **18,502** flagged of **18,582** REDACT rows at source, all **20,232** non-KEEP rows flagged at ship, and the residual **244** resolved exactly as 164 `papers.csv` + 80 `NO_QUOTE`.
- The redaction log reconciles **exactly**: DB **2,072,254 / 156 pairs / 0 mismatched**; catalogue **27,226 = 21,838 + 5,388** with **0 observed-only**; the **43,691** unattributed cells are 15 pairs on tables without `paper_id`.
- The independent scan is genuine — 6,136,425 strings over 299 files, **0 unexplained hits**, manifest **299 / 299**.
- The zero-character background is clean: included sections have **0** length mismatches and **0** hash mismatches across 2,639 sections.
- The guarantee's real boundary: **0** runs at ≥59 characters; **403** catalogue cells and **759** DB cells carry 50–58-character runs that the builder's stride-10 probe cannot see.

**Does not establish:**
- That the rights decisions are correct, or that any of the 179 pending papers may or may not be redistributed. **No reviewer, no final decision, no decision evidence exists on any row.**
- That 50 characters is a legally safe excerpt length — or that 59 is. This component measures what the code does; it does not adjudicate fair use, quotation exceptions, database rights, or derivative-work status.
- That the withheld layer is free of *all* residual content. **946** `gap_changes` cells and 917 `finding_text` cells survive, **85** of the former verbatim; they are bounded and mostly reformatted, but they are content. *[corrected by `CQA-N-AMEND-2026-11-05-1` — previously "930 … 84"]*
- That the CDM is publishable. It is not: it holds the unredacted original of 18,502 flagged cells with no on-row marker.

---

## 5. Component verdict

The rights machinery is the **best-engineered and least-decided** part of this project, and those two facts
point in opposite directions.

Where the question is *mechanical* — did one rule produce consistent outputs across four artefacts, can
every removed cell be accounted for, does the scan actually scan — the answers are unusually good. Three
layers agree on 453 of 453 papers. The log reconciles to the cell: 2,072,254 logged, 2,072,254 observed,
zero mismatched, and the 43,691 that cannot be attributed turn out to be a schema property rather than a
failure. The catalogue side reconciles too: 27,226 = 21,838 exact + 5,388 partial, with nothing observed
that was not logged. That is not the normal state of a release pipeline.

Where the question is *judgement*, almost nothing has happened. **Zero of 453** papers have a named
reviewer, a final decision, a publisher record or decision evidence. **179** papers — 39.5% of the corpus,
10.0 M characters — ship withheld pending a review whose four sub-questions (quotation exception,
derivative work, NC compatibility, share-alike) need different expertise and are currently routed as one
undifferentiated `PENDING` state. The audit can say the pipeline is disciplined about a decision it has not
made; it cannot say the decision is right, and it must not let the discipline imply that.

Three defects matter most, and they are of different kinds.

The **guarantee** is the one that will be quoted against the release. The README promises 50 characters and
the code delivers 59, because the builder probes on a 10-character stride and the "independent" verifier
copies the same stride and then skips anything shorter than 60. 403 shipped cells carry true 50–58-character
verbatim runs from withheld papers; six are shared boilerplate, 397 are not. The fix is either a stride of 1
or a corrected README, and the second is free.

The **flag** is the one that will be quoted against the CDM. `evidence_redacted` exists in six CSVs and in
no database. The DB that ships is the one holding the unredacted text, so a deposit of "the CDM" republishes
18,502 privileged cells and nothing in the schema can detect it. This is `CQA-F-01` from the data side; from
the rights side it is the single property that separates a publishable internal database from an unpublishable
one.

The **claim** is the one that damages least and signals most. `TECHNICAL_VALIDATION.md` says redaction
"changes no identifier, value count or link", and at least 2,136 cells say otherwise — 927 canonical terms
without a label, 164 datasets without a title, 63 accessions and URLs gone, 570 and 892 display labels gone.
None of those losses is large; together they falsify the one sentence in the bundle a rights-conscious
consumer would rely on.

The component's verdict is therefore split in the same shape as the rest of the audit: **the process is
STRONG, the adjudication is a CRITICAL WEAKNESS, and the description of what was done is WEAK.** The cheapest
high-value actions are documentation — correct the 50-character claim, correct the "no identifier changes"
claim, record the 18,502 figure in the dictionary, drop or implement `RESTRICTED_NC_LAYER`. The expensive one
is the 179-paper review, and no amount of engineering substitutes for it.

---

## 6. Amendment record

*[added 2026-11-05 by `CQA-N-AMEND-2026-11-05-1`; the body of this report above is preserved as written, with
in-place `*[corrected …]*` markers pointing here]*

### `CQA-N-AMEND-2026-11-05-1` — four figures corrected, one scope made explicit (reporting only)
- **Date:** 2026-11-05
- **Type:** reporting defects in this audit, **not** data defects. No artefact, release, count in the
  underlying data or dimensional rating changes. `CQA-N-08` keeps **MODERATE**; the component's split verdict
  (process STRONG / adjudication CRITICAL WEAKNESS / description WEAK) is unaffected.
- **Reproducer:** `diagnostics/cqa_n_rights.py:gap_changes_values()`, new in this amendment, emitting
  `gap_changes_values` in `diagnostics/results/cqa_n_rights.json`. Before this amendment the `gap_changes`
  enumeration had **no reproducer on disk** — it was an ad-hoc probe — which is how the omissions below
  survived review.

#### A. `gap_changes` counts enumerated five tables and silently omitted `findings.csv` (affects `CQA-N-08`)
- **Was:** **930** cells ≥30 chars (cohorts 226 / samples 232 / assays 454 / datasets 17 / data_assets 1);
  **224** cells ≥50 chars; **84** verbatim; buckets 30–39: 501, 40–49: 205, 50–59: 116, 60+: 108.
- **Now:** **946** cells ≥30 chars (assays 454 / cohorts 226 / samples 232 / datasets 17 / **findings 16** /
  data_assets 1); **225** cells ≥50; **85** verbatim; buckets 30–39: **513**, 40–49: **208**, 50–59: **117**,
  60+: 108.
- **Arithmetic:** `findings.csv` carries a `gap_changes` column and contributes exactly **16** cells ≥30
  characters, **1** of which is ≥50 characters (`HMPAPER_000166`, `taxon_or_feature`,
  "Bacillus, Bilophila, Barnesiella, and Enterococcus", 50 chars) and is verbatim in its own paper.
  `930 + 16 = 946`; `224 + 1 = 225`; `84 + 1 = 85`; `501 + 12 = 513`; `205 + 3 = 208`; `116 + 1 = 117`;
  `108 + 0 = 108`. Every delta is the findings contribution; no other table's count moved.
- **Why it happened:** the ad-hoc probe iterated a hand-written five-file list rather than every shipped CSV
  exposing a `gap_changes` column. The new generator enumerates
  `sorted(os.listdir(SHIP_CAT))` and skips only files lacking the column, so the omission cannot recur.
- **Direction:** **undercount**, i.e. the audit *understated* residual content. The correction makes the
  finding marginally worse, not better, and does not change its severity: 1 extra cell in 225.
- **Consequential figures checked:** "all 85 under 60 characters" — **true** (longest 57, so `≥60`: 0); the
  "1 also occurs in an included paper" — **true** (unchanged; the findings cell is not that one); "140 not
  verbatim" — recomputed as `225 − 85 = 140`, **true**, and unchanged because both terms moved by 1.
- **New detail added (not a correction):** the 85 cells reduce to **33 distinct strings across 28 papers**,
  so the residual is more repetitive than a raw cell count implies.

#### B. `94 (file, column) pairs / 35,011 cells` quoted without the exclusion that produces it (affects `CQA-N-08`)
- **Was:** "94 distinct `(file, column)` pairs / 35,011 cells in withheld papers carry ≥50-character non-text
  values".
- **Now:** "**103** distinct `(file, column)` pairs / **35,928** cells in withheld papers carry ≥50-character
  values; excluding `papers.csv` — whose 9 pairs / 917 cells are all bibliographic metadata in `EXEMPT_COLS` —
  gives **94** pairs / **35,011** cells".
- **Arithmetic:** `103 − 9 = 94`; `35,928 − 917 = 35,011`. The 9 excluded pairs are
  `papers.authors` 140, `full_text_source` 179, `source_database` 179, `title` 169, `field_sources` 143,
  `full_text_url` 77, `journal` 17, `keywords` 11, `exclusion_reason` 2.
- **Why it happened:** the exclusion is *correct* — those columns are exempt from redaction by design — but it
  was applied in the probe and not stated in the sentence, so the figure reads as the whole population when it
  is a filtered one. No definition reproduces `94 / 35,011` without excluding `papers.csv` (tested: `len(raw)`
  vs `len(ws)`, with and without `*_id`/`evidence_redacted`, with and without `TEXT_COLS`, at thresholds
  50/51/52/60 — all give `103 / 35,928`, `101 / 35,708`, `100 / 35,429` or `87 / 23,593`).
- **Direction:** scope now stated; no value changed for the filtered set.

#### C. Withheld-character total replaced by the reconciled sum (affects `CQA-N-01`)
- **Was:** §3 `CQA-N-01` Affected line quoted the withheld layer's character count from a single decision
  class.
- **Now:** **9,974,210** characters = `WITHHOLD_TEXT` 9,188,416 + `RESTRICTED_NC_LAYER` 785,794 = **37.2%**
  of all section text.
- **Why:** the 15 NC/NC-SA papers are shipped `TEXT_WITHHELD` (see `CQA-N-06`) but are recorded under a
  separate decision class in `releases/zenodo_frozen/release_rights`. Quoting only one class understates the
  withheld layer by 785,794 characters. Both classes were already resolved in
  `diagnostics/results/d12_rights_readiness.json:db_section_text_chars_by_decision`; the fix is additive.
- **Consequential figure checked:** §5's "10.0 M characters" derives from the same sum and is correct; the
  37.2% is `9,974,210 / 26,781,631` (the SQL total, which stops at U+0000 — 37.11% against the Python total
  26,874,831). Both percentages are stated in `CQA-N-01`'s neighbourhood; neither is wrong, but a reader
  must know which denominator applies.

#### D. Superseded values left in place
Nothing was deleted. The superseded strings above remain readable in this record, and each corrected cell in
§3 and §4 carries an inline `*[corrected by `CQA-N-AMEND-2026-11-05-1` …]*` marker with the previous value, per
the additive-correction rule. `grep -n "930\|224 non-KEEP\|84 are\|35,011"` over this report now returns only
§3's marked text and this §6.

#### E. Figures re-verified as unchanged
Independently reproduced while writing this amendment and **not** corrected: 18,502 flagged rows; 18,582
REDACT rows; 80 `NO_QUOTE`; 244 = 164 + 80; 20,232 shipped non-KEEP rows; 2,072,254 logged = observed over
156 pairs; 27,226 = 21,838 + 5,388 with 0 observed-only; 225 over-redacted cells over 93 papers / 41 pairs /
174 detail rows; 403 catalogue cells and 759 public-DB cells in the 50–58 band with `≥59`: 0; 849 REDACT and
68 KEEP_NC `finding_text` survivors (218 and 9 at ≥50); 917 surviving `finding_text` cells total; 9,188,416
and 785,794 per-decision character counts; `max_len_any` 480 for non-KEEP `gap_changes` and 1,490 for KEEP.

#### F. Downstream effects
- `15_ISSUE_REGISTER.csv` rows `CQA-N-01` and `CQA-N-08` were regenerated from the corrected report; their
  `title`, `evidence_summary` and `affected_proportion` fields now carry 946 / 85 and 9,974,210. Severity
  unchanged for both.
- No other component report quotes these figures (`grep -rn "930\|35,011"` over the audit tree, excluding
  this report and the register, returns nothing).
- `16_QUALITY_METRICS.csv` does not yet exist; when built it must read the corrected values.
- No frozen release, manifest or validation result was touched. This amendment is documentation only.
