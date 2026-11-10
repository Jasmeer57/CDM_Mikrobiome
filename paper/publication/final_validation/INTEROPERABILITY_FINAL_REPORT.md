# Interoperability final report — CDM 3.0.3

| Test | Result | Evidence |
|---|---|---|
| SQLite integrity (`PRAGMA quick_check`) | PASS | `CDM_VALIDATION/_interoperability_tests.json` |
| Opens in standard SQLite (3.34 and 3.45 tested) and DuckDB-compatible types | PASS | build and verification runs |
| CSV export round-trip (rows and columns preserved), all tables except the two largest | PASS | `_interoperability_tests.json` |
| Large text fields (section text up to 242,876 characters) exceed the default CSV reader limit | CONDITIONAL: documented | `VOCABULARY_REFERENCE.md` |
| JSON encoded inside text columns (74 columns, 19 tables) | CONDITIONAL: documented | `VOCABULARY_REFERENCE.md` |
| Primary keys enforced (unique indexes on all implemented keys) | PASS | 3.0.3 R6 |
| Foreign keys declared | FAIL: none; links are resolvable but not machine-declared | P1 |
| Data dictionary covers every column | PASS for coverage (866 / 866); **644 columns lack a stated definition** (NEEDS_EXPERT_REVIEW) | `CDM_COLUMN_DICTIONARY.csv` |
| Controlled vocabularies documented | PASS | `VOCABULARY_REFERENCE.md` |
| Example queries | 8, with SQL | `RESEARCH_QUERY_VALIDATION.csv` |
| Standards alignment (OMOP posture, MIxS) | NOT EVALUATED: for the expert | — |
| Reversible versioning with a change log | PASS | `cdm_change_log`, `REVERT_303.sql` |

## Decision

**Interoperability: CONDITIONAL PASS.**

**Adoption requirements for another group:**
1. Parse the JSON columns and the `;`-separated links.
2. Filter `claim_source`.
3. Raise CSV field limits.
4. Use the data dictionary. A third of its definitions still need the expert.
