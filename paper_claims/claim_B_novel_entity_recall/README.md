# Claim B — LLM surfaces novel entities not in any spaCy vocabulary

## Claim statement

> The LLM pipeline extracts entities that are not present in the union of the four sciSpaCy vocabularies (`en_core_sci_lg`, `en_ner_craft_md`, `en_ner_bc5cdr_md`, `en_ner_jnlpba_md`), and at least a substantial fraction of these are *truly novel* (not synonyms or surface variants of vocab terms) — entities the LLM recognizes from contextual cues that no vocabulary-driven NER could match.

## Why this matters

- Distinguishes the LLM from a synonym-finding wrapper around spaCy.
- A 1:1 synonym-only comparison would be a weak claim; novel-entity recall is the real evidence that the LLM contributes something vocabularies can't.
- This is **not** a "LLM is smarter" claim — it's an architectural claim: the LLM sees context, the spaCy vocab is closed-world.

## Test design

1. Build the union of all 4 spaCy NER vocabularies from the spaCy pipeline's output across `papers_txt/*.txt`. (spaCy models that aren't installed locally are skipped — the script reports which ones ran.)
2. Build the LLM-extracted entity set from the LLM pipeline's output across the same files.
3. Set difference: `novel = LLM_set - spaCy_union`. Normalize case + strip punctuation.
4. For each novel entity:
   - Surface-form similarity (Levenshtein / token overlap) to nearest spaCy vocab term. If similarity ≥ 0.85, classify as **synonym/variant** — not a real "novel" claim.
   - Otherwise, classify as **truly novel**. These are the candidates for the paper.
5. Report:
   - Total LLM entities
   - Total spaCy vocab entities
   - Novel (LLM-only) count
   - Of those, fraction that are truly novel
   - Top 20 most-frequent truly-novel entities

## Where the data lives in the repo

- **spaCy pipeline output (per paper):** `spacy_terms/output/step3_deduplicated_terms_*.csv` or live re-run via `python spacy_terms/main.py --input_dir papers_txt/`
- **LLM pipeline output (per paper):** `*.cdm_entities.json` files, or live re-run via `python llm_terms/main.py --input <paper>`
- **spaCy vocab sidecar:** `spacy_terms/data/vocab/CONCEPT.csv`, `CONCEPT_SYNONYM.csv` (OMOP, smaller)
- **Benchmark script:** `paper_claims/claim_B_novel_entity_recall/benchmark.py`

## Verdict

- LLM finds N truly-novel entities, where N ≥ 50 (across the full corpus): **claim supported**
- LLM finds < 50: **claim weak; consider rephrasing** ("LLM catches more context-dependent entities, including N novel ones")
- LLM finds 0: **claim falsified**; the LLM is essentially a synonym wrapper here. (Unlikely given the project's design, but check.)

## What the script produces

Running `benchmark.py` produces:
- `results/llm_entity_set.txt` — every LLM entity, normalized, one per line
- `results/spacy_vocab_union.txt` — every spaCy vocab term
- `results/novel_entities.csv` — the diff with similarity scores and classification
- `results/summary.json` — counts and verdict
- Prints the top-20 novel candidates to stdout for manual review

## Manual review

After running, take the top 20 truly-novel candidates and read each one in its source context (one or two sentences from the paper). The question: is the LLM picking up a real biomedical concept (e.g., a 2023-coined metabolite abbreviation, a study-specific cohort name, a new pathway), or a noisy string (e.g., a long author affiliation, a chemical formula not in any vocab)?

For the paper, the headline number is "the LLM extracted N truly novel entities that are not synonyms of any spaCy vocab term." The qualitative table lists the most interesting 10-20.
