# LLM-as-judge pipeline — Gemma 4 E4B W4A16 on A40

Single-job LLM-as-judge evaluation of the extracted CDM artifacts, modelled on the
user's existing A40 extraction pattern
(`scripts/vllm_termpop/qwen_sections_body_a40.sbatch` +
`qwen_sections_vllm.py`).

> **This is LLM-as-judge, NOT a human gold standard and NOT human validation.**
> The judge (Gemma 4 E4B) is a different model family from the extractor under
> audit (Qwen 3.5:9b). Rates below mean *the judge accepted the artifact* — not
> that the artifact is correct.

## Why single-job

The retired two-job A100 pipeline
(`scripts/llm_judge_gemma4/deprecated/`) failed twice: a GPTQ checkpoint could not
load the multimodal audio tower, and a working server then idled for its full 4 h
walltime because the eval job never attached (`afterok` can never fire for a
server that holds its allocation to walltime). Serving and consuming in one
allocation removes both failure modes.

## Files

| File | Purpose |
|---|---|
| `run_judge_a40.sbatch` | Single job: serve vLLM → poll `/v1/models` → smoke test → judge C1–C4 → metrics |
| `run_judge_client_a40.py` | Judge client: `urllib.request`, `ThreadPoolExecutor(parallel)`, JSON-object mode, client-side verdict validation |
| `compute_judge_metrics_a40.py` | Verdict distributions, rates over decided items, 95% Wilson CIs, UNCERTAIN reported separately |
| `prompts/judge_C{1,2,3,4}.txt` | One fixed-size, self-contained prompt per artifact |

Inputs are read from `logs/llm_judge/input_C{1,2,3,4}.jsonl` (500 items each).
Outputs land in `logs/llm_judge/`: `results/{C1..C4}_verdicts.jsonl`,
`JUDGE_METRICS.md`, `_judge_summary_a40.json`, `vllm_server.log`.

## Run

```bash
# full sample (4 x 500 items)
sbatch scripts/llm_judge_a40/run_judge_a40.sbatch

# smoke test (5 items per artifact)
LIMIT=5 sbatch scripts/llm_judge_a40/run_judge_a40.sbatch

# single GPU instead of two (throughput roughly halves; nothing else changes)
TP=1 sbatch --gres=gpu:a40:1 scripts/llm_judge_a40/run_judge_a40.sbatch
```

## Configuration

| Knob | Default | Notes |
|---|---|---|
| `MODEL` | `google/gemma-4-E4B-it-qat-w4a16-ct` | compressed-tensors pack-quantized W4A16, group_size 32; vLLM auto-detects (no `--quantization`) |
| `TP` | `2` | tensor-parallel size; `#SBATCH --gres=gpu:a40:2` |
| `PARALLEL` | `32` | concurrent client workers |
| `PORT` | `8000` | |
| `HF_HOME` | `/home/jkalra_hpc/.cache/huggingface` | the CT checkpoint lives **here**; `/home/jkalra_hpc/llm/hf-cache` has no gemma-4 model |
| `LIMIT` | unset | cap items per artifact for smoke tests |

Slurm: `mlgpu_short`, 1 node, 16 CPUs, 64 GB, `--time=02:00:00`.

## Design decisions

- **No OpenAI SDK.** Transport is stdlib `urllib.request`, matching
  `qwen_sections_vllm.py`.
- **No guided/schema decoding.** The request sets
  `response_format={"type":"json_object"}` and the client validates the verdict
  enum after the fact.
- **No dependency, no second job.** `trap` kills the server on any exit.
- **Retries (max 3 attempts).** 1) normal, 2) verbatim retry on truncation /
  invalid JSON / bad verdict, 3) retry with an explicit "MUST return exactly one
  of: …" reminder. Exhausted items are written with `verdict: null` and an
  `error`, never silently dropped.
- **`finish_reason == "length"` is always an error** (truncated JSON), so it is
  retried rather than parsed.

## Verdict vocabularies (`logs/gold_standard/REVIEW_GUIDELINES.md`)

| Artifact | Field(s) | Allowed |
|---|---|---|
| C1 | `verdict` | `SUPPORTED \| PARTIALLY_SUPPORTED \| NOT_SUPPORTED \| UNCERTAIN` |
| C2 | `verdict_inventory_type`, `verdict_canonical_type` | `CORRECT \| INCORRECT \| UNCERTAIN` |
| C2 | `verdict_agreement` | `AGREE \| DISAGREE \| UNCERTAIN` |
| C3 | `verdict` | `VALID \| INVALID \| TOO_BROAD \| TOO_NARROW \| UNCERTAIN` |
| C4 | `verdict` | `SENSIBLE \| PLAUSIBLE_BUT_WEAK \| NONSENSE \| UNCERTAIN` |

Headline rates (UNCERTAIN excluded from numerator **and** denominator):

- C1 `SUPPORTED / (SUPPORTED + PARTIALLY_SUPPORTED + NOT_SUPPORTED)`
- C2 `CORRECT / (CORRECT + INCORRECT)` per pipeline; `AGREE / (AGREE + DISAGREE)`
- C3 `VALID / (VALID + INVALID + TOO_BROAD + TOO_NARROW)`
- C4 `SENSIBLE / (SENSIBLE + PLAUSIBLE_BUT_WEAK + NONSENSE)`

## Calibration gate

Before quoting any judge-based claim, a human fills the 10-item sheet
`logs/llm_judge/HUMAN_CALIBRATION_SHEET.csv`:

- **≥ 8/10** agreement → report judge-based claims at full weight
- **6–7/10** → report with a calibration caveat
- **< 6/10** → do not make judge-based claims

## Cost

~2 000 items × ≤512 output tokens. Engine init ≈ 4–6 min (incl. `torch.compile`),
judging ≈ 6–12 min at 32-way parallelism on 2×A40, metrics ≈ instant. Budget
~20 min walltime, ~0.7 GPU-hours (2 GPUs × 20 min).
