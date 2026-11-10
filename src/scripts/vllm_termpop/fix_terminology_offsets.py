"""Terminology 1.0.1: correct the section-level offset shift and link mentions to canonical terms.

In terminology 1.0.0 some sections carry every mention (all models) shifted by a constant
1-3 characters: text[start:end] != surface_form but text[start+d:end+d] == surface_form.
This script finds the shift per (paper_id, section_id) by majority vote, applies it, and verifies
each row; a row is only moved when the shifted span equals its stored text. Nothing else changes
(ids, occurrence_key, supporting text). Each row gains `offset_status` (EXACT / CORRECTED / UNANCHORED)
and `offset_correction` (characters added to both offsets).

1.0.0 also left `canonical_term_id` null on every mention. Mentions are linked by
normalized_mention == canonical term_norm; when several terms share a term_norm, the one whose
cdm_type equals the mention's entity_type is used, else the mention is AMBIGUOUS. Field
`term_link_status`: LINKED / LINKED_BY_TYPE / AMBIGUOUS / NO_CANONICAL_TERM.

Writes a new release directory; 1.0.0 stays frozen. Unchanged artefacts are hard-linked.

    python fix_terminology_offsets.py [--src releases/terminology/1.0.0] [--dst releases/terminology/1.0.1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
SECTIONS = ROOT / "pipelines/corpus_v2/data/sections.jsonl"
SHIFTS = (1, -1, 2, -2, 3, -3)
# file -> (start key, end key, text key)
FIXED = {"term_mentions.jsonl": ("start_offset", "end_offset", "surface_form"),
         "term_definitions.jsonl": ("definition_char_start", "definition_char_end", "definition_text")}


def shift_of(text, a, b, q):
    if text is None or a is None or b is None or not q:
        return None
    if text[a:b] == q:
        return 0
    return next((d for d in SHIFTS if 0 <= a + d and text[a + d:b + d] == q), None)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "releases/terminology/1.0.0"))
    ap.add_argument("--dst", default=str(ROOT / "releases/terminology/1.0.1"))
    args = ap.parse_args(argv)
    src, dst = Path(args.src), Path(args.dst)
    if dst.exists():
        raise SystemExit(f"{dst} exists (frozen); choose a new version")
    t0 = time.time()
    sec = {}
    with open(SECTIONS, encoding="utf-8") as fh:
        for line in fh:
            s = json.loads(line)
            sec[(s["paper_id"], s["section_id_original"])] = s.get("section_text_original") or ""

    by_norm = defaultdict(list)
    with open(src / "canonical_terms.jsonl", encoding="utf-8") as fh:
        for line in fh:
            t = json.loads(line)
            by_norm[t["term_norm"]].append((t["term_id"], t.get("cdm_type")))

    def link(m):
        if m.get("canonical_term_id"):
            return m["canonical_term_id"], "LINKED"
        cands = by_norm.get(m.get("normalized_mention") or "")
        if not cands:
            return None, "NO_CANONICAL_TERM"
        if len(cands) == 1:
            return cands[0][0], "LINKED"
        typed = [tid for tid, typ in cands if typ == m.get("entity_type")]
        return (typed[0], "LINKED_BY_TYPE") if len(typed) == 1 else (None, "AMBIGUOUS")

    # pass 1: vote the shift of each section over both files
    votes = defaultdict(Counter)
    for name, (ka, kb, kq) in FIXED.items():
        with open(src / name, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                k = (r["paper_id"], r["section_id"])
                d = shift_of(sec.get(k), r.get(ka), r.get(kb), r.get(kq))
                if d is not None:
                    votes[k][d] += 1
    sec_shift = {k: c.most_common(1)[0][0] for k, c in votes.items()}
    shifted = {k: d for k, d in sec_shift.items() if d}
    print(f"sections with rows: {len(votes):,}; shifted: {len(shifted):,} {dict(Counter(shifted.values()))}", flush=True)

    # pass 2: write corrected files
    dst.mkdir(parents=True)
    report = {"source_release": str(src.relative_to(ROOT)), "sections_shifted": len(shifted),
              "shift_histogram": dict(Counter(shifted.values())), "files": {}}
    for name, (ka, kb, kq) in FIXED.items():
        st = Counter()
        tmp = dst / (name + ".tmp")
        with open(src / name, encoding="utf-8") as fi, open(tmp, "w", encoding="utf-8") as fo:
            for line in fi:
                r = json.loads(line)
                k = (r["paper_id"], r["section_id"])
                text, a, b, q = sec.get(k), r.get(ka), r.get(kb), r.get(kq)
                d = shift_of(text, a, b, q)
                if d == 0:
                    r.update(offset_status="EXACT", offset_correction=0)
                elif d is not None and d == sec_shift.get(k):
                    r[ka], r[kb] = a + d, b + d
                    r.update(offset_status="CORRECTED", offset_correction=d)
                else:   # no shift reproduces the stored text, or it disagrees with the section's shift
                    r.update(offset_status="UNANCHORED", offset_correction=0)
                st[r["offset_status"]] += 1
                if name == "term_mentions.jsonl":
                    r["canonical_term_id"], r["term_link_status"] = link(r)
                    st["link:" + r["term_link_status"]] += 1
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, dst / name)
        report["files"][name] = dict(st)
        print(f"{name}: {dict(st)}", flush=True)

    # unchanged artefacts: hard links (same bytes, same checksums as 1.0.0)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_dir() or rel.name in FIXED or rel.name in ("MANIFEST.sha256", "README.md", "PROVENANCE.json"):
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        os.link(p, dst / rel)
    report["artifacts"] = {n: sha256(dst / n) for n in FIXED}
    (dst / "OFFSET_FIX_REPORT.json").write_text(json.dumps(report, indent=1) + "\n")
    prov = json.loads((src / "PROVENANCE.json").read_text())
    prov.update(manifest_version="1.0.1", derived_from="releases/terminology/1.0.0",
                frozen_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                change="section-level offset shift corrected in term_mentions / term_definitions; "
                       "mention canonical_term_id linked by term_norm "
                       "(src/scripts/vllm_termpop/fix_terminology_offsets.py)")
    prov.pop("repository_root", None)
    prov.setdefault("artifacts", {}).update(report["artifacts"])
    (dst / "PROVENANCE.json").write_text(json.dumps(prov, indent=2) + "\n")
    m = report["files"]["term_mentions.jsonl"]
    dfs = report["files"]["term_definitions.jsonl"]
    (dst / "README.md").write_text("\n".join([
        "# Terminology Build 1.0.1 — frozen release", "",
        "Corrections: (1) character offsets of mentions and definitions, (2) mention -> canonical term links.", "",
        "Derived from `releases/terminology/1.0.0` (kept unchanged). Only the character offsets of "
        "`term_mentions.jsonl` and `term_definitions.jsonl` change: in "
        f"{len(shifted)} sections every row was shifted by a constant {sorted(set(shifted.values()))} characters "
        "(all extraction models alike), so `section_text[start:end]` missed the term by one or two characters. "
        "The shift is found per section by majority vote and applied only where the shifted span equals the "
        "stored text. Ids, `occurrence_key` and supporting text are unchanged.", "",
        "New fields: `offset_status` (EXACT / CORRECTED / UNANCHORED) and `offset_correction`.", "",
        "`canonical_term_id` was null on every mention in 1.0.0; it is now set by normalized_mention == term_norm "
        "(type breaks ties; otherwise AMBIGUOUS), with `term_link_status`: "
        + ", ".join(f"{k[5:]} {v:,}" for k, v in sorted(m.items()) if k.startswith("link:")) + ".", "",
        "| file | EXACT | CORRECTED | UNANCHORED |", "|---|---:|---:|---:|",
        f"| term_mentions.jsonl | {m.get('EXACT', 0):,} | {m.get('CORRECTED', 0):,} | {m.get('UNANCHORED', 0):,} |",
        f"| term_definitions.jsonl | {dfs.get('EXACT', 0):,} | {dfs.get('CORRECTED', 0):,} | {dfs.get('UNANCHORED', 0):,} |", "",
        "All other files are hard links to the 1.0.0 files (identical bytes). Details: `OFFSET_FIX_REPORT.json`.", "",
        "Verify: `sha256sum -c MANIFEST.sha256`", ""]))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    raise SystemExit(main())
