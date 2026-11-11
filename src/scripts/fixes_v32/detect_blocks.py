"""Detect TABLE, TABLE_CAPTION and FIGURE_CAPTION blocks in the CDM section text (catalogue 3.2.0-candidate).

Source: section.section_text_original of the frozen CDM 3.0.3 (opened read-only) -- the same text the catalogue_v3_1
extractor read, so block offsets are directly comparable with claim.section_id / char_start / char_end.
References and Acknowledgements sections are skipped. Deterministic rules only (no model).

    python src/scripts/fixes_v32/detect_blocks.py            # writes blocks.jsonl + detection report
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "outputs/results/catalogue_tables_captions_v32_2026-11-11"
SKIP_SECTIONS = ("References", "Acknowledgements")

MARK = re.compile(
    r"^[ \t]*(?P<supp>Supplementa(?:ry|l)\s+)?(?P<kind>Fig(?:ure)?s?\.?|FIGURE|FIG\.?|Table|TABLE)\s*"
    r"(?P<num>S?\d{1,2}[A-Za-z]?)(?P<rest>.*)$")
NOT_CAPTION_WORDS = re.compile(r"^(shows?|summari[sz]es?|lists?|presents?|describes?|provides?|gives?|and|or|to|in|"
                               r"for|of|was|were|is|are|also|indicates?|displays?|illustrates?|depicts?|reports?|"
                               r"contains?|demonstrates?|details?|compares?|highlights?)\b", re.I)
PAGE = re.compile(r"^\s*(\d+\s+of\s+\d+|page\s+\d+(\s+of\s+\d+)?|\d{1,3})\s*$", re.I)
CONT = re.compile(r"^\s*(\(?cont(inued)?\.?\)?|continued)\s*\.?\s*$", re.I)
HEADING = re.compile(r"^\s*(\d+(\.\d+)*\.?\s+[A-Z][^.]{0,80}|#{1,6}\s.*)$")
MAX_CAPTION = 2000
MAX_TABLE = 12000


def marker(line: str):
    """-> (kind 'FIG'|'TAB', supplementary, label, caption_start_col) when the line opens a caption, else None."""
    m = MARK.match(line)
    if not m:
        return None
    rest = m.group("rest")
    if re.match(r"^\s*[)\],;]|^\s*[-–](?=\s*[A-Za-z]?\d)|^\s*(and|to|&)\s", rest):
        return None  # in-text reference: "Figure 3).", "Fig. 1b-c)", "Tables 1 and 2"
    sep = re.match(r"^\s*([.:|—–])\s*", rest)
    body = rest[sep.end():] if sep else rest.lstrip()
    if CONT.match(body):
        return None  # "Figure 2. Cont."
    if sep:
        if body and not re.match(r"[A-Z(\[0-9\"'‘“a-z]", body):
            return None
        if body and re.match(r"[a-z]", body) and NOT_CAPTION_WORDS.match(body):
            return None
    else:
        if body and (not re.match(r"[A-Z(]", body) or NOT_CAPTION_WORDS.match(body)):
            return None
    kind = "FIG" if m.group("kind").lower().startswith("fig") else "TAB"
    return kind, bool(m.group("supp")) or m.group("num").upper().startswith("S"), m.group("num"), body


def is_prose(line: str, min_len: float = 70) -> bool:
    s = line.strip()
    if len(s) < min(70, max(45, min_len)):
        return False
    words = s.split()
    if len(words) < 7:
        return False
    alpha = sum(ch.isalpha() for ch in s) / len(s)
    nums = sum(bool(re.fullmatch(r"[-+<>≤≥±()%.,0-9eE×*/]+", w)) for w in words) / len(words)
    return alpha > 0.65 and nums < 0.25


def lines_with_offsets(text: str):
    out, pos = [], 0
    for ln in text.split("\n"):
        out.append((pos, pos + len(ln), ln))
        pos += len(ln) + 1
    return out


def caption_end(lines, i, kind):
    """Index (exclusive) of the last line of a caption opened at lines[i]."""
    widths = [len(l[2].strip()) for l in lines if len(l[2].strip()) > 40]
    typical = statistics.median(widths) if widths else 80
    j, chars = i, 0
    max_lines = 3 if kind == "TAB" else 25
    while j < len(lines):
        s = lines[j][2].strip()
        if j > i and (not s or PAGE.match(s) or marker(lines[j][2]) or HEADING.match(s) and len(s) < 60 and not s.endswith(",")):
            break
        if kind == "FIG" and j - i >= 2 and j + 1 < len(lines):
            # layout change: full-width caption lines followed by two clearly narrower body-column lines
            cap_w = statistics.median(len(lines[x][2].strip()) for x in range(i + 1, j))
            nxt = [len(lines[j][2].strip()), len(lines[j + 1][2].strip())]
            if cap_w > 80 and all(25 < w < 0.7 * cap_w for w in nxt):
                break
        chars += len(s) + 1
        j += 1
        if chars > MAX_CAPTION or j - i >= max_lines:
            break
        # paragraph end: sentence-final line that is clearly shorter than the wrapped width
        if s.endswith((".", ".)")) and len(s) < 0.8 * typical and j - i >= 1:
            break
        if kind == "TAB" and s.endswith("."):
            break
    return j


FOOTNOTE = re.compile(r"^\s*([a-z*†‡§¶#]\s|\(?[a-z]\)|abbreviations?|data are|values|p[- ]?values?|note|\*)", re.I)


def table_end(lines, j):
    """Index (exclusive) where a flattened table body that starts at lines[j] ends."""
    widths = [len(l[2].strip()) for l in lines if len(l[2].strip()) > 40]
    typical = statistics.median(widths) if widths else 80
    k, chars, cells = j, 0, 0
    while k < len(lines):
        s = lines[k][2].strip()
        if marker(lines[k][2]):
            break
        if (k + 1 < len(lines) and all(is_prose(lines[x][2], 0.75 * typical) and not FOOTNOTE.match(lines[x][2])
                                       for x in (k, k + 1))):
            break
        if HEADING.match(s) and re.match(r"^\d+(\.\d+)+\.?\s", s):
            break
        chars += len(s) + 1
        cells += bool(s)
        k += 1
        if chars > MAX_TABLE:
            break
    while k > j and not lines[k - 1][2].strip():
        k -= 1
    return k, cells


def delimited_tables(lines):
    """Runs of >= 3 lines with >= 2 '|' or tab delimiters (Markdown pipe / TSV tables)."""
    out, start = [], None
    for idx, (_, _, ln) in enumerate(lines + [(0, 0, "")]):
        hit = ln.lstrip().startswith("|") and ln.count("|") >= 3 or ln.count("\t") >= 2
        if hit and start is None:
            start = idx
        elif not hit and start is not None:
            if idx - start >= 3:
                out.append((start, idx))
            start = None
    return out


def detect(text: str):
    lines = lines_with_offsets(text)
    blocks, i = [], 0
    while i < len(lines):
        mk = marker(lines[i][2])
        if not mk:
            i += 1
            continue
        kind, supp, label, body = mk
        nxt = lines[i + 1][2].lstrip() if i + 1 < len(lines) else ""
        if not body.strip() and (not nxt or re.match(r"[)\],;.]|[a-z]", nxt)):
            i += 1  # in-text reference broken across a line: "Supplementary Table S9\n)."
            continue
        j = caption_end(lines, i, kind)
        cap = (lines[i][0] + (len(lines[i][2]) - len(lines[i][2].lstrip())), lines[j - 1][1])
        if cap[1] - cap[0] > MAX_CAPTION:  # text without line breaks: clip at the last sentence end before the cap
            seg = text[cap[0]:cap[0] + MAX_CAPTION]
            cut = max(seg.rfind(". "), seg.rfind(".\n"))
            cap = (cap[0], cap[0] + (cut + 1 if cut > 200 else MAX_CAPTION))
        if kind == "FIG":
            blocks.append({"block_type": "FIGURE_CAPTION", "label": label, "supplementary": supp,
                           "char_start": cap[0], "char_end": cap[1]})
            i = j
            continue
        blocks.append({"block_type": "TABLE_CAPTION", "label": label, "supplementary": supp,
                       "char_start": cap[0], "char_end": cap[1]})
        k, cells = table_end(lines, j)
        if cells >= 3:
            blocks.append({"block_type": "TABLE", "label": label, "supplementary": supp,
                           "char_start": lines[j][0], "char_end": lines[k - 1][1], "caption_char_start": cap[0],
                           "detector": "flattened_after_caption"})
            i = k
        else:
            i = j
    taken = [(b["char_start"], b["char_end"]) for b in blocks]
    for a, b in delimited_tables(lines):
        s, e = lines[a][0], lines[b - 1][1]
        if not any(s < te and ts < e for ts, te in taken):
            blocks.append({"block_type": "TABLE", "label": "", "supplementary": False, "char_start": s, "char_end": e,
                           "detector": "delimited"})
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--spot", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20261111)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = c.execute("SELECT paper_id, section_id_original, section_type, section_name_normalized, section_text_original "
                     "FROM section WHERE section_type NOT IN (?, ?) ORDER BY paper_id, section_order",
                     SKIP_SECTIONS).fetchall()
    # existing catalogue evidence spans, to report how much block text the prose extraction already used
    spans = defaultdict(list)
    for pid, sid, s, e in c.execute("SELECT paper_id, section_id, char_start, char_end FROM claim "
                                    "WHERE claim_source = 'catalogue_v3_1' AND char_start != '' AND char_end != ''"):
        try:
            spans[(pid, sid)].append((int(s), int(e)))
        except (TypeError, ValueError):
            pass
    allp = sorted({r[0] for r in c.execute("SELECT paper_id FROM paper")})
    blocks, per_paper = [], defaultdict(Counter)
    for pid, sid, stype, sname, text in rows:
        for b in detect(text or ""):
            t = text[b["char_start"]:b["char_end"]]
            if len(t.strip()) < 8 or b["block_type"] == "FIGURE_CAPTION" and len(t.split()) < 4:
                continue  # e.g. eLife "Figure 2—figur" fragments
            ov = sum(1 for s, e in spans.get((pid, sid), []) if s < b["char_end"] and b["char_start"] < e)
            b.update(block_id=f"{pid}:{sid}:{b['char_start']}-{b['char_end']}", paper_id=pid, section_id=sid,
                     section_type=stype, section_name=sname, text=t, n_chars=len(t),
                     catalogue_v3_1_findings_overlapping=ov)
            blocks.append(b)
            per_paper[pid][b["block_type"]] += 1
    # tables are emitted after their caption, keep a stable order
    blocks.sort(key=lambda b: (b["paper_id"], b["section_id"], b["char_start"]))
    with open(out / "blocks.jsonl", "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blocks))
    with open(out / "detection_per_paper.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["paper_id", "FIGURE_CAPTION", "TABLE_CAPTION", "TABLE"])
        for pid in allp:
            w.writerow([pid] + [per_paper[pid][k] for k in ("FIGURE_CAPTION", "TABLE_CAPTION", "TABLE")])
    rng = random.Random(a.seed)
    sample = rng.sample(blocks, min(a.spot, len(blocks)))
    with open(out / "detection_spotcheck.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["block_id", "block_type", "detector", "n_chars", "head_200", "tail_120", "verdict", "note"])
        for b in sample:
            w.writerow([b["block_id"], b["block_type"], b.get("detector", "marker"), b["n_chars"],
                        b["text"][:200].replace("\n", " ⏎ "), b["text"][-120:].replace("\n", " ⏎ "), "", ""])
    by = Counter(b["block_type"] for b in blocks)
    summ = {"source": "CDM 3.0.3 section.section_text_original (read-only); References/Acknowledgements skipped",
            "papers_total": len(allp), "sections_scanned": len(rows), "blocks": dict(by), "blocks_total": len(blocks),
            "supplementary_captions": sum(b["supplementary"] for b in blocks if b["block_type"] != "TABLE"),
            "papers_with_any_block": sum(1 for p in allp if per_paper[p]),
            "papers_with": {k: sum(1 for p in allp if per_paper[p][k]) for k in by},
            "delimited_tables": sum(b.get("detector") == "delimited" for b in blocks),
            "chars_in_blocks": sum(b["n_chars"] for b in blocks),
            "blocks_with_overlapping_catalogue_v3_1_finding": {k: sum(1 for b in blocks if b["block_type"] == k and
                                                                      b["catalogue_v3_1_findings_overlapping"]) for k in by},
            "by_section_type": {k: dict(Counter(b["section_type"] for b in blocks if b["block_type"] == k)) for k in by}}
    (out / "detection_summary.json").write_text(json.dumps(summ, indent=2) + "\n")
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()
