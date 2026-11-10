# Component M — Interoperability and Portability

**Audited object:** the shipped CDM bundle `releases/cdm_v3/3.0.3/` — **300 files / 299 manifest
entries**, the SQLite database (771,629 pages × 4,096 B ≈ 3.16 GB), the six catalogue CSVs, and the
`MANIFEST.sha256` chain — judged as an artefact another system must ingest.
**Evidence base:** `diagnostics/results/d13_interop_reproducibility.json`,
`d10_provenance_manifest.json`, `d19_cdm_schema_quality.json`, `d11_count_reconciliation.json`.
**Independence:** the manifest was re-verified by hashing every listed file; the seven headline counts
were recomputed by SQL; the CSV↔DB column diff was computed table by table; portability properties
were read from `PRAGMA` on the frozen file.

> **Scope.** This component judges whether the bundle can be *consumed elsewhere*. Correctness of
> the values is components A–G; rights posture is component N. Where a portability defect causes a
> downstream problem, it is cross-referenced rather than re-argued.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Manifest integrity | **STRONG** | **299 / 299** manifest entries verify; 0 mismatches; 0 missing; 0 unlisted artefacts except `MANIFEST.sha256` itself, which cannot hash itself and is the correct exception. `manifest_problems` is empty | verification rate **100%** (299/299); unlisted **1**, benign | The manifest covers the bundle it ships with, so it proves integrity in transit, not integrity of the build | High |
| Headline count reproduction | **STRONG** | All seven shipped counts recompute exactly: sections 4,006 / canonical terms 162,409 / term definitions 6,773 / concept mappings 331,394 / triples 25,788 / triple evidence 34,416 / catalogue records 52,400 | count reproduction **7 / 7 = 100%** | Reproducing a count proves the file matches the number, not that the number means what a reader thinks (see component F on record-vs-entity counting) | High |
| Schema portability | **CRITICAL** | `PRAGMA` on all 44 tables: **866 / 866 columns declared `NONE`**; **0 foreign keys**; `journal_mode_persisted='delete'`; page size 4,096. Every column is dynamically typed and every relationship is a text convention | typed columns **0.00%**; declared FKs **0**; portable-with-a-schema **no** | A consumer cannot generate a target DDL from this database. Recreating it elsewhere requires reading 44 tables and inferring 866 types from data — which is what this audit effectively had to do | High |
| CSV ↔ DB roundtrip | **ADEQUATE** | Row counts match exactly on all six catalogue tables (cohort 7,085 / sample 7,530 / assay 8,545 / dataset 2,976 / data_asset 1,992 / claim 24,272). Column sets **differ in both directions**: CSV-only `evidence_redacted`, `intervention_agent`, `intervention_category`; DB-only `char_start`, `char_end`, `evidence_anchor_status`, `evidence_span*`, `evidence_verified`, `extraction_model`, `extraction_run_id`, `review_status`, `section_id`, `section_text_sha256`, `study_id` | rows agree **6/6**; columns differ **both ways** on every table | "CSV and DB are the same data" is false at the column level in both directions. Neither artefact is a superset, so a reuser must decide which to trust per column — and the two carry different rights postures (component N, CQA-N-05) | High |
| Multi-value encoding | **WEAK** | **183** semicolon multi-value columns and **119** JSON-encoded columns; no schema, no documented separator escaping, no length limit. Parent lists resolve 100% (component H) but as text | non-atomic columns **183 / 866 = 21.1%**; JSON columns 119 | A target system must invent its own splitter. Two different consumers will implement two different splits, and `""` is overloaded across "none", "unknown" and "not reported" | High |
| Vocabulary interoperability | **CRITICAL** | No triple carries an ontology id (`subject_ontology_id`/`object_ontology_id` = `unresolved` on 25,788/25,788); `concept.ontology_name` NULL on **185,822 / 204,817 = 90.7%**; 5,237 `term_concept_map` rows point at a non-existent term id (documented sentinel) | triples with an ontology id **0.00%**; concepts with a named ontology **9.3%** | The bundle can be loaded but cannot be *linked*. Interoperability in the semantic sense — joining to external vocabularies — is unavailable for the graph and available for under a tenth of the concept table | High |
| Provenance portability | **ADEQUATE** | `run_metadata` 11 keys (built 2026-10-31T12:19:10, migrated 2026-11-02T02:12:44, promoted 2026-11-02T08:04:46 from `3.0.3-rc1`); **5 / 5** upstream file hashes MATCH; `cdm_change_log` 79 rows each with `revert_sql`; `REVERT_303.sql` shipped but **unexecuted** | upstream hash match **5 / 5**; reversible change rows **79 / 79** | Traceability is to *inputs*, not to a build script: no DDL, no loader, no stage graph ships with the bundle | High |
| Boundary integrity | **STRONG** | The bundle's rights rescan finds **179 withheld / 274 included** and **0 leaks**; 1,353,833 withheld passages indexed, 0 shipped; 1,453 shared-wording windows inside *included* papers are boilerplate, not leakage | withheld-paper leaks **0**; passages from withheld papers shipped **0** | This is the strongest boundary property in the bundle and it belongs to the public-release artefact, not the CDM (component N shows the CDM has no such boundary) | High |
| Documentation | **ADEQUATE** | Data dictionary covers **866 / 866 columns (100%)**, 0 undocumented; bundle README + MANIFEST + per-release provenance; three status columns documented by value but not explained | dictionary coverage **100%** | Coverage is by column name; semantics of sentinels (`unresolved`, `NO_CANDIDATES`, `pending_stage57`) are not documented, which is exactly where a consumer will trip | High |
| FAIR position | **WEAK** | Findable: yes (manifest, versioned path, counts). Accessible: yes (plain files, no auth). **Interoperable: no** (0 ontology ids, 0 types, 0 FKs). **Reusable: partial** (licence per paper, not per bundle; 179 papers unadjudicated) | F/A **yes**; I **no**; R **partial** | FAIR-I is not a judgement call here — it fails on measured properties. FAIR-R depends on rights decisions that have not been made (component N) | High |

**No averaged score is computed.**

---

## 2. What a consumer receives

### 2.1 The bundle

| Property | Value |
|---|---:|
| Files | 300 |
| Manifest entries | 299 (**+ `MANIFEST.sha256` itself**) |
| Verified | **299 / 299** |
| Mismatch / missing | 0 / 0 |
| Database size | 771,629 × 4,096 B ≈ 3.16 GB |
| Tables / views / columns | 44 / **0** / 866 |

### 2.2 The seven counts, recomputed

| Count | Claimed | Recomputed | Match |
|---|---:|---:|---|
| sections | 4,006 | 4,006 | ✔ |
| canonical terms | 162,409 | 162,409 | ✔ |
| term definitions | 6,773 | 6,773 | ✔ |
| concept mappings | 331,394 | 331,394 | ✔ |
| triples | 25,788 | 25,788 | ✔ |
| triple evidence | 34,416 | 34,416 | ✔ |
| catalogue records | 52,400 | 52,400 | ✔ |

### 2.3 The column-set divergence

For every catalogue table the CSV and the DB carry different columns:

| Direction | Columns |
|---|---|
| **CSV only** | `evidence_redacted`, `intervention_agent`, `intervention_category` |
| **DB only** | `char_start`, `char_end`, `evidence_anchor_status`, `evidence_span`, `evidence_span_end`, `evidence_span_start`, `evidence_verified`, `extraction_model`, `extraction_run_id`, `review_status`, `section_id`, `section_text_sha256`, `study_id` |

Rows agree exactly (6/6 tables); columns do not, in both directions. A consumer who takes the CSV
loses the anchor/offset layer; one who takes the DB loses the redaction flag, the intervention
fields, and the assay/data_asset/claim `field_sources` (component F, CQA-F-02).

---

## 3. Issues

### CQA-M-01 — The database cannot be ported: 866 untyped columns, 0 foreign keys
- **Severity:** **CRITICAL**
- **Type:** Confirmed design defect
- **Evidence:** `declared_types = {"NONE": 866}`; `fk_declared = 0`; `fk_total_all_tables = 0`; `journal_mode_persisted='delete'`; 0 views.
- **Affected:** 44/44 tables, 866/866 columns.
- **Scientific impact:** Any ingestion into PostgreSQL, OMOP, RDF or a dataframe-with-schema requires inferring every type from data and reconstructing every relationship from semicolon strings. That work is non-trivial and will be done differently by each consumer, so two downstream copies will not be comparable.
- **Publication impact:** The bundle can be described as "a SQLite export", not as "a relational schema" or "a portable data model". Reviewers who try to load it into a database will discover the difference.
- **Recommended action:** Ship a DDL file with column affinities, PKs, FKs and a junction table for the five parent lists (component H, CQA-H-01/02). The DB file can stay exactly as frozen.
- **Blocking:** blocks any interoperability claim and any multi-site reuse plan.

### CQA-M-02 — CSV and DB are not the same data, and the difference is not documented
- **Severity:** **HIGH**
- **Type:** Confirmed defect (documentation + divergence)
- **Evidence:** row counts identical 6/6; **CSV-only** `evidence_redacted`, `intervention_agent`, `intervention_category`; **DB-only** 13 columns incl. `evidence_verified`, `evidence_anchor_status`, `section_text_sha256`.
- **Affected:** all six catalogue tables; 52,400 rows.
- **Scientific impact:** Neither artefact is a superset. A reuser who picks one silently loses either the rights annotation or the evidence anchors. Worse, the two differ *on the redaction question*: the CSV marks 18,502 cells as licence-redacted and the DB ships their full text with no flag (component N, CQA-N-05).
- **Publication impact:** "Available as CSV and SQLite" implies equivalence. It must say which columns are in which, and which is authoritative per column.
- **Recommended action:** Publish a column-level crosswalk table in the README, and declare the CDM the primary artefact with the CSV as the rights-annotated view.
- **Blocking:** blocks a "two equivalent distribution formats" claim.

### CQA-M-03 — A fifth of the schema is untyped multi-value text
- **Severity:** **HIGH**
- **Type:** Confirmed design defect
- **Evidence:** 183 semicolon columns, 119 JSON columns; no escaping convention documented; parent lists resolve 100% but only as strings.
- **Affected:** 183 / 866 = 21.1% of columns.
- **Scientific impact:** Interoperability requires atomic values. Every consumer must write a splitter, and the split semantics (empty string vs sentinel vs absent) are not specified, so the same column can yield different cardinalities downstream.
- **Publication impact:** Any row-count a consumer computes by joining through these columns is a pair count, not a row count (component F's 437 redundant dataset rows are partly this).
- **Recommended action:** Document the separator, the escaping rule, and the meaning of `""` per column; provide a normalised view or a companion table per multi-value column.
- **Blocking:** blocks clean downstream ingestion.

### CQA-M-04 — Nothing links to an external vocabulary
- **Severity:** **CRITICAL**
- **Type:** Confirmed defect
- **Evidence:** 0 / 25,788 triples carry an ontology id; `concept.ontology_name` NULL on 185,822 / 204,817 (90.7%); `external_linking_status='pending_stage57'` on 100%; the 5,237 dangling `term_concept_map.term_id` values are a documented sentinel, not a link.
- **Affected:** the entire graph; 90.7% of the concept table.
- **Scientific impact:** "Interoperable" in the FAIR sense means a term in this bundle can be resolved to the same term elsewhere. For the graph, that is impossible: nodes are English strings compared by `string_normalization_v1_exact`. For concepts, it is possible for 9.3%.
- **Publication impact:** The manuscript cannot claim semantic interoperability or ontology alignment at the triple level. It can claim a candidate-mapping table (`term_concept_map`, 331,394 rows) that was never accepted — 0 `auto_accepted` (component D).
- **Recommended action:** State the limitation plainly; point readers to `term_concept_map` as *candidates* and to the unnamed-concept count as the ceiling.
- **Blocking:** blocks any "linked data" or "ontology-grounded" framing.

### CQA-M-05 — The change log ships a revert script that was never run
- **Severity:** **MODERATE**
- **Type:** Confirmed documentation gap
- **Evidence:** `cdm_change_log` 79 rows, each with `revert_sql`; `REVERT_303.sql` is shipped and **unexecuted**; run_metadata records a promotion from `3.0.3-rc1` on 2026-11-02T08:04:46.
- **Affected:** 79 logged changes.
- **Scientific impact:** A consumer cannot tell from the bundle whether the 79 changes are applied or pending. The presence of both a change log and an unexecuted revert script is precisely the ambiguity that a `status` column would resolve.
- **Publication impact:** Minor, but the methods section must state that 3.0.3 is the promoted build and what was migrated.
- **Recommended action:** Document the state of each change (`applied` / `reverted`) and why the revert script is shipped unused.
- **Blocking:** neither.

### CQA-M-06 — Status sentinels are undocumented, so a consumer cannot filter correctly
- **Severity:** **MODERATE**
- **Type:** Confirmed documentation defect
- **Evidence:** `external_linking_status='pending_stage57'` on 100% of triples; `review_status='UNVERIFIED'` on 100% of catalogue rows; `link_status='NO_CANDIDATES'` on 100% of datasets; `verification_status` absent from four tables. All appear in the dictionary as columns, none as constants.
- **Affected:** 52,400 catalogue rows + 25,788 triples.
- **Scientific impact:** A filter on any of these returns either everything or nothing, which reads as a broken query rather than a constant column (component F, CQA-F-08; component G, CQA-G-09).
- **Publication impact:** The data dictionary must mark these as reserved/constant.
- **Recommended action:** Add a "fixed value" column to the dictionary.
- **Blocking:** neither.

### CQA-M-07 — No build script ships with the bundle
- **Severity:** **MODERATE**
- **Type:** Confirmed reproducibility gap
- **Evidence:** 5/5 upstream hashes match and `run_metadata` pins the build timestamp, but the bundle contains no DDL, no loader and no stage graph; the stage name `stage56_triples_canonicalize@2.1.0` appears only as a value inside the data.
- **Affected:** the whole bundle.
- **Scientific impact:** The bundle can be *verified* but not *rebuilt*. A reviewer can confirm the files are the files; they cannot re-run the pipeline to see whether the result is stable.
- **Publication impact:** "Reproducible build" is not claimable; "checksummed snapshot with pinned inputs" is.
- **Recommended action:** Ship `build_cdm_v3.py` + the DDL + a stage manifest in the bundle (read-only). The code already exists in `src/scripts/vllm_termpop/`.
- **Blocking:** blocks a reproducible-build claim.

### CQA-M-08 — SQLite-only with a non-WAL journal is a concurrency limit, not just a format choice
- **Severity:** **LOW**
- **Type:** Confirmed usability constraint
- **Evidence:** `journal_mode_persisted='delete'`, page size 4,096, single file 3.16 GB, 0 views.
- **Affected:** any multi-user deployment.
- **Scientific impact:** `delete` journal mode takes an exclusive lock on write; with 2.5 M-row tables, a shared deployment will serialise. This audit ran `mode=ro` throughout, which is unaffected.
- **Publication impact:** None.
- **Recommended action:** Document `mode=ro` as the supported access pattern, as this audit did.
- **Blocking:** neither.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates:**
- **299 / 299** manifest entries verify, with a single benign unlisted file (`MANIFEST.sha256`).
- All **seven** headline counts recompute exactly.
- 5/5 upstream file hashes match; 79 change-log rows are individually reversible.
- The DB has **866 / 866** untyped columns, **0** foreign keys, **0** views, 183 semicolon and 119
  JSON columns, and `journal_mode=delete`.
- CSV and DB agree on rows **6/6** and differ in columns **both ways**, so neither is a superset.
- **0 / 25,788** triples carry an ontology id; **90.7%** of concepts have no ontology name.
- The shipped bundle's rights boundary is intact: **0** leaks from 179 withheld papers.

**Does not establish:**
- That the bundle is interoperable. FAIR-I fails on measured properties, not on opinion.
- That the CSV and DB carry the same information; they do not.
- That the build is reproducible; it is verifiable and pinned, not rebuildable.

---

## 5. Component verdict

The bundle is **verifiable and honest, and not interoperable**. Its manifest is the best in the audit
(299/299), its seven counts are exact, its upstream hashes match, and its rights boundary holds at
zero leaks. A reuser can trust that the bytes are the bytes.

What a reuser cannot do is *link* them. Zero ontology identifiers on 25,788 triples and 90.7% unnamed
concepts mean the semantic half of interoperability is absent; 866 untyped columns and zero foreign
keys mean the structural half is absent too. The CSV/DB divergence adds a third trap: the two shipped
formats are not the same data, and the difference includes the redaction flag — the one column a
rights-conscious consumer would most want and the one the database does not have.

So the component's verdict is a split: **integrity STRONG, portability CRITICAL**. The cheapest fix
with the largest effect is a DDL file and a column crosswalk — both are documentation, neither touches
the frozen bytes.
