# Draft: Methods and Resource description

*Working title: A literature-derived common data model and evidence-backed data catalogue for a 168,464-sample human microbiome compendium.*

*Target: Scientific Data (Data Descriptor); alternative GigaScience.*

*Draft 0.2, 2026-11-02. Every number is recomputed from the frozen releases by `src/scripts/final_validation/claims_register.py` (`../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv`, claim IDs in brackets; 80 / 80 match). `[PENDING]` marks items that depend on people outside the project. **No human annotation was performed; this draft must not be read as reporting human-validated accuracy.***

---

## Methods

### Corpus

The corpus consists of the publications describing the BioProjects of the human microbiome compendium of Abdill et al. (2025), which contains 168,464 samples.
- **Papers:** 453, each linked to one BioProject. Five publications are shared by 11 BioProjects, giving 447 distinct publications. Shared publications are flagged rather than merged. [audit A.papers, A.publications_*]
- **Linked samples:** 156,330 of the 168,464 compendium samples (92.8%) belong to 452 of these BioProjects; one BioProject (PRJNA803937) has no samples in the compendium. Links are at BioProject level; individual samples are not linked to individual statements in the papers. [audit A.compendium_*]
- **Text:** full texts were converted to plain text and segmented into 4,006 sections (Abstract 247, Introduction 216, Methods 385, Results 379, Discussion 482, Supplementary 239, Acknowledgements 431, References 385, other 1,242). Each section's text is stored with its SHA-256 hash; all 4,006 hashes were re-verified against the text for this release. [audit A.sections, A.section_hash_mismatch]
- **Offsets:** all character offsets in the resource index this section text.

### Entity mention extraction

Mentions were extracted section by section with four independent sources, kept as separate records rather than merged:

| Source | Description | Mentions |
|---|---|---:|
| `cpu_ensemble_v1` | ensemble of CPU NER models | 1,705,449 |
| `qwen35_vllm_body_v1` | Qwen3.5-4B via vLLM, section bodies | 366,123 |
| `qwen_ollama_cell7c_v1` | Qwen3.5 via Ollama | 186,024 |
| `mesh_gazetteer_2026` | MeSH 2026 dictionary matching | 248,088 |

[CDM 3.0.3 `term_mention.extraction_run_id`; run registry `extraction_run`]

- **Total:** 2,505,684 mention records (2,505,735 before 51 byte-identical duplicates were removed at load).
- **Offsets:** 2,505,628 mentions carry offsets, and every one reproduces its surface form exactly from the section text. In 75 sections a systematic offset shift was detected and corrected (156,870 mentions in the CDM); 56 mentions could not be anchored and carry no offsets. [M07–M09; terminology 1.0.1 counts before de-duplication: 156,884 and 85]

### Canonical terms, definitions and vocabulary mapping

**Canonical terms:**
- Mentions were normalised (lower-case, alphanumeric collapse) and grouped into 165,991 canonical terms (terminology 1.0.1), each the pair (normalised string, type). A review by a second model family (DeepSeek-R1-Distill-Qwen-7B) removed 3,582 non-terms, leaving **162,409** canonical terms in CDM 3.0.3; removed terms are kept with their reason. [T01–T04]
- Each term has one of 14 CDM types (organism, protein, chemical, disease, DNA/RNA, cell type, sample method, lab method, data analysis, pathway, experimental method, study design, genomics, clinical) or the generic type ENTITY (89,799 terms, 55%). [T05]
- 2,198,766 mentions (87.8%) link to a canonical term; 7,072 are ambiguous and 299,846 have none. [audit B.*]

**Definitions:** definitions were taken only from the papers themselves, either by rule patterns or by a language model that had to quote the defining passage. 6,773 definitions for 3,397 terms remain after review; every one is located verbatim in its section (6,460 at the stated offsets, 313 relocated). [CDM `term_definition`]

**Vocabulary mapping:**
- 334,231 candidate mappings were retrieved from BioPortal [@whetzel2011bioportal], OLS [@cote2006ols], UMLS [@bodenreider2004umls], the OMOP vocabularies [@hripcsak2015ohdsi], MeSH [@lipscomb2000mesh] and NCBI Taxonomy [@schoch2020taxonomy] and filtered by deterministic guards: 314,772 kept, 16,622 rejected (both retained in the CDM) and 2,837 demoted (kept in the guard files, not loaded into the CDM). [P01–P04]
- Each candidate in the CDM keeps its retrieval evidence (method, scores, query, service); 11,477 rows have no recorded service. [P07]
- No threshold-based automatic acceptance was used. 18,272 candidate rows (16,750 terms) are marked ACCEPTED because two different models (Gemma-4-E4B [@gemma2026gemma4] and DeepSeek-R1-Distill-Qwen-7B [@guo2025deepseekr1]) both judged them an exact match; this is model agreement, **not** human acceptance. [P05, P06]

### Data catalogue

**Extraction:**
- Catalogue records of six types (cohorts, sample groups, assays, datasets, data assets, findings) were extracted from each complete section with Qwen3.5-4B [@qwen35card] served by vLLM [@kwon2023vllm] (prompt `cdm-catalogue-ner-v2`).
- The prompt requires values stated explicitly in the passage, a verbatim quote of at most 300 characters as evidence, integer counts only when stated, and fixed vocabularies for coded fields (`src/scripts/vllm_termpop/catalogue_ner.py`).
- Records were then de-duplicated and linked within each paper (findings to cohorts, assays and datasets).

**Gap filling:**
- Missing fields were filled by a second pass (G1) that proposed a value and a supporting quote for each empty field.
- A value was accepted only if deterministic validators confirmed that the quote occurs in the section, that it contains the value, and that counts and vocabulary are valid.
- Of the proposals, 21,403 were accepted and 76,253 rejected by the validators. Fields where all candidate passages were checked and no value was found received the code NOT_REPORTED (46,182 in the release); contradictory values received CONFLICTING (4,586). [G1 report; catalogue 3.1.1]

**Record validity review:**
- A different model family (Gemma-4-E4B, with Llama-3.1-8B as tie-breaker) classified each record.
- 2,586 records were removed: methods text 1,264, cited other studies 945, invalid 127, table or figure text 103, wrong entity type 71, empty 49, reagent or file 27.
- Removed records are retained with their reason in a provenance file. [G3 report; `provenance/_removed.jsonl`]

**Final catalogue:** the release contains 52,400 records from all 453 papers:

| Type | Records |
|---|---:|
| findings | 24,272 |
| assays | 8,545 |
| sample groups | 7,530 |
| cohorts | 7,085 |
| datasets | 2,976 |
| data assets | 1,992 |

**Quotation matching** (catalogue 3.1.1 in CDM 3.0.3):
- 88.2% of records' quotes occur verbatim in their section: 15.1% exact at the stored offsets, 58.0% differing only in whitespace, 5.9% relocated, 9.3% after Unicode or punctuation normalisation.
- 8.0% align approximately and 3.8% could not be located or have no quote. [K08–K10]
- Quotation matching does not establish that a quote supports its value; that is assessed only computationally (see Computational validation); no human validation was performed. [audit C.quote_anchor_status]

### Common data model

**Structure:**
- The CDM is a relational model of ten modules (M1 source documents through M10 catalogue and releases) and 33 entities, specified before implementation (`src/template/cdm/`).
- Release 3.0.3 is a single SQLite database: 44 tables, 866 columns.
- 27 entities are implemented as tables, 5 as columns of other tables (paragraph, sentence, model run, mention evidence, definition evidence), and the human-review entity is empty by design. Only human reviewers may set an accepted or rejected status, and no model judgement is stored as one.

**Provenance (template §5):**
- **Runs:** every derived row names an extraction run that resolves in the run registry (0 unresolved). Of the 45 registered runs, 38 are verified from job logs, code with input-file hashes or run events; 3 are recorded only in the data; 4 are carried from 3.0.2 without independent verification. [X03, X04, X06]
- **Location:** rows carry their section and character offsets where these exist. The exceptions are 142 datasets derived from BioProject metadata (no section), 56 mentions without offsets, and catalogue records whose quote could not be located (3.8%). [K10, K11, M09]
- **Text version:** offset-bearing rows carry the SHA-256 of the section text their offsets refer to.

[CDM 3.0.3 `extraction_run`, `cdm_change_log`; `MISSING_PROVENANCE_RECOVERY_MATRIX.csv`]

**Versioning:**
- Releases are immutable, with a SHA-256 manifest.
- Release 3.0.3 was derived from 3.0.2 by additive changes only. Each of its 79 changes is logged with its reverse operation.
- We verified that every 3.0.2 column is content-identical in 3.0.3, and that the reverse script restores 3.0.2 exactly. [`VERIFICATION_303.json`]

### Quality control

**Automated checks run on the final release:**
- the release QA suite: PASS;
- regression tests for four defects found and fixed during development: lost mentions, mapping verdicts attached to the wrong term, missing term links, shifted offsets. All pass;
- 121 schema, key, value, relationship and provenance tests: 118 pass, 2 fail (an undocumented identifier pattern; mixed integer/text count columns) and 1 is conditional (two finding extractions share one table). [X07]

All links between catalogue records resolve to records of the same paper.

**Model-based assessments:** these were used during development and are reported as such, not as accuracy. A full-census judgement by Gemma-4-E4B rated 92.2% of decided records as supported by their evidence passage. We do not report it as an accuracy estimate.

### Computational validation (no human annotation)

**No human annotation was performed.** Accuracy is therefore not reported. In its place, the release was assessed computationally, by methods other than the extraction models, each reported separately and never combined into one score. None of these assessments establishes scientific accuracy or completeness:

1. **Exhaustive structural checks** of every record (keys, links, vocabularies, offsets, provenance, reversible migration).
2. **Deterministic evidence checks:** for every populated catalogue value, whether the value (or the stated count) occurs in its evidence passage.
3. **Model-based evidence assessment:** every catalogue record with an assessable value (52,397) was judged separately by two model families that did not extract catalogue values: Mistral-7B, which played no part in building the catalogue, and Llama-3.1-8B, which was the second model in the G3 verify-and-repair stage and is therefore not independent of it. Each judge saw only the source passage, the field names with their extraction rules and the values, never earlier verdicts.
   - **Literal support:** 70.5% of text values and 75.4% of counts occur in their evidence [E01, E02].
   - **Judged unsupported:** of validly labelled text values, Llama judged 2.9% and Mistral 6.6% unsupported [J01, J02]. Mistral followed the label rubric for 55.4% of values [J03].
   - **Gap-filled values:** they were judged unsupported far more often than original extractions (Mistral: 19.1% vs 5.6%) [J07, J08].
   - **Agreement:** the two models agreed on 85.0% of jointly labelled values (Cohen's κ [@cohen1960kappa] between models 0.28) [J04, J05]. Both failed 2,023 values, which are listed for curation [J06].
   - These are model judgements, not accuracy, and the judges do not test whether a quote is genuine; only offset anchoring does.
4. **External-reference concordance:** terms and triple entities resolved in NCBI Taxonomy [@schoch2020taxonomy], NCBI Gene [@brown2015gene], CTD/MeSH [@davis2026ctd; @lipscomb2000mesh], Mondo [@vasilevsky2022mondo] and HPO [@gargano2024hpo] (reference files downloaded 2026-11-02); triple pairs checked against CTD [@davis2026ctd] and Disbiome [@janssens2018disbiome]. Absence from a reference is reported as unsupported, not as wrong.
5. **Cross-method agreement on selected objective metadata fields:** a deterministic regular-expression extractor, independent of all models, recovered project accessions, sequencing platforms and 16S regions from the text of all 453 papers. The catalogue contains 88.7%, 89.2% and 72.1% of the facts it found [V01–V03]. The extractor's own coverage is limited: it finds only explicitly patterned statements and was not itself validated. This is therefore agreement on three fields, not recall, and it says nothing about the completeness or correctness of other catalogue fields.
6. **Usability:** eight research questions were run against the CDM and compared with paper sets found independently by keyword rules over the text.

### NER benchmark

**Public test sets:**
- 21 systems were compared under one protocol, fixed before scoring, on the official test splits of BC5CDR [@li2016bc5cdr] (500 abstracts, 9,809 entities) and BioRED [@luo2022biored] (100 abstracts, 3,535 entities).
- Systems:
  - **Trained NER:** HunFlair2 [@sanger2024hunflair2; @akbik2019flair]; scispaCy models [@neumann2019scispacy] trained on BC5CDR, CRAFT [@cohen2017craft], JNLPBA [@kim2004jnlpba] and BioNLP13CG [@pyysalo2015bionlp13]; BioBERT-based [@lee2019biobert] and SciBERT-based [@beltagy2019scibert] taggers.
  - **Zero-shot NER:** GLiNER [@zaratiana2024gliner], GLiNER2 [@zaratiana2025gliner2] and GLiNER-BioMed [@yazdani2026glinerbiomed].
  - **Reference annotations:** PubTator3 [@wei2024pubtator3].
  - **LLMs:** Qwen3.5-4B [@qwen35card], Gemma-4-E4B [@gemma2026gemma4], Llama-3.1-8B-Instruct [@grattafiori2024llama3], Mistral-7B-Instruct-v0.3 [@jiang2023mistral], Phi-3.5-mini-instruct [@abdin2024phi3] and DeepSeek-R1-Distill-Qwen-7B [@guo2025deepseekr1], served with vLLM [@kwon2023vllm], four of them AWQ-quantised [@lin2023awq].
  - Exact checkpoints are listed in the benchmark metadata.
- The systems: 14 NER tools, the PubTator3 precomputed annotations as a reference, and 6 open LLMs, each zero-shot and three-shot (27 configurations).
- Thresholds were tuned on development splits only, few-shot examples came from training splits, and models trained on a test corpus are flagged.
- 95% confidence intervals were obtained by document bootstrap, and differences from the best system by paired bootstrap [@efron1993bootstrap].

**Corpus evaluation:** the same systems were run over the 453-paper corpus and assessed without gold labels:
- by grounding of predicted strings in reference vocabularies (NCBI Gene, CTD/MeSH, Mondo, HPO, NCBI Taxonomy);
- by support of co-occurring entity pairs in curated knowledge graphs (CTD, Disbiome).

These measures are precision proxies, not accuracy. All 26 configurations completed on all 453 papers [H03]. Public F1 predicted corpus grounding for diseases (Spearman ρ 0.75) but not for organisms (ρ 0.02) [H04, H05].

---

## Resource description (Data Records)

| Component | Content | Size |
|---|---|---|
| Corpus metadata | 453 papers, 447 publications, 4,006 sections with hashes | `pipelines/corpus_v2/data` |
| Terminology 1.0.1 | 2.5 M mentions, 165,991 canonical terms, mappings, definitions | `releases/terminology/1.0.1` |
| Data catalogue 3.1.1 | 52,400 evidence-quoted records in six tables, removed-record provenance | `releases/data_catalogue_v3/3.1.1` |
| CDM 3.0.3 | 44 tables integrating all of the above, plus 156,330 linked compendium samples and the run registry | `releases/cdm_v3/3.0.3` |
| Documentation | data dictionary (866 columns), vocabulary reference, change reports, validation reports | in each release |

**Limitations the paper must state:**
- No human annotation was performed; factual accuracy and completeness are not established.
- No independent expert has yet reviewed the CDM design. Structural tests (118 / 121 pass) and interoperability checks do not establish semantic coherence or readiness for adoption.
- 55% of canonical terms carry only the generic type ENTITY.
- 23% of terms have a taxonomy category.
- Only 18,272 mapping candidates (16,750 terms) were accepted, by agreement of two models; none by humans. Mapping accuracy is not established.
- 69% of relation triples use the catch-all relation.
- Catalogue and corpus-stage findings coexist in one table and are not reconciled.

**Availability:** `[PENDING: rights review; redacted public build; DOI]`. Every paper's recorded licence has been assessed against a proposed release policy; this is readiness, not legal clearance, and no redistribution right has yet been confirmed. Under the proposed policy, and subject to the outstanding legal/library review of 179 papers, text and quotations would be redistributed for 274 papers under CC BY or CC0, with 15 NC-licensed papers in a separate layer; for the other 164 papers, only offsets and hashes would be released.
