# CDM Migration Risks — DRAFT 0.1.0

Risks of physically materializing the CDM from the audited sources
(`cdm_source_inventory.csv`). Design phase: no migration has been run.
Each risk carries a mitigation that operates within project rules
(no production writes, no silent correction, human review as sole gate).

## R1 — Identity

| # | Risk | Evidence | Severity | Mitigation |
|---|---|---|---|---|
| 1.1 | ID re-minting / hash drift between runs | content-hash IDs are deterministic; any rerun divergence = misjoin | HIGH | V1.2 recompute check; adopt existing IDs as-is (template §3); never re-hash |
| 1.2 | Cross-walk ambiguity between catalogue sequential IDs (HM*_[0-9]{6}) and content-hash IDs | two coexisting ID families (ids.py layers) | MED | crosswalk table mapping catalogue ↔ hash IDs; PK pattern check V1.1 |
| 1.3 | canonical_terms.jsonl first-record oddity (n_papers=2092, HMPAPER_000001–5) signals pre-corpus_v2 counts in a shipped file | verified oddity, predates corpus_v2 | MED | treat as documented caveat (V5.4); no correction — flag at ingest inspection |
| 1.4 | RELATION id scheme undefined until stage 53/54 + 56 outputs exist | jobs 28607588 (PENDING), 28607924 (dependency) | HIGH (blocked) | do not populate RELATION until triple_mentions.jsonl is verified; propose hash-style ids in proposal §5.1 |
| 1.5 | PubTator3 rows keyed by BioProject filename (`PRJDB10485.txt`), not paper ids | original run layout | MED | join via papers.jsonl `bioproject`; backfill proved the join (28608086) |

## R2 — Provenance and lineage

| # | Risk | Evidence | Severity | Mitigation |
|---|---|---|---|---|
| 2.1 | Legacy paper-level `_multi_ner_runs/*` are 444-era (pre-corpus_v2, pre-453) | inventory PENDING-VERIFICATION flags | HIGH | ingest only with lineage flag + re-validation requirement; section-level zenodo_v1 rows are primary; never present legacy rows as current-coverage |
| 2.2 | Two SUPERSEDED microbiome_cdm.db lineages (c2.0.0: 9 tables/113,517 entities; llm_terms: 12 tables) could be mistaken for current truth | both inventoried | HIGH | migration-input-only flag in registry; sketch-level reconciliation: legacy rows must re-validate against sources before admission; adopt IDs, not trust |
| 2.3 | In-flight job outputs ingested as final | cv-link 28607619 RUNNING; llm-ner-body 28607825 RUNNING (7 seg errors); termpipe-v1 28608065 user-submitted PENDING | MED | PROVISIONAL rows only; promotion gated on verified manifest (V0.3); do not interfere with user jobs |
| 2.4 | Release 2.2.0 inputs incomplete | stage 53/54 (28607588) PENDING on resources → 28607924 auto-fires after | HIGH | release blocked; DATASET_RELEASE row for 2.2.0 only after verification battery |
| 2.5 | catalogue_records.jsonl: 56,985 lines vs 51,941 records (multiline JSON records) | line-count ≠ record-count verified | MED | JSON-parse record-wise (proposal §5.5); parse failures kept as CONFLICTING rows, never dropped |
| 2.6 | csv count inflation from quoted embedded newlines | naive wc -l over-counted tables by 13–37% (e.g. cohorts 11,792 vs 9,575) | MED | always count with a real CSV parser (done in inventory); raw line counts labelled as such |

## R3 — Evidence and geometry

| # | Risk | Evidence | Severity | Mitigation |
|---|---|---|---|---|
| 3.1 | Offset/locator drift — mentions index section_text_original; PubTator3 offsets 0,0 (paper/abstract geometry) | backfill + run provenance | HIGH | V3.3: geometry recorded on the run; assertions of section-level geometry for PubTator3 rows fail the build |
| 3.2 | text_version_id staleness after any re-parse | locator gate requires text at version | MED | V2.4 + V3.1; text re-parse = new version + full recheck, never in-place patch |
| 3.3 | Claim locator failures silently shipped | evidence_locator_status exists (some FAIL) | HIGH | V3.1 keeps failed locators flagged + queued; count of FAILs in release report |
| 3.4 | p-shaped effect_estimate quirk (~1,088: 849 dup + 239 sole) misread as real effect measures | findings quirk documented | MED | never corrected (V5.4); QUANTITATIVE_RESULT keeps verbatim values + quirk annotation |

## R4 — Process and safety

| # | Risk | Evidence | Severity | Mitigation |
|---|---|---|---|---|
| 4.1 | Accidental writes to production outputs (esp. `paper_claims/_multi_ner_runs/pubtator3_ner.csv`, zenodo_v1, MANIFESTs) | read-only rule for this phase | HIGH | V0.2 hash-snapshot precondition; ingests read-only; new outputs go to new dirs (28608086 pattern) |
| 4.2 | Model outputs treated as ground truth by consumers | agreement-without-gold-standard limitation | HIGH | review-state machine; no ACCEPTED without HUMAN_REVIEW (V4.4); reports carry agreement framing only (V6.5) |
| 4.3 | Conflicts auto-resolved during dedup/join | remapping (19,230 keys) + fuzzy word_norm could be mistaken for identity | HIGH | canon_norm = identity, word_norm = dedup key only (crosswalk legend); conflicts = values, never deletions (V5.3) |
| 4.4 | Accuracy claims before adjudication | 735-record ner_comparison_errors.jsonl unadjudicated | MED | eval tables restricted to agreement metrics; accuracy language gated on HUMAN_REVIEW of evidence records |
| 4.5 | Unreviewed git state; uncommitted design work on `refactor/modular-layout-20261015-014735` | branch holds template + design docs uncommitted | MED | no commit/push without explicit go-ahead; deliverables tracked as working-tree files for now |
| 4.6 | Retrying the 4 transient PubTator3 API errors creates stray outputs | 28608086 status has 4 PUBTATOR_ERROR (502) | LOW | if retried: new results dir, same rules; never overwrite 28608086 outputs; merged coverage documented per run |
| 4.7 | Known extraction anomalies propagate into claims (`HMPAPER_000268` failure, `HMPAPER_000239` anomaly, 121 malformed llm_terms, hypernym taxa, off-schema types, 12.4% paraphrase) | release 2.1.0 QA notes | MED | V5.4 enumerated in every release report; anomalies carried not cleaned |
