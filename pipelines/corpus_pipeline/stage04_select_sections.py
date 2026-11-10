"""Stage 4 (deterministic) - Relevant-section selection.

Reads the existing 453-record section inventories, resolves each section's text
via its recorded character offsets, and assigns a selection status using
deterministic rules over the recorded ``section_type`` plus heading cues.

This stage is deliberately deterministic. It is the baseline against which the
JEV pass (Stage 5) is compared; a disagreement between the two is recorded, not
silently resolved.

Emits:
  manifests/section_selection.csv|.json
  reports/section_selection_summary.csv
  reports/deterministic_mapping_report.md
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402

RULE_VERSION = "deterministic-v1"

# Section types that carry primary scientific content for the corpus.
RELEVANT_TYPES = {
    "abstract", "introduction", "methods", "results", "discussion",
    "conclusion", "data_availability", "supplementary", "other",
}
RELEVANT_CONTEXT_TYPES = {"ethics", "abbreviations"}
CONTAINER_TYPES = {
    "references", "author_contributions", "conflict_of_interest",
    "acknowledgments", "funding",
}

# Heading cue overrides, applied when the recorded type is 'other' or missing.
HEADING_CUES = {
    "methods": ("material", "method", "patient", "sample", "sequenc", "dna", "rna",
                "assay", "laborator", "protocol", "study design", "cohort", "participant"),
    "results": ("result", "finding", "outcome"),
    "discussion": ("discussion", "limitation", "strength"),
    "conclusion": ("conclusion", "summary", "implication"),
    "data_availability": ("data avail", "availability", "accession", "code avail",
                          "data and code", "repository"),
    "supplementary": ("supplement", "supporting", "additional file", "appendix"),
}

# Table/figure/caption cues: first-class scientific content even inside
# otherwise unclassified regions.
CONTENT_CUES = re.compile(
    r"\b(table\s+\d|figure\s+\d|fig\.\s*\d|supplementary table|supplementary figure)\b",
    re.IGNORECASE,
)


def cue_type(heading: str) -> str | None:
    """Infer a section type from heading wording when the record lacks one."""
    if not heading:
        return None
    low = heading.lower()
    for stype, cues in HEADING_CUES.items():
        if any(c in low for c in cues):
            return stype
    return None


def decide(section: dict, text: str) -> tuple[str, str, list[str]]:
    """Return (status, rationale, rule_ids) for one section."""
    stype = (section.get("section_type") or "").strip().lower()
    heading = (section.get("heading") or "").strip()
    rules: list[str] = []

    if not stype or stype == "other":
        inferred = cue_type(heading)
        if inferred:
            stype = inferred
            rules.append("R01_HEADING_CUE")
        else:
            rules.append("R02_UNCLASSIFIED")

    # A table/figure cue inside any section keeps it reachable for review rather
    # than letting a container classification hide scientific content.
    has_content_cue = bool(CONTENT_CUES.search(text[:4000]))

    if stype in RELEVANT_TYPES:
        rules.append("R10_PRIMARY_SCIENTIFIC")
        return "RELEVANT", f"recorded_type={stype}", rules
    if stype in RELEVANT_CONTEXT_TYPES:
        rules.append("R11_CONTEXT")
        return "RELEVANT_CONTEXT", f"recorded_type={stype}", rules
    if stype in CONTAINER_TYPES:
        if has_content_cue:
            rules.append("R20_CONTAINER_WITH_CONTENT_CUE")
            return "REVIEW_REQUIRED", f"container={stype} but table/figure content present", rules
        rules.append("R21_CONTAINER")
        return "CONTAINER_ONLY", f"recorded_type={stype}", rules

    if has_content_cue:
        rules.append("R30_UNCLASSIFIED_WITH_CONTENT_CUE")
        return "REVIEW_REQUIRED", "unclassified heading but table/figure content present", rules

    rules.append("R40_DEFAULT_UNCERTAIN")
    return "UNCERTAIN", f"no rule matched (type={stype or 'none'})", rules


def main() -> int:
    C.ensure_dirs()
    recon = json.loads((C.REPORTS_DIR / "target_453_reconciliation.json").read_text())
    targets = {r["corpus_id"]: r for r in
               json.loads((C.MANIFESTS_DIR / "target_453_papers.json").read_text())}

    rows: list[dict] = []
    text_cache: dict[str, str] = {}
    unresolved_text = 0

    for cid, meta in targets.items():
        if meta["state"] != "READY":
            continue
        rec_path = C.RECORDS_DIR / f"{cid}.json"
        rec = json.loads(rec_path.read_text())
        # Recorded char offsets index the ORIGINAL source (data/papers_txt/), not the
        # derived data/corpus/text/ copy - verified across 449/453 records.
        src_rel = (rec.get("files", {}) or {}).get("source_text_path", "")
        src_path = C.REPO_ROOT / src_rel if src_rel else None
        if src_path and src_path.exists():
            if cid not in text_cache:
                text_cache[cid] = src_path.read_text(encoding="utf-8", errors="replace")
            body = text_cache[cid]
        else:
            body = ""
            unresolved_text += 1

        for sec in rec.get("F_full_text_section_inventory") or []:
            a, b = sec.get("char_start", 0), sec.get("char_end", 0)
            in_bounds = 0 <= a <= b <= len(body)
            if not in_bounds:
                # Tolerate a trailing overrun of a few bytes (4 records show
                # char_end = len+1..3) rather than dropping the section.
                if 0 <= a < len(body):
                    b = min(b, len(body))
                    in_bounds = True
            slice_text = body[a:b] if in_bounds else ""
            if not in_bounds:
                unresolved_text += 1

            status, rationale, rules = decide(sec, slice_text)
            rows.append({
                "corpus_id": cid,
                "bioproject_accession": meta["bioproject_accession"],
                "section_id": sec.get("section_id", ""),
                "order": sec.get("order", 0),
                "heading": (sec.get("heading") or "")[:200],
                "heading_path": (sec.get("heading_path") or "")[:300],
                "section_type": sec.get("section_type", ""),
                "char_start": a,
                "char_end": b,
                "chars": max(0, b - a),
                "offsets_in_bounds": in_bounds,
                "selection_status": status,
                "rationale": rationale,
                "rule_ids": ";".join(rules),
                "rule_version": RULE_VERSION,
                "jev_decision": "",
                "jev_score": "",
                "disagreement": "",
                "review_flag": status in ("UNCERTAIN", "REVIEW_REQUIRED"),
            })

    out = C.MANIFESTS_DIR / "section_selection.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    with (C.MANIFESTS_DIR / "section_selection.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ------------------------------------------------------------ summary ----
    import collections
    by_status = collections.Counter(r["selection_status"] for r in rows)
    by_type = collections.Counter((r["section_type"], r["selection_status"]) for r in rows)

    with (C.REPORTS_DIR / "section_selection_summary.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["section_type", "selection_status", "n_sections", "n_chars"])
        agg: dict[tuple[str, str], list[int]] = {}
        for r in rows:
            k = (r["section_type"], r["selection_status"])
            agg.setdefault(k, [0, 0])
            agg[k][0] += 1
            agg[k][1] += r["chars"]
        for (t, s), (n, ch) in sorted(agg.items(), key=lambda x: -x[1][0]):
            w.writerow([t, s, n, ch])

    review_queue = [r for r in rows if r["review_flag"]]
    (C.REVIEW_DIR / "uncertain_section_queue.json").write_text(
        json.dumps(review_queue, indent=2, ensure_ascii=False)
    )

    md = [
        "# Deterministic Section Mapping Report",
        "",
        f"- Rule version: `{RULE_VERSION}`",
        f"- Papers processed: **{len({r['corpus_id'] for r in rows})}** (READY subset of 453)",
        f"- Sections classified: **{len(rows)}**",
        f"- Sections with unresolved offsets: **{sum(1 for r in rows if not r['offsets_in_bounds'])}**",
        "",
        "## Selection status distribution",
        "",
        "| status | sections |",
        "|---|---|",
    ]
    for k, v in by_status.most_common():
        md.append(f"| {k} | {v} |")
    md += ["", "## Section type x status", "", "| type | status | n |", "|---|---|---|"]
    for (t, s), v in by_type.most_common():
        md.append(f"| {t} | {s} | {v} |")
    md += ["",
           f"Review queue: **{len(review_queue)}** sections flagged UNCERTAIN or REVIEW_REQUIRED.",
           "No source text was modified. Deterministic decisions are the baseline for the JEV stage.",
           ""]
    (C.REPORTS_DIR / "deterministic_mapping_report.md").write_text("\n".join(md))

    print(json.dumps({
        "papers": len({r["corpus_id"] for r in rows}),
        "sections": len(rows),
        "by_status": dict(by_status),
        "offset_failures": sum(1 for r in rows if not r["offsets_in_bounds"]),
        "review_queue": len(review_queue),
        "unresolved_text_papers": unresolved_text,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())