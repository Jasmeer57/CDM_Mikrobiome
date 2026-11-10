# Master validation report

*2026-11-02. Scope: corpus metadata, terminology 1.0.1, data catalogue 3.1.1 and CDM 3.0.3 (all frozen; none was modified by this validation), plus the NER benchmark. Every number traces to a report in this folder and to `MANUSCRIPT_CLAIMS_REGISTER.csv`.*

## The decision not to annotate

**No human annotation was performed.** By decision, the human annotation study (Gate 4) was replaced by a human-free validation strategy. Consequences:

- **Not measured:** factual accuracy, recall and completeness. They are reported as **NOT EVALUATED**, never estimated.
- **Model output:** language-model judgements are reported as model judgements. Agreement between two models is not inter-annotator agreement.
- **Not simulated:** the independent CDM expert review and the legal rights review were not simulated by any model. Both remain outstanding.
- **Superseded figures:** earlier development figures (92.2% Gemma census, 59%) are not used as accuracy for the final release.

## What was done

| Workstream | Method | Report |
|---|---|---|
| A. Exhaustive integrity | every identifier, link, offset, hash, manifest and run pointer checked over all rows | `EXHAUSTIVE_INTEGRITY_REPORT.md` |
| B. Catalogue evidence | deterministic value-in-evidence checks on 447,380 values; two model judges (Llama-3.1-8B, Mistral-7B) on all 52,397 assessable records | `CATALOGUE_EVIDENCE_ASSESSMENT.md` |
| C. Terminology | grounding in NCBI Taxonomy / Gene, CTD-MeSH, Mondo, HPO, by distinct term and by mention | `TERMINOLOGY_VALIDATION_REPORT.md` |
| D. Triples | relation-family profile; entity grounding; support in CTD and Disbiome | `TRIPLE_VALIDATION_REPORT.md` |
| E. Cross-method agreement on selected objective metadata fields | an independent, unvalidated regular-expression extractor run over all 453 papers for three fields, compared with the catalogue | `SOURCE_FIRST_COVERAGE_REPORT.md` |
| F. NER benchmark | 27 public / 26 corpus configurations of 21 systems | `BENCHMARK_FINAL_ANALYSIS.md` |
| G. CDM usability | 8 research questions against the CDM vs independent keyword retrieval | `CDM_USABILITY_REPORT.md` |
| H. Interoperability | SQLite / DuckDB, CSV round-trip, keys, dictionary, versioning | `INTEROPERABILITY_FINAL_REPORT.md` |
| I. Rights readiness | per-paper licence matrix and proposed release layers | `RIGHTS_READINESS_REPORT.md` |

## Decision matrix

PASS · CONDITIONAL PASS (holds, with documented exceptions or as a proxy only) · FAIL (as a quality claim) · NOT EVALUATED · NOT DONE / OUTSTANDING.

| Component | Structural integrity | Computational evidence support | External-reference concordance | Cross-model agreement | Scientific accuracy | Scientific completeness | Human validation | Independent expert review |
|---|---|---|---|---|---|---|---|---|
| **Corpus** (453 papers, 4,006 sections) | PASS: hashes, IDs, BioProject → sample links recomputed | n/a | PASS: 156,330 compendium samples linked through 452 BioProjects | n/a | n/a | NOT EVALUATED | NOT DONE | OUTSTANDING |
| **Terminology** (2.5 M mentions, 162,409 terms) | PASS: all offsets reproduce surface forms; no dangling links | PASS: every mention anchored to text (56 without offsets) | CONDITIONAL: about 50% of organism, chemical and disease mentions ground; 11–19% of distinct terms; 98% of ENTITY terms ground nowhere | CONDITIONAL: four extraction sources kept separate | NOT EVALUATED. Type consistency **FAIL** as a quality claim (55% ENTITY) | NOT EVALUATED | NOT DONE | OUTSTANDING |
| **Mappings** (314,772 candidates) | PASS: verdicts attached to the right (term, concept) | PASS: evidence restored and verified for 331,394 rows | n/a (the mappings are themselves the external links) | CONDITIONAL: 18,272 accepted by two-model agreement only | NOT EVALUATED | NOT EVALUATED (most candidates never adjudicated) | NOT DONE | OUTSTANDING |
| **Catalogue** (52,400 records) | PASS: release QA 10/10; links resolve within paper | CONDITIONAL: 88.2% of quotes verbatim; 70.5% of text values and 75.4% of counts found literally in evidence; judges find 2.9% (Llama) / 6.6% (Mistral) unsupported; gap-filled values 3–3.5× weaker | CONDITIONAL (source-first): 88.7% accessions, 89.2% platforms, 72.1% 16S regions | CONDITIONAL: 85.0% agreement, κ 0.28 between the two models; Mistral rubric compliance 55% | NOT EVALUATED | NOT EVALUATED (proxy: 72–89% on 3 fact types) | NOT DONE | OUTSTANDING |
| **Triples** (25,788) | CONDITIONAL: 93.6% of evidence sentences anchored | CONDITIONAL: sentence evidence for every triple; 195 with conflicting polarity | CONDITIONAL: 36.5% of grounded microbe–disease triples supported (50/137); 95% unassessable by any curated KG | n/a | NOT EVALUATED. Predicate informativeness **FAIL** (68.7% generic) | NOT EVALUATED | NOT DONE | OUTSTANDING |
| **CDM 3.0.3 structure** | CONDITIONAL PASS: 118/121 tests; foreign keys not declared (**FAIL**, design) | PASS: every row names its run; offsets carry text-version hashes | n/a | n/a | n/a | n/a | n/a | **OUTSTANDING** (required for any claim of semantic coherence) |
| **CDM usability** | n/a | CONDITIONAL: identifier and provenance queries strong (Q4 97.1%, Q5 90.1%); disease and intervention queries weak (26–39%) | n/a | n/a | NOT EVALUATED | NOT EVALUATED | NOT DONE | OUTSTANDING |
| **Interoperability** | CONDITIONAL PASS: opens in standard tools; CSV round-trip; dictionary covers 866/866 columns (644 undefined) | n/a | NOT EVALUATED (OMOP / MIxS alignment left to the expert) | n/a | n/a | n/a | n/a | OUTSTANDING |
| **NER benchmark** | PASS: fixed protocol, CIs, in-domain flagged | PASS: corpus run complete (26 configurations × 453 papers) | CONDITIONAL: grounding and KG support are precision proxies | n/a | Public gold sets: PASS (measured). Corpus: NOT EVALUATED | NOT EVALUATED (no corpus recall) | n/a (public gold sets are human-made) | n/a |
| **Rights / release** | Readiness assessment complete: licence matrix consistent with catalogue quote policy 453/453. **This is not legal clearance** | n/a | n/a | n/a | n/a | n/a | n/a | **Legal review OUTSTANDING** (179 papers); not decidable by a model |

## What has been demonstrated

1. **The resource is structurally consistent and traceable.**
   - Every identifier, link, offset, hash and run pointer resolves.
   - Releases are immutable and reversible.
   - 90.1% of findings trace to a DOI, a section and a verbatim quote.
2. **Computational assessment found substantial literal correspondence between catalogue values and their associated evidence, alongside a subset of potentially unsupported values.**
   - 70.5% of text values and 75.4% of counts occur literally in their evidence; literal matching is not semantic support.
   - Model-based assessments by two judges provide additional but limited evidence of support. Llama is not independent of the G3 curation stage, Mistral followed the rubric for 55% of values, κ between them is 0.28, and neither checks that a quote exists in the paper.
   - The potentially unsupported values cluster in gap-filled values and in storage, preservation and DNA-extraction fields. They are listed, for prioritising a future release, in `evidence_judge/BOTH_JUDGES_FAIL.csv`; neither judge's verdict is definitive.
   - These evaluations do not establish scientific accuracy.
3. **Cross-method agreement on selected objective metadata fields is 72–89%** (accessions, platforms, 16S regions). The comparison extractor is itself limited and unvalidated; this is not recall and says nothing about other fields.
4. **Trained and zero-shot NER remain competitive with, or better than, small open LLMs.** On public gold standards a trained tagger is best. Public F1 predicts corpus behaviour only for diseases.

## What remains unknown

1. **Whether catalogue values, terms, mappings and triples are correct.** No human ground truth exists.
2. **What the catalogue misses.** Recall is unknown beyond accessions, platforms and 16S regions.
3. **Whether the CDM is semantically coherent and adoptable by others.** This requires the independent expert review.
4. **Which papers' text and quotes may be redistributed.** This requires the legal/library review of 179 papers.
5. **The correctness of the ~95% of triples outside any curated KG, and of the 98% of ENTITY terms outside any vocabulary.**

## Weaknesses the paper must state prominently (as results, not a generic limitations paragraph)

- **Terminology:** 55% of canonical terms carry only the generic type ENTITY, and many typed terms are not entities.
- **Triples:** 68.7% use a generic relation.
- **Retrieval:** disease- and intervention-defined questions retrieve a quarter to two-fifths of the papers a keyword search finds.
- **Model judges:** they are lenient. Llama took part in the G3 curation stage, and Mistral followed the rubric for only 55% of values. Do not write that independent judges confirmed the catalogue's reliability.
- **Structure is not semantics:** 118 / 121 structural tests and interoperability checks do not establish semantic coherence or readiness for adoption. Foreign keys are undeclared and no expert has reviewed the model.
- **Rights readiness is not legal clearance:** 179 papers await legal/library review, which blocks public release.

The terminology and triple limitations (55% ENTITY; 98% of ENTITY terms ungrounded; 68.7% generic relations) restrict semantic querying and downstream knowledge-graph use, and must appear in the Results, not only among the limitations.

## Overall decision

**CONDITIONAL PASS for submission as a resource paper whose claims are limited to structure, provenance and computational evidence.**

- **Allowed claims:** structural integrity; traceability; the literal evidence-support, model-assessment, external-concordance and cross-method-agreement figures above, each with its caveat; benchmark results.
- **Not allowed:** accuracy, recall, completeness or "validated" without qualification; "independent judges confirmed"; "semantically coherent" or "ready for adoption"; "legally cleared" or "publicly available" before B1–B4; "LLMs beat NLP methods"; any human-validation language; any claim about the 168K-sample compendium itself beyond BioProject-level linkage.
- **Before public release:** B1 legal review, B2 licence choice, B3 redacted build, B4 DOI (`REMAINING_PUBLICATION_BLOCKERS.csv`).
- **Before claiming CDM semantic coherence:** B5 independent expert review.
