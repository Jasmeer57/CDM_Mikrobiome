# Comparison with existing resources (WS-5), 2026-11-05

Facts only, for the authors to turn into a table. Every cell names its source. **to verify** = not confirmed from a primary
source in this pass; check before use. The CDM column describes CDM 3.0.3 and the licence-filtered deposit.

| Dimension | BugSigDB | Disbiome | GMrepo v2 | PubTator 3.0 | This CDM |
|---|---|---|---|---|---|
| What it is | community-curated database of differential-abundance signatures from published studies [1] | database of microbe–disease associations from published studies [2] | curated database of human gut microbiome samples and runs, with marker taxa computed per phenotype pair [3] | automated annotation of PubMed abstracts and PMC open-access full texts [4] | evidence-anchored data model built from the literature behind a gut microbiome compendium (453 BioProjects, 447 publications) |
| Unit / scale | signatures (taxa with direction) per study and contrast [1; export 2026-11-03] | "experiments" (organism, disease, outcome) [2; export] | 353 projects, 71,642 runs; 592 marker taxa for 47 phenotype pairs [3] | >1 billion entity and relation annotations over ~36 M abstracts and 6 M full texts [4] | 52,400 catalogue records, 2.5 M mentions, 162,409 terms, 25,788 triples (K01, M01, T02, R01) |
| Curation method | manual, by trained curators with review state per signature [1; export columns `Curator`, `Reviewer`, `Review state`] | manual, with a reporting-quality questionnaire per study [2] | manual curation of sample metadata; markers computed from sequencing data [3] | fully automated: AIONER entity recognition, identifier mapping, BioREx relations [4] | automated (trained and zero-shot NER, small open LLMs, gazetteer, LLM extraction) with deterministic checks; no human annotation |
| Source of facts | paper figures, tables, text and supplements | papers | sequencing data (not paper text) | paper text (abstracts, PMC OA) | paper text (sections), with BioProject metadata |
| Location of the fact in the paper | per signature: `Source` field, e.g. "Figure 4" [export] | publication link per experiment [export: `publication_id`]; finer location **to verify** | not applicable | character offsets per annotation (BioC; offsets observed via the PubTator3 API, 2026-11-05) | character offsets per mention; verbatim evidence quote per catalogue value (88.2% verbatim, K08) |
| Per-row provenance | study (PMID/DOI), curator, curation date [export] | publication [export] | project and run accessions [3] | PMID / PMCID per annotation [4] | paper, section, offsets, extraction run, model and version per row (CDM 3.0.3 run registry) |
| Direction / relations | increased / decreased in group 1 [export: `Abundance in Group 1`] | elevated / reduced [export: `qualitative_outcome`] | marker taxa per phenotype pair [3] | 12 relation types over 8 entity-type pairs [4] | findings with direction (catalogue); 25,788 relation triples with sentence evidence |
| Vocabularies | NCBI Taxonomy, UBERON, EFO [export columns] | NCBI Taxonomy, SILVA, MedDRA [2; export: `meddra_id`, `organism_ncbi_id`] | phenotypes: **to verify** (MeSH?) | species, genes, chemicals, diseases, variants, cell lines mapped to identifiers [4]; vocabularies **to verify** | NCBI Taxonomy, MONDO, HPO, MeSH, SNOMED, NCIt, OMOP and others via BioPortal / OLS / UMLS / OMOP (P01–P07) |
| OMOP mapping | no (not in export) | no (not in export) | **to verify** | **to verify** | yes, candidate mappings to OMOP concepts |
| Licence of the data | CC BY 4.0 [export header] | **to verify** | **to verify** | **to verify** (NCBI resource) | proposed CC BY 4.0; paper text only for the 274 CC BY / CC0 papers, licence-filtered (deposit README) |
| Licence handling of paper text | ships curated values, not paper text | ships curated values | no paper text | annotations of abstracts and the PMC OA subset [4] | per-paper licence screening; text and quotes withheld for 179 papers; zero-leak check in the release build (WS-1) |
| Update model | continuous community curation (wiki) [1] | **to verify** | versioned releases (v1, v2) [3] | weekly automated updates [4] | versioned, frozen releases with SHA-256 manifests |

**How the CDM relates to these resources:** it complements the curated databases rather than replacing them. It is
automated, so it covers every paper in a defined corpus with row-level provenance, but its precision is lower and
model-judged. BugSigDB is its reference standard (N01–N11).

## Sources

1. Geistlinger L, et al. (2023) BugSigDB captures patterns of differential abundance across a broad range of host-associated microbial signatures. *Nat Biotechnol* 42:790–802. doi:10.1038/s41587-023-01872-y. Export: `data/reference_kg/raw/bugsigdb/full_dump.csv` (2026-11-03; header states CC BY 4.0).
2. Janssens Y, et al. (2018) Disbiome database: linking the microbiome to disease. *BMC Microbiol* 18:50. doi:10.1186/s12866-018-1197-5. Export: `data/reference_kg/raw/disbiome_experiment.json`.
3. Dai D, et al. (2022) GMrepo v2: a curated human gut microbiome database with special focus on disease markers and cross-dataset comparison. *Nucleic Acids Res* 50:D777–D784. doi:10.1093/nar/gkab1019 (verified via Crossref, 2026-11-05; online 2021-11-12).
4. Wei C-H, et al. (2024) PubTator 3.0: an AI-powered literature resource for unlocking biomedical knowledge. *Nucleic Acids Res* 52:W540–W546. doi:10.1093/nar/gkae235.
