# Component P — Manuscript Claim Impact

**Audited object:** the manuscript's numeric and factual claims as registered in
`paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (**133 rows / 127 distinct
claim IDs**), plus the surrounding prose that carries them in `paper/publication/manuscript_draft/`
and the prohibition list in `paper/publication/PUBLICATION_INDEX.md:57`.
**Evidence base:** `MANUSCRIPT_CLAIMS_REGISTER.csv` (133), `MANUSCRIPT_NUMBER_AUDIT.csv` (434 rows:
305 `REGISTER` / 129 `REPORT`), `benchmark/benchmark_analysis.json`, `EXHAUSTIVE_INTEGRITY_REPORT.md`,
`REMAINING_PUBLICATION_BLOCKERS.csv` (21 rows), and the measured findings of components A–N in this
audit (`15_ISSUE_REGISTER.csv`, 148 rows). *[corrected 2026-11-05: the register closed at **154
rows** — 146 report issues + 8 dated amendments. `148` was the row count at the moment this report
began and was not revised when the Component-I, Component-N and amendment rows were appended; no
finding or percentage below depends on it. Recorded as cross-report consistency correction **CC-01**
in `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md` §7 rather than as a ninth amendment row, because the
ranked plan (`18_ACTION_PLAN.csv`) is keyed to the closed 154-row register.]*
**Independence:** every claim that a component of this audit independently recomputed is marked
recomputed here; every claim that was only *read* is marked as such. **This report adds no new
measurement of its own** except the four degradations of reading (§5) and the two reconciliations of
arithmetic (§6), each of which is shown against the frozen artefacts.

> **Scope.** This component judges whether each manuscript claim is *supportable by the audit's own
> evidence*, and at which evidence tier. It does **not** re-derive the manuscript, does not edit it,
> and does not decide publishability on its own. Correctness of the underlying values is components
> A–N; the three go/no-go decisions are report 00.
>
> **This report contains no accuracy, recall, precision or completeness figure for the corpus.**
> Where such a figure appears in the manuscript, the entry records that it does not exist.

---

## 1. The claim inventory, and what "132 MATCH" does and does not mean

`claims_register.py` recomputes each registered number from the frozen releases and writes a status
of `MATCH`, `STATEMENT` or `MISMATCH`. The shipped register reads:

| Status | Rows | Meaning |
|---|---|---|
| `MATCH` | 132 | The *stated* value equals the *recomputed* value, from the release the generator points at |
| `STATEMENT` | 1 (`H01`) | Not a number; a disclosure ("NONE (no human annotation performed)") |
| `MISMATCH` | **0** | No registered value failed its own recomputation |

Three properties of this table must be stated before any of it is quoted:

1. **`MATCH` certifies arithmetic, not truth.** It says the number in the manuscript is the number
   the generator computes from the same frozen artefact. If a *definition* underlying both is wrong,
   the claim matches and is still misread. `K08` ("quotes verbatim 88.2%") matches its generator
   exactly and is nonetheless the figure that Component F shows is **not** a support measure (§4.3).
2. **A `MATCH` population has no scope protection.** The register is a fixed list. A claim that is
   *absent* from it cannot fail it. `X07` (118 / 2 / 1 validation tests) is present; the
   *consequence* of `X07` — that 2 schema/value/provenance tests **fail** — has no counterpart in
   any component report and was not re-derived by this audit (§5.4).
3. **`H01` is the only disclosure-shaped row.** The absence of human annotation is asserted **once**,
   in the register, and repeated in each draft header. That is the correct shape — a disclosed null —
   but it is a single sentinel: nothing in the register forces any *other* claim to be tiered, which
   is why this report exists.

### 1.1 Distribution by section

| Section | Rows | Dominant evidence tier |
|---|---|---|
| LLM-judge suppl. | 15 | **4** — model-generated validity |
| Mentions | 14 | internal (structural) |
| Catalogue | 14 | internal (structural) + **1** deterministic |
| Validation | 14 | **1** deterministic (`E01`,`E02`), **4** model judge (`J01`–`J08`), **1** disclosure (`H01`) |
| BugSigDB suppl. | 11 | **2** — external-reference grounding |
| Corpus | 10 | internal (structural) |
| Benchmark | 10 | **1** — public gold standard |
| KG suppl. | 9 | **3** (KG support, `Q07`–`Q09`) + **4** (judge, `Q03`–`Q06`) |
| CDM | 8 | internal (structural) |
| Mappings | 7 | internal (structural) |
| Triple ref. suppl. | 6 | **2**/**3** |
| Terms | 6 | internal (structural) |
| Figures | 3 | internal / **2** |
| Definitions | 3 | internal (structural) |
| Triples | 3 | internal (structural) |
| **Total** | **133** | |

**69 of the 133 claims (51.9%) are internal structural counts** — they certify that the artefact is
internally consistent, and are the tier at which this audit is strongest. Only **10 claims (7.5%)**
are Tier 1, and **all ten are about the benchmark, not the corpus** (§3).

---

## 2. The four evidence tiers, reused verbatim from report 09 §4

Report 09 §4 is the canonical statement; it is reproduced here unchanged so that a reader of the
claim table does not have to hold two documents open.

| Tier | What it is | This audit's evidence for it | What it can support |
|---|---|---|---|
| **1. Public gold standard** | Human-annotated BC5CDR / BioRED | 27 configs × 2 corpora, CIs, p-values | Model ranking on chemical/disease (and 4 more BioRED types) mention finding. **Nothing about the corpus.** |
| **2. External-reference grounding** | BugSigDB, CTD, Disbiome, external lexicons | triple-reference check; BugSigDB field concordance; corpus grounding | Whether a specific fact appears in a curated reference. Coverage, not accuracy. |
| **3. KG support** | Curated-KG membership of an edge | 622 resolved microbe–disease edges, 13.18% vs 5.78% chance | Coverage of a small resolved subset. Absence is untested, not incorrect. |
| **4. Model-generated validity** | LLM judges, DeepSeek/Gemma/Qwen verdicts | judge layer, cleaned layer, LLM-judge supplement | Model behaviour. Never annotation. |

**No claim in the register may be averaged, ranked, summed or compared across tiers.** The manuscript
already respects this in three places — `03_discussion.md:28-29` states factual accuracy and
completeness "not established"; `02_results.md:3` states "no result below is an accuracy estimate
unless it is F1 on a public gold standard"; `01_methods_and_resource.md:148` calls grounding
"precision proxies, not accuracy". Those statements are correct and this report confirms them rather
than contradicting them. What this report adds is the per-claim tier assignment that the draft does
not carry.

---

## 3. Tier 1 claims — the ten benchmark claims, and the one thing they must never be used for

| Claim | Stated | Audit status |
|---|---|---|
| `B05` | 27 public-benchmark configurations | **Recomputed**, consistent with `NER_TYPE_COVERAGE_MATRIX.csv`; 27 configs over 21 systems, **7** carry the in-domain `†` flag |
| `B01` | BC5CDR best (PubTator3) exact F1 **90.1** | **Recomputed by Component I**; `pubtator3` is `IN_DOMAIN` and is an **annotation-source lookup**, not a trained model. Reference-only, **not deployable** for section NER (`predict_text` raises `NotImplementedError`) |
| `B02` | BioRED best (HunFlair2) exact F1 **80.6** | **Recomputed**; `80.62` per-type `OrganismTaxon` exact micro (tp 363 / fp 13 / fn 30 over 393 gold) reproduces from `preds/biored__hunflair2.jsonl`. The runner-up is statistically indistinguishable (78.3, p = 0.274) |
| `B03` | BC5CDR best LLM (Qwen 3-shot) exact F1 **69.5** | **Recomputed** (`0.6951`); also ties `gliner_v25_medium` at 0.6922 within CI |
| `B04` | BioRED best LLM (Qwen 3-shot) exact F1 **66.2** | **Recomputed** (`0.6623`) |
| `H03` | 26 corpus-benchmark configurations | **Recomputed**; 26 ran, **25** carry a grounding block (`scispacy_lg` carries none) |
| `H04` | Spearman BioRED F1 vs corpus grounding, disease **0.749** | **Read, then contextualised** — see §6.2 |
| `H05` | Spearman BioRED F1 vs corpus grounding, organism **0.023** | **Read, then contextualised** — see §6.2 |
| `H06` | Disbiome associations recovered by GLiNER v2.5 biomed **1,456** | **Read**; recovery count, not recall (no denominator of true Disbiome associations in scope) |
| `H07` | Highest corpus grounding of any configuration and type **41.3%** | **Recomputed, and qualified.** The 41.3% is a genuine external-vocabulary lookup, but the same column also carries a `VARIANT_RE.match()` regex (pooled **2.5%**, 1,257/50,249 distinct strings) and the definitional CellLine zero; the denominator is **distinct strings, not mentions**; and the shipped `other_type_pct` (up to **19.1%**, >10% in 9 cells) has never been reported. See `CQA-I-AMEND-2026-11-05-1` |

**The Tier-1 hazard, restated.** The single most likely misreading of this manuscript is
"our NER achieves F1 0.90". It does not. PubTator3 achieves 0.90 on **BC5CDR abstracts, in-domain,
as a database lookup**. The manuscript's own framing is correct; the risk lives in any downstream
summary that drops "PubTator3", "BC5CDR" or "in-domain" — which is exactly what happened once already
in `FIGURE_PLAN.md` (figure 5 plots CellLine 0.0% as a model outcome; see `CQA-I-AMEND-2026-11-05-1`).

**Two further Tier-1 qualifications the manuscript must carry:**

- **The top BC5CDR row is not deployable.** `pubtator3` cannot run on our sections. Reporting it as
  the "best" row without the deployability flag invites the reader to assume it is available.
- **`span_only` is not span-only.** It filters through each model's label map and equals the
  all-span F1 for **42 of 54** runs, so a "typed vs untyped" contrast drawn from it is not a pure
  contrast.

---

## 4. Tier 2/3/4 claims — the claims most exposed to over-reading

### 4.1 Tier 2 — external-reference grounding (BugSigDB `N01`–`N11`, triple ref `X01`–`X06`)

All eleven BugSigDB claims and all six triple-reference claims recompute. Their **standing** is the
issue, and report 11 §4 / report 12 §4 set it:

- **`N02` 27.7% / `N04` 57.3% / `X02` 50.4%** are compared against an explicit cross-paper chance
  baseline (9.0% / 18.1% / 16.1%). That is the correct construction, and each is **coverage against a
  curated slice**, not accuracy.
- **`X05` 22.4% vs 24.2% chance is a null result** on CTD chemical–disease support, and **`X06` 0/7**
  is uninformative (CI to 35.4%). Both must be reported as null/uninformative. A draft that lists
  `X05` among "validated" claims would be misusing it.
- **`N09` sequencing type 50.0% / platform 89.4% / statistical test 3.6%** — the 3.6% is the honest
  number and is far below the others; it must not be hidden behind the 89.4%.
- **`N10` is a `0` in the last position** ("our findings": 0 taxon IDs absent from current NCBI
  Taxonomy). A clean zero, correctly stated.

**Tier-2 limit, applied uniformly:** locating a fact in a curated reference shows the fact is
**covered**, not that it is right; and failing to locate it shows **nothing at all**, because absence
was never tested. This applies to the 13.18%-vs-5.78% microbe–disease figure (`Q07`) as much as to
the BugSigDB fields.

### 4.2 Tier 3 — KG support (`Q07`, `Q08`, `Q09`, `X03`, `X04`)

- **`Q07` microbe–disease edges 622 resolved / 13.2% in Disbiome or BugSigDB / 5.8% chance** is the
  audit's strongest graph-level external signal (2.3× chance). Component G/L confirm it.
- **`Q08` kept 15.4% vs dropped 6.4%** validates the *selection* the cleaning step made; it says
  nothing about whether the kept labels are right. Same for `X03` (+10.0 pts).
- **`X04` 11/12 direction agreement** is a 12-item denominator and must be presented with it.
- **The denominator ceiling:** the reference exercise reaches **847 / 25,788 = 3.28%** of the graph,
  because no triple endpoint carries an ontology identifier (`CQA-G-01`, 25,788/25,788
  `unresolved`). A reader who takes these percentages as graph-wide quality is reading 3.28% of the
  graph as if it were all of it.
- **`OTHER_RELATION` 68.7%** (`CQA-G-02`, 17,717 triples of which 15,665 are flagged) is
  **uncheckable** against these references. It is not "unchecked but fine".

### 4.3 Tier 4 — model-generated validity (`L01`–`L15`, `J01`–`J08`, `Q03`–`Q06`)

This is the largest block in the register (**15 + 8 = 23 claims, 17.3%**) and the weakest tier.
Component F's finding is structural, not marginal:

- **The two judges agree at κ 0.282** on both-valid text values, and **0.084** across all classes.
  `L13`'s 730,195 judged items are the *input* to a process whose inter-rater reliability is near
  zero by the conventional bands.
- **`J01` 2.9% / `J02` 6.6% FAIL are model verdicts**, and `J07`'s gap-filled 19.1% vs `J08`'s
  original 5.6% is a **model-judge contrast**, not a measurement that gap-filled values are worse.
- **`284,325` / `242,158` history.** `284,325` reproduces exactly on the all-fields scope
  (544,992 cells). The `81.15% / κ 0.2321 / 242,158` triple was **reproducible from no scope** and is
  recorded as *missing provenance, not fabrication* (`CQA-F-AMEND-2026-11-05-2`). The register's own
  `J04` 0.85 / `J05` 0.282 are the text-value both-valid values and are the ones to quote.
- **`L09`–`L12` (triples judged well-formed 39.3%, valid subject+object 38.7%, specific relation 12.5%,
  too-generic 29.5%)** are the most tempting numbers in the supplement and the most dangerous: they
  read exactly like accuracy. They are **one model family's opinion of another model family's output**.

**Tier-4 rule, stated once for the whole manuscript:** a judge verdict is a **model-behaviour
measurement**. It is never annotation, never validation, never accuracy, and never "expert review".
`PUBLICATION_INDEX.md:57` already forbids the three phrasings; report 00 restates the rule.

### 4.4 Tier "internal structural" — 69 claims, the audit's strongest ground

Corpus (`C01`–`C10`), Mentions (`M01`–`M14`), Catalogue counts (`K01`–`K07`, `K11`–`K13`), CDM
(`X01`–`X08`), Mappings (`P01`–`P07`), Terms (`T01`–`T06`), Definitions (`D01`–`D03`), Triples
(`R01`–`R03`), Figures (`F01`–`F02`). These are the claims this audit can defend without
qualification, and it does:

- `C07` 4,006 sections, `C08` 0/4,006 hash mismatches — **re-verified**, with the
  SQL-vs-Python caveat of `CQA-A-AMEND-2026-11-05-1`.
- `M01` 2,505,684 mentions, `T02` 162,409 canonical terms, `K01` 52,400 catalogue records,
  `R01` 25,788 triples, `X01` 44 tables, `X02` 866 columns, `D01` 6,773 definitions — **all
  independently recomputed by components A–H** and all exact.
- `T04` "T02 + T03 = T01" (162,409 + 3,582 = 165,991) — **arithmetic verifies**, and reconciles
  `canonical_terms.jsonl` 165,991 = 162,409 live + 3,582 `removed_canonical_term`.
- `P01` 334,231 / `P02` 314,772 / `P03` 16,622 / `P04` 2,837 — **verify**, and the
  DB↔terminology discrepancy (331,394 vs 334,231) is fully explained by `317,521 live-term rows +
  11,473 removed-term rows + 5,237 NOT_IN_TERMINOLOGY = 334,231`, with a residual 2,837 that is
  multiplicity on 2,727 pairs (§6.1).

**One structural claim is exact yet misleading, and the manuscript must split it:**
`R01` "25,788 relationship triples" is arithmetically true. `CQA-G-02` shows **17,717 of them
(68.7%) carry `OTHER_RELATION`**. The headline must be the typed subset (**8,071**) and the generic
bucket (**17,717**) reported separately.

---

## 5. Four traceability defects in the claim layer itself

These are defects in the *manuscript's* claim apparatus, discovered while building this report.
None of them is a data defect. All four are cheap to fix and all four are disqualifying if a reviewer
finds them first.

### CQA-P-01 — `X01`–`X06` are each used twice for different claims
- **Severity:** MODERATE
- **Type:** Audit-class finding against the claim layer (documentation)
- **Evidence:** 133 register rows carry **127 distinct `claim_id`s**. `X01`, `X02`, `X03`, `X04`,
  `X05`, `X06` each appear twice with different values and different sections:

  | ID | Twice as (Triple ref. suppl.) | described as (CDM) |
  |---|---|---|
  | `X01` | 518 (triple, paper) items / 45 papers | 44 tables |
  | `X02` | 50.4% taxon in BugSigDB / 16.1% chance | 866 columns |
  | `X03` | 54.3 / 44.3 / 10.0 points | 45 registered runs |
  | `X04` | 11/12 direction agreement | 4 `AS_IN_3.0.2_UNVERIFIED` runs |
  | `X05` | 49 / 22.4% / 24.2% | 79 change-log entries |
  | `X06` | 7 / 0 gene–disease | 0 unresolvable run ids |

- **Affected:** 12 rows / 6 IDs = 9.0% of the register.
- **Scientific impact:** None to any value; every value is separately correct.
- **Publication impact:** **High.** A `[X01]`-style bracket in the draft resolves to two different
  numbers depending on which row a reader reaches first. A supplementary table keyed on `claim_id`
  will silently double-key. A reviewer who spot-checks `X01` has a 50% chance of finding the wrong
  value and concluding a number is wrong.
- **Recommended action:** Disambiguate additively — `X01tr`/`X01cdm` etc. — leaving the frozen
  register's values untouched but adding a disambiguated column. Do **not** renumber (renumbering
  breaks every existing bracket in the draft).
- **Blocking:** **publication** (traceability), not release.

### CQA-P-02 — Three files say "80 / 80" while the register holds 133 claims / 127 IDs
- **Severity:** MODERATE
- **Type:** Confirmed defect (stale self-description)
- **Evidence:** `manuscript_draft/01_methods_and_resource.md:7`, `manuscript_draft/02_results.md:3`
  and `PUBLICATION_INDEX.md:7` all state "80 / 80 match" (or "80 / 80 numeric claims recompute").
  The shipped register has **133 rows**, **127 distinct IDs**, **132 `MATCH`** and **1 `STATEMENT`**.
  The number 80 predates 53 added claims.
- **Affected:** 3 files, 1 figure each.
- **Scientific impact:** None.
- **Publication impact:** **High for credibility, zero for correctness.** The claim apparatus is
  *stronger* than it advertises, and advertising a weaker number is still a misstatement. Worse, a
  reviewer who counts 133 rows and reads "80 / 80" cannot tell whether 53 claims are unverified or
  whether the header is stale — and there is no way to distinguish the two from inside the
  manuscript.
- **Recommended action:** Regenerate the three headers from the register at build time rather than
  hand-writing the count. State "133 registered claims: 132 MATCH, 1 disclosed STATEMENT, 0
  MISMATCH, 127 distinct IDs" and cross-reference `CQA-P-01`.
- **Blocking:** **publication** (traceability).

### CQA-P-03 — "No dangling link was found" contradicts a 5,237-row undeclared dangling set
- **Severity:** HIGH
- **Type:** Description-vs-behaviour (claim layer) — **the two statements are reconcilable, but only
  by stating the scope**
- **Evidence:** `manuscript_draft/02_results.md:29` — "Every identifier, link, offset, hash, manifest
  and run pointer was checked over all rows. **No dangling link**, cross-paper link or hash mismatch
  was found." `final_validation/EXHAUSTIVE_INTEGRITY_REPORT.md:16` "0 dangling" (terminology) and
  `:20` "0 dangling, 0 cross-paper" (catalogue). Against that, `CQA-H-03` measures **5,237
  `term_concept_map.term_id` values that resolve to no `canonical_term` row**.

  **Reconciliation.** The two are not in conflict *once the scope is named*: the integrity report
  checks the **declared** link graph and the term layer's own referential closure is not part of it,
  and the 5,237 are the documented sentinel `term_status = 'NOT_IN_TERMINOLOGY'` (a deliberate marker
  for mapping candidates whose term was removed in review — see §6.1). They are **not breakage**.
  But the manuscript states the property without the scope, and the property as stated is false at
  the database level.
- **Affected:** 5,237 rows; 1 manuscript sentence; 2 integrity-report cells.
- **Scientific impact:** None — no query is broken, and `NOT_IN_TERMINOLOGY` is intentional.
- **Publication impact:** **High.** This is the specific class of claim that collapses on review:
  a reviewer who runs `SELECT COUNT(*) FROM term_concept_map m LEFT JOIN canonical_term c ON
  m.term_id=c.term_id WHERE c.term_id IS NULL` gets 5,237 and the manuscript says 0. The 5,237 are
  defensible; the sentence is not.
- **Recommended action:** Rewrite as "no dangling link **within the declared link graph**; 5,237
  mapping rows point at terms deliberately removed in review and are marked `NOT_IN_TERMINOLOGY`".
  Add the DB-level check to `EXHAUSTIVE_INTEGRITY_REPORT.md` as a third scope row. **Do not delete
  the sentinel.**
- **Blocking:** **publication** (accuracy of a stated integrity property).

### CQA-P-04 — `X07` (118 / 2 / 1) has no component-report counterpart, and the 2 failures are undiscussed
- **Severity:** MODERATE
- **Type:** Coverage or scope (un-re-derived claim)
- **Evidence:** `X07` = "validation tests pass / fail / conditional **118 / 2 / 1**" and
  `02_results.md:25` states "118 of 121 schema, value and provenance tests pass; 2 fail and 1 is
  conditional". No component report (A–N) re-derives the 121-test suite, and none identifies which
  two tests fail. `X08` ("3.0.3 verification overall: True") is likewise read, not recomputed.
- **Affected:** 1 register row, 1 manuscript sentence, 2 unidentified failing tests.
- **Scientific impact:** **Unknown, and that is the problem.** Two failing schema/value/provenance
  tests inside the release's own validator are a known-unknown this audit did not close.
- **Publication impact:** **Moderate.** Reporting "2 fail" without naming them is worse than either
  naming them or not running the suite: it tells a reviewer something is wrong and refuses to say
  what.
- **Recommended action:** Enumerate the 2 failing and 1 conditional test by name and their failure
  messages, then either fix the tests or state each failure's scope. This audit **did not re-derive
  `X07`** and says so rather than asserting agreement.
- **Blocking:** **publication** (a stated defect left unnamed).

---

## 6. Two arithmetic reconciliations the manuscript needs

### 6.1 Mention linkage: the manuscript says 87.8%, report 02 says 86.55% — both are right, about different sets

| Source | Numerator | Denominator | Figure |
|---|---|---|---|
| `M13` / `M10` (register, manuscript) | **2,198,766** `LINKED` + `LINKED_BY_TYPE` | 2,505,684 | **87.8%** |
| `02_ENTITY_EXTRACTION_QUALITY.md:41` (`CQA-B-06` context) | 2,168,717 `LINKED` only | 2,505,684 | **86.55%** |

**Verified independently in the frozen DB:** `canonical_term_id IS NOT NULL` = **2,198,766**
(87.75%); `term_link_status` = `LINKED` **2,168,717** / `LINKED_BY_TYPE` **30,049** /
`NO_CANONICAL_TERM` 299,846 / `AMBIGUOUS` 7,072. The identity
`2,198,766 + 299,846 + 7,072 = 2,505,684` closes exactly.

`LINKED_BY_TYPE` is a real resolution — `fix_terminology_offsets.py:83` assigns it when the type
breaks a tie and a unique term results, so `canonical_term_id` **is set** on those 30,049 rows. Report
02's 86.55% therefore **understates** linkage by 1.20 points (30,049 mentions) because it counts only
the `LINKED` token.

- **Resolution:** the manuscript's 87.8% is the correct figure for "mentions linked to a canonical
  term", and it agrees with the DB column that a reuser would actually query. **Report 02 is
  corrected by `CQA-B-AMEND-2026-11-05-1` (§8).** The 11.97% remainder in `CQA-B-06` (`NO_CANONICAL_TERM`
  only, excluding `AMBIGUOUS`) stays as it is but is relabelled as "no canonical term and not
  ambiguous", so that 87.75% + 11.97% + 0.28% = 100.02% closes.

**Also verified, and consistent with `CQA-H-04`:** `term_mention` has **2,505,684** rows but only
**1,948,059** distinct `mention_id`, so **557,625** rows share an id — exactly `M14`'s stated value.
Distinct `(paper_id, section_id, start_offset, end_offset)` = **1,362,888**; distinct
`occurrence_key` = **1,362,931**. The 45.6% duplicate-span rate in `CQA-H-04` is confirmed and is the
same fact as `M14` described from the other side. Both are correct; the manuscript must not present
`M14` as a defect (multi-model observation is by design) nor as a curiosity (it means `term_mention`
is not a mention table).

### 6.2 `H04` / `H05`: bench-vs-corpus association, over 16–22 models, is not corpus accuracy

The manuscript states at `02_results.md:108`: "public F1 predicted corpus grounding for diseases
(ρ 0.75) but not for organisms (ρ 0.02)". Both recompute from
`benchmark/benchmark_analysis.json → public_vs_corpus.correlation`:

| Type | ρ (F1 vs grounding) | ρ (precision vs grounding) | n_models |
|---|---|---|---|
| DiseaseOrPhenotypicFeature | **0.749** | 0.853 | 20 |
| ChemicalEntity | 0.252 | 0.305 | 21 |
| GeneOrGeneProduct | 0.200 | 0.308 | 22 |
| SequenceVariant | 0.112 | −0.124 | 16 |
| **OrganismTaxon** | **0.023** | 0.270 | 19 |

Generator: `src/scripts/final_validation/benchmark_analysis.py:34`; pairs are built only where
`g["unique"] >= 50`, which is why `n_models` varies and why `SequenceVariant` is 16.

**What these five numbers can support:** an association *across models* between how well a model does
on a public gold standard and how many of its corpus-emitted strings match an external vocabulary, for
that type. It is a statement about the **models**, not about the corpus.

**What they cannot support, and must not be written as:**
1. **Not corpus accuracy.** Better bench F1 does not mean better corpus extraction. For
   `OrganismTaxon` the association is **essentially absent (ρ 0.023)** — the manuscript already says
   this and is right to. `SequenceVariant` (0.112) and `GeneOrGeneProduct` (0.200) are weak in the
   same direction.
2. **Not a validated bridge.** Five tests, two of them near zero, one moderate, no multiplicity
   correction and no preregistration. The honest description is "one type showed a moderate
   association; four did not", i.e. **the bridge from benchmark to corpus is not established for any
   type except disease, and even for disease the association is across models, not a transfer
   guarantee.**
3. **The `ρ = 0.749` for disease must never be quoted without `n = 20`.** A Spearman over 20
   heterogeneous configurations with `SequenceVariant` and `scispacy_lg` in the pool is not a
   generalisable relationship.

**Report 09 does not yet discuss `H04`/`H05`.** That is a gap in report 09, not an error: report 09's
§4 tier table already says a Tier-1 result supports "nothing about the corpus". This report records
the correlation set as the audit's answer to `H04`/`H05` and flags that report 09 should carry it
(§8).

---

## 7. The prohibition list, checked claim by claim

`PUBLICATION_INDEX.md:57` lists ten claim families that must not appear. Each is mapped to the audit
finding that makes it unsafe:

| Forbidden claim | Why it is unsafe | Audit evidence |
|---|---|---|
| Any accuracy / recall / "validated" claim | No human annotation exists | `H01` (STATEMENT); `03_discussion.md:28`; no Tier-1 result on corpus |
| Model-judge agreement as inter-annotator agreement | κ 0.282 / 0.084 between two models is not κ between two people | `J04`/`J05`; `CQA-F-AMEND-2026-11-05-2` |
| "LLMs beat NLP methods" | Ranking flip-flops by corpus and top two are statistically tied | `B01`–`B04`; `p = 0.274` |
| DeepSeek-V4-Flash judging as "expert review"/"validation"/accuracy | It is a model screen by one model family | Tier 4; `L09`–`L12` |
| "Independent judges confirmed the catalogue", "most values consistent", "semantically coherent", "ready for adoption", "legally cleared" | Two judges disagree at κ 0.282; 179 papers unreviewed | `CQA-N-01`, `CQA-B-05`-class judge limits |
| Source-first figures as recall/coverage | `V01`–`V03` are agreement between two of our own extraction paths | `02_results.md:29-32` already correct |
| "Publicly available" / a DOI | 39.5% of papers ship withheld pending an unreviewed rights process | `CQA-N-01` (179 papers, 9,974,210 chars withheld) |
| "Scientifically validated CDM" | `B5` independent expert review outstanding | `REMAINING_PUBLICATION_BLOCKERS.csv` B5 |
| Any result on the 168k samples themselves | The CDM is built on cited literature, not the compendium; `samples` table is empty | `C05`/`C06` (BioProject-level link only) |
| Claim F's 100% | Circular by construction | `CQA-I-AMEND-2026-11-05-1` retired the related grounding-circularity claim; the Claim-F 100% remains circular and is a separate matter |

**Two live violations of the list exist in the draft layer today, both already known and both
editorial rather than data:**

1. `02_results.md:108` — "**Unreliable LLMs:** several LLMs **invented** strings (up to 44%)" reads a
   *grounding shortfall* as an *invention rate*. Grounding is measured against external lexicons on
   **distinct strings**; a string that fails to ground may be a valid term absent from the lexicon.
   The 44% is also the `other_type_pct`-adjacent figure, not a clean measure.
   **Action:** restate as "did not match any external vocabulary (up to X%)", and disclose the
   unreported `other_type_pct` (up to 19.1%). `CQA-I-AMEND-2026-11-05-1`.
2. `FIGURE_PLAN.md:11` — figure 5 plots CellLine grounding **0.0%** as a model outcome. It is
   definitional (`ground()` returns `set()` for CellLine). **Action:** drop CellLine from the figure
   or annotate it as "not measured".

`01_methods_and_resource.md:148` ("precision proxies, not accuracy") and `03_discussion.md:26`
(naming the external vocabularies) are already correct and should be preserved verbatim.

---

## 8. Additive corrections this report records

### `CQA-B-AMEND-2026-11-05-1` — report 02's linkage percentage counted one status token
- **Date:** 2026-11-05
- **Location:** `02_ENTITY_EXTRACTION_QUALITY.md` (Reusability row of §1, and `CQA-B-06`).
- **Was:** reusability indicator "linked-to-term = 2,168,717/2,505,684 = **86.55%**".
- **Now:** "linked-to-term = **2,198,766/2,505,684 = 87.75%**" (LINKED + LINKED_BY_TYPE); the
  86.55% figure is retained in the record as "`LINKED` token only".
- **Why:** `canonical_term_id IS NOT NULL` on exactly 2,198,766 rows, matching `M10`/`M13` (87.8%).
  Report 02 counted only the `LINKED` status token and omitted the 30,049 `LINKED_BY_TYPE` rows,
  which also carry a `canonical_term_id`. Verified read-only in
  `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db`.
- **Scope:** the percentage and its denominator description only. `CQA-B-06`'s MODERATE severity, its
  "11.97% unlinked" recomputation (`NO_CANONICAL_TERM` 299,846) and all ten Component-B ratings are
  **unchanged**. The remainder is relabelled "no canonical term and not ambiguous" so that
  87.75% + 11.97% + 0.28% = 100.02% closes with rounding.
- **Type:** reporting defect in this audit, not a data defect.
- **Reproducer:** the three `COUNT(*)` queries in §6.1 against the frozen DB (`mode=ro`).

### `CQA-P-AMEND-2026-11-05-1` — report 09 does not yet carry `H04`/`H05`
- **Date:** 2026-11-05
- **Location:** `09_NER_BENCHMARK_QUALITY.md`, proposed new §2.4.
- **What is missing:** the five `public_vs_corpus.correlation` rows (`H04`, `H05`) and their
  `n_models` denominators. Report 09's §4 already establishes that a Tier-1 result supports nothing
  about the corpus, so the *conclusion* is not in conflict; the *evidence* is simply absent from the
  report while being present in the register.
- **Status:** **recorded here, not applied to report 09** in this pass — report 09 carries a dated
  SHA-256 seal and four amendment records, and adding a section would require a further reseal. The
  table in §6.2 of this report is the authoritative statement in the meantime, and report 00 cites it.
- **Type:** coverage gap in this audit's own reporting.

---

## 9. What this component demonstrates, and what it does not

**Demonstrates:**
- **133 registered claims, 127 distinct IDs, 132 `MATCH`, 1 `STATEMENT`, 0 `MISMATCH`** — the claim
  apparatus is complete and every registered number recomputes from the frozen releases.
- Every one of the seven headline construction counts (453 papers, 4,006 sections, 2,505,684 mentions,
  162,409 terms, 52,400 records, 25,788 triples, 6,773 definitions) is independently reproduced by a
  different component of this audit and is exact.
- The tier assignment is stable: **10 claims Tier 1 (all benchmark, none about the corpus), 17 Tier 2/3,
  23 Tier 4, 69 internal structural, 3 mixed, 1 disclosure.**
- `M13` 87.8%, `M14` 557,625, `T04`'s additive identity, `P01`–`P04`, `D01`, `K01`, `R01`, `X01`,
  `X02` all verify exactly against the frozen DB — recomputed here, not merely read.
- `H04`/`H05` recompute from `benchmark_analysis.json` and the manuscript's own framing of them is
  correct.
- The four tier-separation statements already in the draft (`02_results.md:3`,
  `03_discussion.md:28-29`, `01_methods_and_resource.md:148`) are consistent with this audit and
  should be preserved.

**Does not establish:**
- **That any corpus claim is accurate.** `MATCH` certifies arithmetic against a frozen artefact; not
  one claim was checked against human annotation, because none exists (`H01`).
- That the tier assignment makes a weak claim strong. Twenty-three claims sit at Tier 4 and their tier
  does not improve by being registered.
- That the manuscript is internally consistent as a document. Four traceability defects remain
  (`CQA-P-01`–`CQA-P-04`), two of them (duplicate IDs, stale "80 / 80") survive in the shipped draft
  and the third (dangling links) is a false as-stated property.
- That `X07`'s two failing tests are benign. **They were not re-derived by this audit.**
- That the benchmark→corpus bridge exists. One moderate association out of five, uncorrected for
  multiplicity, over 16–22 models, is not a bridge.
- Anything about the 179 rights-unreviewed papers beyond the fact that their text is withheld
  (Component N).

---

## 10. Component verdict

The claim layer is **the most trustworthy part of this project and it is mislabelled in three
places.** Every registered number recomputes; the tier separation the draft already states is
correct; and the four-tier vocabulary holds under every check this audit applied. Against that, the
register double-keys six IDs, the drafts advertise 80 claims where there are 133, one stated
integrity property is false as written at the database level, and two failing validator tests are
reported without being named.

None of those is a data defect. All four are the kind of defect that costs a reviewer's trust in the
numbers that *are* sound, and all four are fixable by additive edit.

**Publication readiness of the claim layer: `CONDITIONAL`.** The claims are supportable at the tier
each belongs to; the traceability apparatus needs four additive fixes and no re-measurement. The
release question is not decided here — see report 00.

---

## 11. Cross-references

- Tier vocabulary: `09_NER_BENCHMARK_QUALITY.md` §4 (canonical), §6a for the grounding correction.
- Benchmark detail behind §3 and §6.2: `NER_TYPE_COVERAGE_MATRIX.csv`,
  `NER_MODEL_DEPLOYABILITY.csv`, `NER_RECOMPUTATION_CHECK.csv` (1,407 rows: 1,186 `MATCH`,
  0 `MISMATCH`, 0 `MISSING`, 69 N/A, 152 NEW).
- Judge-layer limits behind §4.3: `06_CATALOGUE_QUALITY.md` §4.3–§4.5 and §7
  (`CQA-F-AMEND-2026-11-05-2`).
- Rights posture behind §7: `14_RIGHTS_READINESS_QUALITY.md` (`CQA-N-01`, `CQA-N-02`,
  `CQA-N-AMEND-2026-11-05-1`).
- Issue register: `15_ISSUE_REGISTER.csv`, 148 rows *[corrected 2026-11-05: **154**]*; this report
  contributes `CQA-P-01`–`CQA-P-04` and two amendments.
- Blockers: `paper/publication/final_validation/REMAINING_PUBLICATION_BLOCKERS.csv` (21 rows,
  B1–B21); ranked in report 18.
