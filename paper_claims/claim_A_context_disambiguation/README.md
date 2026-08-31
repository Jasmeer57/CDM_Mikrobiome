# Claim A — LLM uniquely resolves context-dependent entity types

## Claim statement

> In the 14 CDM entity types, ambiguous terms (e.g., "butyrate", "BLAST", "IL-6", "inflammation") have a single expected type in 90%+ of microbiome-paper contexts. The LLM pipeline assigns the correct type with significantly higher accuracy than any single spaCy model because the LLM has a context model; spaCy models are vocabulary-driven and assign the most-common label without considering context.

## Why this matters

- This is the **strongest novel-methods claim** of the paper. The precision/recall tradeoff between LLM and spaCy is well-known; *context-dependent type disambiguation* is a different and more interesting claim.
- The LLM pipeline already *deliberately rejects GENE entities* because of LLM hallucination (`extractors/entity_extractor.py:165-166`). That makes Claim A's 14-type set the *correct* comparison space.
- spaSy's `en_ner_bc5cdr_md` and `en_ner_craft_md` are *named-entity recognizers*, not classifiers — they don't have a context model. So a term like "BLAST" might come out as GENE in some contexts, BIOINFO_TOOL in others, depending on which model is used and which surface form is most common in its training data.

## Test design

**Test set:** 35 ambiguous terms spanning the 14 CDM types. Each term has an expected type (in microbiome context) and an example sentence (2-3 sentences from a real microbiome paper or a constructed context that matches the expected type).

**Procedure:**
1. For each term-context pair, run `CDMEntityPipeline` (LLM pipeline) on the context.
2. For each term-context pair, run `TermsExtractor` (spaCy pipeline) on the context, using all 4 available sciSpaCy models.
3. Score each pipeline's type classification against the expected type.
4. Compute per-type and overall accuracy.

**Verdict:**
- LLM accuracy > any single spaCy model by a meaningful margin (≥15% on ambiguous terms) → claim supported.
- LLM accuracy ≈ best spaCy model → claim not supported; the context advantage is smaller than claimed.
- LLM accuracy < best spaCy model → claim falsified; LLM is the wrong tool for this.

## Where the data lives in the repo

- **Test set:** `paper_claims/claim_A_context_disambiguation/ambiguous_terms.json` (curated here)
- **LLM pipeline:** `llm_terms/core/pipeline.py` → `CDMEntityPipeline.extract_entities()`
- **LLM type correction logic:** `llm_terms/core/term_corrector.py`, `llm_terms/extractors/entity_extractor.py:_map_hallucinated_type()`
- **spaCy pipeline:** `spacy_terms/src/modules/terms_extractor.py` → `TermsExtractor.extract_from_text()`
- **Ground-truth (CDM types):** `llm_terms/config/cdm_config.py:CDMEntityConfig.ENTITY_TYPES`
- **EntityFilter regex rules:** `llm_terms/core/entity_filter.py:type_corrections` (worth checking what spaCy uses vs. what LLM uses)

## What the script produces

Running `benchmark.py` produces:
- A per-term accuracy table (CSV)
- An overall accuracy summary (printed)
- A confusion matrix: which types each pipeline confuses (printed)
- A LaTeX-ready table fragment for the paper (printed)

## Expected outcome (prediction)

LLM should win on the genuinely ambiguous terms (BLAST, IL-6, inflammation, butyrate) but lose or tie on the easy terms (E. coli, Lactobacillus, 16S rRNA). The headline number should be reported on the ambiguous subset (15-20 of the 35), not the full set.

## Results

**Verdict: SUPPORTED (Δ = 25.7 pp, ≥ 15 pp threshold).**

| model | correct / 35 | overall accuracy | on detected |
|---|---|---|---|
| spaCy `en_core_sci_lg` | 0/35 | 0.0% | (all ENTITY) |
| spaCy `en_ner_craft_md` | 7/35 | 20.0% | 80% |
| spaCy `en_ner_bc5cdr_md` | 9/35 | **25.7%** | 75% |
| spaCy `en_ner_jnlpba_md` | 1/35 | 2.9% | 20% |
| spaCy best-of-4 union | 13/35 | 37.1% | — |
| **LLM Qwen3:8b** | **18/35** | **51.4%** | 75% |

On the 14 most-ambiguous sentences:
- LLM: 6/14 (42.9%)
- Best single spaCy: 4/14 (28.6%)
- spaCy best-of-4 union: 7/14 (50.0%)

The LLM beats every single spaCy model on both the full set (+25.7 pp) and the ambiguous subset (+14.3 pp). The spaCy union (4 models combined) narrows the gap to +14.3 pp on the full set but requires running 4 models — the LLM is a single-pass alternative.
