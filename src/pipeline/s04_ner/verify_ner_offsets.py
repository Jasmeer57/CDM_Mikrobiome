#!/usr/bin/env python
"""Verify a 452-paper section-NER variant run against the segmented corpus.

Checks, per CSV and per row:
  * every (paper, section_id) resolves to a real body unit   -> missing_unit
  * ``term`` is non-empty after strip                        -> empty_term
  * ``source[char_start:char_end] == term`` (exact)          -> mismatch
  * mismatches explained by stripping U+0000 from the slice  -> nul_explained
  * anything left over                                      -> unexplained (FAIL)

The NUL cases are the documented `data/papers_txt/` ligature-loss artifact, not a
runner bug: tokenizers drop U+0000, so the model returns ``inammation`` for the
source slice ``in\\x00ammation``. They are reported separately so a real offset
regression cannot hide inside them.

Usage:
    PYTHONPATH=src python src/scripts/verify_ner_offsets.py outputs/results/<dir>/*_ner.csv

Exit codes:
    0  every file passed (unexplained == 0 and missing_unit == 0)
    1  at least one file failed
"""
from __future__ import annotations

import csv
import os
import sys

from pipeline.s04_ner.runner_sections import load_sections

SEG_DIR = str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                   if (p / ".cdm_root").is_file()) / "data" / "segmented_sections_markdown")

# Java-tool CSVs carry extra trailing columns; these are the ones we need.
REQUIRED = ("term", "paper", "section_id", "char_start", "char_end")


def check(path, index):
    n = missing_row = bad = nul = unexplained = empty = 0
    papers, unexp_samples = set(), []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        absent = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if absent:
            return {"path": path, "fatal": f"missing columns {absent}"}

        for row in reader:
            n += 1
            text = index.get((row.get("paper"), row.get("section_id")))
            if text is None:
                missing_row += 1
                continue
            term = row.get("term") or ""
            if not term.strip():
                empty += 1
                continue
            try:
                s, e = int(row["char_start"]), int(row["char_end"])
            except (TypeError, ValueError):
                bad += 1
                unexp_samples.append(("unparseable offsets", row))
                continue
            slice_ = text[s:e]
            if slice_ == term:
                continue
            bad += 1
            papers.add(row.get("paper"))
            if "\x00" in slice_ and slice_.replace("\x00", "") == term:
                nul += 1
            else:
                unexplained += 1
                if len(unexp_samples) < 5:
                    unexp_samples.append((row.get("paper"), row.get("section_id"),
                                          term, slice_))

    return {
        "path": path, "rows": n, "missing_unit": missing_row, "empty_term": empty,
        "mismatch": bad, "nul_explained": nul, "unexplained": unexplained,
        "papers": sorted(p for p in papers if p), "samples": unexp_samples,
        "ok": missing_row == 0 and unexplained == 0,
    }


def expand(paths):
    """Expand directories to their CSVs; keep explicit files as-is.

    Directory expansion deliberately lists ALL ``*.csv`` rather than globbing
    ``*_ner.csv``: the variant runs name files inconsistently
    (``scispacy_ner_bionlp13cg.csv`` has no ``_ner`` suffix), and a pattern that
    silently skips a file would under-report failures.
    """
    out = []
    for p in paths:
        if os.path.isdir(p):
            hits = sorted(os.path.join(p, f) for f in os.listdir(p)
                          if f.endswith(".csv"))
            if not hits:
                print(f"WARNING: no CSVs in {p}")
            out.extend(hits)
        else:
            out.append(p)
    return out


def main(argv):
    paths = expand(argv[1:])
    if not paths:
        print(__doc__)
        return 2

    units, _stats = load_sections(SEG_DIR)
    index = {(u["cid"], u["section_id"]): u["text"] for u in units}
    papers = {u["cid"] for u in units}
    chars = sum(len(u["text"]) for u in units)
    print(f"corpus: {len(index)} body units | papers={len(papers)} "
          f"| chars={chars:,}\n", flush=True)

    failures = 0
    for path in paths:
        if not os.path.isfile(path):
            print(f"MISSING FILE {path}")
            failures += 1
            continue
        r = check(path, index)
        name = os.path.basename(path)
        if r.get("fatal"):
            print(f"FAIL {name}: {r['fatal']}")
            failures += 1
            continue
        flag = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            failures += 1
        print(f"{flag} {name}")
        print(f"     rows={r['rows']} missing_unit={r['missing_unit']} "
              f"empty_term={r['empty_term']} mismatch={r['mismatch']} "
              f"(nul_explained={r['nul_explained']}, "
              f"unexplained={r['unexplained']})")
        if r["mismatch"]:
            print(f"     papers with mismatches: {r['papers']}")
        for s in r["samples"]:
            print(f"     UNEXPLAINED: {s!r}")
        print()

    print(f"{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
