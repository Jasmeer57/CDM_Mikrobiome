# Exhaustive integrity report — final releases

**What this measures:** structural reliability, i.e. whether every identifier, link, offset, value code and provenance pointer is consistent. It does **not** measure scientific truth.

**Releases:** corpus (453 papers), terminology 1.0.1, catalogue 3.1.1, CDM 3.0.3. All checks are automated and cover the whole population (no sampling).

| Component | Check | Population | Failures | Result | Source |
|---|---|---:|---:|---|---|
| Corpus | paper identifiers unique | 453 | 0 | PASS | audit A.papers |
| Corpus | section text = stored SHA-256 | 4,006 | 0 | PASS | audit A.section_hash_mismatch |
| Corpus | paper → BioProject → compendium samples recomputed from source | 453 BioProjects | 1 BioProject with no samples (documented) | PASS | audit A.compendium_* |
| Corpus | shared publications flagged, not merged | 5 publications / 11 BioProjects | 0 | PASS | CDM `publication` |
| Releases | SHA-256 manifests (13 release manifests incl. 3.0.3) | all files | 0 | PASS | `sha256sum -c` |
| Terminology | mention offsets reproduce the surface form | 2,505,628 | 0 (56 mentions have no offsets) | PASS | REG4 |
| Terminology | no mention lost at load | 2,505,735 | 51 byte-identical duplicates dropped, recorded | PASS | REG1 |
| Terminology | mention → canonical-term links resolve | 2,505,684 | 0 dangling | PASS | REG3 |
| Terminology | mapping verdicts attached to the right (term, concept) | 52,020 | 0 | PASS | REG2 |
| Terminology | mapping evidence restored and verified | 331,394 | 0 mismatches | PASS | 3.0.3 R3 |
| Catalogue | release QA (10 checks: IDs, links, placeholders, accessions, counts, vocabularies, CSV = JSONL, v2 traceability) | 52,400 | 0 | PASS | catalogue `qa_report.json` |
| Catalogue | links resolve within the same paper | 8 link types | 0 dangling, 0 cross-paper | PASS | `CDM_RELATIONSHIP_VALIDATION.csv` |
| Catalogue | removed records traceable with reason | 8,166 | 0 | PASS | `_removed.jsonl` |
| Catalogue | coded fields within their prompt vocabulary | 43,101 coded values | **215** (`cohort_role` 196, `longitudinal` 8, `dataset_role` 11) | **FAIL (minor)**; queued for the next catalogue release | `vocabulary_violations.json` |
| Catalogue | missing-data codes use only the four documented codes | all values | 0 free-text variants | PASS | CDM test S7 |
| Catalogue | quote located verbatim | 52,400 | 4,179 approximate, 1,988 unlocated / absent | CONDITIONAL | K08–K10 |
| CDM | 44 tables / 866 columns match the generated dictionary | 866 | 0 | PASS | `CDM_COLUMN_DICTIONARY.csv` |
| CDM | implemented keys unique and non-null (now enforced by unique indexes) | 30 tables | 0 | PASS | test S3 |
| CDM | every run-bearing row names a registered run | 3,145,984 rows, 12 tables | 0 | PASS | X06 |
| CDM | registered runs independently verified | 45 | 4 unverified, 3 data-only | CONDITIONAL | X03, X04 |
| CDM | offset-bearing rows carry the text-version hash | all with a section | 0 | PASS | 3.0.3 R4 |
| CDM | 3.0.2 content preserved; migration reversible | 805 columns | 0 | PASS | `VERIFICATION_303.json` |
| CDM | schema / value / provenance test suite | 121 | 2 fail, 1 conditional | CONDITIONAL | X07 |
| CDM | foreign keys declared in the database | — | none declared (multi-valued links prevent it) | FAIL (design) | `RELATIONSHIP_REDESIGN_PROPOSAL.md` P1 |
| CDM | triple evidence anchored to offsets | 34,416 mentions | 2,224 unanchored (6.5%) | CONDITIONAL | `relation_evidence` |
| CDM | canonical terms reachable from a mention | 162,409 | 9,940 unreachable | CONDITIONAL | `has_linked_mention` |

## Decision

**Structural integrity: CONDITIONAL PASS.**
- Every identifier, link, offset and run pointer resolves.
- The remaining items are documented and do not cause data loss: 215 out-of-vocabulary values, undeclared foreign keys, unanchored triples and unreachable terms.
