"""Find text in non-Latin scripts (CJK, kana, Hangul, Cyrillic, Arabic, ...) in a folder of outputs. Read-only.

    python src/scripts/final_validation/scan_non_english.py [DIR] [--out DIR]

Scans text files (.json, .jsonl, .csv, .tsv, .md, .txt, .graphml, .log, also .gz) line by line and SQLite databases
column by column. Parquet and Excel are skipped: they are exports of the scanned database. Greek and accented Latin
are not flagged (normal in scientific text). Writes summary.json (counts per file / table.column and script, with
examples) and strings.tsv (every distinct flagged string with where it occurs).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sqlite3
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
SCRIPTS = {
    "CJK": r"㐀-䶿一-鿿豈-﫿",
    "Japanese_kana": r"぀-ヿ",
    "Hangul": r"가-힯ᄀ-ᇿ",
    "Cyrillic": r"Ѐ-ӿ",
    "Arabic": r"؀-ۿ",
    "Hebrew": r"֐-׿",
    "Thai": r"฀-๿",
    "Devanagari": r"ऀ-ॿ",
}
ANY = re.compile("[" + "".join(SCRIPTS.values()) + "]")
PER = {k: re.compile("[" + v + "]") for k, v in SCRIPTS.items()}
RUN = re.compile("[^\"\t,|]*[" + "".join(SCRIPTS.values()) + "][^\"\t,|]*")
TEXT_EXT = {".json", ".jsonl", ".csv", ".tsv", ".md", ".txt", ".graphml", ".log", ".sql", ".yaml", ".yml", ".py"}


def scripts_in(s):
    return [k for k, r in PER.items() if r.search(s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", type=Path, default=ROOT / "paper/publication/all_frozen_outputs")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/results/non_english_scan_2026-11-08")
    a = ap.parse_args()
    base = a.dir.resolve()
    where = collections.defaultdict(lambda: collections.Counter())      # location -> script -> lines
    examples = collections.defaultdict(list)
    strings = collections.defaultdict(set)                              # string -> locations

    def hit(loc, text):
        for k in scripts_in(text):
            where[loc][k] += 1
        for m in RUN.findall(text):
            m = m.strip()[:200]
            if m:
                strings[m].add(loc)
                if len(examples[loc]) < 5 and m not in examples[loc]:
                    examples[loc].append(m)

    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(base))
        suf = p.suffixes[-2] if p.suffix == ".gz" and len(p.suffixes) > 1 else p.suffix
        if p.suffix == ".db":
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            for (t,) in con.execute("select name from sqlite_master where type='table'"):
                cols = [c[1] for c in con.execute(f'pragma table_info("{t}")') if (c[2] or "").upper() in ("TEXT", "")]
                for c in cols:
                    q = f'select "{c}" from "{t}" where "{c}" is not null and typeof("{c}")=\'text\''
                    for (v,) in con.execute(q):
                        if ANY.search(v):
                            hit(f"{rel}::{t}.{c}", v)
            con.close()
        elif suf in TEXT_EXT:
            opener = gzip.open if p.suffix == ".gz" else open
            with opener(p, "rt", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ANY.search(line):
                        hit(rel, line)

    a.out.mkdir(parents=True, exist_ok=True)
    summary = {"scanned": str(base.relative_to(ROOT)), "scripts_flagged": list(SCRIPTS),
               "locations": {k: {"lines_by_script": dict(v), "examples": examples[k]}
                             for k, v in sorted(where.items(), key=lambda kv: -sum(kv[1].values()))},
               "distinct_strings": len(strings)}
    json.dump(summary, open(a.out / "summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(a.out / "strings.tsv", "w", encoding="utf-8") as f:
        f.write("string\tscripts\tn_locations\tlocations\n")
        for s, locs in sorted(strings.items()):
            f.write(f"{s}\t{','.join(scripts_in(s))}\t{len(locs)}\t{' ; '.join(sorted(locs))[:500]}\n")
    print(f"{len(where)} locations, {len(strings)} distinct strings -> {a.out.relative_to(ROOT)}")
    for k, v in list(summary["locations"].items())[:40]:
        print(f"{sum(v['lines_by_script'].values()):>8}  {k}  {v['lines_by_script']}  e.g. {v['examples'][:2]}")


if __name__ == "__main__":
    main()
