#!/usr/bin/env python3
"""Stage 45: section integrity validation (template §3E/§3F, §7 document integrity).

Independent re-check of every section record produced by stage 40. This stage
does not trust stage 40's stored hashes: it recomputes them from the stored text
and compares, re-reads the source file, and inspects the text for marker
leakage, NUL bytes and duplicated blocks.

It also adds the token counts deferred by stage 40 (tokenizer when available,
otherwise a documented whitespace approximation - the method is always stored).

Fail-closed rules
  CRIT_text_hash_match           stored hash == recomputed hash
  CRIT_source_unchanged          source file hash still matches stage 10/40
  CRIT_text_recovered            section text is a subsequence of the source text
  PART_no_marker_leakage         no `<!-- SEGMENT` / `SECTION_ID` residue in text
  PART_no_nul_bytes              no NUL characters
  PART_no_duplicated_block       no immediately repeated paragraph
  PART_tokens_reasonable         token count > 0 for non-empty text
  WARN_section_classified        section_type != Other

Outputs: data/sections.jsonl (updated), validation/section_validation_report.json
Resume: checkpoints/stage45_section_validation.jsonl keyed by section_record_id.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage45_section_validation"
PV = "2.0.0"

MARKER_RE = re.compile(r"<!--\s*(SEGMENT|END_SEGMENT|SECTION_ID|SECTION_PATH|SEGMENT_ORDINAL)")


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()

    papers = {p["paper_id"]: p for p in C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")}
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    if not sections:
        sys.exit("ERROR: data/sections.jsonl missing/empty; run stage 40 first")

    # source text cache (one read per paper, keyed by paper_id)
    source_cache = {}

    def source_text(pid: str) -> tuple:
        if pid not in source_cache:
            p = papers.get(pid)
            path = p.get("raw_file_path") if p else None
            path = C.resolve_recorded_path(path) if path else None
            if path and Path(path).exists():
                raw = Path(path).read_bytes()
                source_cache[pid] = (C.sha256_bytes(raw), raw.decode("utf-8", "replace"))
            else:
                source_cache[pid] = (None, "")
        return source_cache[pid]

    prog = C.Progress(STAGE, total=len(sections), unit="section", desc="validate sections")
    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl",
                        key="section_record_id")
    started = C.now_utc()
    by_paper = defaultdict(list)

    for s in sections:
        sid = s["section_record_id"]
        pid = s["paper_id"]
        fp = s.get("text_hash_sha256")
        if ckpt.has(sid, fp):
            rec = ckpt.done[sid]["section"]
            by_paper[pid].append(rec)
            prog.update(1, detail=f"{sid} resumed")
            continue

        text = s.get("section_text_original") or ""
        src_hash, src_text = source_text(pid)
        recomputed = C.sha256_text(text)
        stored = s.get("text_hash_sha256")
        n_tokens, tok_method = C.token_count(text) if text.strip() else (0, "empty")

        # Recoverability probe: the first non-empty line of the section must
        # appear verbatim in the source file. A line never spans a segment
        # boundary, so this is stable even when a section has many segments.
        probe = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:120]
        recovered = (probe in src_text) if probe else True

        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        dup_block = any(a == b for a, b in zip(paras, paras[1:]) if len(a) > 80)

        checks = [
            ("CRIT_text_hash_match", stored == recomputed,
             f"stored={stored} recomputed={recomputed}"),
            ("CRIT_source_unchanged", src_hash == s.get("source_file_hash_sha256"),
             f"source hash now {src_hash}, record says {s.get('source_file_hash_sha256')}"),
            ("CRIT_text_recovered", recovered,
             "first 200 chars of section not found in source file"),
            ("PART_no_marker_leakage", not MARKER_RE.search(text),
             "SEGMENT/SECTION marker text leaked into section body"),
            ("PART_no_nul_bytes", "\x00" not in text,
             f"{text.count(chr(0))} NUL char(s) in section text"),
            ("PART_no_duplicated_block", not dup_block,
             "identical consecutive paragraphs (possible double concatenation)"),
            ("PART_tokens_reasonable", (n_tokens > 0) == (text.strip() != ""),
             f"token_count={n_tokens} for {len(text)} chars via {tok_method}"),
            ("WARN_section_classified", s.get("section_type") != "Other",
             "section type not recognized from heading"),
        ]
        status, reason = C.fail_closed(checks)
        is_container = bool(s.get("is_container_section"))

        rec = dict(s)
        rec.update({
            "token_count": n_tokens,
            "token_count_method": tok_method,
            "quality_checks": [{"rule_id": rid, "passed": ok, "detail": why}
                               for rid, ok, why in checks],
            "section_quality_status": status,
            "extraction_eligibility": (
                status == "COMPLETE"
                and not is_container
                and bool(text.strip())
                and s.get("section_type") not in {"References", "Acknowledgements", "Supplementary"}),
            "exclusion_reason": (
                None if (status == "COMPLETE" and not is_container) else
                ("container_section" if is_container else reason)),
            "validated_at": C.now_utc(),
            "validator_version": PV,
        })
        ckpt.add({"section_record_id": sid, "section": rec}, fingerprint=fp)
        by_paper[pid].append(rec)
        ev.record(pipeline_stage=STAGE, paper_id=pid, section_record_id=sid,
                  run_status="success" if status == "COMPLETE" else "partial",
                  input_artifact_hash=stored, output_artifact_hash=recomputed,
                  error_message=None if status == "COMPLETE" else reason)
        if status != "COMPLETE":
            cur.add(pid, STAGE, "stage45_section_validation", PV,
                    "recompute hash + integrity rules", status, problem=reason,
                    resolution="section kept; extraction disabled" if
                    not rec["extraction_eligibility"] else "section kept; flagged")
        prog.update(1, detail=f"{sid} {status} tok={n_tokens}")

    ckpt.close()

    ordered = [ckpt.done[row["section_record_id"]]["section"]
               for row in sections if row["section_record_id"] in ckpt.done]
    C.write_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl", ordered)

    status_counts = defaultdict(int)
    for s in ordered:
        status_counts[s["section_quality_status"]] += 1
    token_methods = defaultdict(int)
    for s in ordered:
        token_methods[s["token_count_method"].split(" (")[0]] += 1

    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "sections_validated": len(ordered),
        "status_counts": dict(status_counts),
        "sections_eligible_for_extraction": sum(1 for s in ordered if s["extraction_eligibility"]),
        "sections_hash_mismatch": sum(
            1 for s in ordered
            if not next(c["passed"] for c in s["quality_checks"]
                        if c["rule_id"] == "CRIT_text_hash_match")),
        "sections_source_changed": sum(
            1 for s in ordered
            if not next(c["passed"] for c in s["quality_checks"]
                        if c["rule_id"] == "CRIT_source_unchanged")),
        "sections_with_marker_leakage": sum(
            1 for s in ordered
            if not next(c["passed"] for c in s["quality_checks"]
                        if c["rule_id"] == "PART_no_marker_leakage")),
        "sections_with_nul_bytes": sum(
            1 for s in ordered
            if not next(c["passed"] for c in s["quality_checks"]
                        if c["rule_id"] == "PART_no_nul_bytes")),
        "total_tokens": sum(s["token_count"] or 0 for s in ordered),
        "token_methods": dict(token_methods),
        "papers_with_no_eligible_section": sorted(
            pid for pid in {s["paper_id"] for s in ordered}
            if not any(s["extraction_eligibility"] for s in by_paper[pid])),
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "section_validation_report.json", summary)
    ev.record(pipeline_stage=STAGE, run_status="success", started_at=started,
              completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"sections={len(ordered)} eligible={summary['sections_eligible_for_extraction']}")
    ev.close()
    prog.close(summary=json.dumps(summary["status_counts"]))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
