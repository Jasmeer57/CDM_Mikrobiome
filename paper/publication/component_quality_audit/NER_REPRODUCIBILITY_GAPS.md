# Component I — Reproducibility gaps: what can be regenerated, what cannot

**Status date:** 2026-11-04
**Companion to:** `NER_BENCHMARK_CORRECTIONS.md` (the substantive correction), `NER_RECOVERED_PROMPTS.md`
(the recovered prompts), `NER_RETROSPECTIVE_SEAL.sha256` (the dated hash manifest).
**Scope:** the two benchmark suites — `outputs/results/benchmark/ner_fair_bench/` (54 prediction files,
27 configurations × 2 corpora) and `outputs/results/benchmark/ner_corpus_bench/` (26 configurations over
the 453-paper corpus), plus `ner_quality_quantity_2026-11-03/`.

**What this document is.** A gap register, not a remedy. Nothing here was fixed, re-run, or back-filled.
Each item is classified by whether a third party could reconstruct the result **from what is on disk
today**, and — where the answer is no — by what exactly is missing and whether it can still be obtained
without re-running the extraction.

**Why it matters separately from the corrections document.** The corrections document fixes *what the
numbers mean*. This document fixes *what a reader is entitled to assume about how they were produced*.
The two are different failure modes: a benchmark can be arithmetically perfect (it is — 1,186/1,186
values reproduce) and still not be reproducible in the ordinary scientific sense.

---

## 1. The summary table

| # | Question a reviewer will ask | Answer | Basis |
|---|---|---|---|
| 1 | Can every reported metric be recomputed from the shipped predictions? | **Yes, exactly** | 1,186/1,186 values reproduced to 1e-12 (§2) |
| 2 | Are the gold standards pinned? | **Yes, by content** — not by source | `data/benchmarks_ner/raw/SHA256SUMS`, §7 |
| 3 | Are the model checkpoints pinned? | **Yes** — but in the SLURM logs, not in the prediction metadata | §3, 11 distinct revisions + 6 HF snapshot hashes recovered |
| 4 | Are the prompts recoverable? | **Yes, and verified** against recorded metadata | `NER_RECOVERED_PROMPTS.md`, §4 |
| 5 | Is the runtime stack recorded? | **Partly**: vLLM 0.32.0 yes; torch / transformers / CUDA driver **no** | §5 |
| 6 | Are the predictions themselves lossless? | **No.** Off-schema entities are deleted at write time; truncation and salvage are counts, not records | §6 — the most consequential gap |
| 7 | Was the analysis plan fixed before the results? | **No.** Tier 1 has no preregistration; Tier 2/3 do | §8 |
| 8 | Is the shipped report an independent artefact? | **No** — it is a rendering of the JSON by the same code | §9 |
| 9 | Is the corpus-side protocol stable across the run? | **No** — the scoring was run three times; only the last survives | §10 |
| 10 | Is the whole thing sealed? | **Yes, retrospectively** — and that is not the same as preregistered | §11 |

---

## 2. What is exactly reproducible today

Everything in `fair_ner_metrics.json` that is a function of (gold file, prediction file, matching rule).
The audit demonstrated this by importing `fairbench.py` rather than re-implementing it:

```
diagnostics/cqa_ner_recompute.py  →  NER_RECOMPUTATION_CHECK.csv   (1,407 rows)
   MATCH 1,186 · MISMATCH 0 · MISSING 0 · N/A 69 · NEW 152
```

Reproducible: full-schema exact F1/P/R/tp/fp/fn, relaxed F1, both CI bounds, span-only exact and relaxed
F1, `chem_dis` where defined, per-type exact F1 and per-type CIs, and the identity of `best_on_dataset`.
Also reproducible: the LLM prompt strings and few-shot example blocks, the decoding parameters, the
GLiNER threshold grids and the chosen thresholds, and the corpus-side `corpus_metrics.json` aggregates.

Because the recomputation closes exactly, **any future disagreement about these numbers is a
disagreement about artefacts, not about implementation.** That is a real and unusual strength and it
should be stated as such.

---

## 3. Model identity and checkpoint pinning — better than the metadata suggests

The prediction files carry `hf_id` (24 LLM files) and `raw_labels` (30 files) but **no revision hash**.
On that basis alone the checkpoints would be unpinned, and an earlier draft of this audit said so. That
was too pessimistic: the revision hashes are in the SLURM job logs, which survive.

**Classic models — `Loading <repo> (revision=<sha>)` in `outputs/logs/ner_bench/nerbench-classic_*.out`:**

| Repository | Revision |
|---|---|
| `alvaroalon2/biobert_diseases_ner` | `0a4ed7dd4fd3e6db7229e5b801b70eefcb253759` |
| `fastino/gliner2-base-v1` | `f9634218e53580c56edf0de97ca1a7d3f1c2354e` |
| `fastino/gliner2-large-v1` | `d7aa8a2850d175a9227ff80358ea380723d03ad2` |
| `gliner-community/gliner_medium-v2.5` | `88c3b98b57ad5e7d66fb209ed61c53f4b1fd05da` |
| `Ihor/gliner-large-v2.5-biomed` | `304d250ab2373a0d4ef0bc9524868cf04de0d509` |

The remaining classic configurations do not print a hash but are pinned by name and by the environment
script: `en_ner_bc5cdr_md`, `en_ner_bionlp13cg_md`, `en_ner_craft_md`, `en_ner_jnlpba_md`,
`en_core_sci_lg` (scispaCy v0.5.4 tarballs in `src/scripts/setup_ner_variants_venv.sh`), HunFlair2
(flair 0.15.1 in `~/venvs/ner_variants`), `biobert_chemical` / `biobert_genetic` (HF ids in the
registry). Model *names* are in the logs; version *revisions* for the scispaCy packages are pinned only
in the installer script, which is itself not hashed.

**LLMs — HF cache snapshot hash, printed by vLLM at load time (`outputs/logs/ner_bench/vllm_*.log`):**

| Model | HF id (from `_meta`) | Snapshot commit |
|---|---|---|
| qwen | `Qwen/Qwen3.5-4B` | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` |
| gemma | `google/gemma-4-E4B-it-qat-w4a16-ct` | `6cd26aaa2357fb2bad8c51699a7558a4d1a965bb` |
| llama | `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4` | `db1f81ad4b8c7e39777509fac66c652eb0a52f91` |
| mistral | `TechxGenus/Mistral-7B-Instruct-v0.3-AWQ` | `98bcbff8d515b4103485b10f2b700e064dac9582` |
| phi | `thesven/Phi-3.5-mini-instruct-awq` | `c3a719dac508095455d0a691495e60877e34ff6e` |
| deepseek | `casperhansen/deepseek-r1-distill-qwen-7b-awq` | `305e6f12907dc78ae61a1f0bb7a19faa2b25e8a3` |

**Residual gap.** This reconstruction depends on the log directory surviving and on a human knowing to
look there. The prediction files should have carried `revision` in `_meta`; they do not. A reviewer who
receives only the `preds/` directory — which is exactly what a data-availability statement would hand
over — receives unpinned checkpoints. That is a packaging defect, not a provenance defect, and it is
closable by copying one field into the metadata on any future run.

**PubTator3 is the exception.** Its `_meta` records `docs_found: 500/500` (BC5CDR) and `100/100`
(BioRED) and an `offset_match` of **11,590/12,188 = 95.09%** (BC5CDR) and **2,903/3,345 = 86.79%**
(BioRED). The API has no revision, no date stamp and no version field anywhere in the artefact. The
annotations it returned are therefore **not identifiable**: a second call today returns whatever the
live service serves. This is the one configuration in the suite whose inputs cannot be reconstructed at
all, which is a further reason it cannot be treated as a candidate (§7 of the corrections document).

---

## 4. Prompts — recovered and verified, not merely plausible

`llm_system(ds)` and `fewshot(ds, k=3, seed=0)` are deterministic functions in the shipped code, so the
message lists were reconstructed exactly, then checked against what the runs recorded:

* all **12** `_fs` prediction files carry `fewshot_train_pmids`, and all 12 match the reconstructed ids;
* BC5CDR shots `12523465, 7053303, 12695819`; BioRED shots `19918264, 20533999, 20722491`;
* all six shot PMIDs per corpus lie in the **train** split; `test ∩ train = 0` and `test ∩ dev = 0` in
  both corpora, measured from the gold files.

Verbatim system prompts (550 characters BC5CDR, 879 BioRED) and every shot message:
`NER_RECOVERED_PROMPTS.md`; machine-readable `diagnostics/results/ner_recovered_prompts.json`.

**One genuine asymmetry that must be carried with the results.** `NO_SYSTEM_ROLE = {"mistral"}`. For
Mistral the system text is concatenated as `<system>\n\n<first message>` into the first message, which
in 3-shot mode is a few-shot *user* turn. Mistral's prompt is therefore not the same object as the other
five models' prompts, in both `_zs` and `_fs` mode. This is recoverable and documented; it is not a
defect, but any cross-model sentence that says "all models received the same instructions" is wrong.

---

## 5. Runtime environment — half recorded

| Item | Recorded? | Where / value |
|---|---|---|
| vLLM version | **Yes** | `version 0.32.0` in all 25 `vllm_*.log` files |
| Served model path | **Yes** | full `models--<org>--<name>/snapshots/<sha>` path in the vLLM logs |
| Sampling config | **Yes** | `temperature`, `seed`, `max_tokens`, `response_format`, `chat_template_kwargs` in `run_llm()`, and `temperature` in `_meta` |
| vLLM non-default args | **Yes** | `max_model_len 16384`, `quantization awq_marlin`, `gpu_memory_utilization 0.9`, `enable_prefix_caching`, `max_num_seqs 128` — logged per server |
| GPU model | **Yes** | `NVIDIA A40` in the job `.out`; `device` in 52 of 54 `_meta` records |
| Module stack (CPU) | **Script-level** | `Python/3.12.3-GCCcore-13.3.0`, `CUDA/12.9.1` in `classic.sbatch` / `llm.sbatch` |
| **torch version at run time** | **No** | not in any log. Today's `~/venvs/vllm` reports **2.13.0+cu130**, but the venv is mutable and today's value is not proof of the run-time value |
| **transformers version at run time** | **No** | today's venv reports **5.19.0** — same caveat |
| **CUDA driver / GPU firmware** | **No** | never printed |
| **Python interpreter used for corpus scoring** | **Inferred** | `corpus_score.sbatch` calls bare `python3` after loading the module, i.e. the module interpreter, **not** `venvs/vllm` — a different interpreter from the extraction runs, and no artefact confirms which one actually ran |
| **requirements lock for the bench** | **No** | `requirements.lock` exists at repo root but pins torch 2.1.1+cpu / scipy 1.10.1, which contradicts the 2.13.0 actually in use. It is not a lock for this run |

**Consequence.** The LLM half of the suite can be described as "vLLM 0.32.0 serving snapshot X on an A40
with these sampling parameters". It cannot be described as a fully specified software environment.
Because vLLM is not bit-deterministic across builds even at `temperature=0`, exact response
reproduction was never available; what is missing is the ability to say *which* stack a re-run would
have to match. Per-item, this is a **documentation gap, not a result-integrity defect** — the predictions
exist, the metrics are verified, and the environment only affects forward reproduction.

---

## 6. The predictions are lossy — the most consequential gap

This is the only gap in this document that changes what a reader can conclude, and it cannot be closed
without re-running extraction.

### 6.1 Off-schema entities are deleted before the file is written

`run_llm()` filters at write time:

```python
if typ not in TYPES[ds]:
    st["invalid_type"] += 1
    continue
```

An LLM that emits `Bacteria` on BC5CDR (schema: Chemical, Disease) has that entity **removed from the
prediction record**. Only a counter survives. So:

* the shipped files cannot answer "what else did the model find?";
* the shipped `span_only` metric cannot be recomputed type-agnostically — which is exactly why the audit
  had to add `span_all_exact_F1` and found it *identical* to `span_only` for 42 of 54 runs (the LLM
  files have nothing else in them to see);
* the loss rate is large where it matters: `llm_phi_zs` on BC5CDR discarded **2,257 of 3,377 emitted
  strings (66.8%)**; `llm_phi_fs` discarded **3,295 of 4,773 (69.0%)**.

For the trained models the loss is smaller but present, and it is recorded only as a per-run `raw_labels`
histogram (30 files) — enough to see *that* extra classes were emitted, not enough to see *which spans*.

### 6.2 Truncation and salvage are counts, never records

`truncated_docs`, `salvaged_docs`, `failed_docs` are integers. Nothing records **which** documents hit
the token ceiling. `errors` retains at most **three distinct exception strings**, each truncated to 300
characters (`sorted({...})[:3]`), so a per-document failure cannot be attributed. `strings_not_in_text`
is a count of emitted strings with no match in the source text, but the strings themselves are not kept.

Practical effect: `llm_llama_zs` on BC5CDR truncated and salvaged **294 of 500 documents**, and there is
no way to ask whether its 0.5780 F1 is depressed by those specific documents or is uniform. The audit
can report the count; it cannot decompose the score.

### 6.3 Sparse metadata: an absent key means zero, and nothing says so

`_meta` is built with `**dict(Counter)`, and `Counter` only gains a key when it is incremented. So
`invalid_type` is present in **18 of 24** LLM files and absent in 6 — absent means *zero*, not
*not measured*. `raw_labels` likewise appears only where a model reported labels. A reader who treats
absent as unknown will understate the loss; a reader who treats absent as zero will be right, but only
because they read the code. There is no schema, no `null`s, and no data dictionary.

### 6.4 Offset repair is invisible for PubTator3

PubTator3 emits PubMed abstract coordinates. The runner maps them onto local text and records the
outcome only as a ratio (`11590/12188`, `2903/3345`). The ~4.9% / ~13.2% that failed to map are not
listed, and their contribution to the `fn` count is not separable from genuine misses.

---

## 7. Inputs: gold data pinned by content, references pinned only now

**Gold standards.** `data/benchmarks_ner/raw/SHA256SUMS` pins all six PubTator files. `load()` re-verifies
every gold offset against the text on read and raises `SystemExit` if any disagree — a strong internal
check. `BC5CDR_README.txt` carries the NLM public-domain notice and the required citation.

**Gap:** neither the retrieval URL nor the retrieval date is recorded anywhere in the repository. The
audit can say *"the BC5CDR test file whose sha256 is 926992c3… is what was scored"* and cannot say
*"obtained from source Y on date Z"*. That is sufficient for verification and insufficient for citation
practice.

**Corpus-side reference lexicons.** `corpus_bench.py` rebuilds four lexicons and four KG association sets
on every scoring run, from `data/reference_kg/raw/` (NCBI `names.dmp` / `nodes.dmp`, CTD disease,
chemical and gene files, human and mouse `gene_info`, Disbiome) plus `outputs/results/omop_vocab/CONCEPT.csv`
and `CONCEPT_SYNONYM.csv` (1.35 GB + 383 MB). Total **≈2.5 GB of external reference data**, of which
*none* was hash-pinned at run time.

Two facts mitigate this, and one fact sharpens it:

* The lexicon sizes are stable across all three scoring runs (`GeneOrGeneProduct` 905,041 ·
  `DiseaseOrPhenotypicFeature` 248,620 · `ChemicalEntity` 717,982 · `OrganismTaxon` 5,028,243 ·
  `microbe_disease` 16,583), so the lexicons did not drift *during* the benchmark window.
* `reference_sizes.json` and `disbiome_unmatched_diseases.json` survive and match those numbers.
* **Sharpening:** some files in `data/reference_kg/raw/` were modified *after* the run (`delnodes.dmp`,
  `merged.dmp`, 2026-11-03). Those two are **not read** by `corpus_bench.py` (only `names.dmp` and
  `nodes.dmp` are), so the grounding is unaffected — but a reader checking modification times would
  reasonably conclude otherwise, and only a code read resolves it.

**This audit closes the gap prospectively** by including the exact twelve reference inputs in the
retrospective seal (§11). A seal taken today is weak evidence about a run on 2026-11-02 (the files could
in principle have changed in between — the mtimes say they did not, within the tolerance of a mutable
filesystem), and it is the strongest evidence still obtainable.

---

## 8. No preregistration for Tier 1 — while Tier 2 and Tier 3 have one

`outputs/results/benchmark/` contains:

| Directory | `PREREGISTRATION.sha256` | `MANIFEST.sha256` |
|---|---|---|
| `triple_reference_check_2026-11-03/` | **yes** | yes |
| `bugsigdb_comparison_2026-11-03/` | **yes** | yes |
| `llm_judge_deepseek_v4_flash/` | no | yes |
| `ner_fair_bench/` | **no** | **no** |
| `ner_corpus_bench/` | **no** | **no** |
| `ner_quality_quantity_2026-11-03/` | **no** | **no** |

The NER suite is the component the project relies on most for model choice, and it is the only one of
the three Tier-2/3 studies with **no preregistration and no manifest** — a direct inversion of the
evidential priority. The asymmetry is not hidden (nothing was mislabelled), but it means the NER results
cannot claim the "analysis plan fixed in advance" status that the triple-reference and BugSigDB
comparisons can.

The `fairbench.py` docstring does say *"Protocol (fixed before any test-set result was seen)"*. That is
an assertion in a source file, not a timestamped commitment: the file is mutable and its mtime is
uninformative. It may well be true; it is not evidence.

---

## 9. The report file is not an independent artefact

`FAIR_NER_BENCHMARK.md` is emitted by `report()`, called by `score()`, immediately after
`fair_ner_metrics.json` is written — the same process, the same values, seconds apart (both files carry
mtime `2026-11-02 02:08:38`). It is a **rendering**, not a second measurement.

Consequences:

* Cross-checking the Markdown against the JSON cannot detect an error, because both come from one
  computation. Any audit that "verified the report against the metrics" verified nothing;
* the numbers in the Markdown are rounded to one decimal, so the file is a lossy view of the JSON;
* the same is true of `CORPUS_NER_BENCHMARK.md` versus `corpus_metrics.json` (both `2026-11-02 10:25:10`).

Related packaging issue: `per_config_type.csv`, cited as component-I evidence, lives in
`ner_quality_quantity_2026-11-03/`, **not** in `ner_fair_bench/`. The earlier component report's
"evidence base" line merged two directories without saying so.

---

## 10. The corpus-side protocol changed mid-flight, and the intermediates are gone

`MEASUREMENT_NOTES.md` discloses it: *"Fixed during trial scoring on 24 of 26 runs (2026-11-02), before
the final runs were scored"* — (1) short gene symbols were being matched case-insensitively and never
grounded; (2) the CDM triple check used CDM types instead of corpus triple domain types.

The job logs show exactly three scoring runs and let this be dated and quantified:

| Log | Time | Models in tables | Change |
|---|---|---:|---|
| `corpus-score_28682471.out` | 08:25:24 | 24 | pre-fix |
| `corpus-score_28682500.out` | 08:30:32 | 24 | gene-symbol case fix (grounding rises: `bert_genetic` 14.2 → 17.6, `hunflair2` 15.3 → 19.4) |
| `corpus-score_28682517.out` | 10:25:12 | **26** | CDM triple-domain fix; and `llm_llama_fs` / `llm_phi_fs` predictions appear for the first time |

Only the third run's outputs are shipped (`corpus_metrics.json`, mtime 10:25:10). Two things follow:

1. The disclosure is **honest and accurate** — the 24-vs-26 note is precisely what the logs show.
2. The **intermediate scoring outputs survive only as SLURM logs**, not as archived artefacts. A reader
   who wants to know what the fix did to `hunflair2`'s KG support (it moved ~0.5 pp) can only diff two
   log files. The pre-fix `corpus_metrics.json` was overwritten in place. That is a genuine
   versioning gap: three runs, one output slot.

No model's *extraction* changed between runs — only the scoring — so no prediction file is affected.
The corpus-side predictions are likewise intact (26 files) and were scored from a stable input.

---

## 11. The seal: what it proves and what it cannot

`NER_RETROSPECTIVE_SEAL.sha256` — dated **2026-11-04T16:48:22+0100**, **126 files / 3,574,150,615 bytes**,
sha256sum format, paths relative to the repository root, verified `sha256sum -c` **126/126 OK** from the
root. It covers the 80 prediction files, the corpus chunk manifest, the metrics and reports, the protocol
scripts and launchers, the nine gold-data files, the recovered prompts, the recomputation outputs, the
derived tables, and the twelve external reference inputs the corpus scorer reads.

**Deliberately excluded:** the three narratives that describe the seal (this document,
`NER_BENCHMARK_CORRECTIONS.md`, `09_NER_BENCHMARK_QUALITY.md`). A document that quotes the manifest's own
byte count cannot be hashed by that manifest without becoming self-invalidating on every edit. The
exclusion is declared in `diagnostics/results/ner_environment.json` (`not_sealed`), and it costs nothing:
no result, prediction, metric or input file is left out.

It proves: *these are the bytes this audit read.*
It cannot prove: *these are the bytes that were analysed at the time, or that the analysis plan preceded
the results.*

**This is retrospective provenance sealing, not preregistration**, and the two are not interchangeable.
A seal taken two days after the results can only detect later tampering; it can never constrain a choice
already made. The distinction is stated in the seal file itself, in `NER_BENCHMARK_CORRECTIONS.md` §5, and
in the accompanying `diagnostics/results/ner_environment.json` (`"seal_kind": "retrospective provenance
seal — NOT a preregistration"`).

Two mechanical notes for anyone verifying the seal:

* `outputs/results/ner_fair_bench` and `outputs/results/ner_corpus_bench` are **symlinks** to
  `outputs/results/benchmark/…`. The seal hashes the resolved paths under `benchmark/`. Anyone copying
  only the symlinked paths must resolve them, or verification fails for a reason unrelated to tampering.
* The environment block records the *sealing host* (`/usr/bin/python3`, 3.9.21), which is **not** the
  interpreter that produced any benchmark result. It is there to identify the sealing process, and must
  not be read as the run-time Python version.

---

## 12. Gap register

Severity is scoped to *provenance and reproduction*. No item here is a defect in a reported number — all
1,186 reported values reproduce exactly (§2).

| ID | Gap | Severity | Closable without re-running extraction? | What closing it would take |
|---|---|---|---|---|
| **CQA-I-09** | Off-schema entities deleted at write time in the LLM prediction files (`invalid_type` up to 69.0% of emitted strings); type-agnostic scoring therefore unavailable | **HIGH** | **No** | Re-running the 12 LLM configurations with raw responses retained; or, at minimum, storing the rejected `{text,type}` pairs alongside the accepted ones on any future run |
| **CQA-I-10** | No `PREREGISTRATION.sha256` for `ner_fair_bench` / `ner_corpus_bench`, while the two Tier-2/3 studies have one | **HIGH** | **No** — cannot be created after the fact | Nothing, for this run. Declare the tier honestly and preregister the next one |
| **CQA-I-11** | torch / transformers / CUDA-driver versions at run time are unrecorded; `requirements.lock` contradicts the venv in use | MEDIUM | Partly (venv still exists; values are today's, not run-time proof) | Print `pip freeze` + `nvidia-smi` into the job log at start |
| **CQA-I-12** | Checkpoint revisions live only in SLURM logs, not in the shipped `_meta` | MEDIUM | **Yes** — recoverable now, merge into metadata | One field per prediction file, from the table in §3 |
| **CQA-I-13** | Corpus scoring ran three times into one output slot; pre-fix `corpus_metrics.json` overwritten | MEDIUM | Partly (SLURM logs preserve the printed tables; the JSON does not) | Version the output directory per scoring run |
| **CQA-I-14** | External reference lexicons (≈2.5 GB) were not hash-pinned at run time | MEDIUM | Retrospectively sealed only | Pin at build time; `reference_sizes.json` is a size proxy, not a content hash |
| **CQA-I-15** | Truncation, salvage, failed-document and non-matching-string counts are integers with no per-document record; `errors` keeps ≤3 strings | MEDIUM | **No** | Per-document status line in the prediction file on any future run |
| **CQA-I-16** | PubTator3 is unidentifiable — no version, date or revision anywhere; ~4.9% / ~13.2% of its offsets failed to map, silently | MEDIUM | **No** | Query date + service version in `_meta`; it remains reference-only regardless |
| **CQA-I-17** | Gold-data retrieval URL and retrieval date unrecorded (content *is* pinned by `SHA256SUMS`) | LOW | Yes — documentation only | Add a provenance note beside `SHA256SUMS` |
| **CQA-I-18** | `_meta` is sparse: an absent counter key means zero, with no schema documenting that | LOW | Yes | Fixed key list with explicit zeroes |
| **CQA-I-19** | The environment-capture job (`nerbench-env_28681234`) produced a **0-byte** output and its script (`env.sbatch`) is not in the tree | LOW | **No** for that job | Preserve the script; print the environment inline in each job instead of a separate one |
| **CQA-I-20** | `FAIR_NER_BENCHMARK.md` / `CORPUS_NER_BENCHMARK.md` are renderings of the JSON by the same function — cross-checking them is circular | LOW | Yes — attention, not new work | State in the report's own header that it is generated |

---

## 13. Recommended handling in the manuscript

These are recommendations, not changes made here. Nothing below was applied to any file outside
`paper/publication/component_quality_audit/`.

1. **State the reproduction status in one sentence, in the NER section, not in a supplement.** The
   accurate sentence is: *"All reported benchmark metrics are recomputed from the released prediction
   files and reproduce exactly; the models are identified by checkpoint revision; the runtime library
   versions at the time of the run are not recorded, and the prediction files retain only in-schema
   entities."*
2. **Do not claim preregistration for the NER suite.** Claim it only for the triple-reference and
   BugSigDB comparisons, which have `PREREGISTRATION.sha256`.
3. **Cite the seal as what it is** — a retrospective integrity manifest, dated, verifying N files — and
   never in the same sentence as "pre-specified".
4. **Ship the `preds/` directory with a revision table**, not alone. Without §3's table the checkpoints
   are unpinned for anyone who receives only the predictions.
5. **Keep `invalid_type` in the limitations.** A 66.8% off-schema discard rate for `llm_phi_zs` on BC5CDR
   is a property of the result, not a footnote: it means the type-agnostic comparison in the suite has
   no independent measurement for LLMs.
6. **Do not report the corpus-side grounding or KG support as reproducible without the reference-input
   hashes from §11.** They depend on ≈2.5 GB of external vocabulary that was not pinned when the run was
   scored.

---

## 14. Bottom line

The suite is **recomputable but not preregistered**, and **documented but not lossless**.

* Recomputable: 1,186 of 1,186 reported values reproduce from the shipped predictions under the project's
  own matching code, with zero mismatches. The arithmetic is not in question.
* Not preregistered: Tier 1 has no `PREREGISTRATION.sha256` while Tier 2/3 do. The protocol's claim to
  have been fixed in advance is a docstring, not a record.
* Documented: prompts, decoding, few-shot ids, checkpoint revisions and gold-data hashes are all
  recoverable from artefacts on disk — more of the chain than the prediction metadata alone suggests.
* Not lossless: the LLM prediction files discard off-schema entities before writing and record truncation
  as counts. No re-analysis can recover what those files do not contain, and no amount of post-hoc
  sealing changes that.

Of the **twelve** registered gaps, **three** cannot be closed without re-running extraction
(**CQA-I-09** off-schema discard, **CQA-I-15** per-document truncation records, **CQA-I-16** PubTator3
identifiability), **two** cannot be closed at all (**CQA-I-10** no preregistration, **CQA-I-19** a
0-byte environment log whose script no longer exists), **three** can be closed only partly
(**CQA-I-11**, **CQA-I-13**, **CQA-I-14**), and **four** are documentation or packaging fixes available
today (**CQA-I-12**, **CQA-I-17**, **CQA-I-18**, **CQA-I-20**). The last group is why the gaps are listed
individually rather than summarised as "reproducibility concerns": most of them cost one line of code or
one paragraph to eliminate in the next run.
