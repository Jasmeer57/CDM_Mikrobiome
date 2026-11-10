# Technical validation

All figures were computed on the complete CDM 3.0.3, before the public text redaction. Redaction removes text only; it changes no identifier, value count or link.

**No human annotation was performed.** None of the results below is an accuracy, recall or completeness estimate, except the F1 scores on the public gold-standard corpora (section 6).

## 1. Structural integrity (all rows)

| Check | Result |
|---|---|
| Section text matches its stored SHA-256 | 4,006 / 4,006 |
| Mention offsets reproduce the surface form | 2,505,628 mentions with offsets (56 without), 0 mismatches |
| Mention → canonical-term links | 0 dangling |
| Catalogue links between records | all resolve to records of the same paper |
| Rows naming a run that does not exist | 0 |
| Schema, value and provenance test suite | 118 / 121 pass (2 fail, 1 conditional) |
| Foreign keys | not declared in the database; many-to-many links are stored as lists |

## 2. Evidence anchoring and literal support (catalogue)

**Anchoring of evidence quotes in the paper text:**

| Anchoring | Share of quotes |
|---|---:|
| Verbatim (exact, whitespace-only, relocated or normalised match) | 88.2% |
| Approximate | 8.0% |
| Not located | 3.8% |

**Values found literally in their evidence passage:**

| Value type | Found |
|---|---:|
| Text values (n = 392,587) | 70.5% |
| Stated counts (n = 12,114) | 75.4% |

A value can be correct without being found literally: normalised or paraphrased values fail a literal match.

## 3. Model-based evidence assessment

Every catalogue record with a value was judged by two language models that did not extract catalogue values (Mistral-7B and Llama-3.1-8B). Each model saw only the evidence passage, the field definitions and the values.

| | Llama-3.1-8B | Mistral-7B |
|---|---:|---:|
| Validly labelled values judged unsupported by the passage | 2.9% | 6.6% |
| Valid rubric labels | 99.2% | 55.4% |
| Unsupported rate: gap-filled values | 9.0% | 19.1% |
| Unsupported rate: original extractions | 2.6% | 5.6% |

**Agreement between the two models:** 85.0% observed, Cohen's κ = 0.28. This is agreement between two models, not inter-annotator agreement.

**Limitations of this assessment:**
- Llama-3.1-8B also took part in an earlier record-curation stage, so it is not independent of the catalogue.
- Neither model checks whether a quote actually exists in the paper. Section 2 covers that.
- These are model judgements, not accuracy.

## 4. Cross-method agreement on selected objective fields

An independent extractor based on regular expressions (no model) found the following facts in the text of all 453 papers. The table shows the share of those facts that also appear in the catalogue:

| Field | Share present in the catalogue |
|---|---:|
| Project accessions | 88.7% |
| Sequencing platforms | 89.2% |
| 16S rRNA variable regions | 72.1% |

The extractor's own coverage is limited and has not been validated. These figures measure agreement between two methods on three fields; they are not recall.

## 5. External concordance (terminology and triples)

**Terminology.** Grounding in reference vocabularies (NCBI Taxonomy, NCBI Gene, CTD/MeSH, Mondo, HPO), by type:

| Type | Mentions grounded | Distinct terms grounded |
|---|---:|---:|
| Organisms | 48.5% | 12.2% |
| Chemicals | 50.0% | 18.5% |
| Diseases | 54.5% | 16.1% |
| Proteins | 27.6% | 11.1% |

Of the 89,799 terms typed only as ENTITY, 98.3% ground in none of these vocabularies. Nine of the 14 CDM types have no matching reference vocabulary and were not assessed.

**Triples.**
- 68.7% of the 25,788 triples use a generic relation.
- 4.9% fall in pair types that a curated knowledge graph covers.
- Of 137 microbe–disease triples with both entities grounded, 50 (36.5%) are curated in Disbiome.

Absence from a knowledge graph is reported as "unsupported", not as "wrong".

## 6. NER benchmark

21 systems were compared in 27 configurations. They included trained taggers, zero-shot taggers, PubTator3 annotations and six open LLMs, each run zero-shot and three-shot.

**Public gold-standard corpora** (exact-match F1, 95% bootstrap confidence intervals in `FAIR_NER_BENCHMARK.md`):

| | BC5CDR | BioRED |
|---|---:|---:|
| Best overall | PubTator3 90.1 (in-domain) | HunFlair2 80.6 |
| Best LLM (Qwen3.5-4B, three-shot) | 69.5 | 66.2 |

**The 453-paper corpus** (no gold standard; `CORPUS_NER_BENCHMARK.md`). Measures are vocabulary grounding and knowledge-graph support, which are proxies for precision.
- No configuration grounded more than 41.3% of its strings of any type.
- Public F1 predicted corpus grounding for diseases (Spearman ρ 0.75) but not for organisms (ρ 0.02).

## 7. Use for research questions

Results from the CDM were compared with sets of papers found independently by keyword rules over the text. Both methods are computational.

| Question | Share of keyword-found papers also returned by the CDM |
|---|---:|
| Datasets with a public accession | 97.1% |
| Findings traceable to DOI, section and a verbatim quote | 90.1% of 24,272 findings |
| Stool samples stored at −80 °C | 80.0% |
| Shotgun metagenomics with a linked taxon finding | 71.7% |
| *F. prausnitzii* decreased | 53.6% |
| Type 2 diabetes cohorts | 39.3% |
| IBD studies using 16S | 26.8% |
| Probiotic intervention | 26.1% |

Questions defined by disease or intervention are poorly served, because those fields are sparsely populated.
