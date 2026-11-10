# Draft: Discussion and Limitations

*Draft 0.2. Numbers trace to `../final_validation/` and `MANUSCRIPT_CLAIMS_REGISTER.csv`.*

## What the resource provides

The resource connects a large sample compendium to the literature that explains it.
- **Coverage:** for 452 of the compendium's BioProjects, accounting for 156,330 samples, a researcher can find the describing paper, its cohorts, sample groups, assays, datasets and findings.
- **Traceability:** each value comes with the passage it was taken from.

Its strongest properties are structural:
- every identifier, link and offset resolves;
- every row names the run that produced it;
- the text version behind every offset is fixed by a hash;
- releases are immutable and can be reverted.

Its weakest properties are semantic, and are reported as such below.

## What was and was not established

| Property | Established by | Status |
|---|---|---|
| Structural integrity | exhaustive automated checks | established, with documented exceptions |
| Evidence traceability | offset and quote anchoring | 88.2% of catalogue quotes verbatim; 90.1% of findings fully traceable to DOI, section and a verbatim quote |
| Value-in-evidence | deterministic checks; model-based assessment by two non-extractor model families | 70.5% of text values literally in evidence; 2.9% / 6.6% judged unsupported by the two models (κ 0.28 between them); gap-filled values 3–3.5× weaker. Model judgements, not accuracy |
| External concordance | NCBI Taxonomy / Gene, CTD/MeSH, Mondo, HPO, CTD, Disbiome | about 50% of organism, chemical and disease mentions resolve; 36.5% of grounded microbe–disease triples supported |
| Cross-method agreement (3 objective metadata fields) | independent rule-based extractor, itself unvalidated | 72–89% on accessions, platforms, 16S regions; not recall |
| Factual accuracy | — | **not established** (no human annotation) |
| Completeness | — | **not established**; cross-method agreement on three objective fields (72–89%) is not recall |
| Semantic validity of the CDM | independent expert review | **outstanding** |

## The terminology and triple layers are the weakest part of the resource

Their limitations are not cosmetic:
- 55% of canonical terms (89,799) carry only the generic type ENTITY, and 98% of those match no term in the reference vocabularies tested.
- Typed terms include many non-entities.
- 68.7% of the 25,788 relation triples use a generic relation.
- About 95% of triples fall in pair types that no curated knowledge graph covers, so their correctness cannot be assessed at all.

**Consequences for users:**
- Semantic queries over the terminology, such as "all papers mentioning a given pathway", are likely to be noisy and incomplete; for most types this has not been measured.
- Knowledge-graph analyses built on the triples would mostly rest on unassessed, weakly typed relations.

We therefore present these layers as traceable candidate annotations, with every mention anchored to its text, not as a curated vocabulary or knowledge graph. The catalogue and its evidence links, not the triples, are the part of the resource intended for direct reuse.

## Structure is not semantics

The CDM's structural properties are well tested:
- 118 of 121 schema, value and provenance tests pass;
- every link resolves;
- every row names its run;
- releases are reversible;
- the database opens and round-trips in standard tools.

None of this shows that the model is semantically coherent or ready for broad adoption:
- foreign keys are not declared, because many-to-many links are stored as lists;
- disease- and intervention-defined questions retrieve a quarter to two-fifths of the papers a keyword search finds;
- no independent expert has reviewed the entity definitions, relationships or cardinalities.

We make no claim of semantic validity. An external biomedical-informatics review is the next step before any such claim in a later release.

## Trained NER versus LLMs

On public gold-standard corpora, a multi-corpus trained tagger was best:
- **HunFlair2:** 77.3 exact F1 on BC5CDR, 80.6 on BioRED.
- **Best open LLM tested** (Qwen3.5-4B, three examples): 69.5 and 66.2.
- **LLMs vs zero-shot taggers:** LLMs matched or exceeded zero-shot taggers (GLiNER) on BioRED, and tied them on BC5CDR.
- **Few-shot prompting:** inconsistent. It helped Qwen and Llama on BC5CDR but hurt Gemma.
- **Cost:** LLMs were 10–100 times slower per document.

These results describe abstracts with established type schemas. They do not show which approach is better for microbiome full texts, nor for the concept types without annotated corpora (sampling, study design, data availability), which only LLMs and zero-shot models can address. On the microbiome corpus, public F1 predicted grounding in reference vocabularies only for diseases (ρ 0.75), not for organisms (ρ 0.02), the type most central to microbiome papers. No system grounded more than 41.3% of its strings of any type. Gemma came closest to the trained taggers, while several LLMs invented strings or violated the schema at scale. Benchmarks on the target corpus, not on public abstracts, should guide tool choice.

## Lessons from development

Several defects were silent: every count looked plausible, and they surfaced only through deliberately adversarial checks.
- A load step kept one row per span identifier and dropped 557,625 competing model mentions.
- Mapping verdicts were attached to the wrong term when identifiers were shared or missing.
- Offsets were shifted in 75 sections.

Each is now covered by a regression test run on every release. We report them because similar pipelines are likely to contain similar defects.

## Limitations

1. **No human annotation was performed.** Accuracy and completeness of catalogue values, terms, mappings and triples are unknown. Model-based assessments are reported as model judgements, and the judges share the general failure modes of language models.
2. **Terminology quality:**
   - 55% of canonical terms carry only the generic type ENTITY, and 98% of those resolve in no reference vocabulary.
   - Many typed terms are not entities ("patients" typed as disease, for example).
   - Only 23% of terms have a taxonomy category.
3. **Mappings:** 18,272 candidate mappings (16,750 terms) were accepted by agreement of two models; none by a person. Most candidates were never adjudicated.
4. **Triples:** 69% use a generic relation, and 95% fall in domain pairs that no curated knowledge graph covers.
5. **Catalogue gaps:**
   - Disease- and intervention-defined queries retrieve a quarter to two-fifths of the papers a keyword search finds.
   - 16S regions are missed for about a quarter of the papers that state them.
   - 215 coded values fall outside their vocabulary.
6. **Model design:**
   - Catalogue and corpus-stage findings share one table without reconciliation.
   - Many-to-many links are stored as text lists.
   - One study per paper is assumed.
   - Junction tables and reconciliation are proposed, pending expert review.
7. **Reference vocabularies:** they under-recognise abbreviations, strain designations and British spellings. Concordance figures are therefore lower bounds on what a perfect extractor would achieve.
8. **Rights:** the licence matrix covers all 453 papers, but it is a readiness assessment, not legal clearance. Under the proposed policy, text and quotations could be redistributed for at most 274 papers; 179 await legal/library review, which blocks public release.

## Reuse

`[After the expert review: what another group needs in order to adopt the CDM for its own corpus.]`
