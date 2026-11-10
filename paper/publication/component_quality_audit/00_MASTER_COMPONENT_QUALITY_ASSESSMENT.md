# Component 00 — Master Component Quality Assessment

**Audited object:** the whole Microbiome-CDM resource as frozen on 2026-11-05 — **490 files / 8.97 GB**
across `releases/cdm_v3/3.0.3` (37 files / 3.16 GB), `releases/data_catalogue_v3/3.1.1` (46 / 206 MB),
`releases/terminology/1.0.1` (24 / 4.34 GB), `pipelines/corpus_v2/releases/2.2.0` (43 / 521 MB),
`releases/zenodo_frozen` (300 / 603 MB), `paper/publication/manuscript_draft` (10 / 68 KB) and
`paper/publication/final_validation` (30 / 136 MB).
**Evidence base:** the fifteen component reports (`01`–`14`, `17`), `15_ISSUE_REGISTER.csv` (**154 rows**),
`16_QUALITY_METRICS.csv` (**131 dimension rows**, components A–N only), `18_ACTION_PLAN.csv` (**154 ranked
rows**), the 38 files in `diagnostics/results/`, and `NER_RETROSPECTIVE_SEAL.sha256` (126 entries).
**Independence:** every number quoted below is taken from the register, the metrics CSV, the action plan or
a named component report. This file **adds no measurement**. It aggregates, and where two reports disagree
it says so in §7 rather than picking a winner silently.

**Scope boundary.** This is an audit, not a repair. Nothing in it changes a frozen release, a catalogue,
terminology, mapping, triple or CDM record; no extraction was re-run; no corpus was regenerated. Nine
`A_APPLIED` rows in `18_ACTION_PLAN.csv` are corrections this audit made **to its own reports**, each with
a dated amendment record and the superseded text retained in place.

---

## 1. What was audited, and how to read a rating

Fifteen components, each rated on the brief's nine dimensions — structural integrity, provenance, internal
consistency, evidence support, external concordance, semantic quality, coverage, reproducibility,
reusability — against five levels: **STRONG / ADEQUATE / WEAK / CRITICAL WEAKNESS / NOT EVALUATED**.

| | Component | | Component |
|---|---|---|---|
| A | Literature corpus | H | CDM schema and database |
| B | Entity mention extraction | I | NER benchmark |
| C | Canonical terminology | J | Post-freeze cleaned layer |
| D | Vocabulary mapping | K | BugSigDB comparison |
| E | Definition quality | L | Triple reference validation |
| F | Data catalogue | M | Interoperability and portability |
| G | Triple and knowledge graph | N | Rights readiness and redaction integrity |
| | | P | Manuscript claim impact |

Four rules govern every rating in this audit, and they are stated here because a master report is where a
reader is most likely to violate them:

1. **No averaged score exists and none is computed here.** There is no "overall quality = 3.2/5". A
   component can be STRONG on integrity and CRITICAL WEAKNESS on provenance simultaneously (D, F, G, H, M
   all are), and collapsing those into one number destroys the only information the audit produces.
2. **Four evidence tiers stay separate.** (i) public gold-standard benchmark results; (ii) external-reference
   grounding against a curated resource; (iii) KG-support enrichment; (iv) model-generated validity
   (LLM-as-judge, cleaning rubrics). A Tier-1 number is never evidence about the corpus; a Tier-4 verdict is
   never "validation". **Public-benchmark F1 is never corpus accuracy** — there is no gold standard for this
   corpus, and no F1, precision, recall or completeness figure for it exists anywhere in this audit.
3. **Agreement is not accuracy.** Cross-model, cross-run and cross-method agreement is reported as
   agreement. Human adjudication is `0 / 2,989` in Component K and `0 / 453` in Component N; where no human
   decided, the audit says "unadjudicated", not "consistent".
4. **Absence from a curated reference is not incorrectness.** A triple, catalogue value or term missing from
   BugSigDB, CTD, MeSH or OMOP is not thereby wrong. Components K, L and G state this explicitly and the
   register's `RESIDUAL_CONTENT` and `COVERAGE_OR_SCOPE` classes inherit the constraint.

Three further things this audit does not do: it makes **no legal determination** of any kind (Component N
records a decision that has not been taken, not what that decision should be); it does not simulate expert
or legal review; and it does not treat its own earlier PASS-style reports as evidence.

---

## 2. Headline findings

1. **The project's arithmetic is far stronger than its semantics.** Of 1,186 recomputable Component-I values,
   all 1,186 reproduce exactly (`NER_RECOMPUTATION_CHECK.csv`: 1,186 MATCH, 152 NEW, 69 N/A of 1,407 checks).
   Of 133 registered manuscript claims, 132 recompute and 1 is a statement of intent; **0 mismatch**. Against
   that, 48 of 154 register rows are `CONFIRMED_DEFECT` and 19 are `REPRODUCIBILITY`.
2. **The single most consequential defect is not a number, it is a divergence between two artefacts described
   as the same data.** `CQA-F-01`: **18,502** cells the catalogue redacted for licence reasons ship in full
   inside the CDM, with no flag saying so; `CQA-N-02`: the redaction flag exists only in the six catalogue
   CSVs — neither database can mark a redacted cell. This is simultaneously a data-integrity defect, a rights
   defect, and a silent inconsistency. It is the only finding in the audit that is all three.
3. **The release is disciplined about a decision nobody has made.** Rights machinery: 453/453 papers agree
   across three layers, 2,072,254 logged cells reconcile to 2,072,254 observed with zero mismatched, zero
   leaks in the shipped bundle. Adjudication: **0 of 453** papers have a named reviewer or a final decision;
   **179 papers (39.5%, 10.0 M characters)** ship withheld pending a review with four distinct legal
   questions routed as one `PENDING` state (`CQA-N-01`).
4. **The best-executed component is the most dangerous to quote.** Component I has intervals on every
   headline number and a p-value on every pairwise claim, and its benchmark reaches only part of the CDM's
   own type list *[corrected 2026-11-05: the earlier sentence here read "2/14 on BC5CDR, 6/14 on BioRED, with
   **0 benchmarks for the five microbiome-specific types**". Those are counts of **benchmark types present**,
   not of CDM types covered, and `MICROBIOME`/`DIET`/`HABITAT` are **not CDM types** — the "five
   microbiome-specific types" did not exist. The verified split of the 14 CDM types is **2 direct**
   (CHEMICAL, DISEASE — 22.78% of the 72,610 typed terms), **3 approximate** (ORGANISM ← OrganismTaxon,
   PROTEIN ← GeneOrGeneProduct, CELL_TYPE ← CellLine — 35.32%), **9 none** (41.90%). `ENTITY`, which carries
   55.29% of *all* 162,409 terms, is not a CDM type and has no typed benchmark by construction. Source:
   `NER_TYPE_COVERAGE_MATRIX.csv` and `NER_BENCHMARK_CORRECTIONS.md` §1.2–1.4.]* (`CQA-I-01`). **Nine
   of fourteen CDM types — 41.90% of typed terms — have no benchmark at all**, and the three approximate
   correspondences are measured to fail on their instances (90.8% of BioRED `OrganismTaxon` gold mentions are
   host terms and **zero are bacterial taxa**). The transfer of any of those numbers to the corpus is the
   largest single scientific hazard in the project.
5. **The graph is half the size it is advertised to be, and none of it is ontology-grounded.** 25,788 triples,
   of which **68.7% are `OTHER_RELATION`** (`CQA-G-02`) and **0 carry an ontology identifier**
   (`CQA-G-01`). Evidence is complete (100% coverage, 84.5% strict sentence location) and 13.2%-vs-5.8%
   external support on the subset that resolves is a real result — for 3.3% of the graph.
6. **The claim layer is sound and mislabelled.** Tier separation in the draft is already correct in three of
   the four places it appears (`02_results.md:3`, `03_discussion.md:28-29`,
   `01_methods_and_resource.md:148`); two live violations remain (`FIGURE_PLAN.md:11`,
   `02_results.md:108`, where grounding is read as an invention rate), and the traceability apparatus
   double-keys `X01`–`X06`, advertises "80 / 80" claims against 133, and reports `X07`'s two failures without
   naming them (`CQA-P-01`–`P-04`).
7. **The schema is honest and unconstrained.** 866 columns documented (100%), 79/79 change-log rows carry
   revert SQL, 299/299 bundle files verify — and **0 declared types, 0 declared foreign keys, 0 views**
   (`CQA-H-01`, `CQA-M-01`, `CQA-M-04`). A reuser cannot port it and cannot link it. Both can be fixed by
   shipping a DDL file; the frozen bytes need not move.

---

## 3. Summary table — every component

Required by the brief: strongest demonstrated property, weakest property, severity of outstanding issues,
readiness status. Severity counts are read from `15_ISSUE_REGISTER.csv`, not from prose. `C/H/M/L` =
critical / high / moderate / low.

| # | Component | Strongest demonstrated property | Weakest property | Outstanding issues | Readiness status |
|---|---|---|---|---|---|
| A | Literature corpus | **STRONG** — structural integrity: `section.text_hash_sha256` verifies 4,006/4,006 = 100.0%; 0 uncovered chars; 453 distinct BioProjects | **WEAK** — internal consistency: 392/453 papers self-declare `REVIEW_REQUIRED`; 1.3% have a closed eligibility decision; 0% an annotation status | 0/1/3/3 = **7** | Usable as a text corpus today; **not quotable as a screened corpus** without a stated inclusion criterion |
| B | Entity extraction | **STRONG** — structural integrity: exact offset reproduction 2,348,758/2,505,628 = 93.74%, exact+corrected 99.998% | **WEAK** — semantic quality: 38% of mentions come from a source that emits exactly one untyped label, contaminating every per-type statistic downstream | 0/1/4/3 = **8** | Usable as a **span** corpus; **not usable as a type corpus** without separating the untyped contributor. No accuracy statement supported |
| C | Canonical terminology | **STRONG** — structural integrity: live + removed = 165,991 exactly; partition verified; tombstone discipline intact | **CRITICAL WEAKNESS** — semantic quality: 8 undeclared types covering 19.62% of terms; 55.3% typed `ENTITY`; typing provenance 96.9% absent | 1/2/4/2 = **9** | **Not ready for type-based reuse.** The audit's clearest schema-level contradiction (`CQA-C-01`) |
| D | Vocabulary mapping | **STRONG** — structural integrity: referential closure 100%, 0 dangling concept ids | **CRITICAL WEAKNESS** — provenance: `matched_via` populated on 21,127/331,394 = 6.37%; the artefact was **restored, not recomputed** (`CQA-D-01`) | 1/4/2/2 = **9** | A **candidate** table wearing a mapping table's name. 1 term in 10 has an exact ontology link; more than half were never looked up |
| E | Definitions | **STRONG** — structural integrity: 6,773/6,773 definitions anchored in their source section = 100.0% | **CRITICAL WEAKNESS** — coverage: definitions exist for **2.09%** of the vocabulary; 8.14% of rows are passages that do not contain their term | 1/1/4/1 = **7** | A **high-quality evidence extract for a small number of terms**, not a glossary. Must be described that way |
| F | Data catalogue | **ADEQUATE** — structural integrity: PK duplication 0.00%, parent-list resolution 100% | **CRITICAL WEAKNESS** — provenance: cell-level provenance silently dropped for 3 of 6 tables; strict literal correspondence 38.22%; the two evidence flags contradict each other on 802 rows | 1/6/8/3 = **18** | The largest and most consequential component. Skeleton and quote layer sound; **cannot survive being read as validated data**. `CQA-F-01` is a decision, not a disclosure |
| G | Triples / KG | **ADEQUATE** — structural integrity: canonical-duplicate rate 0.00%; evidence coverage 100% (34,416 rows, mean 1.05) | **CRITICAL WEAKNESS** — ontology grounding: triples with any ontology identifier 0/25,788 = 0.00%; 68.7% `OTHER_RELATION` | 2/4/5/2 = **13** | Structurally sound, semantically thin. Must be published as **8,071 typed relationships + 17,717 generic co-occurrences**, never as one total |
| H | CDM schema / DB | **STRONG** — documentation: dictionary coverage 100% (866/866), 79/79 change-log rows carry `revert_sql` | **CRITICAL WEAKNESS** — constraint enforcement: declared FKs 0; typed columns 0/866 = 0.00%; 0 views | 1/6/3/0 = **10** | **Honest but unconstrained.** All eight published queries reproduce exactly; `CQA-H-07` scope boundary is the item that must reach Limitations |
| I | NER benchmark | **STRONG** — statistical robustness: every headline number carries an interval; every pairwise claim a p-value; explicit `n/a` where a model cannot emit a type | **CRITICAL WEAKNESS** — coverage of the CDM's own types: **2 direct / 3 approximate / 9 none** across the 14 CDM types; 9 unbenchmarked = 41.90% of typed terms *[corrected 2026-11-05: this cell previously read "2/14 on BC5CDR, 6/14 on BioRED, 0 benchmarks for the five microbiome-specific types" — benchmark-types-present, not CDM types covered, and the five types do not exist; see `NER_TYPE_COVERAGE_MATRIX.csv`]* | 1/4/11/6 = **22** | **Best-executed on method, most dangerous to quote.** The two must be kept in separate subsections with separate verbs |
| J | Cleaned layer | **STRONG** — original recoverability: 100% reversibility; every changed field's original sits beside it | **WEAK** — reproducibility: generator script absent, rubric/prompt absent, model version named only in the output directory | 0/3/3/1 = **7** | The most defensible thing built on top of the freeze — **additive, reversible, checksummed, externally corroborated** (9–13.5 pt kept-vs-dropped separation). Not validated curation |
| K | BugSigDB comparison | **STRONG** — paper matching: 47/453 = 10.4% of corpus, identifier basis 98.5% PMID; 3× chance coverage, 3.2× chance support | **CRITICAL WEAKNESS** — adjudication: 0/2,989 items adjudicated; the protocol's nine adjudication fields are empty | 0/3/3/2 = **8** | **The strongest external evidence in the project**, and not validation of the corpus. 47 papers is an editorial sample, not a random draw |
| L | Triple reference validation | **STRONG** — pre-registration: 2/2 runs pre-registered, code hash 2/2, chance baselines, bootstrap intervals | **CRITICAL WEAKNESS** — cross-run consistency: 50.4% (Nov-3, 518 items) vs 13.18% (Nov-4, 622 edges) are not comparable, and the gap is entirely denominator and reference set | 0/3/4/1 = **8** | Methodologically the cleanest work in the audit; the defect is **presentation**. Null result (CTD 22.4% vs 24.2%) is published as a null — correctly |
| M | Interoperability | **STRONG** — manifest integrity: 299/299 verified, 1 unlisted (benign); seven counts exact; upstream hashes match | **CRITICAL WEAKNESS** — schema portability: 0.00% typed columns, 0 declared FKs, portable-with-a-schema = **no**; 90.7% unnamed concepts | 2/2/3/1 = **8** | **Integrity STRONG, portability CRITICAL.** The cheapest high-effect fix is a DDL file and a column crosswalk — documentation, no frozen bytes touched |
| N | Rights / redaction | **STRONG** — policy consistency: 453/453 papers agree across three layers; 2,072,254 logged = 2,072,254 observed, 0 mismatched; 0 leaks in the shipped bundle | **CRITICAL WEAKNESS** — legal adjudication: 0/179 papers adjudicated; 0/453 rows with a named reviewer; 0 decision-evidence records | 2/2/9/2 = **15** | **Best-engineered, least-decided.** The pipeline is disciplined about a decision it has not made — and must not let the discipline imply the decision |
| P | Manuscript claims | **Support at the registered tier:** 133 rows / 127 ids, 132 MATCH + 1 STATEMENT, **0 MISMATCH**; four-tier vocabulary holds under every check applied | **Traceability apparatus:** `X01`–`X06` double-keyed; "80 / 80" vs 133; `X07` (118/2/1) has no component counterpart and its 2 failures are undiscussed; `02_results.md:29` "no dangling link … was found" is false at DB level | 0/1/3/1 = **5** | **`CONDITIONAL`** — claims supportable at their tier; four additive traceability fixes needed, no re-measurement. *P has no row in `16_QUALITY_METRICS.csv` (131 rows, A–N only); this line is sourced from report 17 §10.* |
| | **Total** | | | **12 / 43 / 69 / 30 = 154** | **146 findings + 8 dated amendment records** |

Read the "outstanding issues" column against the "strongest property" column, not against the weakest alone:
F has 18 rows and E has 7, yet F's skeleton is sound and E's is immaculate — what differs is the **consequence**
of failure, and that is what §9 ranks.

---

## 4. Component-by-component position, in one line each

The table above is the finding. This section exists only to state the *reason* behind each readiness call in
the words the component report used, so that the master report cannot be read as more positive than its
sources.

- **A —** "usable as a text corpus today and not quotable as a screened corpus"; the two must not be conflated.
- **B —** offset integrity is near-perfect and independently re-derived; semantic quality is the weakest thing
  in the component and it propagates into C, D and F.
- **C —** structurally clean, and it fails the two things a CDM exists to provide: a declared type vocabulary
  the data follows, and typed coverage.
- **D —** the referential and count-layer work is genuinely solid and the self-labelling discipline
  (`REVIEW_REQUIRED`, `RESTORED`, `NOT_IN_TERMINOLOGY`) is unusually honest; the substance is thin.
- **E —** "structurally impeccable and substantively thin"; the CDM table cannot be derived from the release file.
- **F —** "everything else is a disclosure problem; that one is a decision problem."
- **G —** the sentence that must not be written is that the relationships are ontology-grounded,
  ontologically validated or human-verified — the columns that would say so are the literal string `unresolved`.
- **H —** a manuscript that respects the scope boundary is safe; one that implies intervention analysis is not,
  and no amount of documentation fixes a column that does not exist.
- **I —** the protocol is honest; the danger is entirely in the transfer.
- **J —** a real result, and it should be reported as one — as a *cleaning* result, not a validation.
- **K —** three times chance against a human-curated reference is real; 47 papers is 10.4% and nothing was
  adjudicated.
- **L —** two runs, two "BugSigDB support" numbers, four-fold apart; published side by side without
  reconciliation they will be read as a contradiction.
- **M —** a reuser can trust that the bytes are the bytes; a reuser cannot link them.
- **N —** the audit can say the pipeline is disciplined about a decision it has not made; it cannot say the
  decision is right.
- **P —** "the most trustworthy part of this project and it is mislabelled in three places."

---

## 5. The rating landscape — why no summary score is offered

`16_QUALITY_METRICS.csv`, 131 dimension rows over A–N, tallied on **`rating_normalised`** (the column the
brief's five-level scale is defined against):

| Rating | Rows |
|---|---|
| STRONG | 20 |
| ADEQUATE | 43 |
| WEAK | 48 |
| CRITICAL WEAKNESS | 16 |
| NOT EVALUATED | 4 |
| **Total** | **131** |

*[corrected 2026-11-05: the column this table tallies was previously unstated, and the table is
reproducible two ways. On **`rating`** the tally is STRONG 20 / ADEQUATE 43 / **WEAK 47** / CRITICAL
WEAKNESS 16 / NOT EVALUATED 4 / **`MODERATE` 1** = 131 — one row (J / "Error introduction",
`16_QUALITY_METRICS.csv:93`) carries an off-scale value that `rating_normalised` maps to `WEAK`. Both
tallies are correct; they answer different questions. All §5 prose below and `19_AUDIT_REPRODUCIBILITY.md` §8.2
quote the **normalised** figure of 48, and the six-value tally of 47 + 1 is the same 131 rows read raw.
Recorded as **CC-14** in §7.1.]*

Three properties of this table are disclosed rather than tidied:

1. **`rating_as_published` contains nine distinct tokens, not five.** Besides the five scale values there are
   `CRITICAL` (10 rows), `MODERATE` (1), `WEAK (uninformative)` (1) and
   `ADEQUATE (rated WEAK before the 2026-11-04 amendment)` (1). These are the components' own wording,
   preserved verbatim; `rating_normalised` maps them onto the brief's scale and `scale_conformant` flags the
   one row that does not map cleanly (J / "Error introduction" / `MODERATE` → `WEAK`). Nothing was silently
   re-labelled.
2. **Seventy-one distinct dimension labels exist, and the canonical nine are fully covered only by A–F.**
   Canonical-dimension coverage: G 7/9, H 2/9, I 1/9, J 1/9, **K 0/9, M 0/9, N 0/9**, L 1/9. Components G–N
   were rated on labels their subject required (ontology grounding, adjudication, schema portability, legal
   adjudication completeness); forcing them into the nine would have produced false comparability. **The
   consequence is that dimension labels are not a cross-component index** — the cross-component index is the
   issue register, and §3 above is computed from it.
3. **P is absent from the metrics CSV by construction**, not by omission: `cqa_metrics.py`'s `REPORTS` lists
   A–N. P's ratings live in `17_PUBLICATION_CLAIM_IMPACT.md` §10 and are cited by reference.

No column in this table is averaged, summed, weighted or plotted. 20 STRONG and 16 CRITICAL WEAKNESS coexist
because they describe different properties of different objects, and the whole point of the audit is that the
project is simultaneously excellent at some things and unsafe to quote about others.

---

## 6. Component I — the amendment record and the retrospective seal

Component I (NER benchmark) is the only component with a sealed provenance chain, and the seal's status must be
stated precisely because it is easy to over-claim.

### 6.1 What the seal is

`NER_RETROSPECTIVE_SEAL.sha256` — **126 entries / 16,734 B**, sealing **3,574,150,615 B** of inputs:

| Field | Value |
|---|---|
| `seal_kind` | **"retrospective provenance seal — NOT a preregistration"** |
| `seal_date` | `2026-11-04T16:48:22+0100` |
| `base_directory` | `/home/jkalra_hpc/Microbiome-CDM` (repo-root-relative paths) |
| `files_sealed` | 126 |

Composition: `outputs/results/benchmark` 91, `data/reference_kg/raw` 10, `data/benchmarks_ner/raw` 9,
`paper/publication/component_quality_audit` 8 (all NER artefacts — `NER_RECOVERED_PROMPTS.md`,
`NER_RECOMPUTATION_CHECK.csv`, `NER_TYPE_COVERAGE_MATRIX.csv`, `NER_MODEL_DEPLOYABILITY.csv`,
`diagnostics/results/ner_*`), `src/scripts/ner_fair_bench` 5, `outputs/results/omop_vocab` 2,
`pipelines/corpus_v2/data` 1.

**It is not a preregistration.** The inputs it hashes were produced before it existed; it pins the state at
the time of sealing so that later edits are detectable, and it can prove nothing about what happened earlier.
A preregistration contradicts; a retrospective seal only detects. **No component report is sealed**, and the
three narratives that *describe* the seal (`NER_BENCHMARK_CORRECTIONS.md`, `NER_REPRODUCIBILITY_GAPS.md`,
`09_NER_BENCHMARK_QUALITY.md`) are deliberately excluded, because hashing a document that quotes the
manifest's byte count is self-referential.

### 6.2 Seal verification

`sha256sum -c NER_RETROSPECTIVE_SEAL.sha256`, run **from the repo root** in this session: **rc = 0, zero
non-OK lines, 126/126 OK.** Hash checks of this file are CWD-sensitive — run from the audit directory the same
command reports spurious `FAILED open or read` lines. That is a usability trap, not a seal failure, and it is
recorded in report 19.

### 6.3 The eight amendment records

Report 00 must carry the amendment chain, because additive correction is the audit's own discipline and the
only defence against silently rewriting a published number. All eight are register rows; the superseded text
stays in place with an `*[corrected …]*` / `*[superseded …]*` marker.

| Amendment | Sev. | Rank | What it corrects | Values moved |
|---|---|---|---|---|
| `CQA-A-AMEND-2026-11-05-1` | LOW | 152 | SQLite `LENGTH()` vs Python `len()` give two corpus character totals and two zero-section counts — 26,874,831 / 453 vs 26,781,631 / 454 | 1 clause + 1 record; no other report superseded |
| `CQA-B-AMEND-2026-11-05-1` | LOW | 153 | Report 02's linkage percentage counted only the `LINKED` token and omitted `LINKED_BY_TYPE` — **86.55% → 87.75%** | 2 figure sentences; no rating changed. Aligns report 02 with the manuscript's own 87.8% |
| `CQA-F-AMEND-2026-11-05-1` | MOD | 119 | Unreproducible catalogue record count **15,582 → 18,502** | 1 sentence; population was always 18,502 |
| `CQA-F-AMEND-2026-11-05-2` | MOD | 120 | Evidence-judge scope: four figures re-scoped (81.15% / κ 0.2321 / 242,158 / 284,325), one unit corrected (2,023 **pairs**, not records) | 5 sentences; no rating changed. **284,325 reproduces exactly; 242,158 / 0.8115 / 0.2321 are missing-provenance, not fabricated** |
| `CQA-I-AMEND-2026-11-04-1` | MOD | 122 | Three Component-I reporting defects: column mislabel (full-schema vs OrganismTaxon-only micro recall), wrong F1 cell (0.3971 → 0.4238), 35-vs-36 typo | 3 cells; no metric value changed. Sealed after application |
| `CQA-I-AMEND-2026-11-05-1` | MOD | 123 | **Withdraws the corpus-grounding circularity claim** — the premise was false; grounding is a Tier-2 external-reference measure, not a check against the project's own vocabulary | 2 sentences + 1 issue block; 117 grounding cells re-described. Rating ADEQUATE unchanged |
| `CQA-N-AMEND-2026-11-05-1` | MOD | 124 | Four Component-N figures: `gap_changes` 930/224/84 → **946/225/85**; withheld characters 9,188,416 → **9,974,210**; one scope made explicit | 4 figures; no rating changed |
| `CQA-P-AMEND-2026-11-05-1` | LOW | 154 | **Recorded, not applied.** Report 09 does not carry the `H04`/`H05` bench-to-corpus correlation set; report 17 §6.2 states it authoritatively in the meantime | 1 missing subsection; nothing superseded |

The withdrawal in `CQA-I-AMEND-2026-11-05-1` is the most important row in this table: an audit that publishes
its own retraction has demonstrated the property a reader should most want. The one *unapplied* amendment
(`CQA-P-AMEND-2026-11-05-1`) is deferred rather than forgotten — report 09 is sealed, and adding §2.4 to it
forces a reseal, which is not a decision this audit takes unilaterally.

### 6.4 Seal-adjacent findings that are not register rows

Report 19 §10 records eight properties of the audit's own machinery. They are disclosed here because two of
them will mislead a re-deriver:

- `ner_environment.json`'s `coverage` block sums to **137**, while `files_sealed` is **126**. Both are correct
  for what they measure (coverage counts by artefact family; the seal counts deduplicated paths). **The two
  numbers must never be equated.**
- `cqa_ner_seal.py` lists `NER_RECOVERED_PROMPTS.md` twice (`TARGETS` lines 39 and 47). Harmless after
  deduplication, a maintenance trap on the next edit.

---

## 7. Cross-report consistency verification

The brief requires a consistency pass before the audit is declared complete: contradictory numbers,
inconsistent severities, missing citations, unsupported claims, unresolved issues. It was performed across all
15 component reports, the register, the metrics CSV, the action plan and this file.

### 7.1 Corrections applied (additive, dated)

**CC-01 — register row count.** `17_PUBLICATION_CLAIM_IMPACT.md` (lines 10 and 13, and its cross-reference
list) stated `15_ISSUE_REGISTER.csv` held **148 rows**. The register closed at **154** (146 findings + 8 dated
amendment records). `148` was the count at the moment report 17 began and was not revised when the Component-I,
Component-N and amendment rows were appended. Superseded text retained with `*[corrected 2026-11-05: **154**]*`.
**No finding or percentage in report 17 depends on it.**

**CC-02 — missing filename.** `06_CATALOGUE_QUALITY.md` line 4 cited `d19_cdm_shape.json`, which does not
exist; the correct evidence file is `d19_cdm_schema_quality.json`. Superseded text retained with a dated
`*[corrected …]*` marker.

**CC-03 — superseded Component-I coverage statement propagated into the headline.** This file's §2 item 4 and
the §3 table row for component I both carried the pre-correction wording "2/14 on BC5CDR, 6/14 on BioRED, 0
benchmarks for the five microbiome-specific types". `09_NER_BENCHMARK_QUALITY.md:42` and
`NER_BENCHMARK_CORRECTIONS.md` §1.2–1.4 had already superseded it: **2/14 and 6/14 are counts of benchmark
types present, not of CDM types covered**, and `MICROBIOME` / `DIET` / `HABITAT` are **not CDM types**, so
"the five microbiome-specific types" had no referent. The verification against `NER_TYPE_COVERAGE_MATRIX.csv`
(15 rows: 14 CDM types plus the off-schema `ENTITY`) gives **DIRECT 2** (CHEMICAL, DISEASE — 22.78% of the
72,610 typed terms), **APPROXIMATE 3** (ORGANISM, PROTEIN, CELL_TYPE — 35.32%), **NONE 9** (41.90%), with
`ENTITY` (89,799 terms, 55.29% of all 162,409) outside the typed denominator. The superseded sentence was also
internally inconsistent — it said `6/14` and then "**Nine** of fourteen". Corrected in both places with the
verified split retained and the original wording quoted in the marker. **The finding `CQA-I-01` and its
CRITICAL severity do not change**; only the quantity in the audit's own sentence.

**CC-04 — inverted "Frozen change?" column in §9.1.** The twelve-CRITICAL table had `yes` on ranks 1 and 4–12
and `no` on ranks 2–3, exactly inverting its source. The authoritative field is `18_ACTION_PLAN.csv` →
`doable_without_touching_frozen_records`, where `yes` means *no frozen byte moves*; `no` occurs on exactly the
**13 `BLD` rows** and on no others. Verified row by row for ranks 1–12: ranks 1 and 4–12 = `yes`, ranks 2
(`CQA-F-01`) and 3 (`CQA-N-02`) = `no`. Corrected values now agree with the paragraph that follows the table
("Only two of the twelve need a rebuild") and with §9.2's `doable w/o frozen change 141 (no: the 13 BLD rows)`.
No rank, class, severity or finding identity changed.

**CC-05 — unsourced "37" in the band-2 summary.** §9.3 item 4 said the 43 HIGH rows were "37 of which touch
neither release nor submission prose". No derivation for `37` exists in the plan. The measured values are:
`touches_publication=no` **1**, `touches_release=no` **29**, and `touches_publication=no` **and**
`touches_release=no` **0**. The decision-relevant count is `doable_without_touching_frozen_records=yes` =
**41 / 43** (the exceptions are the two `BLD` rows `CQA-F-02` and `CQA-I-09`). Replaced with that figure and the
superseded text retained in the marker.

**CC-06 — Lane 2 set inverted, and its closing arithmetic double-counted.** `18_RECOMMENDED_ACTIONS.md` §6's Lane-2 closing paragraph
named `CQA-N-08` in the "disclosure suffices" set (it has no note in `cqa_actions.json` at all) and placed
`CQA-I-09` in the "needs a build for a substantive reason" set, contradicting the sentence immediately below
it. Verified note set: `H-05` "documenting the population difference is sufficient today"; `I-09`, `I-11`,
`I-13`, `I-15`, `I-16` "disclosure suffices"; `N-04` "partial only" → **7**. `F-01` is the only row whose note
explicitly denies a documentation fallback. The five `BLD` rows with no note are exactly `N-02`, `F-02`, `H-10`,
`N-07`, `N-08`; the first three are promoted to build-required on the merits of what they would change, the
last two are not. The 13 therefore partition 4 / 7 / 2 (build-required / disclosure-suffices /
unclassified-preferred). The passage's earlier closing sentence also double-counted — it named `N-07`, `N-08`
*and* "the three un-noted `BLD` rows besides", i.e. it counted `N-02`/`F-02`/`H-10` twice. Corrected in report
18 §6 and restated in this file's §9.3.

**CC-07 — "18 rows touch neither" conflated two fields.** `18_RECOMMENDED_ACTIONS.md` §2 said "18 rows touch
neither" release nor publication. `18` is the `touches_publication=no` total, not the neither total. The
inclusion–exclusion join is 58 release + 136 publication − 53 both = 141 rows touching at least one, leaving
**13** touching neither (`CQA-A-05`, `B-04`, `B-05`, `C-07`, `C-08`, `C-09`, `D-09`, `E-06`, `E-07`, `L-07`,
`M-06`, `N-12`, `N-13`). `touches_release=no` is 96. The five release-only rows the passage names are correct
and unchanged.

**CC-08 — Lane-1 effort table presented as a partition.** `18_RECOMMENDED_ACTIONS.md` §6 introduces the effort
table with "Split by effort", implying the four buckets partition the lane's 127 rows. They total ~105, leaving
22 unassigned. The lane's **membership** figure (83 `DOC` + 44 `ART` = 127) is exact and computed from
`action_class`; only the framing of the breakdown was wrong. Marked as illustrative, not an allocation.

**CC-09 — dangling finding id.** `18_RECOMMENDED_ACTIONS.md` §7's B-list comparison cited `CQA-B-13` for gate
B20. **No such row exists**: component B holds exactly 8 register rows (`B-01`–`B-07` + the dated amendment
`CQA-B-AMEND-2026-11-05-1`), and nothing above `B-07` was ever allocated. The citation is removed rather than
re-pointed — the audit cannot recover which row was meant, and inventing a target would fabricate a
correspondence. B20's real cross-references are the three already carried by B13 (`CQA-I-02`, `CQA-K-02`,
`CQA-J-01`), which name the same "no human accuracy evaluation" hazard.

**CC-10 — "12 critical disclosures" misdescribed the CRITICAL band's composition.** §9.2 said the project "is
12 critical disclosures away". Measured from `18_ACTION_PLAN.csv`, the twelve CRITICAL rows are **7 `DOC`**
(`CQA-C-01`, `D-01`, `E-01`, `G-01`, `G-02`, `I-01`, `M-04`), **2 `ART`** (`CQA-H-01`, `CQA-M-01`), **2 `BLD`**
(`CQA-F-01`, `CQA-N-02`) and **1 `HUM`** (`CQA-N-01`). Only the first group is disclosure. The sentence's
lawyer count (1) and rebuild count (2) were already correct; the noun "disclosures" was not. Replaced with the
full 7 / 2 / 2 / 1 split. **Severity, ranks and plan identities unchanged.**

**CC-11 — "none requires a frozen value to change" contradicted the plan.** §10.6 said all twelve CRITICAL
rows are doable in-house with no frozen value moving. `18_ACTION_PLAN.csv` records
`doable_without_touching_frozen_records=no` on exactly two of them — `CQA-F-01` and `CQA-N-02` — and on the
other eleven `BLD` rows besides. Corrected to ten-of-twelve with the two exceptions named. This is the same
field CC-04 corrected in the §9.1 table and CC-06 corrected in Lane 2; the §10.6 sentence had escaped both.

**CC-12 — "every one of those twelve is closable by disclosure" repeated the CC-11 error.** §8's "Why not
'Not ready'" paragraph made the same claim about the same twelve rows in the readiness decision itself.
Rewritten to separate the ten closable without a rebuild from the two that need one. **The decision string is
unchanged** — it was already "Ready with limitations.", and it is reached on the same grounds; only the
supporting sentence was over-broad.

**CC-13 — the audit's own file inventory was under-counted and over-projected.** Four separate statements
disagreed with a fresh `os.walk` census. (a) `19_AUDIT_REPRODUCIBILITY.md` §1 projected the delivered
directory at **109 files / 2,241,390 B**; the real figure is **110 files** (root 29, `diagnostics/` 33,
`diagnostics/results/` 38, `logs/` 6, `__pycache__/` 4 / 21,522 B) because the projection predated this file
and ignored the growth of the root `.md` files during the correction pass. (b) This file's closing paragraph
called itself "the twenty-first" of "the other twenty" markdowns; there are **22** root `.md` files — 15
component reports (`01`–`14`, `17`) plus 7 supporting documents (`00`, `18`, `19` and the four NER evidence
documents). The "one file larger" claim was therefore two files short. (c) `19_AUDIT_REPRODUCIBILITY.md` §1's
root-file arithmetic read "exactly the brief's 20 required deliverables plus the seven Component-I supporting
files … and the seal" = 28, omitting **`18_ACTION_PLAN.csv`**, the machine-readable companion every rank in
this plan depends on; the true count is 29. That same paragraph then repeated the "21st markdown" error of (b).
(d) `19_AUDIT_REPRODUCIBILITY.md`'s own snapshot table (108 / 2,198,420) is **correct as stated** and is
deliberately not retro-fitted: it describes the directory before reports 00 and 19 existed. All four
statements are corrected in place with the superseded wording retained. **No finding, severity, rank, rating
or readiness decision depends on any file count** — this is audit-machinery bookkeeping only. The stable
number to quote is **110 delivered files (106 excluding `__pycache__`)**; **byte totals are not stable** and
must not be quoted as if they were — this correction itself pinned `2,308,645 B` on the first attempt and
that figure was stale before it was saved, because every additive edit to a root `.md` moves the total without
adding a file. Report 19 now states the total as **≈2.3 MB** and says why it will not state it more precisely.

**CC-14 — §5's rating table did not say which column it tallies.** The table reports **WEAK 48**, which is
the `rating_normalised` count. Tallied on the raw `rating` column it is **WEAK 47 + `MODERATE` 1** — component
J's "Error introduction" row (`16_QUALITY_METRICS.csv:93`) is the single off-scale value, `scale_conformant =
no`, `rating_normalised = WEAK`. Both reads total 131 and both appear in the audit (`19_AUDIT_REPRODUCIBILITY.md`
§8.2 quotes the six-value form deliberately). The table is now labelled as normalised and the raw form is
stated beside it. **No rating, severity, rank or decision changes** — this is a labelling defect in a summary
table, not a measurement defect, and it is exactly the kind of silent choice the audit exists to forbid.
*[corrected 2026-11-05: recorded as **CC-14**.]*

CC-03 through CC-14 are corrections to **this audit's own prose**, found in the final consistency pass, not
new findings about the project: every underlying finding, severity, row identity and plan rank is unchanged, so
none is a ninth amendment row. They are dated and additive, and the superseded wording is retained in each
marker. An amendment record exists to re-scope a *finding*, and none of these does. They are recorded here
because they are cross-report, and the plan is keyed to the closed 154-row register, which none of them
changes.

### 7.2 Scope distinction, not a defect — the 44-vs-46 table gap

Report 08 records the frozen CDM as **44 tables / 0 views / 8,490,496 rows**; `d19_cdm_schema_quality.json`
says `tables: 44`; `CDM_COLUMN_DICTIONARY.csv` documents 866 columns over 44 tables. A 46-table /
8,491,212-row figure also exists in circulation and was initially treated as a contradiction.

**It is not one.** The two objects differ:

| Object | Tables | Rows | Extra tables |
|---|---|---|---|
| `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (frozen) | **44** | **8,490,496** | — |
| `/tmp/cqa_zn/public.db` (extracted `zenodo_frozen` public bundle DB) | **46** | **8,491,212** | `release_rights` (453 rows), `release_redaction` (263 rows) |

**Row counts on the 44 shared tables are identical (0 differences).** Report 08's figure is correct for its
stated object. The public bundle adds two tables that encode *decisions* — and, as `CQA-N-02` and `CQA-N-11`
record, marks no rows and is documented nowhere. **No correction marker is applied**; this is a scope
distinction, and it is written down here so no future reader re-opens it.

### 7.3 Flags raised and left open

| Flag | Status |
|---|---|
| **Dimension-name divergence** — 71 distinct labels; canonical 9 fully covered only by A–F; K/M/N cover 0/9 | **Disclosed, not normalised.** Forcing labels would fabricate comparability. Consequence: use the register, not the metrics CSV, as the cross-component index (§5.2) |
| **Nine raw rating tokens including off-scale `CRITICAL` / `MODERATE` / `WEAK (uninformative)`** | **Preserved verbatim** with `rating_normalised` + `scale_conformant`; 1 row non-conformant (J). No silent re-label |
| **P absent from `16_QUALITY_METRICS.csv`** | **By construction** (`cqa_metrics.py` `REPORTS` = A–N). P sourced from report 17 §10 (§5.3) |
| **`H02` missing from `MANUSCRIPT_CLAIMS_REGISTER.csv`** (live ids: `H01, H03, H04, H05, H06, H07`) | **Observed only.** No gap in coverage results; renumbering would break every existing citation. Recorded, not patched |
| **154-row register vs the brief's 20-file deliverable list** | **Not a conflict.** The 20 files are deliverables; the register counts findings. 146 findings + 8 amendments = 154, spread over 15 component scope areas |
| **`X07` (118 pass / 2 fail / 1 conditional) has no component-report counterpart**, and its 2 failures are undiscussed | **`CQA-P-04`.** The check was **not re-derived**; recorded as reported |
| **`p_vs_best` in report 09** | **Quoted as reported, not recomputed.** Stated where it appears |
| **"Phantom `ner_metrics.json`"** | **RETRACTED.** Only `fair_ner_metrics.json` exists (159,150 B, sha256 `eb7c843cff7cd386…`). The concern was a search artefact |
| **13-candidate broken-reference sweep** | **All non-findings.** Every candidate resolved to a prefix-matched or prose-summarised file |
| **Three results cited by no report by filename** (`cqa_catalogue_redaction.json`, `ner_llm_run_diagnostics.csv`, `ner_recompute_summary.json`) | **Made explicit in report 19 §8.1**; no report edited. All 38 result files are cited by ≥1 markdown once prefix matches count |

### 7.4 Checks that passed

- **Register ↔ action plan**: identical 154-id sets; 0 mismatches on severity, component, `type_class`,
  blocking status and all three `touches_*` flags when joined **on `issue_id`**. `rank` is contiguous 1–154.
  *(Joining by position produces false mismatches — the plan is rank-ordered.)*
- **Register ↔ per-component tallies**: `component_issues_*` in the metrics CSV reconcile exactly with the
  register, 14/14 components, 0 mismatches.
- **Citations**: every one of the 38 `diagnostics/results/*` files is cited by at least one report (78 filename
  occurrences, 59 distinct report→result pairs).
- **Source reports**: every `16_QUALITY_METRICS.csv` `report_file` and every `15_ISSUE_REGISTER.csv`
  `source_report` exists on disk.
- **Severity tallies quoted from the file**: CRITICAL 12 / HIGH 43 / MODERATE 69 / LOW 30 = 154. Findings
  only: 12/43/64/27 = 146. Amendments: 5 MODERATE + 3 LOW = 8.
- **`type_class` census**: CONFIRMED_DEFECT 48, REPRODUCIBILITY 19, MEASURED_PROPERTY 19, COVERAGE_OR_SCOPE
  16, DOCUMENTATION 13, POTENTIAL_RISK 9, AUDIT_CORRECTION 8, RESIDUAL_CONTENT 7, DESCRIPTION_VS_BEHAVIOUR 6,
  SCHEMA 3, VALIDATION_ABSENT 2, USABILITY_LIMITATION 2, CLAIM_DEPENDENCY 1, GOVERNANCE_GAP 1.
- **`touches_*` census**: scientific 124, publication 136, release 58; publication **and** release 53; the
  five rows touching release but **not** publication (`CQA-A-04`, `CQA-G-09`, `CQA-M-03`, `CQA-N-08`,
  `CQA-N-09`) are flagged in §9 because a reader looking only for "publication blockers" will miss them.
- **Blocking-status reading**: read per row. 78 rows start with a submission/`block` term, 72 start with
  neither, and **4** start `publication` — `CQA-P-01`–`P-04`. Keyword filters over-count; the per-row reading
  is the only valid one.

### 7.5 What the consistency pass could not resolve

- The `CQA-P-AMEND-2026-11-05-1` deferral (report 09's seal) — **deferred by decision**, not oversight (§6.3).
- `X07`'s two failing validator tests remain unnamed at source (`CQA-P-04`); naming them would require
  re-running a validation this audit was not scoped to re-run.
- `p_vs_best` (report 09) remains quoted-not-recomputed.
- The eight frozen-input hashes are pinned by the seal; report 02's own `.csv`-level checks and report 06's
  probe results depend on `outputs/scratch/` scripts that live outside the audit directory (report 19 §5) —
  **disclosed as a reproduction boundary, not repaired**.

---

## 8. The three readiness decisions

Each is decided independently. They diverge, and the divergence is the finding.

### A. Scientific publication readiness

> ## **Ready with limitations.**

Not "Ready", and not "Not ready".

**Why not "Ready".** Twelve CRITICAL rows are open. Seven are claim-language defects that would put a false
statement in the manuscript if left (`CQA-C-01` undeclared type vocabulary at 19.62% of terms; `CQA-D-01`
mapping never re-queried; `CQA-E-01` definitions at 2.09% of vocabulary; `CQA-G-01` zero ontology identifiers;
`CQA-G-02` 68.7% `OTHER_RELATION`; `CQA-I-01` the benchmark-transfer hazard; `CQA-M-04` nothing links to an
external vocabulary). Two are database-shape claims (`CQA-H-01`, `CQA-M-01`) that cannot be made in the
current wording. One is a rights divergence that also has a scientific reading (`CQA-F-01`). The manuscript's
own claim layer is `CONDITIONAL`: four traceability fixes outstanding (`CQA-P-01`–`P-04`), and **two live
sentences violate the project's own prohibition list** (`FIGURE_PLAN.md:11`, `02_results.md:108`).

**Why not "Not ready".** Ten of those twelve are closable by disclosure, one added file, or a one-sentence
correction, and the other two (`CQA-F-01`, `CQA-N-02`) by a rebuild or an added column — **141 of 154 rows
require no frozen value to change**, and none of the twelve is a defect in a number.
*[corrected 2026-11-05: this passage previously said "Every one of those twelve is closable by disclosure, one
added file, or a one-sentence correction". `CQA-F-01` and `CQA-N-02` are the two `BLD` rows and appear in
`18_ACTION_PLAN.csv` with `doable_without_touching_frozen_records=no`. Recorded as **CC-12** in §7.1.]*
The numbers reproduce: 1,186/1,186 Component-I values exact; 132 registered claims recompute with 0 mismatch;
all eight published CDM queries return exactly what the release says they return. Three of the four places the
draft states the evidence tiers are already correct (`02_results.md:3`, `03_discussion.md:28-29`,
`01_methods_and_resource.md:148`) and must be preserved. There is no gold standard to fail against, and the
manuscript does not currently claim one. A referee who executes the plan in §9 gets a defensible paper; a
referee who reads the current draft's two remaining violations does not.

**The limitations that must appear in the manuscript, regardless of anything else.** No accuracy, recall,
precision, completeness or "validated" claim for the corpus. Nine of fourteen CDM types unbenchmarked. The
graph is 8,071 typed relationships plus 17,717 generic co-occurrences, not 25,788 typed relationships.
Definitions cover 2.09% of the vocabulary. One term in ten has an exact ontology link. The layer is an
association record attached to a paper and cannot express dose, diet or effect size (`CQA-H-07`). 179 papers
ship withheld pending an unreviewed rights position.

### B. Public data release readiness

> ## **Ready after legal review.**

Not "Ready", and not "Not ready".

**Why not "Ready".** `CQA-N-01`: **0 of 453** papers have a named reviewer, a final decision, a publisher
record or decision evidence; **179 papers (39.5%, 10.0 M characters)** ship withheld pending a review that has
not happened, with four distinct legal questions — quotation exception, derivative work, NC compatibility,
share-alike — routed as one undifferentiated `PENDING` state. An audit cannot substitute for that review and
this one does not attempt to. Compounding it, **two build-level rights defects are CRITICAL**: the CDM carries
18,502 licence-redacted cells in full (`CQA-F-01`) and neither database can mark a redacted cell
(`CQA-N-02`). Both are `BLD` rows — they cannot be closed by disclosure alone.

**Why not "Not ready".** The shipped public bundle is a real, verified artefact: 299/299 manifest entries
verified, seven counts exact, upstream hashes matched, **zero leaks**, and a redaction policy applied per paper
(274 `TEXT_INCLUDED` / 179 withheld). Its three layers agree on 453/453 papers and its log reconciles to the
cell with zero mismatched. Nothing in the audit found a leak in the bundle — the leak found is in the
**CDM**, which is not the released object. "Not ready" would be false for the artefact that exists.

**What "after legal review" means concretely.** Legal review is **necessary but not sufficient**. Four
mechanical prerequisites accompany it and none is a legal judgement: (i) resolve the 18,502-cell CDM ↔
catalogue asymmetry or ship the CDM with `evidence_redacted` present (`CQA-F-01`, `CQA-N-02`); (ii) correct
the documented 50-character guarantee, which is really 59 and which 403 shipped cells violate (`CQA-N-03`);
(iii) resolve the 7 `TODO` placeholders and the author blanks in the upload metadata (`CQA-N-10`); (iv) correct
the false invariant in `TECHNICAL_VALIDATION.md` (`CQA-N-05`). The audit does **not** say the review will
succeed, does **not** predict its outcome, and does **not** rank the 179 papers by likely outcome. It says
which question each needs answered.

### C. Downstream research reusability

> ## **Ready for restricted use cases.**

Not "Ready", not "Requires substantial improvement".

**Why not "Ready".** A reuser cannot link the resource: **zero** ontology identifiers on 25,788 triples
(`CQA-G-01`), 90.7% unnamed concepts (`CQA-M-04`), 866 untyped columns and zero foreign keys (`CQA-M-01`).
A reuser cannot type-filter reliably: 19.62% of terms carry undeclared types (`CQA-C-01`) and 55.3% are
`ENTITY`. A reuser cannot read the graph as a typed relationship resource: 68.7% is `OTHER_RELATION`
(`CQA-G-02`). A reuser cannot quote a mapping as current: the artefact was restored, not recomputed
(`CQA-D-01`). A user who assumes portability or linked data will be actively misled.

**Why not "Requires substantial improvement".** Distinct, substantial uses work today, and they are not
hypothetical:

| Restricted use case | Basis | Provenance |
|---|---|---|
| Full-text retrieval and section addressing | 4,006/4,006 section hashes verify; 4,006 units; offsets section-body-relative and exact | report 01 |
| Span-level mention lookup | 93.74% exact offset reproduction, 99.998% exact+corrected; 2,505,684 mentions with a stated status on each | report 02 |
| Catalogue as a discovery index | 52,400 records over all 453 papers; PK duplication 0.00%; parent lists resolve 100%; every `gap_evidence` quote verbatim | report 06 |
| Verified-bytes redistribution | 299/299 manifest entries; seven exact counts; upstream hashes match | report 13 |
| Cleaning as a *separate labelled layer* | 100% reversible; kept-vs-dropped separation 9–13.5 points under three independent tests | report 10 |
| Benchmark suite as a method | pre-registration, intervals, p-values, `n/a` where a model cannot emit a type | report 09 |

The restriction is stated as a set of **prohibited inferences**, and it is short: not a validated corpus;
not a typed resource; not a knowledge graph; not a linked dataset; not a portable schema; not a glossary;
not a screening decision. Each prohibition maps to a CRITICAL row, not to a matter of taste.

---

## 9. Final ranked action plan

`18_ACTION_PLAN.csv` holds all 154 rows, rank-ordered by severity band → action class
(`HUM > BLD > ART > DOC > NONE > A_APPLIED`) → component → register order. Full prose in
`18_RECOMMENDED_ACTIONS.md`; this is the operative summary and it **adds no item**.

### 9.1 The twelve CRITICAL rows (ranks 1–12)

| Rank | id | Class | Human? | Frozen change? | What it is |
|---|---|---|---|---|---|
| 1 | `CQA-N-01` | HUM | **yes** | no | 179 papers withheld pending a rights review that has not happened |
| 2 | `CQA-F-01` | BLD | no | **yes** | 18,502 licence-redacted cells ship as full text in the CDM |
| 3 | `CQA-N-02` | BLD | no | **yes** | The redaction flag lives only in CSVs; no database can mark a redacted cell |
| 4 | `CQA-H-01` | ART | no | no | Zero foreign keys, zero declared types, no enforcement |
| 5 | `CQA-M-01` | ART | no | no | The database cannot be ported: 866 untyped columns, 0 FKs |
| 6 | `CQA-C-01` | DOC | no | no | Type vocabulary diverges from the declared CDM vocabulary |
| 7 | `CQA-D-01` | DOC | no | no | The mapping was never re-queried and cannot be regenerated |
| 8 | `CQA-E-01` | DOC | no | no | Definitions cover 2.09% of the vocabulary |
| 9 | `CQA-G-01` | DOC | no | no | No triple carries an ontology identifier |
| 10 | `CQA-G-02` | DOC | no | no | 68.7% of triples fall into a single `OTHER_RELATION` bucket |
| 11 | `CQA-I-01` | DOC | no | no | The public benchmark cannot speak to the corpus — and must not be made to |
| 12 | `CQA-M-04` | DOC | no | no | Nothing links to an external vocabulary |

*[corrected 2026-11-05: in the first issue of this table the "Frozen change?" column was **inverted** against
its source. The authoritative field is `18_ACTION_PLAN.csv` → `doable_without_touching_frozen_records`, where
`yes` means **no** frozen byte moves and `no` occurs on exactly the 13 `BLD` rows. Ranks 1 and 4–12 all carry
`doable=yes`, so they need **no** frozen change; ranks 2–3 are `BLD` and do. The corrected values now agree with
the paragraph below and with §9.2's `doable w/o frozen change 141 (no: the 13 BLD rows)`. No rank, class,
severity or finding identity changed.]*

The twelve collapse to **five substantive issues**: an unreviewed rights position (1); a redaction asymmetry
between catalogue and database (2–3); an unportable schema that can be documented without being rebuilt
(4–5); seven disclosures whose numbers are true but whose implication is not (6–12); and one hazard that is
pure scientific risk — carrying a public-benchmark F1 onto a corpus with no gold standard (11).

**Only two of the twelve need a rebuild.** Ten of the twelve are closable by documentation, two added
artefacts or a legal decision — which is what makes this plan tractable.
*[corrected 2026-11-05: "one added artefact" undercounted the two `ART` rows (`CQA-H-01`, `CQA-M-01`); the
bare "documentation" bucket is the seven `DOC` rows. Recorded with **CC-10** in §7.1.]*

### 9.2 The plan in numbers

```
rows                    154
by class                DOC 83  ART 44  BLD 13  HUM 3  NONE 2  A_APPLIED 9
by severity             CRITICAL 12  HIGH 43  MODERATE 69  LOW 30
human_required = yes     6   (N-01, K-02, K-03, J-01, I-02, N-10)
doable w/o frozen change 141  (no: the 13 BLD rows)
touches publication      136 yes / 18 no
touches release           58 yes / 96 no
release yes, publication no   5   (A-04, G-09, M-03, N-08, N-09)
```

**The project is not 154 fixes away from being publishable. It is 12 CRITICAL rows away, of which
exactly one needs a lawyer, two need a rebuild, and nine are disclosure or one-added-file work.**
*[corrected 2026-11-05: this sentence previously read "It is 12 critical disclosures away". Only **7** of the
twelve are `DOC` disclosures (`CQA-C-01`, `D-01`, `E-01`, `G-01`, `G-02`, `I-01`, `M-04`); two are `ART`
one-added-file items (`CQA-H-01`, `CQA-M-01`), two are `BLD` rebuilds (`CQA-F-01`, `CQA-N-02`) and one is the
`HUM` legal review (`CQA-N-01`). The lawyer/rebuild counts were already right. Recorded as **CC-10** in §7.1.]*

### 9.3 Three lanes, by who can act

- **Lane 1 — doable today, no rebuild, no permission (127 rows: 83 `DOC` + 44 `ART`).** ~55 single-sentence
  disclosures; ~35 one-added-file items (DDL with affinities and declared FKs, CSV↔DB crosswalk, prompt
  bundle and rubric, manifests, column-level verb vocabulary); ~5 query/constant rewrites; ~10 edits to
  shipped *documentation*, which are `ART`/`DOC` rather than `BLD` but which imply re-manifesting the
  checksummed bundle — a decision the project must take, not the audit.
- **Lane 2 — needs a build or rerun (13 `BLD` rows).** The 13 partition: **4 need a real build**
  (`CQA-F-01`, `CQA-N-02`, `CQA-F-02`, `CQA-H-10`); **7 are already disclosed as sufficient**
  (`CQA-H-05`, `CQA-I-09`, `CQA-I-11`, `CQA-I-13`, `CQA-I-15`, `CQA-I-16`, `CQA-N-04` partial); **2 are
  rebuild-preferred but unclassified** (`CQA-N-07`, `CQA-N-08`). For the seven, the value is unrecoverable
  and **disclosure suffices for the blocking claim** — the honest move is to say so rather than to
  reconstruct. `CQA-F-01` is the only row whose own note explicitly denies a documentation fallback; only a
  schema change or a stated export rule resolves the deposit question.
  *[corrected 2026-11-05: this sentence previously listed `CQA-N-08` in the disclosure set and `CQA-I-09` in
  the rebuild set, inverting `cqa_actions.json`; see `18_RECOMMENDED_ACTIONS.md` §6; recorded as **CC-06** in §7.1.]*
- **Lane 3 — needs a person (6 flagged + standing external gates).** `CQA-N-01` (legal), `CQA-K-02` and
  `CQA-K-03` (adjudication of 2,989 items and explanation of body-site concordance at 24.6%), `CQA-J-01`
  (the 50-row human check on the 60.7% well-formedness claim), `CQA-I-02` (organism-recall adjudication),
  `CQA-N-10` (metadata decisions).

### 9.4 Order of execution

1. **Ranks 1–3** (rights, redaction asymmetry) — sequence them together; they answer to one decision.
2. **Ranks 4–5** (DDL + declared affinities + junction table) — one artefact, two register rows, zero frozen
   bytes moved. Largest ratio of claim-safety to effort in the plan.
3. **Ranks 6–12** — the disclosure band. Each is a sentence or a subsection; all seven belong in one editing
   pass, because they share one requirement: *state the denominator, separate the tiers, name the population,
   declare the sentinel*.
   *[corrected 2026-11-05: this item previously said "all twelve", importing the CRITICAL band's size onto the
   seven-row disclosure sub-band. Ranks 6–12 are the seven `DOC` rows; ranks 4–5 are `ART` and ranks 1–3 are
   the rights work. See **CC-10** in §7.1.]*
4. **Band 2 (HIGH, ranks 13–55)** — 43 rows, **41 of which need no frozen record to change** (the two `BLD`
   exceptions are `CQA-F-02` and `CQA-I-09`), so they can be batched in one pass
   *[corrected 2026-11-05: this sentence previously read "37 of which touch neither release nor submission
   prose". That count has no derivation in `18_ACTION_PLAN.csv` — **0** of the 43 HIGH rows have
   `touches_release=no` **and** `touches_publication=no`; 29 are `touches_release=no` and 42 are
   `touches_publication=yes`. The verifiable and decision-relevant figure is the `doable_without_touching_frozen_records=yes`
   count of **41 / 43**. Recorded as **CC-05** in §7.1]*.
5. **Bands 3–4 (MODERATE 56–124, LOW 125–154)** — including the eight amendment records (`A_APPLIED`,
   ranks 119–124 and 152–154), which are already done and appear in the plan for traceability only.

**No further development cycle is opened by this report.** The plan is the deliverable; executing it is the
next cycle's work and is out of scope here.

---

## 10. What this audit actually did — the brief's closing obligations

### 10.1 What was actually inspected

490 frozen files / 8.97 GB across seven trees, read-only; the 453-paper corpus and its 4,006 section units;
the CDM 3.0.3 SQLite database (44 tables, 866 columns, 8,490,496 rows) including every `PRAGMA table_info`,
`PRAGMA index_list`, all eight published research queries, and the extracted public-bundle DB (46 tables);
`data_catalogue_v3/3.1.1` (52,400 records across six tables); `terminology/1.0.1` (165,991 canonical terms,
331,394 mapping rows, 6,773 definitions); corpus 2.2.0 (43 files, 4,006 sections); `zenodo_frozen` (300 files,
manifest 299 entries); the manuscript draft (10 files incl. `FIGURE_PLAN.md` and `PUBLICATION_INDEX.md`);
`final_validation` (30 files: claim register 133 rows, number audit 434 rows, 21 blockers B1–B21); and the
benchmark/BugSigDB/reference bundles named in Components I, J, K and L.

### 10.2 What was independently recomputed

Hashes (4,006/4,006 section SHA-256), offsets (2,348,758 exact of 2,505,628), all 1,186 recomputable
Component-I values, all 132 registered manuscript claims, all eight published CDM queries, every referential
integrity and rollup check in reports 04/06/08/13, the six catalogue anchor/flag recounts, the rights log
reconciliation (2,072,254 / 2,072,254) and the catalogue-side reconciliation (27,226 = 21,838 + 5,388), the
clean-layer reversibility check, and the manifest verification (299/299). **Nothing in §3's STRONG column is
inherited from a prior PASS report.**

### 10.3 What was only inherited

`fulltext_crosscheck_status` (Component A evidence support) — no PDF-to-text oracle exists in this audit;
`X07`'s validator result (118/2/1) and `X08`'s "verification overall: True" (Component P) — read, not
re-derived; `p_vs_best` (Component I) — quoted as reported; the 50-character guarantee's *intent* (Component
N) — the audit measures the behaviour (59) and reports the divergence without deciding which is right; the
landing of the storage-sign loss in PDF extraction (Component F) — traced, but inherited as upstream; and the
`REVIEW_REQUIRED` / `full_text_completeness=partial` flags (Component A) — self-declared upstream, not
independently re-graded. Each is marked as inherited at the point it is used.

### 10.4 What new defects were found

The audit's own new findings, not previously on any project list: the 18,502-cell redaction asymmetry between
catalogue and CDM (`CQA-F-01`) and the absence of a redaction flag in either database (`CQA-N-02`); the
59-vs-50 character guarantee with 403 violating cells (`CQA-N-03`); the 946 values and 85 verbatim excerpts
surviving in withheld papers (`CQA-N-08`); the 6.37% `matched_via` provenance rate (`CQA-D-01`); 19.62% of
terms in undeclared types (`CQA-C-01`); the 68.7% `OTHER_RELATION` share (`CQA-G-02`); zero ontology
identifiers (`CQA-G-01`); the 2.09% definition coverage (`CQA-E-01`); the `X01`–`X06` double-keying and
"80 / 80" mismatch (`CQA-P-01`, `P-02`); the false "no dangling link" statement (`CQA-P-03`); the
undiscussed `X07` failures (`CQA-P-04`); the four-fold divergence between the two BugSigDB runs
(`CQA-L-01`); 6 duplicate paper rows in the CDM; the 802 rows where the two catalogue evidence flags
contradict each other; 36.54% duplicate real dataset rows; and the whole of report 19's reproduction
boundary (8 of 38 results probe-produced out of tree; `cqa_n_rights.py` depending on an unscripted 2.86 GB
extraction; `d07` and `d10` non-byte-reproducible for two different reasons).

### 10.5 Which claims need revision

Seven of the twelve CRITICAL rows are claim revisions, and they are listed at ranks 6–12 in §9.1. The
prohibited-inference set (§8C) is the operative list. Two live draft sentences must change:
`FIGURE_PLAN.md:11` (figure 5) and `02_results.md:108` (grounding read as an invention rate). Three draft
passages are **already correct and must be preserved**: `02_results.md:3`, `03_discussion.md:28-29`,
`01_methods_and_resource.md:148`. The manuscript's Abstract and §3.2/Table 8 describe a 452-paper corpus
whose entity and relationship totals come from the **444-paper extraction build** — that scope statement is
accurate and must not be "corrected" to match 453 or the HMCV2 2.1.0 totals.

### 10.6 What blocks publication

Twelve CRITICAL rows, of which the seven claim-language items are the direct blockers — and of those seven,
`CQA-I-01` is the one that could survive review unnoticed and matter most. Plus the four claim-layer
traceability fixes
(`CQA-P-01`–`P-04`) and the two live prohibition violations. Ten of the twelve are doable in-house with no
frozen value moving; `CQA-F-01` and `CQA-N-02` are the two `BLD` exceptions and need a rebuild or an added
column. *[corrected 2026-11-05: this paragraph previously ended "All are doable in-house; none requires a
frozen value to change", which contradicts `18_ACTION_PLAN.csv` for those two rows. Recorded as **CC-11** in
§7.1.]*

### 10.7 What blocks public release

`CQA-N-01` (the legal review — a person, not a computation), `CQA-F-01` and `CQA-N-02` (the two `BLD` rights
rows, which need a rebuild or an added column), and `CQA-N-10` (7 `TODO` metadata fields). Secondary but
required before deposit: `CQA-N-03`, `CQA-N-05`. Note that five register rows touch the release but **not**
publication (`CQA-A-04`, `CQA-G-09`, `CQA-M-03`, `CQA-N-08`, `CQA-N-09`) — a reader filtering for
publication blockers will miss them.

### 10.8 What can be deferred to a future version

Everything in Lane 2 that is not one of the five substantive rebuilds; the 866-column type/FK declaration if
a DDL file is rejected as out of scope (it should not be — it costs nothing and moves no frozen byte); the
`CQA-P-AMEND-2026-11-05-1` reseal; the taxonomy full-table pass; the composite index on the 2.5 M-row mention
table; PubTator3 version capture; and the entire `MODERATE`/`LOW` tail of the register (99 of 154 rows) **on
the condition that each deferral is disclosed**. Deferral with disclosure is a legitimate engineering choice;
deferral without it is the defect this audit is most concerned about.

### 10.9 One sentence

The resource is **technically verifiable, semantically unvalidated, and honestly labelled in most places and
not in the few that matter** — and the audit's own recomputation found more wrong with its own reports than
with the data they measure.

---

## 11. Cross-references

- `01`–`14`, `17` — the fifteen component reports; every rating in §3 originates in one of these tables.
- `15_ISSUE_REGISTER.csv` — **154 rows, 18 columns**; the sole source for severity, `type_class`,
  `touches_*` and blocking status. Totals 12/43/69/30.
- `16_QUALITY_METRICS.csv` — **131 rows, 21 columns**, A–N only; the sole source for dimension ratings.
- `18_ACTION_PLAN.csv` — the same 154 rows with `rank`, `band`, `action_class`, `human_required`,
  `doable_without_touching_frozen_records`. Join **on `issue_id`**, never by position.
- `18_RECOMMENDED_ACTIONS.md` — prose plan, three lanes, B1–B21 mapping, amendment table.
- `19_AUDIT_REPRODUCIBILITY.md` — the reproduction ladder, the writer census, the seal, and the eight
  audit-machinery findings of §6.4.
- `NER_RETROSPECTIVE_SEAL.sha256` + `NER_BENCHMARK_CORRECTIONS.md` + `NER_REPRODUCIBILITY_GAPS.md` +
  `NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md` + `NER_RECOVERED_PROMPTS.md` +
  `NER_RECOMPUTATION_CHECK.csv` + `NER_TYPE_COVERAGE_MATRIX.csv` + `NER_MODEL_DEPLOYABILITY.csv` — the
  Component-I evidence chain.
- `diagnostics/` (33 files: 32 `.py` + 1 `.sbatch`) and `diagnostics/results/` (38 results) — every number
  quoted in this report is regenerable from these, per the four-tier ladder in report 19 §2. Eight of the 38
  are probe-produced from `outputs/scratch/`, which is outside this directory.

**This file is the final markdown in the audit directory** — the twenty-second of twenty-two root `.md`
files. It was written last, after report 19, and is the one file the other twenty-one cannot depend on —
nothing here is an input to any script, and `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md` appears in no
`cqa_metrics.py` `REPORTS` list. The directory as delivered is **two files larger** than the snapshot in
report 19 §1 (108 + this file + report 19 = 110), and report 19 §1 now says so explicitly.
*[corrected 2026-11-05: this paragraph previously read "the twenty-first and final markdown … one file
larger than report 19 §1 records". Twenty-two root `.md` files exist, not twenty-one: the count missed one
of the four NER evidence documents. The `108 + 2 = 110` arithmetic and the 110-file delivered total are
unchanged. Recorded as **CC-13** in §7.1.]*
