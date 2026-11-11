"""Step 2 of the 3.2.0-candidate fix: gazetteer pass over methods-type sections, per paper, with offsets; and the
candidate windows ("paragraphs") that the field-targeted LLM extractor sees.

Methods-type sections (rule fixed before any run):
  section_type == 'Methods'; or section_type in ('Other', 'Supplementary') unless the section name is an ethics /
  competing-interest / abbreviations / acknowledgement / funding / author / data-availability / preamble block;
  papers WITHOUT any 'Methods' section additionally use their 'Results' sections (fallback).
Candidate windows: +-700 characters around every gazetteer hit and every field trigger phrase (e.g. "DNA was extracted",
"sequenced on"), merged when overlapping, split at 3,000 characters. Offsets are into section_text_original of CDM 3.0.3
(read-only), so every value is traceable to (paper_id, section_id_original, char_start, char_end).

    python src/scripts/fixes_v32/dict_pass.py
Outputs (outputs/results/catalogue_fields_v32_2026-11-11/): gazetteer_hits.jsonl, windows.jsonl, dict_pass_summary.json
Written with Claude Code (declare).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gazetteer as G  # noqa: E402

CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = G.OUT
FIELDS = ("dna_extraction_method", "sequencing_platform")
EXCLUDE_NAME = re.compile(r"ethic|competing|conflict|abbreviat|acknowledg|funding|financ|author|contribution|consent|"
                          r"availab|declaration|preamble|copyright|licen[cs]e|correspond|orcid|disclos|publisher", re.I)
TRIGGER = {
    "dna_extraction_method": re.compile(
        r"DNA\s+(?:was|were)\s+(?:\w+\s+){0,3}?(?:extracted|isolated|purified)|(?:DNA|nucleic\s+acids?)\s+(?:extraction|isolation)|"
        r"extracted\s+(?:\w+\s+){0,4}?DNA", re.I),
    "sequencing_platform": re.compile(
        r"sequenced\s+(?:\w+\s+){0,3}?(?:on|using|with|by|at)\b|sequencing\s+(?:was|were)\s+(?:\w+\s+)?(?:performed|carried\s+out|"
        r"conducted|done)|sequencing\s+platform|\bsequencer\b", re.I)}
CTX, CAP = 700, 3000


def methods_sections(c):
    rows = c.execute("SELECT paper_id, section_id_original, section_name_original, section_type, section_text_original "
                     "FROM section ORDER BY paper_id, section_order").fetchall()
    has_methods = {r[0] for r in rows if r[3] == "Methods"}
    out = []
    for pid, sid, name, st, txt in rows:
        if not txt:
            continue
        keep = st == "Methods" or (st in ("Other", "Supplementary") and not EXCLUDE_NAME.search(name or "")) or \
            (st == "Results" and pid not in has_methods)
        if keep:
            out.append((pid, sid, name, st, txt))
    return out


def snap(txt, a, b):
    """Extend [a, b) to sentence-ish boundaries (". " or newline) within 150 chars."""
    lo = max(0, a)
    k = max(txt.rfind(". ", max(0, lo - 150), lo), txt.rfind("\n", max(0, lo - 150), lo))
    if k > 0:
        lo = k + 1
    hi = min(len(txt), b)
    m = re.search(r"\.\s|\n", txt[hi:hi + 150])
    if m:
        hi = hi + m.end()
    return lo, hi


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    secs = methods_sections(c)
    papers = sorted({r[0] for r in c.execute("SELECT DISTINCT paper_id FROM section")})
    nh, nw = Counter(), Counter()
    with open(OUT / "gazetteer_hits.jsonl", "w", encoding="utf-8") as fh, open(OUT / "windows.jsonl", "w", encoding="utf-8") as fw:
        for pid, sid, name, st, txt in secs:
            spans = []
            for f in FIELDS:
                for h in G.match(f, txt):
                    h.update({"paper_id": pid, "section_id": sid, "section_type": st, "field": f,
                              "canonical": G.canonical(f, h["family"], h["model"]), "gazetteer_version": G.VERSION})
                    fh.write(json.dumps(h, ensure_ascii=False) + "\n")
                    nh[f] += 1
                    spans.append((h["start"], h["end"]))
                for m in TRIGGER[f].finditer(txt):
                    spans.append((m.start(), m.end()))
            if not spans:
                continue
            spans.sort()
            merged = []
            for a, b in spans:
                lo, hi = max(0, a - CTX), min(len(txt), b + CTX)
                if merged and lo <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], hi)
                else:
                    merged.append([lo, hi])
            k = 0
            for lo, hi in merged:
                for s in range(lo, hi, CAP):
                    a, b = snap(txt, s, min(hi, s + CAP))
                    wid = f"{pid}|{sid}|{k}"
                    k += 1
                    fw.write(json.dumps({"window_id": wid, "paper_id": pid, "section_id": sid, "section_type": st,
                                         "start": a, "end": b, "text": txt[a:b]}, ensure_ascii=False) + "\n")
                    nw[st] += 1
    summ = {"gazetteer_version": G.VERSION, "papers_in_cdm": len(papers), "methods_type_sections": len(secs),
            "papers_with_methods_type_sections": len({s[0] for s in secs}), "gazetteer_hits": dict(nh),
            "windows": sum(nw.values()), "windows_by_section_type": dict(nw), "window_ctx_chars": CTX, "window_cap_chars": CAP,
            "cdm": str(CDM.relative_to(ROOT))}
    (OUT / "dict_pass_summary.json").write_text(json.dumps(summ, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
