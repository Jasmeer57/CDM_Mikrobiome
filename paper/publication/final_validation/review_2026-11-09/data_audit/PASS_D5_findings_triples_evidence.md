# PASS D5 — Findings / Triples / Evidence Anchors

Date: 2026-11-09
Target: `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (read-only, immutable URI,
`PRAGMA query_only=ON`) vs `pipelines/corpus_v2/releases/2.2.0/` (corpus_v2 2.2.0
release bundle) and `releases/data_catalogue_v3/3.1.1/` conventions.
Scratch facts: `_work/d5_dbfacts.json` (all numbers below re-derivable from it
and `checks_D5.sql`).

## Scope

Reconcile the claim/relation side of the CDM DB against the corpus_v2 2.2.0
release and manifest, with evidence-anchor integrity per D3 conventions
(offsets validated against stored section LENGTHs only; no paper text read).

Headline: **D5 is clean. 33 checks, all PASS, 0 new DISCREPANCY.** The
`relation` 25,788 / `removed_relation` 6,925 split is a provable exact
partition of the release's 32,713 canonical triples, and every derived count
in the manifest ties to the DB.

## The claim universe: two sources, disjoint, both fully tied

| source | claim rows | evidence rows | papers | locator/anchor status basis |
|---|---|---|---|---|
| `catalogue_v3_1` | 24,272 | 24,272 | — | anchor_status (D3 census: WHITESPACE 15,057 / EXACT 3,510 / NORMALISED 2,139 / FUZZY 1,670 / RELOCATED 1,290 / UNANCHORED 560 / NO_EVIDENCE 46) |
| `corpus_stage52` | 21,395 | 21,395 | 383 | evidence_locator_status (verified_exact 2,005 / verified_normalized 16,602 / unresolved_not_in_source 2,788) |

* `claim` = `claim_evidence` = 45,667 rows, 1:1 both directions (0 orphans each
  way), and `finding_id` is distinct across all 45,667 (D3 probe, re-asserted).
* **stage52 claims tie exactly to the release**: `findings.jsonl` 21,395 rows,
  21,395 distinct finding_ids, symmetric difference 0 vs DB stage52 claim
  finding_ids. Claim-type / locator-status censuses match the manifest
  (`status_summary.findings_claim_type` sum 21,395;
  `findings_evidence_locator_status` verified_normalized 16,602 /
  unresolved_not_in_source 2,788 / verified_exact 2,005).
* `claim_source × evidence_verified` cross-tab closes: catalogue_v3_1 → 23,526
  verified=1 + 746 verified=0; stage52 → evidence_verified is NULL for all
  rows (status carried in `evidence_locator_status` instead) — expected,
  convention per source, not a defect.
* `papers_without_findings` manifest 70 ⇒ 453−70 = 383 papers with findings —
  equals distinct stage52 claim papers. **`claim` 45,667 vs manifest findings
  21,395 therefore is NOT a discrepancy**: the manifest's "findings" count
  covers only the stage52 extraction, while the DB `claim` table is the union
  of two disjoint extraction sources; the stage52 half is the manifest tie,
  the catalogue_v3_1 half is the distinct data-catalogue extraction (24,272).

## Canonical-triples partition (relation vs removed_relation)

> DB `relation` (live) 25,788 + `removed_relation` 6,925 = **32,713 = manifest
> canonical_triples exactly**, and this is an exact id partition:
> 0 overlap between the two tables, `symdiff(canonical_triples.jsonl ids,
> live∪removed) = 0`.
>
> The `removed_relation` table is therefore **not** "deletions from
> canonical_triples.jsonl" — the jsonl row itself is the canonical row and
> carries `record_status='active'` for both halves (live and removed); the DB
> merely splits it into live vs LLM-guard-demoted (see below) storage.
> `removed_relation.record_status='active'` is the row's status within its own
> table's lifecycle, not a contradiction of the removal.

Per-table facts:

* `relation`: 25,788 rows / ids, `extraction_run_id=
  'stage53_triples_extract@2.1.0'`, `canonicalization_stage=
  'stage56_triples_canonicalize@2.1.0'`, `graph_version='2.1.0'` for all rows.
* `removed_relation`: 6,925 rows / ids; same canonicalization stage; every row
  carries `verdict_deepseek='NOT_SUPPORTED'` (6,925/6,925) — the demotion
  criterion is unanimous across the two-judge LLM guard (gemma_c4 splits:
  PLAUSIBLE_BUT_WEAK 6,568 / NONSENSE 286 / UNCERTAIN 71).

### Mention-count arithmetic (all exact ties)

| manifest / report quantity | value | DB tie (live + removed) |
|---|---|---|
| triple_mentions | 34,416 | `relation_evidence` rows 34,416; distinct triple_mention_id 34,416; symdiff vs `triple_mentions.jsonl` ids = 0 |
| canonical_triples groups: unique / within-paper / cross-paper | 31,473 / 931 / 309 | duplicate_validation_status live 24,806/738/244 + removed 6,667/193/65 = 31,473/931/309 |
| cross_paper_evidence | 309 | live cp-dup 244 + removed cp-dup 65 = 309; symdiff vs `cross_paper_evidence.jsonl` ids = 0 |
| conflict triples | 326 | live 247 + removed 79 = 326 |
| triple_mentions_evidence_resolved / unresolved | 32,206 / 2,210 | SUM(evidence_verified_count) 25,414+6,792 = 32,206; SUM(evidence_unresolved_count) 1,716+494 = 2,210 |
| canonical_evidence_unresolved (≥1 unresolved mention) | 2,153 | live 1,673 + removed 480 = 2,153 |
| all_mentions_verified triples | 30,560 | live (unresolved=0 ∧ verified=mention_count) 24,115 + removed 6,445 = 30,560 |
| entities | 37,907 | distinct subject/object entity ids across live+removed = 37,907 |

Per-triple `mention_count` equals the number of `relation_evidence` rows for
that triple under its own `relation_table` value, for every one of the 32,713
triples (match 25,788/6,925, mismatch 0). `relation_evidence.relation_table`
splits exactly as relation 27,130 / removed_relation 7,286 = SUM(mention_count)
per table.

### Full-row row-comparison regime

A field-by-field compare of `canonical_triples.jsonl` (all 46 shared scalar /
id / enum fields incl. lists normalized as JSON) against DB rows (live +
removed rows keyed by canonical_triple_id) **after boolean coercion**
(jsonl booleans vs DB 0/1): 32,713 rows checked, **0 mismatches**.
> Comparator artifact: a naive string compare reported 65,426 "mismatches"
> (32,713 × 2 boolean fields, `False`/`0`); coercing jsonl `true/false` to
> int collapses this to zero. Recorded so nobody re-chases it.

### Evidence anchor integrity (D3 conventions, no text read)

`relation_evidence` (34,416 rows, extraction_run
`stage53_triples_extract@2.1.0`):

* Anchor census (re-anchor basis): WHITESPACE 24,702 / EXACT 5,375 /
  UNANCHORED 2,224 / NORMALISED 2,115. Re-anchor total
  (non-UNANCHORED) = 32,192.
* Cross-tab with release locator_status (per mention):
  * `verified_exact` 30,077 → EXACT 5,375 + WHITESPACE 24,702 (all re-anchored)
  * `verified_normalized` 2,129 → NORMALISED 2,115 + **UNANCHORED 14**
  * `unresolved_not_in_source` 2,210 → UNANCHORED 2,210
* **Δ14 explained**: the DB's anchor_status is a post-hoc re-anchor of stored
  evidence text; 14 of the 2,129 `verified_normalized` mentions fail DB
  re-anchor. DB UNANCHORED total 2,224 = 2,210 locator-unresolved + 14
  locator-resolved-but-re-anchor-failed. The manifest's 32,206/2,210 split uses
  the release's own locator status; the DB census 32,192/2,224 uses the stricter
  re-anchor basis. Both are internally consistent; **no discrepancy** — the
  difference is basis, not contradiction.
* Offsets: `char_start IS NULL` exactly on the 2,224 UNANCHORED rows (746 of
  the catalogue evidence rows likewise, matching their UNANCHORED +
  NO_EVIDENCE count); 0 inverted, 0 out-of-bounds vs
  `section.character_count` (join `section_record_id`, 100% match), 0 orphan
  paper/section refs.

`claim_evidence` `catalogue_v3_1` (24,272 rows): 0 orphans under the
(paper_id, section_id_original) join, 746 null-offset rows, 0 inverted, 0
out-of-bounds. **`corpus_stage52` offsets are NULL by design** — that source
carries location via `evidence_locator` conventions, not stored offsets; its
resolution status is `evidence_locator_status`, done in D3.

### Extraction/section coverage

* `papers_with_mentions` (report) 451 = distinct papers in relation_evidence
  = 453 − `papers_without_triple_mentions` 2. ✓
* 2,498 eligible sections − 728 zero-mention sections = 1,770 distinct
  sections carrying triple evidence. ✓
* `sections_eligible_for_extraction` 1,699 (also `llm_enriched_sections`
  1,699) is the stage-40/45 LLM-enrichment eligibility universe — a different
  concept from the per-stage eligibility of findings (1,101) and triples
  (2,498); see note N-1.

## Findings/notes for downstream passes

* **N-1 (info note, not a discrepancy)**: manifest
  `sections_eligible_for_extraction` = `llm_enriched_sections` = 1,699 does
  NOT equal the sum of the per-stage eligibility universes (findings 1,101 +
  triples 2,498). The stage reports show each stage applies its own
  eligibility filters (triples excludes empty/container/Acknowledgements/
  References: 453+239+431+385 = 1,508 excluded from 4,006 → 2,498; findings
  restricts to Results/Abstract/Discussion → 1,101), while 1,699 is the
  stage-40/45 LLM-term-enrichment eligibility. Different concepts, all
  internally consistent. Flagged so D7/D9 do not re-chase the "1,699 vs
  1,101+2,498" difference.
* **Probe hygiene**: an earlier session's probe printed long verdict strings;
  all D5 queries here were pre-checked for column cardinality/length before
  any GROUP BY (the `safe_census` guard in `checks_D5.sql`), and only short
  enum/id columns were censused. No free-text column was selected, grouped,
  or dumped.
* **Guards**: `claim`/`relation` free-text verdict columns exist (guard
  reasons, unresolved_issues 79 non-null in removed_relation) — D5 checked
  them only via enum status fields; text columns were never selected,
  GROUP'd, or printed, satisfying the "no paper text" constraint.
* **D6 preview (settled facts consumed)**: 2,837 mapping demotion, 38,334
  eligible / 0 auto_accept_ed, G2 off-by-one unpatched — these D4 findings
  carry forward unchanged.
* **D5 facts ground D10 trust flags**: DB re-anchor census (32,192/2,224),
  catalogue anchor census (D3), 746 verified=0 rows, 2,788+2,210
  locator-unresolved, all-UNVERIFIED review statuses — D10 will consume
  these as trust-flag inventory rather than re-deriving.

## Checks

See `checks_D5.sql`. All queries runnable read-only from repo root with the
immutable URI. Exact failing commands: none — every check tied.
