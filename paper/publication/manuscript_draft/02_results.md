# Draft: Results

*Draft 0.1, 2026-11-02. Claim IDs in brackets refer to `../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (80 / 80 numeric claims recompute from the frozen releases). Workstream reports in `../final_validation/` hold the full tables. **No human annotation was performed; no result below is an accuracy estimate unless it is F1 on a public gold standard.***

## 1. The resource (Figure 1–3)

**Corpus:**
- 453 papers (447 distinct publications) describe the compendium's BioProjects [C01, C02]. Five publications are shared by 11 BioProjects and are flagged, not merged [C03, C04].
- These BioProjects hold 156,330 of the compendium's 168,464 samples [C05, C06]. This is a BioProject-level link; no sample was re-analysed.
- The text is split into 4,006 sections, each fixed by a SHA-256 hash; all hashes verify [C07, C08].

**Terminology:**
- Four extraction sources yielded 2,505,684 mentions, kept separate by source [M01, M03–M06].
- All but 56 mentions carry offsets that reproduce their surface form [M07, M09].
- 2,198,766 mentions link to one of 162,409 canonical terms [M10, T02]. That is terminology 1.0.1's 165,991 terms less 3,582 removed in review [T01, T03].
- 314,772 vocabulary-mapping candidates passed guards [P02]. 18,272 (for 16,750 terms) were accepted by agreement of two models; none were accepted by a person [P05, P06].

**Catalogue:**
- 52,400 records in six tables (cohorts, sample groups, assays, datasets, data assets, 24,272 findings) [K01, K02].
- 88.2% of supporting quotes are located verbatim in the paper, 8.0% approximately, and 3.8% not at all [K08–K10].

**CDM 3.0.3:**
- Integrates all of the above in 44 tables and 866 columns [X01, X02].
- Every row names one of 45 registered runs; 4 runs are marked as not independently verifiable [X03, X04, X06].
- 118 of 121 schema, value and provenance tests pass; 2 fail and 1 is conditional [X07].

## 2. Structural integrity (Workstream A)

Every identifier, link, offset, hash, manifest and run pointer was checked over all rows. No dangling link, cross-paper link or hash mismatch was found.

Documented exceptions:
- foreign keys are not declared, because multi-valued links prevent it;
- 6.5% of triple-evidence mentions are unanchored;
- 9,940 canonical terms are unreachable from any mention;
- 215 coded values fall outside their vocabulary.

None of these loses data. Three silent defects found during development are now regression tests: a load step that dropped 557,625 competing mentions, mapping verdicts attached to the wrong term, and offsets shifted in 75 sections. (`EXHAUSTIVE_INTEGRITY_REPORT.md`)

## 3. Catalogue values against their evidence (Workstream B; Figure 6a–c)

**Deterministic checks:**
- 70.5% of 392,587 populated text values and 75.4% of 12,114 stated counts occur literally in their evidence passage [E01, E02].
- Coded values (42,679) cannot be string-checked.
- A value absent from its passage is not necessarily wrong: normalised and paraphrased values fail a literal match.

**Model judgements:**
- **Coverage:** two model families that did not extract catalogue values judged every assessable record (52,397).
- **Independence:** Mistral-7B took no part in building the catalogue. Llama-3.1-8B had served in the G3 curation stage.
- **Unsupported values:** of validly labelled text values, Llama judged 2.9% and Mistral 6.6% unsupported by the passage [J01, J02].
- **Rubric compliance:** Mistral returned a valid label for only 55.4% of values [J03].
- **Agreement between the two models:** 85.0%, with κ = 0.28, low because nearly every value passes [J04, J05].

**Interpretation.** Computational assessment found substantial literal correspondence between catalogue values and their evidence, alongside a subset of potentially unsupported values. The model-based assessments add evidence of support that is limited: one judge took part in curation, the other followed the rubric for only about half of the values, their agreement beyond chance is low, and neither checks that a quote exists in the paper. These assessments do not establish scientific accuracy, and neither judge's verdict is treated as definitive. Three signals nevertheless point to the same weak spots:
- values not found literally in their evidence are judged unsupported 2.6 (Mistral) to 4.9 (Llama) times as often as values that are;
- values added by the gap pipeline are judged unsupported 3–3.5 times as often as original extractions (Mistral: 19.1% vs 5.6%) [J07, J08];
- the 2,023 values both models fail concentrate in DNA extraction, storage, preservation and timepoint fields [J06].

**What the judges cannot test.** They do not test whether a quote is genuine: unlocated quotes pass as often as exact ones, because the judge sees only the quote. Quote authenticity rests on offset anchoring alone. (`CATALOGUE_EVIDENCE_ASSESSMENT.md`)

## 4. Cross-method agreement on selected objective metadata fields (Workstream E; Figure 6d)

A regular-expression extractor that uses no model recovered three objective fact types from all 453 papers. The catalogue contains:
- 88.7% of the stated project accessions [V01];
- 89.2% of the sequencing platforms [V02];
- 72.1% of the 16S regions [V03].

Of 306 papers stating their own BioProject, 20 are missing it in the catalogue. The comparison extractor is pattern-based and unvalidated, so it misses facts stated in other forms. The figures are agreement between two methods on three fields, not recall, and do not speak to the completeness of other catalogue fields. (`SOURCE_FIRST_COVERAGE_REPORT.md`)

## 5. Terminology and triples: external concordance and information-quality limits (Workstreams C, D; Figures S1–S3)

These two layers have serious information-quality limitations, which restrict their use for semantic querying and knowledge-graph analysis. The figures below are reported as primary results, not as caveats.

**Terminology grounding.** Share of distinct terms vs share of mentions grounding in NCBI Taxonomy, NCBI Gene, CTD/MeSH, Mondo or HPO:

| Type | Distinct terms | Mentions |
|---|---:|---:|
| Organisms | 12.2% | 48.5% |
| Chemicals | 18.5% | 50.0% |
| Diseases | 16.1% | 54.5% |
| Proteins | 11.1% | 27.6% |

- Frequent terms ground well; the long tail does not.
- 55% of canonical terms (89,799) carry only the generic type ENTITY, and 98.3% of these ground in no reference [T05].
- Nine of the 14 CDM types have no matching reference vocabulary and were not evaluated.

**Triples.**
- 68.7% of 25,788 relation triples use the generic relation [R01, R02].
- Only 4.9% fall in pair types that a curated knowledge graph covers.
- Of 137 microbe–disease triples with both entities grounded, 50 (36.5%) are curated in Disbiome.
- Absence from a knowledge graph is reported as unsupported, not wrong. (`TERMINOLOGY_VALIDATION_REPORT.md`, `TRIPLE_VALIDATION_REPORT.md`)

## 6. Using the CDM to answer research questions (Workstream G)

Eight research questions were run against the CDM and compared with paper sets found independently by keyword rules over the text.
- **Identifier and provenance questions perform well:**
  - papers with a publicly accessioned dataset: the CDM finds 97.1% of those found by keyword rules;
  - findings traceable to DOI, section and verbatim quote: 90.1%.
- **Disease- and intervention-defined questions perform poorly:** 26–39% of keyword-found papers are retrieved. The information sits in sparsely and inconsistently filled fields. (`CDM_USABILITY_REPORT.md`)

## 7. NER benchmark (Workstream F; Figures 4–5)

**Public gold standards.** 27 configurations of 21 systems were compared [B05].
- **Best overall:** PubTator3 on BC5CDR (90.1, in-domain) and HunFlair2 on BioRED (80.6) [B01, B02].
- **Best LLM:** Qwen3.5-4B with three examples, 69.5 and 66.2 [B03, B04]. This ties zero-shot GLiNER on BC5CDR (69.2) and exceeds it on BioRED (60.4).
- **Few-shot prompting** helped some LLMs and hurt others.

**Microbiome corpus.** All 26 configurations completed on all 453 papers [H03].
- **Grounding:** no configuration grounded more than 41.3% of its strings of any type. Gemma-4-E4B was the LLM closest to the trained taggers.
- **Unreliable LLMs:** several LLMs invented strings (up to 44%) or used types outside the schema (up to 53%). Llama zero-shot hit the output cap on 79% of chunks.
- **Curated associations:** zero-shot taggers recovered the most Disbiome associations (GLiNER v2.5 biomed: 1,456, 86.5% of all found) [H06].
- **Public vs corpus:** public F1 predicted corpus grounding for diseases (ρ 0.75) but not for organisms (ρ 0.02) [H04, H05]. (`BENCHMARK_FINAL_ANALYSIS.md`)

## 8. Summary of what is and is not established

See the decision matrix in `MASTER_VALIDATION_REPORT.md`:
- **Established:** structural integrity, traceability, computational evidence support and partial external concordance.
- **Not evaluated:** scientific accuracy and completeness, because no human annotation was performed.
- **Outstanding:** independent expert review of the CDM.
