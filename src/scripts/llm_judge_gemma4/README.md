# LLM-as-judge evaluation — Gemma 4 E4B (4-bit)

A build-only, GPU-backed evaluation of the automated extraction pipeline
(**extractor: Qwen 3.5:9b**) using an **independent judge model**, Gemma 4 E4B
(4-bit, thinking disabled), served by vLLM on Slurm A100s.

> **This is LLM-as-judge, NOT human validation and NOT a human gold standard.**
> A 10-item human calibration sheet (`../logs/llm_judge/HUMAN_CALIBRATION_SHEET.csv`)
> is required before any claim is made; the judge output alone is not a gold standard.

## Layout

| file | stage | purpose |
|---|---|---|
| ~~`start_vllm.sbatch`~~ | P2 | **retired** — moved to `scratch/removed_launchers/scripts/llm_judge_gemma4/deprecated/` |
| `run_judge_client.py` | P2 | async OpenAI-compatible judge client |
| `prompts/metric_*.txt` | P3 | 7 metric prompt templates (self-contained, JSON out) |
| `build_inputs.py` | P4 | deterministic 500-item samples → `logs/llm_judge/input_C*.jsonl` |
| ~~`run_sample_eval.sbatch`~~ | P5 | **retired** — moved to `scratch/removed_launchers/`; superseded by `scripts/llm_judge_a40/run_judge_a40.sbatch` |
| `compute_judge_metrics.py` | P6 | per-artifact × metric rates, Wilson CIs, repair queue |
| `run_repair.py` + `prompts/repair_fullsection.txt` | P7 | second-pass re-judge of flagged items |
| `make_calibration_sheet.py` | P8 | 10-item human calibration sheet + instructions |
| `README.md` | P9 | this file |

## Environment

- Cluster **marvin**, login `login01`; no vLLM module — use the venv:
  `/home/jkalra_hpc/venvs/vllm/bin/python` (Python 3.12.3, vLLM 0.32.0).
- Modules: `Python/3.12.3-GCCcore-13.3.0`, `CUDA/12.9.1`
  (`module use /opt/software/easybuild-AMD/modules/all`).
- GPU partition **`sgpu_short`** (`gpu:a100:4` per node; 8 h walltime).
- `HF_HOME=$HOME/llm/hf-cache-gemma4-w4a16`; `HF_HUB_OFFLINE=1` at serve time
  (model is pre-downloaded).

## Model & quantization

- Chosen judge: **`ciocan/gemma-4-E4B-it-W4A16`** — GPTQ, 4-bit W4A16,
  ~10.1 GB, arch `Gemma4ForConditionalGeneration`.
- AWQ (`cyankiwi/gemma-4-E4B-it-AWQ-4bit`) is **not published**; the documented
  fallback is `google/gemma-4-E4B-it-qat-w4a16-ct` (compressed-tensors, W4A16).
- Served with `--quantization gptq --tensor-parallel-size 2
  --gpu-memory-utilization 0.90 --max-model-len 8192` and
  `--default-chat-template-kwargs '{"enable_thinking": false}'`.
- Expected GPU memory: ~10 GB total → ~5 GB/GPU at TP=2.

> **Risk:** GPTQ support for the multimodal `Gemma4ForConditionalGeneration` is
> unverified on vLLM 0.32.0. If the server fails to start, switch `JUDGE_MODEL`
> to the compressed-tensors fallback (set `JUDGE_QUANT=compressed-tensors`).

## Reproduce

```bash
cd /home/jkalra_hpc/Microbiome-CDM

# P4 — build the 4 x 500-item samples (CPU, read-only against frozen artifacts)
/home/jkalra_hpc/venvs/vllm/bin/python scripts/llm_judge_gemma4/build_inputs.py

# P2/P5 — the two-job A100 form is RETIRED (moved to
# scratch/removed_launchers/). It failed twice: a GPTQ checkpoint could not load
# the multimodal audio tower, and a server that holds its allocation to walltime
# can never fire afterok for an attached eval job. Use the single-job A40 pipeline:
sbatch scripts/llm_judge_a40/run_judge_a40.sbatch          # serve -> poll -> smoke -> judge C1-C4 -> metrics

# P7/P8 — second pass + human calibration (P7 re-judges flagged items and needs a
# running judge server; launch one yourself, or use the A40 pipeline above)
/home/jkalra_hpc/venvs/vllm/bin/python scripts/llm_judge_gemma4/run_repair.py
/home/jkalra_hpc/venvs/vllm/bin/python scripts/llm_judge_gemma4/make_calibration_sheet.py
```

## Sample

**2,000 items total — 500 per artifact** (C1 catalogue records, C2 inventory→
canonical types, C3 ontology mappings, C4 canonical triples). Selection is
deterministic: `sha1("judge-gemma4-v1|" + stable_id)`, ranked, then
proportionally allocated across each artifact's strata (largest-remainder,
≥1 per stratum). Only human-visible fields enter a prompt — no confidence,
`extraction_method`, or internal metadata.

## Metrics (RAGAS-style + task excellence)

| metric | kind | applies to | verdict vocabulary |
|---|---|---|---|
| `metric_faithfulness` | RAGAS | C1, C4 | `FAITHFUL \| PARTIALLY_FAITHFUL \| UNFAITHFUL \| UNCERTAIN` |
| `metric_context_precision` | RAGAS | C1, C4 | `HIGH \| MEDIUM \| LOW \| UNCERTAIN` |
| `metric_context_recall` | RAGAS | C1 | `COMPLETE \| PARTIAL \| MISSING \| UNCERTAIN` |
| `metric_factual_correctness` | task | C2, C3 | `CORRECT \| INCORRECT \| UNCERTAIN` |
| `metric_instruction_following` | task | C1–C4 | `YES \| NO \| PARTIAL` |
| `metric_completeness` | task | C1, C4 | `COMPLETE \| PARTIAL \| INCOMPLETE \| UNCERTAIN` |
| `metric_relevance` | task | C2, C3 | `HIGH \| MEDIUM \| LOW \| UNCERTAIN` |

15 slices × 500 items = **7,500 judge calls**; each returns
`{"verdict", "confidence", "reasoning"}`. UNCERTAIN is excluded from the
numerator and denominator; every rate carries its N and a Wilson 95% CI.

## Cost

7500 calls at ~1.5 s/call with 8 workers ≈ **20–25 min** of wall clock on the
2×A100 server job (~0.8 GPU-h at TP=2). The server itself is requested for
4 h; a `sgpu_short` (8 h) allocation leaves ample headroom for the repair pass.

## Outputs (all under `logs/llm_judge/`)

`input_C1..C4.jsonl`, `_input_stats.json`, `results/{artifact}_{metric}.jsonl`,
`JUDGE_METRICS.md`, `repair_queue.jsonl`, `repair_second_pass.jsonl`,
`REPAIR_REPORT.md`, `HUMAN_CALIBRATION_SHEET.csv`,
`HUMAN_CALIBRATION_INSTRUCTIONS.md`.

## Calibration gate (P8)

Compare the human `human_verdict` against the judge on the 10 sheet items:
**≥ 8/10** agree → run the full-corpus judge; **6–7/10** → report with a
calibration caveat; **< 6/10** → drop the judge-based claim. No item is ever
auto-fixed; both `REPAIR_FAILED` and `REPAIR_DISPUTED` items go to the human queue.
