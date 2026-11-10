# Evidence-linked study metadata and common data model for the literature behind a human gut microbiome compendium

Public data release, version 1.1 (candidate, 2026-11-05). Same content as version 1.0, with stricter removal of withheld wording (see *Text and licences*).

This release covers the **453 publications** (447 distinct) behind the BioProjects of the Human Microbiome Compendium (Abdill et al., *Cell* 2025, doi:10.1016/j.cell.2024.12.017). Those projects contain 156,330 of the compendium's 168,464 samples. The release contains four integrated parts:

- **Corpus:** 4,006 sections, each with a SHA-256 hash of its text.
- **Catalogue:** 52,400 evidence-linked records describing cohorts, sample groups, assays, datasets, data assets and findings.
- **Terminology:** 2.5 million entity mentions from NER models, LLMs and a MeSH gazetteer, grouped into 162,409 canonical terms with candidate vocabulary mappings.
- **Triples:** 25,788 relation triples with sentence-level evidence.

All four are integrated in one SQLite common data model (CDM 3.0.3) and are also exported as CSV.

**No human annotation was performed.** Values were extracted by NER models and language models and assessed computationally (`validation/TECHNICAL_VALIDATION.md`). The accuracy, recall and completeness of the extracted content are **not** established. Every value links to its paper, section and character offsets, so it can be checked against the source.

## Contents

| Path | Content |
|---|---|
| `cdm/microbiome_cdm_v3.0.3_public.db.gz` | The complete CDM as a SQLite database; gunzip before use. It opens in SQLite 3.34 or later and in DuckDB, and has 46 tables (see below). |
| `cdm/CDM_COLUMN_DICTIONARY.csv` | Every table and column: type, keys, null share, values, source stage, and a definition where one is stated |
| `cdm/VOCABULARY_REFERENCE.md` | All coded values |
| `catalogue/*.csv` | Catalogue tables: papers, cohorts, samples (sample groups), assays, datasets, data_assets, findings |
| `terminology/canonical_terms.csv.gz` | 162,409 canonical terms, with type, contributing models and paper counts |
| `terminology/term_concept_mappings.csv.gz` | 331,394 candidate vocabulary mappings (NCBI Taxonomy, MeSH, OMOP, BioPortal, OLS, UMLS), with scores, guard verdict and disposition |
| `terminology/term_definitions.csv.gz` | 6,773 definitions located in the papers, with character offsets |
| `terminology/ontology_registry.json`, `terminology_taxonomy.json` | Vocabulary sources and the term taxonomy |
| `triples/triples.csv.gz` | 25,788 canonical relation triples: subject, relation, object, types and supporting paper counts |
| `triples/triple_evidence.csv.gz` | 34,416 triple mentions: paper, section, character offsets and sentence (where the licence allows) |
| `corpus/sections.jsonl.gz` | 4,006 sections: identifiers, names, types, sizes, SHA-256 of the text, and the text itself where the licence allows |
| `corpus/markdown/` | One markdown file per paper, for the 274 papers whose licence allows it |
| `rights/PAPER_LICENCES.csv` | For each paper: DOI, recorded licence, and whether its text is included |
| `validation/` | `TECHNICAL_VALIDATION.md` and the NER benchmark tables |
| `RELEASE_REDACTION_LOG.csv`, `VERIFICATION_RIGHTS_SCAN.json` | What was withheld, and the scan showing that no withheld text remains |
| `MANIFEST.sha256` | Checksums of every file |

**Main database tables:**

| Area | Tables |
|---|---|
| Corpus | `paper`, `section` |
| Terminology | `term_mention`, `canonical_term`, `term_concept_map`, `term_definition` |
| Catalogue | `cohort`, `sample`, `assay`, `dataset`, `data_asset`, `claim` (findings) |
| Triples | `relation`, `relation_evidence` |
| Provenance | `extraction_run` (run registry) |
| Release | `release_rights`, `release_redaction` |

`claim` holds the catalogue findings (`claim_source = 'catalogue_v3_1'`) together with findings from an earlier corpus stage.

**Terms by source.** In `term_mention`, the columns `extraction_run_id` and `extraction_model` identify where each mention came from:

| Source | `extraction_run_id` | Models |
|---|---|---|
| NER ensemble | `cpu_ensemble_v1` | scispaCy lg / craft / bc5cdr / jnlpba, GLiNER medium / biomed, BioBERT-diseases |
| LLM | `qwen35_vllm_body_v1` | Qwen3.5-4B via vLLM |
| LLM | `qwen_ollama_cell7c_v1` | qwen3.5:4b via Ollama |
| Dictionary | `mesh_gazetteer_2026` | MeSH gazetteer |

For example: `SELECT * FROM term_mention WHERE extraction_run_id = 'qwen35_vllm_body_v1';`

## Text and licences

Paper text and verbatim quotations are included **only for the 274 papers published under CC BY or CC0**. Each record carries the paper's DOI for attribution.

For the other **179 papers** (135 with no licence found; 29 CC BY-NC-ND, 12 CC BY-NC, 3 CC BY-NC-SA), the following are withheld:
- section text, abstracts, evidence quotations, supporting sentences and definition passages;
- any other value that reproduces a passage of the paper's wording of 40 letters or digits or more, compared after
  removing spaces, punctuation and case (so copies that differ only in hyphenation, punctuation or line breaks are also
  caught).

Identifiers, character offsets, text hashes and short extracted values remain.

**Vocabulary labels.** Concept identifiers are shipped for every vocabulary. Concept labels (names) are shipped only
for vocabularies on `rights/VOCABULARY_LABEL_ALLOWLIST.csv` (MeSH, NCI Thesaurus, NCBI Taxonomy, ChEBI, GO, MONDO, PR, DOID),
pending confirmation by the rights review. Labels of UMLS, SNOMED CT, MedDRA, OMIM, LOINC, Read codes, RxNorm, NDDF,
HPO and other vocabularies are left empty; resolve the identifiers with your own licensed copy. `rights/restore_vocab_labels.py` fills the empty labels
into a copy of the database from your own UMLS `MRCONSO.RRF` (UMLS CUIs and source-vocabulary codes such as SNOMED CT,
MedDRA or LOINC) and/or an OMOP `CONCEPT.csv` from Athena:

```
python rights/restore_vocab_labels.py --db microbiome_cdm_v3.0.3_public.db --out restored.db --mrconso MRCONSO.RRF
``` Anyone with access to a paper can therefore locate and verify every value.

`RELEASE_REDACTION_LOG.csv` logs every redaction. An independent scan (`VERIFICATION_RIGHTS_SCAN.json`) checked every string in every file against all 40-letter/digit passages of the withheld papers (same normalisation)
and found no remaining passage. A second, independent check (`VERIFICATION_LEAK_REGRESSION.json`) looks for long CDM
strings that occur only in withheld papers. Wording that an included CC BY paper shares with a withheld one is allowed.

## Licence

**[AUTHORS TO CONFIRM BEFORE UPLOAD]** Proposed licence for the data in this release: CC BY 4.0. Text from the 274 included papers remains under each paper's own licence (CC BY or CC0), with attribution via the DOI.

## Integrity and provenance

To check every file against its recorded checksum:

```
sha256sum -c MANIFEST.sha256
```

The release is derived from the project's frozen releases, which were not modified:

| Source release | Manifest digest |
|---|---|
| CDM 3.0.3 | `9e71d509…` |
| Data catalogue 3.1.1 | `671b672b…` |
| Terminology 1.0.1 | `2ddc5706…` |
| Corpus 2.2.0 | `ce4db5a5…` |

The terminology files are exported from the CDM. The CDM is the reviewed state: terminology 1.0.1 had 165,991 terms, and a review removed 3,582 of them.

Build steps, run from the code repository:
1. `src/scripts/release/build_zenodo_frozen.py`
2. `src/scripts/release/finalize_zenodo_frozen.py`
3. `src/scripts/release/verify_zenodo_frozen.py`
4. `src/scripts/release/finalize_zenodo_frozen.py --seal`

## Citation

Kalra JS, Hofmann-Apitius M, Simon M-C. *Evidence-linked study metadata and common data model for the literature behind a human gut microbiome compendium* (dataset, version 1.0). Zenodo. DOI: **[add after deposit]**. Article: **[add after acceptance]**.

Code: https://github.com/SCAI-BIO/Microbiome-CDM

## Known limitations

- **No human annotation.** Accuracy and completeness are not established.
- **Generic term types.** 55% of canonical terms have only the generic type ENTITY, and most of these match no reference vocabulary.
- **Generic relations.** 69% of triples use a generic relation. About 95% fall in pair types that no curated knowledge graph covers.
- **Model-only mapping acceptance.** 18,272 mappings were accepted by agreement of two models, none by a person.
- **Sparse disease and intervention metadata.** Questions defined by disease or intervention therefore retrieve only part of the relevant papers.
- **Undefined columns.** 644 of 866 columns have no stated definition in the dictionary.

Details are in `validation/TECHNICAL_VALIDATION.md`.
