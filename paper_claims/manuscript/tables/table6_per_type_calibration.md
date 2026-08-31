# Table 6. Per-CDM-type confidence calibration (Claim D, SUPPORTED — reframed).

## Global post-hoc calibration (5-fold CV, 917 gold-labeled entities, 52% accuracy)

| calibrator | ECE | Brier | ECE std |
|---|---|---|---|
| Uncalibrated LLM | 0.2774 | 0.1198 | — |
| **Platt scaling** | **0.0403** | 0.2361 | 0.0262 |
| **Isotonic regression** | **0.0606** | 0.2683 | 0.0244 |

Spearman ρ (confidence vs proxy correctness) = 0.0699 (p = 0.034). spaCy `relevance_score`: 1 distinct value across 100,691 entities → **vacuous, not calibratable**.

## Per-CDM-type breakdown

| CDM type | n | accuracy | mean conf | gap | verdict |
|---|---|---|---|---|---|
| **DNA_RNA** | 14 | 0.86 | 0.80 | 0.05 | **well-calibrated** |
| **PROTEIN** | 10 | 0.60 | 0.68 | 0.08 | **well-calibrated** |
| **DISEASE** | 48 | 0.62 | 0.73 | 0.11 | **well-calibrated** |
| GENOMICS | 10 | 0.50 | 0.68 | 0.18 | mild over-confidence |
| CELL_TYPE | 2 | 0.50 | 0.70 | 0.20 | (n too small) |
| LAB_METHOD | 16 | 0.38 | 0.67 | 0.29 | over-confident |
| CHEMICAL | 37 | 0.46 | 0.77 | 0.31 | over-confident |
| SAMPLE_METHOD | 22 | 0.27 | 0.70 | 0.43 | over-confident |
| ORGANISM | 87 | 0.39 | 0.86 | 0.47 | over-confident |
| CLINICAL | 7 | 0.14 | 0.63 | 0.49 | over-confident |
| DATA_ANALYSIS | 53 | 0.15 | 0.72 | 0.57 | over-confident |
| PATHWAY | 18 | 0.11 | 0.74 | 0.63 | over-confident |
| EXPERIMENTAL_METHOD | 6 | 0.00 | 0.72 | 0.72 | over-confident |
| STUDY_DESIGN | 1 | 0.00 | 0.70 | 0.70 | (n too small) |

## Three takeaways

1. **The LLM is well-calibrated on the types it gets right.** DNA_RNA (0.86 acc, 0.80 conf), PROTEIN (0.60, 0.68), DISEASE (0.62, 0.73) all have gaps < 0.12.

2. **The LLM is severely overconfident on the types it gets wrong.** PATHWAY (0.11 acc, 0.74 conf), DATA_ANALYSIS (0.15, 0.72), EXPERIMENTAL_METHOD (0.00, 0.72) all have gaps ≥ 0.57. The inflated global ECE (0.277) is a *composition artifact* — a mixture of well-calibrated and over-confident types — not a single mis-calibrated knob.

3. **Post-hoc calibration fixes the global number, and the LLM/spaCy contrast is a contribution.** Platt scaling drops global ECE from 0.277 to 0.040 and isotonic to 0.061 (5-fold CV). The raw score is monotonically informative (Spearman ρ 0.070, p 0.034). spaCy's `relevance_score` is a constant (1 distinct value across 100,691 entities) and cannot be calibrated at all — the LLM gives a usable score, spaCy does not.
