# Paper Claims Workspace

This folder is the empirical workbench for the 5 differentiator claims of the Microbiome-CDM paper. Each subfolder is a self-contained unit with its own README, scaffold script, and (where applicable) a curated test set. Goal: every claim has reproducible evidence that survives peer review.

## Reference paper

> Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025). *Integration of 168,000 samples reveals global patterns of the human gut microbiome.* **Cell** 188(4):1100–1118.e17. DOI: [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017)

This project is a Common Data Model + Knowledge Graph built on the cited literature of the 168k compendium.

## The 5 claims (in priority order)

| # | Claim | Load-bearing? | Subfolder | Time to evidence |
|---|---|---|---|---|
| **C** | Hybrid (LLM ∪ spaCy ∪ ChEBI ∪ UMLS ∪ NCBI) > either single method on KG quality | **Yes — main paper contribution** | `claim_C_hybrid_fusion/` | 1 week |
| **A** | LLM uniquely resolves context-dependent type disambiguation (butyrate = chem vs. process) | **Yes — strongest novel claim** | `claim_A_context_disambiguation/` | 3-5 days |
| **B** | LLM surfaces novel entities not in any spaCy vocabulary | Supporting | `claim_B_novel_entity_recall/` | 2-3 days |
| **D** | LLM confidence is well-calibrated; spaCy vocab scores are not | Supporting | `claim_D_confidence_calibration/` | 1-2 days |
| **E** | Speed/efficiency: when each method is preferable, $/doc tradeoffs | Supporting | `claim_E_speed_efficiency/` | 2-3 days |

**C is the minimum-viable paper.** A + B add the most novel-methods flavor. D + E are nice-to-haves that strengthen the methods story but can be moved to supplementary.

## Each subfolder has

- `README.md` — the claim statement, why it matters, test design, expected outcome, where the data lives in this repo
- `benchmark.py` — a runnable Python scaffold (or pseudo-script with the structure filled in) that produces numbers
- Optional: a small curated test set in CSV/JSON

## How to use this

1. Start with **C** — it's the load-bearing claim and the easiest to make solid because the 5-source fusion is already implemented.
2. Then **A** — it's the strongest novel-methods claim if the data supports it.
3. **B, D, E** as supplementary / time-permitting.

Run each `benchmark.py` from its folder. Each script prints a results table you can paste into the paper or save to `results.json` for later figure generation.

## Cross-claim consistency

- All scripts use the same convention: `*_AVAILABLE` flags for optional deps, paths resolved relative to repo root, results saved to `<claim_folder>/results/`.
- All scripts read the same input format where possible: `cdm_entities_clean.json` (the LLM pipeline output) and `*_cdm_entities.json` (the spaCy output).
- For all claims, the ground-truth anchor is `extract_chebi_relationships.py`'s curated 10-metabolite gold standard (LLM pipeline) and `microbiome_components.py`'s 55+ term gold standard (spaCy pipeline).

## Status

| Claim | Status | Notes |
|---|---|---|
| A | Scaffold ready | Test set has 35 ambiguous terms with expected types. Benchmark needs to be run on the actual pipeline outputs. |
| B | Scaffold ready | Needs LLM entity set + spaCy vocabulary set to be loaded; manual classification of novel candidates required. |
| C | Scaffold ready | Needs to run the KG construction under 3 configurations (LLM-only, spaCy-only, hybrid) and compare. |
| D | Scaffold ready | Needs LLM confidence scores loaded; spaCy vocab confidence distribution computed (probably "always 1.0" or "N/A"). |
| E | Scaffold ready | Needs both pipelines run on the same input with timing/memory measurement. |

After running each benchmark, update the claim's README with the actual numbers and the verdict.
