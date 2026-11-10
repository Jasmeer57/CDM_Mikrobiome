# Terminology crosswalk (L1 → L2, L3 → L2)

Status: **published for review**. No row in any inventory is human-verified.
This document describes how three *different* term inventories relate. It does
not assert that any term, type, or mapping is correct.

- Terminology build: **28619916**
- Corpus release: **2.2.0**
- Generator: `scripts/build_terminology_crosswalk.py` (read-only on all inputs)
- Outputs: `docs/crosswalk/` (`dedup_to_canonical.csv`, `inventory_to_canonical.csv`,
  `_collisions.json`, `_summary.json`, `_sources.json`)

## 1. The three inventories

| Layer | File | Rows | What it is | What it is not |
|---|---|---:|---|---|
| **L1** | `data_catalogue/terminology/terminology_dedup.csv` | 166,012 | NER-derived deduplicated term/type table (CPU ensemble + Qwen) | not a controlled vocabulary |
| **L2** | `results/terminology_v1/canonical_terms.jsonl` | 165,991 | Canonical term registry, `(term_norm, cdm_type)` identity | not a verified ontology |
| **L3** | `corpus_v2/releases/2.2.0/terminology_inventory.csv` | 39,694 | Qwen extraction over corpus 2.2.0 sections, taxonomy-labelled | not CDM-typed, not deduplicated against L1/L2 |

**They are three different populations and their counts must never be summed.**
L2 is built *from* L1; L3 is built from a different extraction run over a
different text state. `39,694 + 166,012` is a meaningless number.

L2 detail: 165,991 rows, 165,905 distinct `term_norm`, 81 norms carrying more
than one `cdm_type`. A norm with two types therefore yields two crosswalk rows —
one per actual term/type relationship.

## 2. Identity and matching rules

- **L2 identity**: `(term_norm, cdm_type)`.
- **L1 identity**: `(term_norm, cdm_type)`.
- **L3 key**: `term_normalized` (surface only; L3 carries *taxonomy* labels, not
  CDM types).

Normalizers are imported, not re-invented:

- `sanitize` — `scripts/termpipeline/textnorm.py:50`: strip C0/C1 + DEL, collapse
  whitespace, strip. This is the pipeline's own read-time cleaner.
- `normalize_title` — `corpus_v2/scripts/common.py:245`: NFKD → lowercase →
  non-`[a-z0-9 ]` → space → collapse.

### L1 → L2 (`dedup_to_canonical.csv`)

| `match_method` | Meaning |
|---|---|
| `IDENTITY` | L1 `(term_norm, cdm_type)` is an exact L2 key. |
| `SANITIZED` | Equal only after `sanitize` is applied to the L1 `term_norm`; the L1 surface carries an invisible control byte. |
| `UNMATCHED` | Neither rule matches. |

### L3 → L2 (`inventory_to_canonical.csv`)

| `match_method` | Meaning |
|---|---|
| `EXACT_TERM_NORM` | L3 `term_normalized` equals an L2 `term_norm` byte-for-byte. |
| `NORMALIZED` | Equal after `normalize_title` is applied to both sides. |
| `UNMATCHED` | No L2 row. Preserved in the CSV with empty L2 columns. |

`match_score` is `1.0` for every matched row: the two rules are exact equalities,
not similarity scores. No fuzzy matching is performed in this build.

## 3. Verified L1 → L2 counts

Recomputed from the three source files (SHA-256 in `docs/crosswalk/_sources.json`):

| Figure | Value |
|---|---:|
| L1 rows | **166,012** |
| `IDENTITY` | **165,662** |
| `SANITIZED` | **350** |
| `UNMATCHED` | **0** |
| Sanitization collisions | **19 groups / 40 rows / 21 removed** |

Every L1 row resolves to an L2 row. The 350 `SANITIZED` rows are the same 350
rows whose `term_norm` carries a C0/C1 control byte; `sanitize` recovers them.
The 21 rows "removed" are the difference between the 40 rows in collision groups
and the 19 survivors — they were collapsed upstream in L2, not deleted here; all
40 remain in `dedup_to_canonical.csv` with a `collision_group` id.

### Deviation from the build spec

The spec anticipated 165,991 `IDENTITY` + 21 `SANITIZED` and 0 `UNMATCHED`.
The actual build is **165,662 / 350 / 0**. The 350/21 split is a property of the
L1 surfaces (how many carry a control byte), not of the L2 registry: L2 reports
`deduped_after_sanitize: 21` (`results/terminology_v1/canonical_terms_summary.json`)
because only 21 of those rows had a *colliding* survivor. The remaining 329
control-byte rows were sanitized one-to-one with no collision, so their L1
`term_norm` is still the raw (un-sanitized) surface. This is reported as-is.

## 4. Verified L3 → L2 counts

| Figure | Value |
|---|---:|
| L3 rows | **39,694** |
| `EXACT_TERM_NORM` | **21,920** |
| `NORMALIZED` | **5,503** |
| Matched total | **27,423** |
| `UNMATCHED` | **12,271** |

These reproduce the plan's prior claims exactly (21,920 / 27,423 / 12,271).

## 5. Type relation (L3 taxonomy label vs L2 CDM type)

L3 carries **taxonomy** labels (`organism_taxa`, `gene_protein`, …); L2 carries
**CDM** types (`ORGANISM`, `PROTEIN`, …). The two vocabularies have **no shared
label** — verified: the intersection of the 25 distinct L3 labels and the 15 CDM
types is empty. `type_relation` is therefore recorded per emitted CSV row:

| `type_relation` | Rows | Meaning |
|---|---:|---|
| `SAME` | 0 | L3 label set equals the L2 CDM type (never observed). |
| `SUBSET` | 0 | L3 label set is a proper subset of the L2 type family (never observed). |
| `DISJOINT` | **17,661** | Matched; the vocabularies share no type. |
| `GENERIC_ONLY` | **10,209** | The matched L2 row is the generic `ENTITY` type. |
| `NONE` | **12,271** | Unmatched. |
| **Total emitted rows** | **40,141** | |

`inventory_to_canonical.csv` has 40,141 data rows: one per emitted (L3, L2)
pair, plus one row per unmatched L3 term. The 27,423 matched L3 terms emit
27,870 rows because 363 L3 terms match more than one L2 term (multi-mapped; 447
extra rows). The generator de-duplicates only on `term_id`, so no L2 row is
counted twice for the same L3 term.

`L3_TO_CDM` in the generator is a documented, deliberately incomplete
compatibility map kept for reference; it is **not** used to force a `SUBSET`
match. Where a correspondence is plausible (e.g. `organism_taxa → ORGANISM`) it
is still reported `DISJOINT`, because the two vocabularies are not the same
vocabulary.

## 6. Sanitization collisions

`docs/crosswalk/_collisions.json` lists all 19 groups. Each group is a set of L1
rows that share `(sanitize(term_norm), cdm_type)` while their raw `term_norm`
strings differ solely by an invisible C0/C1 byte. Example groups include
`cd4 t cells`, `spearman r`, `klebsiella`, and `standard deviation`.

Cross-check: `results/terminology_v1/canonical_terms_summary.json` reports
`deduped_after_sanitize: 21`, matching the 21 rows lost across these 19 groups.

## 7. What this document does not claim

- It does not claim any term is a concept, nor that any type is correct.
- It does not merge L1/L3 rows into L2 or invent a preferred type; divergent
  types are recorded, never resolved.
- It does not assert accuracy — there is no gold standard. All counts are
  agreement/structure measurements over machine-extracted data.
