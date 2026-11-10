# Component K — BugSigDB Comparison Quality

**Audited object:** `outputs/results/benchmark/bugsigdb_comparison_2026-11-03/` — the comparison of
the catalogue and triple layers against **BugSigDB** over the **47 papers** that both resources
contain, plus `summary.json`, `items.jsonl` (2,989 items) and `scoring_schema.json`.
**Evidence base:** `summary.json` (all fields, all verdicts), `items.jsonl`, the shipped
`protocol: scoring_schema.json v1.0`, the BugSigDB export record
(`BugSigDB 2026-11-03_07:58_UTC, License: Creative Commons Attribution 4.0 International`,
`https://bugsigdb.org`), and the taxonomy snapshot (`2026-11-01`).
**Independence:** coverage, support, direction and field-concordance figures were recomputed from
the per-item verdicts and the reported denominators; the chance baselines were re-derived from the
stated population (1,537 BugSigDB items / 667 of ours / 47 papers) rather than assumed.

> **What this comparison is.** BugSigDB is a **human-curated** database of differential-abundance
> signatures: for a paper, it records which taxa were found enriched or depleted, with a body site,
> a condition and a direction. It is therefore the closest thing to a gold standard the project has
> — but it is a **partial** one: it covers only papers it has curated, only signature-level taxa,
> and only abundance-direction statements. **A taxon absent from BugSigDB is not a wrong taxon**, and
> the report itself says so. This comparison is Tier 2 (external-reference grounding), not Tier 1.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Paper matching | **STRONG** | 47 of 453 papers matched: **PMID 266 + DOI 4** = 270 matched on PMID alone, 4 additional on DOI. BugSigDB export is versioned and dated, and the licence (CC BY 4.0) is recorded in the artefact | match coverage **47 / 453 = 10.4%** of the corpus; identifier basis **98.5% PMID** | PMID matching is exact and auditable. The 10.4% is not a matching failure — BugSigDB has curated only 47 of these papers — but it does bound what the comparison can say about the rest | High |
| Reference integrity | **STRONG** | Export timestamped to the minute, licence stated, `scoring_schema.json` named as the protocol, item-level records written, `code_sha256` recorded, all verdicts enumerated | reference provenance **complete** (source, version, licence, protocol, code hash) | No `MANIFEST.sha256` for this directory, so the item file itself is unhashed — a small gap in an otherwise clean provenance chain | High |
| Coverage of BugSigDB signatures | **ADEQUATE** | 1,537 BugSigDB taxa items; **361 MATCH + 65 PARTIAL**, 1,111 MISMATCH → coverage **27.72%** (Wilson 25.54–30.01; paper bootstrap 21.53–35.84); **chance 8.97%**, chance-corrected **20.6%**; exact (not genus-collapsed) coverage **23.49%** | coverage **27.72% vs 8.97% chance = 3.1×**; exact coverage 23.49% | "Coverage" is the share of BugSigDB's curated taxa that our extraction also reports. It is a **recall-like** quantity **only for the subset BugSigDB curates** — i.e. signature taxa in 47 papers. It says nothing about the other 406 papers, and nothing about taxa BugSigDB did not record | High |
| Support of our taxa | **ADEQUATE** | 667 of our taxa items in those papers: **MATCH 361 + PARTIAL 21**, NOT_IN_REFERENCE 285 → support **57.27%** (53.49–60.97; bootstrap 48.04–67.09); **chance 18.1%** | support **57.27% vs 18.1% chance = 3.2×** | Support is "of the taxa we report in these papers, how many BugSigDB also lists". It is **precision-like only against BugSigDB's scope**: a correct taxon that is not a differential-abundance signature is counted NOT_IN_REFERENCE | High |
| Direction agreement | **ADEQUATE** | Of 667 items, **261 determinable** (165 UNDETERMINED): **SAME 201, OPPOSITE 60** → **77.01%** same (71.54–81.70; bootstrap 66.36–86.45); post-hoc chance **51.96%** | direction agreement **77.0% vs 52.0% post-hoc chance** on 261 items | 60 opposite-direction calls is a substantial minority and is **not** broken out by taxon, body site or condition, so the audit cannot say whether they concentrate anywhere. The 165 UNDETERMINED (24.7%) are silently outside the rate | High |
| Field concordance (rule-based) | **ADEQUATE** | Nine fields compared against BugSigDB, each with completeness, concordance, Wilson CI, bootstrap CI and a chance baseline: `sequencing_type` 48/1.000 (chance 0.962), `region_16s` 45/0.977 (0.348), `platform` 47/1.000 (0.939), `country` 50/0.940 (0.212), `condition` 55/0.927 (0.050), `statistical_test` 58/0.857 (0.440), `group_size` 176/0.5625 (0.063), `group_name` 249/0.5422 (0.050), `body_site` 57/0.2456 (0.050) | strong: sequencing_type, platform, region_16s, country, condition (0.94–1.00); weak: **body_site 0.246**, group_name 0.542, group_size 0.563 | Several "strong" fields have chance baselines near 0.95 (sequencing_type 0.962, platform 0.939), so 1.000 is **close to no information** — the corpus is overwhelmingly 16S on Illumina, and agreement is the base rate. Only `condition` (0.927 vs 0.05) and `country` (0.94 vs 0.21) are genuinely informative | High |
| Statistical treatment | **STRONG** | Wilson interval + paper-level bootstrap on every rate; chance baseline for every field; chance-corrected values; **post-hoc analyses explicitly labelled** (`posthoc_direction_chance`, `posthoc_strict_set_equal`, `posthoc_coverage_by_source`) | CI on **100%** of reported rates; post-hoc labelling **100%** | The post-hoc direction chance of 51.96% is computed *after* seeing the data and is labelled as such — correct practice, but it means the 77%-vs-52% contrast is not a pre-registered test | High |
| Adjudication / human review | **CRITICAL** | Every field carries `"adjudication": {}` — **empty in all nine**. There is no second curator, no disagreement resolution, no spot-check. Taxa verdicts (MATCH/PARTIAL/MISMATCH) are rule-produced; nothing was human-confirmed | adjudicated items **0 / 2,989 = 0.00%** | The protocol has an adjudication slot and it was never used, which is honest but leaves the whole comparison single-instrument. Where a rule mis-parses a taxon name, no reviewer catches it | High |
| Ontology currency | **ADEQUATE** | Taxonomy snapshot **2026-11-01**; BugSigDB overlap **668 distinct taxa**, **8 absent from the snapshot** (e.g. 1532, 81850, 155615, 424536), **660 with a name**, **0 name differences** from current; full BugSigDB dump **8,479 taxa, 71 absent** from the snapshot | snapshot staleness **8 / 668 = 1.2%** of overlapping taxa; **71 / 8,479 = 0.84%** of the full dump | The comparison is against a snapshot two days older than the export, which is negligible. The "our ontologies are newer" question is answered here **by measurement, not assertion**: 0 name differences, 8 missing ids | High |
| Generalisation | **WEAK** | 47 / 453 papers = **10.4%**; 667 of our taxa items; 261 determinable directions. Post-hoc coverage by BugSigDB source shows the comparison is dominated by figures (754 items, 27.6%) and supplements (660, 22.1%), with tables (105, 51.4%) and text (18, 100%) far smaller | corpus coverage **10.4%** of papers | The 47 papers are not a random sample — they are the papers BugSigDB chose to curate, which skews toward well-known, well-studied studies. A 57% support rate on that subset is plausibly the *best case* in the corpus | High |

**No averaged score is computed.**

---

## 2. The numbers

### 2.1 Taxa

| Quantity | Value | 95% interval | Chance |
|---|---:|---|---:|
| BugSigDB items compared | 1,537 | — | — |
| Our items in the same papers | 667 | — | — |
| Coverage (our taxa present in BugSigDB) | **27.72%** (361 MATCH + 65 PARTIAL) | 25.54–30.01 (Wilson); 21.53–35.84 (bootstrap) | 8.97% |
| Coverage, chance-corrected | 20.6% | — | — |
| Exact coverage (no genus collapse) | 23.49% | 21.44–25.67 | — |
| Support (our taxa listed in BugSigDB) | **57.27%** | 53.49–60.97; 48.04–67.09 | 18.1% |
| Direction determinable | 261 / 667 | — | — |
| Direction SAME | **77.01%** (201/261) | 71.54–81.70 | 51.96% (post-hoc) |

**Read as a pair, this is the most favourable external result in the audit**: 3.1× chance coverage
and 3.2× chance support, on an independently curated human reference, with interval overlap nowhere
near. It is also the only comparison in the project where the chance baseline is appropriate to the
question.

### 2.2 Fields

| Field | Items | Completeness | Concordance | Chance | Informative? |
|---|---:|---:|---:|---:|---|
| `sequencing_type` | 48 | 1.000 | 1.000 | **0.962** | essentially no — base rate |
| `platform` | 47 | 1.000 | 1.000 | **0.939** | essentially no — base rate |
| `region_16s` | 45 | 0.956 | 0.977 | 0.348 | **yes** |
| `country` | 50 | 1.000 | 0.940 | 0.212 | **yes** |
| `condition` | 55 | 1.000 | 0.927 | 0.050 | **yes, strongest** |
| `statistical_test` | 58 | 1.000 | 0.857 | 0.440 | **yes** |
| `group_size` | 176 | 1.000 | 0.5625 | 0.063 | **yes, but weak** (77/176 mismatch) |
| `group_name` | 249 | 1.000 | 0.5422 | 0.050 | **yes, but weak** (114/249 mismatch) |
| `body_site` | 57 | 1.000 | **0.2456** | 0.050 | **yes — and poor** (43/57 mismatch) |

### 2.3 Ontology currency

| Check | Result |
|---|---|
| Taxonomy snapshot | 2026-11-01 (export 2026-11-03) |
| BugSigDB taxa in overlap | 668 distinct |
| Absent from our snapshot | **8 (1.2%)** — e.g. 1532, 81850, 155615, 424536, 541000 |
| Name differs from current | **0** |
| Full BugSigDB dump absent from snapshot | 71 / 8,479 = 0.84% |

---

## 3. Issues

### CQA-K-01 — The comparison covers 10.4% of the corpus and that subset is not random
- **Severity:** **HIGH**
- **Type:** Confirmed scope limitation
- **Evidence:** 47 / 453 papers matched; 667 our-items and 1,537 reference items. BugSigDB curates papers by its own editorial selection, not by sampling. Post-hoc source breakdown: figures 754 items (27.6%), supplements 660 (22.1%), tables 105 (51.4%), text 18 (100%).
- **Affected:** 406 of 453 papers (89.6%) are outside the comparison entirely.
- **Scientific impact:** The 57.27% support rate applies to a curated, well-known subset. Because BugSigDB preferentially curates high-profile studies, the subset is biased toward papers whose taxa are also well known — which inflates both support and coverage relative to the corpus. The **direction** of the bias is knowable; its magnitude is not.
- **Publication impact:** "Validated against BugSigDB" must carry "on the 47 papers BugSigDB covers". A sentence implying corpus-wide validation is false.
- **Recommended action:** Report the 47/453 denominator beside every BugSigDB number. Do not extrapolate.
- **Blocking:** blocks any corpus-wide external-validation claim.

### CQA-K-02 — Nothing was adjudicated; the protocol's adjudication slot is empty in all nine fields
- **Severity:** **HIGH**
- **Type:** Confirmed gap (no human check)
- **Evidence:** `"adjudication": {}` on `sequencing_type`, `region_16s`, `platform`, `country`, `statistical_test`, `group_size`, `body_site`, `condition`, `group_name`. Taxa verdicts are rule-produced. There is one instrument and no reviewer.
- **Affected:** 2,989 items, 9 fields, 1,537 + 667 taxa items.
- **Scientific impact:** Where the matching rule mis-parses a name (e.g. a genus/species collapse, an abbreviation, a strain), nothing catches it. The report *does* report both exact and genus-collapsed coverage (23.49% vs 27.72%), which shows the sensitivity is understood — but it is understood analytically, not by review.
- **Publication impact:** This comparison is rule-based agreement against a human-curated reference. It is not itself human-validated. Say exactly that.
- **Recommended action:** Adjudicate a 10% sample (≈150 items) and report the disagreement rate. The adjudication slot exists; filling it is the cheapest credibility gain available in this component.
- **Blocking:** blocks a "human-validated against BugSigDB" claim.

### CQA-K-03 — `body_site` concordance is 24.6% and the mismatch is unexplained
- **Severity:** **HIGH**
- **Type:** Confirmed weak field
- **Evidence:** 57 items, completeness 1.000, concordance **0.2456** (chance 0.050) — **43 of 57 disagree**. Compare `condition` 0.927 on the same 55-paper population. `group_name` 0.542 (114/249 mismatch), `group_size` 0.5625 (77/176).
- **Affected:** 43 body-site assignments; 191 group-name/size assignments.
- **Scientific impact:** Body site is a first-order microbiome variable; a 24.6% agreement against a human curator in the papers where both exist is the single worst field result in the component. It is consistent with component F's finding that `sample.body_site` is quote-supported on only 43.68% of rows and the controlled vocabulary collapses body sites into few values. Whether the defect is in our normalisation or in the comparison's matching rule is **not determined** — the adjudication slot is empty.
- **Publication impact:** Any body-site-stratified analysis inherits this. "Body site was extracted and normalised" cannot be stated without the 0.246 figure and the 43/57 count.
- **Recommended action:** Manually adjudicate the 57 body-site items — it is a one-afternoon task and it decides whether the defect is ours or the rule's — and report the outcome either way.
- **Blocking:** blocks body-site validation claims.

### CQA-K-04 — Group size disagrees on 77 of 176 items
- **Severity:** **MODERATE**
- **Type:** Confirmed weak field
- **Evidence:** `group_size` 176 items, concordance 0.5625 (99 MATCH / **77 MISMATCH**), chance 0.0634. For comparison `sequencing_type` (48 items) and `platform` (47) agree perfectly.
- **Affected:** 77 group-size assignments.
- **Scientific impact:** This is the same underlying weakness component F measured independently: sample/participant counts are the least reliable numeric fields in the catalogue (184/433 papers exceed 1.5× participant count on the defensible test; outliers up to 481,803). BugSigDB's curator-counted group sizes disagree with ours 44% of the time, which is an **external** confirmation of that finding, not a new one — and it is the strongest external confirmation the audit has for any catalogue defect.
- **Publication impact:** Never report a group-size or sample-size total. Report the disagreement instead.
- **Recommended action:** Report 77/176 as an external count-agreement measurement alongside component F's internal one. They corroborate.
- **Blocking:** blocks group-size claims.

### CQA-K-05 — Three "perfect" fields are at their chance baseline
- **Severity:** **MODERATE**
- **Type:** Confirmed interpretive hazard
- **Evidence:** `sequencing_type` concordance 1.000 with **chance 0.962**; `platform` 1.000 with **chance 0.939**. The corpus is overwhelmingly 16S on Illumina, so agreement is the base rate. In contrast `condition` 0.927 with chance 0.050 is genuinely informative, and the report computes and shows both.
- **Affected:** 95 items across two fields.
- **Scientific impact:** A table row reading "sequencing type: 100% agreement" invites the reader to conclude the extraction is perfect on that field. The correct reading is "the field is near-constant, so agreement is uninformative". The report *does* publish the chance column, which is the right defence — but the ranking a reader takes away will still be wrong unless chance-corrected values are shown in the same column.
- **Publication impact:** If the field table is published, add a chance-corrected column or drop the two constant fields.
- **Recommended action:** Report `concordance − chance` (already computed as `chance_corrected`) in the headline table.
- **Blocking:** neither, if chance is shown.

### CQA-K-06 — Eight BugSigDB taxa are absent from the taxonomy snapshot
- **Severity:** **LOW**
- **Type:** Confirmed currency gap (measured, not asserted)
- **Evidence:** Overlap 668 distinct taxa; **8 absent** from the 2026-11-01 snapshot (1532, 81850, 155615, 424536, 541000, 1505663, 1535326, 1926663); 660 have a name; **0 name differences**. Full dump: 71 / 8,479 absent.
- **Affected:** 8 / 668 = 1.2% of overlapping taxa.
- **Scientific impact:** The project's standing claim is "our ontologies are newer". Here the reference is two days newer and 8 ids are missing from our side — so the claim is **false in this comparison**, by 1.2%. That is a trivial magnitude and a useful demonstration that the question was measured rather than asserted.
- **Publication impact:** Say "our taxonomy snapshot (2026-11-01) lacks 8 of 668 BugSigDB taxa; names agree on all 660 shared". Do not say "our ontologies are newer".
- **Recommended action:** Keep the measurement; it is one of the few places the audit can show a claim being tested rather than repeated.
- **Blocking:** neither.

### CQA-K-07 — Direction agreement rests on 261 of 667 items, and the 60 opposites are not characterised
- **Severity:** **MODERATE**
- **Type:** Confirmed limitation
- **Evidence:** 667 items → **165 UNDETERMINED**, 261 determinable; SAME 201, **OPPOSITE 60** (23.0% of determinable). No breakdown by taxon, body site or condition.
- **Affected:** 261 items; 60 disagreements unexamined.
- **Scientific impact:** 77% agreement is a good result, but a quarter of determinable directions are opposite — and in microbiome literature "increased in cases" vs "decreased" is exactly the variable that flips meaning. Whether the 60 are extraction errors, BugSigDB curation differences, or genuine study heterogeneity is not determined.
- **Publication impact:** Report 201/261 and 60/261, not "77% direction agreement" alone.
- **Recommended action:** Characterise the 60 opposite calls; they are the highest-information error set in the whole component.
- **Blocking:** blocks a direction-accuracy claim.

### CQA-K-08 — The comparison has no manifest, unlike every other benchmark artefact
- **Severity:** **LOW**
- **Type:** Confirmed reproducibility gap
- **Evidence:** `bugsigdb_comparison_2026-11-03/` contains `summary.json`, `items.jsonl`, `scoring_schema.json`, `REPORT.md` — **no `MANIFEST.sha256` and no `PREREGISTRATION.sha256`**, while the Tier-2 triple check and Tier-3 KG check both ship preregistration hashes.
- **Affected:** the whole directory.
- **Scientific impact:** The export is version-stamped to the minute and licence-stated, which is better than most; but the item file that all verdicts derive from is unhashed, so the summary cannot be tied to the items.
- **Publication impact:** Minor. A reviewer can re-derive from `items.jsonl` today and cannot prove it is the same file tomorrow.
- **Recommended action:** Add a manifest at audit time.
- **Blocking:** neither.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates:**
- **47 papers**, matched **266 by PMID + 4 by DOI**, against a dated, CC BY 4.0, licensed reference.
- Coverage of BugSigDB signature taxa **27.72% vs 8.97% chance (3.1×)**; support of our taxa
  **57.27% vs 18.1% chance (3.2×)**; exact coverage 23.49%; chance-corrected coverage 20.6%.
- Direction agreement **77.01% (201/261)** vs 51.96% post-hoc chance, with **60 opposites** and 165
  undetermined.
- Field concordance: `condition` 0.927 and `country` 0.940 are genuinely informative; `body_site`
  **0.246 (43/57 disagree)** and `group_size` **0.5625 (77/176 disagree)** are the weak fields;
  `sequencing_type`/`platform` at 1.000 are at their 0.96/0.94 base rates and carry no information.
- Taxonomy snapshot lacks **8 / 668** BugSigDB taxa with **0** name differences — a measured
  currency check, not an assertion.
- **0 / 2,989** items were adjudicated; the adjudication slot is empty everywhere.

**Does not establish:**
- Any corpus-wide recall, precision, accuracy or completeness figure. 89.6% of the corpus is not in
  the comparison, and the 10.4% that is, is not a random sample.
- That taxa absent from BugSigDB are wrong — the reverse is the project's correct reading and this
  audit adopts it.
- That the 60 opposite-direction calls are errors.
- That `body_site` is wrong in our layer rather than mismatched by the comparison rule; that requires
  the adjudication that was not done.

---

## 5. Component verdict

This is the **strongest external evidence in the project** and it is stronger than the report's own
framing suggests. Three times chance on coverage and 3.2 times chance on support, against a
human-curated reference, with Wilson and bootstrap intervals that do not come near the baseline, is
a real result. The field comparison adds an independent confirmation of two catalogue weaknesses —
body site at 24.6% and group size at 56% — that component F found by a completely different method.

What it is not is validation of the corpus. Forty-seven papers is 10.4%, the sample is BugSigDB's
editorial choice rather than a random draw, and **not one item was adjudicated** — the protocol has
the slot and left it empty. The body-site result in particular cannot be assigned to our layer or to
the matching rule until someone looks at 57 rows.

So: quote the 3.1× and 3.2×, quote the 47/453, quote the 0.246 body site, and quote the 77/176 group
size. Do not quote "validated against BugSigDB" without all four.
