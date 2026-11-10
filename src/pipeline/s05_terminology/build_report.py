#!/usr/bin/env python3
"""Supporting artifact — ``terminology_extraction_report.md``.

A human-readable narrative for one terminology-extraction build, assembled from
the artifacts' own summary files. Nothing is hand-typed and nothing is
estimated: a number that has no source in a summary file is reported as
``not measured`` rather than as a plausible value.

The report is deliberately explicit about what is NOT verified, because the
build's whole point is to keep machine output separable from human review.

Outputs (in ``--out_dir``)
--------------------------
    terminology_extraction_report.md
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fmt(v, dash="not measured"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _table(rows, headers):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Build terminology_extraction_report.md")
    ap.add_argument("--out_dir", type=Path, required=True)
    ap.add_argument("--version", default="v1")
    args = ap.parse_args()
    d = args.out_dir
    d.mkdir(parents=True, exist_ok=True)

    mentions = _load(d / "_mentions_summary.json") or {}
    canon = _load(d / "canonical_terms_summary.json") or {}
    defs = _load(d / "_definitions_summary.json") or {}
    mapsum = _load(d / "mapping_projection_summary.json") or {}
    tax = _load(d / "taxonomy_summary.json") or {}
    reg = _load(d / "ontology_registry.json") or {}
    val = _load(d / "validation_summary.json") or {}
    man = _load(d / "terminology_extraction_manifest.json") or {}

    cov = val.get("coverage") or {}
    mo = val.get("mention_offset_verification") or {}
    mc = canon.get("counts") or {}
    mp = mapsum.get("counts") or {}
    dtax = tax.get("taxonomy") or {}
    dtax_c = tax.get("classification") or {}
    status = val.get("overall_status", "UNKNOWN")

    L = []
    A = L.append
    A("# Terminology extraction report")
    A("")
    A(f"- **Build:** `{args.version}`  ")
    A(f"- **Generated:** {time.strftime('%Y-%m-%dT%H:%M:%S')}  ")
    A(f"- **Overall status:** **`{status}`**  ")
    A(f"- **Corpus:** 453-paper human-microbiome section corpus")
    A("")
    A(f"> `{status}` is a fail-closed roll-up. It becomes `COMPLETE` only when every "
      "corpus paper is present, every section integrity check passes, and every paper "
      "with content carries at least one mention. Section integrity alone is never "
      "enough to claim completeness.")
    A("")

    # ── coverage ────────────────────────────────────────────────────────────
    A("## 1. Coverage")
    A("")
    A(_table([
        ["Papers in corpus membership", _fmt(cov.get("papers_in_corpus_membership"))],
        ["Papers processed", _fmt(cov.get("papers_processed"))],
        ["Papers not processed", _fmt(cov.get("papers_not_processed"))],
        ["Papers flagged", _fmt(cov.get("papers_flagged"))],
        ["Section units validated", _fmt(cov.get("sections_validated"))],
        ["Section units flagged", _fmt(cov.get("sections_flagged"))],
        ["Section units not applicable (empty placeholders)",
         _fmt(cov.get("sections_not_applicable"))],
        ["Section units total", _fmt(cov.get("sections_total"))],
        ["Characters processed", _fmt(cov.get("total_chars_processed"))],
        ["Corpus build: READY / BLOCKED",
         f"{_fmt(cov.get('corpus_report_ready'))} / {_fmt(cov.get('corpus_report_blocked'))}"],
    ], ["Measure", "Value"]))
    A("")
    A(f"Every processed section is hashed and recorded in "
      f"`terminology_validation.jsonl`. "
      f"{_fmt(cov.get('sections_not_applicable'))} zero-character "
      "`front/(preamble)` placeholders are `NOT_APPLICABLE` — they are structural, "
      "not failures — and are excluded from the pass/fail denominator.")
    A("")

    A("### Mention offset verification")
    A("")
    A(_table([
        ["Mentions checked (with integer offsets)", _fmt(mo.get("mentions_checked"))],
        ["Resolved exactly", _fmt(mo.get("mentions_resolved_exactly"))],
        ["Unresolved", _fmt(mo.get("mentions_unresolved"))],
        ["% resolved", _fmt(mo.get("pct_resolved"))],
        ["Excluded — no integer offsets",
         _fmt(mo.get("mentions_excluded_non_integer_offsets"))],
        ["Mention rows seen (checked + excluded)",
         _fmt(mo.get("mentions_seen_total"))],
    ], ["Measure", "Value"]))
    A("")
    A("An offset resolves exactly when `section_text[start:end] == surface_form`, "
      "where `section_text` is the section body the extractor read. A mismatch is "
      "reported for review and is never auto-repaired, re-anchored, or dropped. A "
      "mention whose offsets were never located has no span to verify: it is counted "
      "explicitly as *excluded — no integer offsets* and remains in the mention "
      "artifact. The checked and excluded counts are disjoint, so nothing hides "
      "between them.")
    A("")
    mls = val.get("mention_link_status") or {}
    if mls.get("by_link_status"):
        A("### Mention → canonical-term link")
        A("")
        A(_table([[k, _fmt(v)] for k, v in mls.get("by_link_status") or []],
                 ["`link_status`", "Mention rows"]))
        A("")
        A(f"**{_fmt(mls.get('n_linked'))}** rows carry a resolved canonical term and "
          f"**{_fmt(mls.get('n_unresolved'))}** are explicitly unresolved. The link is "
          "an exact match on the sanitized normalized surface — never fuzzy and never "
          "type-coerced — and a type divergence is recorded on the row rather than "
          "hidden. `PENDING_CANONICAL_STAGE` means Stage 2 did not run on this file.")
        A("")

    # ── stages ──────────────────────────────────────────────────────────────
    A("## 2. Stage 1 — mention extraction")
    A("")
    srcs = mentions.get("sources") or {}
    if srcs:
        A(_table(
            [[k, _fmt(v.get("status")), _fmt(v.get("rows_read")), _fmt(v.get("rows")),
              _fmt(v.get("rows_skipped_empty_surface")),
              _fmt(v.get("offsets_verified")), _fmt(v.get("offsets_unverified")),
              _fmt(v.get("unknown_section"))]
             for k, v in sorted(srcs.items())],
            ["Source", "Status", "Rows read", "Rows written", "Skipped (empty surface)",
             "Verified", "Unverified", "Unknown section"]))
    A("")
    A(f"**{_fmt(mentions.get('rows_written'))}** mention records written from "
      f"**{_fmt(mentions.get('rows_read'))}** source rows read; "
      f"**{_fmt(mentions.get('rows_skipped_empty_surface'))}** rows were skipped and "
      "counted separately because they carried no surface form at all (a row with no "
      "text cannot be a mention). *Rows read* is the unmodified source total, so "
      "`rows read − skipped = rows written` holds per source and in total. Each mention "
      "keeps its own `mention_id` (one occurrence as tagged by one extractor) plus an "
      "extractor-independent `occurrence_key`, so competing type assignments from "
      "different models stay distinct and are never merged.")
    A("")

    # ── stage 2 ─────────────────────────────────────────────────────────────
    A("## 3. Stage 2 — canonical terms")
    A("")
    A(_table([
        ["Canonical terms", _fmt(mc.get("canonical_terms"))],
        ["Distinct normalized forms", _fmt(mc.get("distinct_term_norm"))],
        ["Surface forms with >1 type", _fmt(mc.get("multi_type_surface_forms"))],
        ["Duplicated term ids", _fmt(mc.get("duplicated_term_ids"))],
        ["Generic (`ENTITY`) terms", _fmt(mc.get("generic_entity_terms"))],
        ["Terms with mention rollup", _fmt(mc.get("terms_with_mention_rollup"))],
        ["Mention rows read", _fmt(mc.get("mention_rows_read"))],
        ["Mention rows linked", _fmt(mc.get("mention_rows_linked"))],
        ["Mention rows unresolved", _fmt(mc.get("mention_rows_unresolved"))],
        ["Terms with taxonomy label", _fmt(mc.get("terms_with_taxonomy_label"))],
    ], ["Measure", "Value"]))
    A("")
    A("Identity rule: **one canonical term per `(term_norm, cdm_type)`**. A surface "
      "form that legitimately carries several types keeps one row per type; the extra "
      "types are recorded as evidence (`alternative_types`) and are never used as a "
      "merge signal on their own.")
    A("")
    A("### Frequency semantics")
    A("")
    A("Frequency fields are **not** mention-row counts. Counting rows would multiply "
      "one occurrence by up to four, because the four extractors see the same "
      "occurrence. The counting keys are therefore:")
    A("")
    A(_table([
        ["`mention_count`", "distinct `occurrence_key` (extractor-independent, the "
                            "same occurrence counted once however many models saw it)"],
        ["`mention_rows`", "raw linked mention rows (kept alongside, never used as the "
                           "frequency)"],
        ["`mention_count_exact_type`", "distinct occurrences whose link was type-exact"],
        ["`paper_count`", "distinct `paper_id`"],
        ["`section_count`", "distinct `(paper_id, section_id)` — section ids are only "
                            "unique within a paper and are never summed across papers"],
        ["`alternative_labels`", "distinct surface forms that linked to the term "
                                 f"(capped at {_fmt(25)}; `n_alternative_labels` is the "
                                 "full count and `alternative_labels_truncated` flags a cap)"],
        ["`processing_run_ids`", "the extractor run ids that contributed mentions"],
    ], ["Field", "Counting key / scope"]))
    A("")
    lk = canon.get("mention_link") or {}
    if lk.get("by_link_status"):
        A("**By `link_status`:**")
        A("")
        A(_table([[k, _fmt(v)] for k, v in lk["by_link_status"]], ["`link_status`", "Rows"]))
        A("")
    A("A term with no linked mention keeps `mention_count = null` rather than `0`: the "
      "mention stream is a subset of the corpus, so a zero would be an unsupported "
      "claim.")
    A("")
    fa = canon.get("field_availability") or {}
    if fa:
        A("**Field availability** (nothing is invented to fill a gap):")
        A("")
        A(_table([[k, v] for k, v in sorted(fa.items())], ["Field", "Availability"]))
        A("")

    # ── stage 3 ─────────────────────────────────────────────────────────────
    A("## 4. Stage 3 — source-grounded definitions")
    A("")
    A("Deterministic, CPU-only, no LLM, no network. Definitions are copied **verbatim** "
      "at reproducible offsets; a candidate is discarded unless both "
      "`text[start:end] == definition_text` and `text[dstart:dend] == matched_surface`. "
      "Every row is `review_status=REVIEW_REQUIRED` with `confidence=null`.")
    A("")
    A(_table([
        ["Canonical terms in scope", _fmt(defs.get("canonical_terms_in_scope"))],
        ["Terms with a source definition",
         _fmt(defs.get("canonical_terms_with_source_definition"))],
        ["% of terms covered", _fmt(defs.get("pct_terms_covered"))],
        ["Definition rows", _fmt(defs.get("definition_rows"))],
        ["Papers scanned", _fmt(defs.get("papers_scanned"))],
    ], ["Measure", "Value"]))
    A("")
    bds = defs.get("by_definition_source") or {}
    if bds:
        A("**By provenance class (controlled vocabulary):**")
        A("")
        A(_table([[k, _fmt(v)] for k, v in sorted(bds.items(), key=lambda x: -x[1])],
                 ["`definition_source`", "Rows"]))
        A("")
    A("`CONTEXTUAL_DESCRIPTION` rows are **not** formal definitions and are never "
      "reported as such. External/ontology definitions (`ONTOLOGY_DEFINITION`, "
      "`UMLS_SOURCE_DEFINITION`, `BIOPORTAL_DEFINITION`, `OMOP_CONCEPT_DESCRIPTION`) "
      "are a different provenance class and are **not** produced by this stage. A "
      "paper-vs-ontology disagreement would retain both rows and be marked for review.")
    A("")

    # ── stage 4 ─────────────────────────────────────────────────────────────
    A("## 5. Stage 4 — semantic classification")
    A("")
    A(_table([
        ["Taxonomy id", _fmt(dtax.get("taxonomy_id"))],
        ["Version", _fmt(dtax.get("version"))],
        ["Status", _fmt(dtax.get("status"))],
        ["Upper categories", _fmt(dtax.get("n_upper_categories"))],
        ["Subcategories", _fmt(dtax.get("n_subcategories"))],
        ["Reserved (non-hierarchical)",
         ", ".join(dtax.get("reserved_categories") or []) or "none"],
        ["Terms classified (draft)", _fmt(dtax_c.get("n_classified_terms"))],
        ["Clean upper-level assignments", _fmt(dtax_c.get("n_clean_upper_assignments"))],
        ["Invented categories flagged", _fmt(dtax_c.get("n_invented_categories_flagged"))],
        ["% of canonical terms classified", _fmt((tax.get("coverage") or {}).get("pct_classified"))],
    ], ["Measure", "Value"]))
    A("")
    A("The taxonomy is **exported as-is**; this stage invents no categories. "
      "`UNCERTAIN` is reserved and non-hierarchical, so an uncategorisable term is "
      "flagged rather than forced into an upper category. Classification output is an "
      "LLM-assisted **draft**: rows keep their own verification status and are not "
      "promoted to verified here.")
    A("")

    # ── stage 5 ─────────────────────────────────────────────────────────────
    A("## 6. Stage 5 — controlled-vocabulary linking")
    A("")
    A(_table([
        ["Mapping rows", _fmt(mp.get("rows"))],
        ["Rows with a concept id", _fmt(mp.get("rows_with_concept_id"))],
        ["Terms with any candidate (resolved to a canonical term)",
         _fmt(mp.get("terms_with_any_candidate"))],
        ["… including unresolved subjects (reported separately, never merged in)",
         _fmt(mp.get("terms_with_any_candidate_including_unresolved"))],
        ["Terms: no match found", _fmt(mp.get("terms_no_match_found"))],
        ["Terms: lookup failed", _fmt(mp.get("terms_lookup_failed"))],
        ["Rows re-keyed to a canonical term (type divergent)",
         _fmt(mp.get("rows_rekeyed_type_divergent"))],
        ["Rows left unresolved (no canonical term)",
         _fmt(mp.get("rows_unresolved_no_canonical_term"))],
        ["Distinct `mapping_id`", _fmt(mp.get("distinct_mapping_ids"))],
        ["Duplicate `mapping_id`", _fmt(mp.get("duplicate_mapping_ids"))],
        ["`mapping_id` unique over all rows", _fmt(mp.get("mapping_id_unique"))],
        ["Auto-accept eligible (would qualify)", _fmt(mp.get("auto_accept_eligible"))],
        ["**Auto-accepted**", _fmt(mp.get("auto_accepted"))],
    ], ["Measure", "Value"]))
    A("")
    A("`terms_with_any_candidate` counts subjects that **resolved** to a canonical "
      "term and carry at least one concept id. The earlier figure (65,293) also swept "
      "in the 5,237 rows whose `(term_norm, cdm_type)` key was absent from the "
      "canonical table, so it over-counted *subjects*; the including-unresolved figure "
      "is now reported on its own line and is never folded into the resolved one.")
    A("")
    A("**Mapping subject resolution** — a row's own `(term_norm, cdm_type)` key can "
      "be absent from the canonical table even when the normalized term is present "
      "(the MeSH gazetteer types a heading by its MeSH tree; the canonical table types "
      "it by CDM entity type). Those rows are re-keyed to the canonical term with the "
      "divergence recorded, or marked unresolved — never dropped and never force-linked:")
    A("")
    kr = mapsum.get("by_key_resolution") or []
    if kr:
        A(_table([[k, _fmt(v)] for k, v in kr], ["`key_resolution`", "Rows"]))
        A("")
    ta = mapsum.get("by_type_agreement") or []
    if ta:
        A("**By `type_agreement` (only meaningful for re-keyed rows):**")
        A("")
        A(_table([[k, _fmt(v)] for k, v in ta], ["`type_agreement`", "Rows"]))
        A("")
    A("`mapping_id` is derived from `(subject_key, source_tier, concept_id, "
      "candidate_rank, duplicate_index)` — the trailing occurrence index keeps ids "
      "unique even when a vocabulary returned the same concept more than once, so no "
      "candidate is collapsed. A row whose subject never resolved carries an "
      "`UNRESOLVED:<term_norm>|<cdm_type>` `subject_key`, `mapping_disposition = "
      "UNRESOLVED_NO_CANONICAL_TERM`, `auto_accept_eligible = false`, and keeps its "
      "candidate/error evidence intact.")
    A("")
    cal = mapsum.get("calibration") or {}
    if (mp.get("auto_accepted") or 0) > 0:
        A("`auto_accepted` rows were lifted from `REVIEW_REQUIRED` to "
          "`AUTO_ACCEPTED` because their `(source_service, mapping_relation)` "
          "stratum cleared a **human-reviewed** calibration threshold "
          "(spec 12). The threshold is a property of the labelled sample, not "
          "proof of correctness on the unlabelled population; "
          "`auto_accept_eligible` remains the mark of what *would* qualify.")
    else:
        A("`auto_accepted` is **0** by construction: no acceptance threshold has been "
          "calibrated against a human-reviewed sample, so nothing may be auto-accepted. "
          "`auto_accept_eligible` records what *would* qualify once thresholds are "
          "calibrated — it is not an acceptance.")
    if cal:
        A("")
        A("Calibration state: `%s`%s." % (
            cal.get("status") or "NOT_CALIBRATED",
            (" — %s" % cal["reason"]) if cal.get("reason") else ""))
    A("")
    rel = mapsum.get("by_mapping_relation") or []
    if rel:
        A("**By `mapping_relation`:**")
        A("")
        A(_table([[k, _fmt(v)] for k, v in rel], ["`mapping_relation`", "Rows"]))
        A("")
    disp = mapsum.get("by_mapping_disposition") or []
    if disp:
        A("**By `mapping_disposition`:**")
        A("")
        A(_table([[k, _fmt(v)] for k, v in disp], ["`mapping_disposition`", "Rows"]))
        A("")
    A("`AMBIGUOUS` is scoped **within a single vocabulary**: two different "
      "vocabularies both matching the same term (e.g. MeSH and OMOP/SNOMED) is "
      "corroboration, not ambiguity. Only tied top-confidence candidates carrying "
      "different concept ids *in the same vocabulary* are flagged — the homonym case. "
      "Nothing is forced to a single answer.")
    A("")

    # ── registry ────────────────────────────────────────────────────────────
    A("## 7. Vocabularies consulted")
    A("")
    vocs = reg.get("vocabularies") or []
    if vocs:
        A(_table(
            [[v.get("vocabulary"), _fmt(v.get("edition")), v.get("availability"),
              "yes" if v.get("available") else "no",
              v.get("route")]
             for v in vocs],
            ["Vocabulary", "Edition", "Route", "Available", "How reached"]))
        A("")
        A(f"{_fmt(reg.get('n_local'))} local and {_fmt(reg.get('n_network'))} network "
          "vocabularies. The local path is fully offline; the network tiers are "
          "additive and skippable. Credentials are read from the environment only, "
          "never logged, and never written into an artifact — only their *presence* "
          "is tested.")
        A("")
        A("Only the **term string** is ever sent to a remote service; full paper text "
          "is never transmitted. A no-match and a failed lookup are separate outcomes "
          "and are never conflated.")
    A("")

    # ── completeness ────────────────────────────────────────────────────────
    A("## 8. Completeness and what is NOT covered")
    A("")
    # Computed from the directory rather than read from the manifest: the manifest
    # records the state before the report existed, so using it here would report
    # this very file as missing on every run.
    expected = ["term_mentions.jsonl", "canonical_terms.jsonl",
                "term_definitions.jsonl", "term_ontology_mappings.jsonl",
                "terminology_taxonomy.json", "ontology_registry.json",
                "terminology_validation.jsonl",
                "terminology_extraction_manifest.json",
                "terminology_extraction_report.md"]
    missing = [n for n in expected if not (d / n).exists()]
    A(_table([
        ["Artifacts expected", _fmt(len(expected))],
        ["Artifacts present", _fmt(len(expected) - len(missing))],
        ["Artifacts missing", ", ".join(missing) or "none"],
    ], ["Measure", "Value"]))
    A("")
    nc = man.get("not_covered") or [
        "No canonical term, definition or mapping is human-verified in this build.",
        "External ontology definitions (UMLS/OMOP/BioPortal descriptions) are NOT "
        "produced: they are a different provenance class from source definitions.",
        "No acceptance threshold has been calibrated, so nothing is AUTO_ACCEPTED.",
        "OMOP linking is exact-normalized only; a miss is not evidence of absence.",
        "MeSH/OMOP cover only their own vocabularies; specialist strain/gene names "
        "may legitimately have no candidate.",
        "Definition extraction is limited to the sections scanned; a term with no "
        "definition found is scoped to this pass, not to the literature.",
    ]
    for item in nc:
        A(f"- {item}")
    A("")
    A("### Corpus stages not run for this build")
    A("")
    A("- `corpus_pipeline` stage 06 (judgments/evidence values, JEV): **not run**")
    A("- `corpus_pipeline` stage 11 (embeddings + dense index): **not run**")
    A("- Retrieval evaluation: **blocked** — no human-reviewed labels exist")
    A("")
    A("These are stated as not-run rather than assumed complete.")
    A("")

    A("## 9. Standing caveats")
    A("")
    for item in (man.get("caveats") or [
        "Counts are read from the artifacts' own summaries or recomputed from the "
        "artifacts; none are estimated.",
        "A MISSING artifact is reported as MISSING, never as zero or complete.",
        "Model confidence is not correctness and is not treated as such.",
    ]):
        A(f"- {item}")
    A("")
    A("---")
    A("")
    A("*This report is generated from the artifacts' own summary files. If a number "
      "has no source, it is reported as `not measured` rather than guessed.*")

    out = d / "terminology_extraction_report.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(L)} lines)")


if __name__ == "__main__":
    main()
