# Introduction — improved funnel draft (2026-11-07)

**Status: scaffold, not submission text.** BiB does not accept LLM-drafted prose
(`BIB_MANUSCRIPT_PLAN.md` §0; OUP AI policy). Use this as the fact-and-structure
reference: the authors should close the loop and rewrite it in their own voice before
anything goes into the manuscript. Citation numbers are the provisional numbering in
`../submission_readiness/REFERENCES_BRIEF_BIOINFORM.md`; renumber by first appearance
at submission. All numbers verified 2026-11-07; quality figures are model judgements
(concordance, not accuracy).

---

## The draft (~540 words)

### Paragraph 1 — the problem, quantified

> The scale of human microbiome research is now set by data aggregation rather than data
> generation. The most recent large-scale synthesis integrates 168,000 samples across 482
> BioProjects [1]. The sequencing reads behind all of these studies are downloadable, but
> much of what makes them analysable — host species, body site, disease status,
> intervention, assay protocol — is recorded inconsistently or not at all in structured
> submission metadata [2], and survives in usable form only in the text of the underlying
> publications. Cross-study comparison at this scale is therefore bounded not by data
> availability but by how much prose a project can afford to read.

### Paragraph 2 — why the status quo does not close the gap

> Manual harmonization of that prose is the rate-limiting step. Standardizing hundreds of
> papers into a shared schema takes person-months of expert reading, and annotators
> disagree on the same passage. Curated resources such as BugSigDB show what expert
> curation achieves, but their scope is fixed by curation capacity rather than by
> publication rate [3]. Adjacent computational efforts do not close the gap either:
> MiDRED annotates a corpus for knowledge-base construction over a limited paper set [7];
> DiMB-RE extracts diet–microbiome relations [8]; MINERVA aggregates microbiome–disease
> associations into a large knowledge graph [4], whose methodology has been questioned in
> a published exchange [5,6]. LLM-based metadata harmonization has been explored [9], but
> the reliability of LLMs in biomedical text processing remains contested [10]. None of
> these delivers a provenance-traceable common data model over the cited literature of a
> compendium.

### Paragraph 3 — the protocol, in pipeline terms

> We built Microbiome-CDM as a protocol rather than a single model. The pipeline ingests
> the full text of each publication, converts it to section-aware structured text, and
> applies an ensemble of recognizer programs — trained taggers, zero-shot span detectors,
> small language models and a MeSH gazetteer — whose outputs are kept separate instead of
> merged, so that every downstream row carries the identity of the program that produced
> it. A guarded normalization stage resolves mentions to canonical terms with two-model
> adjudication for contested mappings, and a schema-constrained LLM extracts
> entity–relation triples, each carrying a verbatim sentence from its source paper as
> evidence. Because no human annotation covers a corpus of this size, the protocol embeds
> its own evaluation: structural checks, character-offset verification, LLM-as-judge
> review [33] and a pre-specified comparison against the expert-curated BugSigDB [3].

### Paragraph 4 — the deliverable and what it contains

> Here we describe the pipeline and the resulting resource. The current build holds
> 165,991 canonical terms, 331,394 links to standard vocabularies, and 25,788 canonical
> entity–relation triples, each anchored to a verbatim sentence in its source paper
> (34,416 relation–evidence rows). Automated judge review of all 25,788 triples classifies
> 14,363 as supported, 5,780 as partially supported, and 4,618 as unsupported by their
> quoted evidence; these are model judgements, reported as concordance measures rather
> than accuracy claims. The resource allows researchers to query human microbiome
> relationships programmatically and trace every row back to the sentence that produced
> it, in place of reading the corpus.

---

## What changed vs the previous draft, and why

1. **Framing-rule violations removed.** "to extract, harmonize, and **validate**" and
   "**accurately** bridges the gap" both violate the framing rules
   (`MASTER_VALIDATION_REPORT`; no human validation exists). Replaced with the honest
   formulation: judge verdicts described as *model judgements, concordance not accuracy*,
   reported with the actual bucket counts rather than a blanket "validated".
2. **Paragraph 2 now carries the adjacency argument with citations.** The old P2 asserted
   "existing databases are slow or lack schema" in general terms. The improved version
   names the four nearest efforts and says precisely what each does *not* do, ending on
   the one-sentence statement of the actual gap. This is the argument reviewers ask for.
3. **Every paragraph is anchored to a number or a named resource** (specificity rule).
   The one rhetorical flourish kept ("how much prose a project can afford to read") is
   the sentence the rest of the paper cashes out.
4. **"Dynamically normalized to generate formal, domain-specific ontologies" cut.** The
   pipeline produces a canonical terminology and taxonomy with guarded mapping; "formal
   ontologies" overclaims. P3 now says what the stages actually do, including the
   source-separation property (the thing that makes the audit trail possible).
5. **"multi-phase processing lineage" transition removed from P4.** It is Methods
   material; the paragraph now ends on the resource, and the Methods transition happens
   naturally through stage order (the INTRODUCTION_OUTLINE.md transition table).
6. **Judge bucket numbers moved into P4** so the accounting (14,363 / 5,780 / 4,618,
   plus 860 conflicts + 93 no-evidence + 74 unjudged = 25,788) is introduced in the same
   breathe as the triple count — pre-empting the "how do you know these are right"
   reviewer question before it is asked.

## Citation map (provisional numbering)

[1] abdill2025 · [2] goncalves2019 · [3] geistlinger2023 · [4] langarica2025minerva ·
[5] chirumbolo2025minerva · [6] langarica2025response · [7] hogan2024midred ·
[8] hong2025dimbre · [9] higashi2024harmonization · [10] chen2025llmbench ·
[33] zheng2023mtbench (LLM-as-judge method). Renumber by first appearance: this draft's
order is already 1–10 then 33, so only [33] moves (it will become [11]).

Optional sentence with the mention count, if the authors want scale earlier:
"After normalization, 2,505,650 offset-verified mentions from four extractor sources
resolve to canonical terms…"

## Denominators warning (unchanged)

453 = on-disk papers (safe here, matches the corpus built); catalogue claims use 447
canonical (+6 dup-excluded); NER-variant benchmarks use 452; **444 never appears** —
it is the superseded historical build.
