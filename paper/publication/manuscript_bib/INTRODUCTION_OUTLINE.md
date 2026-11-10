# Introduction outline — 4-paragraph funnel (added 2026-11-07)

*Author note for the BiB submission (BIB_MANUSCRIPT_PLAN §3 §1, budget ~550 words total:
130 + 150 + 150 + 120). Bracketed numbers = the provisional reference numbering in
`../submission_readiness/REFERENCES_BRIEF_BIOINFORM.md` (renumber by first appearance).
Facts verified as of 2026-11-07; "concordance, not accuracy" rule applies to all quality numbers.*

## Paragraph 1 — The broad problem (data explosion) (~130 words)

- **Hook:** human microbiome research produces rapidly growing sequence data AND primary
  literature describing design, phenotypes, cohorts, interventions.
- **The catalyst (specific):** the Cell 2025 compendium — integration of **168,000 samples
  across 482 BioProjects** [1 @abdill2025] — demonstrates the value of cross-study comparison,
  but the biological context is **derivable only from the cited publications** (our corpus is
  exactly that literature: 453 papers).
- **The bottleneck:** sample archives carry sparse, inconsistent metadata [2 @goncalves2019];
  the metadata that decides the analysis (host environment, condition, intervention, sample
  site) survives only as unstructured full text.

## Paragraph 2 — Limitation of the status quo (~150 words)

- **Pain point:** manually reading and curating hundreds of papers to a shared schema is
  intractable and error-prone; even expert-curated resources reflect bounded scope and
  publication-rate backlog [3 @geistlinger2023 BugSigDB].
- **The gap:** (i) curated databases **cannot scale** to the literature; (ii) existing corpora
  and KGs in this space — MiDRED [7 @hogan2024midred], DiMB-RE [8 @hong2025dimbre], MINERVA
  [4 @langarica2025minerva — see its evaluation commentary [5] [6]] — address adjacent fractions
  (corpus annotation, diet-associations, KG visualisation) rather than a provenance-traceable
  CDM over a compendium's cited literature; (iii) LLM-based metadata-harmonisation work exists
  but is unregistered preprint territory [9 @higashi2024harmonization]; (iv) LLM limits in
  biomedical NLP are documented [10 @chen2025llmbench], so plain "give it to an LLM" is not a
  solution — a protocol with checks is.
- Note for authors: do NOT cite 10.1101/2024.10.26.620145 as "EMBERS".

## Paragraph 3 — The solution (~150 words)

Narrate the origin story in pipeline terms (verbs → academic nouns), NO new citations:

| Origin story phrase | Manuscript phrasing |
|---|---|
| harmonizing full text into markdown, segmented sections | automated ingestion with section-aware segmentation of full text |
| entity extraction (many programs) | multi-program ensemble NER (trained taggers, zero-shot GLiNER-family, small LLMs, gazetteers), sources kept separate |
| creating ontologies/terms | guarded terminology normalisation and taxonomy generation with evidence-anchored definitions |
| knowledge extraction → triples | schema-driven LLM extraction of entity–relation triples with verbatim evidence anchors and two-model adjudication |

Add one sentence naming the evaluation design: because no human annotations exist, the
protocol layers structural checks, evidence anchoring (char offsets), LLM judges
[33 @zheng2023mtbench] and a pre-registered comparison against human-curated BugSigDB [3].

## Paragraph 4 — The paper overview (~120 words)

- **Deliverable:** here we present Microbiome-CDM (pipeline + released CDM bundle).
- **Scale (verified numbers — do not mix with other builds):**
  453 papers · 4,006 sections · 2,505,650 offset-verified mentions · 165,991 canonical terms ·
  331,394 term–concept mappings · **25,788 canonical entity–relation triples**, each with its
  own anchor sentence (34,416 relation-evidence rows). Judge verdicts (model judgements,
  not accuracy): SUPPORTED 14,363 / PARTIAL 5,780 / NOT_SUPPORTED 4,618 / CONFLICTS 860 +
  93 no-evidence + 74 unjudged = 25,788.
- **Impact:** programmatic queryability of human-microbiome relationships without reading
  hundreds of papers; fully reversible audit trail.

## Denominators rule (critical when writing)

453 on-disk papers = upstream + terminology; 447 canonical (+6 dup-excluded) = corpus_v2
canonical layer for catalogue claims; 452 = NER-variant analysis universe (minus
`HMPAPER_000372`); 444 = superseded historical build — **never** in this paper's numbers.

## Transition into Methods (seamless, no new citations needed)

| Funnel claim | Methods section | Numbers to carry |
|---|---|---|
| "automated ingestion and segmentation" | Stage 1 corpus & sectioning | 453 papers, 4,006 sections, 26.9M chars |
| "ensemble NER" | Stage 2 | 4 separate extractor sources; per-model benchmark + corpus-judged validity kept distinct |
| "guarded normalisation + taxonomy" | Stage 3 | 2.5M mentions → 165,991 terms; 331,394 mappings; two-model adjudication |
| "catalogue & CDM" | Stage 4 | 447 canonical papers, evidence-anchored catalogue, CDM modules |
| "checked without humans" | Stage 5 | 4 evaluation layers; L judges; N01-N11 BugSigDB comparison |
