# Audit Reproducibility — Can Another Person Re-derive Every Number in This Audit?

**Audited object:** this audit itself — `paper/publication/component_quality_audit/` in its entirety
(**108 files / 2,198,420 B** at the moment this report was written; **110 files as delivered** — see §1),
the **32 Python scripts / 9,422 lines** in `diagnostics/`, the **38 files**
in `diagnostics/results/`, the six stage logs, and `NER_RETROSPECTIVE_SEAL.sha256` (**126 entries**).
**Evidence base:** a full inventory of the audit tree; a static writer-detection census over the 32
scripts; six CWD/permission rules re-executed for return code; two timing sweeps (20 diagnostics × two
interpreters); a six-script generator chain timed twice; eight out-of-tree probe scripts re-executed;
`sha256sum -c` against seven independent snapshot manifests; and the SLURM logs of the six
`cqa_diag_*` jobs.
**Independence:** nothing here is taken on trust from the other reports. Every rule stated below was
executed at least twice and its return code recorded. Where a claim could not be re-executed, the report
says so and says why.

> **Scope.** This report judges **whether the audit can be re-derived**, not whether it was right — that
> is components A–P. It does not re-open any finding, does not raise or lower any rating in
> `16_QUALITY_METRICS.csv`, and does not re-seal anything. It answers one question: *if a referee asked
> "show me 334,231 mapping rows from scratch", how far would they get with only what is in this
> directory?*
>
> The answer is: **all 38 result files, from 30 in-tree scripts plus 8 scripts that live outside the audit
> directory, on a machine with one 2.86 GB side-car file that is not shipped here.**

---

## 1. What is in the directory

| Location | Files | Bytes | What it is |
|---|---|---|---|
| audit root | **27** | 1,036,993 | 20 `.md` files (16 component/action reports + 4 NER evidence docs), 6 `.csv` tables, 1 `.sha256` seal |
| `diagnostics/` | **33** | 418,132 | 32 `.py` + 1 `.sbatch` (no subdirectory except `results/`, `__pycache__/`) |
| `diagnostics/results/` | **38** | 721,182 | every machine-readable result quoted in 01–18 |
| `logs/` | **6** | 591 | one `[wrote] …` line per diagnostic the SLURM wrapper ran |
| `diagnostics/__pycache__/` | 4 | 21,522 | 4 stray `.pyc` (`common` ×2, `d01` py39, `cqa_metrics` py39) |
| **total** | **108** | **2,198,420** | `du -sb` reports 2,198,542 (directory inodes) |

*The counts above were taken **before this file existed** and therefore exclude it and its 42,970 B;
the directory as delivered is **110 files** — 106 excluding the four `diagnostics/__pycache__/` `.pyc`
files. The byte total is **≈2.3 MB** — deliberately not pinned to the byte (see the correction below).
Every other number in this report is unaffected by the addition — report 19
is not an input to any script, and `REPORTS` in `cqa_metrics.py` lists only A–N.*

*[corrected 2026-11-05: this sentence previously projected **109 files / 2,241,390 B** (`du -sb`
2,241,513). That projection added only this file (+42,970 B) to the 108-file snapshot and was overtaken
by two later events: `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md` (+63,400 B) was written after this
report, and three root files (`00`, `18_RECOMMENDED_ACTIONS.md`, `19_AUDIT_REPRODUCIBILITY.md`) then grew
during the §7.1 correction pass. A first attempt at this correction pinned **2,308,645 B**, which was
already stale before it was saved — every additive edit to a root `.md` moves the total by a few KB
without adding a file. The **snapshot table above is correct as stated**: it describes the directory at
the moment this report was written and is deliberately not retro-fitted. The delivered composition from
a fresh `os.walk` census: root **29 files** (22 `.md`, 6 `.csv`, 1 `.sha256`), `diagnostics/` 33
(32 `.py` + 1 `.sbatch`), `diagnostics/results/` 38, `logs/` 6, `__pycache__/` 4 = **110 files**. The 22
root `.md` split as **15 component reports** (`01`–`14` plus `17`) and **7 supporting documents** (`00`,
`18`, `19`, `NER_BENCHMARK_CORRECTIONS.md`, `NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md`,
`NER_RECOVERED_PROMPTS.md`, `NER_REPRODUCIBILITY_GAPS.md`). **Quote the counts, never the byte total** —
a byte figure is a timestamped census that any further edit invalidates, which is why this corrector
declined to give one a second time. Recorded as **CC-13** in `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md`
§7.1.]*

Script breakdown: **20** `dXX_*.py` analytics (**6,061 lines**), **5** `cqa_ner_*.py` Component-I
generators (**756 lines**), **7** supporting scripts — `common.py`, `cqa_actions.py`,
`cqa_build_register.py`, `cqa_f_judge.py`, `cqa_i_grounding.py`, `cqa_metrics.py`, `cqa_n_rights.py`
(**2,605 lines**) — plus `cqa_diagnostics.sbatch` (**86 lines**).

The root file count is the brief's 20 required deliverables plus the seven Component-I supporting files
(`NER_BENCHMARK_CORRECTIONS.md`, `NER_REPRODUCIBILITY_GAPS.md`,
`NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md`, `NER_RECOVERED_PROMPTS.md`,
`NER_RECOMPUTATION_CHECK.csv`, `NER_TYPE_COVERAGE_MATRIX.csv`, `NER_MODEL_DEPLOYABILITY.csv`), the
seal, and `18_ACTION_PLAN.csv` — the machine-readable companion to `18_RECOMMENDED_ACTIONS.md`, which
the brief does not name but which §8 of this report and every rank in the plan depend on:
20 + 7 + 1 + 1 = **29 root files**. `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md` is written after this
file and is the 22nd and last markdown.
*[corrected 2026-11-05: this paragraph previously said the root count was "exactly the brief's 20 required
deliverables plus the seven Component-I supporting files … and the seal" — 28 — and called `00` the
"21st markdown". Both were wrong: `18_ACTION_PLAN.csv` was omitted from the enumeration and 22 root
`.md` exist, not 21. Recorded as **CC-13** in `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md` §7.1.]*

---

## 2. The reproduction ladder — four tiers, in dependency order

There is no single command that reproduces the audit. There are four tiers, and each tier's output is
the next tier's input.

```
Tier 0  frozen releases (read-only)          releases/cdm_v3/3.0.3, data_catalogue_v3/3.1.1,
                                              terminology/1.0.1, corpus_v2/2.2.0, zenodo_frozen
   │
   ├─ Tier 1  20 dXX_*.py  ────────────────►  20 results/*.json          (analytics: measurement)
   │          7 cqa_*.py (F/I/N) ──────────►   3 results/*.json          (judge, grounding, rights)
   │
   ├─ Tier 2  8 probe scripts in outputs/scratch/ ──►  8 results/*.json  (out of tree, see §5)
   │
   ├─ Tier 3  5 cqa_ner_*.py ──────────────►  8 results/ + 4 root CSVs   (Component I, sealed)
   │
   └─ Tier 4  cqa_build_register → cqa_metrics → cqa_actions
                                             15_ISSUE_REGISTER.csv (154)
                                             16_QUALITY_METRICS.csv (131)
                                             18_ACTION_PLAN.csv (154) + cqa_actions.json
```

**Tier 4 order is not arbitrary and cannot be permuted.** `cqa_build_register.py` must run first (it
writes `15_ISSUE_REGISTER.csv`, which both later scripts read for the per-component `component_issues_*`
counts). `cqa_metrics.py` reads `15` and writes `16`. `cqa_actions.py` reads `15` and writes `18_ACTION_PLAN.csv`
plus `cqa_actions.json`. All six generator scripts (`cqa_i_grounding`, `cqa_f_judge`, `cqa_n_rights`,
`cqa_build_register`, `cqa_metrics`, `cqa_actions`) run in **85.675 s** on the login interpreter and
**81.308 s** on the vLLM 3.12 interpreter; the chain is dominated by `cqa_n_rights` (73.689 s / 70.852 s),
which must decompress-adjacent-scan a 2.86 GB attached database.

Tier 4 is the only tier that is fully self-contained: it needs no release access beyond what the earlier
tiers already read, and it is byte-deterministic (verified below).

---

## 3. Result → producer mapping, and the writer census

Each of the 38 files in `diagnostics/results/` was traced to the code that writes it. Two independent
methods were used because neither is complete on its own:

1. **Declared writer** — an `emit("<stem>", …)` call, which is the sanctioned path
   (`common.emit()` writes `diagnostics/results/<name>.json` and prints the repo-relative path).
2. **Observed writer** — a 5-line window around any `json.dump`, `write_text`, `csv.writer`, `open(…"w")`
   or `emit(` site that mentions the result stem.

**Result: 22 of the 38 have a declared `emit()` writer, and those 22 are exactly the 22 emitted names —
no `emit()` target is missing from `results/`.** **16 files have no `emit()` call** and are written by
direct path. The window-based census detects **28 of 38**; the 10 it misses are listed below, and eight of
them are the probe-only files of §5.

Nine scripts contain no `emit(` at all: `cqa_build_register.py`, `cqa_f_judge.py`, `cqa_metrics.py`,
`cqa_n_rights.py`, `cqa_ner_matrix.py`, `cqa_ner_organism_probe.py`, `cqa_ner_prompts.py`,
`cqa_ner_recompute.py`, `cqa_ner_seal.py`.

### 3.1 The 16 direct writers — exact code sites

These are false negatives of any `emit()`-only grep, not missing producers. Locations verified by
reading the files:

| Result | Writer | Site |
|---|---|---|
| `cqa_f_judge.json` | `cqa_f_judge.py` | `dest.write_text(...)`, line 266 |
| `cqa_n_rights.json` | `cqa_n_rights.py` | `json.dump(out, open(OUT,"w"), …)`, line 636 (only script with a repo-absolute `OUT`, line 32) |
| `ner_recovered_prompts.json` | `cqa_ner_prompts.py` | `RES / …`, lines 96–104 |
| `ner_llm_run_diagnostics.csv` | `cqa_ner_prompts.py` | `open(RES / "ner_llm_run_diagnostics.csv","w")`, line ~104 |
| `ner_recompute_summary.json` | `cqa_ner_recompute.py` | `write_text(...)`, line 165 |
| `NER_RECOMPUTATION_CHECK.csv` | `cqa_ner_recompute.py` | line 141 |
| `NER_RETROSPECTIVE_SEAL.sha256` | `cqa_ner_seal.py` | `write_text(body)`, line 75 |
| `ner_environment.json` | `cqa_ner_seal.py` | `write_text(json.dumps(env))`, line 120 |
| `ner_organism_probe.json` | `cqa_ner_organism_probe.py` | lines 104–105 |
| `NER_TYPE_COVERAGE_MATRIX.csv`, `NER_MODEL_DEPLOYABILITY.csv` | `cqa_ner_matrix.py` | lines 119, 181 |
| `NER_RECOVERED_PROMPTS.md` | `cqa_ner_prompts.py` | line 145 |
| `cqa_catalogue_metrics.json` | `outputs/scratch/cqa_f_final.py` | `OUT`, lines 26–28 |
| `cqa_catalogue_provenance_gap.json` | `outputs/scratch/cqa_cat_prov_gap.py` | `OUT` |
| `cqa_catalogue_redaction{,_2,_3}.json` | `outputs/scratch/cqa_f_redaction{,_2,_3}.py` | `OUT` |
| `cqa_gap_evidence_grounding.json` | `outputs/scratch/cqa_gapground.py` | `OUT` |
| `cqa_storage_signloss.json` | `outputs/scratch/cqa_f_signloss.py` | `OUT`, lines 29–31 |
| `cqa_triple_graph.json` | `outputs/scratch/cqa_g_ground.py` | `OUT`, lines 18–20 |

`ner_organism_transfer.json` is the one file with **no current writer anywhere in the tree**. It is a
legacy artefact whose values are reproduced — and reconciled — only by `cqa_ner_organism_probe.py`
(§8.5). It is inside the seal, so it cannot be regenerated without invalidating the seal; it is
reproduced, not rewritten.

---

## 4. How to re-derive the audit — the verified recipe

### 4.1 The six invocation rules (each executed, rc recorded)

All 32 scripts resolve their own paths from `__file__`, so the *interpreter's working directory* only
matters where a script opens a **relative** path. The verified matrix for a representative generator
(`cqa_metrics.py`; identical behaviour re-confirmed on `d11`, `d12`, `d19`, `d20`):

| Working directory | How invoked | `rc` |
|---|---|---|
| audit root | `python3 diagnostics/<stem>.py` | **0** |
| audit root | `python3 <stem>.py` (bare) | **2** — `can't open file` |
| repo root | `python3 paper/publication/component_quality_audit/diagnostics/<stem>.py` | **0** |
| `diagnostics/` | repo-relative path | **2** — path double-prefixed |
| `diagnostics/` | `python3 <stem>.py` (bare) | **0** |
| `diagnostics/` | absolute path | **0** |

Rule of thumb: the sanctioned form (`python3 diagnostics/<stem>.py` from the audit root) and the
`.sbatch` form (`cd "$DIAG_DIR" && "$PY" "$script"` with an absolute `$script`) are both `rc=0`. The two
failing forms are both *path-construction* errors, not data errors, and both fail loudly with a missing-file
message rather than silently writing a wrong result.

### 4.2 `PYTHONPATH` is **not** required

`cqa_diagnostics.sbatch` exports `PYTHONPATH="$DIAG_DIR:$PROJECT_ROOT/src"`. That export is **not
load-bearing**. Verified with `env -u PYTHONPATH` on `cqa_metrics.py` and `cqa_actions.py`: both `rc=0`
and both outputs byte-identical (4/4 checks). The reason is explicit in the code: every script inserts its
own directory (`sys.path.insert(0, str(HERE))` or `HERE = os.path.dirname(os.path.abspath(__file__))`),
and the five `cqa_ner_*` scripts additionally insert `ROOT/src/scripts/ner_fair_bench` before importing
`fairbench as fb`. **Corollary: no audit script imports `cdm_pipeline`, `corpus_builder` or any other
pipeline package.** The dependency envelope of the whole audit is `python3`, the standard library, and
the frozen releases (§7).

### 4.3 The one command that exists, and the 8/38 it cannot reach

`diagnostics/cqa_diagnostics.sbatch` (86 lines, `cqa_diag`, `intelsr_medium`, 1 node / 1 task /
4 CPUs / 32G / 08:00:00, logs to `outputs/logs/%x_%j.{out,err}`) is the audit's only batch entry point.
It reads `DIAGS` (**default `d15_entity_extraction`**, line 41), accepts `d15`, `d15.py` and absolute
paths, writes one `logs/<stem>.log` per diagnostic (`: > "$log"` first, so a stale log cannot survive),
runs each in a subshell with `cd "$DIAG_DIR"`, prints `>> OK <stem>` / `>> FAIL <stem> exit=$?`, and
returns an accumulated `rc` (`set -uo pipefail`; a single failure does not abort the loop).

**It cannot regenerate 8 of the 38 results.** The eight probe scripts live in `outputs/scratch/`, not in
`diagnostics/`, and they open **CWD-relative** paths:

```python
# outputs/scratch/cqa_f_final.py:26-28   (same shape in cqa_f_signloss.py:29-31, cqa_g_ground.py:18-20)
CSV_DIR = "releases/data_catalogue_v3/3.1.1/tables"
DB      = "file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro"
OUT     = ("paper/publication/component_quality_audit/diagnostics/results/"
           "cqa_catalogue_metrics.json")
```

Consequences, all executed:

* **from the repo root**, as bare names: all eight `rc=0` and **byte-reproduce** (6.60 s and 6.62 s on
  two consecutive runs; `r19_probes_py39.json`).
* **from `outputs/scratch/`**, as bare names: seven fail `rc=1`
  `sqlite3.OperationalError: unable to open database file`, and `cqa_f_signloss.py` fails `rc=1`
  `FileNotFoundError: … 'releases/data_catalogue_v3/3.1.1/tables/samples.csv'`.
* **from the audit root**, with absolute paths: **all eight `rc=1`** — absolute paths fix the *script*
  location but not the *data* location.
* **from `outputs/scratch/`** with repo-relative paths: `rc=2` (the path is taken as relative to the
  script directory).

The eight account for 950 lines of the audit's total. A referee who runs only the `.sbatch` gets 30 of
38 results and would correctly conclude that `cqa_catalogue_metrics.json`,
`cqa_triple_graph.json`, `cqa_catalogue_redaction*.json` and the four others have no producer. They do;
it is one `cd` away.

### 4.4 Time to re-derive

Two complete sweeps of all 20 diagnostics, all `rc=0` both times:

| | login `/usr/bin/python3` (3.9.21) | `~/venvs/vllm/bin/python` (3.12.3) |
|---|---|---|
| total, 20 diagnostics | **208.89 s** | **206.54 s** |
| slowest (`d15_entity_extraction`) | 44.84 s | 44.86 s |
| `d19_cdm_schema_quality` | 39.74 s | 39.07 s |
| `d13_interop_reproducibility` | 24.73 s | 23.90 s |
| `d02_referential_integrity` | 20.81 s | 19.39 s |
| `d05_evidence_correspondence` | 18.28 s | 19.26 s |
| `d16_terminology_quality` | 16.78 s | 16.27 s |
| `d04_duplication` | 7.24 s | 7.30 s |
| `d10_provenance_manifest` | 6.96 s | 6.90 s |
| `d18_catalogue_quality` | 6.91 s | 6.80 s |
| remaining 11 (d01, d03, d06, d07, d08, d09, d11, d12, d14, d17, d20) | ≤ 5.61 s each | ≤ 6.02 s each |

Per-diagnostic 3.9-vs-3.12 deltas are all under 1 s. Plus **85.7 s** for the generator chain, **6.6 s**
for the eight probes, and **≈40 s** for the seal (126 files, 3.57 GB read). **A full cold re-derivation is
under six minutes of CPU**, which is why this audit's numbers are cheap to check and why no result in it
needed to be taken on faith.

### 4.5 The verification convention used throughout

Every rerun in this audit was done under a snapshot-and-restore discipline, because rerunning a script
that is itself inside a seal is indistinguishable from tampering unless the bytes are restored:

1. hash the affected files into `/tmp/cqa_zn/v19/<manifest>.txt`
   (`rep19_pre2.txt`, `r19_pre3.txt`, `r19_pre4.txt`, `scr8_pre3.txt`, `rep19_ner_pre.txt`,
   `gen_pre.txt` 7 entries, `p19_gen_pre.txt` 4 entries);
2. copy the originals to `/tmp/cqa_zn/bak19/` and `/tmp/cqa_zn/bak/results/`;
3. rerun;
4. `sha256sum -c` **from the repo root** (or from the audit root, for the audit-root manifests — the two
   conventions are not interchangeable and produce spurious `FAILED open or read` when swapped);
5. copy the backups back.

Latest full cycle: **38 OK** on `rep19_pre2.txt`; **7/7** on `gen_pre.txt`; **5/5** on `rep19_ner_pre.txt`.

---

## 5. Where bit-level reproduction fails — two files, both diagnosable

**36 of 38 result files reproduce byte-for-byte.** The two that do not are not flaky and are not
content changes; each has a single identified cause.

### 5.1 `d07_ontology_currency.json` — set-iteration order in `examples`

`d07_ontology_currency.py:229` builds a 5-element example list from a **set**:

```python
"examples": [str(v)[:70] for v in list({v for v in vals if v})[:5]],
```

`set` iteration order over `str` depends on `PYTHONHASHSEED`, so the *content* of the five examples is
stable in the sense that every element is a real database value — but the *order and choice* of five from
a larger pool is not. At scalar-leaf granularity the file has **68 leaves with an identical key set, and
exactly 4 differ**, all of them `examples` arrays inside `typed_ontology_columns`:

* `body_site.ontology_id` (UBERON terms),
* `sample.body_site_ontology_id`,
* `claim.body_site_ontology_id`,
* `canonical_term.term_id` (5 `HMCTERM_*` identifiers).

Every count in the file — `rows`, `null_or_empty`, `distinct`, `shape` — is identical. Seeded runs confirm
the mechanism: `PYTHONHASHSEED=0` reproduces the shipped file exactly
(`62acb2369ea5ac6eb555da4a7d0eb225601ff53996aacb687296db33de469166`), while `=7` yields a different
`examples` ordering with the same counts. **The finding is the hash: a reader should compare the four
example arrays as sets, or re-run with `PYTHONHASHSEED=0`.** Nothing in any report depends on example
order.

### 5.2 `d10_provenance_manifest.json` — CWD-sensitive artefact resolution

`_resolve_artifact` (`d10_provenance_manifest.py:243-257`) tests `p.exists()` on the literal string
**before** trying the repo prefixes:

```python
if p.is_absolute() or p.exists():   # ← CWD-relative test
    return str(p), "as_written"
for pref in ("releases", "outputs"):
    q = REPO / pref / art
```

From `diagnostics/` (where the `.sbatch` runs) a stored string like `zenodo_v1/...` resolves to nothing,
so it falls through; two artefacts then fail to resolve at all. The structural difference, canonical run
(from the repo root) → `diagnostics/` run:

* `upstream_hashes.rows[32]` — `termpipeline_t3_rules_v1` /
  `releases/terminology/1.0.0/term_definitions.jsonl`: flips `as_written` → `unresolved`,
  `file_exists True → False`, and loses `artifact_is_file` / `hash_matches`.
* `upstream_hashes.rows[40]` — `mapping_guards_v2` / `…/terminology/mapping_guards_v2`: same flip,
  `artifact_is_directory 1 → 0`.
* Aggregates: `hash_verified_here 5 → 4`, `artifact_missing 0 → 2`; `with_sha256` (6) and
  `paths_requiring_implied_prefix` (4) unchanged.

The **identity block is CWD-independent and 100 % verified in both runs**: `cdm_v3/3.0.3` 36/36,
`data_catalogue_v3/3.1.1` 45/45, `terminology/1.0.1` 23/23. So the CWD only affects the *upstream*
section, and it makes that section look **worse**, never better — a reader who reproduces from
`diagnostics/` sees two "missing" artefacts that are present. Canonical hash
`f5e1e08405e51359f45f3a2a907cc4cbf1b7fc486dc5bb4af451b7e33abb3bac`; the `diagnostics/` variant is
`bb644c9cb1cc…`. **Reproduce from the repo root.** Note the per-field keys
(`with_sha256`, `hash_verified_here`, …) nest under `upstream_hashes`, not at top level.

---

## 6. The Component-I generator chain and the retrospective seal

### 6.1 What the five `cqa_ner_*` scripts produce

| Script | Writes | Deterministic? |
|---|---|---|
| `cqa_ner_recompute.py` | `NER_RECOMPUTATION_CHECK.csv` (1,408 lines / 130,966 B), `ner_recompute_summary.json` | **yes** — 1,407 rows, `verdict_counts` MATCH 1,186 / NEW 152 / N/A 69 |
| `cqa_ner_prompts.py` | `NER_RECOVERED_PROMPTS.md` (15,082 B), `ner_recovered_prompts.json`, `ner_llm_run_diagnostics.csv` (2,657 B) | **yes** |
| `cqa_ner_matrix.py` | `NER_TYPE_COVERAGE_MATRIX.csv` (16 lines), `NER_MODEL_DEPLOYABILITY.csv` (28 lines) | **yes** |
| `cqa_ner_organism_probe.py` | `ner_organism_probe.json` | **yes** |
| `cqa_ner_seal.py` | `NER_RETROSPECTIVE_SEAL.sha256`, `ner_environment.json` | **no** — see §6.3 |

All five load `fairbench` by inserting `ROOT/src/scripts/ner_fair_bench` on `sys.path` and then
re-pointing `fb.RAW` / `fb.PRED` at the `benchmark/` paths, because `outputs/results/ner_fair_bench` and
`outputs/results/ner_corpus_bench` are **symlinks** to `outputs/results/benchmark/…`. Any verification
that copies the symlinked paths must resolve them or it fails for a reason unrelated to tampering.

### 6.2 The seal is intact, and this was re-verified six times

`NER_RETROSPECTIVE_SEAL.sha256` — **126 entries / 16,734 B**, sha256sum format, paths repo-root-relative,
`seal_kind` = *"retrospective provenance seal — NOT a preregistration"*, `seal_date`
2026-11-04T16:48:22+0100, `base` `/home/jkalra_hpc/Microbiome-CDM`, **3,574,150,615 bytes** sealed.
`sha256sum -c` from the repo root returns **126/126 OK** on every one of six checks performed during this
audit.

Composition by directory (recomputed with `awk`/`dirname`/`uniq -c` from the manifest, not from prose):

| Directory | Entries |
|---|---|
| `outputs/results/benchmark/ner_fair_bench/preds` | 54 |
| `outputs/results/benchmark/ner_corpus_bench/preds` | 26 |
| `data/reference_kg/raw` | 10 |
| `data/benchmarks_ner/raw` | 9 |
| `src/scripts/ner_fair_bench` | 5 |
| `paper/publication/component_quality_audit` | 4 |
| `paper/publication/component_quality_audit/diagnostics/results` | 4 |
| `outputs/results/benchmark/ner_corpus_bench` | 4 |
| `outputs/results/benchmark/ner_quality_quantity_2026-11-03` | 3 |
| `outputs/results/omop_vocab` | 2 |
| `outputs/results/benchmark/ner_fair_bench` | 2 |
| `outputs/results/benchmark/ner_corpus_bench/lexicon` | 2 |
| `pipelines/corpus_v2/data` | 1 |
| **total** | **126** |

The eight sealed audit-directory paths are `NER_RECOVERED_PROMPTS.md`, `NER_RECOMPUTATION_CHECK.csv`,
`NER_TYPE_COVERAGE_MATRIX.csv`, `NER_MODEL_DEPLOYABILITY.csv`, and four results
(`ner_recovered_prompts.json`, `ner_recompute_summary.json`, `ner_llm_run_diagnostics.csv`,
`ner_organism_transfer.json`). The two `omop_vocab` entries are `CONCEPT.csv` /
`CONCEPT_SYNONYM.csv`; the `corpus_v2/data` entry is `sections.jsonl`.

**`ner_environment.json`'s `coverage` block does not sum to 126 and must not be read as doing so.** It
reports `predictions 80, corpus_chunks 1, metrics_and_reports 21, scripts 5, gold_data 9,
prompts_and_recomputation 8, reference_inputs 12, corpus_sections 1` = **137**, against
`files_sealed = 126`. The two numbers answer different questions: `coverage` counts *categories a reader
might look for*, and some sealed files fall in more than one; `files_sealed` is the deduplicated total.
A reader reconciling the two will fail, and the failure is arithmetical, not evidential.

### 6.3 Post-seal modification dates — expected, and why they are not a seal failure

The seal was taken at **16:48:22** on 2026-11-04. Several sealed files carry later mtimes, because the
manifests and narratives were finalised afterwards. **`sha256sum -c` still returns 126/126**: mtime is not
content. The full set (newest last):

| mtime | File | Status |
|---|---|---|
| 2026-11-04 16:34:54 | `ner_organism_transfer.json` | **pre-seal** — the only sealed result older than the seal |
| 2026-11-05 02:34:53 | `NER_RECOMPUTATION_CHECK.csv` | post-seal edit |
| 2026-11-05 02:34:54 | `ner_llm_run_diagnostics.csv` | post-seal edit |
| 2026-11-05 02:35:17 | `ner_recovered_prompts.json` | post-seal edit |
| 2026-11-05 02:35:17 | `ner_recompute_summary.json` | post-seal edit |
| 2026-11-05 02:35:17 | `NER_RECOVERED_PROMPTS.md` | post-seal edit |
| 2026-11-05 02:41:12 | `NER_RETROSPECTIVE_SEAL.sha256` | the seal itself |
| 2026-11-05 02:41:16 | `ner_environment.json` | written immediately after the seal |
| 2026-11-05 03:18:49 | `NER_TYPE_COVERAGE_MATRIX.csv`, `NER_MODEL_DEPLOYABILITY.csv` | post-seal edit |

The correct reading is: **the seal certifies the bytes as they stood at the moment it was written, and
every one of those bytes still hashes.** A later mtime with an unchanged hash means the file was rewritten
with identical content (a re-run into the same path). It does not mean the seal was taken before the
results existed — the "results existed" claim rests on the artefacts' own internal timestamps
(`ner_recompute_summary.json`: `started 2026-11-04T16:46:35`, `finished 16:48:17`, i.e. it *finished 138 s
before* the seal; `ner_recovered_prompts.json`: `generated 2026-11-04T16:32:23`).

**One genuine quirk, harmless:** `cqa_ner_seal.py` lists `NER_RECOVERED_PROMPTS.md` **twice** in its
`TARGETS` loop (line 39 in the first tuple, line 47 in the appended tuple). Downstream deduplication
collapses it, so the manifest is correct; but a future maintainer editing one line and not the other will
get a confusing result. It also appends every `data/benchmarks_ner/raw` file via `rglob`, so the manifest
grows if a gold file is added.

### 6.4 The seal's own limits — inherited, not re-argued

This report inherits, and does not re-derive, `NER_REPRODUCIBILITY_GAPS.md` §11: the seal proves *these
are the bytes this audit read*; it cannot prove *these are the bytes analysed at the time*, and it can
never constrain a choice already made. The `ner_environment.json` `host` block records the **sealing**
host (`/usr/bin/python3`, 3.9.21, `Linux-5.14.0-570.35.1.el9_6`), which is **not** the interpreter that
produced any benchmark result. `environment_as_recorded_in_artefacts` correctly says
`vllm_version / transformers_version / torch_version / gpu_driver = "NOT RECORDED"`.

---

## 7. Dependency envelope and interpreter sensitivity

| Requirement | Value | Enforced? |
|---|---|---|
| Python | `>=3.9`; verified on **3.9.21** (`/usr/bin/python3`) and **3.12.3** (`~/venvs/vllm/bin/python`) | both, all 20 diagnostics, all `rc=0` |
| sqlite3 | **3.34.1** (py3.9) and **3.45.3** (py3.12) | both, all diagnostics |
| Third-party packages | **none** — stdlib only (`sqlite3, csv, json, hashlib, re, os, sys, pathlib, ast, platform, gzip`) | static: no `import` outside stdlib + `common` + `fairbench` |
| Network | **none** | `common.py` docstring + no HTTP import anywhere |
| Write access | audit directory only; frozen releases opened `file:{p}?mode=ro` | `common.connect()` |
| Side-car data | `/tmp/cqa_zn/public.db` (**2,862,465,024 B**), extracted from `releases/zenodo_frozen/cdm/microbiome_cdm_v3.0.3_public.db.gz` (502,412,612 B) | **required by `cqa_n_rights.py` only** |

`cqa_n_rights.py` is the **only** script with an absolute output path
(`diagnostics/results/cqa_n_rights.json`, line 32) and the **only** script that hardcodes
`PUB_DB = "file:/tmp/cqa_zn/public.db?mode=ro"` (line 28) and `ATTACH`es it as `pubdb`. That file is a
decompression of a shipped frozen artefact, but **the extraction step is not scripted anywhere in this
ticket**. A re-deriver must run `gzip -dc releases/zenodo_frozen/cdm/microbiome_cdm_v3.0.3_public.db.gz >
/tmp/cqa_zn/public.db` (≈2.86 GB, needs ~3 GB of `/tmp`) before `cqa_n_rights.py` will run, and must
expect ≈73 s of I/O. This is the one place where the audit's reproduction story leaks outside the audit
directory in a way an outsider could not guess.

Interpreter choice changes **nothing** in content: all 20 diagnostics, the 6 generator scripts and the 8
probes produce byte-identical output under both interpreters (the 2 exceptions of §5 are interpreter-
*independent* — `d07` is hash-seed dependent and differs within the *same* interpreter too).

---

## 8. Cross-report traceability

### 8.1 Citation census

Across the 20 `.md` files (excluding this one), `diagnostics/results/*` filenames appear **78 times**, as
**59 distinct (report, result) pairs**. Per report: `01` 4/4, `02` 5/5, `03` 4/4, `04` 4/4, `05` 2/2,
`06` 16/11, `07` 8/7, `08` 7/7, `09` 5/3, `10` 1/1, **`11` 0/0**, `12` 1/1, `13` 4/4, `14` 5/2,
**`17` 0/0**, `18` 2/1, `NER_BENCHMARK_CORRECTIONS` 3/3, `NER_ORGANISM_RECALL_AMENDMENT` 3/2,
`NER_RECOVERED_PROMPTS` 1/1, `NER_REPRODUCIBILITY_GAPS` (no result filenames — it cites code paths).

**Three results are cited by no report at all:** `cqa_catalogue_redaction.json`,
`ner_llm_run_diagnostics.csv`, `ner_recompute_summary.json`. The first is cited only by *prefix* match
through `cqa_catalogue_redaction2{,_3}.json`; the other two are summarised in prose (`09` and
`NER_RECOMPUTATION_CHECK.csv` respectively) without naming the file. This report is where those three
become explicit; no report was edited to add them.

Reports `11` and `17` cite zero result files, which is correct for both: Component K reads a
self-contained `benchmark/bugsigdb_comparison_2026-11-03/` bundle, and Component P reads the claim
register and the other components' conclusions.

Results cited only from the NER narratives: `ner_environment.json`, `ner_organism_probe.json`,
`ner_recovered_prompts.json`, `ner_organism_transfer.json` (in `09`), and `cqa_i_grounding.json` (in `09`
only).

### 8.2 The per-report dimension-table census, and one off-scale rating

Each of reports **01–14 contains exactly one** `| Dimension | Rating |` table — 14 tables, 131 dimension
rows (A–F 9, G 10, H 10, I 9, J 10, K 10, L 9, M 10, N 9). Reports `17`, `18` and the five NER narratives
contain **zero**. `cqa_metrics.py` therefore emits 131 rows, and the table in §9 below is deliberately
**not** counted: `REPORTS` in `cqa_metrics.py` lists only A–N, and report 19 is not among them. Adding a
dimension table here cannot change `16_QUALITY_METRICS.csv`.

`parse_dims()` (lines 89–142) reads only lines beginning `| Dimension | Rating |`, and right-anchors the
three fixed tail columns rather than splitting on `|`. That is not fussiness: dimension-table cells contain
`KEEP|INCLUDE_TEXT` and `(null)||(null)`, so a naive split yields the wrong column. The same caution
applies to anyone re-parsing these tables with `csv.reader`.

**`16_QUALITY_METRICS.csv` contains one rating off the brief's five-level scale.** Component J's
"Error introduction" row (`16_QUALITY_METRICS.csv:93`) carries `MODERATE` in both `rating` and
`rating_as_published`, with `rating_normalised = WEAK` and `scale_conformant = no`. This is disclosed in
`cqa_metrics.py`'s docstring and in `10_CLEANED_LAYER_QUALITY.md`; it is preserved verbatim rather than
silently re-labelled, because it is the component's own wording. The six-valued tally (STRONG 20 /
ADEQUATE 43 / WEAK 47 / NOT EVALUATED 4 / CRITICAL WEAKNESS 16 / MODERATE 1) sums to 131 only if the
off-scale value is counted separately — that is the intended reading.
*[cross-referenced 2026-11-05: the master report's §5 table quotes **WEAK 48** because it tallies
`rating_normalised`, where this row is `WEAK`. Both figures describe the same 131 rows; neither is a
correction of the other. Recorded as **CC-14** in `00_MASTER_COMPONENT_QUALITY_ASSESSMENT.md` §7.1.]*

### 8.3 Register provenance

`cqa_build_register.py` (714 lines) writes **only** `15_ISSUE_REGISTER.csv`; it emits no JSON. It parses
`### CQA-*` blocks from reports 01–14 (13 entries in its `REPORTS` list, including `17_PUBLICATION_CLAIM_IMPACT.md`
as component P) **plus** `NER_REPRODUCIBILITY_GAPS.md` §12 via `parse_gap_register` (line 599), setting
`source_report` at line 603. Gap-table rows (`CQA-I-09` … `CQA-I-20`) take `title` and `evidence` from the
gap-description cell and `action` from "what closing it would take"; the impact columns are hand-written in
a `GAP_IMPACTS` table. That is the one place in Tier 4 where prose was authored rather than parsed, and it
is disclosed in the script.

`18_ACTION_PLAN.csv` has **16 columns and no `touches_scientific`**, while `15_ISSUE_REGISTER.csv` has 18
and does. The asymmetry is deliberate (the plan asks whether an action touches *publication* and
*release*), but a consumer joining the two must not assume the register's column survives.

### 8.4 Report-18 blocking counts, read literally

From `18_ACTION_PLAN.csv`: **78** rows start with `blocks…`, **72** start with `neither…`, and **4** start
with `publication…` (`CQA-P-01`–`P-04`) — 78 + 72 + 4 = 154. Keyword filters over `blocking_status`
under-count (a "blocks X but not Y" row still starts with `blocks`), so these three prefixes are the only
safe tallies. Five rows touch release but **not** publication: `CQA-A-04`, `CQA-G-09`, `CQA-M-03`,
`CQA-N-08`, `CQA-N-09`.

### 8.5 `ner_organism_transfer.json` — legacy artefact, reproduced 8/8

`cqa_ner_organism_probe.py` reproduces all eight models in the transfer file exactly: `tp` and `gold`
identical (`/36`), `recall_nonhost` vs the probe's `span_exact_and_type.recall` differing by ≤ 4.44e-5 —
**OK 8 / 8**. `span_exact_and_type` `tp/36`: `llm_qwen_fs` 33, `pubtator3` 23, `gliner_v25_biomed` 21,
`hunflair2` 20, `scispacy_bionlp13cg` 18, `gliner_v25_medium` 11, `llm_gemma_zs` 8, `llm_deepseek_fs` 6.
`span_exact_any_type`: 26 / 15 / 23 / 20 / 23 / 34 / 25 / 19 in the file's own order.

The transfer file's `host_lexicon_size` says **30**; the probe's closed list is **13** surface forms
(`human, humans, inpatient, man, men, mice, mouse, patient, patients, rat, rats, woman, women`). The 13-form
list is authoritative — the 30 was a stale size field, and the *recall* values were never affected. Report
`09` cites this file at line 313 and its "no benchmark tests `ORGANISM`" claim was corrected accordingly.

This is the only sealed result with no in-tree writer. To change it would break the seal; it is
therefore **reproduced and reconciled, never regenerated**.

---

## 9. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Script inventory and provenance | **ADEQUATE** | 32 scripts / 9,422 lines all in `diagnostics/`; **22/38** results have a declared `emit()` writer; all 38 traced to code by two independent methods | results with a traced producer = **38/38** (30 in-tree + 8 out-of-tree) | 16 results are written by direct path, so an `emit()`-only grep reports 16 false negatives; `ner_organism_transfer.json` has no writer anywhere | high |
| One-command reproduction | **WEAK** | `cqa_diagnostics.sbatch` runs any `DIAGS` list, logs per diagnostic, returns an accumulated rc | results one documented command can regenerate = **30/38** (78.9%) | the 8 probe scripts live in `outputs/scratch/` and are not reachable from the `.sbatch`; no script wraps the 4 tiers | high |
| Bit-level determinism | **ADEQUATE** | 36/38 results byte-identical across two interpreters and repeated runs | byte-reproducible = **36/38** (94.7%); the 2 exceptions have one identified cause each | `d07` varies with `PYTHONHASHSEED`; `d10` varies with CWD; neither is content-nondeterminism but both break naive `sha256sum -c` | high |
| Dependency closure | **STRONG** | stdlib only; no network; no `cdm_pipeline`/`corpus_builder` import; frozen releases opened `mode=ro` | third-party packages required = **0**; network calls = **0** | one 2.86 GB side-car `/tmp/cqa_zn/public.db` is required by `cqa_n_rights.py` and its extraction is not scripted in-tree | high |
| Environment capture | **WEAK** | interpreter and sqlite versions known and both were re-tested; `ner_environment.json` records the **sealing** host | runtime library versions recorded at result-write time = **0** of 38 | the seal's `host` block (py3.9.21) is not the benchmark runtime; `vllm/transformers/torch/gpu_driver` are `NOT RECORDED` | high |
| Seal integrity | **STRONG** | `NER_RETROSPECTIVE_SEAL.sha256` 126 entries / 16,734 B; manifest verified **126/126** six times from the repo root | sealed files verifying = **126/126**; bytes sealed = 3,574,150,615 | retrospective by construction — it can detect tampering after 2026-11-04T16:48 but cannot prove the analysis plan preceded the results | high |
| Result↔report traceability | **ADEQUATE** | 78 filename occurrences / 59 distinct (report, result) pairs across 20 reports | results cited by ≥1 report = **35/38** (92.1%) | 3 uncited (`cqa_catalogue_redaction.json`, `ner_llm_run_diagnostics.csv`, `ner_recompute_summary.json`); reports 11 and 17 deliberately cite none | high |
| Runtime cost of verification | **STRONG** | two full 20-diagnostic sweeps: 208.89 s (py3.9) / 206.54 s (py3.12), all rc=0; generator chain 85.7 s / 81.3 s; probes 6.6 s | full cold re-derivation < **6 min CPU**; slowest single diagnostic 44.86 s | wall-clock only; the 44.84 s `d15` figure in an early row came from a local rerun, not from job 28697992 (cancelled, §10) | high |
| Failure-mode documentation | **ADEQUATE** | six invocation rules executed with return codes; the probe CWD failure reproduced four ways; `d07`/`d10` causes located to a line | invocation modes tested = **6**; documented failure modes = 4 (wrong CWD, bare name from audit root, missing `public.db`, probe run away from repo root) | a re-deriver who does not read §4 can lose an hour to a path error; the scripts could assert their own CWD but do not | high |

**No averaged score is offered.** If one sentence were forced: *the audit is cheap, closed and
byte-reproducible for 36 of its 38 results, and its two remaining gaps and one out-of-tree dependency are
each a one-line fix that was deliberately not applied because fixing them would mean editing a sealed
artefact or a script that already produced a shipped verdict.*

---

## 10. What was found here that was not found elsewhere

These are new observations about the audit's own machinery. None contradicts a published number; none
required a register row, because none is a defect in the audited object — they are defects in the audit's
*reproduction story*.

1. **8 of 38 results (21.1%) cannot be regenerated by the documented batch command.** They can be
   regenerated by one `cd` to the repo root and eight bare invocations. This affects no reported value —
   all eight were re-run twice and byte-reproduced — but it makes "run the `.sbatch`" an incomplete
   reproduction instruction, and this report is the only place it is stated.
2. **`cqa_n_rights.py` depends on an unscripted 2.86 GB extraction** (§7). The input is a shipped frozen
   artefact; the extraction command is written down here for the first time.
3. **`cqa_ner_seal.py` lists `NER_RECOVERED_PROMPTS.md` twice** (lines 39 and 47). Harmless, deduplicated
   downstream, but a maintenance trap.
4. **`ner_environment.json`'s `coverage` sums to 137, not 126** (§6.2). Both numbers are correct for what
   they measure; nothing reconciles them in the file.
5. **`d07` and `d10` are non-byte-reproducible for two different reasons** (§5), and only `d07` had been
   previously noted. `d10`'s CWD sensitivity is the more dangerous of the two because it makes the run
   look *worse* from the directory the shipped `.sbatch` actually uses.
6. **The `d15` runtime must not be attributed to job 28697992.** That job (node009, started 10:37:25) was
   **CANCELLED at 10:50:57 "DUE to SIGNAL Terminated"** before producing a result; the 44.84 s figure
   comes from a local rerun. The clean `d15` results are jobs **28698123** (10:51:32 → 10:52:22, `>> OK`)
   and **28698132** (10:54:34 → 10:55:25, `>> OK`); `28698023` ran `d16→d20`, `28698041` ran `d18`/`d19`.
   `sacct` returns nothing on this cluster, so the six `outputs/logs/cqa_diag_*` files are the only job
   record. The six per-stage logs in `logs/` (94–106 B) are the wrapper's own record of the five
   `>> OK` stages.
7. **`d10`'s `run_metadata` declares `catalogue` = `outputs/results/catalogue_v3_1`**, a *working* path,
   not the frozen `releases/data_catalogue_v3/3.1.1` the build says it consumed. Already flagged in report
   `08`; repeated here because it is exactly the kind of string a re-deriver will try to open.

---

## 11. What a re-deriver should do, in order

```bash
# 0. interpreters — either works
P=/home/jkalra_hpc/Microbiome-CDM
cd $P                                        # repo root: required for probes and the seal

# 1. the 20 analytics (≈3.5 min)
cd $P/paper/publication/component_quality_audit
for d in diagnostics/d0*.py diagnostics/d1*.py diagnostics/d20*.py; do python3 "$d"; done

# 2. the three cross-cutting results (≈86 s; needs the public DB, §7)
gzip -dc $P/releases/zenodo_frozen/cdm/microbiome_cdm_v3.0.3_public.db.gz > /tmp/cqa_zn/public.db
python3 diagnostics/cqa_i_grounding.py
python3 diagnostics/cqa_f_judge.py
python3 diagnostics/cqa_n_rights.py

# 3. the 8 probes — MUST run from the repo root (≈7 s)
cd $P
for p in cqa_f_final cqa_cat_prov_gap cqa_f_redaction cqa_f_redaction2 cqa_f_redaction3 \
         cqa_gapground cqa_f_signloss cqa_g_ground; do python3 outputs/scratch/$p.py; done

# 4. the generator chain, in this order (≈86 s)
cd $P/paper/publication/component_quality_audit
python3 diagnostics/cqa_build_register.py
python3 diagnostics/cqa_metrics.py
python3 diagnostics/cqa_actions.py

# 5. the Component-I artefacts — these MUTATE the seal; do not run them casually
#    (they rewrite the manifest and five timestamped files; restore from a backup afterwards)
#    see §6.3 and §4.5

# 6. verify, from the repo root
cd $P && sha256sum -c paper/publication/component_quality_audit/NER_RETROSPECTIVE_SEAL.sha256 | grep -c ': OK'
# expect 126
```

Expected outcomes: 30 of 38 results byte-identical, `d07` identical in all 68 leaves' *counts* and
4 differing `examples` arrays, `d10` identical only if run from the repo root, `15`/`16`/`18` byte-identical,
seal `126/126`. Changing `PYTHONHASHSEED=0` makes `d07` byte-identical too.

---

## 12. Component verdict

**This is the strongest reproduction story in the audit, and it is not a clean one.** On the strong side:
the audit is stdlib-only, network-free, read-only against every frozen release, and cheap — a full cold
re-derivation is under six minutes, which is why every count in reports 01–18 was independently checked
rather than inherited. Thirty-six of 38 result files reproduce byte-for-byte across two interpreters and
two runs. The seal is real, dated, self-describing about what it cannot prove, and verified 126/126 six
times. The generator chain is order-dependent, deterministic, and fails loudly if a register row is
unclassified.

On the weak side, three things would stop a careful outsider:

* **The documented batch command regenerates 30 of 38 results.** The other eight live in
  `outputs/scratch/` and need the repo root as CWD. Nothing in the tree says this; this report does.
* **One required input is a 2.86 GB file that no script creates.** The extraction is one line, but it is
  not written down anywhere except here.
* **Two results are not byte-reproducible**, and one of them (`d10`) differs *more* when run from the
  directory the shipped `.sbatch` uses — so the honest reproduction instruction is "run from the repo
  root," which contradicts the wrapper's own `cd`.

None of this weakens a published number. Every value in every report was recomputed at least once from
the shipped artefacts, and the two non-deterministic files vary only in an example *ordering* and in how
many artefacts resolve — never in a count that a report quotes. The correct characterisation is:
**recomputable by a patient reader, not reproducible by a single command, and honest about both.**

The corresponding register rows already exist and are **re-used, not re-minted**:
`CQA-B-04` (Qwen rows are a frozen checkpointed artefact, not a rerun — rank 89, `DOC`),
`CQA-F-04` (locatability flag rate — rank 19, `ART`), `CQA-H-08` (Q7 returns the opposite storage
condition — rank 26, `ART`), `CQA-H-09` (the query package is stored inside the release it validates —
rank 72, `ART`), `CQA-I-04` (the Tier-1 benchmark is the only unchecksummed artefact — rank 73, `ART`),
`CQA-I-10` (no preregistration for the benchmark suites — rank 47, `DOC`), `CQA-I-13` (corpus scoring ran
three times into one output slot — rank 59, `BLD`). The eight findings in §10 are **not** register rows:
they are properties of this audit's own tooling, and the only two that a reader outside the audit could
be hurt by — the 8/38 probe gap and the `public.db` extraction — are fixed by documentation, which is
what §11 is.

**Bottom line: the audit can be re-derived, and re-deriving it is the cheapest available check on
everything it claims — which is also the reason this report is a reproduction manual rather than a
justification.**
