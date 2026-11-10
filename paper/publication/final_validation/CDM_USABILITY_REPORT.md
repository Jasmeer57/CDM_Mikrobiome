# CDM usability report

The eight research questions from the Gate 4 package were run against CDM 3.0.3 (SQL in `RESEARCH_QUERY_VALIDATION.csv`). Each result is compared with a paper set found **independently** by fixed keyword rules over the section text (`src/scripts/final_validation/query_check.py`; output `queries/QUERY_COMPARISON.csv`).

Both sides are computational. The keyword rules are themselves imperfect: they find any paper *mentioning* the criterion. So disagreement shows where to look, not which side is right.

| Query | CDM papers | Keyword-rule papers | Both | Keyword papers also returned by the CDM | Jaccard |
|---|---:|---:|---:|---:|---:|
| Q1 IBD studies using 16S sequencing | 35 | 82 | 22 | 26.8% | 0.23 |
| Q2 type 2 diabetes cohorts | 18 | 28 | 11 | 39.3% | 0.31 |
| Q3 *F. prausnitzii* decreased (own results) | 58 | 56 | 30 | 53.6% | 0.36 |
| Q4 datasets with a public accession | 442 | 378 | 367 | 97.1% | 0.81 |
| Q6 probiotic intervention | 60 | 88 | 23 | 26.1% | 0.18 |
| Q7 stool samples stored at −80 °C | 191 | 70 | 56 | 80.0% | 0.27 |
| Q8 shotgun metagenomics with a linked taxon finding | 101 | 60 | 43 | 71.7% | 0.36 |
| Q5 trace each finding to DOI, section and a verbatim quote | 24,272 findings | — | — | **90.1% fully traceable** | — |

**Reading the results:**
- **Strong:** data accessions (Q4) and provenance tracing (Q5).
- **Weak: disease- or intervention-defined questions** (Q1, Q2, Q6). The CDM finds only a quarter to two-fifths of the papers whose core text mentions the criterion. The cause lies in where the information sits: the catalogue records disease mainly in `cohort.health_status` and interventions in `claim.intervention_category`, and these are sparsely or inconsistently filled. Keyword over-inclusion explains part of the gap but not all of it.
- **Q7 and Q8:** the CDM returns more papers than the keyword rule. The rules are narrow (one Methods sentence), and the CDM aggregates over sample groups and assays.

**Reproducibility from documentation:** writing these queries required conventions that are now documented in the 3.0.3 vocabulary reference: `claim_source`, `;`-separated links, and missing-data codes in count columns. They were not documented in 3.0.2.

**Decision:**
- CDM usability: **CONDITIONAL**. It is reliable for identifiers and provenance, and weak for disease and intervention retrieval.
- Not evaluated by any human; the independent CDM expert review is still outstanding.
