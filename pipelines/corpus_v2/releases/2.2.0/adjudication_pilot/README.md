# Adjudication pilot: 500 triple mentions, model-assisted triage

**This is a MODEL-ASSISTED TRIAGE pilot. It is NOT verification.** No corpus gold
standard exists; no accuracy/precision/recall claims may be derived from anything
in this directory. Human review is the only verification gate, and every record
carries `human_review_status: pending` by design (project rule: model review is
recommendation-only; no machine record may ever be marked ACCEPTED/REJECTED).

## Sample

- Population: all 34,416 triple mentions in `corpus_v2/data/triple_mentions.jsonl`
  (stage 53/54 triples extraction, release-2.1.0 source of truth; job 28607588).
- Sample: 500 mentions, uniform random, `random.Random(20261024).sample(all, 500)`.
- Enriched substrate: `sample_500_enriched.jsonl` — each record carries the exact
  extraction-time segment text (`segmented_sections_markdown/<paper>.md` SEGMENT
  block), the pipeline's reported source sentence, assertion/speculation fields,
  QUANT fields and the pipeline's own evidence-support flags. 0 missing segments.

## Triage passes (all by GLM-5.2 agents/subagents — a recommendation pass)

| Pass | What | n |
|------|------|---|
| 1 | First-pass triage of all 500 records against mention-anchored context windows (±200 chars, cap 1000) | 500 |
| 2 | Re-review of the 134 records whose pass-1 window likely excluded the supporting sentence, using sentence-centered windows (±400) | 134 (overrides pass 1) |
| 3 | Main-agent QA re-read of a stratified subset: all LIKELY_CONTRADICTS + all LIKELY_HALLUCINATED, 8 random AMBIGUOUS, 8 random LIKELY_SUPPORTS | 38 (18 label overrides, 1 reason-code correction, 17 confirmations) |

Raw agent outputs live in `sheets/` (first pass: `sheets/batch_*.txt` +
`sheets/triage_entries/entries_batch_*.tsv`; re-review: `sheets/rereview/`;
main-agent QA sheet: `sheets/qa_crosscheck.txt`). Final labels and per-pass
provenance are in `triage_results.jsonl` (`review.pass1_label`, `review.review_pass`,
`review.qa_audit`).

## Final label distribution (500)

| Label | n |
|-------|---|
| LIKELY_SUPPORTS | 303 |
| AMBIGUOUS | 191 |
| LIKELY_CONTRADICTS | 2 |
| LIKELY_HALLUCINATED | 2 |
| INSUFFICIENT_CONTEXT | 2 |

Full cross-tabs (label × relation family, label × pipeline evidence status, escape
mapping targets) in `triage_summary.json`.

## Key findings (all model-preliminary, pending human adjudication)

1. **Pass-1 window artifact was the dominant error source.** Mention-anchored
   windows frequently excluded the supporting sentence: 119/134 re-reviewed records
   had their reported sentence present in the full segment but outside the pass-1
   window. Pass-3 confirmed the artifact also inflated LIKELY_HALLUCINATED
   (13/15 checked re-labeled: sentences verbatim in segment) and LIKELY_CONTRADICTS
   (5/7 checked re-labeled). Extreme-label model triage without full-passage
   grounding is unstable — treat every label as a weak prior for queueing human
   attention, nothing more.
2. **Escape-family raw relations are largely recoverable.** Of the 380
   OTHER_RELATION (escape) records, explicit `escape_should_map=PREDICATE` notes
   (passes 1-3) identify ≥95 mapping candidates (ASSOCIATED_WITH 23,
   INCREASED_IN 19, CAUSES 9, DECREASED_IN 7, LOCATED_IN/PRESENT_IN 6 each, ...).
   This directly informs the release-2.2.0 OTHER_RELATION/escape-predicate gap
   remediation (73% of mentions currently escape normalization).
3. **Substantive defect classes remain after window correction**: procedure-as-relation
   (methods/statistics sentences promoted to triples), binding/direction errors,
   dropped quantifiers/hedges, figure-legend and reference-list/backmatter leakage
   into triples (e.g. citation titles reified as subject+relation), and a small
   hallucination residue (placeholder objects like `not_reported` /
   "not explicitly stated location...").
4. **Quote audit**: evidence quotes were machine-checked for exact-substring match
   against the full extraction-time segment text. 63 quotes failed and were voided
   (mostly subagent quotes drawn from the reported sentence of records where that
   sentence isn't in the passage — mislabeled grounding — plus formatting breaks:
   β ligatures, embedded PDF line numbers). `evidence_quote_status` records the
   disposition per record.
5. **58/500 reported source sentences are not in the extraction-time segment text**
   (the `unresolved_not_in_source` pipeline-class residue, expected by design;
   segment-truncation upstream is documented in the release quirk list).

## Files

- `manifest.json` — sample parameters and gate rule
- `sample_500_enriched.jsonl` — review substrate (500 records, full segment texts)
- `triage_results.jsonl` — final labels with pass provenance + QA audit blocks
- `triage_summary.json` — distributions, cross-tabs, caveats (authoritative numbers)
- `sheets/` — all raw per-pass agent sheets (first pass, re-review, QA cross-check)

Generated 2026-10-24. Reviewer model: `nvidia/GLM-5.2-NVFP4` via OpenCode agents.
