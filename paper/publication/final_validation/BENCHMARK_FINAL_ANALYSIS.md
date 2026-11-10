# NER benchmark: final analysis (Workstream F)

*Generated 2026-11-02. Sources:*
- *`outputs/results/ner_fair_bench/FAIR_NER_BENCHMARK.md` and `fair_ner_metrics.json` (public);*
- *`outputs/results/ner_corpus_bench/CORPUS_NER_BENCHMARK.md`, `corpus_metrics.json` and `MEASUREMENT_NOTES.md` (corpus);*
- *`benchmark/benchmark_analysis.json` (cross-analysis, from `src/scripts/final_validation/benchmark_analysis.py`).*

The two benchmarks answer different questions and are never combined into one score:
- **Public:** span-level F1 against human gold standards on PubMed abstracts. This is accuracy on those abstracts.
- **Corpus:** 453 microbiome full texts with no gold standard. Grounding in reference vocabularies and support in curated knowledge graphs are **precision proxies**, not accuracy.

## 1. Configuration inventory

| Group | Systems | Public configurations | Corpus configurations |
|---|---|---:|---:|
| Trained NER | HunFlair2; BERT chemical / disease / genetic; SciBERT-JNLPBA; scispaCy bc5cdr / bionlp13cg / craft / jnlpba / lg | 10 | 10 |
| Zero-shot NER | GLiNER2 base / large; GLiNER v2.5 medium / biomed | 4 | 4 |
| Reference annotations | PubTator3 (precomputed; PubMed only) | 1 | — |
| Open LLMs, zero-shot and 3-shot | Qwen3.5-4B, Gemma-4-E4B, Llama-3.1-8B, Mistral-7B-v0.3, Phi-3.5-mini, DeepSeek-R1-Distill-Qwen-7B | 12 | 12 |
| **Total** | 21 systems | **27** | **26** |

**Protocol, fixed before scoring:**
- official test splits only;
- GLiNER thresholds chosen on development splits;
- few-shot examples from training splits;
- the same prompt per type schema for all LLMs;
- LLM strings mapped to spans by word-bounded occurrence;
- 95% confidence intervals by document bootstrap; paired bootstrap against the best system;
- systems trained on a test corpus marked †.

scispaCy `en_core_sci_lg` emits only the untyped label ENTITY. It scores 0 on typed metrics (span-only F1 30.3 / 38.3) and has no typed corpus row.

## 2. Public gold standards

| | BC5CDR (500 abstracts) | BioRED (100 abstracts) |
|---|---|---|
| Best overall | PubTator3† 90.1 [88.4–91.6] | HunFlair2 80.6 [78.3–82.8] |
| Best trained NER not trained on that corpus | scispaCy-bionlp13cg 48.4 (HunFlair2 77.3 is in-domain) | HunFlair2 80.6 |
| Best zero-shot NER | GLiNER v2.5 medium 69.2 [67.6–70.7] | GLiNER v2.5 biomed 60.4 [57.2–63.3] |
| Best LLM | Qwen 3-shot 69.5 [67.8–71.1] | Qwen 3-shot 66.2 [63.1–69.3]; Gemma zero-shot 66.0 |
| Weakest LLM | Phi zero-shot 50.4 | Phi zero-shot 39.5 |

Full-schema exact F1. Every system is significantly below the best on each corpus (paired bootstrap p < 0.001), except PubTator3 on BioRED (p = 0.27).

**Findings:**
1. **A multi-corpus trained tagger is best on public data.** HunFlair2 leads BioRED by 14 F1 points over every LLM.
2. **The best LLMs match zero-shot NER, not trained NER.** They are tied with GLiNER on BC5CDR (69.5 vs 69.2, overlapping CIs) and above it on BioRED (66.2 vs 60.4).
3. **Few-shot prompting is inconsistent.** It helps Qwen (+8.4 BC5CDR, +1.7 BioRED), Llama (+3.5 BC5CDR), Mistral (+2.4, +1.9) and Phi (+4.2, +4.5). It makes no difference to DeepSeek on BC5CDR. It hurts Gemma (−2.1 BC5CDR, −6.4 BioRED) and Llama on BioRED (−1.1).
4. **Type matters more than model.** LLMs are strong on genes (Qwen 81–82 on BioRED genes, near HunFlair2's 83.3) and weak on organisms (11.8–43.3 vs HunFlair2 94.4).
5. **Cost.** LLMs take 0.08–8.8 s per abstract on one A40, against 0.01–0.12 s for trained NER.

## 3. Microbiome corpus (453 papers, 7,161 chunks, no gold standard)

### 3.1 Grounding: share of a configuration's unique strings found in a reference vocabulary of the predicted type

| Type | Best | Best LLM | Spread across the 26 configurations |
|---|---|---|---|
| Gene / protein | GLiNER2 base 20.9 | DeepSeek 3-shot 17.7 | 4.1–20.9 |
| Disease / phenotype | BERT disease 29.2 | Gemma 3-shot 22.1 | 7.3–29.2 |
| Chemical | BERT chemical 41.3 | Gemma 3-shot 21.0 | 6.1–41.3 |
| Organism | **Gemma zero-shot 25.3** | Gemma zero-shot 25.3 | 5.1–25.3 |
| Sequence variant | Gemma 3-shot 10.7 | Gemma 3-shot 10.7 | 1.0–10.7 |

Grounding is low for every configuration because full texts contain many strings that are real but absent from the vocabularies (abbreviations, strain designations, generic phrases). Treat the values as relative, not absolute.

### 3.2 Knowledge-graph support of co-occurring grounded pairs (microbe–disease, Disbiome)

The pairs-supported share is similar across configurations (2.2–7.9%). What differs is how many distinct curated associations a configuration recovers. Below, "% of union" is the share of all 1,683 associations found by any configuration:

| Configuration | Grounded pairs | Distinct Disbiome associations recovered | % of union |
|---|---:|---:|---:|
| GLiNER v2.5 biomed | 51,385 | 1,456 | 86.5 |
| GLiNER v2.5 medium | 53,772 | 1,383 | 82.1 |
| GLiNER2 large | 42,749 | 1,225 | 72.7 |
| Qwen zero-shot (best LLM) | 20,495 | 743 | 44.1 |
| HunFlair2 | 8,502 | 316 | 18.8 |

For CTD pairs the most distinct associations come from:
- gene–disease: GLiNER v2.5 biomed (114 of a 201-association union);
- chemical–disease: scispaCy-bc5cdr (417 of 657), with GLiNER v2.5 biomed close behind (401);
- chemical–gene: scispaCy-bionlp13cg (510 of 895).

No LLM leads any pair type; the best LLM result is Llama zero-shot for gene–disease (91). HunFlair2 has the highest supported share for chemical–gene pairs (16.3%).

### 3.3 Run inventory and failure statistics (LLMs)

| configuration | model | run time (s)* | failed chunks | truncated / salvaged chunks | strings | not in text % | invalid type % |
|---|---|---:|---:|---:|---:|---:|---:|
| llm_deepseek_fs | DeepSeek-R1-Distill-Qwen-7B (AWQ) | 7,208 | 3 | 442 / 951 | 137,368 | 44.0 | 18.4 |
| llm_deepseek_zs | DeepSeek-R1-Distill-Qwen-7B (AWQ) | 5,412 | 6 | 285 / 458 | 118,519 | 31.8 | 4.4 |
| llm_gemma_fs | Gemma-4-E4B (w4a16) | 1,309 | 2 | 8 / 8 | 87,658 | 6.0 | 0.1 |
| llm_gemma_zs | Gemma-4-E4B (w4a16) | 1,406 | 2 | 63 / 63 | 111,656 | 4.9 | 0.1 |
| llm_llama_fs | Llama-3.1-8B-Instruct (AWQ) | 10,675 | 2 | 1,793 / 1,793 | 465,644 | 14.7 | 1.6 |
| llm_llama_zs | Llama-3.1-8B-Instruct (AWQ) | 22,528 | 2 | 5,665 / 5,665 | 1,279,886 | 15.1 | 0.9 |
| llm_mistral_fs | Mistral-7B-Instruct-v0.3 (AWQ) | 4,023 | 2 | 43 / 43 | 102,575 | 10.9 | 51.7 |
| llm_mistral_zs | Mistral-7B-Instruct-v0.3 (AWQ) | 3,444 | 2 | 72 / 72 | 119,658 | 8.9 | 14.7 |
| llm_phi_fs | Phi-3.5-mini-instruct (AWQ) | 18,938 | 2 | 929 / 929 | 292,851 | 19.9 | 31.8 |
| llm_phi_zs | Phi-3.5-mini-instruct (AWQ) | 9,381 | 2 | 219 / 219 | 155,066 | 11.2 | 53.3 |
| llm_qwen_fs | Qwen3.5-4B | 3,024 | 2 | 233 / 233 | 162,019 | 5.1 | 0.0 |
| llm_qwen_zs | Qwen3.5-4B | 4,272 | 2 | 619 / 619 | 295,819 | 5.1 | 0.1 |

\* Seconds recorded by the final run on one A40. Resumed runs record only their last segment, so these are lower bounds.

**Non-LLM run times:** trained BERT/SciBERT 155–165 s on GPU; GLiNER 499–1,031 s on GPU; scispaCy about 280 s on 8 CPU cores; HunFlair2 2,211 s on 8 CPU cores. Every configuration produced entities for 431–453 papers, apart from scispaCy-lg (untyped).

**What the failure statistics show:**
- Llama zero-shot hit the output cap on 79% of chunks and emitted 1.28 million strings: over-generation, not careful extraction.
- DeepSeek-R1 (a reasoning model) returned many strings not present in the text (32–44%).
- Mistral and Phi often used types outside the schema (15–53%).
- Qwen and Gemma were the most compliant: about 5% of strings not in the text and almost no invalid types.

Strings not found in the text, or with invalid types, are dropped before scoring, so these failures cost recall, not precision.

## 4. Does public F1 predict corpus concordance?

Spearman rank correlation across configurations between BioRED per-type exact F1 (and precision) and corpus grounding for the same type. Configurations with fewer than 50 unique strings of a type are excluded. The pairs are descriptive (not independent), so no p-values are given.

| Type | Configurations | ρ (F1 vs grounding) | ρ (precision vs grounding) |
|---|---:|---:|---:|
| Disease / phenotype | 20 | **0.75** | **0.85** |
| Gene / protein | 22 | 0.20 | 0.31 |
| Chemical | 21 | 0.25 | 0.31 |
| Organism | 19 | 0.02 | 0.27 |
| Sequence variant | 16 | 0.11 | −0.12 |

**Answer: only for diseases.** For the type that matters most in microbiome papers, organisms, public F1 does not predict corpus grounding. HunFlair2 has the best BioRED organism F1 (94.4) but grounds only 13.6% of its organism strings in the corpus. Gemma zero-shot (32.8 on BioRED) grounds 25.3%. BioRED organisms are mostly host species (human, mouse), whereas microbiome papers name bacterial taxa at every rank. Public benchmarks on abstracts are therefore a weak guide to model choice for this corpus.

## 5. Limitations

- **Grounding is a precision proxy.** Real entities missing from a vocabulary count as ungrounded, and junk that matches a synonym counts as grounded. Short gene symbols are matched case-sensitively to reduce false grounding (see `MEASUREMENT_NOTES.md`).
- **No corpus recall.** Without a gold standard, corpus recall is unknown. The number of distinct KG associations recovered is a partial, KG-bounded indicator only.
- **KG absence is not error.** A co-occurring pair absent from CTD or Disbiome is unsupported, not wrong.
- **Model selection.** One quantised checkpoint per LLM family, 4–8B parameters, one prompt per schema. Larger models or tuned prompts may behave differently.
- **Types not benchmarked.** Concepts without gold corpora (sampling, study design, data availability), which only LLMs and zero-shot NER address, are not benchmarked.

## 6. Decision

| Property | Status |
|---|---|
| Public benchmark (fair protocol, CIs, in-domain flagged) | PASS |
| Corpus benchmark (all 26 configurations over all 453 papers, completed) | PASS as a completed computational comparison |
| Corpus accuracy / recall | **NOT EVALUATED** (no gold standard) |
| Claim "LLMs beat NLP methods" | **Not supported.** LLMs match zero-shot NER and trail trained NER on public data. On the corpus, zero-shot and trained NER recover the most curated associations, while Gemma grounds organisms best |
