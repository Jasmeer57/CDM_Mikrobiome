#!/usr/bin/env python3
"""Stage 60: corpus-wide validation and reconciliation (template §3I, §7).

Re-validates every produced record against the JSON schemas, cross-checks counts
between papers / sections / segments / LLM output, and emits a per-paper
validation record plus a corpus-level report.

Fail-closed: a paper is COMPLETE only when every check passes. Counts must
reconcile exactly; any mismatch is reported, never rounded away.

Outputs
  data/validation_per_paper.jsonl
  validation/validation_report.json
  validation/corpus_artifact_hashes.json (sha256 of every data artifact)
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C

STAGE = "stage60_validate"
PV = "2.1.0"

# full-text completeness can only get worse as more evidence arrives
FT_SEVERITY = {"complete": 0, "not_checked": 1, "partial": 2, "failed": 3}


def worse_ft(a: str, b: str) -> str:
    return a if FT_SEVERITY.get(a, 1) >= FT_SEVERITY.get(b, 1) else b


def load_schema(name: str) -> dict:
    p = C.CORPUS_DIR / "schema" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def validate_record(rec: dict, schema: dict) -> list:
    """Minimal JSON-Schema subset: required, enum, type, pattern. Returns failures."""
    fails = []
    for key in schema.get("required", []):
        if rec.get(key) is None:
            fails.append(f"missing_required:{key}")
    types = {"string": str, "integer": int, "boolean": bool,
             "array": list, "object": dict, "null": type(None)}
    for key, spec in (schema.get("properties") or {}).items():
        if key not in rec or rec[key] is None:
            continue
        val = rec[key]
        if "enum" in spec and val not in spec["enum"]:
            fails.append(f"enum:{key}={val!r}")
        t = spec.get("type")
        if isinstance(t, str) and t in types:
            if t == "integer" and isinstance(val, bool):
                fails.append(f"type:{key} expected integer")
            elif not isinstance(val, types[t]):
                fails.append(f"type:{key} expected {t}")
        elif isinstance(t, list):
            ok = any((tt == "integer" and isinstance(val, int) and not isinstance(val, bool))
                     or isinstance(val, types.get(tt, object)) for tt in t)
            if not ok:
                fails.append(f"type:{key} expected one of {t}")
        if "pattern" in spec:
            import re
            if not re.search(spec["pattern"], str(val)):
                fails.append(f"pattern:{key}")
    return fails


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    started = C.now_utc()

    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    segments = C.read_jsonl(C.CORPUS_DIR / "data" / "segments.jsonl")
    llm = {r["section_record_id"]: r for r in
           C.read_jsonl(C.CORPUS_DIR / "data" / "llm_terms.jsonl")}
    crosscheck = {r["paper_id"]: r for r in
                  C.read_jsonl(C.CORPUS_DIR / "data" / "fulltext_crosscheck.jsonl")}
    studies = {r["paper_id"]: r for r in
               C.read_jsonl(C.CORPUS_DIR / "data" / "studies.jsonl")}
    findings = C.read_jsonl(C.CORPUS_DIR / "data" / "findings.jsonl")
    if not papers or not sections:
        sys.exit("ERROR: papers/sections missing; run stages 10–45 first")
    if not studies:
        sys.exit("ERROR: data/studies.jsonl missing; run stage 51 first")
    if not findings:
        sys.exit("ERROR: data/findings.jsonl missing; run stage 52 (and 55) first")

    paper_schema = load_schema("paper.schema.json")
    section_schema = load_schema("section.schema.json")
    study_schema = load_schema("study.schema.json")
    finding_schema = load_schema("finding.schema.json")

    sec_by_paper = defaultdict(list)
    for s in sections:
        sec_by_paper[s["paper_id"]].append(s)
    seg_by_paper = defaultdict(list)
    for s in segments:
        seg_by_paper[s["paper_id"]].append(s)
    finds_by_paper = defaultdict(list)
    for f in findings:
        finds_by_paper[f.get("paper_id") or f.get("corpus_id")].append(f)

    prog = C.Progress(STAGE, total=len(papers), unit="paper", desc="validate corpus")
    per_paper = []
    issue_counter = Counter()

    for p in papers:
        pid = p["paper_id"]
        secs = sec_by_paper.get(pid, [])
        segs = seg_by_paper.get(pid, [])
        paper_fails = validate_record(p, paper_schema)
        section_fails = []
        for s in secs:
            section_fails.extend(f"{s['section_record_id']}:{f}"
                                 for f in validate_record(s, section_schema))

        eligible = [s for s in secs if s.get("extraction_eligibility")]
        enriched = [s for s in eligible if s["section_record_id"] in llm]
        noncanonical = not p.get("is_canonical", True)

        # ---- study-layer + findings-layer checks (stages 51/52/55) ----
        study = studies.get(pid)
        study_fails = []
        if study is None:
            study_fails.append("missing_study_record")
        else:
            study_fails.extend(f"study:{f}" for f in validate_record(study, study_schema))
        p_finds = finds_by_paper.get(pid, [])
        finding_fails = []
        for f in p_finds:
            finding_fails.extend(f"{f.get('finding_id')}:{msg}"
                                 for msg in validate_record(f, finding_schema))
        finding_ids = [f.get("finding_id") for f in p_finds]
        finding_fails.extend(
            f"duplicate_finding_id:{fid}" for fid, n
            in Counter(finding_ids).items() if n > 1)
        # evidence locator: every finding must have a section-anchored locator and
        # an automated status from stage 55; unresolved stays flagged not dropped
        locator_fails = [f"{f.get('finding_id')}:no_evidence_locator_status"
                         for f in p_finds if not f.get("evidence_locator_status")]
        resolved = sum(1 for f in p_finds
                       if f.get("evidence_locator_status") in
                       ("verified_exact", "verified_normalized"))
        locator_unresolved = len(p_finds) - resolved

        xc = crosscheck.get(pid)
        needs_xc = (p.get("bioproject_link") or {}).get("bundle_format") == "jats_xml"
        if not needs_xc:
            xc_ok, xc_why = True, "no original JATS XML; cross-check not applicable"
        elif xc is None:
            xc_ok, xc_why = False, "original JATS XML exists but no cross-check record"
        else:
            xc_ok = xc.get("crosscheck_status") == "COMPLETE"
            xc_why = f"cross-check {xc.get('crosscheck_status')}: {xc.get('evidence')}"

        checks = [
            ("CRIT_paper_schema", not paper_fails, ";".join(paper_fails)),
            ("CRIT_section_schema", not section_fails, ";".join(section_fails[:5])),
            ("CRIT_sections_present", len(secs) > 0, "no section records"),
            ("CRIT_section_ids_unique",
             len({s["section_record_id"] for s in secs}) == len(secs),
             "duplicate section_record_id"),
            ("CRIT_section_counts_reconcile",
             p.get("sections_discovered") in (None, len(secs)),
             f"paper says {p.get('sections_discovered')}, found {len(secs)}"),
            ("CRIT_segments_reconcile",
             sum(len(s.get("segment_ids") or []) for s in secs) == len(segs),
             f"section segment_ids={sum(len(s.get('segment_ids') or []) for s in secs)}, "
             f"segment records={len(segs)}"),
            ("CRIT_characters_reconcile",
             sum(s.get("character_count") or 0 for s in secs) ==
             sum(x.get("character_count") or 0 for x in segs),
             "section vs segment character totals differ"),
            ("PART_llm_coverage",
             (not eligible) or len(enriched) == len(eligible),
             f"{len(enriched)}/{len(eligible)} eligible sections enriched"),
            ("CRIT_study_schema", not study_fails, ";".join(study_fails[:5])),
            ("CRIT_finding_schema", not finding_fails, ";".join(finding_fails[:5])),
            ("CRIT_finding_evidence_locator", not locator_fails,
             ";".join(locator_fails[:5])),
            ("WARN_study_extraction_status",
             (study or {}).get("extraction_status") == "COMPLETE",
             f"study extraction_status={(study or {}).get('extraction_status')}"),
            ("WARN_unresolved_evidence", locator_unresolved == 0,
             f"{locator_unresolved} findings with unresolved_not_in_source"),
            ("PART_hash_chain",
             all(s.get("text_hash_sha256") for s in secs),
             "sections without text hash"),
            ("PART_fulltext_crosscheck", xc_ok, xc_why),
            ("WARN_identifier", bool(p.get("PMID") or p.get("DOI")),
             "no PMID and no DOI"),
            ("WARN_title", bool(p.get("title")), "no title"),
            ("WARN_canonical",
             (p.get("canonical_paper_id") or pid) in {x["paper_id"] for x in papers},
             "canonical_paper_id does not resolve"),
        ]
        status, reason = C.fail_closed(checks)
        if noncanonical and status == "COMPLETE":
            status, reason = "PARTIAL", "non-canonical duplicate record (excluded subset)"

        for rid, ok, _ in checks:
            if not ok:
                issue_counter[rid] += 1

        llm_terms = sum(len(llm[s["section_record_id"]].get("llm_terms") or [])
                        for s in enriched if s["section_record_id"] in llm)
        # baseline is stage 40's verdict (full_text_parse_status), not the value
        # a previous validation pass may have already downgraded
        baseline_ft = C.FT_FROM_INTERNAL.get(
            p.get("full_text_parse_status") or "",
            p.get("full_text_completeness") or "not_checked")
        rec = {
            "paper_id": pid,
            "validation_status": status,
            "full_text_completeness": worse_ft(
                baseline_ft, C.FT_FROM_INTERNAL.get(status, "not_checked")),
            "checks": [{"rule_id": rid, "passed": ok, "detail": why}
                       for rid, ok, why in checks],
            "counts": {
                "sections": len(secs),
                "sections_eligible": len(eligible),
                "segments": len(segs),
                "characters": sum(s.get("character_count") or 0 for s in secs),
                "tokens": sum(s.get("token_count") or 0 for s in secs),
                "llm_terms": llm_terms,
                "findings": len(p_finds),
                "findings_evidence_resolved": resolved,
                "findings_evidence_unresolved": locator_unresolved,
            },
            "known_issues": [f"{rid}:{why}" for rid, ok, why in checks if not ok],
            "validated_at": C.now_utc(),
            "validator_version": PV,
        }
        # keep the paper tracking fields in sync with validation (template §3A/§3E)
        p["validation_status"] = status
        p["validation_evidence"] = reason
        p["full_text_completeness"] = rec["full_text_completeness"]
        p["processing_status"] = ("automated_checks_passed" if status == "COMPLETE"
                                  else p.get("processing_status", "not_started"))
        per_paper.append(rec)
        prog.update(1, detail=f"{pid} {status} sections={len(secs)} llm_terms={llm_terms}")

    C.write_jsonl(C.CORPUS_DIR / "data" / "validation_per_paper.jsonl", per_paper)
    C.write_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl", papers)
    C.write_tracking_table(papers)

    # ---- corpus-level reconciliation ----
    def counter_sum(key, rows):
        return sum(r.get(key) or 0 for r in rows)

    corpus_checks = [
        ("CRIT_all_papers_validated", len(per_paper) == len(papers),
         f"{len(per_paper)} validation records for {len(papers)} papers"),
        ("CRIT_sections_attributed",
         all(s["paper_id"] in {p["paper_id"] for p in papers} for s in sections),
         "section references an unknown paper"),
        ("CRIT_segment_attribution",
         all(s["paper_id"] in {p["paper_id"] for p in papers} for s in segments),
         "segment references an unknown paper"),
        ("CRIT_counts_reconcile",
         counter_sum("sections_discovered", papers) == len(sections),
         f"papers claim {counter_sum('sections_discovered', papers)} sections, "
         f"file has {len(sections)}"),
        ("PART_no_failed_papers",
         all(r["validation_status"] != "FAILED" for r in per_paper),
         f"{sum(1 for r in per_paper if r['validation_status'] == 'FAILED')} FAILED papers"),
        ("PART_llm_all_eligible_covered",
         all(r["counts"]["sections_eligible"] ==
             sum(1 for s in llm.values() if s["paper_id"] == r["paper_id"])
             for r in per_paper),
         "eligible section not enriched"),
        ("CRIT_studies_one_per_paper",
         len(studies) == len([p2 for p2 in papers]) and
         all(p2["paper_id"] in studies for p2 in papers),
         f"{len(studies)} study records for {len(papers)} papers"),
        ("CRIT_findings_attributed",
         all((f.get("paper_id") or f.get("corpus_id")) in
             {p2["paper_id"] for p2 in papers} for f in findings),
         "finding references an unknown paper"),
        ("CRIT_finding_ids_unique",
         len({f["finding_id"] for f in findings if f.get("finding_id")}) ==
         sum(1 for f in findings if f.get("finding_id")),
         "duplicate finding_id in corpus"),
        ("PART_findings_study_links_resolve",
         all(f.get("study_id") == f"{f.get('paper_id') or f.get('corpus_id')}_STUDY_001"
             for f in findings),
         "finding study_id does not resolve to its paper's STUDY_001"),
        ("PART_findings_all_have_locator_status",
         all(f.get("evidence_locator_status") for f in findings),
         "findings without evidence_locator_status (stage 55 not run?)"),
    ]
    corpus_status, corpus_reason = C.fail_closed(corpus_checks)

    def load_report(rel):
        fp = C.CORPUS_DIR / rel
        if not fp.exists():
            return {}
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    studies_report = load_report("validation/studies_report.json")
    findings_report = load_report("validation/findings_report.json")

    artifact_hashes = {}
    for rel in ("data/papers.jsonl", "data/sections.jsonl", "data/segments.jsonl",
                "data/llm_terms.jsonl", "data/studies.jsonl", "data/findings.jsonl",
                "data/validation_per_paper.jsonl"):
        fp = C.CORPUS_DIR / rel
        if fp.exists():
            artifact_hashes[rel] = {"sha256": C.sha256_file(fp),
                                    "bytes": fp.stat().st_size,
                                    "recorded_at": C.now_utc()}
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "artifact_hashes.json", artifact_hashes)

    status_counts = Counter(r["validation_status"] for r in per_paper)
    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "corpus_status": corpus_status,
        "corpus_evidence": corpus_reason,
        "corpus_checks": [{"rule_id": rid, "passed": ok, "detail": why}
                          for rid, ok, why in corpus_checks],
        "papers": len(papers),
        "papers_validated": len(per_paper),
        "validation_status_counts": dict(status_counts),
        "papers_with_issues": sum(1 for r in per_paper if r["known_issues"]),
        "issue_counts_by_rule": dict(issue_counter),
        "sections": len(sections),
        "sections_eligible": sum(1 for s in sections if s.get("extraction_eligibility")),
        "sections_validated": len(sections),
        "segments": len(segments),
        "characters": counter_sum("character_count", sections),
        "tokens": counter_sum("token_count", sections),
        "llm_records": len(llm),
        "llm_terms_total": sum(len(r.get("llm_terms") or []) for r in llm.values()),
        "llm_status_counts": dict(Counter(r.get("llm_status") for r in llm.values())),
        "duplicates_excluded": sum(1 for p in papers if not p.get("is_canonical", True)),
        "studies": {
            "records": len(studies),
            "extraction_status_counts": dict(Counter(
                r.get("extraction_status") for r in studies.values())),
            "llm_status_counts": dict(Counter(
                r.get("llm_status") for r in studies.values())),
            "conflict_fields_total": sum(
                len(r.get("study_provenance", {}).get("conflicts", []))
                for r in studies.values()),
            "field_fill_rate": (studies_report or {}).get("field_fill_rate"),
        },
        "findings": {
            "records": len(findings),
            "papers_with_findings": len(finds_by_paper),
            "claim_type_counts": dict(Counter(f.get("claim_type") for f in findings)),
            "direction_counts": dict(Counter(f.get("direction") for f in findings)),
            "evidence_locator_status_counts": dict(Counter(
                f.get("evidence_locator_status") for f in findings)),
            "quote_resolution_rate": (findings_report or {}).get("quote_resolution_rate"),
            "verification_status_counts": dict(Counter(
                f.get("verification_status") for f in findings)),
        },
        "fulltext_crosscheck": {
            "records": len(crosscheck),
            "status_counts": dict(Counter(r.get("crosscheck_status")
                                          for r in crosscheck.values())),
            "papers_with_missing_sections": sum(
                1 for r in crosscheck.values() if r.get("missing_sections")),
            "papers_without_independent_source": len(papers) - len(crosscheck),
        },
        "artifact_hashes": {k: v["sha256"] for k, v in artifact_hashes.items()},
        "note": "schema validity is not scientific correctness; annotation remains unverified",
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "validation_report.json", summary)

    ev.record(pipeline_stage=STAGE, run_status="success" if corpus_status != "FAILED" else "failed",
              started_at=started, completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"corpus_status={corpus_status} papers={len(papers)} sections={len(sections)}")
    ev.close()
    prog.close(summary=f"corpus={corpus_status} {dict(status_counts)}")
    print(json.dumps(summary, indent=2))

    if corpus_status == "FAILED":
        sys.exit(f"FAILED: {corpus_reason}")


if __name__ == "__main__":
    main()
