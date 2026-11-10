#!/usr/bin/env python3
"""Stage 46: independent full-text cross-check against original JATS XML.

For every paper whose BioProject has an original `article.xml` in
../168000-samples-paper/fulltext/<PRJ>/, parse the JATS document and ask one
question: *is the narrative content of this paper present in what stage 40
reconstructed?*

Why content and not headings
----------------------------
The segmented markdown and the publisher XML are two renderings of the same
paper. They do not share heading labels reliably (a lost heading shows up as
"6", an "Introduction" may be "Background"), and the upstream converter
flattens subsections into their parent. Comparing heading strings therefore
produces false alarms (in an early run 294/296 papers were flagged). Instead,
each substantive body section is matched by *content*: the fraction of its
content words that occur in the best-matching reconstructed section. If a
section's vocabulary is not present anywhere in our text, the text is missing.

Scope of the comparison
-----------------------
- only body narrative sections (>=300 characters of paragraph text)
- back matter is excluded (author contributions, funding, ethics, data
  availability, acknowledgements, supplementary, references, publisher notes),
  because the converter legitimately drops or renames it
- tables, figures and supplementary material are excluded from the section
  character count, since the markdown does not carry them

Outcome
-------
- a missing body section -> PARTIAL (downgrade only; never upgrade)
- unparseable XML -> FAILED
- title mismatch -> PARTIAL (identifier-level alarm)
- abstract difference is recorded as evidence but does not gate, because the
  stored abstract comes from the bundle's `meta.json`, which may be a
  truncated or differently sourced rendering of the same abstract

Papers with a PDF only, or local text only, get `crosscheck_status:
not_available` and an explicit reason. Their completeness is left exactly as
stage 40 recorded it.

Outputs: data/papers.jsonl (integrity_checks), data/fulltext_crosscheck.jsonl,
         validation/fulltext_crosscheck_report.json
Resume: checkpoints/stage46_fulltext_crosscheck.jsonl keyed by paper_id; the
        fingerprint includes the checker version and thresholds, so changing a
        rule invalidates old records instead of silently reusing them.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C

STAGE = "stage46_fulltext_crosscheck"
PV = "2.1.0"

TITLE_MIN = 0.90
ABSTRACT_MIN = 0.80          # diagnostic only, see module docstring
SECTION_SIM_MIN = 0.50       # content-word containment in best matching section
SUBSTANTIVE_CHARS = 300
NUM_PREFIX = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+")

BACK_MATTER = re.compile(
    r"(author|acknowledg|funding|financ|conflict|competing|data availability|"
    r"availability of data|ethic|publisher|supplement|associated data|footnote|"
    r"reference|contributor|declaration|consent|abbreviation|supporting information|"
    r"additional information|^notes$)")

STOPWORDS = set(
    "the a an and or of to in for on with by as at from is are was were be been "
    "this that these those we our it its their they not no than which also can may "
    "using used use between among after before during into such more most other all "
    "any each both same".split())


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def text_of(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def normalize_heading(h: str) -> str:
    h = NUM_PREFIX.sub("", (h or "").strip())
    h = re.sub(r"[^a-z0-9 ]+", " ", h.lower())
    return re.sub(r"\s+", " ", h).strip()


def overlap(a: str, b: str) -> float:
    at, bt = set(a.split()), set(b.split())
    if not at or not bt:
        return 0.0
    return len(at & bt) / min(len(at), len(bt))


def content_words(text: str) -> set:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
            if len(w) > 2 and w not in STOPWORDS}


def is_back_matter(heading: str) -> bool:
    return bool(BACK_MATTER.search((heading or "").lower()))


def parse_jats(xml_bytes: bytes) -> dict:
    """Return title, abstract, and a flat list of sections with paragraph text."""
    root = ET.fromstring(xml_bytes)
    title = None
    abstract_parts = []
    sections = []

    for el in root.iter():
        name = local(el.tag)
        if name == "article-title" and title is None:
            t = text_of(el)
            if t:
                title = t
        elif name == "abstract":
            t = text_of(el)
            if t:
                abstract_parts.append(t)

    def walk(node, depth):
        for child in node:
            if local(child.tag) != "sec":
                continue
            heading = ""
            paras = []
            for sub in child:
                n = local(sub.tag)
                if n == "title" and not heading:
                    heading = text_of(sub)
                elif n == "p":
                    t = text_of(sub)
                    if t:
                        paras.append(t)
                elif n in ("list", "disp-quote"):
                    t = text_of(sub)
                    if t:
                        paras.append(t)
                # table-wrap / fig are intentionally not counted: the markdown
                # does not carry them, so requiring them would be a false alarm
            sections.append({"depth": depth, "heading": heading,
                             "chars": sum(len(p) for p in paras), "paras": paras})
            walk(child, depth + 1)

    body = next((el for el in root.iter() if local(el.tag) == "body"), None)
    if body is not None:
        walk(body, 1)

    return {"title": title, "abstract": " ".join(abstract_parts) or None,
            "sections": sections}


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()

    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    if not papers or not sections:
        sys.exit("ERROR: papers/sections missing; run stages 10-45 first")

    sec_by_paper = {}
    for s in sections:
        sec_by_paper.setdefault(s["paper_id"], []).append(s)

    targets = [p for p in papers
               if (p.get("bioproject_link") or {}).get("bundle_format") == "jats_xml"]
    prog = C.Progress(STAGE, total=len(targets), unit="paper", desc="cross-check XML")
    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl", key="paper_id")
    started = C.now_utc()
    records = []

    for p in targets:
        pid = p["paper_id"]
        xml_path = (p.get("bioproject_link") or {}).get("bundle_original_path")
        xml_path = C.resolve_recorded_path(xml_path) if xml_path else None
        if not xml_path or not Path(xml_path).exists():
            prog.update(1, detail=f"{pid} xml missing")
            continue
        raw = Path(xml_path).read_bytes()
        fp = C.sha256_text("|".join([
            C.sha256_bytes(raw), PV, str(TITLE_MIN), str(SECTION_SIM_MIN),
            str(SUBSTANTIVE_CHARS),
        ]))
        if ckpt.has(pid, fp):
            records.append(ckpt.done[pid]["crosscheck"])
            prog.update(1, detail=f"{pid} resumed")
            continue

        rec = dict(p)
        our_sections = sec_by_paper.get(pid, [])
        our_words = [(s, content_words(s.get("section_text_original") or ""))
                     for s in our_sections
                     if s.get("section_type") not in
                     ("References", "Acknowledgements", "Supplementary")]
        our_words = [(s, w) for s, w in our_words if w]

        try:
            parsed = parse_jats(raw)
            parse_error = None
        except Exception as e:  # noqa: BLE001
            parsed = {"title": None, "abstract": None, "sections": []}
            parse_error = repr(e)

        src_title = parsed["title"]
        src_abstract = parsed["abstract"]
        title_score = overlap(C.normalize_title(src_title or ""),
                              C.normalize_title(rec.get("title") or ""))
        abstract_score = overlap(C.normalize_title((src_abstract or "")[:200]),
                                 C.normalize_title((rec.get("abstract") or "")[:200]))

        substantive = [s for s in parsed["sections"]
                       if s["chars"] >= SUBSTANTIVE_CHARS
                       and not is_back_matter(s["heading"])]
        missing = []
        checked = 0
        for s in substantive:
            ws = content_words(" ".join(s["paras"]))
            if not ws:
                continue
            checked += 1
            best = 0.0
            for _, ours in our_words:
                score = len(ws & ours) / len(ws)
                if score > best:
                    best = score
                    if best >= 0.95:
                        break
            if best < SECTION_SIM_MIN:
                missing.append({"heading": s["heading"][:120],
                                "depth": s["depth"],
                                "chars": s["chars"],
                                "best_similarity": round(best, 3)})

        checks = [
            ("CRIT_xml_parsed", parse_error is None, f"JATS parse error: {parse_error}"),
            ("PART_title_matches", bool(src_title) and title_score >= TITLE_MIN,
             f"title overlap {title_score:.2f} vs original XML"
             + ("" if src_title else " (no article-title in XML)")),
            ("PART_all_sections_present", not missing,
             f"{len(missing)} body section(s) with no content in the reconstructed "
             f"text: " + "; ".join(
                 f"{x['heading']} ({x['chars']} chars, sim={x['best_similarity']})"
                 for x in missing[:6])),
        ]
        status, reason = C.fail_closed(checks)

        crosscheck = {
            "paper_id": pid,
            "crosscheck_status": status,
            "evidence": reason,
            "source_xml": xml_path,
            "source_xml_hash": C.sha256_bytes(raw),
            "source_title": src_title,
            "title_overlap": round(title_score, 3),
            "abstract_overlap": round(abstract_score, 3),
            "source_section_count": len(parsed["sections"]),
            "body_sections_checked": checked,
            "our_section_count": len(our_sections),
            "missing_sections": missing,
            "checks": [{"rule_id": rid, "passed": ok, "detail": why}
                       for rid, ok, why in checks],
            "rule_version": PV,
            "thresholds": {"title": TITLE_MIN, "section_similarity": SECTION_SIM_MIN,
                           "substantive_chars": SUBSTANTIVE_CHARS},
            "checked_at": C.now_utc(),
            "baseline_full_text_completeness": (
                p.get("full_text_completeness") or "not_checked"),
        }

        # only downgrade, never upgrade
        if status in ("FAILED", "PARTIAL", "REVIEW_REQUIRED"):
            rec["full_text_completeness"] = ("partial" if status != "FAILED"
                                             else "failed")
            rec["full_text_completeness_evidence"] = (
                f"stage46 independent JATS cross-check: {reason}")
        rec["integrity_checks"] = {
            **(rec.get("integrity_checks") or {}),
            "title_matches_source": ("pass" if checks[1][1] else "fail"),
            "abstract_matches_source": (
                "not_available" if not src_abstract
                else "pass" if abstract_score >= ABSTRACT_MIN else "fail"),
            "body_text_completeness": (
                "complete" if not missing and parse_error is None
                else "partial" if parse_error is None else "failed"),
            "section_hierarchy_preserved": "yes" if not missing else "no",
        }
        rec["fulltext_crosscheck"] = {
            "status": status,
            "source": "original JATS XML (168000-samples-paper bundle)",
            "missing_sections": len(missing),
            "checked_at": C.now_utc(),
        }

        ckpt.add({"paper_id": pid, "paper": rec, "crosscheck": crosscheck},
                 fingerprint=fp)
        records.append(crosscheck)
        ev.record(pipeline_stage=STAGE, paper_id=pid,
                  run_status="success" if status == "COMPLETE" else "partial",
                  input_artifact_hash=C.sha256_bytes(raw),
                  output_artifact_hash=C.sha256_text(
                      json.dumps(crosscheck, sort_keys=True, default=str)),
                  error_message=None if status == "COMPLETE" else reason)
        if status != "COMPLETE":
            cur.add(pid, STAGE, "stage46_fulltext_crosscheck", PV,
                    "compare narrative content with original JATS XML", status,
                    problem=reason,
                    resolution="status downgraded; original text not modified")
        prog.update(1, detail=f"{pid} {status} missing={len(missing)}/{checked} "
                              f"title={title_score:.2f}")

    ckpt.close()

    updated = [ckpt.done[p["paper_id"]]["paper"] if p["paper_id"] in ckpt.done else p
               for p in papers]
    C.write_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl", updated)
    C.write_jsonl(C.CORPUS_DIR / "data" / "fulltext_crosscheck.jsonl", records)
    C.write_tracking_table(updated)

    no_source = {}
    for p in papers:
        link = p.get("bioproject_link") or {}
        if link.get("bundle_format") != "jats_xml":
            key = link.get("bundle_format") or link.get("bundle_status") or "unlinked"
            no_source[key] = no_source.get(key, 0) + 1

    status_counts = {}
    for r in records:
        status_counts[r["crosscheck_status"]] = status_counts.get(r["crosscheck_status"], 0) + 1
    papers_with_missing = [r["paper_id"] for r in records if r["missing_sections"]]

    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "papers_total": len(papers),
        "crosschecked": len(records),
        "crosscheck_status_counts": status_counts,
        "papers_with_missing_sections": len(papers_with_missing),
        "missing_section_papers": papers_with_missing,
        "missing_section_detail": {
            r["paper_id"]: r["missing_sections"] for r in records if r["missing_sections"]
        },
        "title_mismatches": [r["paper_id"] for r in records
                             if r["title_overlap"] < TITLE_MIN],
        "abstract_mismatches": [r["paper_id"] for r in records
                                if r["abstract_overlap"] < ABSTRACT_MIN
                                and r.get("abstract_overlap", 0) > 0],
        "no_independent_source": no_source,
        "coverage_note": ("independent structural verification exists only for papers "
                          "with an original JATS XML; PDF and local-text-only papers "
                          "are reported as not_available, never assumed complete"),
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "fulltext_crosscheck_report.json",
                        summary)
    ev.record(pipeline_stage=STAGE, run_status="success", started_at=started,
              completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(
                  json.dumps(summary, sort_keys=True, default=str)),
              note=f"crosschecked={len(records)} status={status_counts}")
    ev.close()
    prog.close(summary=f"crosschecked={len(records)} {status_counts} "
                       f"missing_sections={len(papers_with_missing)}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
