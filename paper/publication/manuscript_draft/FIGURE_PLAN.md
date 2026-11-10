# Figure plan

Each figure lists its data source; every source is already frozen or computed.

| # | Figure | Content | Data source | Status |
|---|---|---|---|---|
| 1 | **Resource overview** | compendium (168,464 samples) → 453 BioProjects / 447 publications → 4,006 sections → mentions / terms / catalogue / triples → CDM 3.0.3; counts on each arrow; 156,330 linked samples marked as a BioProject-level link | claims register C01–C08, M01, T02, K01, R01 | data ready |
| 2 | **Extraction and normalisation architecture** | 4 mention sources kept separate → canonical terms (165,991 → review → 162,409) → guarded mappings (334,231 → 314,772) → two-model adjudication (18,272 accepted); catalogue: extraction → G1 validated gap fill (21,403 accepted / 76,253 rejected) → G3 removal (2,586) → 52,400 | claims register M03–M06, T01–T05, P01–P06, K03–K07 | data ready |
| 3 | **CDM architecture** | M1–M10 modules, 33 entities, key relationships; provenance spine (paper → section → offsets → record → run); marks implemented / embedded / empty | entity registry proposal, `CDM_RELATIONSHIP_VALIDATION.csv` | data ready |
| 4 | **Public NER benchmark** | exact F1 with 95% CI per configuration on BC5CDR and BioRED, coloured by kind (trained / zero-shot NER / LLM zero-shot / LLM 3-shot); in-domain flagged; per-type panel | `fair_ner_metrics.json` | data ready |
| 5 | **Corpus benchmark** | grounding rate by type and KG-supported pair share per model; scatter of public F1 vs corpus grounding (does public performance predict corpus concordance?) | `corpus_metrics.json`, `benchmark/benchmark_analysis.json` (per-type ρ: disease 0.75, organism 0.02) | data ready |
| 6 | **Computational validation** | (a) quote anchoring by table; (b) deterministic value-in-evidence by field; (c) model-judge PASS / FAIL / UNCERTAIN by table for both judges, with the INVALID share shown, and FAIL rate by deterministic result and by original vs gap-filled; (d) source-first coverage (3 fact types); (e) query concordance | `final_validation/*`, `evidence_judge/judge_summary.json` | data ready |

**Supplementary figures:**
- S1: terminology concordance, by distinct term vs by mention.
- S2: the generic-ENTITY breakdown.
- S3: triple relation families and KG support.
- S4: rights layers (274 / 15 / 164).
- S5: LLM run failures on the corpus (truncated chunks, strings not in text, invalid types), from `BENCHMARK_FINAL_ANALYSIS.md` §3.3.
- S6: judge-vs-judge confusion matrix on text values, with the INVALID share kept visible (`judge_summary.json`). Labelled "agreement between two models", never "inter-annotator".

**Style:** one categorical palette for model kinds, used consistently across Figures 4–6. Show confidence intervals wherever they exist. No accuracy axis anywhere, because no human ground truth exists.
