# BugSigDB Validation — Microbiome-CDM

- **Audit ID:** `bugsigdb_validation` (version 1, 2026-11-03)
- **Scope:** the frozen CDM release `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (via `releases/CURRENT_FROZEN_SET_2026-11-02/`), compared against **BugSigDB** `full_dump.csv` (dump stamp `2026-11-03T07:58Z`, sha256 `b106dafaec8b5be5a52d685da9bf88f8439ab93f87a4f68f423d6b3d679ce81c`, CC BY 4.0), stored read-only at `data/reference_kg/raw/bugsigdb/`. Comparator sources (gutMDisorder v3, GMrepo, MiDRED, DiMB-RE, MicrobioRel, MINERVA, CTD, Disbiome) and the 12 OBO ontologies + NCBI Taxonomy + MeSH 2026 are profiled in `data/reference_kg/SOURCES.md` and used here only for overlap and identifier-currency statements.
- **Mode:** read-only. The frozen CDM was opened with `?mode=ro`; no release file was written, rebuilt, relabelled, or regenerated. No extraction, mapping, or CDM-construction logic was modified. Nothing was tuned to raise a score: every change between harness versions traces to a named mechanical defect, documented in §7.
- **Method:** every number below comes from an executable read-only probe. The comparison harness is `outputs/scratch/reference_kg_download/compare_bugsigdb_v5.py`; the consolidation producer is `build_validation_report.py`, which re-reads the v3/v4/v5 outputs plus the frozen DB and emits `bugsigdb_validation_report.json`. Row-level detail is in `bugsigdb_comparison_v5_rows.json` (2,158 rows). Adjudications are in `bugsigdb_discordant_adjudication.json` and `bugsigdb_concordant_audit.json`.

> **What this document is not.** It is not an accuracy, precision, or recall estimate for the 453-paper build. It is a same-paper concordance measurement against one external human curation on 47 of 453 papers, with the coverage funnel stated in full so the reader can see exactly what the verdict does and does not cover.

---

## 1. Executive verdict

**Verdict: PARTIALLY VALIDATED, WITH A DISCLOSED SELECTION EFFECT — the direction we attach to a taxon claim agrees with human curation wherever our own text lets us resolve which study arm the direction is about, but that resolving subset is 28 of 2,060 comparable units (1.4%).**

Stated as three separate axes, because collapsing them is how this kind of result gets overstated:

| Axis | Status | Basis |
|---|---|---|
| **Directional agreement, where scorable** | **YES — 28/28** | Every reporting unit whose stored evidence names both BugSigDB arms agrees in direction with BugSigDB after referent alignment. Wilson 95% CI **[0.8794, 1.0000]**. |
| **Corpus-wide validation** | **NOT ESTABLISHED** | 28/2,060 = **1.36%** of comparable units. 28/28 is a *selection effect*: the strict rule refuses a unit unless both arms are named, and that condition correlates with the unit being uncontroversial. |
| **Human-reviewed** | **NO** | The CDM remains machine-extracted. This document measures agreement with someone else's human curation; it does not add human review to our own records. |

Three findings belong in any summary of this work:

1. **The direction field is real and defensible where it resolves.** 28 of 28 scoring units agree, across 10 studies, 24 distinct taxa, 14 distinct group pairs, both BugSigDB directions (increase 17 / decrease 11), and both referent arms (Group 1 in 23 units, Group 0 in 5). Zero direction reversals survived.
2. **The dominant limitation is our missing referent, not our missing direction.** `claim.direction_refers_to` is `NULL` on every KEPT claim. Of 568 units where we do make a claim naming the curated taxon, **262 (46.1%) cannot be scored because the direction's subject arm resolves to neither BugSigDB arm** — this is a schema gap, and it is the single largest addressable cause of the low scorable count.
3. **The largest uncovered block is out of our input's scope, and the second largest is a genuine recall gap.** 1,038 of 2,060 units (50.39%) name a taxon that never appears in our sectioned full text — BugSigDB curates figure panels and supplementary tables. Of the 1,022 units whose taxon *is* in our text, **454 (44.4%) have text evidence but no claim** — that is an extraction recall gap and it is ours.

**The honest single sentence:** *on the 1.4% of comparable units where our stored evidence names both arms, our direction agrees with human curation 28 times out of 28; on the other 98.6% we either do not have the taxon in our input, do not make a claim, or do not store which arm our direction refers to.*

---

## 2. Why BugSigDB, and why nothing else is a gold standard

The inclusion test for "can this source validate us?" is **same-paper overlap**. Concordance on papers neither side shares is not evidence about our extraction. Measured:

| Source | Our papers matched | Denominator | Basis |
| --- | --- | --- | --- |
| **BugSigDB** | **47 studies** (266 rows) | 16,637 reviewed rows | PMID, DOI as cross-check |
| gutMDisorder v3 | 14 | 780 PMIDs | PMID |
| GMrepo | 33 | 808 PMIDs | `Related_Publications` |
| DiMB-RE | 2 | 30 PMCIDs | PMCID |
| MiDRED | 1 | 1,655 PMIDs | PMID |
| MicrobioRel | 0 | 239 PMIDs | `annotation_id` |
| Disbiome | **n/a** | — | no PMID/DOI field at all |
| MINERVA | **n/a** | — | CUI-level only, no paper linkage |

Only BugSigDB has enough same-paper overlap to support a per-finding comparison. The ontologies are **concordance evidence, never gold standards**: an ontology can tell us an identifier is current, it cannot tell us our claim about a paper is right, and ontology absence is never falsity. MINERVA is disqualified as corroboration on a separate ground — its triples are LLM-extracted, so its agreement with our LLM-assisted build is not independent evidence.

**Corpus coverage: 47 / 453 = 10.38% [7.89%, 13.52%].** Every number in this document is bounded by that. Nothing here generalises to the other 406 papers.

### 2.1 Overlap is exact, and one apparent match was rejected

| Join | Rows | Studies |
| --- | --- | --- |
| PMID | 266 | 47 |
| DOI | 270 | 48 |
| Union before exclusion | 270 | 48 |
| **Union after exclusion** | **259 row–paper pairs** | **47** |

The single DOI-only study, `35083314`, is **hard-excluded** as a curation error: BugSigDB records DOI `10.1016/j.celrep.2021.109765` against it, but that DOI belongs to PMID `34592155`, which is already in the PMID-matched set. Admitting it would have added a study whose "match" is a metadata defect, not a shared paper. Excluded as `KNOWN_BAD_DOI_STUDIES` in the harness.

Join hygiene applied: empty `publication.pmid` strings are excluded (the frozen DB contains one) so `NA` rows cannot match on the empty key; DOIs are normalised by stripping `doi.org/`/`doi:` prefixes and trailing `.`/`,`/`;` (BugSigDB contains at least one DOI with a trailing period, e.g. `10.1016/j.chom.2014.02.005.`). 57 BugSigDB `PMID` cells hold non-PMID content and are not treated as identifiers.

BugSigDB side, reviewed set only: **16,637 rows** (16,662 data rows minus **25** `Review state = Incorrect`), **39** conditions, **21** body sites, `Abundance in Group 1` **increased 142 / decreased 122 / NA 6** over the matched union.

---

## 3. The reporting unit

**The unit is `(study, taxon, BugSigDB group pair)`, not a BugSigDB row and not a taxon.**

BugSigDB's `NCBI Taxonomy IDs` cell is `;`-separated **per-taxon lineages**, each a `|`-joined ancestor→self path; `MetaPhlAn taxon names` is `,`-separated in the same order. A single signature row therefore contributes many taxa, and the same taxon recurs across signatures for the same study with *different* group pairs. Treating a row as the unit attributes one verdict to dozens of taxa; treating `(study, taxon)` as the unit deletes real subgroup structure (a taxon can be increased in one contrast and decreased in another and both be correct).

| Quantity | Value |
|---|---|
| Matched row–paper pairs | 259 |
| Papers / distinct studies | 47 / 47 |
| Raw per-taxon units | 2,158 |
| **Reporting units** | **2,060** |
| Units from single-taxon signatures | 47 |
| Distinct curated `(paper, taxid)` pairs | 1,517 |
| Distinct curated taxids / labels | 667 / 661 |
| Signature rows with name↔lineage count mismatch | **0** |

Direction is scored **only at the exact shared taxid, never at a shared ancestor**. A shared phylum makes unrelated claims look contradictory; ancestor matching was removed as unsound.

---

## 4. The coverage funnel — the headline number in context

```
2,060  reporting units (47 studies)
 ├─ 1,038  (50.39%)  taxon never appears in our sectioned full text     → input-scope limit
 └─ 1,022  (49.61%)  taxon present in our text
     ├─   454  (44.42%)  no claim names it                               → GENUINE RECALL GAP
     └─   568  (55.63%)  claimed
          ├─ 262  (46.1%)  DIRECTION_REFERENT_UNRESOLVED  → subject arm on neither BugSigDB arm
          ├─ 172  (30.3%)  DIRECTION_MULTITAXON_ONLY      → one direction stored for a taxon group
          ├─  68  (12.0%)  DIRECTION_NOT_IN_TEXT          → we store NOT_STATED, text states nothing
          ├─  38  ( 6.7%)  WE_REPORT_NO_DIRECTION         → we store MIXED / NO_ASSOCIATION
          └─  28  ( 4.9%)  CONCORDANT                     → directionally scorable
```

`DIRECTION_MIXED_IN_OUR_CDM` and `DISCORDANT` are **0** in this policy.

Per-disposition counts over reporting units (sum = 2,060 exactly; the consolidation producer asserts this):

| Disposition | Units | Meaning |
|---|---|---|
| `NOT_IN_CORPUS_TEXT` | 1,038 | taxon absent from our input — out of scope, never an error, never falsity |
| `TAXON_NOT_CLAIMED_TEXT_PRESENT` | 453 | taxon named in our text, no claim — recall gap |
| `DIRECTION_REFERENT_UNRESOLVED` | 262 | the direction exists but its subject arm is on neither BugSigDB arm |
| `DIRECTION_MULTITAXON_ONLY` | 172 | the only claims naming this taxon store one direction for a taxon group |
| `DIRECTION_NOT_IN_TEXT` | 68 | we store `NOT_STATED` on every claim naming the taxon (74 rows, 108 claim-level direction values) |
| `WE_REPORT_NO_DIRECTION` | 38 | we store `MIXED` (25 units) or `NO_ASSOCIATION` without `MIXED` (13 units) |
| `CONCORDANT` | 28 | same direction after referent alignment |
| `DISCORDANT` | 0 | — |
| `DIRECTION_MIXED_IN_OUR_CDM` | 0 | — |

**Directionally scorable: 28/568 = 4.93% of claimed units; 28/2,060 = 1.36% of comparable units.** Both denominators are stated because "of what resolves" and "of what exists" are different claims and only the first is defensible.

### 4.1 `NOT_IN_CORPUS_TEXT` is an input-sourcing effect, measured

Decomposed by BugSigDB's own `Source` column:

| | Figure* | Table* | other |
|---|---|---|---|
| Out of scope (1,038) | **840** | 141 | 57 |
| In scope (1,022) | 659 | 226 | 137 |
| All units (2,060) | 1,499 | 367 | 194 |

81% of out-of-scope units are figure-sourced. BugSigDB curates supplementary tables and figure panels; our input is sectioned full text. This is a limit of what we fed the extractor, not an error in it. A spot-check of 400 absent units found the taxon label in our markdown **0/400** times.

### 4.2 `TAXON_NOT_CLAIMED_TEXT_PRESENT` is ours, and it is the real recall number

454 units (44.4% of in-text units) have the taxon demonstrably in our text and no claim naming it. Reported two further ways from the claim side, because the choice of denominator matters:

| Measure | Value | Wilson 95% CI |
|---|---|---|
| Kept claims on the 47 matched papers | 2,720 | — |
| Claims naming **no taxon** at all | **1,744 (64.12%)** | — |
| Taxon-bearing claims | 976 | — |
| … naming ≥1 BugSigDB-curated taxon | **651 (66.70%)** | [0.6368, 0.6959] |
| Taxon-bearing **and directional** claims | 587 | — |
| … naming ≥1 curated taxon | **438 (74.62%)** | [0.7094, 0.7797] |
| Distinct `(paper, taxid)` pairs we name | **361 / 1,517 (23.80%)** | [0.2172, 0.2600] |

The first four read *"when we claim a taxon, is it one a human also curated for that paper?"* — high (66.7%–74.6%), which is what a precision proxy looks like. The last reads *"of the taxa a human curated for these papers, how many do we name?"* — 23.8%, which is the recall view. Both are correct; they answer different questions and must not be quoted interchangeably. Median curated taxa per paper is 21, and 64.1% of our claims on these papers name no taxon at all, so the recall ceiling is structural before any comparison begins.

---

## 5. Directional agreement

### 5.1 Headline

| Policy | k / n | Rate | Wilson 95% CI | Status |
|---|---|---|---|---|
| **Strict — both arms named** | **28 / 28** | **1.0000** | **[0.8794, 1.0000]** | **operational result** |
| Permissive — one arm named | 64 / 78 | 0.8205 | [0.7210, 0.8900] | disclosed upper bound, **not adopted** |
| v3 all-route | 82 / 177 | 0.4633 | [0.3914, 0.5367] | superseded, wider-route reference |

**28/28 is a selection effect and must be stated as one.** The strict rule scores a unit only when the pre-comparator and post-comparator fragments each name a *different* one of the two BugSigDB arms. That condition is not independent of the unit being uncontroversial — it prefers explicit two-arm sentences, which are exactly the sentences least likely to contain an ambiguous direction. The 0 discordance is a property of what the rule admits, not proof of perfect agreement. Both rates are reported side by side so the reader sees the range: **our true directional agreement lies somewhere in [0.72, 1.00] on the units we can reach at all, and we cannot narrow it further without storing the referent.**

### 5.2 Anatomy of the 28 scored units

| Property | Value |
|---|---|
| Distinct studies | **10** of 47 |
| Distinct taxa | 24 |
| Distinct group pairs | 14 |
| BugSigDB direction | increase 17 / decrease 11 |
| Our referent arm | Group 1 = 23 / Group 0 = 5 |
| Referent source | `comparison:two-arm` 19 / `evidence:two-arm` 9 |
| Rows carrying the verdict | 31 (25 units rest on 1 row, 3 on 2 rows) |
| Resolving claims per unit | 1: 8, 2: 10, 3: 3, 4: 5, 11: 1, 16: 1 |
| Distinct `(unit, claim)` scoring pairs | 84 |

Both referent arms occur, so the result is not a systematic flip in either direction. Five units score against **Group 0** — i.e. our sentence describes the *control* arm and the verdict required an explicit flip — including study `25644696` (Odoribacter, *"healthy group vs NAFLD group"*). A harness that silently assumed Group 1 would have inverted those five.

Per-study coverage for all 47 studies (this is what 28/28 actually spans):

| Study (PMID) | Scored | Reporting units | Curated taxa |
|---|---|---|---|
| 23844187 | 0 | 25 | 25 |
| 24399150 | 3 | 13 | 13 |
| 24629344 | 0 | 83 | 83 |
| 25644696 | **5** | 6 | 6 |
| 26515465 | 0 | 114 | 32 |
| 27102666 | 0 | 21 | 21 |
| 27450202 | 0 | 12 | 12 |
| 27838347 | 0 | 146 | 82 |
| 27988330 | 0 | 1 | 1 |
| 28245856 | 0 | 2 | 2 |
| 28970732 | 0 | 126 | 81 |
| 29180991 | 0 | 16 | 16 |
| 29307330 | 0 | 16 | 11 |
| 29321519 | 0 | 38 | 15 |
| 29518185 | 0 | 22 | 11 |
| 29596446 | 0 | 6 | 3 |
| 29738477 | 0 | 74 | 65 |
| 29885665 | 1 | 46 | 13 |
| 30483228 | 0 | 13 | 13 |
| 30545401 | 4 | 81 | 37 |
| 30867711 | **0** | 27 | 21 |
| 30894059 | 4 | 36 | 36 |
| 30972048 | 1 | 24 | 23 |
| 31065565 | 0 | 22 | 20 |
| 31078141 | 0 | 2 | 2 |
| 31219947 | 0 | 32 | 32 |
| 31221587 | 0 | 65 | 38 |
| 31231345 | 0 | 69 | 65 |
| 31358825 | 1 | 9 | 9 |
| 31682463 | 0 | 48 | 30 |
| 32295867 | 0 | 11 | 10 |
| 32401750 | 1 | 33 | 24 |
| 32415070 | 0 | 12 | 12 |
| 32490229 | 0 | 23 | 23 |
| 32561908 | 0 | 4 | 4 |
| 32566740 | 0 | 27 | 14 |
| 32934117 | 0 | 49 | 49 |
| 33619320 | 0 | 18 | 18 |
| 33732655 | 1 | 36 | 29 |
| 33921449 | 0 | 17 | 17 |
| 33927704 | 0 | 18 | 18 |
| 34100340 | **7** | 120 | 86 |
| 34283063 | 0 | 195 | 170 |
| 34592155 | 0 | 15 | 5 |
| 35440670 | 0 | 43 | 43 |
| 36250371 | 0 | 47 | 38 |
| 39355268 | **0** | 197 | 139 |

Note study `30867711`: 27 reporting units, **0** scored — and it is the study that contains both genuine reversals (§7.2). Its sentences never name a BugSigDB arm.

### 5.3 Referent policy — why `comparison` and `evidence:comparator` are barred

`claim.direction_refers_to` is `NULL` on every KEPT claim, so the subject arm has to be recovered from text. The rule: take the arm named **before** the comparator (`than`, `compared to/with`, `relative to`, `versus`); else fall back to `comparison_or_exposure`; else do not score. Measured reliability of each source on the v3 result, which is the only run where all sources were exercised:

| Referent source | Agreement | Wilson 95% CI | Used for scoring? |
|---|---|---|---|
| `evidence:subject` | 13/15 = 0.8667 | [0.6212, 0.9626] | **yes** |
| `evidence:whole` | 33/40 = 0.8250 | [0.6805, 0.9125] | **yes** |
| `unresolved` | 19/34 = 0.5588 | [0.3945, 0.7112] | not scored by construction |
| `comparison` | 12/55 = **0.2182** | [0.1295, 0.3437] | **barred** |
| `evidence:comparator` | 5/33 = **0.1515** | [0.0665, 0.3092] | **barred** |
| Total (all routes) | 82/177 = 0.4633 | [0.3914, 0.5367] | — |

Both barred sources are structurally wrong, not merely noisy. `comparison_or_exposure` names **one** arm, so a direction attributed to it is a coin flip — 0.218 is statistically indistinguishable from chance. `evidence:comparator` names the arm the direction is **not** about: in *"X was higher in A than in B"* the direction describes **A**, and `B` is the comparator, so this source attributes the direction to the wrong arm as a matter of construction (0.152 confirms the inversion).

A referent source whose measured agreement with the gold standard is 0.15–0.22 cannot be used to generate verdicts. Barring it necessarily discards most units. That is the correct trade.

In v5, over all 2,158 rows: `our_referent_source` is `null` 2,127, `comparison:two-arm` 22, `evidence:two-arm` 9 — the strict rule fires rarely, which is why the scored set is small.

**No abbreviation table is invented.** Where our text says `RA` and BugSigDB says `rheumatoid arthritis`, or `GC` and `Gastric cancer`, the unit is left unresolved. Matching an unstated expansion would be fabrication, and abbreviation asymmetry is the single dominant generator of false discordance (§7.2).

### 5.4 Hidden-contradiction audit on the 28

A `CONCORDANT` verdict does **not** mean "every claim we make about this taxon agrees". It means "the claims whose arm resolves agree". Most claims on these taxa do not resolve, so the verdict rests on a minority of stored claims. Audited (`audit_concordant_units.py`, hard-fails on any unclassified unit):

| Finding | Count |
|---|---|
| Scored units carrying an opposing unresolved claim | **5 / 28** |
| — claim is not an arm contrast at all (`NON_ARM_CONTRAST`) | 3 |
| — arm is resolvable by hand, resolver too strict (`ARM_RESOLVABLE_BY_HAND`) | 2 |
| — **genuine internal contradiction** | **0** |

The 5: `29885665`/`475` Moraxella, `30894059`/`216851` Faecalibacterium, `32401750`/`543` Enterobacteriaceae (all three: the opposing claim is a correlation or a within-cohort contrast, not an arm comparison); `33732655`/`1279` Staphylococcus (*"Asian (4M)"* vs *"Pacifica (4M)"*) and `34100340`/`194` Campylobacter (`decrease` vs `decrease`) where the resolver simply did not recognise the arm wording. In the two resolver cases our verdict is correct by hand. **Zero of 28 rest on a genuinely self-contradictory record.**

---

## 6. Verdict reconciliation across harness versions

Three harness generations exist. Only v5 is operational; the others are retained so the change history is auditable and so the upper bound can be disclosed.

| Version | Policy | Scored | Concordant | Rate | Why superseded |
|---|---|---|---|---|---|
| v1 | row-level | — | — | — | **retracted** — parsed `;`-separated lineage sets as one lineage, corrupting every count |
| v2 | stripped `healthy`/`control`/`normal` from stopwords | — | — | — | forced inverted arms |
| v3 | all referent routes, first-available | 177 | 82 | 0.4633 | admits sources measured at 0.15–0.22 (§5.3) |
| v4 | permissive one-arm + fixes | 78 | 64 | 0.8205 | manufactures discordance via abbreviation asymmetry (§7.2) |
| **v5** | **strict both-arms** | **28** | **28** | **1.0000** | **operational** |

Fixes in v4, each traceable to a mechanical cause and none tuned to a target:

- **Hyphenated-compound tokenisation** with negation prefixes glued, so `non-cancerous` and `non-alcoholic` are single tokens rather than a negation and an arm.
- **Removal of the invalid `evidence:comparator` fallback** — it was structurally inverted (§5.3).
- **New `DIRECTION_MULTITAXON_ONLY` disposition** — one stored direction over a taxon group is right for some members and wrong for others, so it cannot be scored per taxon.
- **`CORREL` guard** — correlation / AUC / regression evidence states no arm, so it never scores.

v5 vs v4, measured on unit key sets:

| | Count |
|---|---|
| Units scored by both | **27** |
| Verdict agreement on shared units | **27 / 27** |
| Scored by v5 not v4 | 1 (`30894059` / `216851`) |
| Scored by v4 not v5 | **51** — of which 37 v4-`CONCORDANT`, 14 v4-`DISCORDANT` |
| Where all 51 land in v5 | `DIRECTION_REFERENT_UNRESOLVED` |

The one v5-only unit was v4-`MIXED`: v5's `CORREL` guard drops the correlational claim that had been making the record contradictory. So the correct relationship is *"v5 strict ⊆ v4 permissive, modulo `CORREL`-corrected `MIXED` units"* — not a clean subset.

**The 51-unit drop is a disclosed selection effect, not a silent improvement.** Every unit v4 called discordant is among them, which is precisely why v5 shows zero discordance.

### 6.1 v3's 95 discordant units, explained by the collapse rule alone

| Where v3 discordant units land in v5 | Units |
|---|---|
| `DIRECTION_MULTITAXON_ONLY` | **38** |
| `DIRECTION_REFERENT_UNRESOLVED` | 54 |
| `CONCORDANT` | 3 |

**41 of 95 v3 "disagreements"** were the multi-taxon collapse: `;`-adjacent taxa collapsed into one unit whose single stored direction was then compared against each member separately. 38 are now correctly refused as `DIRECTION_MULTITAXON_ONLY`. The 3 that become `CONCORDANT` were v3 referent errors.

---

## 7. What the permissive rule found, and what happened to it

The permissive rule produced 78 scored units and 14 `DISCORDANT`. All 14 were adjudicated individually against their own stored `evidence_text` (`bugsigdb_discordant_adjudication.json`). This is a manual analyst reading of 14 stored records — **not** independent human curation, **not** annotation of the corpus, and **not** an accuracy estimate.

| Verdict | Units | Cause |
|---|---|---|
| `CONCORDANT` | **6** | manufactured by the permissive rule — it matched an arm word and missed the abbreviation |
| `NOT_COMPARABLE` | **6** | there is no direction between the two BugSigDB arms anywhere in the record |
| **`GENUINE_DISAGREEMENT`** | **2** | real direction reversal |

### 7.1 The 6 abbreviation artifacts

| Study | Taxon | Group 0 → Group 1 | BugSigDB | Our text |
|---|---|---|---|---|
| 27102666 | 216851 Faecalibacterium | healthy controls → RA patients | decrease | picked a hydroxychloroquine-use claim instead of the RA-vs-control claim |
| 31231345 | 1239 Bacillota | adjacent normal tissue → cancer tissue | increase | *"decreased abundance of Firmicutes … when compared with the cancer group"* — lower in normal ⇒ higher in Group 1. Missed only because our text says *"non-cancerous tissues"* |
| 32490229 | 1485 Clostridium | Healthy urban elderly → Diabetic elderly | decrease | *"Clostridium, Healthy versus T2D: 5.6% vs 3.2%"* — `T2D` not matched to *"Diabetic elderly"*, so the rule saw only *"Healthy"* and flipped a concordant unit |
| 39355268 | 528 Ochrobactrum | benign+normal → Gastric cancer (GC) | increase | *"The GC group was characterized by a higher presence of Ochrobactrum"* — `GC` missed, `benign`/`normal` matched, increase attributed to the wrong arm |

(Study `39355268` appears three times in the adjudication file because it has three group-pair units against the same taxon; the table lists distinct cases.)

### 7.2 The 2 genuine reversals — and why the strict rule cannot see them

Both are study **`30867711`** (RYGB time course), Group 0 = pre-RYGB, Group 1 = 3-months-post-RYGB:

| Taxon | BugSigDB (Group 1) | Ours | Our evidence |
|---|---|---|---|
| `909932` Negativicutes | **increase** | decrease | *"The present study observed a decrease in Negativicutes in the gut microbiota at 3 months after RYGB."* |
| `216851` Faecalibacterium | **increase** | decrease | *"…after a decrease in Faecalibacterium after RYGB, the β diversity decreased towards the level in the healthy volunteers."* |

Group 1 **is** the 3-month-post-RYGB arm, so both really do oppose. Neither sentence names a BugSigDB arm — *"at 3 months after RYGB"* is a timepoint, not the arm label — so the strict rule refuses both. **This is the strict rule's blind spot and it must be published with the 28/28, not after it.** BugSigDB's own `Source` column should be consulted before either record is called wrong.

The remaining `NOT_COMPARABLE` cases are equally instructive: study `29885665`/`1716` Corynebacterium where BugSigDB's arms are specimen types (bronchial brush vs oral wash) while our claims are cytokine correlations and dominance frequency; `30867711`/`850` F. mortiferum where the only naming claim has empty `evidence_text` and the second is OCR-corrupted figure text; `32295867`/`5506` Fusarium where our claim is a temporal trend within the treated cohort, not a treated-vs-untreated contrast.

**Measured discordance, properly stated: 2 / 78 = 0.0256 [0.0071, 0.0888] under the permissive rule, and 6 of those 14 "disagreements" were ours to fix.**

### 7.3 The word-boundary hazard, and the extraction-glue hazard

Naive substring matching of a taxon label counts `Bacillus` inside `Lactobacillus` and `Streptococcus` inside `Peptostreptococcus`. Both dispositions that depend on text presence use `(?<![a-z0-9])label(?![a-z0-9])`. Measured cost on the 1,492 unclaimed units:

| | Units |
|---|---|
| Boundary match | **453** |
| Substring match | 464 |
| **Substring-only false positives** | **11** |
| Boundary-only | 0 |

The 11 are mostly the expected family: `Neisseria` in `neisseriaceae`, `Streptococcus`/`Streptococcaceae` in `peptostreptococcus`/`peptostreptococcaceae`, `Clostridia` in `clostridiales`, `Akkermansia` in `akkermansiaceae`, `Bacillus` in `lactobacillus`.

**One of the 11 was not a lookalike at all.** `Clostridium butyricum` (taxid 1492, study 33927704) reads `Escherichia coli(P = 0.011) andClostridium butyricum(P = 0.035)` in `HMPAPER_000411` — PDF extraction dropped the space at a case boundary, so a leading-substring test missed a taxon that is genuinely present. That markdown file is hash-pinned by corpus release 2.2.0 and may not be rewritten, so the correction belongs at read time: the harness re-splits on lowercase→uppercase before lowercasing.

The glue is a real extraction class, not a one-off: **9,242 lowercase→uppercase glued tokens across 437 of 453 papers** (`rossRef`, `niFrac`, `acBio`, …). Measured effect of the read-time re-split on the unclaimed universe:

| | Units |
|---|---|
| Unclaimed units whose presence verdict flips | **1** |
| … absent → present (recall reclaims the unit) | 1 |
| … present → absent (regression) | 0 |

So the corrected counts are **454** `TAXON_NOT_CLAIMED_TEXT_PRESENT` (464 under bare substring, 453 under the boundary rule before this fix) and 1,038 `NOT_IN_CORPUS_TEXT`. The single reclassified unit is a recall gap we should not have been able to hide; no verdict in §5 changes, because this unit carries no claim and therefore never reached direction scoring.

---

## 8. Identifier currency — measured, not asserted

"The ontologies are newer than BugSigDB's" is a measurable statement, so it is measured. These are **maintenance statements about identifier currency. They are not accuracy statements.**

### 8.1 Our cited ontology identifiers resolve against current releases

12 OBO ontologies downloaded (`.obo`, hashed, 209 MB) and parsed; 237 namespace entries reported in `id_resolution_report.json`.

| Namespace | Cited | Resolved | Stale | % |
|---|---|---|---|---|
| NCIT | 13,694 | 13,683 | 11 | 99.92 |
| CHEBI | 3,299 | 3,299 | 0 | **100.00** |
| GO | 2,179 | 2,176 | 3 | 99.86 |
| HP | 1,866 | 1,866 | 0 | **100.00** |
| MONDO | 1,362 | 1,362 | 0 | **100.00** |
| DOID | 566 | 566 | 0 | **100.00** |
| OBI | 456 | 435 | 21 | 95.39 |
| CL | 414 | 414 | 0 | **100.00** |
| ARO | 354 | 354 | 0 | **100.00** |
| UBERON | 174 | 174 | 0 | **100.00** |
| ENVO | 117 | 117 | 0 | **100.00** |
| **Total (11 `OK` namespaces)** | **24,481** | **24,446** | **35** | **99.86%** |

NCBITaxon is measured separately because `concept.concept_id` mixes `NCBITaxon:NNN` and the purl form and must be matched on `NCBITaxon[:_](\d+)`: **5,559 distinct IDs → 5,550 primary + 9 recoverable via `merged.dmp` = 100.00%**, 0 hard-deleted, 0 unexplained.

Our own taxon field: **662 distinct numeric NCBI IDs in `claim.taxon_ncbi_ids`, all present in `nodes.dmp`, 0 stale.** Zero overlap with BugSigDB's stale set.

### 8.2 BugSigDB's identifiers

Reviewed-set denominator only (25 `Incorrect` rows dropped, 671 literal `NA` cell tokens excluded from the instance count):

| | Value |
|---|---|
| Rows scanned | 16,637 |
| Taxon instances | 736,533 |
| Distinct taxids | 9,815 |
| Distinct stale taxids | **71** |
| Rows with ≥1 stale taxid | 456 (**2.741%**) |
| Stale instances | 491 (**0.067%**) |
| Recoverable via `merged.dmp` | 70 of 71 |
| Hard-deleted | 1 (`3120442`) |
| Instances resolving after merge-remap | 736,513 / 736,533 = **99.9973%** |

Quote the instance rate (0.067%) when talking about data volume and the row rate (2.741%) when talking about curation effort; they differ by 40× and are both correct. **Do not present this as BugSigDB being wrong.** A 99.93% as-is taxid resolution at scale is good curation; the number exists here only to show that the currency comparison was measured rather than asserted.

### 8.3 Licences were resolved from evidence

BugSigDB is **CC BY 4.0**, read in-band from `full_dump.csv` line 1, not assumed. Of the 12 ontologies: ARO, CHEBI, CL, GO, MONDO, NCIT, OBI are CC BY 4.0; DOID, ENVO are CC0 1.0; UBERON is CC BY 3.0; **EFO and HP remain unverified** and are not quoted as known. OLS4 `license: null` fields and GitHub licence-API 404s are not licence sources. GMrepo is **CC BY-NC**, which restricts redistribution and is why GMrepo is weak evidence here (33 PMIDs of overlap, non-commercial).

---

## 9. Known limitations — all of them

1. **28/28 is a selected subset.** 1.36% of comparable units. Never quote it as corpus-wide accuracy.
2. **Only 47 of 453 papers are shared**, and only **10** of those 47 yield a strictly scorable unit. No corpus-wide estimate is computable from this data.
3. **The strict rule's blind spot is real:** it cannot score a direction whose sentence names no BugSigDB arm, and both genuine reversals are exactly that shape (§7.2).
4. **40 reporting units carry more than one distinct BugSigDB direction** for the same `(study, taxon, group pair)` (all 40 have exactly 2). The harness keeps the first row and does not collapse them silently; first-row-wins is a disclosed resolution rule, not a validated one.
5. **81 units have rows that disagree on signature size** — the same taxon arrives via a 3-taxon signature in one row and a 12-taxon signature in another. Smallest-signature-size distribution over all 2,060 units (sums exactly): {1: 47, 2: 36, 3: 66, 4: 100, 5: 115, 6: 80, 7: 54, 8: 74, 9: 123, 10: 86, 11: 87, 12: 84, 13: 52, 14: 25, 15: 45, 16: 61, 17: 34, 18: 69, 19: 139, 20: 76, 21: 42, 22: 39, 24: 46, 25: 23, 26: 45, 28: 80, 29: 36, 31: 62, 32: 27, 33: 33, 40: 40, 42: 42, 44: 44, 52: 48}. Only 47 units come from single-taxon signatures, of which 3 are concordant.
6. **`DIRECTION_MULTITAXON_ONLY` (172 units) is not a claim of correctness.** It means we cannot fairly compare, because our record stores one direction for a taxon group. Smallest-claim-taxon-count distribution over those units (sums to 172): {1: 18, 2: 21, 3: 49, 4: 24, 5: 3, 6: 30, 7: 11, 10: 2, 12: 12, 13: 2}. The 18 units at 1 are ones where a single-taxon claim exists but stores no direction, so every *directional* claim on that taxon is multi-taxon — the disposition's assertion holds, it just arrives by a different route. A row-level view of the same data double-counts units and is reported separately in the JSON as `..._rows_view`.
7. **`DIRECTION_REFERENT_UNRESOLVED` (262 units)** splits 130 all-single-taxon-claims / 132 including multi-taxon claims. This is the largest addressable gap: adding a referent column to `claim` would move a large share of these two buckets into scorable territory.
8. **`WE_REPORT_NO_DIRECTION` (38 units)** = 25 units carrying a `MIXED` claim and 13 carrying `NO_ASSOCIATION` without `MIXED`. A `MIXED` claim is our own record disagreeing with itself, not agreement with anything.
9. **`DIRECTION_NOT_IN_TEXT` (68 units / 74 rows)** is uniformly `NOT_STATED` (108 raw occurrences). We store the field as not-stated and the text confirms it; these units contain no direction to compare.
10. **`DIRECTION_MIXED_IN_OUR_CDM` is 0 here but was 7 in v4** — the `CORREL` guard reclassifies correlational claims, which had been creating spurious `MIXED` records.
11. **Evidence is quoted only from the frozen CDM's own stored text.** Where that text does not resolve the arm, the unit is left `DIRECTION_REFERENT_UNRESOLVED` rather than guessed. Unlocatable evidence would be `UNABLE_TO_VERIFY`; it does not arise in this run because `section.section_text_original` is present for every matched paper.
12. **BugSigDB's `Incorrect` rows (25) and literal `NA` tokens (671) inflate every denominator** if left in. Every count here uses the reviewed set.
13. **MINERVA cannot corroborate an LLM build** — its triples are LLM-extracted, so agreement is not independent.
14. **Ontology comparison provides precision proxies only.** There is no recall signal in an ontology lookup, and absence from an ontology is never falsity.

---

## 10. What may and may not be claimed

**May be claimed**

- "On the 28 reporting units where our stored evidence names both BugSigDB arms, our direction agrees with BugSigDB's human curation in all 28 (Wilson 95% CI 0.879–1.000), across 10 studies."
- "A disclosed permissive rule scores 78 units at 64/78 = 82.1% (CI 0.721–0.890); 6 of its 14 disagreements were referent artifacts and 6 were non-comparable, leaving 2 genuine reversals."
- "BugSigDB and our corpus share 47 of 453 papers (10.4%, CI 7.9%–13.5%)."
- "Of 976 taxon-bearing claims on those 47 papers, 651 (66.7%) name a taxon BugSigDB also curated for that paper; of 587 directional taxon-bearing claims, 438 (74.6%)."
- "Of 1,517 distinct `(paper, taxid)` pairs BugSigDB curated for those papers, our claims name 361 (23.8%, CI 21.7%–26.0%)."
- "Our cited ontology identifiers resolve at 99.86% (24,446/24,481) against current OBO releases, and our NCBITaxon IDs at 100% after `merged.dmp` remap (0 stale of 662)."
- "BugSigDB's taxids resolve at 99.9973% after merge-remap (491 of 736,533 instances stale, 71 distinct IDs, 70 recoverable)."
- "1,038 of 2,060 comparable units name a taxon absent from our sectioned full text; 840 of those 1,038 are figure-sourced in BugSigDB."

**May not be claimed**

- "Our CDM is 100% / 82% / 46% accurate." No such number exists here.
- Any precision, recall, or F1 figure for the 453-paper build.
- "28/28 validates our directional extraction across the corpus." It validates 28 units in 10 papers.
- "Our ontology identifiers are newer than BugSigDB's, therefore we are more correct." Measured currency is a maintenance fact (§8), not correctness.
- Any statement built by quoting one rate without its denominator and CI, or the permissive rate without the strict rate.
- Anything described as human-annotated. The 47-paper reference is BugSigDB's human curation; **our** records remain machine-extracted and unreviewed by any human.

---

## 11. Reproducing this

```bash
cd /home/jkalra_hpc/Microbiome-CDM

# 1. comparison harness (read-only over the frozen DB)
python3 outputs/scratch/reference_kg_download/compare_bugsigdb_v5.py

# 2. consolidation producer -> bugsigdb_validation_report.json (asserts funnel arithmetic)
python3 outputs/scratch/reference_kg_download/build_validation_report.py

# 3. adjudications
python3 outputs/scratch/reference_kg_download/adjudicate_v4_discordant.py
python3 outputs/scratch/reference_kg_download/audit_concordant_units.py

# 4. identifier-currency measurements (one producer each, so the three
#    staleness/repair JSONs cannot drift apart)
python3 outputs/scratch/reference_kg_download/measure_bugsigdb_staleness.py
python3 outputs/scratch/reference_kg_download/check_id_resolution.py
```

Inputs are pinned: `data/reference_kg/raw/bugsigdb/full_dump.csv` (sha256 in `SHA256SUMS`), `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db`, `data/reference_kg/raw/{nodes,merged,delnodes}.dmp`, `data/reference_kg/raw/obo/*.obo`. Standard library only (`csv`, `json`, `sqlite3`, `re`) — no pandas or numpy.

Artifacts: `bugsigdb_validation_report.json`, `bugsigdb_comparison_v5.json`, `bugsigdb_comparison_v5_rows.json`, `bugsigdb_comparison_v4{,_rows}.json`, `bugsigdb_comparison_v3{,_rows}.json`, `bugsigdb_discordant_adjudication.json`, `bugsigdb_concordant_audit.json`, `bugsigdb_overlap_final.json`, `bugsigdb_taxon_staleness.json`, `bugsigdb_taxon_repair.json`, `cdm_taxon_staleness.json`, `id_resolution_report.json` — all under `outputs/scratch/reference_kg_download/`.

Source decisions, licences, taxonomy-cell grammar and the full comparator inventory: **`data/reference_kg/SOURCES.md`**.

---

## 12. Final decision — the seven questions

1. **Do we have an external human gold standard we overlap?**
   **Yes, on 47 papers only.** BugSigDB is a human curation and shares 47 of our 453 papers (10.4%, CI 7.9%–13.5%). No other candidate source has enough same-paper overlap to support a per-finding comparison.

2. **Does our stored direction agree with human curation?**
   **Where it can be resolved, yes — 28/28 (CI 0.879–1.000).** But that is 1.36% of comparable units, and the 28/28 is a selection effect; the defensible range for our directional agreement is **[0.72, 1.00]** on the units the permissive rule can reach.

3. **Where does the comparison break down, and why?**
   **In this order:** 50.39% of units name a taxon outside our input (figure/supplement sourcing in BugSigDB); 44.4% of in-text units have no claim (recall gap, ours); 46.1% of claimed units have an unresolvable subject arm (**`direction_refers_to` is NULL on all claims** — the largest addressable defect); 30.3% store one direction for a taxon group.

4. **Are there genuine disagreements?**
   **Two, both in study `30867711`** (`909932` Negativicutes and `216851` Faecalibacterium, Group 0 = pre-RYGB, Group 1 = 3-months-post-RYGB; BugSigDB increase vs our decrease). Six of the permissive rule's 14 "disagreements" were referent artifacts and six were non-comparable; 41 of v3's 95 were multi-taxon collapse.

5. **Is our identifier layer current?**
   **Yes, measured.** 24,446/24,481 = 99.86% of cited OBO identifiers resolve against current releases (35 stale across 11 namespaces, concentrated in OBI 21 and NCIT 11); NCBITaxon 100% after `merged.dmp` (9 remapped, 0 deleted); our own 662 claim taxids all primary. BugSigDB's taxids resolve at 99.9973% after remap.

6. **Is this resource validated?**
   **Partially, and the word matters.** Directional extraction is validated on a small, explicitly selected, high-confidence subset. Taxon recall against human curation is 23.8% of curated pairs. The corpus-wide accuracy question is **not answered** and cannot be answered from 47 of 453 papers.

7. **What should be done next?**
   In order of measured payoff: **(a)** add a `direction_refers_to` column to `claim` and populate it at extraction time — it is the single defect that removes 262 units (46.1% of everything we claim) from scorability; **(b)** stop storing one direction for multi-taxon claims (172 units, 30.3%), emitting per-taxon records instead; **(c)** close the 454-unit in-text recall gap, which is our own extraction failing on evidence we already hold; **(d)** treat figure/supplement sourcing (1,038 units, 50.39%) as an input-scope decision to make deliberately rather than an error to fix; **(e)** extend the comparison beyond 47 papers if a second human-curated source with real same-paper overlap ever appears — none exists today.

**Bottom line:** *our direction agrees with human curation wherever our own text lets us determine which arm we meant — 28 of 28 — across 10 papers; but only 1.4% of comparable units reach that bar, the dominant cause is a missing referent field rather than a wrong direction, and the largest single block of uncompared units is a sourcing difference between our full text and BugSigDB's figure panels. This is a positive signal on a small, disclosed subset, not a validation of the 453-paper build.*
