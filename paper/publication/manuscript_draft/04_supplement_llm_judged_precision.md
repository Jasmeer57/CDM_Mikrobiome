# Supplementary analysis: model-judged validity of all extracted entities and triples

*Draft 0.1, 2026-11-03. Claim IDs in brackets refer to `../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (L01–L12). Source: `outputs/results/benchmark/llm_judge_deepseek_v4_flash/` (pinned by its `MANIFEST.sha256`; `summary.json` sha256 `42460f76…`).*

**Status:** a dated supplementary analysis added after the validation freeze of 2026-11-02. It does not modify the frozen validation results. Every number below is a **model judgement**, not accuracy, recall or human validation.

**This is NOT the domain expert review.** The independent CDM expert review (blocker B5) is a review of the data-model design (entities, relationships, cardinalities, provenance, adoptability) by a human biomedical-informatics expert. It is still outstanding, and by project rule it must not be simulated by a language model. The analysis below is an automated, model-based quality screen of extracted strings and triples. It must not be described as expert review, expert validation or human validation.

## Claim for the manuscript

> We asked a large language model not involved in extraction to judge every unique string produced by every NER system and every relation triple. Trained single-type taggers and zero-shot NER models produced valid, correctly typed entities more often than small open LLMs. The generic entity type of the CDM terminology was dominated by invalid strings. Only a minority of triples were judged well-formed claims. These are model judgements and do not establish accuracy.

## Method

**Judge**
- **Model:** DeepSeek-V4-Flash (`deepseek-ai/DeepSeek-V4-Flash-0731`) on an OpenAI-compatible institutional endpoint.
- **Settings:** reasoning disabled, temperature 0.
- **Prompt:** version `entity-triple-judge-v2-tailored-nothink`. It defines the invalid categories that occur in our data (generic nouns, units and conditions, statistics, person names, citations, figure labels, sentence fragments) and gives microbiome-specific valid examples for each type.
- **Code:** `src/scripts/ner_llm_judge/judge.py`, settings in `config.yml`.

**Items judged:** every unique (lower-cased string, type) pair from:
- the 26 corpus-benchmark configurations (345,693 pairs, BioRED type scheme);
- all 10 CDM terminology sources (358,714 pairs, CDM type scheme);
- all 25,788 CDM relation triples.

Each pair was judged once, from the string and its proposed type alone. **No paper text was sent**, so no licence restriction applies. The verdict was then mapped back to every system, mention and term.

**Batching and completion:** 150 entities or 75 triples per request; 730,195 items in total. Every item received a verdict; 272 items omitted in a first pass were re-requested.

**Questions asked**

| Item | Criterion | Question |
|---|---|---|
| Entity | valid | Is the string a real, specific entity or concept name? |
| Entity | microbiome-relevant | Is the entity meaningful in human microbiome research? |
| Entity | type correct | Is the proposed type correct? |
| Triple | well-formed | Is the triple a plausible claim? |
| Triple | microbiome-relevant | Is the claim relevant to human microbiome research? |
| Triple | label specific | Is the relation label specific, or too generic? |
| Triple | entities valid | Are the subject and object valid entities? |

**Measures**
- **Distinct-string precision:** each unique string counts once.
- **Mention-weighted precision:** each string is weighted by how often the system extracted it. This is closer to what a user of the output encounters.
- **Uncertainty:** all intervals are 95% Wilson intervals.

## Results

**NER systems on the 453-paper corpus** (BioRED types, distinct strings; full table in `REPORT.md`):

| System | Valid and correctly typed | Valid (mention-weighted) |
|---|---:|---:|
| BERT chemical (single-type tagger) | 59.3% [L01] | 87.6% |
| GLiNER v2.5 medium (zero-shot NER) | 43.6% [L02] | 74.4% |
| HunFlair2 (trained, multi-type) | 37.4% | 67.9% |
| Best LLM: Gemma-4-E4B, zero-shot | 35.5% [L03] | 60.4% |
| Qwen3.5-4B, three-shot | 28.9% | 59.7% |
| Lowest: Llama-3.1-8B, zero-shot | 15.7% [L04] | 42.8% |

- **Ranking:** trained and zero-shot taggers ranked above every LLM configuration on correctly typed validity.
- **Small type sets:** the single-type BERT taggers ranked highest, but each covers only one type.
- **Agreement with the earlier benchmark:** this matches the public-benchmark ordering and the corpus grounding results.

**CDM terminology sources** (distinct strings judged valid):
- **Generic ENTITY terms:** `en_core_sci_lg`, the source of all generic ENTITY terms, has 137,893 distinct strings, of which only **9.4%** were judged valid [L05].
- **Best sources:** the MeSH gazetteer (67.3%) and BioBERT-diseases (60.9%) [L06].
- **LLM sources:** the two Qwen3.5-4B runs reached 34.5% and 36.6%. Weighted by mentions, the vLLM run reached 50.7% [L07].

**CDM entity types** (distinct strings judged valid):
- **Highest:** chemical (44.3%), data analysis (43.1%) and disease (42.8%).
- **Lowest:** experimental method (14.1%) and study design (16.1%) [L08].

**Triples** (all 25,788):

| Judgement | Share |
|---|---:|
| Well-formed, plausible claim | 39.3% [L09] |
| Subject and object both valid entities | 38.7% [L10] |
| Relation label specific | 12.5% [L11] |
| Relation label too generic | 29.5% [L12] |
| Relevant to human microbiome research | 74.6% |

## Cleaned layer (DeepSeek-curated, derived; CDM 3.0.3 unchanged)

The verdicts were used to derive a cleaned layer, in `outputs/results/cleaned_layer_deepseek/` (code `src/scripts/ner_llm_judge/clean.py`, pinned by `MANIFEST.sha256`). Every row keeps its original value next to the cleaned one.

**Triples**
- **Kept:** 9,682 of 25,788 triples were judged well-formed with valid subject and object. 15,661 were dropped as not well-formed, and 445 for invalid entities.
- **Relabelled:** of the kept triples, 6,733 had a label judged generic or wrong. DeepSeek chose a label from the CDM's own relation vocabulary, using the evidence sentence for the 4,012 triples from CC BY / CC0 papers and the triple alone otherwise.
- **Result:** 6,203 triples were relabelled, and 408 had their direction reversed. Triples labelled `OTHER_RELATION` fell from 6,574 to 437.
- **Caveat:** the most frequent new label, `ASSOCIATED_WITH` (1,758 triples), is still broad.

**Canonical terms**
- **Kept:** 30,727 of 162,409 terms, those for which most of their mentions were judged valid entities.
- **Retyped:** 11,614 of the kept terms.
- **Generic ENTITY type:** kept terms typed ENTITY fell from 7,735 to 744.

This layer is model curation, not human curation. It is offered as an optional quality-filtered view and does not replace the frozen releases.

## Limitations (must accompany the claim)

1. **Model judgements, not accuracy, and not expert review.** No human checked the verdicts, and no inter-annotator agreement exists. The CDM expert review remains outstanding.
2. **String-only judging.** Each string was judged without its sentence, so context-dependent entities can be misjudged, for example abbreviations and ambiguous short names.
3. **Not independent.** A DeepSeek-family model (DeepSeek-R1-Distill-Qwen-7B) was used in the pipeline, for term review and mapping adjudication. It is also one of the benchmarked systems.
4. **Distinct-string figures penalise systems that produce many rare junk variants.** Mention-weighted figures are therefore also reported.
5. **Recall is not measured.** Systems that extract little can score high precision.
6. **Data quirk.** 278 CDM terms carry a type `GO` that is not one of the 14 CDM types.

## Placement in the manuscript

- **Results:** one paragraph and one table, following the NER benchmark.
- **Discussion:** add a sentence to the paragraph on the terminology and triple layers.
- **Supplement:** this file, plus `REPORT.md`.
- **Data release:** the full verdict tables (`entity_verdicts.csv.gz`, `triple_verdicts.csv.gz`) can be offered with the deposit as a quality flag for filtering. Adding them to `releases/zenodo_frozen` would require a new build and seal.
