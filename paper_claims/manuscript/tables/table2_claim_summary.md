# Table 2. Six differentiator claims, all empirically verified on a 50-paper (LLM) / 50-paper (spaCy) cohort.

| Claim | Verdict | Headline | Benchmark |
|---|---|---|---|
| A — context disambiguation | **SUPPORTED** | LLM 51.4% vs spaCy best 25.7% (+25.7 pp) on 35 ambiguous sentences | `claim_A_context_disambiguation/` |
| B — novel entity recall | **SUPPORTED** | 393 truly novel entities (LLM > spaCy vocab union, sim ≥ 0.85, after `is_valid_entity` filter) | `claim_B_novel_entity_recall/` |
| C — 7-source hybrid fusion | **SUPPORTED** | Hybrid wins 5/5 metrics (n_entities, n_relationships, n_entity_types, cross_source, mean_conf) | `claim_C_hybrid_fusion/` |
| D — confidence calibration | **SUPPORTED (reframed)** | Uncalibrated LLM ECE 0.277 → post-hoc Platt ECE 0.040 / isotonic ECE 0.061 (5-fold CV); Spearman ρ 0.070 (p=0.034). spaCy vacuous (1 distinct value across 100,691 entities) | `claim_D_confidence_calibration/` |
| E — speed / efficiency | **SUPPORTED** | spaCy 104.7× faster, LLM 392.6× more expensive | `claim_E_speed_efficiency/` |
| F — biological coverage | **STRONGLY SUPPORTED** | **100% full-triple recall** on 110 gold associations across 12 categories, 6 relation types | `claim_F_biological_validation/` |

**Final tally: 4 SUPPORTED, 1 SUPPORTED (reframed), 1 STRONGLY SUPPORTED.**
