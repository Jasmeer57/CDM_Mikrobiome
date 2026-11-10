# Component I — NER Benchmark Quality

**Audited object:** the two benchmark suites the project uses to justify NER model choices —
the **public gold-standard benchmark** (`outputs/results/benchmark/ner_fair_bench/`: BC5CDR
500 abstracts / 9,809 entities and BioRED 100 abstracts / 3,535 entities, **27 configurations ×
2 corpora = 54 runs**) and the **corpus benchmark** (`outputs/results/benchmark/ner_corpus_bench/`:
**26 configurations** over 21,560,603 chars / 7,161 chunks) — plus the quality-vs-quantity study in
`ner_quality_quantity_2026-11-03/`.
**Evidence base:** `FAIR_NER_BENCHMARK.md`, `fair_ner_metrics.json` (54 keys of the form
`<corpus>__<model>`), `CORPUS_NER_BENCHMARK.md`, `corpus_metrics.json`, `REPORT.md` +
`MEASUREMENT_NOTES.md`, `per_config_type.csv`; Tier-1/Tier-2 records in
`d20_evidence_tiers.json`; and `preds/` (54 JSONL prediction files).
**Independence:** every F1, confidence interval, p-value and grounding percentage below was read
from the per-run metrics and the per-configuration predictions, not from a summary table alone. The
absence of a manifest was established by listing the directory.

> **AMENDED 2026-11-04 — read `NER_BENCHMARK_CORRECTIONS.md` before quoting anything in this file.**
> Twelve statements below are superseded by a dated methodological correction (full list in §6 of
> this file, immediately before the verdict). The correction re-derived every metric from the 54
> prediction files (**1,186 values, 0 mismatches**), rebuilt the CDM↔benchmark type crosswalk, measured
> the ORGANISM transfer gap, separated deployable from reference-only systems, recovered and verified
> the prompts, and sealed the artefact set retrospectively. Nothing in this file was deleted and no
> frozen result was altered; superseded numbers are marked *[superseded]* where they appear and
> itemised at the end.

> **Tier discipline (brief §I, and the audit's central rule).** These benchmarks are **Tier 1 —
> human-annotated public gold standards**. They establish how well each extractor performs on
> BC5CDR and BioRED. They establish **nothing** about the 453-paper corpus, because the corpus has
> no human annotation and the public corpora are a different domain, a different type inventory and
> a different text genre (PubMed abstracts vs segmented full text). Public F1 must never appear in a
> sentence as "corpus accuracy".

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Protocol / fairness | **ADEQUATE** | All models scored on the same official splits with whole title+abstract; exact and relaxed matching both reported; **full-schema F1** counts types a model cannot emit as misses and `n/a` cells are shown explicitly; in-domain training flagged `†`; document-bootstrap 95% CIs and permutation p-values reported for every row | identical splits: **yes** (500 / 100 abstracts); chance-corrected comparisons **present**; in-domain advantage **flagged** | The comparison mixes *kinds*: a curated database lookup (PubTator3), trained token classifiers, zero-shot NER, and 3-shot LLMs sit in one ranked table. That is a legitimate "what is available" comparison but not a controlled model comparison — and the winner is the one that is not a model run | High |
| Statistical robustness | **STRONG** | 95% CI by document bootstrap on every F1; significance vs the best row (`p vs best`); Wilson intervals on every proportion; bootstrap intervals on every rate; permutation tests in the per-model evaluation | every headline number carries an interval; every pairwise claim carries a p-value | Bootstrap over 500/100 documents is wide for the smaller corpus (BioRED n=100), so small rank differences there are not resolvable — and the report says so via CI overlap (PubTator3 78.3 [71.2–85.0] vs HunFlair2 80.6 [78.3–82.8], p=0.274) | High |
| Reproducibility | **ADEQUATE** *(rated WEAK before the 2026-11-04 amendment)* | 54 prediction files exist in `preds/`, the metrics JSON is complete, and the protocol is named (`src/scripts/ner_fair_bench/fairbench.py`) — but the directory contains **no `MANIFEST.sha256`** and no `PREREGISTRATION.sha256` *[superseded in part — a dated retrospective seal now exists, and the prompts were recovered and verified; preregistration is still absent. See `NER_BENCHMARK_CORRECTIONS.md` §5–6 and `NER_REPRODUCIBILITY_GAPS.md`]* | checksummed artefacts **0 / 3** at the time of audit *[superseded: manifest **1 / 3**, retrospective; prompt bundle **recovered**; preregistration still **absent**]*; 54 unhashed prediction files *[superseded: 126 files / ≈3.57 GB sealed]* | *Revised upward because all **1,186** reported values were recomputed from the predictions with **0 mismatches**, checkpoint revisions were recovered from job logs, and a seal now exists. Still not STRONG: there is **no preregistration**, run-time library versions are unrecorded, and the LLM prediction files discard off-schema entities before writing* | High |
| Coverage of the CDM's own types | **CRITICAL** | BC5CDR covers **2** types (Chemical, Disease); BioRED covers **6** (Chemical, Disease, Gene, Variant, CellLine, Species). The CDM vocabulary is **14** types, and the dominant extracted type is **`ENTITY` (89,799 terms, 55.29%)** with `ORGANISM` second (component C). **No benchmark in the suite tests `ORGANISM`, `MICROBIOME`, `LAB_METHOD`, `DATA_ANALYSIS`, `DIET`, or `HABITAT`** — the types that carry the corpus's scientific content *[superseded: `ORGANISM` **is** approximated by BioRED `OrganismTaxon`; `MICROBIOME`/`DIET`/`HABITAT` are **not CDM types**. Correct split: 2 direct / 3 approximate / 9 none. See `NER_TYPE_COVERAGE_MATRIX.csv`]* | target-type coverage **2/14** on BC5CDR, **6/14** on BioRED, **0** benchmarks for the five microbiome-specific types *[superseded: those are counts of benchmark types present, not CDM types covered; wholly unbenchmarked CDM types = **9**, not 6 — §1.4 of the correction]* | The benchmark can rank extractors on chemical/disease mention finding. It cannot tell you whether any extractor finds a taxon, a method, or a body site correctly, which is what the CDM is for | High |
| Grounding (corpus) | **ADEQUATE** | 25 configurations carry a grounding block over 21.56 M chars / 7,161 chunks (`scispacy_lg` is untyped and carries none); per-type grounding reported against **external reference lexicons**, not the CDM vocabulary *[corrected 2026-11-05 — see §6a]*. Best chemical grounding **41.3%** (`bert_chemical`, 1,702/4,123 unique), `scispacy_craft` 38.1%, `bert_disease` 29.2%, `scispacy_bc5cdr` 25.7%, `llm_gemma_zs` OrganismTaxon 25.3%; **0.0%** for CellLine across all models | max grounding **41.3%**; median far lower; CellLine **0%** for every configuration | *[superseded — the circularity claim below is **wrong**]* Grounding is measured against **external** lexicons (NCBI Gene, CTD/MEDIC, Mondo, HPO, NCBI Taxonomy, OMOP), not the project's own term layer, so it is not circular; it remains a **precision proxy** (a string can hit an unrelated synonym, a real entity can be absent). The CellLine **0%** is **definitional** — `ground()` returns `set()` for that type. See correction §9 | High |
| KG support (corpus) | **WEAK** | `corpus_metrics.json:cdm_triples`: microbe–disease **943 triples, 137 with both ends grounded, 50 KG-supported = 36.5% of grounded**; gene–disease 29 triples / 8 grounded / **0 supported**; chem–disease and chem–gene **0 triples**. | KG support **36.5%** of 137 grounded microbe–disease edges; 0/8 gene–disease | Support is a coverage statement about a reference KG (component L). A 36.5% figure over 137 edges is a very small denominator and must not be read as precision. | High |
| Quality vs quantity | **ADEQUATE** | `ner_quality_quantity_2026-11-03/` compares volume against the merged metrics and the type table (`per_config_type.csv`); the report carries `MEASUREMENT_NOTES.md` documenting what was and was not measured | per-config type breakdown **present**; explicit measurement notes **present** | Volume is easy to inflate: the highest-row configuration is not the best one, and the corpus layer later collapses 45.6% duplicate spans (component H, CQA-H-06) — a benchmark that ranks by rows would reward redundancy | High |
| Interpretability of the recommendation | **WEAK** | The ranked table's top row is `pubtator3 †` (BC5CDR 90.1 [88.4–91.6]) — a **precomputed API result trained on BC5CDR**, i.e. an in-domain curated database lookup, not a model the project can run on its own corpus. The best *runnable* general models are `hunflair2 †` 77.3 and `llm_qwen_fs` 69.5. On BioRED the order flips: `hunflair2` 80.6 > `pubtator3` 78.3 (p=0.274) | "best model" changes with corpus (**pubtator3** on BC5CDR, **hunflair2** on BioRED) and the top BC5CDR entry is **not deployable** for full-text section NER (PubTator3 is excluded from section mode in the pipeline) | A reader skimming the table will conclude "use PubTator3". The pipeline itself cannot, for section-level work, and the manuscript must not recommend a component it does not run | High |
| Runtime / resource reporting | **ADEQUATE** | `s/doc` reported per configuration (0.0116 s for `bert_chemical` to **6.53 s** for `llm_llama_zs`), device recorded per model (`A40 GPU`, `CPU (8 cores)`), chunk and char counts fixed across models | throughput spread **≈560×** between fastest and slowest; same 7,161 chunks / 21.56 M chars for all | Total GPU-hours are not aggregated, so the cost of the chosen configuration is not stated as a single number | High |

**No averaged score is computed.**

---

## 2. What the two suites actually contain

### 2.1 Public gold standard (Tier 1) — selected rows, BC5CDR

| Model | Kind | Full-schema exact F1 [95% CI] | Relaxed | P | R |
|---|---|---:|---:|---:|---:|
| pubtator3 † | precomputed API | **90.1 [88.4–91.6]** | 93.7 | 91.4 | 88.8 |
| hunflair2 † | trained NER | 77.3 [76.1–78.6] | 90.5 | 79.1 | 75.6 |
| scispacy_bc5cdr † | trained NER | 75.1 [73.7–76.4] | 85.4 | 79.6 | 71.1 |
| llm_qwen_fs | LLM 3-shot | 69.5 [67.8–71.1] | 76.2 | 71.9 | 67.3 |
| gliner_v25_medium | zero-shot NER | 69.2 [67.6–70.7] | 83.1 | 71.4 | 67.2 |
| llm_gemma_zs | LLM zero-shot | 67.0 [65.3–68.6] | 75.4 | 65.5 | 68.5 |
| llm_deepseek_fs | LLM 3-shot | 55.1 [53.1–57.1] | 62.0 | 70.5 | 45.3 |
| scispacy_craft | trained NER | 23.3 [21.3–25.4] | 26.4 | 63.9 | 14.3 |
| bert_genetic / scibert_jnlpba / scispacy_jnlpba / scispacy_lg | trained NER | **0.0** | 0.0 | 0.0 | 0.0 |

BioRED (6 types): `hunflair2` **80.6 [78.3–82.8]** > `pubtator3 †` 78.3 [71.2–85.0] (p=0.274) >
`llm_qwen_fs` 66.2 > `llm_gemma_zs` 66.0 > `llm_qwen_zs` 64.5 > `gliner_v25_biomed` 60.4.

The **0.0 rows are label-mapping artefacts, not model failures**: `bert_genetic`, `scibert_jnlpba`
and `scispacy_jnlpba` cannot emit Chemical or Disease, so full-schema F1 is 0 by construction —
`scispacy_lg` scores 0.0 exact but **30.3 span-only F1**, which is the tell. Any summary that counts
these as four broken models is wrong. *[superseded in part: there are **five** 0.0 rows across the two
corpora (`+ biored__scispacy_lg`, 38.3 span-only), and the mechanisms differ — three label-map zeros,
one untyped-only model, one untyped-only on BioRED.]*

### 2.2 Corpus run (not a gold standard) — 26 configurations

21,560,603 chars / 7,161 chunks / 453-paper body universe *[corrected description: **all 453 papers**,
every section except References and Acknowledgements, packed into ≤4,000-character chunks, scored under
the **BioRED 6-type schema** — not the CDM 14-type schema, and not the 452-paper body universe]*.
`hunflair2` on CPU (8 cores) took
2,210.6 s and emitted DISEASE 34,818 / CHEMICAL 33,857 / ORGANISM 30,238 / PROTEIN 9,708 /
CELL_TYPE 101 — note that on the corpus, ORGANISM is a high-volume type, while on BC5CDR/BioRED
**no benchmark exists for it**.

Grounding spread across 117 (model, type) cells: best 41.3% (chemical), 38.1% (chemical),
29.2% (disease), 25.7% (chemical), 25.3% (OrganismTaxon); **0.0%** for CellLine in every model that
emits it, and 0 papers with entities for `scispacy_lg`.

### 2.3 KG support is a by-product, with a small denominator

| Edge type | Triples | Both ends grounded | KG-supported | % of grounded |
|---|---:|---:|---:|---:|
| microbe–disease | 943 | 137 | 50 | **36.5%** |
| gene–disease | 29 | 8 | 0 | 0.0% |
| chemical–disease | 0 | 0 | 0 | — |
| chemical–gene | 0 | 0 | 0 | — |

---

## 3. Issues

### CQA-I-01 — The public benchmark cannot speak to the corpus, and the risk of it doing so is the largest hazard here
- **Severity:** **CRITICAL**
- **Type:** Confirmed scope limitation (interpretive hazard)
- **Evidence:** Tier 1 = BC5CDR (2 types) + BioRED (6 types) over PubMed abstracts. The corpus is 453 full-text papers in 14 CDM types, of which `ENTITY` (55.29% of terms) and `ORGANISM` are the largest. *[superseded in part: `ORGANISM` is approximated by BioRED `OrganismTaxon`, though the transfer fails — 90.8% of that type's gold mentions are host terms and none are bacterial taxa; see correction §1.3.]* `d20_evidence_tiers.json` records Tier 1 with `manifest: ABSENT`.
- **Affected:** the entire inferential bridge from benchmark to corpus.
- **Scientific impact:** A 90.1 F1 on BC5CDR chemical/disease mention detection says nothing about whether `HMCTERM_…` "composition of the gut microbiota" is a valid entity, or whether the type assigned to it is right (component C finds 3.06% type provenance and 57.6% flag-vs-type disagreement). The corpus layer's own measured property is **offset exactness 99.9978%** — an extraction-mechanics result, not an accuracy result.
- **Publication impact:** The single most likely misreading in the whole manuscript is "our NER achieves F1 0.90". It does not: PubTator3 does, on BC5CDR, in-domain. The manuscript must report the benchmark **as a model-selection experiment on public data** and separately report what was measured on the corpus (offset integrity, type distribution, grounding), never as one number.
- **Recommended action:** Keep the two in separate subsections with separate verbs. Add one sentence stating explicitly that no gold standard exists for the corpus and that no F1 is claimed for it.
- **Blocking:** blocks any corpus-accuracy claim derived from these numbers.

### CQA-I-02 — No benchmark covers the types the CDM is built on
- **Severity:** **HIGH**
- **Type:** Confirmed coverage gap
- **Evidence:** BC5CDR: Chemical, Disease. BioRED: Chemical, Disease, Gene, Variant, CellLine, Species. CDM `CDM_TYPES`: 14. Corpus volume leaders: `ENTITY` 89,799, `ORGANISM` 12,026. *[superseded in part: `HABITAT`, `DIET` and `MICROBIOME` are **not** CDM types — they were invented here. The correct split is 2 direct / 3 approximate / **9 wholly unbenchmarked**, and `ENTITY` is outside the schema entirely. See correction §1.4 and `NER_TYPE_COVERAGE_MATRIX.csv`.]* `scispacy_lg` produces a generic `ENTITY` label for every term and therefore cannot be scored on any type at all.
- **Affected:** ≥12 of 14 CDM types; 100% of the microbiome-specific types.
- **Scientific impact:** Model selection for the corpus was driven by performance on chemical/disease mention finding — the two types with the *least* microbiome specificity. A model that is best at disease names may be worst at taxa; nothing in this suite tests that.
- **Publication impact:** "Models were selected on benchmark performance" must be qualified with **which** performance and **which** types, or a reviewer will assume the selection optimized the corpus's own task.
- **Recommended action:** State the type-coverage gap in the methods and limitations. A small hand-annotated taxon sample (200 spans) would be worth more than any additional public benchmark.
- **Blocking:** blocks a "benchmark-justified model selection" claim.

### CQA-I-03 — The top BC5CDR row is an in-domain database lookup, and the pipeline cannot use it for section NER
- **Severity:** **HIGH**
- **Type:** Confirmed property (misleading ranking)
- **Evidence:** `pubtator3 †` = 90.1 [88.4–91.6], `†` = trained on this corpus. PubTator3 is a **precomputed API result**, not a local model; the pipeline excludes PubTator3 from section mode (`predict_text` raises `NotImplementedError`) and its offsets are PubMed-abstract geometry, not corpus section offsets. On BioRED the same row drops below HunFlair2 (78.3 vs 80.6, p=0.274).
- **Affected:** the recommendation that follows from the table.
- **Scientific impact:** The best *available* general extractor for the project's actual task is `hunflair2` (77.3) or `llm_qwen_fs` (69.5), not the 90.1 row. The 90.1 is a ceiling set by a curated resource, and it is not reachable on full-text sections.
- **Publication impact:** A ranked table headed by a non-deployable component invites the wrong conclusion. Either drop the row from the ranking or annotate it as "reference ceiling, not a candidate".
- **Recommended action:** Add a `deployable_on_sections` column to the table and rank by it.
- **Blocking:** blocks a "best model" recommendation that cites 90.1.

### CQA-I-04 — The Tier-1 benchmark is the only unchecksummed artefact in the audit
- **Severity:** **MODERATE**
- **Type:** Confirmed reproducibility gap
- **Evidence:** `outputs/results/benchmark/ner_fair_bench/` contains `preds/` (54 JSONL files), `fair_ner_metrics.json` and `FAIR_NER_BENCHMARK.md`. **No `MANIFEST.sha256`, no `PREREGISTRATION.sha256`, no prompt bundle, no environment lock.** By contrast, `triple_reference_check` (Tier 2) and `kg_2026-11-04/evidence_check` (Tier 3) both ship `PREREGISTRATION.sha256` + `MANIFEST.sha256`.
- **Affected:** 54 runs, both corpora.
- **Scientific impact:** The benchmark that matters most for credibility is the one that cannot be verified against a hash. Predictions could be re-scored, but nothing proves the shipped predictions are the ones that produced the shipped metrics.
- **Publication impact:** A reviewer asking "can I reproduce Table X" can be answered for Tier 2/3 and not for Tier 1.
- **Recommended action:** Add a manifest and a preregistration hash retroactively (the artefacts are unchanged; the hash can be computed now and dated as an audit-time seal). Ship the nine LLM prompts verbatim.
- **Blocking:** blocks a "fully reproducible benchmark" claim.

### CQA-I-05 — Nine LLM configurations differ in prompt strategy, and the prompts are not shipped
- **Severity:** **MODERATE**
- **Type:** Confirmed documentation gap
- **Evidence:** `_zs` (zero-shot) and `_fs` (3-shot) variants for deepseek, gemma, llama, mistral, phi, qwen. Within-model gaps are large and inconsistent: `qwen_fs` 69.5 vs `qwen_zs` 61.1 on BC5CDR (**+8.4**), `llama_fs` 61.3 vs `llama_zs` 57.8 (+3.5), `gemma_zs` 67.0 > `gemma_fs` 64.9 (**−2.1**). Latency explodes for some: `llama_zs` 6.53 s/doc vs `gemma_zs` 0.23 s/doc.
- **Affected:** 18 of 54 runs.
- **Scientific impact:** A few-shot advantage that flips sign between models, and a 30× latency spread at the same accuracy band, means the `_fs`/`_zs` comparison is not a clean ablation. Without the prompts, a reader cannot tell whether the shots are the same examples across models.
- **Publication impact:** Any "few-shot improves LLM NER" statement is unsafe; the gemma reversal is direct counter-evidence.
- **Recommended action:** Publish the prompt templates and the shot examples; report `_fs` vs `_zs` per model with CIs rather than pooled.
- **Blocking:** blocks a few-shot claim.

### CQA-I-06 — The grounding column mixes three unlike measures and one of them is not a vocabulary lookup *[corrected 2026-11-05 — the circularity claim in this block was wrong; see §6a]*

> *[superseded 2026-11-05]* The block below was originally titled **"Corpus grounding is measured
> against the project's own terms, so it is partly circular."** That premise is **false**:
> `corpus_bench.py:build_lexicon()` builds its lexicons from *downloaded external references*
> (NCBI Gene, CTD/MEDIC, CTD chemicals, OMOP/Mondo + HPO, NCBI Taxonomy) and the source contains no
> reference to `canonical_term` at all — verified by `diagnostics/cqa_i_grounding.py`. The original
> title, evidence, scientific-impact and recommended-action text follow, marked as superseded, because
> the *defect the block was reaching for* is real, just different. The corrected statement is in the
> "Corrected finding" block after it.

- **Severity:** **MODERATE** *(unchanged — the severity was right, the reason was wrong)*
- **Type:** Confirmed methodological limitation
- **Evidence:** *[superseded 2026-11-05 — this evidence describes a mechanism that does not exist]*
  ~~Grounding = share of extracted surfaces that match a `canonical_term`. `bert_chemical` 41.3%
  (1,702/4,123), `scispacy_craft` 38.1%, `bert_disease` 29.2%, `scispacy_bc5cdr` 25.7%,
  `llm_gemma_zs` 25.3%. The canonical terms were themselves produced by a *different* ensemble over
  the same corpus.~~
- **Affected:** all 117 (model, type) grounding cells; 25 configurations *(corrected 2026-11-05:
  `scispacy_lg` carries no grounding block, so 25 of 26 configurations contribute the 117 cells; the
  original said 26)*.
- **Scientific impact:** *[superseded 2026-11-05]* ~~Two extractors agreeing on a string raises the
  grounding score even if both are wrong...~~ The corrected impacts are below.
- **Publication impact:** *[superseded 2026-11-05]* ~~"Models were validated by entity grounding" is
  not supportable. The correct phrasing is "model output was consistent with the project's canonical
  term inventory at X%".~~
- **Recommended action:** *[superseded 2026-11-05]* ~~Label the column `consistency_with_CDM_terms`,
  not `grounded`.~~
- **Blocking:** blocks a grounding-as-validation claim.

**Corrected finding (2026-11-05).** The grounding column is *external*, so the circularity worry is
gone — and with it the project's best defence against the weaker charge that follows. Three unlike
measures share one column name, and the manuscript quotes a single number from all of them:

1. **`ChemicalEntity`, `DiseaseOrPhenotypicFeature`, `GeneOrGeneProduct`, `OrganismTaxon`** are genuine
   external-vocabulary lookups over 95 of the 117 cells. These are legitimate Tier-2 precision proxies.
2. **`SequenceVariant` (16 cells) is not a vocabulary lookup at all.** `ground()` returns
   `{"PATTERN"}` iff the string matches `VARIANT_RE` — a surface-format regex for `rs…`, HGVS-like and
   substitution-like strings. Its 2.5% pooled rate (1,257 / 50,249 unique strings) measures **how often
   a model emitted variant-shaped text**, not whether the variant exists. A fabricated `rs999999999`
   scores exactly like a real one.
3. **`CellLine` (19 cells) is definitional 0.0%** — `ground()` returns `set()` unconditionally. It is a
   missing vocabulary, not a model result, and appears in the manuscript's figure as a model outcome.

**Two further denominators the block never stated.** (a) Grounding is the share of **unique strings**,
not of mentions: `llm_qwen_fs` `OrganismTaxon` is 15.1% of 9,113 distinct strings over **54,139
mentions**, so a model that repeats one grounded surface inflates nothing while a model that emits many
near-duplicate wrong surfaces is punished — the metric is a *type inventory* measure, not a
per-occurrence one. (b) `corpus_metrics.json` ships `other_type_pct` — the share of a model's strings
that ground **in a different type than predicted** — and neither this report nor the manuscript has ever
reported it. It reaches **19.1%** (`llm_qwen_fs` `GeneOrGeneProduct`) and is above 10% in 9 cells, so
for the LLMs a large fraction of "ungrounded" strings are in fact recognisable biomedical names filed
under the wrong type. Grounding is therefore **type-blind about the error that dominates the LLMs**.

- **Corrected scientific impact:** The four lookup types are a usable precision proxy; the variant
  column and the CellLine column are not measures of correctness at all. Because the metric scores
  distinct strings and ignores cross-type grounding, a low grounding rate cannot be read as "the model
  invented strings" — the manuscript's own sentence at `02_results.md:108` and the plotting of CellLine
  0.0% as a model outcome both go further than the metric supports.
- **Corrected publication impact:** "Gemma came closest to the trained taggers" and "no system grounded
  more than 41.3% of its strings of any type" are defensible as stated *only* if the figure caption
  excludes `SequenceVariant` and `CellLine`, states that the denominator is unique strings, and reports
  `other_type_pct`. Without those, the grounding panel reads as an accuracy-like ranking it is not.
- **Corrected recommended action:** (i) split the column into `grounded_external_vocab` (4 types),
  `variant_pattern_match` and `cellline_not_attempted`; (ii) label the denominator "share of distinct
  predicted strings"; (iii) publish `other_type_pct` beside every grounding cell; (iv) drop CellLine from
  the figure or annotate it as a vocabulary gap. Reproducer: `diagnostics/cqa_i_grounding.py`.


### CQA-I-07 — Four 0.0 rows are label-mapping artefacts that will be misread
- **Severity:** **LOW**
- **Type:** Confirmed artefact (needs a footnote)
- **Evidence:** `bert_genetic`, `scibert_jnlpba`, `scispacy_jnlpba` score 0.0 full-schema because they emit no Chemical/Disease label; `scispacy_lg` scores 0.0 exact but **30.3 span-only**, and produces a generic `ENTITY` label for every span, so it can never score on any typed benchmark.
- **Affected:** 4 of 27 BC5CDR rows.
- **Scientific impact:** These are single-type or untyped models being scored on a two-type / six-type task. Their 0.0 is a schema mismatch, not a failure to find spans.
- **Publication impact:** If the table is published, the footnote must be in the caption; otherwise it reads as "four models found nothing", which is false.
- **Recommended action:** Replace 0.0 with `n/a` where the type is unsupported, and add `span-only F1` alongside (already present for these rows — surface it).
- **Blocking:** neither.

### CQA-I-08 — The corpus KG-support figure rests on 137 edges
- **Severity:** **LOW**
- **Type:** Confirmed small-denominator risk
- **Evidence:** microbe–disease 943 triples, 137 with both ends grounded, 50 KG-supported = 36.5%; gene–disease 8 grounded / 0 supported; chemical–disease and chemical–gene **0 triples**.
- **Affected:** 137 edges.
- **Scientific impact:** 36.5% of 137 is a 95% interval roughly 26–48%; it cannot distinguish a good extractor from a mediocre one, and the two zero-triple edge types mean half the table is empty.
- **Publication impact:** Do not summarize this as "36.5% of extracted relationships were confirmed in a knowledge graph". It is 36.5% of the 1.4% of edges whose ends both grounded.
- **Recommended action:** Report the denominator explicitly or omit the corpus KG-support column.
- **Blocking:** neither, if the denominator is stated.

### CQA-I-09 … CQA-I-20 — provenance and reproduction gaps
Twelve further issues were raised by the 2026-11-04 amendment, all scoped to *how the numbers were
produced* rather than *what they say*. Full entries — evidence, severity, closability and what it would
take to close each — are in `NER_REPRODUCIBILITY_GAPS.md` §12. Summary: **3** cannot be closed without
re-running extraction (off-schema entities discarded before write; per-document truncation recorded only
as counts; PubTator3 unidentifiable), **2** cannot be closed at all (no preregistration; a 0-byte
environment log whose script is gone), **3** only partly, and **4** are documentation or packaging fixes
available today. No item contradicts any reported value — all 1,186 reproduce exactly.

---

## 4. The four evidence tiers, kept separate

| Tier | What it is | This component's evidence | What it can support |
|---|---|---|---|
| **1. Public gold standard** | Human-annotated BC5CDR / BioRED | 27 configs × 2 corpora, CIs, p-values | Model ranking on chemical/disease (and 4 more BioRED types) mention finding. **Nothing about the corpus.** |
| **2. External-reference grounding** | BugSigDB, CTD (component K/L) | triple-reference check; BugSigDB field concordance | Whether a specific fact appears in a curated reference. Coverage, not accuracy. |
| **3. KG support** | Curated-KG membership of an edge | 50/137 microbe–disease grounded edges | Coverage of a small resolved subset. Absence is untested, not incorrect. |
| **4. Model-generated validity** | LLM judges, DeepSeek/Gemma verdicts | judge layer, cleaned layer | Model behaviour. Never annotation. |

The benchmark suite is entirely Tier 1. Every other number in this audit that someone might want to
put beside it is a different tier and cannot be averaged with it.

---

## 5. What this component demonstrates, and what it does not

**Demonstrates:**
- The benchmark protocol is fair and statistically careful: identical splits, both match regimes,
  in-domain flags, bootstrap CIs, permutation p-values, explicit `n/a`.
- On BC5CDR the ranking is `pubtator3 †` 90.1 > `hunflair2 †` 77.3 > `scispacy_bc5cdr †` 75.1 >
  `llm_qwen_fs` 69.5 > `gliner_v25_medium` 69.2, with every other row below and CI-separated.
- On BioRED the order changes and the top two are statistically indistinguishable (80.6 vs 78.3,
  p=0.274) — a real, reported result that undercuts any single "best model" claim.
- Four 0.0 rows are schema artefacts, one of which (`scispacy_lg`) has 30.3 span-only F1.
  *[superseded: five rows across both corpora, and `scispacy_lg` is 0.3027 on BC5CDR / 0.3832 on
  BioRED — see correction §2.4.]*
- Corpus grounding peaks at 41.3%; CellLine grounds at 0.0% everywhere; corpus KG support is 36.5%
  of 137 edges. *[CellLine 0.0% is definitional, not a model result — correction §9.]* *[superseded
  2026-11-05 in part: the 41.3% is a genuine external-vocabulary lookup, but the same column also
  carries a regex "variant pattern match" (2.5% pooled) and the definitional CellLine zero; the
  denominator is distinct strings, and the shipped `other_type_pct` (up to 19.1%) is unreported.
  See §6a.]*
- The Tier-1 artefacts carry **no manifest, no preregistration and no prompt bundle**.
  *[superseded: a dated retrospective SHA-256 seal now exists (126 files, ≈3.57 GB, verifies 126/126)
  and the prompts were recovered and verified; **preregistration is still absent and cannot be created
  retrospectively**. Correction §5–6.]*

**Does not establish:**
- Any accuracy, precision, recall or completeness figure for the 453-paper corpus, in any type.
- That the corpus's dominant types (`ENTITY`, `ORGANISM`) are extracted well or badly.
- That a model chosen on BC5CDR is the right model for full-text microbiome sections.
- That grounding equals correctness, or that KG support equals truth.

---

## 6. Amendment record — 2026-11-04

A focused methodological correction re-derived component I from the prediction files and the frozen
terminology layer. It changed **no** prediction file, **no** `fair_ner_metrics.json`, **no**
`FAIR_NER_BENCHMARK.md`, and **no** frozen release; every new artefact is written under
`paper/publication/component_quality_audit/`. The twelve statements below are superseded. Where a
superseded number appears in the body of this file it is marked *[superseded …]* in place; nothing was
deleted.

| # | Superseded here | Corrected | Correction doc |
|---|---|---|---|
| 1 | "0 benchmarks for the five microbiome-specific types"; `MICROBIOME`/`DIET`/`HABITAT` listed as CDM types | `MICROBIOME`, `DIET`, `HABITAT` are **not** in `CDM_TYPES`. Correct split of the 14 types: **2 direct** (CHEMICAL, DISEASE = 22.78% of 72,610 typed terms), **3 approximate** (ORGANISM, PROTEIN, CELL_TYPE = 35.32%), **9 none** (41.90%) | §1.2, §1.4; `NER_TYPE_COVERAGE_MATRIX.csv` |
| 2 | "No benchmark tests `ORGANISM`" | BioRED `OrganismTaxon` tests it — but **90.8%** of its test mentions are host-generic, **0** are bacterial taxa, and the best model on the type (0.9441 `hunflair2`) falls to **0.556** recall on the 36 non-host mentions while `llm_qwen_fs` reaches **0.917** | §1.3; `diagnostics/results/ner_organism_transfer.json` |
| 3 | "target-type coverage 2/14 on BC5CDR, 6/14 on BioRED" | Those are counts of *benchmark types present*, not of CDM types covered. The CDM-type view is **2 / 3 / 9** | §1.2 |
| 4 | Reproducibility rated WEAK partly for "no record of the prompt text used for the nine LLM configurations" | There are **twelve** LLM configurations (6 models × zs/fs), and all twelve prompts plus every few-shot message were **recovered and verified** against the `fewshot_train_pmids` recorded in the prediction files | §6; `NER_RECOVERED_PROMPTS.md` |
| 5 | "no manifest … no prompt bundle"; "checksummed artefacts 0/3" | A dated **retrospective** SHA-256 seal now covers **126 files / ≈3.57 GB** and verifies 126/126. Prompts recovered. **Preregistration is still absent** and cannot be created after the fact — the seal is explicitly not a preregistration | §5; `NER_RETROSPECTIVE_SEAL.sha256`, `NER_REPRODUCIBILITY_GAPS.md` |
| 6 | Grounding is "measured against the project's own term layer, so it is circular" | **Wrong.** `corpus_bench.py` builds its lexicons from **external** references (NCBI Gene, CTD/MEDIC, Mondo, HPO, NCBI Taxonomy, OMOP). It is a precision proxy, not circular; `CellLine` 0.0% is **definitional** (`ground()` returns `set()`) | §9 |
| 7 | "Four 0.0 rows are schema artefacts, one of which (`scispacy_lg`) has 30.3 span-only F1" | **Five** 0.0 rows across both corpora (`+ biored__scispacy_lg`); `scispacy_lg` is **0.3027** on BC5CDR and **0.3832** on BioRED; the mechanisms differ (3 label-map zeros, 2 untyped-only) | §2.4 |
| 8 | `†` treated as a single category meaning "trained on this corpus" | Four distinct exposure classes plus one unmeasurable: training-set reuse (4 names), **annotation-source contamination** (`pubtator3` — P 0.9142 / R 0.8879 / F1 0.9009 on BC5CDR, `docs_found 500/500`), dev-set threshold tuning (8 GLiNER runs, grid 0.3–0.7, thresholds reused on the corpus run), and **unmeasurable LLM pretraining contamination**. Split leakage itself is **0** (test∩train = 0, test∩dev = 0) | §3 |
| 9 | "The best *runnable* general models are `hunflair2 †` 77.3 and `llm_qwen_fs` 69.5" — presented as a caveat | Retained numerically but promoted to a **structural rule**: PubTator3 is **reference-only**, not deployable (`predict_text` raises `NotImplementedError`, excluded from section mode, abstract/passage offsets). `NER_MODEL_DEPLOYABILITY.csv` classifies 25 YES / 1 reference-only / 1 untyped-only, and a non-deployable system must never head a candidate ranking | §7 |
| 10 | `full_schema` F1 used as the cross-model headline | `full_schema` conflates **label coverage with skill**: **14 of 27** BioRED configurations cannot emit all six types. A `supported_schema_exact_F1` was added — `bert_disease` moves 0.3613 → **0.8606**. Neither is comparable across label inventories; **per-type F1 is the only cross-model unit** | §2.1–2.2; `NER_RECOMPUTATION_CHECK.csv` |
| 11 | "453-paper body universe" for the corpus run; CDM type schema implied | All **453** papers, **every section except References/Acknowledgements**, ≤4,000-char chunks (**7,161** chunks / 21,560,603 chars), scored under the **BioRED 6-type schema** | §9 |
| 12 | "span-only F1" read as a type-agnostic measure | `span_only` re-projects spans through the model's label map. It equals all-span F1 for **42 of 54** runs and *falls* for broad models (`hunflair2` BC5CDR 0.7739 → 0.6819; `pubtator3` 0.9009 → 0.7935). No type-agnostic number in the suite is cross-model comparable | §2.3 |

**Arithmetic status after the correction.** All **1,186** reported values across the 54 runs reproduce
exactly from the prediction files under the project's own matching code — **0 mismatches, 0 missing**.
The benchmark's defects are interpretive and structural, not computational.

**Additions this file did not have.** `NER_BENCHMARK_CORRECTIONS.md` (the correction itself),
`NER_TYPE_COVERAGE_MATRIX.csv` (14 CDM types + `ENTITY`), `NER_RECOMPUTATION_CHECK.csv` (1,407 rows),
`NER_MODEL_DEPLOYABILITY.csv` (27 configurations), `NER_RECOVERED_PROMPTS.md`,
`NER_RETROSPECTIVE_SEAL.sha256`, and `NER_REPRODUCIBILITY_GAPS.md` (a 12-item gap register).

---

## 6a. Amendment record — 2026-11-05

*[added by `CQA-I-AMEND-2026-11-05-1`; the body of this report above is preserved as written, with
in-place `*[superseded 2026-11-05]*` markers pointing here]*

### `CQA-I-AMEND-2026-11-05-1` — the grounding-circularity premise was wrong; the real defect is column mixing and two unreported denominators

- **Date:** 2026-11-05
- **Type:** audit reporting defect (`AUDIT_CORRECTION`) plus one **newly stated** methodological
  limitation. **No** data defect, **no** frozen artefact changed, **no** metric recomputed, and
  **no rating changed**: Grounding stays **ADEQUATE**, and `CQA-I-06` stays **MODERATE**.
- **Reproducer:** `diagnostics/cqa_i_grounding.py` → `diagnostics/results/cqa_i_grounding.json`,
  new in this amendment.

#### A. `CQA-I-06` asserted a mechanism that does not exist
- **Was:** the issue was titled *"Corpus grounding is measured against the project's own terms, so it
  is partly circular"*, with the evidence *"Grounding = share of extracted surfaces that match a
  `canonical_term`"* and the conclusion *"measures inter-model consistency with the project's
  vocabulary, not correctness."*
- **Why it is wrong:** `src/scripts/ner_fair_bench/corpus_bench.py:build_lexicon()` assembles every
  lexicon from **downloaded external references** — `Homo_sapiens`/`Mus_musculus` `gene_info.gz`
  (NCBI Gene), `CTD_diseases.tsv.gz` (CTD/MEDIC), `CTD_chemicals.tsv.gz` (CTD), OMOP `CONCEPT.csv` +
  `CONCEPT_SYNONYM.csv` filtered to Mondo/HPO, and NCBI `names.dmp` (NCBI Taxonomy). The module
  docstring says "from the downloaded references only", `LEX = OUT / "lexicon"`, and the source
  contains **no** occurrence of `canonical_term`. Verified mechanically, not by reading:
  `cqa_i_grounding.json:lexicon_provenance.source_mentions_canonical_term_layer = false`,
  `n_sources_not_cited_in_source = 0`.
- **Own internal contradiction:** this file's own §6 row 6 and `NER_BENCHMARK_CORRECTIONS.md` §9
  already stated the claim was **Wrong** — but the issue block and the register row built from it were
  never amended, so the audit shipped a finding its own correction doc contradicted. That is the
  defect this amendment fixes.
- **Corrected:** retitled to *"The grounding column mixes three unlike measures and one of them is not
  a vocabulary lookup"*, with the superseded title/evidence/impacts retained under markers and a
  "Corrected finding" block carrying the replacement analysis.

#### B. The replacement finding, stated with its denominators
1. **Four of six types are genuine external-vocabulary lookups** — `ChemicalEntity`,
   `DiseaseOrPhenotypicFeature`, `GeneOrGeneProduct`, `OrganismTaxon`: **95 of 117** cells. These are
   legitimate Tier-2 precision proxies and the circularity charge is withdrawn for them.
2. **`SequenceVariant` (16 cells) is a regex, not a lookup.** `ground()` returns `{"PATTERN"}` when
   `VARIANT_RE.match(s)` succeeds. Pooled **1,257 / 50,249 unique strings = 2.5%**; per-model range
   1.0% (`llm_deepseek_fs`) to 10.7% (`llm_gemma_fs`). It measures *variant-shaped surface text*, not
   variant existence — a fabricated `rs` id scores identically to a real one.
3. **`CellLine` (19 cells) is definitional 0.0%.** `ground()` returns `set()` unconditionally for that
   type; all 19 zero cells in the run are CellLine and **no other cell is 0.0%**
   (`zero_cells_all_CellLine = true`). It is a missing vocabulary, not a model outcome.
4. **The denominator is distinct strings, never mentions.** `llm_qwen_fs` `OrganismTaxon` is 15.1% of
   **9,113 distinct strings** over **54,139 mentions**. A verbose model that emits many near-duplicate
   surfaces is penalised on inventory, not on occurrences.
5. **`other_type_pct` is shipped and unreported.** The share of a model's strings that ground in a
   *different* type than predicted reaches **19.1%** (`llm_qwen_fs` `GeneOrGeneProduct`) and exceeds
   10% in 9 cells. Neither this report, the manuscript, nor `FIGURE_PLAN.md` figure 5 has ever shown
   it — so the grounding column is **type-blind about the error class that dominates the LLMs**.

#### C. Two counts corrected in passing
- **Affected line `26 configurations` → `25`.** 26 configurations ran; **25** carry a grounding block.
  `scispacy_lg` (untyped, generic `ENTITY`) has none, so 117 cells come from 25 configurations, not 26.
  `117` itself is unchanged and reproduces exactly.
- **The dimension table now names the external lexicons** rather than "the CDM vocabulary".

#### D. What this amendment does *not* do
- It does **not** raise or lower any rating. Grounding remains **ADEQUATE**; the component verdict in
  §7 is unchanged; `CQA-I-06` remains **MODERATE**, because "one of three sub-measures is a regex and
  two denominators are suppressed" is a moderate methodological limitation, not a critical one.
- It does **not** claim the manuscript is wrong. `01_methods_and_resource.md:148` already says
  "precision proxies, not accuracy" and names the external vocabularies; `03_discussion.md:26` already
  cites them. The manuscript's *framing* is correct — the exposure is confined to the figure as
  planned in `FIGURE_PLAN.md:11` and to the sentence at `02_results.md:108`, which reads a grounding
  rate as an invention rate.
- It does **not** touch the retrospective seal. `NER_RETROSPECTIVE_SEAL.sha256` deliberately excludes
  the three narrative files that describe it, and this report is one of them, so no reseal is required.
  Re-verification after this edit: see `19_AUDIT_REPRODUCIBILITY.md`.

---

## 7. Component verdict

This is the **best-executed component in the audit on method** and the **most dangerous one to
quote**. The protocol is honest: same splits, both match regimes, in-domain advantages flagged, CIs
and p-values everywhere, `n/a` where a model cannot emit a type, and an explicit refusal to rank
across corpora when the CIs overlap.

The danger is entirely in the transfer. The suite optimizes chemical-and-disease mention finding on
PubMed abstracts; the CDM's content is taxa, methods, body sites and generic entity strings in
full-text sections. **Nine of the fourteen CDM types (41.90% of typed terms) have no benchmark
counterpart at all**, three more have only an approximate one, and the single largest label in the
corpus (`ENTITY`, 55.29% of all terms) is not a schema type and cannot be benchmarked by any typed
corpus. A 90.1 F1 heading the table belongs to a curated database that the section pipeline cannot
run. The corpus-side substitutes — 41.3% grounding, 36.5% KG support of 137 edges — are consistency
measurements with denominators too small to carry the inference a reader will want to make.

So the component's verdict is conditional: **excellent as a model-selection study, unusable as a
corpus-accuracy result**, and the manuscript must keep those two sentences apart at the cost of
repeating itself.

**After the 2026-11-04 amendment, the verdict holds and one rating moves.** Reproducibility is raised
from **WEAK** to **ADEQUATE** — all 1,186 reported values were recomputed with zero mismatches, the
checkpoints are identifiable from the job logs, the prompts were recovered and verified, and a dated
retrospective seal now covers the artefact set. It does not become STRONG: there is **no
preregistration**, run-time library versions are unrecorded, and the LLM prediction files delete
off-schema entities before writing, so the type-agnostic comparison has no independent measurement for
LLMs. **Coverage of the CDM's own types stays CRITICAL** (2 direct / 3 approximate / 9 none, with
`ENTITY` outside the schema), and **Interpretability stays WEAK** — the top BC5CDR row is a
non-deployable curated resource and must be presented as a reference ceiling, never as the pipeline's
winner. No other rating changes, and no averaged score is computed.
