# Claim E — Speed/efficiency tradeoffs when combining methods

## Claim statement

> The two pipelines have complementary speed/cost profiles: the spaCy pipeline is faster and cheaper on a per-document basis (CPU-only, ~1-2 min/document, no GPU), while the LLM pipeline is slower and more expensive (GPU, 2-3 min/5K chars, VRAM-bound). For a given budget, the optimal strategy is **hybrid routing**: spaCy for first-pass, LLM for second-pass on entities where context disambiguation matters. The paper reports wall-clock, peak memory, throughput, and cost-per-document for each.

## Why this matters

- Reviewers will ask "why two pipelines, not one?"
- A practical claim: at $0.10/document LLM cost and $0/document spaCy cost, a 2-stage router gives the best precision/recall-per-dollar.
- This is the **deployability** claim — the one that says "this isn't just a paper, you can run it."

## Test design

For both pipelines, measure on the **same input** (e.g., 10 randomly sampled papers from `papers_txt/`, with sizes spanning the 1KB-100KB range):

| Metric | How |
|---|---|
| **Wall clock (s)** | `time.time()` before/after the pipeline runs |
| **Peak memory (MB)** | `tracemalloc` or `resource.getrusage` (RSS) — or `nvidia-smi` for GPU memory |
| **Throughput (entities/sec)** | total entities / wall clock |
| **Cost per document ($)** | GPU-hours × $/hour + (LLM tokens × $/token) |
| **Scalability (s/MB)** | linear fit of wall clock vs. doc size |
| **GPU utilization (%)** | nvidia-smi during a representative run |

Report:
- Per-pipeline tables of (wall clock, memory, throughput) per document size bucket
- A combined cost-vs-precision graph (cost on x-axis, KG quality metric on y-axis, two dots per pipeline + the hybrid)

## Where the data lives

- **LLM pipeline orchestrator:** `llm_terms/core/pipeline.py:CDMEntityPipeline` — has `run(text, output_path)` and `extract_entities(text)` that we can time
- **spaCy pipeline orchestrator:** `spacy_terms/src/pipeline.py:GlobalPipelineProcessor` — has `.run()` for batch, or `terms_extractor.extract_from_text(text)` for single
- **Cost data:** depends on hardware. Estimate from:
  - LLM: GPU $/hr (e.g., A100 ~$1.50/hr → 30GB VRAM at ~50% util → ~$0.04/hr → per-doc cost is wall clock / 3600 × $0.04)
  - spaCy: CPU only, ~$0/doc
  - Cloud Ollama / vLLM: $/token pricing varies
- **llm_terms/README.md** claims 1MB = 30s, 10MB = 3min, 100MB = 25min — these are starting benchmarks to verify and update

## Verdict

This is a **supporting** claim — the paper doesn't need it to be true in any novel sense (the tradeoff is well-known), but reporting the actual numbers gives the paper a deployable contribution.

If the numbers are roughly:
- LLM: 2-3 min/5K chars, ~$0.001-0.01/doc, 16GB GPU
- spaCy: 30-60s/full document, ~$0/doc, 8GB CPU
- Hybrid (router + LLM second-pass): 1.5-2x spaCy wall clock, ~30% of LLM cost

then the claim is "supported in magnitude" and the paper can recommend the hybrid.

## What the script produces

Running `benchmark.py` produces:
- `results/timings.csv` — per-paper wall clock, memory, throughput, cost
- `results/scalability_fit.csv` — wall clock vs. document size, with linear fit
- Prints a comparison table and verdict

## Practical note

A **wall-clock benchmark across 10 papers is the absolute minimum** for the paper. For a serious submission, run on 50-100 papers spanning the size range and report the median + 25th/75th percentile, not just means (NER pipelines are heavy-tailed on outliers — one malformed PDF can take 10x as long).
