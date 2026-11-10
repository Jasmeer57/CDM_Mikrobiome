# Draft: Introduction

*Draft 0.3. Citations use keys `[@key]` from `../submission_readiness/VERIFIED_REFERENCES.md`; each is checked against its claim in `../submission_readiness/REFERENCE_TO_CLAIM_MAPPING.csv`. Numbers trace to `../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv`.*

Large compendia of human microbiome sequencing data now aggregate hundreds of thousands of samples from public archives. The Human Microbiome Compendium of Abdill et al. (2025) processed 168,464 publicly available human gut 16S rRNA amplicon samples with a uniform pipeline [@abdill2025], drawn from projects deposited in the Sequence Read Archive [@leinonen2011].

Such compendia standardise what the archives record: sequencing runs, sample identifiers, and a small set of submitter-supplied metadata fields. Much of what is needed to reuse the data lives only in the publications that describe each project:
- the study design;
- who the participants were;
- how samples were collected and stored;
- which assays and analysis pipelines were used;
- what the authors found.

Sample metadata in public archives are often poorly standardised and inconsistent [@goncalves2019]. Manual curation of the accompanying literature is possible at the scale of hundreds of studies, but it has required sustained community effort [@geistlinger2023].

Text mining offers a route from publications to structured metadata. Biomedical named-entity recognition (NER) tools trained on annotated corpora are fast and well characterised on benchmark datasets [@li2016bc5cdr; @luo2022biored; @sanger2024hunflair2]. Large language models (LLMs) can be applied without task-specific training, although on most biomedical NLP benchmarks fine-tuned models still outperform them in zero- and few-shot use, and their outputs can contain hallucinations [@chen2025llmbench]. In principle, prompting also reaches concepts that no annotated corpus covers, such as sampling methods, study designs or data-availability statements.

Two gaps remain:
1. Comparisons of LLMs with fine-tuned models have used established benchmark corpora [@chen2025llmbench]; they have rarely been made on full-text microbiome literature, under one protocol with the same type definitions and no tuning on test data.
2. Extracted entities are of limited use unless they are organised in a model that preserves provenance, separates competing outputs, and links each value back to the passage that supports it.

**This resource.** We describe a literature-derived common data model (CDM) and evidence-backed data catalogue for the publications behind a 168,464-sample human microbiome compendium:
- **Corpus:** 453 papers (447 distinct publications) describing the compendium's BioProjects, whose projects contain 156,330 of the compendium's samples. They were processed into 4,006 text sections with verifiable hashes.
- **Terminology:** four independent extraction sources yield 2.5 million entity mentions, organised into a terminology of 162,409 canonical terms with candidate vocabulary mappings and definitions drawn from the papers themselves.
- **Catalogue:** 52,400 records describing cohorts, sample groups, assays, datasets, data assets and findings. Each value carries the quotation that supports it.
- **CDM:** everything is integrated in a versioned relational CDM in which every row names the run that produced it and every offset names the text version it indexes.

**Evaluation.** We assess the resource computationally, without human annotation, using methods other than the extraction models:
- exhaustive structural checks;
- deterministic evidence checks;
- concordance with external vocabularies and knowledge graphs;
- an independent rule-based extractor;
- model-based evidence assessment by two model families not used for extraction.

We report what each establishes and what remains unknown. None of these assessments establishes the scientific accuracy or completeness of the extracted content. We also benchmark 21 NER systems and LLMs under a fixed protocol, on public gold-standard corpora and on the full microbiome corpus.

**Contributions.**
1. **A literature-derived resource for a large microbiome compendium:**
   - a 453-paper corpus with hash-verified text;
   - an evidence-quoted catalogue of 52,400 study-metadata records;
   - a terminology of 162,409 canonical terms, offered as traceable candidate annotations rather than a curated vocabulary.
2. **A versioned, provenance-tracking CDM** in which:
   - every row names the run that produced it;
   - every offset names the text version it indexes;
   - every release is immutable and reversible.
3. **A protocol-fixed NER benchmark** of 21 trained taggers, zero-shot taggers and open LLMs, run both on public gold standards and on the full microbiome corpus. It shows that public scores predict corpus behaviour for diseases but not for organisms.
4. **A transparent computational validation without human annotation.** It reports structural integrity, literal evidence support, limited model-based assessment, external concordance and cross-method agreement separately, and states what remains unknown: accuracy, completeness and semantic validity. It also documents silent defects found during development.
