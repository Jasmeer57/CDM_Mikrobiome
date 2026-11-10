# Final manuscript QA

*2026-11-02. Drafts checked: `manuscript_draft/00_introduction.md` (v0.3), `01_methods_and_resource.md`, `02_results.md`, `03_discussion.md`, `FIGURE_PLAN.md`. Frozen releases and frozen validation results were not modified.*

## Summary

| Check | Result |
|---|---|
| Numerical claims vs claims register | **PASS**: 278 numbers found; 190 trace to `MANUSCRIPT_CLAIMS_REGISTER.csv`, 88 to frozen reports, **0 untraced**. Register: 88 / 88 numeric claims recompute (`claims_register.py`; `manuscript_number_audit.py`) |
| References | **PASS with 3 open items**: 41 / 41 references verified from registries; 0 `[CITE]` placeholders left; 2 unresolved choices (GLiNER v2.5 biomed paper; Qwen3.5 report) |
| Reference supports claim | **PASS after revision**: 3 Introduction sentences revised because the source did not support them as written (§3) |
| Prohibited claims (`PUBLICATION_INDEX.md`) | **PASS after 3 fixes** (§4) |
| Validation framing (`final_validation/CHANGE_RECORD.md`) | **PASS** (§5) |
| No-human-annotation decision preserved | **PASS**: stated in Introduction, Methods (twice), Results header and Discussion limitation 1 |
| Figures and supplementary references | **PASS**: every cited figure exists in the plan; S4–S6 planned but not yet cited in text |
| Data availability statement | **OPEN**: `[PENDING]`; depends on rights review (B1–B4) |
| Code availability statement | **MISSING**: no statement, no public repository, no LICENSE file (B16) |
| Journal format | **OPEN DECISION**: structure does not match a *Scientific Data* Data Descriptor (§6) |

## 1. Numbers

- `MANUSCRIPT_NUMBER_AUDIT.csv` lists every number with its draft, status and context.
- New claims registered today: C09–C10, M13–M14, K12–K14, H07 (all MATCH).
- Two rounded figures were replaced by exact values: 168,000 → 168,464 and 41% → 41.3%.
- No scientific number changed.

## 2. References

`VERIFIED_REFERENCES.md` and `REFERENCE_TO_CLAIM_MAPPING.csv` (52 citation uses).

Every entry was resolved from Crossref, the arXiv API, PubMed or the Hugging Face API, with a stored record (`references_source/bibliography.json`). No bibliographic detail was written from memory.

**Open items — all resolved 2026-11-08 (evidence in `VERIFIED_REFERENCES.md`, "Resolved 2026-11-08"):**
1. GLiNER v2.5 biomed: the GLiNER-BioMed paper (btag322) released v1.0 models only; the v2.5 checkpoint is a later separate release and is not described by any paper. The manuscript never cited btag322 for it (v2.5-medium results cite GLiNER2). Model card has no paper; kept as-is.
2. Qwen3.5-4B: no technical report exists; the model card (HF, last modified 2026-03-02) is the canonical citation — status confirmed, not a placeholder.
3. Mondo: preprint only (no journal version exists); venue corrected to medRxiv in `reference.bib` (Crossref posted-content records report publisher "openRxiv"; the true server is in `institution`).

## 3. Sentences revised because the reference did not support them

| Slot | Original | Problem | Revised |
|---|---|---|---|
| R1 | "168,464 samples" of "human microbiome" data | Source: human **gut** 16S samples | "168,464 publicly available human gut 16S rRNA amplicon samples" |
| R3 | metadata "sparse and inconsistent" | Source measures standardisation, not sparsity | "often poorly standardised and inconsistent" |
| R4 | manual curation "does not scale to hundreds of studies" | **Contradicted**: BugSigDB manually curated more than 600 studies | "possible at the scale of hundreds of studies, but it has required sustained community effort" |
| R6 | LLMs "promise extraction … including for concepts no corpus covers" | Source shows zero/few-shot LLMs trail fine-tuned models; says nothing on uncovered concepts | Cited for applicability **and** its limits; the uncovered-concepts clause is stated as the authors' premise, uncited |
| Gap 1 | LLMs and NER "rarely compared under one protocol" | Chen et al. 2025 compare them on 12 benchmarks | Narrowed to "rarely … on full-text microbiome literature" |

## 4. Prohibited-claim scan

Scan terms: validated, accuracy, recall, completeness, confirm, independent judge, semantically coherent, ready for adoption, legally, publicly available, beat, coverage, inter-annotator, consistent with their, reliable. Every hit was read in context.

**Fixed:**
- **Stale Methods sentence:** "that is assessed by human validation (below)" → "assessed only computationally … no human validation was performed".
- **Introduction:** "provenance-complete CDM" → "provenance-tracking CDM". Four runs are unverified, 56 mentions have no offsets and 142 datasets have no section.
- **Discussion table:** "Completeness: not established beyond the three fact types" implied completeness was established for those three. It now reads "not established; cross-method agreement on three objective fields (72–89%) is not recall".

**Kept, by decision:** Methods discloses the development-era Gemma census (92.2%) explicitly as "not an accuracy estimate". This complies with the rule against using it as final-release accuracy. The authors may still prefer to delete it.

**All other hits are negations or correct uses**, for example "not accuracy", "not recall", "completeness … not established".

## 5. Framing against the change record

| Required framing | Status |
|---|---|
| "Substantial literal correspondence … a subset of potentially unsupported values"; no "most values consistent" | in Results §3 and master report |
| No "independent judges confirmed"; Llama's role in G3 disclosed; Mistral 55% compliance | Methods, Results |
| Source-first = "cross-method agreement on selected objective metadata fields", not recall; extractor limits stated | Methods item 5, Results §4, Discussion table |
| Structure ≠ semantic coherence | Discussion "Structure is not semantics"; Methods limitations |
| Rights readiness ≠ legal clearance | Methods availability, Discussion limitation 8 |
| ENTITY typing and generic relations reported as results, not buried | Results §5 header; Discussion section |
| "LLMs beat NLP methods" absent | not present |

## 6. Journal fit (*Scientific Data*, pages fetched 2026-11-02)

The target journal has not been confirmed by the authors. If it is *Scientific Data*, the guidance (saved in `journal_requirements_source/`) means the following.

**Data Descriptor format:**
- Sections: Background & Summary, Methods, Data Records, Data Overview (optional), Technical Validation, Usage Notes (optional), Data Availability, Code Availability.
- Quote: *"Please do not include general results or analyses in this section (or anywhere in the paper)"*.
- Data Overview is limited to "1–2" figures or tables.
- **Consequences:**
  - The current Results/Discussion structure and the LLM-vs-NER benchmark (Figures 4–5) do not fit a Data Descriptor.
  - The computational validation fits **Technical Validation**.
  - Options: (a) Data Descriptor, with the benchmark reduced to a technical note or moved to a separate article; (b) the journal's *Article* type, which allows IMRaD and covers "data standards, data curation".
  - **Authors' decision.**

**Title:** at most 110 characters, no colons, parentheses or self-made acronyms. The current working title has 123 characters. Candidates, not adopted:
- "A literature-derived data model and evidence-linked catalogue for a human gut microbiome compendium" (99 characters);
- "Evidence-linked study metadata from the literature behind a human gut microbiome compendium" (91 characters).

**Abstract:** recommended at most 170 words, with no claims of new scientific findings. Not yet drafted.

**Data at first-round review:** must be downloadable anonymously from any URL; a temporary location is allowed. A formal repository is required from the second round. A DOI is therefore not needed at initial submission, but reviewers need a download (§7 of the checklist).

**Data compilations:**
- Quote: *"Care must be taken to ensure all extracted fields are accurate and that the DOI … of the source article is clearly visible at the data level."* The DOI part is satisfied for 447 of 453 papers; 6 have no DOI in the CDM (HMPAPER_000063, HMPAPER_000073, HMPAPER_000117, HMPAPER_000170, HMPAPER_000249, HMPAPER_000419) and need another visible source identifier (PMID / URL). The accuracy part is a **risk**, because no human accuracy evaluation exists.
- The policy also says text cannot be re-shared "without permission unless the primary work is under a permissive licence (e.g. CC0 or CC-BY)", and advises consulting institutional rights experts. This matches B1.

**Data citation:** cite source articles and datasets; references are capped at 500. The 447 source publications could be cited in the reference list, or listed in the data file only.

**Not stated on the pages:** whether a resource without human accuracy evaluation is acceptable. **Recommendation:** send a pre-submission enquiry to the editors describing the computational validation and its stated limits.

## 7. Remaining manuscript work (authors)

1. Choose the journal and article type. Restructure if it is a Data Descriptor.
2. Write the Abstract, Data Records, Usage Notes, Data Availability and Code Availability sections.
3. Resolve the three reference open items and apply the journal's reference style; DOIs are already stored.
4. Cite figures S4–S6 in the text, or drop them.
5. Shorten the title.
