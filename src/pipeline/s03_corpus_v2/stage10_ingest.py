#!/usr/bin/env python3
"""Stage 10: source inventory + hashing (template §3C provenance, §7 document integrity).

Reads every segmented_sections_markdown/HMPAPER_*.md, hashes the exact bytes,
verifies UTF-8 decodability, counts NUL bytes, parses the YAML-ish front matter,
and reconciles the file set against the upstream _conversion_report.json.

Nothing is repaired here. Defects (NUL bytes, missing report rows, unreadable
files, decode errors) are recorded in data/source_inventory.jsonl and pushed
through the fail-closed gate so later stages never mistake "present" for
"complete".

Outputs
  data/source_inventory.jsonl  one row per source file (audit trail)
  data/papers.jsonl            paper skeleton (template §3A–§3D)
  validation/ingest_report.json reconciliation summary

Resume: checkpoints/<stage>.jsonl is keyed by paper_id.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage10_ingest"
PV = "2.0.0"


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    corpus_id = cfg["corpus"]["corpus_id"]
    src_dir = C.REPO_ROOT / "data/segmented_sections_markdown"
    conv_path = src_dir / "_conversion_report.json"

    prog = C.Progress(STAGE, total=None, unit="paper", desc="ingest/hash")
    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl", key="paper_id")
    ev = C.Events(corpus_id, STAGE, PV)
    cur = C.CurationLog()
    started = C.now_utc()

    if not conv_path.exists():
        prog.close("FATAL: conversion report missing")
        sys.exit(f"ERROR: {conv_path} not found")
    conv = json.loads(conv_path.read_text(encoding="utf-8"))
    conv_by_id = {p["corpus_id"]: p for p in conv.get("papers", [])}

    md_files = sorted(src_dir.glob("HMPAPER_*.md"))
    prog.total = len(md_files)
    if prog.bar is not None:
        prog.bar.total = len(md_files)
        prog.bar.refresh()

    skipped = 0
    for f in md_files:
        pid = f.stem
        raw = f.read_bytes()
        file_hash = C.sha256_bytes(raw)
        if ckpt.has(pid, file_hash):
            skipped += 1
            prog.update(1, detail=f"{pid} resumed-from-checkpoint (source unchanged)")
            continue

        nul_count = raw.count(b"\x00")
        decode_ok, decode_err = True, None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            decode_ok, decode_err, text = False, repr(e), raw.decode("utf-8", "replace")

        meta, body_start, fm_found = C.parse_front_matter(text)
        title = (meta.get("title") or "").strip() or None
        bioproject = (meta.get("bioproject") or "").strip() or None
        report = conv_by_id.get(pid)
        total_chars = report.get("total_chars") if report else None
        uncovered = report.get("uncovered_chars") if report else None
        warnings = list(report.get("warnings", [])) if report else []

        # Text integrity and metadata completeness are different questions.
        # A missing front-matter title must never downgrade full-text status.
        text_checks = [
            ("CRIT_source_readable", len(raw) > 0, "zero-byte source file"),
            ("CRIT_utf8_decodable", decode_ok, f"decode error: {decode_err}"),
            ("CRIT_in_conversion_report", report is not None,
             "absent from _conversion_report.json (file set != report set)"),
            ("PART_no_nul_bytes", nul_count == 0,
             f"{nul_count} NUL byte(s) in source; upstream extraction defect, text kept as-is"),
            ("PART_uncovered_chars_zero",
             uncovered == 0, f"conversion reports uncovered_chars={uncovered}"),
            ("PART_no_conversion_warnings", not warnings,
             "upstream conversion warnings: " + "; ".join(warnings)),
        ]
        meta_checks = [
            ("WARN_frontmatter", fm_found, "no YAML front matter"),
            ("WARN_title", bool(title), "no title in front matter"),
        ]
        text_status, text_reason = C.fail_closed(text_checks)
        meta_status, meta_reason = C.fail_closed(meta_checks)
        status = C.worst_status(text_status, meta_status)
        reason = "; ".join(x for x in (text_reason, meta_reason) if x)

        inventory = {
            "paper_id": pid,
            "source_file_path": str(f),
            "source_file_name": f.name,
            "source_file_hash_sha256": file_hash,
            "source_bytes": len(raw),
            "source_characters": len(text),
            "utf8_decodable": decode_ok,
            "utf8_error": decode_err,
            "nul_byte_count": nul_count,
            "frontmatter_found": fm_found,
            "frontmatter_keys": sorted(k for k in meta if not k.startswith("_")),
            "frontmatter_parser": ("line_based_fallback" if meta.get("_yaml_fallback")
                                   else "yaml"),
            "bioproject": bioproject,
            "title": title,
            "in_conversion_report": report is not None,
            "conversion_total_chars": total_chars,
            "conversion_covered_chars": report.get("covered_chars") if report else None,
            "conversion_uncovered_chars": uncovered,
            "conversion_sections": report.get("sections") if report else None,
            "conversion_warnings": warnings,
            "conversion_source_path": report.get("source") if report else None,
            "source_path_note": (
                "conversion report records a different absolute path; local file is authoritative"
                if report and report.get("source") and not str(report["source"]).endswith(f.name)
                else None),
            "ingest_status": status,
            "ingest_evidence": reason,
            "text_status": text_status,
            "text_evidence": text_reason,
            "metadata_status": meta_status,
            "metadata_evidence": meta_reason,
            "ingested_at": C.now_utc(),
        }

        # ---- paper skeleton: template §3A–§3D ----
        paper = {
            "corpus_id": corpus_id,
            "paper_id": pid,
            "schema_version": "1.0.0",
            "processing_status": "source_acquired",
            "full_text_completeness": C.FT_FROM_INTERNAL.get(text_status, "not_checked"),
            "full_text_availability": ("available_full_text" if len(raw) > 0
                                       else "unavailable"),
            "full_text_parse_status": None,
            "full_text_completeness_evidence": text_reason,
            "completeness_checks": [{"rule_id": rid, "passed": ok, "detail": why}
                                    for rid, ok, why in text_checks],
            "metadata_review_status": meta_status,
            "metadata_checks": [{"rule_id": rid, "passed": ok, "detail": why}
                                for rid, ok, why in meta_checks],
            "source_title_present": bool(title),
            "annotation_status": "not_started",
            "reviewer": None,
            "review_date": None,
            "curation_notes": None,
            "title": title,
            "DOI": None,
            "PMID": None,
            "PMCID": None,
            "authors": [],
            "journal": None,
            "publication_year": None,
            "publication_type": None,
            "language": "en",
            "abstract": None,
            "keywords": [],
            "source_database": "segmented_sections_markdown (internal; upstream papers_txt)",
            "source_url": None,
            "retrieval_date": C.now_utc()[:10],
            "license_name": None,
            "license_url": None,
            "reuse_permission_checked": "unclear",
            "original_pdf_path": None,
            "original_xml_path": None,
            "extracted_text_path": str(f),
            "supplementary_file_paths": [],
            "raw_file_path": str(f),
            "raw_file_hash": file_hash,
            "extraction_tool": "upstream PDF→text→SEGMENT/SECTION conversion (see _conversion_report.json)",
            "extraction_date": None,
            "text_version_id": f"sha256:{file_hash}",
            "bioproject": bioproject,
            "human_microbiome_relevance": "unclear",
            "inclusion_decision": "pending",
            "eligibility_status": "pending",
            "exclusion_reason": None,
            "protocol_version": "inclusion-protocol-v1",
            "duplicate_group_id": None,
            "canonical_paper_id": pid,
            "is_canonical": True,
            "integrity_checks": {
                "title_matches_source": "not_checked",
                "abstract_matches_source": "not_checked",
                "body_text_completeness": C.FT_FROM_INTERNAL.get(text_status, "not_checked"),
                "section_hierarchy_preserved": "not_checked",
                "tables_checked": "not_checked",
                "figure_captions_checked": "not_checked",
                "supplementary_materials_checked": "not_checked",
                "references_retained": "not_checked",
                "known_extraction_problems": (
                    (f"{nul_count} NUL bytes; " if nul_count else "")
                    + ("; ".join(warnings) if warnings else "")) or None,
            },
            "source_characters": len(text),
            "conversion_uncovered_chars": uncovered,
            "source_integrity": {
                "nul_bytes": nul_count,
                "non_utf8_bytes": 0 if decode_ok else len(raw),
                "encoding_status": ("clean" if decode_ok and nul_count == 0
                                    else "defects_present"),
            },
        }

        ckpt.add({"paper_id": pid, "inventory": inventory, "paper": paper},
                 fingerprint=file_hash)
        prog.update(1, detail=f"{pid} text={text_status} meta={meta_status} "
                              f"nul={nul_count} warn={len(warnings)}")
        ev.record(pipeline_stage=STAGE, paper_id=pid,
                  run_status="success" if status == "COMPLETE" else "partial",
                  input_artifact_hash=file_hash,
                  output_artifact_hash=C.sha256_text(json.dumps(inventory, sort_keys=True, default=str)),
                  error_message=None if status == "COMPLETE" else reason)
        if text_status != "COMPLETE":
            cur.add(pid, STAGE, "stage10_ingest", PV,
                    "hash+decode+reconcile (text)", text_status, problem=text_reason,
                    resolution="recorded for downstream fail-closed handling; source not modified")
        if meta_status != "COMPLETE":
            cur.add(pid, STAGE, "stage10_ingest", PV,
                    "front-matter completeness", meta_status, problem=meta_reason,
                    resolution="source front matter lacks a title; stage 20 attempts an "
                               "internal-map recovery and records its provenance")

    ckpt.close()

    # ordered emission (checkpoint may cover a resumed subset)
    inventory = [ckpt.done[f.stem]["inventory"] for f in md_files if f.stem in ckpt.done]
    papers = [ckpt.done[f.stem]["paper"] for f in md_files if f.stem in ckpt.done]
    C.write_jsonl(C.CORPUS_DIR / "data" / "source_inventory.jsonl", inventory)
    C.write_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl", papers)

    disk_ids = {f.stem for f in md_files}
    report_ids = set(conv_by_id)
    missing_files = sorted(report_ids - disk_ids)
    orphan_files = sorted(disk_ids - report_ids)

    def count(pred):
        return sum(1 for r in inventory if pred(r))

    summary = {
        "stage": STAGE,
        "pipeline_version": PV,
        "generated_at": C.now_utc(),
        "source_dir": str(src_dir),
        "conversion_report": str(conv_path),
        "papers_on_disk": len(md_files),
        "papers_in_conversion_report": len(report_ids),
        "resumed_from_checkpoint": skipped,
        "reconciled": len(missing_files) == 0 and len(orphan_files) == 0,
        "missing_files": missing_files,
        "orphan_files": orphan_files,
        "files_with_nul_bytes": count(lambda r: r["nul_byte_count"] > 0),
        "nul_byte_total": sum(r["nul_byte_count"] for r in inventory),
        "files_not_utf8": count(lambda r: not r["utf8_decodable"]),
        "files_without_frontmatter": count(lambda r: not r["frontmatter_found"]),
        "files_without_title": count(lambda r: not r["title"]),
        "files_with_conversion_warnings": count(lambda r: bool(r["conversion_warnings"])),
        "conversion_warning_total": sum(len(r["conversion_warnings"]) for r in inventory),
        "conversion_uncovered_chars_total": sum(
            (r["conversion_uncovered_chars"] or 0) for r in inventory),
        "status_counts": {
            s: count(lambda r, s=s: r["ingest_status"] == s)
            for s in ("COMPLETE", "PARTIAL", "FAILED", "REVIEW_REQUIRED")},
        "text_status_counts": {
            s: count(lambda r, s=s: r["text_status"] == s)
            for s in ("COMPLETE", "PARTIAL", "FAILED", "REVIEW_REQUIRED")},
        "metadata_status_counts": {
            s: count(lambda r, s=s: r["metadata_status"] == s)
            for s in ("COMPLETE", "PARTIAL", "FAILED", "REVIEW_REQUIRED")},
        "defect_files": {r["paper_id"]: {
            "nul_bytes": r["nul_byte_count"],
            "warnings": r["conversion_warnings"],
            "text_status": r["text_status"],
            "metadata_status": r["metadata_status"],
            "title_missing": not r["title"],
        } for r in inventory if r["ingest_status"] != "COMPLETE"},
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "ingest_report.json", summary)

    prog.update(0, detail=f"reconciled={summary['reconciled']} "
                          f"nul_files={summary['files_with_nul_bytes']} "
                          f"warn_files={summary['files_with_conversion_warnings']} "
                          f"text={summary['text_status_counts']} "
                          f"meta={summary['metadata_status_counts']}")
    ev.record(pipeline_stage=STAGE, run_status="success",
              started_at=started, completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True, default=str)),
              note=f"papers={len(papers)} reconciled={summary['reconciled']}")
    ev.close()
    prog.close(summary=json.dumps(summary["status_counts"]))

    if not summary["reconciled"]:
        sys.exit(f"REVIEW_REQUIRED: file set != conversion report set "
                 f"(missing={missing_files}, orphan={orphan_files})")


if __name__ == "__main__":
    main()
