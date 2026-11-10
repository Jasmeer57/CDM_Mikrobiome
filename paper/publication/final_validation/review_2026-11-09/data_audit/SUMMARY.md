# Data audit — final summary (passes D0–D10)

Date closed: 2026-11-09. Audit of pipeline output artifacts, strictly read-only:
**217 check rows** (header excluded) in `DATA_AUDIT.csv` (8 columns, 0 malformed).

## Tally

| pass | scope | rows | PASS | DISCREPANCY |
|---|---|---:|---:|---:|
| D0 | bundle inventory & checksums | 12 | 12 | 0 |
| D1 | 3.0.3 DB row counts & integrity | 26 | 26 | 0 |
| D2 | schema, keys, cross-refs | 15 | 13 | 2 |
| D3 | mentions, entities, claim/relation offsets | 15 | 15 | 0 |
| D4 | catalogue CSV state (52,400 family) | 48 | 48 | 0 |
| D5 | findings, triples, evidence anchors | 32 | 32 | 0 |
| D6 | terminology 1.0.1 | 16 | 16 | 0 |
| D7 | data_catalogue_v3 3.1.1 | 18 | 18 | 0 |
| D8 | provenance & runs (extraction_run, change log) | 12 | 12 | 0 |
| D9 | version isolation (444/452/453 universes) | 10 | 10 | 0 |
| D10 | trust flags & transparency markers | 13 | 12 | 1 |
| **total** | | **217** | **214** | **3** |

## The 3 discrepancies (all documented/characterized; none require data repair)

1. **L-1 (D2)** — `processing_lineage` carries 2 dangling child refs whose ids are
   stage labels ("gap G1"/"gap G9"); re-confirmed benign in D8 (gap structure is
   the release-suite lineage convention).
2. **L-2 (D2)** — `term_definition.definition_id`/mention-id non-uniqueness;
   documented in-bundle via `identifier_crosswalk` (quarantine resolved).
3. **D3-line-50 "129" (D10)** — a number in **my own D3 report prose**
   ("129 UNANCHORED+FUZZY+NORMALISED rows verified=1"), not in the frozen data.
   Not reproducible under any predicate; exact re-measurement gives 3,669
   (55+1,496+2,118). The same line's verified=0 decomposition (746) ties exactly.
   The frozen DB is internally consistent; the error is report-level only.

## Frozen facts consumed unchanged (never patched)

* G2 off-by-one Δ1 in the terminology manifest (expected, must-not-patch).
* T5b calibration sample quarantined (`calibration_v0_pre_fix/`); redraw
  mandatory before use. Thresholds `NOT_CALIBRATED`; `auto_accept_eligible`
  38,334 / `auto_accepted` 0 — fail-closed behavior verified in-bundle (D10).
* All-UNVERIFIED `review_status` 52,400 + stage52 `pending` 21,395 — the honesty
  ledger is complete and consistent end-to-end.

## Key verified ties (selected)

* 2,505,684 mentions; 45,667 claims (24,272 catalogue + 21,395 stage52 = findings.jsonl);
  32,713 canonical triples (25,788 live + 6,925 guard-demoted); 34,416 relation_evidence.
* 52,400 catalogue family total by two independent routes (DB census == jsonl
  entity_type census).
* 3.0.3 `derived_from` sha256 == 3.0.2 on-disk DB; `promoted_at` ties PROMOTION.txt
  to the second; REVERT_303.sql parses clean (56 statements); MANIFEST.sha256 0
  failures; extraction_run 45 rows all with provenance (28 loaded + 17 R1 inserts).
* Version isolation: 3.0.3 (453) / frozen_output 03 (453, v2-era) / working
  `_multi_ner_runs` (444 — manuscript build) are distinct universes; manuscript's
  34,818 entities are 444-build numbers, never conflated with 37,907 (HMCV2 2.1.0)
  or 113,517 (444 working DB union).
* Every documentation pointer re-checked in-DB: SENTENCE_CLIPPED 358,150;
  UNANCHORED 560 / FUZZY 1,670 / NORMALISED 2,139 / NO_EVIDENCE 46; re-anchor
  32,192/2,224; all tie.

## Rules honored throughout

No paper text read (offsets validated against stored section lengths only);
frozen DBs opened strictly `mode=ro&immutable=1` + `PRAGMA query_only=ON`; no
network; all writes confined to this directory (`_work/` scratch); README/
BUNDLE_INFO/PROVENANCE never treated as evidence; exact observed values and
failing commands recorded; every row re-parse-validated after append.

**Audit verdict: the frozen 3.0.3 release and its companion bundles are
internally consistent, fully provenance-stamped, and honestly flagged. The only
repairs owed are report-side (D3 line 50's "129"), corrected in the D10 record.**
