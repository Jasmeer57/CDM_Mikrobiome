# Component J — Post-freeze Cleaned Layer

**Audited object:** `outputs/results/cleaned_layer_deepseek/` — a DeepSeek-V4-Flash curation of the
frozen terminology and triple layers: `cleaned_triples.csv.gz` (25,788 rows → **9,682 kept /
16,106 dropped**), `cleaned_terms.csv.gz` (162,409 rows → **30,727 kept / 131,682 dropped**),
`relabel.jsonl`, `CLEANING_REPORT.md`, `MANIFEST.sha256`, and the derived KG in
`outputs/results/kg_2026-11-04/kg_cleaned.graphml`.
**Evidence base:** the two cleaned CSVs (read in full, 25,788 and 162,409 rows), `relabel.jsonl`,
`CLEANING_REPORT.md`, `MANIFEST.sha256` (4/4 verified), the judge run it derives from
(`outputs/results/benchmark/llm_judge_deepseek_v4_flash/`), and the graph statistics recomputed in
`cqa_triple_graph.json`.
**Independence:** every keep/drop/relabel/swap count below was recomputed from the shipped CSVs, not
read from the report. The graph comparison (orphaned nodes, components, generic share) was
recomputed from the shipped edge list.

> **Separation rule (brief §J).** This is a **post-freeze, model-curated derivative**. Nothing in it
> is part of the frozen release. Every row preserves `relation_original` / `type_original` beside
> the cleaned value, and the frozen CDM is untouched, so the layer is **additive and reversible** —
> that is its most important property and this report treats it as such throughout.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Original recoverability | **STRONG** | Frozen CDM unmodified (all audits open `mode=ro`); every cleaned row carries `relation_original`, `type_original`, `kept`, `drop_reason`; `MANIFEST.sha256` verifies **4/4** files; `relabel.jsonl` records each relabel | reversibility **100%** — the input can be reconstructed row-for-row, and every changed field has its original beside it | Recoverability is structural, not semantic: you can get the old value back, but you cannot recover the *reason* for each of 6,203 relabels beyond `sentence` / `triple_only` | High |
| Reproducibility | **WEAK** | Artefacts are checksummed and the judge run is named (`llm_judge_deepseek_v4_flash`), but **no builder script ships in the repository** — `src/scripts/kg/` contains only `build_kg.py`, `evidence_check.py`, `gold_kg_check.py`, all of which *consume* the cleaned layer; a repository-wide search finds no generator | generator script **absent**; rubric/prompt **absent**; model version named only in the output directory | The transformation cannot be re-run from the release. The judge's rubric is not shipped either, so the keep/drop rule is documented only by `CLEANING_REPORT.md` prose | High |
| Triple well-formedness | **ADEQUATE** | Dropped 16,106: `not_well_formed` **15,661 (60.7% of all triples)** + `invalid_entities` 445. Kept 9,682. The 15,661 include strings like `100lofathp1cellsuspension106cellsml` — concatenated PDF artefacts (see `removed_relation` samples in component G) | not-well-formed share **60.7%**; invalid-entity share 1.73%; survivor share **37.5%** | "Not well formed" is a model judgment against an unshipped rubric. That 60.7% of the frozen graph is judged ill-formed is a **finding about the frozen graph**, and it is the single largest claim in the layer | High |
| Predicate specificity | **ADEQUATE** | Among the 9,682 kept, `OTHER_RELATION` falls from **6,574 (67.9%)** to **437 (4.5%)**; **6,146** of the 6,203 relabels start from `OTHER_RELATION`; **0 new relation labels** are introduced — every target already exists in the frozen 76-relation vocabulary | generic share **67.9% → 4.5%** within the kept set; invented vocabulary **0** | The improvement is real *inside the kept set*, but the kept set is 37.5% of the graph, so the end-to-end generic share across the whole frozen population only falls from 68.7% to 1.7% of the original. Quoting 4.5% without the denominator misleads | High |
| Relabelling correctness | **WEAK** | Of 6,203 relabels, evidence is `sentence` for **3,796 (61.2%)** and `triple_only` for **2,407 (38.8%)** — i.e. **two in five relabels have no sentence-level support recorded**. Among generic→typed relabels specifically: `sentence` 3,895 / `triple_only` 2,638 / none 41. `direction_swapped=1` on **408** (299 sentence, 109 triple_only) | relabels without sentence evidence **38.8%**; swaps **408 (1.6% of all rows, 4.2% of kept)** | A `triple_only` relabel is the model reading `subject — OTHER_RELATION — object` and choosing a predicate from the pair alone. That is exactly the regime where a plausible-sounding but unsupported predicate is produced. No human checked any of them | High |
| Entity / term validity | **WEAK** | 131,682 of 162,409 terms (**81.1%**) dropped; 30,727 kept; **11,614 retyped**; `ENTITY` falls **7,735 → 744** among kept. The drop rule is internally consistent: **0** dropped terms have `valid_mention_share ≥ 0.5` | drop rate **81.1%**; retype rate **37.8%** of kept; `ENTITY` collapse **−90.4%** | An 81% term drop is an enormous claim and it is model-generated. `valid_mention_share` is computed from the same judge, so the consistency check above is circular by construction, not independent confirmation | High |
| Type correctness | **ADEQUATE** | The cleaned vocabulary is drawn entirely from `CDM_TYPES` — ORGANISM 5,485 / CHEMICAL 4,735 / DATA_ANALYSIS 4,170 / DISEASE 3,279 / LAB_METHOD 2,338 / PROTEIN 2,155 / CLINICAL 1,788 / DNA_RNA 1,662 — and removes the off-vocabulary `ENTITY` label from 6,991 of 7,735 kept terms | off-vocabulary `ENTITY` among kept **7,735 → 744 (−90.4%)**; all target labels are in the 14-type CDM vocabulary | Moving to `CDM_TYPES` fixes a vocabulary defect (component C) but says nothing about whether each individual re-type is right; 11,614 were changed with no gold standard | High |
| Graph-level effect | **ADEQUATE** | Kept graph: 8,897 nodes / 9,682 edges / 1,219 components / largest 6,029 (**67.8%**) / 2 isolated / mean degree 2.11. Full graph: 22,579 nodes / 3,052 components / largest 15,470 (68.5%) / 73 isolated. **13,682 nodes (60.6%) are orphaned** by the cleaning | node attrition **60.6%**; component count −60.1%; largest-component share essentially unchanged (68.5% → 67.8%) | Cleaning removes volume without changing the graph's topology: it is still one dominant blob. That is evidence the layer is *pruning*, not *restructuring* | High |
| Error introduction | **MODERATE** | New relation labels: **0**. New term types: **0** (all in `CDM_TYPES`). But 2,407 relabels and 109 swaps have no sentence evidence; 11,614 re-types and 1,614 `sentence`-evidenced relabels are unverified; `drop_reason` is a single model's label with no second opinion | unverifiable transformations **14,021** of 30,727 terms + 9,682 triples touched (retype 11,614 + no-evidence relabel 2,407) | Nothing is *overwritten* — the original survives beside it — so the risk is not loss, it is a reader mistaking the cleaned value for a verified one | High |
| Relevance of retained set | **ADEQUATE** | Independent corroboration from component G/L: kept triples are better KG-supported (**15.45% vs 6.41%**, microbe–disease) and better evidence-supported (**30.65% vs 17.15%**); BugSigDB: kept 54.3% vs dropped 44.3% (+10.0 pts, CI 1.1–18.6). Direction agreement 91.7% (11/12) | kept-vs-dropped deltas **+10.0 pts** (BugSigDB), **+9.0 pts** (KG, microbe–disease), **+13.5 pts** (evidence check) | All three corroborations are external and independent of the DeepSeek judge, which is what makes the layer's *selection* credible even though its *labels* are not verified | High |

**No averaged score is computed.**

---

## 2. What the layer does, in numbers

### 2.1 Triples

| Outcome | Rows | Share |
|---|---:|---:|
| kept | 9,682 | 37.54% |
| dropped — `not_well_formed` | 15,661 | 60.73% |
| dropped — `invalid_entities` | 445 | 1.73% |
| **relabelled** (orig ≠ cleaned) | **6,203** | 24.05% of all; 64.1% of kept |
| of which generic → typed | 6,146 | 99.1% of relabels |
| **direction swapped** | **408** | 1.58% of all; 4.21% of kept |
| relabel evidence `sentence` / `triple_only` | 3,796 / 2,407 | 61.2% / 38.8% |

`OTHER_RELATION` inside the kept set: **6,574 → 437**. The typed labels the model reaches for are
`ASSOCIATED_WITH` 2,374, `DECREASED_IN` 518, `CONTRIBUTES_TO` 510, `INCREASED_IN` 464, `CAUSES` 419,
`PRESENT_IN` 416, `MODULATES` 364, `PRODUCES` 306, `MEASURED_BY` 289, `COMPARED_WITH` 285,
`FOUND_IN` 258. The family composition of the kept set shifts accordingly: `disease_relationship`
2,759 (from 681), `presence_abundance` 1,547, `causal_regulatory` 1,499, `study_evidence` 607,
`host_association` 567.

### 2.2 Terms

| Outcome | Rows | Share |
|---|---:|---:|
| kept | 30,727 | 18.92% |
| dropped | 131,682 | 81.08% |
| retyped (kept) | 11,614 | 37.80% of kept |
| `ENTITY` before → after (kept) | 7,735 → 744 | −90.4% |

Judged-mention counts are thin: 6,048 kept terms rest on **2** judged mentions, 5,166 on **1**,
3,570 on 3, 3,052 on 4, 1,871 on 5. So the majority of keep/drop decisions at term level rest on one
or two mentions — a very small evidence base per decision.

### 2.3 Graph

| | Full | Cleaned | Change |
|---|---:|---:|---:|
| Nodes | 22,579 | 8,897 | −60.6% |
| Edges | 25,788 | 9,682 | −62.5% |
| Components | 3,052 | 1,219 | −60.1% |
| Largest component | 15,470 (68.5%) | 6,029 (67.8%) | share −0.7 pts |
| Isolated nodes | 73 | 2 | −97% |
| Mean degree | 2.20 | 2.11 | −4% |

---

## 3. Issues

### CQA-J-01 — 60.7% of the frozen triple layer is judged not well formed, by a model with an unshipped rubric
- **Severity:** **HIGH**
- **Type:** Confirmed property (largest single claim in the layer)
- **Evidence:** `drop_reason='not_well_formed'` on **15,661 / 25,788 = 60.73%**; `invalid_entities` 445. Survivors 9,682. Examples of dropped subjects/objects are concatenated strings (`100lofathp1cellsuspension106cellsml`, `100mgoffecalcontents`) — these are genuine extraction artefacts, which corroborates the *direction* of the judgment.
- **Affected:** 15,661 triples (60.7%).
- **Scientific impact:** This is a statement that **most of the released graph is not a well-formed relation**. It is more damaging than any finding in component G, and it comes from the project's own curation. The corroborating evidence (string concatenation) makes it credible; the fact that it is a single model's unshipped rubric makes it unverified.
- **Publication impact:** If the cleaned layer is described as "removing malformed relationships", the natural question is how many were malformed in the frozen release, and the answer is 60.7%. That number should be disclosed wherever the cleaned graph is presented, not just the survivor count.
- **Recommended action:** Report dropped-by-reason with the rubric definition and the count; sample 50 drops for a human spot-check to validate the 60.7% before it is quoted as fact. Publish the rubric.
- **Blocking:** blocks a "cleaned graph preserves the valid majority" framing.

### CQA-J-02 — Two in five relabels have no sentence-level evidence
- **Severity:** **HIGH**
- **Type:** Confirmed risk (unsupported transformation)
- **Evidence:** 6,203 relabels: `relabel_evidence='sentence'` **3,796 (61.2%)**, `'triple_only'` **2,407 (38.8%)**. Among generic→typed relabels: sentence 3,895 / triple_only 2,638 / none 41. `direction_swapped` on 408 rows: 299 sentence, **109 triple_only**.
- **Affected:** 2,407 relabels + 109 swaps = 2,516 transformations.
- **Scientific impact:** A relabel derived from the triple alone (`A — OTHER_RELATION — B` ⇒ `A ASSOCIATED_WITH B`) is a guess from the pair. `ASSOCIATED_WITH` is the modal target (2,374), and it is exactly the predicate a pair-only heuristic defaults to. The result is a graph that *looks* typed but whose typing is, for 39% of edits, unsupported by text.
- **Publication impact:** "Predicates were cleaned using sentence evidence" is true for 61% of edits. The manuscript must not imply sentence grounding for the whole relabel set.
- **Recommended action:** Separate the two relabel strata in any reported metric; publish `relabel.jsonl` alongside and state that 2,407 lack sentence evidence.
- **Blocking:** blocks a "sentence-grounded relabelling" claim.

### CQA-J-03 — 81% of canonical terms are dropped on 1–2 judged mentions each
- **Severity:** **HIGH**
- **Type:** Confirmed risk (thin evidence base)
- **Evidence:** 131,682 / 162,409 = **81.08%** dropped. Of the 30,727 kept, **5,166 rest on 1 judged mention and 6,048 on 2** — 36.5% of survivors are decided on a single mention. The drop rule is monotone in `valid_mention_share` (0 dropped terms have share ≥ 0.5), which is internally consistent but circular: the share is computed from the same judge that decides.
- **Affected:** 131,682 terms; and 11,214 of the kept ones whose verdict rests on ≤2 mentions.
- **Scientific impact:** An entity seen once is judged on one mention by one model. Dropping 81% of a terminology layer on that basis is a far more aggressive filter than any published NER curation and will delete many valid low-frequency taxa and methods — precisely the long tail a microbiome CDM exists to capture.
- **Publication impact:** The 30,727-term cleaned vocabulary must be presented as "high-confidence subset", never as "valid terms". The 131,682 are **not** shown to be invalid.
- **Recommended action:** State the mention-count distribution behind the keep decision; report a stratified sample of dropped single-mention terms as unvalidated. Do not call dropped terms invalid.
- **Blocking:** blocks describing the cleaned vocabulary as validated.

### CQA-J-04 — The transformation cannot be re-run from the repository
- **Severity:** **MODERATE**
- **Type:** Confirmed reproducibility gap
- **Evidence:** `MANIFEST.sha256` verifies 4/4 artefacts; `relabel.jsonl` records the relabels; but a repository-wide search finds **no generator** — `src/scripts/kg/build_kg.py`, `evidence_check.py`, `gold_kg_check.py` all consume the layer. The judge run is named only by directory (`llm_judge_deepseek_v4_flash`); its rubric/prompt is not in the layer.
- **Affected:** the whole layer.
- **Scientific impact:** The outputs can be checked for internal consistency and cross-validated externally (they are, §1), but the mapping from judge output to `kept`/`drop_reason`/`relation_cleaned` cannot be inspected. A reader cannot tell whether the threshold was 0.5, a majority vote, or something else.
- **Publication impact:** "Reproducible curation" is not claimable. "Checksummed curation with a documented rule" is.
- **Recommended action:** Ship the builder script and the exact rubric next to the layer. It is a small amount of code and it converts a WEAK to an ADEQUATE dimension.
- **Blocking:** blocks a reproducibility claim for the layer.

### CQA-J-05 — Cleaning prunes the graph but does not restructure it
- **Severity:** **MODERATE**
- **Type:** Confirmed property (interpretation)
- **Evidence:** Nodes −60.6%, edges −62.5%, components −60.1%, but largest-component share moves only 68.5% → 67.8% and mean degree 2.20 → 2.11. **13,682 of 22,579 nodes (60.6%) are orphaned** — every edge touching them was dropped.
- **Affected:** the whole graph.
- **Scientific impact:** A 60% node loss with unchanged topology means the cleaning removed *peripheral* structure and left the hub-dominated core intact. That is consistent with a well-formedness filter (junk strings live at the periphery) — a good sign — but it also means the cleaned graph is not a re-analysis. It is the same graph, smaller.
- **Publication impact:** Do not present `kg_cleaned.graphml` as a "curated knowledge graph" implying a qualitatively different object. It is a pruned version of the same one, with relabelled edges.
- **Recommended action:** Report node/edge attrition and the unchanged component share in the same sentence.
- **Blocking:** neither.

### CQA-J-06 — The layer's type vocabulary is now CDM-conformant, but the conformity is the only thing verified
- **Severity:** **MODERATE**
- **Type:** Confirmed property (partial validation)
- **Evidence:** Cleaned types are all drawn from `CDM_TYPES` (ORGANISM 5,485 / CHEMICAL 4,735 / DATA_ANALYSIS 4,170 / DISEASE 3,279 / LAB_METHOD 2,338 / PROTEIN 2,155 / CLINICAL 1,788 / DNA_RNA 1,662); `ENTITY` falls 7,735 → 744 among kept; **0** relation labels invented.
- **Affected:** 11,614 retyped terms.
- **Scientific impact:** This is a genuine improvement against component C's CRITICAL vocabulary-divergence finding: the cleaned layer removes the generic label that carried 55.29% of terms. But "in vocabulary" ≠ "correct type". Whether `CKD-related systemic inflammation` (DISEASE, unchanged) or any of the 11,614 re-typed terms got the right label is untested.
- **Publication impact:** The defensible claim is "the cleaned layer uses only CDM types and removes `ENTITY`". The indefensible one is "types were corrected".
- **Recommended action:** Report the retype count and the `ENTITY` collapse; do not report a type-accuracy figure.
- **Blocking:** neither, if scoped.

### CQA-J-07 — The cleaned layer and the frozen layer can be confused by a reader, and nothing in the filenames prevents it
- **Severity:** **LOW**
- **Type:** Documentation risk
- **Evidence:** Both live in `outputs/results/`; the cleaned files are `cleaned_triples.csv.gz` / `cleaned_terms.csv.gz` under a differently-named directory, `CLEANING_REPORT.md` says "Model curation, not human curation", and `MANIFEST.sha256` covers only the cleaned dir. The derived KG (`kg_cleaned.graphml`) sits beside the full graph in the same folder with a `kg_stats.json` that tabulates both.
- **Affected:** presentation risk only.
- **Scientific impact:** None intrinsically — the separation is real and reversible.
- **Publication impact:** Figure captions and supplement file names must say "DeepSeek-curated derivative" every time. The main text must quote the frozen numbers (25,788 / 162,409) or the cleaned ones (9,682 / 30,727) and never mix a numerator from one with a denominator from the other.
- **Recommended action:** Add a one-line header to each cleaned CSV naming the source release and the curation model.
- **Blocking:** neither.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates:**
- The layer is **additive and fully reversible**: originals sit beside cleaned values, the frozen CDM is untouched, and 4/4 artefacts verify.
- **60.7%** of the frozen triple layer is judged not well formed; survivors are 9,682 (37.5%).
- Generic predicates within the kept set fall **67.9% → 4.5%** with **0** invented relation labels; `ENTITY` among kept terms falls **7,735 → 744** and all cleaned types are CDM types.
- **38.8%** of relabels and **109 of 408** direction swaps have no sentence evidence.
- **81.1%** of terms are dropped, 36.5% of survivors decided on a single judged mention.
- Cleaning removes 60.6% of nodes without changing component share (68.5% → 67.8%) — pruning, not restructuring.
- External corroboration of the *selection* is real and independent: kept-vs-dropped +10.0 pts (BugSigDB), +9.0 pts (KG microbe–disease), +13.5 pts (evidence check).
- The generator script and rubric are **not** in the repository.

**Does not establish:**
- That the 131,682 dropped terms are invalid, or that the 445 invalid-entity triples are the only invalid ones.
- That any relabel or re-type is correct; no human reviewed any of them.
- That the cleaned layer is the release. It is a derivative and must be labelled as one.
- Any accuracy figure. This is model curation end to end.

---

## 5. Component verdict

As an artefact, this is the most defensible thing the project has built on top of the freeze: it is
**additive, reversible, checksummed, and externally corroborated**. Its keep/drop decisions survive
three independent tests that did not use the same judge — BugSigDB, curated-KG support and the
pre-registered evidence check all agree that the kept rows are better than the dropped ones, by 9 to
13.5 points. That is a real result and it should be reported as one.

As a *validated* curation it is not there, and the two gaps are specific. First, **two in five
relabels rest on the triple alone**, with no sentence — and `ASSOCIATED_WITH` is the modal target,
which is what a pair-only heuristic produces. Second, **81% of terms are dropped on one or two
mentions each**, so the 30,727-term vocabulary is a high-confidence tail-cut, not a validated
vocabulary; the 131,682 are unvalidated, not wrong.

The one number that must not be lost is **60.7%**. The project's own curation says most of the frozen
graph is not a well-formed relation. Whether that is right deserves a 50-row human check, because it
is the single most consequential claim anyone has made about this layer — and it currently rests on
a model and an unshipped rubric.
