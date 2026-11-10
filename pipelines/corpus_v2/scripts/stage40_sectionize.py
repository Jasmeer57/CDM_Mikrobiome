#!/usr/bin/env python3
"""Stage 40: sectionize segmented_sections_markdown into corpus records.

Source: ~/Microbiome-CDM/segmented_sections_markdown/HMPAPER_*.md
Each .md has YAML front-matter and SEGMENT blocks:
  <!-- SEGMENT: SEG_xxxxx -->
  <!-- SECTION_ID: sec_xxx / sec_gap_xxx / sec_preface -->
  <!-- SECTION_PATH: original heading (may be empty) -->
  <!-- SEGMENT_ORDINAL_WITHIN_SECTION: N -->
  ... text ...
  <!-- END_SEGMENT: SEG_xxxxx -->

Full-text integrity (fail-closed):
- Every paper's chars are validated against the upstream conversion report
  (_conversion_report.json: covered_chars, uncovered_chars) - evidence, not assumption.
- Segment markers must be balanced; concatenated segment text is re-hashed.
- section/segment coverage ratio computed and folded into the status:
  CRIT uncovered>0 -> FAILED; PART coverage<1.0 -> PARTIAL; else COMPLETE.
- Hierarchy is derived from numbered headings only when the source has them;
  otherwise hierarchy_status=flat_in_source. Nesting is never invented.

Metadata written by stage 10/20/30 is preserved: stage 40 merges its text and
coverage fields into the existing papers.jsonl record (it never re-creates it).

Outputs
  data/papers.jsonl     updated in place (text/coverage fields only)
  data/sections.jsonl   section records (template §3F)
  data/segments.jsonl   segment-level audit trail
  validation/reconciliation_report.json

Resume: checkpoints/stage40_sectionize.jsonl keyed by paper_id.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C

STAGE = "stage40_sectionize"
PV = "2.0.0"

SEG_RE = re.compile(
    r"<!-- SEGMENT: (?P<seg>SEG_\d+) -->\n"
    r"(?:<!-- SECTION_ID: (?P<sec_id>[^>]+) -->\n)?"
    r"(?:<!-- SECTION_PATH: (?P<sec_path>[^>]*?) -->\n)?"
    r"(?:<!-- SEGMENT_ORDINAL_WITHIN_SECTION: (?P<ord>\d+) -->\n)?\n?"
    r"(?P<text>.*?)"
    r"<!-- END_SEGMENT: (?P=seg) -->", re.S)

NUM_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<rest>.+)$")
CONTAINER_TYPES = {"References", "Acknowledgements", "Supplementary"}
CORE_TYPES = {"Abstract", "Introduction", "Methods", "Results", "Discussion"}


def count_stats(text: str) -> dict:
    paras = [p for p in text.split("\n\n") if p.strip()]
    sents = re.split(r"(?<=[.!?])\s+", text)
    return {
        "word_count": len(re.findall(r"\S+", text)),
        "character_count": len(text),
        "paragraph_count": len(paras),
        "sentence_count": sum(1 for s in sents if s.strip()),
        "counting_convention": "words=whitespace-separated; sentences=[.!?]+space",
    }


def parse_paper(md_path: Path) -> dict:
    raw = md_path.read_text(encoding="utf-8")
    meta, body_start, head_found = C.parse_front_matter(raw)
    body = raw[body_start:]
    segs = []
    for m in SEG_RE.finditer(body):
        txt = m.group("text")  # verbatim: no synthetic whitespace is inserted
        ordn = m.group("ord")
        segs.append({
            "seg_id": m.group("seg"),
            "sec_id": (m.group("sec_id") or "").strip(),
            "sec_path": (m.group("sec_path") or "").strip(),
            "ordinal": int(ordn) if ordn else None,
            "text": txt,
        })
    opens = re.findall(r"<!-- SEGMENT: (SEG_\d+) -->", body)
    closes = re.findall(r"<!-- END_SEGMENT: (SEG_\d+) -->", body)
    balance_errors = [] if opens == closes else [f"open_close_mismatch:{len(opens)}vs{len(closes)}"]
    return {"meta": meta, "body": body, "segments": segs,
            "balance_errors": balance_errors, "head_found": head_found}


def heading_depth(heading: str) -> tuple:
    """Return (depth, display_heading). Numbered headings give explicit depth."""
    if not heading:
        return 0, ""
    m = NUM_RE.match(heading)
    if m:
        return m.group("num").count(".") + 1, heading
    return 0, heading


def build_hierarchy(group_order: list) -> dict:
    """Map section index -> (parent_index, heading_path, status).

    Only numbered headings create nesting. An unnumbered heading is top level
    and resets the numbering stack, so a stray `Introduction` never becomes a
    child of the previous numbered section.
    """
    out = {}
    stack = []  # list of (depth, index)
    for idx, heading in group_order:
        depth, _ = heading_depth(heading)
        if depth == 0:
            stack = []
            out[idx] = {"parent_index": None, "heading_path": [heading] if heading else [],
                        "depth": 0}
            continue
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1] if stack else None
        path = [group_order[i][1] for _, i in stack] + [heading]
        out[idx] = {"parent_index": parent, "heading_path": path, "depth": depth}
        stack.append((depth, idx))
    return out


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()

    src_dir = C.REPO_ROOT / "data/segmented_sections_markdown"
    conv_path = src_dir / "_conversion_report.json"
    conv = json.loads(conv_path.read_text(encoding="utf-8"))
    conv_by_id = {p["corpus_id"]: p for p in conv.get("papers", [])}

    existing = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    if not existing:
        sys.exit("ERROR: data/papers.jsonl missing/empty; run stage 10 (and 20/30) first")
    papers_by_id = {p["paper_id"]: p for p in existing}

    md_files = sorted(src_dir.glob("HMPAPER_*.md"))
    prog = C.Progress(STAGE, total=len(md_files), unit="paper", desc="sectionize")
    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl", key="paper_id")
    started = C.now_utc()

    for f in md_files:
        pid = f.stem
        raw_hash = C.sha256_bytes(f.read_bytes())
        if ckpt.has(pid, raw_hash):
            prog.update(1, detail=f"{pid} resumed-from-checkpoint (source unchanged)")
            continue

        r = parse_paper(f)
        meta = r["meta"]
        conv_rec = conv_by_id.get(pid)

        # ---- group segments into sections, preserving document order ----
        order, groups = [], {}
        for s in r["segments"]:
            key = s["sec_id"] or f"path:{s['sec_path'] or 'NONE'}"
            if key not in groups:
                order.append(key)
                groups[key] = {"texts": [], "ordinals": [], "segs": [],
                               "heading": s["sec_path"] or ""}
            groups[key]["texts"].append(s["text"])
            groups[key]["ordinals"].append(s["ordinal"])
            groups[key]["segs"].append(s["seg_id"])
            if s["sec_path"] and not groups[key]["heading"]:
                groups[key]["heading"] = s["sec_path"]

        hierarchy = build_hierarchy([(i, groups[k]["heading"]) for i, k in enumerate(order)])
        paper_numbered = any(heading_depth(groups[k]["heading"])[0] > 0 for k in order)
        hierarchy_status = "derived_from_numbering" if paper_numbered else "flat_in_source"

        segrecs, sections = [], []
        seg_chars = 0
        for i, key in enumerate(order):
            g = groups[key]
            text = "".join(g["texts"])
            st = count_stats(text)
            sec_id = None if key.startswith("path:") else key
            heading = g["heading"] or None
            ftype = C.classify_section(heading or "")
            is_container = ftype in CONTAINER_TYPES

            checks = [
                ("CRIT_nonempty_text", st["character_count"] > 0, "no text"),
                ("CRIT_marker_balance", not r["balance_errors"], ";".join(r["balance_errors"])),
                ("PART_ordered_ordinals",
                 [o for o in g["ordinals"] if o is not None] ==
                 sorted(o for o in g["ordinals"] if o is not None),
                 f"ordinals out of order: {g['ordinals']}"),
                ("WARN_classified_section", ftype != "Other", "unclassified heading"),
            ]
            status, reason = C.fail_closed(checks)

            # empty preamble/gap blocks are legitimate but never extractable
            if st["character_count"] == 0:
                status = "REVIEW_REQUIRED" if status == "COMPLETE" else status
                reason = (reason + "; " if reason else "") + "empty_section"

            eligible = (status in ("COMPLETE", "PARTIAL") and not is_container
                        and st["character_count"] > 0)
            if ftype in CORE_TYPES and status != "COMPLETE":
                eligible = False

            sid = f"{pid}:sec:{i:03d}"
            sections.append({
                "section_record_id": sid,
                "paper_id": pid,
                "section_id_original": sec_id,
                "section_name_original": heading,
                "section_name_normalized": ftype,
                "section_type": ftype,
                "heading_path": hierarchy[i]["heading_path"],
                "section_order": i,
                "parent_section_id": (f"{pid}:sec:{hierarchy[i]['parent_index']:03d}"
                                      if hierarchy[i]["parent_index"] is not None else None),
                "hierarchy_status": hierarchy_status,
                "section_text_original": text,
                "section_text_cleaned": None,
                "cleaning_operations": [],
                "paragraph_count": st["paragraph_count"],
                "sentence_count": st["sentence_count"],
                "character_count": st["character_count"],
                "word_count": st["word_count"],
                "token_count": None,
                "token_count_method": "not_computed:stage45",
                "counting_convention": st["counting_convention"],
                "language": "en",
                "language_status": "assumed_from_source",
                "text_hash_sha256": C.sha256_text(text),
                "source_file_hash_sha256": raw_hash,
                "source_location": f"segmented_sections_markdown/{f.name}#section={i}",
                "source_char_start": None,
                "source_char_end": None,
                "offset_convention": "no character offsets in source; segment ids used instead",
                "segment_ids": g["segs"],
                "parsing_status": status,
                "section_quality_status": status,
                "quality_checks": [{"rule_id": rid, "passed": ok, "detail": why}
                                   for rid, ok, why in checks],
                "extraction_eligibility": eligible,
                "exclusion_reason": None if eligible else (
                    "container_section" if is_container else (reason or "not_eligible")),
                "is_container_section": is_container,
                "llm_enrichment": None,
            })
            for seg_id, seg_text, ordn in zip(g["segs"], g["texts"], g["ordinals"]):
                sst = count_stats(seg_text)
                seg_chars += sst["character_count"]
                segrecs.append({
                    "segment_record_id": f"{pid}:{seg_id}",
                    "paper_id": pid,
                    "section_record_id": sid,
                    "section_path_original": heading,
                    "segment_ordinal": ordn,
                    "text_hash_sha256": C.sha256_text(seg_text),
                    "source_file_hash_sha256": raw_hash,
                    "word_count": sst["word_count"],
                    "character_count": sst["character_count"],
                    "paragraph_count": sst["paragraph_count"],
                })

        # ---- paper-level fail-closed completeness ----
        conv_total = conv_rec.get("total_chars") if conv_rec else None
        uncovered = conv_rec.get("uncovered_chars", -1) if conv_rec else -1
        coverage = (seg_chars / conv_total) if conv_total else None
        chars_delta = (seg_chars - conv_total) if conv_total else None
        pchecks = [
            ("CRIT_conversion_record_exists", conv_rec is not None, "missing from conversion report"),
            ("CRIT_no_uncovered_chars", uncovered == 0, f"conversion uncovered_chars={uncovered}"),
            ("CRIT_marker_balance", not r["balance_errors"], ";".join(r["balance_errors"])),
            ("CRIT_segments_present", len(r["segments"]) > 0, "no segments parsed"),
            ("PART_fulltext_coverage", coverage is not None and coverage >= 0.999,
             f"segment chars {seg_chars} vs source chars {conv_total} "
             f"(ratio {coverage}, delta {chars_delta})"),
            ("WARN_core_sections_present",
             any(s["section_type"] in CORE_TYPES for s in sections), "no core sections"),
        ]
        pstatus, preason = C.fail_closed(pchecks)
        n_complete = sum(1 for s in sections if s["parsing_status"] == "COMPLETE")

        paper = dict(papers_by_id.get(pid, {}))
        paper.update({
            "paper_id": pid,
            "title": paper.get("title") or meta.get("title"),
            "bioproject": paper.get("bioproject") or meta.get("bioproject"),
            "raw_file_path": str(f),
            "raw_file_hash": raw_hash,
            "text_version_id": f"sha256:{raw_hash}",
            "processing_status": ("text_extracted" if pstatus != "FAILED"
                                  else paper.get("processing_status", "source_acquired")),
            "full_text_availability": ("available_full_text" if sections else
                                       "unavailable"),
            "full_text_parse_status": pstatus,
            "full_text_completeness": C.FT_FROM_INTERNAL.get(pstatus, "not_checked"),
            "full_text_completeness_evidence": (
                f"{preason} | source_chars={conv_total} covered="
                f"{conv_rec.get('covered_chars') if conv_rec else None} "
                f"segment_chars={seg_chars} ratio={coverage} delta_chars={chars_delta}"),
            "sections_discovered": len(sections),
            "sections_complete": n_complete,
            "sections_needing_review": len(sections) - n_complete,
            "section_hierarchy_status": hierarchy_status,
            "section_count_evidence": {
                "source_report_sections": conv_rec.get("sections") if conv_rec else None,
                "parsed_sections": len(sections),
                "segments": len(r["segments"]),
            },
            "integrity_checks": {
                **paper.get("integrity_checks", {}),
                "body_text_completeness": C.FT_FROM_INTERNAL.get(pstatus, "not_checked"),
                "section_hierarchy_preserved": ("yes" if hierarchy_status == "derived_from_numbering"
                                               else "not_checked"),
            },
        })

        ckpt.add({"paper_id": pid, "paper": paper, "sections": sections, "segments": segrecs},
                 fingerprint=raw_hash)
        prog.update(1, detail=f"{pid} {pstatus} sections={len(sections)} "
                              f"segments={len(segrecs)} chars={seg_chars}")
        ev.record(pipeline_stage=STAGE, paper_id=pid,
                  run_status="success" if pstatus != "FAILED" else "failed",
                  error_message=None if pstatus == "COMPLETE" else preason,
                  input_artifact_hash=raw_hash,
                  output_artifact_hash=C.sha256_text(
                      "".join(s["text_hash_sha256"] for s in sections)))
        if pstatus != "COMPLETE":
            cur.add(pid, STAGE, "stage40_sectionize", PV, "parse+coverage", pstatus,
                    problem=preason, resolution="kept as recorded; flagged for review")

    ckpt.close()

    papers = [ckpt.done[f.stem]["paper"] for f in md_files if f.stem in ckpt.done]
    sections = [s for f in md_files if f.stem in ckpt.done for s in ckpt.done[f.stem]["sections"]]
    segrecs = [s for f in md_files if f.stem in ckpt.done for s in ckpt.done[f.stem]["segments"]]

    C.write_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl", papers)
    C.write_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl", sections)
    C.write_jsonl(C.CORPUS_DIR / "data" / "segments.jsonl", segrecs)

    def n_status(rows, key, val):
        return sum(1 for r in rows if r.get(key) == val)

    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "papers_total": len(papers),
        "papers_complete": n_status(papers, "full_text_parse_status", "COMPLETE"),
        "papers_partial": n_status(papers, "full_text_parse_status", "PARTIAL"),
        "papers_failed": n_status(papers, "full_text_parse_status", "FAILED"),
        "papers_review_required": n_status(papers, "full_text_parse_status", "REVIEW_REQUIRED"),
        "papers_available_full_text": sum(1 for p in papers if p.get("sections_discovered")),
        "sections_discovered": len(sections),
        "sections_complete": n_status(sections, "parsing_status", "COMPLETE"),
        "sections_needing_review": sum(1 for s in sections if s.get("parsing_status") != "COMPLETE"),
        "sections_eligible_for_extraction": sum(1 for s in sections if s.get("extraction_eligibility")),
        "container_sections_excluded": sum(1 for s in sections if s.get("is_container_section")),
        "segment_records": len(segrecs),
        "total_characters": sum(s.get("character_count", 0) for s in sections),
        "hierarchy_derived_from_numbering": sum(
            1 for p in papers if p.get("section_hierarchy_status") == "derived_from_numbering"),
        "hierarchy_flat_in_source": sum(
            1 for p in papers if p.get("section_hierarchy_status") == "flat_in_source"),
        "message": "availability != parse != verified completeness; see per-paper status fields",
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "reconciliation_report.json", summary)
    ev.record(pipeline_stage=STAGE, run_status="success", started_at=started,
              completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"papers={len(papers)} sections={len(sections)} segments={len(segrecs)}")
    ev.close()
    prog.close(summary=json.dumps({k: summary[k] for k in
                                   ("papers_complete", "papers_partial", "papers_failed",
                                    "sections_discovered")}))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
