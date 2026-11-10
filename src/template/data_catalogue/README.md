# Human Microbiome Data Catalogue Template

## Purpose
Template for cataloguing 444+ full-text papers on the human microbiome, including both external datasets linked to papers and scientific data/results reported in the papers.

## Files
- `human_microbiome_data_catalogue_template.xlsx`: workbook with linked tables, field definitions, controlled vocabularies, relationships, and a workflow checklist.
- `human_microbiome_data_catalogue_template.json`: blank structured example with one placeholder record per entity type.
- `human_microbiome_data_catalogue.schema.json`: JSON Schema (Draft 2020-12) for basic structural validation.
- `csv_templates/`: separate CSV headers for each table.

## Data model
- Papers: one row per publication.
- Datasets: one row per distinct dataset linked to a paper.
- DataAssets: one row per file/resource in a dataset.
- Cohorts: one row per cohort.
- Samples: one row per reported sample group/body site/timepoint, not necessarily one row per physical specimen.
- Assays: one row per assay/workflow.
- Findings: one row per discrete reported result.
- Workflow: staged curation checklist.

## Stable identifiers
- `HMPAPER_000001`
- `HMDATA_000001`
- `HMASSET_000001`
- `HMCOHORT_000001`
- `HMSAMPLE_000001`
- `HMASSAY_000001`
- `HMFINDING_000001`

IDs should remain stable even if titles, accessions, or classifications are corrected.

## Missing-data conventions
- Blank / JSON `null`: not yet extracted or unknown.
- `NOT_REPORTED`: the relevant paper/supplement/repository record was checked and does not report it.
- `NOT_APPLICABLE`: the field does not apply.
- `NOT_ACCESSIBLE`: the resource is known but currently inaccessible.
- `CONFLICTING`: sources disagree; retain both sources and explain in notes.
- Never use numeric zero to mean missing.

## Evidence and provenance
For critical values, record `evidence_text` and `evidence_location`, such as Methods, Data Availability, Table 2, Supplementary Table S1, repository page, or a stable URL. Record retrieval and verification dates. Distinguish claims made in a paper from information verified directly in a repository.

## Suggested workflow for 444+ papers
1. Create a canonical paper list and deduplicate using DOI, PMID/PMCID, and title checks.
2. Assign stable paper IDs and populate bibliographic metadata.
3. Screen for human microbiome relevance; document exclusions.
4. Extract all dataset mentions, accessions, URLs, and availability statements.
5. Verify repository landing pages, accession types, access conditions, and asset availability.
6. Catalogue individual data assets.
7. Extract cohorts, specimen groups, assays, methods, and scientific findings.
8. Validate foreign keys, controlled vocabularies, IDs, counts, and URLs.
9. Manually review a stratified sample of records and all high-impact fields.
10. Freeze a versioned release and preserve a changelog.

## Practical recommendations
- Start with Papers and Datasets for all papers; only populate detailed findings/assets when the paper supports them.
- Do not force a dataset record if no dataset is mentioned. Instead record the paper's data availability status and evidence in the Papers or a dedicated screening log.
- One paper may use several datasets, and one dataset may be reused by several papers. If cross-paper dataset reuse is common, consider a separate canonical dataset entity plus a linking table; this starter workbook uses `paper_id` in Datasets for simplicity.
- Do not duplicate raw files in the catalogue; store stable URLs and accessions.
- Avoid putting direct identifiers or sensitive participant-level data in the catalogue.
- Review reuse licenses and repository terms before redistributing data or full-text content.
