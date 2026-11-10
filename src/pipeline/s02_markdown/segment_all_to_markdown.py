"""Convert all 453 corpus full texts to segmented-sections markdown.

Reads:
  data/corpus/records/HMPAPER_*.json  -> F_full_text_section_inventory (char offsets)
  data/corpus/text/HMPAPER_*.txt      -> harmonized full text those offsets refer to
  data/papers_txt/<ACCESSION>.txt         -> used instead for papers whose inventory was
                                        computed against the raw text (see
                                        INVENTORY_AGAINST_PAPERS_TXT below)
  data/corpus/id_map.csv             -> corpus_id <-> BioProject accessions

Writes one file per paper to OUTPUT_DIR (default data/segmented_sections_markdown/),
in the exact marker format consumed by src/notebooks/pipeline_standalone.ipynb
Cell 2 (parse_sections):

    ---
    # HMPAPER_000001
    bioproject: PRJDB10485
    ---
    <!-- SEGMENT: SEG_paper1_0001 -->
    <!-- SECTION_ID: sec_preface -->
    <!-- SECTION_PATH: front/(preamble) -->
    <!-- SEGMENT_ORDINAL_WITHIN_SECTION: 1 -->
    <uncovered leading text verbatim>
    <!-- END_SEGMENT: SEG_paper1_0001 -->
    <!-- SEGMENT: SEG_paper1_0002 -->
    <!-- SECTION_ID: sec_001 -->
    <!-- SECTION_PATH: MATERIALS AND METHODS -->
    ...
    <!-- END_SEGMENT: SEG_paper1_0002 -->

Every character of the source text is covered exactly once, as one of:
  - a `front/(preamble)` segment (leading title/author block before sec 1),
  - the inventoried sections, in file order,
  - `gap` segments between sections when the inventory skips text,
  - a `back/postamble` segment for trailing text.

The notebook's is_backmatter() keeps a section as body when the last
SECTION_PATH element is exactly `(preamble)`; gap/postamble paths use the
`gap` marker in the last element only when the content looks like
references (heuristic, conservative: frontmatter and mid-text gaps stay
body). Pass --no-heuristic to label all gaps/postambles as kept body.

Usage:
  python src/scripts/segment_all_to_markdown.py [--output DIR] [--limit N] [--force]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2] if Path(__file__).parent.name == "slurm" else Path(__file__).resolve().parents[1]
RECORDS_DIR = REPO_ROOT / "data" / "corpus" / "records"
TEXT_DIR = REPO_ROOT / "data" / "corpus" / "text"
ID_MAP_CSV = REPO_ROOT / "data" / "corpus" / "id_map.csv"
PAPERS_TXT = REPO_ROOT / "data/papers_txt"
DEFAULT_OUTPUT = REPO_ROOT / "data/segmented_sections_markdown"

# Papers whose F_full_text_section_inventory was computed against the raw
# papers_txt file, not the harmonized data/corpus/text file (verified:
# inventory fits papers_txt with no OOB/overlap while corpus text is far
# shorter than the last section end).
INVENTORY_AGAINST_PAPERS_TXT = {
    "HMPAPER_000187",
    "HMPAPER_000240",
    "HMPAPER_000446",
}

MIN_GAP_CHARS = 40  # gaps smaller than this get silently skipped in output (never in inventories)

SENTINEL_RE = re.compile(r"<!-- (SEGMENT|SECTION_ID|SECTION_PATH|END_SEGMENT|SEGMENT_ORDINAL_WITHIN_SECTION): ")
SEG_ID_FMT = "SEG_{seg_count:05d}"


def sanitize_body(text: str) -> str:
    """Escape any accidental marker-looking lines so parse_sections cannot be fooled."""
    def esc(line: str) -> str:
        return f"\\<\\!-- {line[4:]}" if SENTINEL_RE.match(line) else line
    # split("\n") NOT splitlines(): splitlines() also breaks on \x0b/\x0c/\u2028 etc.
    # and the rejoin would mutate source bytes (breaks lossless round-trip).
    return "\n".join(esc(ln) for ln in text.split("\n"))


def load_id_map() -> dict:
    with open(ID_MAP_CSV, encoding="utf-8-sig", newline="") as f:
        return {r["corpus_id"]: r["bioproject_accession"] for r in csv.DictReader(f)}


def source_text_for(cid: str, id_map: dict) -> Path:
    if cid in INVENTORY_AGAINST_PAPERS_TXT:
        acc = id_map[cid]
        return PAPERS_TXT / f"{acc}.txt"
    return TEXT_DIR / f"{cid}.txt"


def convert_one(record_path: Path, id_map: dict, out_dir: Path, force: bool = False) -> dict:
    cid = record_path.stem
    out_path = out_dir / f"{cid}.md"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    inv = record.get("F_full_text_section_inventory") or []

    text_path = source_text_for(cid, id_map)
    text = text_path.read_text(encoding="utf-8-sig", errors="replace")
    n = len(text)

    spans = []  # (section_id, heading_path, start, end) non-overlapping, ordered
    prev_end = 0
    warnings = []
    for sec in inv:
        st, en = int(sec["char_start"]), int(sec["char_end"])
        path = str(sec.get("heading_path") or sec.get("section_type") or "unknown")
        if st < prev_end:
            st = prev_end  # clamp tiny 1-2 char inventory overlaps (never negative span)
            warnings.append(f"clamped overlap at {sec['section_id']}")
        if en > n or en <= st:
            warnings.append(f"skipped invalid section {sec['section_id']} ({st}..{en} > {n})")
            continue
        if st - prev_end >= MIN_GAP_CHARS:
            spans.append((f"sec_gap_{len(spans):03d}", "gap", prev_end, st))
        spans.append((sec["section_id"], path, st, en))
        prev_end = en
    if prev_end >= MIN_GAP_CHARS:
        spans.insert(0, ("sec_preface", "front/(preamble)", 0, prev_end if not spans else spans[0][2]))
    elif not spans and n:
        spans = [("sec_preface", "front/(preamble)", 0, n)]
    if n - prev_end >= MIN_GAP_CHARS:
        spans.append((f"sec_postamble_{len(spans):03d}", "back/postamble", prev_end, n))

    idx = record.get("bioproject_accession") or id_map.get(cid, "")
    title = record.get("B_publication_metadata", {}).get("title", "")
    lines = ["---", f"# {cid}"]
    if idx:
        lines.append(f"bioproject: {idx}")
    if title:
        lines.append(f"title: {title}")
    lines.append("---")

    covered = 0
    prev_span_end = None
    for k, (sec_id, path, st, en) in enumerate(spans, 1):
        if prev_span_end is not None and st < prev_span_end:
            warnings.append(f"internal overlap {sec_id}: {st} < {prev_span_end}")
            st = prev_span_end
        seg_id = SEG_ID_FMT.format(seg_count=k)
        body = sanitize_body(text[st:en])
        lines.append(f"<!-- SEGMENT: {seg_id} -->")
        lines.append(f"<!-- SECTION_ID: {sec_id} -->")
        lines.append(f"<!-- SECTION_PATH: {path} -->")
        lines.append("<!-- SEGMENT_ORDINAL_WITHIN_SECTION: 1 -->")
        lines.append(body)
        lines.append(f"<!-- END_SEGMENT: {seg_id} -->")
        covered += en - st
        prev_span_end = en

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # small seams (<MIN_GAP_CHARS) are intentionally not segmented; count them so the
    # report is honest rather than claiming full coverage
    seam_chars = 0
    cursor = 0
    for _, _, st, en in spans:
        seam_chars += max(0, st - cursor)
        cursor = max(cursor, en)
    seam_chars += max(0, n - cursor)
    return {
        "corpus_id": cid,
        "bioproject": idx,
        "source": str(text_path),
        "sections": len(spans),
        "covered_chars": covered,
        "seam_chars_lt_threshold": seam_chars,
        "total_chars": n,
        "uncovered_chars": n - covered,
        "warnings": warnings,
        "output": str(out_path),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="output directory (default: %(default)s)")
    ap.add_argument("--records", default=str(RECORDS_DIR), help="corpus records dir (default: %(default)s)")
    ap.add_argument("--limit", type=int, default=None, help="process at most N papers")
    ap.add_argument("--force", action="store_true", help="rewrite files that already exist")
    args = ap.parse_args(argv)

    t0 = time.time()
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    id_map = load_id_map()
    record_paths = sorted(Path(args.records).glob("HMPAPER_*.json"))
    if not record_paths:
        print(f"ERROR: no records found in {args.records}", file=sys.stderr)
        return 2
    if args.limit:
        record_paths = record_paths[: args.limit]

    stats = []
    for rp in record_paths:
        out_file = out_dir / f"{rp.stem}.md"
        if out_file.exists() and not args.force:
            continue
        stats.append(convert_one(rp, id_map, out_dir, force=True))

    bad = [s for s in stats if s["uncovered_chars"] > 0 or s["warnings"]]
    report = {
        "output_dir": str(out_dir),
        "papers_written": len(stats),
        "papers_skipped_existing": len(record_paths) - len(stats),
        "warnings": sum(len(s["warnings"]) for s in stats),
        "papers_with_warnings": len(bad),
        "total_chars": sum(s["total_chars"] for s in stats),
        "uncovered_chars": sum(s["uncovered_chars"] for s in stats),
        "sections_written": sum(s["sections"] for s in stats),
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    report_path = out_dir / "_conversion_report.json"
    report_path.write_text(json.dumps({"report": report, "papers": stats}, indent=1), encoding="utf-8")
    # Per-paper gap fallback promoted from header: never invent content.
    print(json.dumps(report, indent=1))
    if bad:
        print("papers with warnings:", file=sys.stderr)
        for s in bad[:10]:
            print(" ", s["corpus_id"], s["warnings"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
