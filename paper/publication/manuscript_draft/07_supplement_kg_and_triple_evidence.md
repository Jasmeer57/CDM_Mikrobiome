# Supplementary analysis: knowledge graph, evidence check of the triples, and curated-KG comparison

*Working notes, 2026-11-04. Claim IDs refer to `../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (Q01–Q09). Sources: `outputs/results/kg_2026-11-04/` (KG), `…/evidence_check/` and `…/gold_kg_check/`. Figure: `manuscript_bib/figures/fig_triples`.*

**Status:** dated supplementary analyses after the validation freeze. The frozen CDM 3.0.3 is read-only and unchanged.

## 1. Knowledge graph

The 25,788 triples were assembled into a directed multigraph whose nodes are canonical terms (`src/scripts/kg/build_kg.py`).

| | Full | Cleaned (DeepSeek) |
|---|---:|---:|
| Nodes / edges | 22,579 / 25,788 | 8,897 / 9,682 [Q01] |
| Largest connected component | 68.5% of nodes | 67.8% [Q02] |

- **Weakness:** the most connected nodes are generic, such as "gut microbiota", "gut microbiome" and "microbiota". This is typical of literature-mined graphs and should be stated.
- **Release:** `kg_cleaned.graphml`, `nodes.csv.gz` and `edges.csv.gz` hold the graph. Each edge carries its original and cleaned relation.

## 2. Does the source sentence state the triple? (DeepSeek, evidence-grounded)

**Method**
- **Pre-registration:** `src/scripts/kg/evidence_schema.json`.
- **Items:** every triple with a source sentence from a CC BY / CC0 paper. No text from the 179 withheld papers was sent.
- **Coverage:** 16,132 of 16,142 judged; 10 failed repeatedly [Q03].

**Results**

| Measure | Result |
|---|---:|
| Sentence states a relationship between subject and object | 86.6% [Q04] |
| Original relation label supported as written | 22.0% [Q04] |
| Supported, or related but with a generic label | 80.2% [Q04] |
| Original label supported: kept vs dropped by the cleaning | 30.6% vs 17.2% [Q05] |
| Relabelled triples: original vs cleaned label supported | 17.2% vs 50.4% [Q06] |

**Reading:**
- **Pairs:** extraction usually links the right pair of entities.
- **Labels:** the main weakness is generic or wrong relation labels.
- **Cleaning:** the relabelling corrects many labels. However, the relabelling and this check used the same model family, so this improvement is not independent evidence.

## 3. Are the pairs known in curated knowledge graphs?

**Method**
- **Pre-registration:** `src/scripts/kg/gold_kg_schema.json`.
- **References:** Disbiome and BugSigDB (microbe–disease); CTD (chemical–disease, gene–disease, chemical–gene).
- **Matching:** independent of the source paper. A pair counts as supported if it appears anywhere in the reference.

**Results**

| Edge type | Resolved edges | In a reference | Chance | Kept vs dropped |
|---|---:|---:|---:|---:|
| Microbe–disease | 622 | 13.2% | 5.8% [Q07] | 15.5% vs 6.4% [Q08] |
| Chemical–disease | 202 | 11.4% | 9.8% [Q09] | — |
| Gene–disease | 16 | none | — | — |
| Chemical–gene | 7 | 2 | — | — |

- **Microbe–disease:** a modest signal above chance, and edges kept by the cleaning are more often known.
- **Chemical–disease:** no signal above chance.
- **Gene–disease and chemical–gene:** too few edges to judge.
- **Sentence support does not predict reference support.** A correctly extracted, specific finding need not be in a curated database. Reference KGs are incomplete, so absence is not error.

## Limitations

1. Every DeepSeek result is a model judgement, not human validation.
2. One sentence per triple. A triple stated across sentences can be judged unsupported.
3. Many disease and microbe names were resolved by exact name matching. The resolution methods are reported per edge in `edge_support.csv.gz`.
4. Only a small share of edges resolve to reference identifiers. The curated-KG comparison therefore covers a minority of the graph.
