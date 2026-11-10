# Independent CDM expert review: package and remit

*Prepared 2026-11-02 for an external reviewer. **Status: NOT YET REVIEWED.** No reviewer has been recruited, and no part of this package has been assessed by an expert or simulated by a model.*

## 1. What we are asking for

This is a review of the **data model**, not a review of the paper and not an annotation study. Please do not judge whether the manuscript "looks good". Answer the six technical questions below, and return written findings classified as **critical, major or minor**.

**Reviewer profile:** biomedical informatics, database design or common-data-model experience (OMOP, MIxS / GSC standards or comparable). The reviewer must not have contributed to this pipeline and should declare any conflict of interest.

**Expected effort:** about 1–2 days.

## 2. The six review questions

| # | Question | Where to look |
|---|---|---|
| Q1 | **Semantics:** are the entities and relationships semantically appropriate for literature-derived microbiome study metadata? | template §M1–M10; `UPDATED_ENTITY_REGISTRY_PROPOSAL.csv`; data dictionary |
| Q2 | **Cardinality and identifiers:** are cardinalities (for example sample group → cohort, finding → cohort / assay / dataset) and identifier conventions (HM\* prefixes, `paper_id`, BioProject, `section_record_id`) defensible? | template §3–4; `RELATIONSHIP_REDESIGN_PROPOSAL.md` P1–P6 |
| Q3 | **Workflow fit:** can the model represent real microbiome research workflows (cohort → sampling → storage → extraction → sequencing → bioinformatics → finding; longitudinal and intervention designs)? | worked example (§4); catalogue tables |
| Q4 | **Provenance and evidence:** are the provenance and evidence relationships sufficient (run registry, offsets, text-version hashes, verbatim quotes, removed-record provenance, model-vs-human status)? | template §5 and §8; `extraction_run`; `VOCABULARY_REFERENCE.md` |
| Q5 | **Adoptability:** could another research group adopt the CDM for its own corpus **without** our internal pipeline? What would it need? | data dictionary; interoperability report |
| Q6 | **Limitations:** what are the most consequential design limitations, and which must be fixed before the model is described as semantically coherent? | §5 below |

## 3. Materials, in reading order

All paths are relative to the repository root. The database and documentation are frozen (`releases/cdm_v3/3.0.3/MANIFEST.sha256`).

1. `src/template/cdm/human_microbiome_cdm_template.md`: intended architecture (M1–M10), identifiers (§3), conventions (§4), provenance contract (§5), traceability test (§8).
2. `releases/cdm_v3/3.0.3/remediation/UPDATED_ENTITY_REGISTRY_PROPOSAL.csv`: 33 entities, keys, statuses, foreign keys.
3. `releases/cdm_v3/3.0.3/remediation/COMPLETE_CDM_DATA_DICTIONARY.md` and `CDM_COLUMN_DICTIONARY.csv`: 44 tables, 866 columns. **644 columns are marked NEEDS_EXPERT_REVIEW** (no stated definition).
4. `releases/cdm_v3/3.0.3/remediation/VOCABULARY_REFERENCE.md`: all coded values, including the model-vs-human status distinction.
5. `releases/cdm_v3/3.0.3/remediation/RELATIONSHIP_REDESIGN_PROPOSAL.md`: six modelling proposals (P1–P6) awaiting a decision.
6. `releases/cdm_v3/3.0.3/remediation/CHANGE_REPORT_302_vs_303.md` and `VERIFICATION_303.json`: what 3.0.3 changed, and proof that 3.0.2 content is preserved.
7. **The database:** `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (SQLite; opens in DuckDB). Use this frozen copy, not the release-candidate copy named in the older package (`releases/cdm_v3/3.0.3/remediation/EXPERT_REVIEW_PACKAGE.md`).
8. **Worked example:** `cdm_review/EXAMPLE_RECORDS_HMPAPER_000258.json` (§4).
9. **Computational validation:** `paper/publication/final_validation/MASTER_VALIDATION_REPORT.md`, `EXHAUSTIVE_INTEGRITY_REPORT.md`, `INTEROPERABILITY_FINAL_REPORT.md`, `CDM_USABILITY_REPORT.md`.

## 4. Worked example

**Paper:** HMPAPER_000258 (mSphere, doi:10.1128/mSphere.00358-19; CC BY, so quotations may be shared with attribution). The file holds one record from each table on the provenance spine:

> paper → section (with SHA-256) → cohort → sample group → assay → dataset → finding (with evidence quote, offsets, anchor status, linked IDs) → term mention → canonical term → concept mappings → extraction runs

This paper's only relation triple was removed during review. It therefore appears as `removed_relation` with its `relation_evidence`, which illustrates how removals stay traceable. The example was extracted read-only from the frozen database; long text is truncated at 300 characters.

## 5. Known limitations (stated by the authors; the reviewer should confirm, dispute or extend)

**Structural:**
- No foreign keys are declared. Many-to-many links (finding → cohort / assay / dataset) are stored as semicolon-separated lists (P1).
- One study per paper is assumed.
- Sample group (`sample`) vs specimen (`compendium_sample`) naming and granularity are unresolved (P3).
- Catalogue findings and corpus-stage findings share the `claim` table without an identity rule (P4).

**Semantic:**
- 55% of canonical terms carry only the generic type ENTITY, and 98% of those match no term in the reference vocabularies tested.
- 68.7% of relation triples use a generic relation.
- 644 columns have no stated definition.

**Validation:** structural integrity is tested (118 / 121 tests pass), but semantic coherence is untested. That gap is the reason for this review. No human annotation was performed.

## 6. CDM usability: eight research questions (computational results)

Each CDM result was compared with paper sets found by independent keyword rules over the text (`final_validation/queries/QUERY_COMPARISON.csv`). Both sides are computational.

| Query | CDM papers | Keyword papers | Keyword papers also returned by the CDM |
|---|---:|---:|---:|
| Q1 IBD studies using 16S sequencing | 35 | 82 | 26.8% |
| Q2 type 2 diabetes cohorts | 18 | 28 | 39.3% |
| Q3 *F. prausnitzii* decreased (own results) | 58 | 56 | 53.6% |
| Q4 datasets with a public accession | 442 | 378 | 97.1% |
| Q5 findings traceable to DOI, section and verbatim quote | 24,272 findings | — | 90.1% |
| Q6 probiotic intervention | 60 | 88 | 26.1% |
| Q7 stool samples stored at −80 °C | 191 | 70 | 80.0% |
| Q8 shotgun metagenomics with a linked taxon finding | 101 | 60 | 71.7% |

**Questions for the reviewer:**
- Are these the right questions for a microbiome CDM?
- Is the weak retrieval for disease and intervention questions (Q1, Q2, Q6) a modelling problem, a population problem, or both?

## 7. What the reviewer returns

### 7.1 Overall verdict (choose one)

- [ ] Semantically appropriate as is
- [ ] Appropriate with changes (list them under findings)
- [ ] Not appropriate in its current form

### 7.2 Answers to Q1–Q6

Free text, about half a page each.

### 7.3 Findings

One row per finding; a CSV is welcome.

| ID | Severity (critical / major / minor) | Question (Q1–Q6) | Entity / table / column | Finding | Evidence (query, record ID, document section) | Recommended change |
|---|---|---|---|---|---|---|
| F1 | | | | | | |

**Severity:**
- **Critical:** blocks describing the model as semantically coherent or adoptable.
- **Major:** should be fixed in the next release.
- **Minor:** documentation or naming.

### 7.4 Decisions on proposals P1–P6

For each: adopt / adopt with changes / reject, with reasons.

### 7.5 NEEDS_EXPERT_REVIEW columns

Supply definitions, or mark columns for removal. At minimum, cover the six catalogue tables plus `claim`, `relation` and `term_concept_map`.

### 7.6 Conflict-of-interest statement and reviewer details

For acknowledgement, with the reviewer's permission.

## 8. How the review will be used

- Findings are reported in the paper as an **independent expert review of the data model**, with the reviewer's consent. They are never described as validation of the extracted content.
- **Critical and major findings** are addressed in a new CDM release with a change log. 3.0.3 itself stays frozen.
- **Until the review is returned,** the manuscript makes no claim of semantic coherence or readiness for adoption.
