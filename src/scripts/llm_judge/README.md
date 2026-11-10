# LLM-as-Judge Pipeline (`scripts/llm_judge/`)

At-scale **LLM-as-judge** evaluation of the `corpus_v2` extraction pipeline.

> **Framing.** This is an LLM-as-judge evaluation, **not** a human gold standard
> and **not** human validation. It measures how a judge model scores the
> extractor's outputs; a small 10-item human calibration sheet only checks
> whether the *judge* is trustworthy enough to run, not whether the extractor is
> correct.

- **Extractor under audit:** Qwen 3.5:9b (Qwen family).
- **Judge:** `google/gemma-4-E4B-it-qat-w4a16-ct` (Gemma family; official Google
  QAT 4-bit, vLLM-native compressed-tensors). Cross-family by design.
- **No secrets** are read or written; the judge model id comes from `--model` /
  `$JUDGE_MODEL` / the live vLLM server.

## Files

| file | stage | purpose |
|---|---|---|
| `build_inputs.py` | P2 | normalize the 3 artifact sets into `*_input.jsonl` |
| `sample_stratified.py` | P3 | deterministic stratified 10k sample |
| `prompts/c1_record.txt` | P4 | record evidence-support prompt |
| `prompts/c2_type.txt` | P4 | type correctness + agreement prompt |
| `prompts/c3_mapping.txt` | P4 | ontology mapping prompt |
| `prompts/c4_triple.txt` | P4 | triple-coherence prompt |
| `run_judge.py` | P5 | async OpenAI-compatible runner (+ `--dry-run`) |
| `compute_judge_metrics.py` | P6 | verdict dist, Wilson CI, chi-square |
| `make_calibration_sheet.py` | P7 | 10-item human calibration sheet |
| ~~`judge_sample.sbatch`~~ | — | phase-1 GPU launcher, **retired** — moved to `scratch/removed_launchers/`. Superseded by `scripts/llm_judge_a40/run_judge_a40.sbatch` |

## Build (offline, no GPU)

```bash
python scripts/llm_judge/build_inputs.py          # -> logs/gold_standard/labeled/*_input.jsonl
python scripts/llm_judge/sample_stratified.py     # -> sample_input.jsonl + sample_strata.json
python scripts/llm_judge/run_judge.py --prompt c1_record --dry-run   # prompt render check
```

### Input sizes (full set = 423,929 items)

| artifact | rows | bytes | join |
|---|---:|---:|---|
| triples | 32,713 | 16.1 MB | mention 100.0% |
| mappings | 334,231 | 77.5 MB | definition 1.8% (only 1,150 defs exist) |
| records | 56,985 | 55.2 MB | section 100.0% (11,743 null-span by design) |

### Sample (10,000 items)

- triples 2,500 (stratified by `relation`, 78 strata)
- mappings 5,000 (stratified by `mapping_relation`, 4 strata)
- records 2,500 (stratified by `entity_type`, 6 strata)

Selection is deterministic: rank by `sha1("judge-v1|" + item_id)`, take the K
smallest per stratum with largest-remainder proportional allocation. Hidden
fields (`confidence`, `verification_status`, `mapping_relation`, `extraction_method`,
…) are never placed in a prompt; `_stratum` is stripped before writing the sample.

## Run (GPU)

The A100 launcher `judge_sample.sbatch` was retired and moved to
`scratch/removed_launchers/scripts/llm_judge/`. Use the A40 single-job pipeline instead:

```bash
sbatch scripts/llm_judge_a40/run_judge_a40.sbatch          # full sample (4 x 500 items)
LIMIT=200 sbatch scripts/llm_judge_a40/run_judge_a40.sbatch # smoke test
```

See `scripts/llm_judge_a40/README.md`. The retired two-job A100 form failed twice
(a GPTQ checkpoint could not load the multimodal audio tower; and a server that
holds its allocation to walltime can never fire `afterok` for an attached eval job).

The launcher starts a node-local vLLM server, runs the four prompts, then writes
metrics and the calibration sheet. `run_judge.py` exits non-zero if > 1% of items
fail.

## Verdict vocabularies

| prompt | verdicts |
|---|---|
| c1_record | `SUPPORTED \| PARTIALLY_SUPPORTED \| NOT_SUPPORTED \| UNCERTAIN` |
| c2_type | inventory `CORRECT\|INCORRECT\|UNCERTAIN`; canonical `CORRECT\|INCORRECT\|UNCERTAIN`; agreement `AGREE\|DISAGREE\|UNCERTAIN` |
| c3_mapping | `VALID \| INVALID \| TOO_BROAD \| TOO_NARROW \| UNCERTAIN` |
| c4_triple | `SENSIBLE \| PLAUSIBLE_BUT_WEAK \| NONSENSE \| UNCERTAIN` |

## Calibration gate

`HUMAN_CALIBRATION_SHEET.csv` has 10 items (3 triples / 3 mappings / 2 records /
2 worst-cases by lowest judge confidence). If **≥ 8/10** human verdicts match the
judge, run full scale; if **< 8/10**, drop the corresponding claim and revise the
prompts/model first. See `HUMAN_CALIBRATION_INSTRUCTIONS.md`.

## Scope notes

- The 10k sample covers three artifacts (records/triples/mappings). `c2_type`
  has no artifact in the sample; the launcher runs it only if `types` rows are
  added. The four C1–C4 prompt families are otherwise complete.
- Outputs land in `logs/gold_standard/labeled/`. Frozen artifacts
  (`corpus_v2/releases/2.2.0`, `data_catalogue/`, `releases/terminology/1.0.0/`)
  and the four original sheets are read-only and untouched.
