# Cross-method agreement on selected objective metadata fields (source-first)

**Method:** an independent extractor (`src/scripts/final_validation/source_first_coverage.py`) uses fixed regular expressions, with no language model and no catalogue output. It was run over every section of all 453 papers except References, for three fact types that can be matched without interpretation:
- **project accessions:** BioProject, SRA/ENA/DDBJ study, EGA, MG-RAST;
- **sequencing platforms:** 10 families;
- **16S rRNA variable regions.**

Its findings are compared with the catalogue (datasets, data assets, assays), paper by paper. Datasets derived from compendium BioProject metadata are excluded from the catalogue side, so only text-extracted values count.

**What this measures:** agreement between two independent methods on three narrow, unambiguous fields. It is **not recall** of the catalogue. The regex extractor's own coverage is limited: it finds only explicitly patterned statements and has not itself been validated.

| Fact type | Papers with the fact in text | Facts matched | In text, not in catalogue (potential omissions) | In catalogue, not in text | Text facts present in catalogue |
|---|---:|---:|---:|---:|---:|
| Project accessions | 345 | 582 | 74 | 34 | **88.7%** |
| Sequencing platforms | 377 | 421 | 51 | 30 | **89.2%** |
| 16S variable regions | 387 | 378 | 146 | 30 | **72.1%** |

Run summary: `source_first/coverage_summary.json`.

**Own BioProject:** the paper's own BioProject accession is stated in the text of 306 papers. The catalogue's text extraction captured it for 297 papers in total, but missed it in 20 papers where the text states it.

**Interpretation:**
- Coverage of explicitly stated data identifiers and platforms is high but incomplete: roughly 1 in 9 is missed.
- 16S regions are missed more often, about 1 in 4, likely because they appear in passing in methods text rather than as a dedicated statement.
- "In catalogue, not in text" values are mostly normalisations (e.g. platform names given generically in the text) or accessions written with spacing the regex does not match.

**Limitations:**
- Only three fact types are covered. Cohort size, disease, body site and findings are not covered by any independent extractor, so their completeness is **unknown**.
- An earlier run skipped Acknowledgements sections and under-counted accessions. It was corrected before reporting, because data-availability statements are often parsed into that section.

**Decision:** cross-method agreement on selected objective metadata fields **CONDITIONAL**: 72–89% on three fields. Scientific completeness **NOT EVALUATED**.
