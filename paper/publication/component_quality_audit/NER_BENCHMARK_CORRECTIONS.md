# Component I — NER Benchmark: Methodological Correction

**Amendment date:** 2026-11-04
**Amends:** `09_NER_BENCHMARK_QUALITY.md` (component I of the component quality audit)
**Object of the correction:** `outputs/results/benchmark/ner_fair_bench/` (54 prediction files, 27
configurations × BC5CDR + BioRED), `outputs/results/benchmark/ner_corpus_bench/` (26 configurations
over the 453-paper corpus, BioRED type schema), and the audit's own component-I report.

**What this correction did:** re-derived every reported benchmark metric directly from the 54 shipped
prediction files using the project's own matching code, rebuilt the CDM↔benchmark type crosswalk from
the frozen terminology layer, verified the training-exposure flags, recovered the LLM prompts and
few-shot examples, separated deployable from reference-only systems, and sealed the artefact set with
a dated SHA-256 manifest.

**What this correction did not do:** no NER extraction was re-run, no prediction file was modified,
`fair_ner_metrics.json` and `FAIR_NER_BENCHMARK.md` were not touched, no frozen release or scientific
release was altered, and no model was re-scored for publication. Every new number is an *audit-time
derivation* written only under `paper/publication/component_quality_audit/`.

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Verify BC5CDR/BioRED → 14 CDM types; direct vs approximate; Species vs ORGANISM | **RESOLVED** — 2 direct, 3 approximate, 9 none; ORGANISM transfer measured and found inadequate | §1, `NER_TYPE_COVERAGE_MATRIX.csv` |
| 2 | Reconcile "five microbiome-specific types" vs "six unbenchmarked" | **RESOLVED** — the earlier list was wrong; there are no microbiome-specific CDM types, and 9 (not 6) types have no benchmark counterpart | §1.4 |
| 3 | Full-schema F1 for models that cannot emit all labels; N/A; span-only vs typed | **RESOLVED** — supported-schema F1 added; `span_only` shown not to be span-only; N/A policy applied | §2, `NER_RECOMPUTATION_CHECK.csv` |
| 4 | Verify training status/data exposure of every † model; name leakage | **RESOLVED** — 7 flagged runs audited; split leakage measured at 0; one annotation-source contamination confirmed | §3 |
| 5 | Recompute metrics from the 54 prediction files; report discrepancies | **RESOLVED** — 1,186 reported values recomputed, **0 mismatches**, 0 missing; 152 new values added | §4 |
| 6 | Dated SHA-256 manifest, labelled retrospective | **DONE** — 126 files, ≈3.57 GB, verifies 126/126 | §5, `NER_RETROSPECTIVE_SEAL.sha256` |
| 7 | Recover exact prompts and few-shot examples | **RECOVERED AND VERIFIED** — all 12 shot-runs match recorded metadata | §6, `NER_RECOVERED_PROMPTS.md` |
| 8 | Separate deployable from reference-only; never recommend a non-deployable winner | **DONE** — PubTator3 reclassified as reference ceiling | §7, `NER_MODEL_DEPLOYABILITY.csv` |
| 9 | Reassess model-selection claims | **DONE** — explicit statement that public F1 does not select a microbiome full-text extractor | §8 |
| 10 | Preserve the four evidence tiers | **DONE** — restated and applied | §9 |

---

## 1. Type mapping: what the benchmarks actually cover (items 1 and 2)

### 1.1 The two schemas are not the CDM's schema

`fairbench.py` scores each model **in the benchmark's own type space**:

* BC5CDR: `Chemical`, `Disease` — 2 types.
* BioRED: `GeneOrGeneProduct`, `DiseaseOrPhenotypicFeature`, `ChemicalEntity`, `OrganismTaxon`,
  `SequenceVariant`, `CellLine` — 6 types.

The CDM's `CDM_TYPES` has **14**. Nothing in either benchmark uses a CDM type name; the correspondence
is a semantic judgement, and it exists in two very different strengths.

### 1.2 The crosswalk, verified against the frozen terminology layer

`NER_TYPE_COVERAGE_MATRIX.csv` carries one row per CDM type with the live term count, the
corresponding benchmark type(s), the correspondence class, the best measured per-type exact F1, and a
semantic note. Summary:

| Correspondence | CDM types | Live terms | Share of typed terms |
|---|---|---:|---:|
| **DIRECT** | CHEMICAL, DISEASE | 16,543 | **22.78%** |
| **APPROXIMATE** | ORGANISM, PROTEIN, CELL_TYPE | 25,646 | **35.32%** |
| **NONE** | DNA_RNA, GENOMICS, PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, STUDY_DESIGN | 30,421 | **41.90%** |
| **(not a CDM type)** | `ENTITY` | 89,799 | 55.29% of *all* terms |

Denominator for the shares is the **72,610** live terms that carry a CDM type. A further **89,799**
terms (55.29% of all 162,409) carry the off-schema label `ENTITY`, for which no typed benchmark can
exist at all — the only available measurement is untyped span F1.

The three approximate correspondences fail in three different ways, and each failure is measured:

* **PROTEIN ← GeneOrGeneProduct** is a *superset* mismatch. GeneOrGeneProduct covers genes, mRNAs and
  protein families; the CDM splits the same region of meaning across PROTEIN and DNA_RNA. A benchmark
  hit therefore does not determine the correct CDM type. Best measured F1 on the covering type:
  **0.8326** (`hunflair2`).
* **CELL_TYPE ← CellLine** is a *category* mismatch. An immortalised line (HeLa, HEK293) is a reagent;
  a cell type (enterocyte, T cell) is an anatomical class. `fairbench.py`'s own comment records the
  distinction — "cell type != cell line" — and maps anyway because there is no better slot. Best
  measured F1 on CellLine: **0.8077** (`pubtator3`), which says nothing about CDM CELL_TYPE.
* **ORGANISM ← OrganismTaxon** is a *distribution* mismatch. It is the largest gap in the suite and is
  treated separately below.

### 1.3 Species vs ORGANISM — measured, not argued

The label correspondence is sound: `TYPE_DEFS["OrganismTaxon"] = "organisms and species, including
common names such as human, mouse or patients"`, and a bacterial species *is* an organism taxon. The
**instances** do not correspond, and this is now quantified rather than asserted:

| Quantity | Value |
|---|---:|
| BioRED test `OrganismTaxon` gold mentions | **393** |
| …host-generic (`patients`, `mice`, `rats`, `human`, `women`, `man`, …) | **357 (90.8%)** |
| …viral (`rsv`, `hcv`, `hbv`, `hiv`, `hepatitis c virus`, …) | **27 (6.9%)** |
| …other non-host species (`zebrafish`, `arabidopsis`, `tobacco`, `chinese hamster`) | **9 (2.3%)** |
| …**bacterial taxa** | **0** |
| Same composition in the BioRED *train* split (1,429 mentions) | host 1,307 / viral 46 / other 76 / bacterial 0 |
| CDM `ORGANISM` live terms | 12,026 |
| …matching a microbial-name pattern (heuristic) | 3,827 (31.8% of terms, 53.6% of the mention rollup) |
| …top CDM ORGANISM terms by mention | `microbiota` 20,785 · `gut microbiota` 15,667 · `bacteroides` 6,040 · `firmicutes` 5,257 · `bifidobacterium` 4,616 |
| BioRED `OrganismTaxon` surfaces that exist as CDM ORGANISM terms | 9 of 25 surfaces / 181 of 393 mentions (46.1%) — all host terms plus `rsv` |

So the two layers overlap on the words that are *host* words, and not on the words the CDM exists to
capture. The consequence is measurable in the benchmark itself. Restricting BioRED `OrganismTaxon`
gold to the **36 non-host mentions** (27 viral + 9 other, spread over 10 documents) and scoring
recall exactly — a measurement this audit added, flagged as small-n:

| Model | Recall on all 393 OrganismTaxon | Recall on the 36 non-host mentions [95% Wilson] | Best measured OrganismTaxon F1 |
|---|---:|---:|---:|
| `hunflair2 †` | 0.744 (recall, full-schema) | **20/36 = 0.556 [0.396–0.705]** | **0.9441** |
| `pubtator3 †` | 0.760 | 23/36 = 0.639 [0.476–0.775] | 0.8050 |
| `gliner_v25_biomed †` | — | 21/36 = 0.583 [0.422–0.729] | 0.3971 |

> *[superseded by `CQA-I-AMEND-2026-11-04-1` — `NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md`]* The
> column headed "Recall on all 393 OrganismTaxon" holds **full-schema 6-type micro recalls**, not
> per-type `OrganismTaxon` recalls (true values: `hunflair2` 0.9237, `pubtator3` 0.8142). The
> `gliner_v25_biomed` F1 cell reads 0.3971, which is `biored · bert_disease · span_only_relaxed_F1`;
> the correct per-type value is 0.4238. The values in the first two rows of the third column are
> unchanged and correct. See the amendment for the corrected table and the any-type sensitivity column.
| `scispacy_bionlp13cg` | — | 18/36 = 0.500 [0.345–0.655] | 0.7376 |
| `gliner_v25_medium` | — | 11/36 = 0.306 [0.180–0.469] | 0.4726 |
| `llm_qwen_fs` | — | **33/36 = 0.917 [0.782–0.971]** | 0.4241 |
| `llm_gemma_zs` | — | 8/36 = 0.222 [0.117–0.381] | — |
| `llm_deepseek_fs` | — | 6/36 = 0.167 [0.079–0.319] | — |

The model that scores 0.9441 on the benchmark's target type drops to **0.556** recall once host terms
— the 90.8% majority — are removed, and the 3-shot Qwen model, which scores 0.4241 on the full type,
recovers **0.917** of the non-host mentions. The two Wilson intervals do not overlap. This is a
~~35-mention-versus-36-mention~~ *36-mention-versus-36-mention* comparison *[superseded typo, corrected
by `CQA-I-AMEND-2026-11-04-1`]* and must be reported with its denominator, but the direction
is unambiguous: **a high OrganismTaxon F1 measures host and virus recognition, not microbial taxon
recognition.** Anyone using 0.9441 as evidence that a model finds gut taxa is reading the wrong
denominator.

### 1.4 Resolving the "five microbiome-specific types" / "six unbenchmarked" discrepancy

The superseded report listed `ORGANISM, MICROBIOME, LAB_METHOD, DATA_ANALYSIS, DIET, HABITAT` as "the
five microbiome-specific types" with no benchmark, and separately stated "BC5CDR 2/14, BioRED 6/14".
Both statements were wrong, in three distinct ways:

1. **`MICROBIOME`, `DIET` and `HABITAT` are not CDM types.** They do not appear in
   `src/cdm_pipeline/config.py:CDM_TYPES`. The claim invented three schema members. The six-name list
   contained three real types (`ORGANISM`, `LAB_METHOD`, `DATA_ANALYSIS`) and three non-types.
2. **`ORGANISM` is not unbenchmarked.** BioRED `OrganismTaxon` corresponds to it — approximately, and
   inadequately (§1.3), but not "not at all".
3. **The correct count of wholly unbenchmarked CDM types is nine, not six**: DNA_RNA, GENOMICS,
   PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, STUDY_DESIGN.

The corrected statement, which should replace both: *the CDM has 14 types. Two are directly
benchmarked (CHEMICAL, DISEASE, 22.78% of typed terms). Three have an approximate benchmark
correspondence that does not transfer (ORGANISM, PROTEIN, CELL_TYPE, 35.32%). Nine have no benchmark
correspondence at all (41.90%), and the single largest label in the corpus — `ENTITY`, 55.29% of all
terms — is not a schema type and cannot be benchmarked by any typed corpus.*

### 1.5 A typing observation this correction inherits rather than resolves

The CDM `ORGANISM` layer contains `microbiota` and `gut microbiota` as its two highest-mention terms.
A microbiota is a community, not an organism. Whether that is a typing error is a component-C
question, not a component-I question; it is recorded here because it means the 12,026-term ORGANISM
denominator is itself partly "microbiome concept" rather than "taxon", which further weakens any
attempt to read a taxon benchmark onto it.

---

## 2. Full-schema F1, supported-schema F1, and what "span-only" actually measures (item 3)

### 2.1 The problem with the headline number

`full_schema` is `micro(docs, pred, TYPES[ds])` — a micro-average over **every** type in the dataset.
A model that cannot emit a type contributes `fn` for every gold mention of that type and `0` for
precision, so its F1 is capped by its label inventory, not by its skill. The `per_type` table already
shows `n/a` for those types; the headline does not. On BioRED, **14 of 27 configurations cannot emit
all six types**, and three can emit only one.

### 2.2 Adding a supported-schema F1 (new, audit-only)

`NER_RECOMPUTATION_CHECK.csv` adds `supported_schema_exact_F1` — micro over `fb.supported(name, ds)`,
i.e. only the types a configuration can actually emit — with a document-bootstrap CI.

| Dataset | Model | types it can emit | full-schema F1 | supported-schema F1 | gap |
|---|---|---:|---:|---:|---:|
| BioRED | `bert_chemical` | 1 / 6 | 0.2893 | **0.8117** | **+0.522** |
| BioRED | `bert_disease` | 1 / 6 | 0.3613 | **0.8606** | **+0.499** |
| BioRED | `bert_genetic` | 1 / 6 | 0.3633 | 0.7194 | +0.356 |
| BioRED | `scispacy_bc5cdr` | 2 / 6 | 0.4133 | 0.6482 | +0.235 |
| BioRED | `scibert_jnlpba` | 2 / 6 | 0.2744 | 0.4886 | +0.214 |
| BioRED | `scispacy_jnlpba` | 2 / 6 | 0.2290 | 0.4388 | +0.210 |
| BioRED | `scispacy_craft` | 3 / 6 | 0.3411 | 0.4510 | +0.110 |
| BioRED | `hunflair2` | 5 / 6 | 0.8062 | 0.8371 | +0.031 |
| BC5CDR | `bert_disease` | 1 / 2 | 0.5379 | 0.8545 | +0.317 |
| BC5CDR | `bert_chemical` | 1 / 2 | 0.6424 | 0.9137 | +0.271 |
| BC5CDR | `scispacy_craft` | 1 / 2 | 0.2335 | 0.3698 | +0.136 |

**`bert_disease` is the clearest case.** It scores 0.3613 on BioRED under full-schema and **0.8606**
on the one type it emits — a 0.50 gap that is entirely schema coverage. Reporting only the first number
as "model quality" is indefensible; reporting only the second as "model quality" is equally
indefensible, because a one-type model is being scored on its own terms.

**Rule adopted.** `full_schema` answers *"how well does this configuration cover this annotation
schema?"* — legitimate for choosing a general-purpose extractor. `supported_schema` answers *"how well
does it do on what it claims to do?"* — legitimate for characterising a specialist. **Neither is
comparable across models with different label inventories**, and the only fully comparable unit is the
**per-type F1**, which is why the matrix is built from per-type numbers:

| Benchmark type | Best exact F1 | Model |
|---|---:|---|
| `OrganismTaxon` | 0.9441 | `hunflair2` — but see §1.3; 0.556 on non-host mentions |
| `Disease` (BC5CDR) | 0.9213 | `pubtator3` |
| `Chemical` (BC5CDR) | 0.9137 | `bert_chemical` |
| `ChemicalEntity` | 0.8881 | `pubtator3` |
| `DiseaseOrPhenotypicFeature` | 0.8657 | `hunflair2` |
| `GeneOrGeneProduct` | 0.8326 | `hunflair2` |
| `SequenceVariant` | 0.8228 | `pubtator3` |
| `CellLine` | 0.8077 | `pubtator3` |

### 2.3 `span_only` is *not* span-only, and the difference is material

`span_only` in `fairbench.py` is computed as:

```python
spans = [(p, sorted({(int(x["start"]), int(x["end"]), "SPAN") for x in ps
         if name == "scispacy_lg" or project([(p, [x])], name, ds)[0][1]})) for p, ps in raw]
```

Every span is re-projected through the model's own label map and **kept only if its label maps into
the dataset schema**. So the shipped `span_only` is "type-agnostic matching over spans the model can
score", not "span detection". Two consequences:

1. **For LLMs it is exactly equal to all-span F1**, because `run_llm()` drops off-schema entities
   *before writing the prediction file*. The audit computed an all-span F1 (`span_all_exact_F1`,
   new) and found it identical to `span_only` for **42 of 54** runs — every LLM and every
   all-type-supporting model. The 12 runs where it differs are exactly the trained models whose raw
   label sets exceed the schema.
2. **For broad trained models, including the extra classes *lowers* the number.** `hunflair2` on
   BC5CDR: `span_only` 0.7739, `span_all` **0.6819** (−0.092) because its ORGANISM/PROTEIN/CELL_TYPE
   spans become false positives. `pubtator3` on BC5CDR: 0.9009 → 0.7935 (−0.107). `scispacy_bionlp13cg`:
   0.4910 → 0.3772 (−0.114). Conversely, three models that could not be scored at all rise from 0.0
   to 0.013–0.028 because their gene/protein spans occasionally hit a gold offset.

So no type-agnostic number in this suite is comparable across models: it depends on how many
irrelevant entity classes the model volunteers. **`scispacy_lg`'s 30.3 / 38.3 span-only is the one
clean case** (it emits nothing but `ENTITY`, so `span_only == span_all`), and it is precisely the case
where it is the only thing that can be measured.

### 2.4 N/A policy applied

* **Unsupported type, no computation possible** → `n/a` in the type table, and the type still counts
  as a miss in `full_schema`. This is the shipped behaviour and it is correct as long as the caption
  says so.
* **Model with no typed label at all** (`scispacy_lg`) → `full_schema` is reported as **0.0 by
  construction**, not as a measurement. It must be printed as `n/a (untyped)` in any table that
  compares it to typed models, with its span-only number beside it. The shipped report prints `0.0`
  and relies on a footnote; the footnote must become part of the cell.
* **Metric not computable for the model** (`chem_dis` when a model lacks one of the two types) → `n/a`,
  and this is already the shipped behaviour (69 `N/A` rows in the check CSV).

---

## 3. Training status and data exposure (item 4)

### 3.1 What the flag means

`IN_DOMAIN = {scispacy_bc5cdr, bert_chemical, pubmedbert, bert_disease, hunflair2, pubtator3,
gliner_biomed, gliner_v25_biomed}` with per-corpus lists; `in_domain_training` is set when the
dataset is in that model's list, and the `†` marker in the report is exactly that boolean. Of the
eight names, **six appear among the 54 runs** (`pubmedbert` and `gliner_biomed` are not among the 27
scored configurations — the registry defines them but they were not run here).

| Run(s) | Exposure claimed by `†` | What the artefacts show | Split leakage |
|---|---|---|---|
| `bc5cdr__scispacy_bc5cdr` | BC5CDR | `en_ner_bc5cdr_md`; trained on the BC5CDR **train** split | none — test∩train = **0** PMIDs |
| `bc5cdr__bert_chemical` | BC5CDR | BioBERT chemical NER on BC5CDR train | none |
| `bc5cdr__bert_disease` | BC5CDR | BioBERT disease NER on BC5CDR train | none |
| `bc5cdr__hunflair2` | BC5CDR | HunFlair2, trained on 8 corpora including BC5CDR | none |
| `bc5cdr__gliner_v25_biomed` | BC5CDR | biomedical GLiNER checkpoint, PubMed-derived | none |
| `bc5cdr__pubtator3`, `biored__pubtator3` | BC5CDR **and** BioRED | Precomputed PubTator3 API output over the resource's own indexed collection | **not applicable — see §3.3** |
| all 12 `llm_*` runs | *(not flagged)* | 3-shot examples drawn from the official train split | none — shots ∈ train, 0 of 3 in test, 0 in dev |
| 8 `gliner*` runs | *(not flagged except two)* | zero-shot; GLiNER threshold tuned on the **dev** split, grid 0.3–0.7 | dev-only, 5-point grid |

**Split leakage is zero and this was measured, not assumed:** `test ∩ train = 0` and `test ∩ dev = 0`
PMIDs for both corpora, and the three recovered few-shot PMIDs for each corpus are all in the train
split (`bc5cdr`: 12523465, 7053303, 12695819; `biored`: 19918264, 20533999, 20722491).

### 3.2 What the `†` flag does *not* capture

The flag is a boolean per (model, dataset). It cannot express four distinct exposure classes, and this
is the substantive correction to the earlier report, which treated `†` as "trained on this corpus"
and stopped there:

1. **Training-set reuse** (`scispacy_bc5cdr`, `bert_*`, `hunflair2`, `gliner_v25_biomed`) — the flag
   is accurate. The test split is still disjoint, so these are legitimate but in-domain results, and
   comparing them to a zero-shot model without the flag is a category error the report does label.
2. **Annotation-source contamination** (`pubtator3`) — see §3.3. This is stronger than training-set
   reuse and the flag understates it.
3. **Dev-set tuning** (8 GLiNER runs) — a 5-point threshold grid chosen on dev. Small exposure,
   fully disclosed in `_meta` (`threshold_split: dev`, `dev_f1_by_threshold`), but the corpus run then
   *reuses* the BioRED-dev threshold (`corpus_bench.public_threshold`). Not leakage of test data;
   it is dev reuse across corpora and should be said.
4. **Unmeasurable pretraining contamination** (12 LLM runs) — every LLM here was pretrained on
   web-scale text that certainly contains PubMed abstracts, possibly including BC5CDR/BioRED PMIDs.
   Nothing in the artefacts can bound this. It must be declared as unmeasurable, not assumed absent.

### 3.3 PubTator3: annotation-source contamination, not in-domain training

`pubtator3` is not a model trained on BC5CDR; it is the NCBI annotation resource from which
BC5CDR's curation lineage descends, serving annotations for PMIDs in its own index
(`docs_found: 500/500` for BC5CDR). The shipped `†` calls this "in-domain training", which is the
wrong mechanism. What can be measured:

* `bc5cdr__pubtator3`: P 0.9142, R **0.8879**, F1 0.9009 (8,709 tp / 817 fp / 1,100 fn).
* `biored__pubtator3`: P 0.8076, R 0.7601, F1 0.7832.
* Its raw output on BC5CDR PMIDs includes **2,008 `Species`**, 571 `Gene`, 58 `CellLine` — i.e. it is
  emitting the full PubTator type set on BC5CDR documents, not just the two BC5CDR types.

**Reading.** Recall of 0.8879 means at most 88.8% of BC5CDR gold is reproduced verbatim by the
resource, so the served annotations are not a byte copy of the gold file — but 88.8% of the gold *is*
reproduced by the resource that generated the annotation ecosystem the gold lives in. The 0.9009 is
therefore an **upper bound set by a curated resource**, not an independent model measurement. It must
never appear in the same ranking as runnable models without that sentence (see §7).

### 3.4 An exposure risk the flag misses and the audit cannot quantify

BioRED's entity layer derives from the PubTator annotation stack (the resource pre-annotated entity
mentions, which were then curated), and PubTator's taggers were trained on BC5CDR and related
corpora. If so, a model trained on BC5CDR is **not fully out-of-domain on BioRED's disease / chemical
/ gene / cell-line types**, even though `IN_DOMAIN` does not flag it. This would matter because
`hunflair2` — best on BioRED at 0.8062 — is exactly such a model.

This is recorded as a **risk, not a confirmed defect**: the claim about BioRED's construction is a
property of the published resource, not something documented inside this repository, and no artefact
here lets the audit measure the overlap. The correct handling is to state it in the limitations and to
avoid describing `hunflair2`'s BioRED result as fully out-of-domain either way.

---

## 4. Recomputation from the 54 prediction files (item 5)

**Method.** `diagnostics/cqa_ner_recompute.py` imports `fairbench.py` itself and calls `fb.load`,
`fb.project`, `fb.counts`, `fb.agg`, `fb.boot`, `fb.micro` — the project's own matching rules, not a
re-implementation — over `outputs/results/benchmark/ner_fair_bench/preds/*.jsonl`. Gold is re-verified
against the text on load (`load()` raises if any gold offset does not match). Tolerance 1e-12.

**Result (1,407 rows in `NER_RECOMPUTATION_CHECK.csv`):**

| Verdict | Rows | Meaning |
|---|---:|---|
| `MATCH` | **1,186** | Reported value reproduced exactly |
| `MISMATCH` | **0** | — |
| `MISSING_IN_JSON` | **0** | — |
| `N/A` | 69 | Metric undefined for that model (e.g. `chem_dis` when a model lacks a type) |
| `NEW` | 152 | 49 supported-schema F1 + 49 supported-schema CI + 54 all-span F1 |

**What was covered by the 1,186 matches:** for all 54 runs — full-schema exact F1/P/R/tp/fp/fn,
relaxed F1, both CI bounds, span-only exact and relaxed F1, `chem_dis` where defined, per-type exact
F1 and both per-type CI bounds for every supported type, and the identity of `best_on_dataset`.

**Conclusion: the shipped metrics are arithmetically sound.** There is no discrepancy between
`fair_ner_metrics.json`, `FAIR_NER_BENCHMARK.md` and the prediction files. The benchmark's problems
are interpretive and structural, not computational — which is precisely why a recomputation that only
checks arithmetic would have found nothing wrong with it.

**What was *not* recomputed, and why:** `p_vs_best`. It is a paired-bootstrap test statistic over
2,000 resamples per pair, not a metric; recomputing it would confirm the same code path already
validated by the CI recomputation. It is quoted in this report as *reported*, with that provenance.

**Structural discrepancies that the arithmetic check cannot see** (all corrected in this document):

1. The headline `full_schema` F1 conflates label coverage with skill (§2.1–2.2).
2. `span_only` is not type-agnostic over emitted output (§2.3).
3. `†` conflates four exposure mechanisms and misses one entirely (§3.2–3.3).
4. The ranked table's top BC5CDR row is not a runnable model (§7).

---

## 5. Provenance seal (item 6)

`NER_RETROSPECTIVE_SEAL.sha256` — **126 files, 3,574,150,615 bytes**, sealed **2026-11-04T16:48:22+0100**,
sha256sum-format with paths relative to the repository root, verifying **126/126 OK**.

Coverage: the 54 fair-benchmark and 26 corpus-benchmark prediction files + the 7,161-chunk corpus
manifest + the metrics, reports and config files + `fairbench.py`, `corpus_bench.py` and the three
launchers + the nine gold-data files including `SHA256SUMS` + the recovered prompts and the recomputation
outputs (`NER_RECOMPUTATION_CHECK.csv`, the deployability and type-coverage tables, the LLM run
diagnostics, the ORGANISM transfer probe) + **the twelve external reference inputs the corpus scorer
reads** (≈2.5 GB: NCBI `names.dmp`/`nodes.dmp`, five CTD files, two `gene_info` files, Disbiome, OMOP
`CONCEPT.csv` and `CONCEPT_SYNONYM.csv`) + `sections.jsonl`, the JSONL that defines the 7,161 chunks.

**Deliberately not sealed:** the three audit narratives that describe the seal (`NER_BENCHMARK_CORRECTIONS.md`,
`NER_REPRODUCIBILITY_GAPS.md`, `09_NER_BENCHMARK_QUALITY.md`). Hashing a document that quotes the
manifest's own byte count is self-referential — every edit would invalidate the manifest it describes.
The exclusion is recorded in `diagnostics/results/ner_environment.json` under `not_sealed`. No result
file, prediction file, metric file or input is excluded.

**Post-seal amendment (`2026-11-04`):** `NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md` and
`diagnostics/cqa_ner_organism_probe.py` / `diagnostics/results/ner_organism_probe.json` were written
after the seal and are likewise not hashed; they describe and re-derive the same sealed inputs. The
manifest was re-verified after the amendment — **126/126 OK**, no digest altered.

**This is retrospective provenance sealing, not preregistration.** It was computed after every result
already existed and it constrains nothing. What it establishes: the files this management audit read
are the files that exist now, and a reviewer can prove that. What it does not establish: that any
analysis choice was fixed in advance. The project's Tier-2 and Tier-3 runs ship genuine
`PREREGISTRATION.sha256` files; **the Tier-1 benchmark does not, and this seal cannot substitute for
one.**

Verify from the repository root:

```bash
sha256sum -c paper/publication/component_quality_audit/NER_RETROSPECTIVE_SEAL.sha256
```

---

## 6. Prompts and few-shot examples (item 7)

**Status: recovered and verified — not "incompletely reproducible".** `llm_system(ds)` and
`fewshot(ds, k=3, seed=0)` are deterministic functions in the shipped scoring code, so the exact
message lists can be reconstructed without re-running anything. Full record:
`NER_RECOVERED_PROMPTS.md`; machine-readable: `diagnostics/results/ner_recovered_prompts.json`.

The recovery is **verified rather than asserted**: the PMIDs of the three few-shot documents
reconstructed from `fewshot()` match `fewshot_train_pmids` recorded in `_meta` of all **12** 3-shot
prediction files, for both corpora. The system prompts are 550 characters (BC5CDR) and 879
characters (BioRED); the shot blocks are 4,312 and 6,298 characters.

Decoding: temperature 0.6 / max_tokens 10,000 / no `response_format` for `deepseek` (a reasoning
model); temperature 0 / max_tokens 8,000 / `response_format: json_object` for the other five;
`enable_thinking: false` for qwen and gemma; `seed: 0`; three retries on exception.

**Mistral's special case is a real prompt difference, not a footnote.** `NO_SYSTEM_ROLE = {"mistral"}`
means the system text is concatenated as `<system>\n\n<first message>` into the first message. In
3-shot mode that first message is a few-shot *user* turn, so Mistral's first user message carries the
system prompt *and* the first example. Any cross-model `_fs` comparison includes this asymmetry.

**What remains unrecoverable, and is therefore marked as a gap rather than claimed:** the vLLM build,
serving flags, tokenizer revision, GPU driver and library versions (only `device: "1x A40 (vLLM)"` is
recorded), and therefore exact response reproducibility — vLLM is not bit-deterministic across builds
even at `temperature=0`. See `NER_REPRODUCIBILITY_GAPS.md` for the itemised list.

---

## 7. Deployable extractors vs reference-only systems (item 8)

`NER_MODEL_DEPLOYABILITY.csv` classifies all 27 configurations on evidence rather than on the `kind`
string:

| Class | n | Configurations | Basis |
|---|---:|---|---|
| **YES — section-level** | 25 | all trained NER + 8 GLiNER + 12 LLM | Ran on the 453-paper corpus (every section except References/Acknowledgements, 7,161 chunks / 21,560,603 chars, BioRED type schema) and produced entities in 431–453 papers |
| **NO — reference only** | 1 | `pubtator3` | API lookup by PMID against PubTator3's own index; `predict_text` raises `NotImplementedError`; excluded from section mode in `runner_sections.py`; offsets are abstract/passage geometry, not section offsets; **absent from the 26-configuration section run** |
| **NO — untyped only** | 1 | `scispacy_lg` | Emits one generic `ENTITY` label; cannot produce a CDM type; **0 papers with entities** in the corpus run |

**`pubtator3` is therefore reclassified from "best model on BC5CDR" to "reference ceiling, not a
candidate".** It remains in the table — as an upper bound on what curated NCBI annotation achieves on
its own corpora — but it must not head a candidate ranking and must not be named as the pipeline's
winner.

**The deployable ranking, from the same numbers:**

| | Best deployable | F1 | Caveat |
|---|---|---:|---|
| BC5CDR | `hunflair2` | 0.7735 | in-domain (trained on BC5CDR) |
| BC5CDR, excluding in-domain | `llm_qwen_fs` | 0.6951 | CI overlaps `gliner_v25_medium` 0.6922 |
| BioRED | `hunflair2` | 0.8062 | not flagged, but shares the PubTator annotation lineage (§3.4) |
| BioRED, excluding flagged | `llm_qwen_fs` | 0.6623 | followed by `llm_gemma_zs` 0.6600 |

Runtime on the corpus run, which is what a section-level pipeline actually pays:
`bert_chemical` 165 s, `scispacy_bc5cdr` 268 s, `gliner_v25_medium` 643 s, `hunflair2` 2,211 s (CPU,
8 cores), `llm_qwen_fs` 3,024 s, `llm_llama_zs` 22,528 s (A40). The accuracy ordering and the cost
ordering are not the same, and the cost spread across the deployable set is **≈136×**.

---

## 8. Model-selection claims (item 9)

Restating the boundary explicitly, because the ranked table invites the opposite reading:

> **Public benchmark results do not establish the best extractor for microbiome-specific full-text
> NER.** BC5CDR and BioRED are PubMed abstracts annotated with chemical, disease, gene, variant, cell
> line and organism-taxon mentions. The corpus is 20.9 M characters of segmented full text in which
> the dominant labels are `ENTITY` (55.29%) and ORGANISM taxa (16.6% of typed terms), 90.8% of the
> benchmark's organism-taxon mentions are host terms, and nine of the CDM's fourteen types — 41.9% of
> typed terms — have no benchmark counterpart at all. A ranking on BC5CDR chemical/disease F1 cannot
> rank extractors for that task, and the corpus-side substitutes (external-vocabulary grounding, KG
> support) are coverage measurements with small denominators, not accuracy.

Three specific claims that must not be made:

1. *"Our NER achieves F1 0.90."* — That is PubTator3 on BC5CDR, in-domain, non-deployable.
2. *"The model was chosen because it performs best on the benchmark."* — The best deployable model
   differs by corpus (`hunflair2` on both, but with different caveats), the top BC5CDR row is not a
   candidate, and the type the corpus is built on was never benchmarked on its own distribution.
3. *"The benchmark validates the corpus extraction."* — No gold standard exists for the corpus. The
   only measured corpus property is mechanical: offset exactness 99.9978% (component B).

What *can* be claimed: the suite is a fair, statistically careful comparison of extractors on two
public corpora, that `hunflair2` is the strongest deployable configuration on both under this protocol,
that the 3-shot Qwen configuration is the strongest non-in-domain alternative, and that on the only
benchmark type resembling ORGANISM the ranking **inverts** once host terms are removed (§1.3).

---

## 9. The four evidence tiers, preserved (item 10)

| Tier | What it is | Where it appears in component I | What it can support |
|---|---|---|---|
| **1. Public gold standard** | Human-annotated BC5CDR / BioRED | 27 configs × 2 corpora; CIs, p-values, per-type | Ranking on chemical/disease (+4 BioRED types) mention finding on PubMed abstracts. Nothing about the corpus. |
| **2. External-reference grounding** | Reference vocabularies: NCBI Gene, CTD/MeSH, Mondo, HPO, NCBI Taxonomy, OMOP | Corpus-bench "grounding" — share of a model's unique strings that resolve in a vocabulary of the predicted type | A precision *proxy*. A string can match an unrelated synonym; a real entity can be missing from the vocabulary. Not accuracy. |
| **3. KG support** | Curated-KG membership of an edge | Corpus-bench `cdm_triples`: microbe–disease 943 triples / 137 both-grounded / 50 KG-supported = 36.5% | Coverage of a small resolved subset. **Absence is untested, not incorrect.** |
| **4. Model-generated validity** | LLM judges / cleaned layer | Not used by component I at all | Model behaviour. Never annotation. |

**A correction to the superseded text:** the earlier report described corpus grounding as "measured
against the project's own term layer, so it is circular". That is **wrong**. `corpus_bench.py` builds
its lexicons from downloaded external references — NCBI `gene_info` for human and mouse, `CTD_diseases`
(MEDIC), `CTD_chemicals` (MeSH), Mondo, HPO, NCBI Taxonomy, and a variant-pattern regex — and never
from the project's canonical terms. Grounding is therefore Tier 2, not circular. It still has two real
limitations, both now stated precisely: it is a precision proxy by construction, and **`CellLine`
grounding is hard-coded to resolve nothing** (`ground()` returns `set()` for that type), so the 0.0%
CellLine column across all models is definitional and must not be read as model failure.

Two further facts about the corpus run that belong with the tiers: it scores models under the
**BioRED 6-type schema**, not the CDM 14-type schema, and it reuses the GLiNER thresholds tuned on the
BioRED **dev** split. It is a Tier-2 measurement of corpus behaviour, not a corpus gold standard.

---

## 10. Amendment record for `09_NER_BENCHMARK_QUALITY.md`

The following statements in `09` are superseded by this correction. `09` is amended in place with a
dated block that points here; no other component report is affected.

| # | Superseded in `09` | Corrected |
|---|---|---|
| 1 | "BC5CDR covers 2 types; BioRED covers 6 … 0 benchmarks for the five microbiome-specific types" | 2 direct (22.78% of typed terms), 3 approximate (35.32%), 9 none (41.90%); `MICROBIOME`/`DIET`/`HABITAT` are not CDM types. §1.4 |
| 2 | "No benchmark tests `ORGANISM`" | BioRED `OrganismTaxon` tests it approximately; the failure is distributional and now measured (90.8% host-generic, 0 bacterial taxa, 0.9441 → 0.556 recall on non-host). §1.3 |
| 3 | "target-type coverage 2/14 on BC5CDR, 6/14 on BioRED" | Counts are of *benchmark types present*, not of CDM types covered; the CDM-type view is 2/3/9. §1.2 |
| 4 | "full-schema F1 … n/a cells are shown explicitly" (rated as an ADEQUATE protocol property) | True for `per_type`, false for the headline; a supported-schema F1 is added and the coverage/skill split is measured. §2 |
| 5 | "Four 0.0 rows are schema artefacts" | Five 0.0 rows across both corpora (`+ biored__scispacy_lg`), and the mechanism differs: three are label-map zeros, one is untyped-only, one is untyped-only on BioRED. §2.4 |
| 6 | "`scispacy_lg` scores 0.0 exact but 30.3 span-only" | Correct for BC5CDR (0.3027); BioRED is 0.3832. The number is the *only* valid measurement for that model and must be shown in the cell. §2.3 |
| 7 | "Corpus grounding is measured against the project's own term layer, so it is partly circular" | **Wrong.** External lexicons (NCBI Gene, CTD, Mondo, HPO, NCBI Taxonomy, OMOP). It is a precision proxy, not circular; `CellLine` 0.0% is definitional. §9 |
| 8 | "`pubtator3 †` … the best *runnable* general models are `hunflair2` 77.3 and `llm_qwen_fs` 69.5" | Retained, but promoted from a caveat to a structural rule: PubTator3 is reference-only and the ranked table must separate it. §7 |
| 9 | "† = trained on this corpus" treated as one category | Four exposure classes plus one unmeasurable; PubTator3 is annotation-source contamination, not training reuse; BioRED/PubTator lineage and LLM pretraining are declared unmeasured. §3 |
| 10 | "no manifest, no preregistration, no prompt bundle" | Manifest now exists and is labelled retrospective; prompts recovered and verified; preregistration still absent and cannot be created after the fact. §5–6 |
| 11 | "the corpus benchmark ran over 21.56 M chars / 7,161 chunks / 453-paper body universe" | Correct figures, wrong description: all 453 papers, every section except References/Acknowledgements, **BioRED** type schema, 4,000-char chunks. §9 |
| 12 | "Qwen side is the historical Ollama run" / `llm_qwen_*` treated as one thing in the corpus discussion | The 12 LLM corpus runs use the same BioRED prompts and the same 3-shot examples as the public benchmark, verified. §6 |

**Later correction (`2026-11-04`):** a fourth passage in `09` — "a 35-mention-versus-36-mention
comparison" and the adjacent §1.3 table — is amended by `CQA-I-AMEND-2026-11-04-1`
(`NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md`): the "Recall on all 393 OrganismTaxon" column holds
full-schema 6-type micro recalls, the `gliner_v25_biomed` F1 cell was a cross-row transcription, and
both subsets are 36 mentions. No value in `09` or in any metrics artefact changed.

---

## 11. What this component now demonstrates and does not

**Demonstrates (corrected set):**

* All **1,186** reported benchmark values reproduce exactly from the 54 prediction files under the
  project's own matching rules; **0** mismatches. The metrics are arithmetically sound.
* **2 / 3 / 9** is the correct CDM-type coverage picture: 22.78% of typed terms directly benchmarked,
  35.32% approximately, **41.90% not at all**; plus `ENTITY` at 55.29% of all terms, unbenchmarkable.
* BioRED `OrganismTaxon` is **90.8% host-generic with zero bacterial taxa**; the best model on that
  type (0.9441) falls to **0.556** non-host recall, while the 3-shot Qwen model reaches **0.917**.
* **14 of 27** BioRED configurations cannot emit all six types; `bert_disease` moves from 0.3613
  full-schema to 0.8606 supported-schema.
* `span_only` is not span detection; it equals all-span F1 for **42/54** runs and *falls* by up to
  0.11 for broad trained models.
* **7** runs carry `†`; split leakage is **0** PMIDs in both corpora; one `†` run is annotation-source
  contamination rather than training reuse; two exposures are unmeasurable and declared.
* **25** configurations are deployable at section level, **1** is reference-only, **1** is untyped-only.
* Prompts and few-shot examples are **recovered and verified** against recorded metadata for all 12
  shot-runs; the environment stack is **not** recorded and cannot be recovered.
* A dated SHA-256 seal over **126 files / ≈3.57 GB** (including the ≈2.5 GB of external reference
  inputs the corpus scorer reads) verifies **126/126**, and is **not a** preregistration.

**Does not establish:**

* Any accuracy, recall, precision or completeness figure for the 453-paper corpus in any type.
* That the corpus's dominant types (`ENTITY`, `ORGANISM`) are extracted well or badly — the ORGANISM
  probe is 36 mentions over 10 documents, and the `ENTITY` label has no benchmark at all.
* That `hunflair2`, or any other configuration, is the right extractor for microbiome full text.
* That PubTator3's 0.9009 is a model result; it is a curated-resource ceiling on its own corpora.
