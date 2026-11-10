# Component L — Triple Reference Validation

**Audited object:** the pre-registered external-reference checks of the triple layer —
`outputs/results/benchmark/triple_reference_check_2026-11-03/` (BugSigDB + CTD; 518 + 49 + 7 items)
and the overlapping run in `outputs/results/kg_2026-11-04/gold_kg_check/` (BugSigDB + Disbiome + CTD
on resolved edges).
**Evidence base:** `REPORT.md`, `summary.json`, `items.jsonl`, `scoring_schema.json`,
`PREREGISTRATION.sha256`, `MANIFEST.sha256` (4/4 verified) in the Nov-3 run; `summary.json`,
`REPORT.md`, `PREREGISTRATION.sha256`, `edge_support.csv.gz`, `code_sha256` in the Nov-4 run; and the
relation populations in `d08_triple_semantics.json`.
**Independence:** every rate, interval and denominator below was recomputed from the per-item
verdicts. The two runs were compared field by field because they answer the same question with
different reference sets.

> **The rule this component must obey.** A triple absent from BugSigDB, CTD or Disbiome is
> **untested, not incorrect**. All three references cover a narrow slice of microbiome literature,
> and none covers `OTHER_RELATION` — 68.7% of the graph. Support rates here are **coverage**
> statements. They are never accuracy.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Pre-registration | **STRONG** | Both runs ship `PREREGISTRATION.sha256`; the Nov-3 protocol is named (`scoring_schema.json v1.0`), item schema validated, `code_sha256` recorded; the Nov-4 run carries `code_sha256` and a schema file (`gold_kg_schema.json`) | pre-registered **2 / 2** runs; code hash **2 / 2** | The thresholds (what counts as MATCH vs PARTIAL) were fixed before scoring, which is what makes the negative CTD result credible rather than a fishing expedition | High |
| Reproducibility | **STRONG** | Nov-3: `MANIFEST.sha256` **4/4 verified**, 0 mismatch, 0 missing, 0 unlisted; item-level `items.jsonl`; Nov-4: `PREREGISTRATION.sha256` + manifest | manifest verification **100%** (4/4); unlisted files **0** | The Nov-4 run's `edges.csv.gz` is large but hashed; the reference snapshots themselves (BugSigDB/CTD/Disbiome dumps) are dated but not bundled | High |
| BugSigDB concordance | **ADEQUATE** | **518 items** on **45 of 47** overlap papers: MATCH 242 + PARTIAL 19 = **50.4% (261/518; 46.1–54.7)**, paper bootstrap 42.1–58.8; **chance 16.1%**; kept **54.3% (172/317)** vs dropped **44.3% (89/201)**; kept−dropped **+10.0 pts (1.1–18.6)** | support **50.4% vs 16.1% chance = 3.1×**; kept−dropped **+10.0 pts, CI excludes 0** | Taxon resolution is `name_match` on 401/518 and `cdm_mapping` on 117/518 — so **77% of the links rest on string matching**, and a name match does not establish that the same taxon is meant (strain-level differences, renamed genera) | High |
| CTD concordance | **WEAK** | **49 items**: CURATED 4 / NOT_IN_REFERENCE 38 / INFERRED_ONLY 7. Any support **22.4% (11/49; 13.0–35.9)** vs **chance 24.2%** — *at or below chance*. Curated support **8.2% (4/49; 3.2–19.2)** vs chance 2.1%. Kept 22.2% (8/36) vs dropped 23.1% (3/13); kept−dropped **−0.9 pts (−30.0 to +20.9)** | any support **22.4% vs 24.2% chance = null**; curated **8.2% vs 2.1% chance = 3.9×** on 4 items | The two readings point in opposite directions and both are published. The honest summary is "no evidence of enrichment at the any-support level; a 4-item curated signal that cannot be distinguished from noise" | High |
| Gene–disease concordance | **WEAK (uninformative)** | 7 items, **all NOT_IN_REFERENCE**; 0/7 (CI −0.0 to 35.4); chance 0.0; kept 0/4, dropped 0/3 | support **0/7**; interval spans zero to 35% | With n=7 and a zero chance baseline, this is a null result that carries no information either way — and it should be labelled as such rather than reported as a failure | High |
| Direction agreement | **ADEQUATE** | Taxon-as-subject, directional relation, determinable: **same direction 11/12 = 91.7%** (64.6–98.5) vs base-rate chance **50.0%**; same kept pairs original vs cleaned relation, n=7: **85.7% both** | direction **91.7% on n=12** | n=12. The interval (64.6–98.5) is compatible with a true rate anywhere from "barely better than a coin" to "almost always right" | High |
| Cross-run consistency | **CRITICAL** | The two runs disagree on the reference set and the denominator: Nov-3 uses BugSigDB **+ CTD** (518 items, **Disbiome absent**); Nov-4 uses BugSigDB **+ Disbiome (59 supports) + CTD** on **622 resolved edges** with microbe–disease support **13.18% vs 5.78% chance**. Same question, different populations, different reference sets, different denominators | overlapping headline numbers **not comparable**: 50.4% (Nov-3, 518 items) vs 13.18% (Nov-4, 622 edges) | Both are defensible individually. Presented together without reconciliation, a reader will see two "BugSigDB support" figures that differ by a factor of four. The difference is the denominator (items vs resolved edges) and the reference set — not a contradiction, but it reads as one | High |
| Coverage of the graph | **ADEQUATE** | 518 + 49 + 7 = **574 checked items**; the Nov-4 run resolves **847 edges** of 25,788 = **3.28%**. The remaining 96.7% are untested because their ends never resolved to an identifier | graph coverage **847 / 25,788 = 3.28%**; `name_match+name_only` 289 of 622 microbe–disease edges (46.5%) | Coverage is limited by resolution, and resolution is limited by the absent ontology layer (component G, CQA-G-01). The reference check inherits that defect | High |
| Interpretation discipline | **STRONG** | The Nov-3 report's own line: "Support by a reference, not accuracy: a triple absent from BugSigDB or CTD is not counted as wrong, and CTD support shows that an association is known, not that the paper stated it." The Nov-4 tier statement: "KG support is a coverage statement; a triple absent from the KG is untested, not incorrect." A scope scan of the Tier-3 report finds **0** occurrences of accuracy/recall/F1/precision/gold_standard/agreement | scope violations **0** | This is the component that most often goes wrong in biomedical KG papers, and here the wording is correct in both runs. It should be preserved verbatim in the manuscript | High |

**No averaged score is computed.**

---

## 2. The two runs, side by side

| | Nov-3 `triple_reference_check` | Nov-4 `gold_kg_check` |
|---|---|---|
| References | BugSigDB, CTD | BugSigDB, **Disbiome**, CTD |
| Unit | (triple, paper) items | resolved edges, by edge type |
| Population | 518 BugSigDB items / 49 CTD / 7 gene–disease | 622 microbe–disease / 202 chemical–disease / 16 gene–disease / 7 chemical–gene resolved edges |
| Headline | support **50.4%** vs 16.1% chance | microbe–disease support **13.18%** vs 5.78% chance |
| Kept vs dropped | +10.0 pts (1.1–18.6) | +3.2 to +13.6 pts |
| Preregistration | yes | yes |
| Manifest | 4/4 verified | present |

The four-fold gap between 50.4% and 13.18% is **arithmetic, not disagreement**: the Nov-3 denominator
is *items where taxa were found in the paper* (a favourable, pre-filtered set), while the Nov-4
denominator is *all resolved microbe–disease edges* (including pairs whose exact combination is not
in any reference). Both are correct for their own question. Presenting either without its
denominator is the hazard.

### 2.1 BugSigDB, Nov-3

| Stratum | Support | 95% CI |
|---|---:|---|
| All | **50.4% (261/518)** | 46.1–54.7 |
| Kept by cleaning | 54.3% (172/317) | 48.8–59.7 |
| Dropped by cleaning | 44.3% (89/201) | 37.6–51.2 |
| Chance (other papers' signatures) | 16.1% | — |
| Kept − dropped | **+10.0 pts** | 1.1–18.6 |

### 2.2 CTD, Nov-3

| Stratum | Any support | Curated |
|---|---:|---:|
| All (49) | **22.4% (11/49)** | 8.2% (4/49) |
| Kept (36) | 22.2% (8/36) | 5.6% (2/36) |
| Dropped (13) | 23.1% (3/13) | 15.4% (2/13) |
| Chance | **24.2%** | 2.1% |

### 2.3 Resolution methods (the hidden dependency)

| Run / edge type | Method mix |
|---|---|
| Nov-3 BugSigDB (518) | `name_match` **401**, `cdm_mapping` 117 |
| Nov-3 CTD (49) | `name_match+cdm_mapping` 18, `name_match+name_match` 15, `cdm_mapping+cdm_mapping` 6, `cdm_mapping+name_match` 10 |
| Nov-4 microbe–disease (622) | `name_match+name_only` **289**, `name_match+cdm_mapping` 205, `cdm_mapping+name_only` 71, `cdm_mapping+cdm_mapping` 57 |

Most links — and every "name_only" link — are string matches. `name_only` means the end was matched
by text and never resolved to an identifier, which is the trace of CQA-G-01 (no ontology ids).

---

## 3. Issues

### CQA-L-01 — Two "BugSigDB support" figures circulate: 50.4% and 13.18%
- **Severity:** **HIGH**
- **Type:** Confirmed comparability defect
- **Evidence:** Nov-3: 261/518 = **50.4%** on (triple, paper) items. Nov-4: 82/622 = **13.18%** on resolved microbe–disease edges. Different references (Disbiome absent in Nov-3), different unit, different pre-filter. A reader who sees both without denominators must conclude one is wrong.
- **Affected:** every downstream citation of either number.
- **Scientific impact:** Neither number is wrong; the *pair* is unusable as published. The 50.4% is conditioned on "the paper is one BugSigDB covers and its taxa were found"; the 13.18% is conditioned on "both ends resolved and the edge type is microbe–disease".
- **Publication impact:** Quote **one** figure in the main text, with its denominator, and relegate the other to a footnote that names the difference. Do not put both in one table.
- **Recommended action:** Add a reconciliation line to the supplement: 518 items → 622 resolved edges → 847 total, and state why the rates differ.
- **Blocking:** blocks quoting either figure unqualified.

### CQA-L-02 — CTD support is at chance, and the two CTD readings contradict each other
- **Severity:** **HIGH**
- **Type:** Confirmed negative result
- **Evidence:** Any support **22.4% (11/49)** vs **chance 24.2%** — below chance. Curated support **8.2% (4/49)** vs chance 2.1% — 3.9× on four items. Kept−dropped **−0.9 pts (−30.0 to +20.9)**.
- **Affected:** 49 chemical–disease items.
- **Scientific impact:** At the level of "is this chemical–disease association known at all", the triple layer performs no better than random pairing. The curated 8.2% rests on **four** items and its interval (3.2–19.2) overlaps the any-support reading. Neither reading supports a positive claim.
- **Publication impact:** CTD must be reported as **a null result** with both readings. Selecting the curated 8.2% and describing it as "3.9× chance" would be technically true and materially misleading given n=4.
- **Recommended action:** Report the null, state the denominator, and note that the four curated hits are too few to distinguish from noise.
- **Blocking:** blocks any CTD corroboration claim.

### CQA-L-03 — 46.5% of the KG-check's links are name-only
- **Severity:** **HIGH**
- **Type:** Confirmed dependency
- **Evidence:** Nov-4 microbe–disease resolution: `name_match+name_only` **289 / 622 = 46.5%**; `name_match+cdm_mapping` 205; `cdm_mapping+name_only` 71; `cdm_mapping+cdm_mapping` 57. Nov-3 BugSigDB: `name_match` 401 / 518 = 77.4%.
- **Affected:** 289 of 622 edges; 401 of 518 items.
- **Scientific impact:** Every one of these comparisons depends on a string equality between our label and a reference name. Compound labels ("gut microbiota", "composition of the gut microbiota") are compared to curated taxon names. A name match can be right for the wrong reason, and `name_only` means the end was never identifier-resolved at all.
- **Publication impact:** The support rate measures "our label string appears in the reference" as much as it measures "the biological pair is known". Say so.
- **Recommended action:** Report the resolution-method mix beside every support rate. Prefer restricting the headline to `cdm_mapping+cdm_mapping` (57 edges) if an identifier-based number is wanted — and state that it is 57 edges.
- **Blocking:** blocks an identifier-level corroboration claim.

### CQA-L-04 — Direction agreement rests on twelve items
- **Severity:** **MODERATE**
- **Type:** Confirmed small-denominator risk
- **Evidence:** 11/12 = 91.7% (64.6–98.5) vs 50% base rate. Same kept pairs, original vs cleaned, n=7: 85.7% both.
- **Affected:** 12 items.
- **Scientific impact:** The point estimate is excellent and the interval is 64.6–98.5. A reader will remember 91.7%; the honest statement is "direction agreed on 11 of 12 determinable items". The cleaned-vs-original comparison on 7 pairs (6/7 either way) is a tie and should not be presented as an improvement.
- **Publication impact:** Report counts, not percentages, for n<20.
- **Recommended action:** Merge direction reporting into the BugSigDB paragraph with the raw fraction.
- **Blocking:** neither, if counts are shown.

### CQA-L-05 — The gene–disease check is uninformative and is reported as if it were a result
- **Severity:** **MODERATE**
- **Type:** Confirmed null with wide interval
- **Evidence:** 7 items, 0/7, CI −0.0 to 35.4, chance 0.0. Kept 0/4, dropped 0/3.
- **Affected:** 7 items.
- **Scientific impact:** A zero-baseline comparison with n=7 cannot distinguish 0% from 35%. Its appearance in a results table alongside the 518-item BugSigDB row gives it undue weight.
- **Publication impact:** Either drop the row or mark it `n=7, uninformative`.
- **Recommended action:** Drop from the main table; keep in the supplement with the interval.
- **Blocking:** neither.

### CQA-L-06 — The graph coverage of the whole reference exercise is 3.3%
- **Severity:** **MODERATE**
- **Type:** Confirmed scope limitation
- **Evidence:** 847 resolved edges / 25,788 = **3.28%**; Nov-3 items 574. The remaining 96.7% never resolved, because `subject_ontology_id`/`object_ontology_id` are `unresolved` on 100% of triples (CQA-G-01).
- **Affected:** 24,941 triples.
- **Scientific impact:** The reference checks cannot reach the graph's bulk. Their positive results describe a resolved periphery, and the 68.7% `OTHER_RELATION` bucket is untestable against these references by construction — no curated KG stores "OTHER_RELATION".
- **Publication impact:** "Relationships were checked against three curated references" must carry "for the 3.3% whose endpoints resolved".
- **Recommended action:** State the 847/25,788 denominator in the same sentence as any support rate.
- **Blocking:** blocks a graph-wide corroboration claim.

### CQA-L-07 — Kept-better-than-dropped validates the cleaning, not the triples
- **Severity:** **MODERATE**
- **Type:** Confirmed interpretive hazard
- **Evidence:** BugSigDB +10.0 pts (1.1–18.6); Nov-4 +3.2 to +13.6 pts for microbe–disease; but CTD **−0.9 pts (−30.0 to +20.9)** and gene–disease 0/4 vs 0/3. Two of four strata show no separation.
- **Affected:** all four edge-type strata.
- **Scientific impact:** The consistent positive direction on the largest strata is genuine evidence that the DeepSeek selection is picking real signal. It is **not** evidence that the kept triples are correct — it is evidence that they are *more likely to be in a reference*, which is what the cleaning may have selected for.
- **Publication impact:** "The cleaned layer was validated against BugSigDB" is a category error: the comparison validates the *selection*, not the *labels*.
- **Recommended action:** State the claim as "kept triples were more often reference-supported than dropped ones (+10.0 pts)", nothing stronger.
- **Blocking:** neither, if scoped.

### CQA-L-08 — Reference snapshots are dated but not bundled
- **Severity:** **LOW**
- **Type:** Confirmed reproducibility gap
- **Evidence:** BugSigDB export dated 2026-11-03 07:58 UTC with licence; taxonomy snapshot 2026-11-01; CTD and Disbiome dumps referenced but not included in either result directory.
- **Affected:** 2 of 3 references (CTD, Disbiome).
- **Scientific impact:** Today's re-run against a newer CTD could differ. The code hash and preregistration pin the *method*, not the *reference*.
- **Publication impact:** Minor; state the snapshot dates.
- **Recommended action:** Record CTD/Disbiome dump dates and sizes in the manifest.
- **Blocking:** neither.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates:**
- Both runs are **pre-registered**, both ship `code_sha256`, and the Nov-3 run's manifest verifies
  **4/4** — the cleanest provenance in the audit alongside component K.
- BugSigDB support **50.4% (261/518) vs 16.1% chance** on items; **13.18% vs 5.78%** on resolved
  microbe–disease edges. Both are 3.1× and 2.3× chance respectively, and **neither is accuracy**.
- CTD any-support **22.4% vs 24.2% chance** — a **null result**; curated 8.2% on 4 items.
- Gene–disease **0/7**, uninformative (CI to 35.4%).
- Direction same on **11/12** determinable items; original vs cleaned a **tie** on 7 pairs.
- Resolution is **name-match dominated**: 46.5% of Nov-4 links are `name_only`, 77.4% of Nov-3 links
  are pure `name_match`.
- The reference exercise reaches **847 / 25,788 = 3.28%** of the graph, because no endpoint carries
  an ontology id.
- Kept triples are more reference-supported than dropped ones by **+10.0 pts** (BugSigDB), which
  validates the *selection*, not the labels.

**Does not establish:**
- That any triple is correct. Support is coverage of a curated slice; absence is untested.
- Any precision, recall, accuracy or completeness figure for the graph.
- That CTD corroborates anything — at the any-support level it is below chance.
- That `OTHER_RELATION` triples (68.7%) are unchecked-but-fine; they are **uncheckable** against these
  references.

---

## 5. Component verdict

Methodologically this is the cleanest work in the project: pre-registered, hashed, item-level, with
chance baselines, bootstrap intervals and — unusually — an explicit and repeated statement that
absence from a reference is not error. Two of the four strata behave as hoped (BugSigDB items 3.1×
chance; microbe–disease edges 2.3× chance), one is a null (CTD at 22.4% vs 24.2% chance), and one is
uninformative (7 gene–disease items).

The component's real problem is **presentation, not method**: two runs produce two "BugSigDB support"
numbers that differ by four-fold, and the difference is entirely in the denominator and the reference
set. Published side by side without reconciliation they will be read as a contradiction, and the
two-thirds of the graph that is `OTHER_RELATION` cannot be checked at all because no curated KG stores
it and no endpoint carries an identifier.

So the component's contribution to the manuscript is narrow and solid: **a 3× chance enrichment
against a human-curated reference over 3.3% of the graph, a documented null against CTD, and a
kept-vs-dropped separation that validates the cleaning**. Everything beyond that sentence is overreach.
