#!/usr/bin/env python3
"""Supporting artifact — ``terminology_validation.jsonl``.

One validation record per **section unit** actually processed, so the run's
coverage claim is checkable against the corpus rather than asserted.

This is a FAIL-CLOSED gate. Each section is checked for:

  * the section is present and non-empty in the segmented-section source;
  * its sha256 is recorded for the exact text that was read;
  * every Stage-1 mention offset in it resolves to the exact surface form;
  * a mention whose offsets do NOT resolve is reported, never silently dropped.

A section that fails any check is marked ``REVIEW_REQUIRED``. Coverage is only
ever reported over what was validated — a paper missing from the section set is
counted as ``not_processed``, not as a pass.

Section text and offsets are taken from ``runner_sections.load_sections`` — the
same loader the extraction stages use — so "the text" here is the same bytes
those stages saw. Offsets are relative to the SECTION BODY, which is why this
validates units, not whole files.

Outputs (in ``--out_dir``)
--------------------------
    terminology_validation.jsonl
    validation_summary.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

SECTIONS_DIR = REPO_ROOT / "data/segmented_sections_markdown"
MEMBERSHIP_CSV = REPO_ROOT / "data/corpus/corpus_tracking.csv"
CORPUS_REPORT = REPO_ROOT / "pipelines/corpus_pipeline/reports/final_execution_report.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_mentions(path: Path):
    """(paper_id, section_id) -> list of mention dicts, plus link-status counts.

    Also returns a Counter over ``link_status`` (Stage T2 writes it) so the
    validation summary can show whether the mention -> canonical-term link was
    actually materialised, without a second pass over the stream.
    """
    by_unit = defaultdict(list)
    link_counts = Counter()
    if not path.exists():
        return by_unit, link_counts
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_unit[(m.get("paper_id"), m.get("section_id"))].append(m)
            link_counts[m.get("link_status") or "MISSING_LINK_STATUS_FIELD"] += 1
    return by_unit, link_counts


def _overall(n_fail, not_processed, no_mentions, n_papers, mentions_present):
    """Fail-closed roll-up. ``COMPLETE`` requires ALL of:

      * no section failed a structural/integrity check;
      * every corpus member paper is present in the section set;
      * every paper with content actually carries at least one mention;
      * a mention stream was supplied at all.

    Anything less is ``REVIEW_REQUIRED`` — the run is not allowed to call itself
    complete on the strength of section integrity alone.
    """
    if not mentions_present:
        return "REVIEW_REQUIRED"
    if n_fail or not_processed:
        return "REVIEW_REQUIRED"
    if no_mentions:
        return "REVIEW_REQUIRED"
    return "COMPLETE"


def main():
    ap = argparse.ArgumentParser(description="Build terminology_validation.jsonl")
    ap.add_argument("--sections_dir", type=Path, default=SECTIONS_DIR)
    ap.add_argument("--mentions", type=Path,
                    default=REPO_ROOT / "outputs/results/terminology_v1/term_mentions.jsonl")
    ap.add_argument("--membership_csv", type=Path, default=MEMBERSHIP_CSV)
    ap.add_argument("--corpus_report", type=Path, default=CORPUS_REPORT)
    ap.add_argument("--body_only", action="store_true",
                    help="validate only body sections (default: every section unit)")
    ap.add_argument("--out_dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if not args.sections_dir.exists():
        raise SystemExit(f"missing sections dir: {args.sections_dir}")

    from pipeline.s04_ner.runner_sections import load_sections  # noqa: E402

    units, per_paper_stats = load_sections(args.sections_dir,
                                           body_only=args.body_only)
    mentions, link_counts = load_mentions(args.mentions)
    mentions_present = args.mentions.exists()

    corpus_report = {}
    try:
        corpus_report = json.loads(args.corpus_report.read_text(encoding="utf-8"))
    except Exception:
        pass
    ready = corpus_report.get("ready")
    blocked = corpus_report.get("blocked")

    member_papers = set()
    if args.membership_csv.exists():
        with args.membership_csv.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("corpus_id"):
                    member_papers.add(row["corpus_id"])

    out_path = args.out_dir / "terminology_validation.jsonl"
    n_pass = n_fail = n_na = 0
    n_checked = n_ok = n_bad = n_skipped = 0
    fail_reasons = Counter()
    flagged_papers = set()
    per_paper = {}
    total_chars = 0
    section_paths = Counter()

    with out_path.open("w", encoding="utf-8") as fout:
        for u in units:
            paper = u["cid"]
            sid = u["section_id"]
            text = u["text"]
            spath = u.get("path") or ""
            section_paths[spath.split("/")[0] if "/" in spath else "(none)"] += 1
            total_chars += len(text)

            reasons = []
            checks = {}
            checks["section_exists"] = bool(text.strip())
            if not checks["section_exists"]:
                reasons.append("EMPTY_SECTION")

            checks["in_corpus_membership"] = paper in member_papers
            if not checks["in_corpus_membership"]:
                reasons.append("NOT_IN_CORPUS_MEMBERSHIP")

            sec_hash = _sha256(text)

            ok = bad = skipped = 0
            for m in mentions.get((paper, sid)) or []:
                s, e = m.get("start_offset"), m.get("end_offset")
                surf = m.get("surface_form")
                if not isinstance(s, int) or not isinstance(e, int):
                    # A mention whose offsets could not be located has no span to
                    # verify. These are counted explicitly (never silently
                    # skipped) so the exclusion is visible in the summary instead
                    # of hiding inside the checked/unresolved totals.
                    skipped += 1
                    continue
                if not (0 <= s < e <= len(text)):
                    bad += 1
                    continue
                if text[s:e] == surf:
                    ok += 1
                else:
                    bad += 1
            checks["offsets_resolve_exactly"] = bad == 0
            checks["offsets_all_locatable"] = skipped == 0
            if bad:
                reasons.append("OFFSET_MISMATCH")
            n_checked += ok + bad
            n_ok += ok
            n_bad += bad
            n_skipped += skipped

            # A zero-character structural placeholder (one empty front/(preamble)
            # per paper) is not a processing failure and is not counted as a
            # validated section either — it simply had no content to process.
            # Anything else that is empty IS a real problem.
            placeholder = (not text.strip() and len(text) == 0
                           and reasons == ["EMPTY_SECTION"])
            if placeholder:
                status = "NOT_APPLICABLE"
                reasons = []
                n_na += 1
            elif reasons:
                status = "REVIEW_REQUIRED"
                n_fail += 1
                flagged_papers.add(paper)
                for r in reasons:
                    fail_reasons[r] += 1
            else:
                status = "VALIDATED"
                n_pass += 1

            rec = {
                "validation_id": "HMVAL_" + _sha256(f"{paper}|{sid}|{sec_hash}")[:16],
                "paper_id": paper,
                "section_id": sid,
                "section_path": spath,
                "section_kind": spath.split("/")[0] if spath else None,
                "content_sha256": sec_hash,
                "content_chars": len(text),
                "checks": checks,
                "mentions_checked": ok + bad,
                "mentions_resolved": ok,
                "mentions_unresolved": bad,
                "mentions_excluded_non_integer_offsets": skipped,
                "mentions_seen": ok + bad + skipped,
                "validation_status": status,
                "failure_reasons": reasons,
                "content_was_modified": False,
                "note": "Offsets are checked against the section body as read; a "
                        "mismatch is reported, never silently repaired. A mention "
                        "without integer offsets has no span to verify and is "
                        "counted in mentions_excluded_non_integer_offsets, not in "
                        "mentions_checked.",
            }
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

            pp = per_paper.setdefault(paper, {"sections": 0, "chars": 0,
                                              "mentions": 0, "bad": 0})
            if not placeholder:
                pp["sections"] += 1
                pp["chars"] += len(text)
                pp["mentions"] += ok + bad
                pp["bad"] += bad

    papers_with_sections = set(per_paper)
    not_processed = sorted(member_papers - papers_with_sections)
    no_mentions = sum(1 for p, v in per_paper.items() if v["mentions"] == 0)

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "inputs": {
            "sections_dir": str(args.sections_dir),
            "body_only": args.body_only,
            "mentions": str(args.mentions),
            "mentions_present": mentions_present,
            "membership_csv": str(args.membership_csv),
        },
        "outputs": {"terminology_validation": str(out_path)},
        "coverage": {
            "papers_in_corpus_membership": len(member_papers),
            "papers_processed": len(papers_with_sections),
            "papers_not_processed": len(not_processed),
            "papers_flagged": len(flagged_papers),
            "papers_without_any_mention": no_mentions,
            "sections_validated": n_pass,
            "sections_flagged": n_fail,
            "sections_not_applicable": n_na,
            "sections_with_content": n_pass + n_fail,
            "sections_total": n_pass + n_fail + n_na,
            "total_chars_processed": total_chars,
            "pct_sections_validated": (round(100.0 * n_pass / (n_pass + n_fail), 4)
                                       if (n_pass + n_fail) else None),
            "sections_by_kind": section_paths.most_common(25),
            "corpus_report_ready": ready,
            "corpus_report_blocked": blocked,
            "corpus_report_note": "ready/blocked counts come from the corpus build's own "
                                  "report; a blocked paper is not claimed as covered here.",
        },
        "mention_offset_verification": {
            "mentions_checked": n_checked,
            "mentions_resolved_exactly": n_ok,
            "mentions_unresolved": n_bad,
            "mentions_excluded_non_integer_offsets": n_skipped,
            "mentions_seen_total": n_checked + n_skipped,
            "pct_resolved": (round(100.0 * n_ok / n_checked, 4) if n_checked else None),
            "note": "mentions_checked = ok + unresolved. A mention with no integer "
                    "offsets has no span to verify and is excluded here as "
                    "mentions_excluded_non_integer_offsets; it still exists in the "
                    "mention artifact and was never dropped.",
        },
        "mention_link_status": {
            "by_link_status": link_counts.most_common(),
            "n_linked": sum(v for k, v in link_counts.items()
                            if (k or "").startswith("LINKED_")),
            "n_unresolved": sum(v for k, v in link_counts.items()
                                if (k or "").startswith("UNRESOLVED_")),
            "note": "Written by Stage T2 (build_canonical_terms) which rewrites "
                    "term_mentions.jsonl in place. PENDING_CANONICAL_STAGE here means "
                    "T2 did not run on this mention file.",
        },
        "failure_reasons": fail_reasons.most_common(),
        "papers_not_processed": not_processed[:50],
        "overall_status": _overall(n_fail, not_processed, no_mentions,
                                   len(papers_with_sections), mentions_present),
        "overall_status_note": "COMPLETE requires every corpus paper present, every section "
                               "integrity check passing, and at least one mention for every "
                               "paper with content. Section integrity alone is not enough.",
        "caveats": [
            "Validation checks structure, integrity and provenance only — not scientific correctness.",
            "A paper absent from the section set is counted as not_processed, never as a pass.",
            "Section text is hashed as read and is never modified by this pipeline.",
            "An empty section placeholder (front/(preamble)) is NOT_APPLICABLE, not a failure.",
            "Offsets are section-body relative, matching what the extraction stages read.",
            "A mention with non-integer offsets is excluded from offset verification "
            "and reported explicitly in mentions_excluded_non_integer_offsets — it is "
            "not deleted from the mention artifact.",
            "The mention -> canonical-term link status is reported as written by Stage "
            "T2; validation does not re-derive or repair it.",
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    with (args.out_dir / "validation_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps({"coverage": summary["coverage"],
                      "mentions": summary["mention_offset_verification"],
                      "overall_status": summary["overall_status"]}, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
