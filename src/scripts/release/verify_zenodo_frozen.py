"""Independent check of releases/zenodo_frozen: no verbatim passage (>= 60 chars) of a withheld paper is shipped.

Indexes every 50-character window of the withheld papers' text (from the frozen CDM 3.0.3), then scans every string
in every shipped file: SQLite (all tables / text columns), CSV, JSONL(.gz), Markdown and JSON. A hit is accepted only
when the string belongs to a text-included paper and also occurs in that paper's own text (shared boilerplate).
Writes VERIFICATION_RIGHTS_SCAN.json; exits 1 on any unexplained hit.

    python verify_zenodo_frozen.py
    python verify_zenodo_frozen.py --out releases/zenodo_r2 --match alnum
Matching modes (--match): "ws" (default; the frozen deposit) compares whitespace-normalised 50-character windows,
probed every 10 characters. "alnum" compares windows of 40 letters/digits after lower-casing and removing everything
else (spaces, punctuation, hyphens, arrows), probed every 5; it also catches copies that differ from the paper only in
punctuation, hyphenation or line breaks (1,308 such strings were found in the frozen deposit on 2026-11-05).
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OUT = ROOT / "releases/zenodo_frozen"
SRC_DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
W, STRIDE = 50, 10
MATCH = {"ws": (50, 10), "alnum": (40, 5)}
MODE = "ws"
csv.field_size_limit(sys.maxsize)
# not paper text: bibliographic metadata, ontology labels, compendium (SRA-derived) tables -- same list as the build
EXEMPT_COLS = {"title", "authors", "journal", "doi", "concept_label", "standard_concept_label"}
EXEMPT_TABLES = {"compendium_project", "compendium_sample", "compendium_sample_tag", "concept", "release_rights"}


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def key(s):
    return ws(s) if MODE == "ws" else re.sub(r"[^0-9a-z]", "", (s or "").lower())


def main():
    global OUT, W, STRIDE, MODE
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="bundle folder, relative to the repository root (default releases/zenodo_frozen)")
    ap.add_argument("--match", choices=sorted(MATCH), default="ws")
    a = ap.parse_args()
    if a.out:
        OUT = ROOT / a.out
    MODE = a.match
    W, STRIDE = MATCH[MODE]
    MINLEN = W + STRIDE if MODE == "ws" else W
    print(f"bundle {OUT}; matching {MODE}: window {W}, stride {STRIDE}", flush=True)
    rights = {r["paper_id"]: r["text_layer"] for r in csv.DictReader(open(OUT / "rights/PAPER_LICENCES.csv"))}
    withheld = {p for p, l in rights.items() if l != "TEXT_INCLUDED"}
    src = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    text = {}
    for pid, t in src.execute("SELECT paper_id, section_text_original FROM section"):
        text[pid] = text.get(pid, "") + (" " if MODE == "ws" else "") + key(t)
    index = set()
    for p in withheld:
        t = text.get(p, "")
        index.update(hash(t[i:i + W]) for i in range(0, max(0, len(t) - W + 1)))
    print(f"indexed {len(index):,} windows from {len(withheld)} withheld papers", flush=True)
    included_text = " ".join(t for p, t in text.items() if p not in withheld)
    stats = Counter()
    hits = []

    def check(v, where, pid=None):
        col = re.split(r"[.:]", where)[-1]
        if col in EXEMPT_COLS:
            return
        if not isinstance(v, str) or len(v) < MINLEN:
            return
        v2 = key(v)
        if MODE == "alnum" and len(v2) < W:
            return
        stats["strings_checked"] += 1
        matched = [v2[i:i + W] for i in range(0, len(v2) - W + 1, STRIDE) if hash(v2[i:i + W]) in index]
        if not matched:
            return
        # a text-included paper may ship its own wording, even when a withheld paper uses the same words
        if pid and pid not in withheld and all(m in text.get(pid, "") for m in matched):
            stats["shared_wording_in_included_paper"] += 1
            return
        if not pid and all(m in included_text for m in matched):
            stats["no_paper_value_also_in_included_paper"] += 1
            return
        stats["hits_by_location"] = stats.get("hits_by_location") or Counter()
        layer = "withheld" if pid in withheld else ("included" if pid else "no_paper_id")
        stats["hits_by_location"][f"{where} [{layer}]"] += 1
        hits.append({"where": where, "paper_id": pid, "paper_layer": "withheld" if pid in withheld else
                     ("included" if pid else "no_paper_id"), "excerpt": matched[0]})

    def walk(o, where, pid=None):
        if isinstance(o, dict):
            pid = o.get("paper_id", pid)
            for k, x in o.items():
                walk(x, f"{where}.{k}", pid)
        elif isinstance(o, list):
            for x in o:
                walk(x, where, pid)
        else:
            check(o, where, pid)

    for f in sorted(OUT.rglob("*")):
        if not f.is_file() or f.name.startswith("VERIFICATION_"):
            continue
        rel = str(f.relative_to(OUT))
        stats["files"] += 1
        if f.suffix == ".db" or f.name.endswith(".db.gz"):
            dbf = f
            if f.suffix == ".gz":
                import shutil, tempfile
                tmp = tempfile.NamedTemporaryFile(suffix=".db", dir=OUT.parent, delete=False)
                with gzip.open(f, "rb") as fi:
                    shutil.copyfileobj(fi, tmp)
                tmp.close()
                dbf = Path(tmp.name)
            c = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                if t in EXEMPT_TABLES:
                    continue
                cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")') if (r[2] or "").upper() in ("TEXT", "")]
                if not cols:
                    continue
                has_pid = "paper_id" in [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
                sel = ", ".join(f'"{x}"' for x in cols)
                cond = " OR ".join(f'length("{x}") >= {MINLEN}' for x in cols)
                q = f'SELECT {"paper_id, " if has_pid else ""}{sel} FROM "{t}" WHERE {cond}'
                for row in c.execute(q):
                    pid = row[0] if has_pid else None
                    for x, v in zip(cols, row[1:] if has_pid else row):
                        check(v, f"{rel}:{t}.{x}", pid)
            c.close()
            if dbf != f:
                dbf.unlink()
        elif f.suffix == ".csv" or f.name.endswith(".csv.gz"):
            op = gzip.open if f.suffix == ".gz" else open
            for r in csv.DictReader(io.StringIO(op(f, "rt", encoding="utf-8").read())):
                for k, v in r.items():
                    check(v, f"{rel}:{k}", r.get("paper_id"))
        elif f.name.endswith(".jsonl") or f.name.endswith(".jsonl.gz"):
            op = gzip.open if f.suffix == ".gz" else open
            with op(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    walk(json.loads(line), rel)
        elif f.suffix == ".json":
            walk(json.load(open(f, encoding="utf-8")), rel)
        elif f.suffix == ".md":
            pid = f.stem if f.stem.startswith("HMPAPER_") else None
            if pid in withheld:
                hits.append({"where": rel, "paper_id": pid, "excerpt": "markdown file of a withheld paper"})
            for para in open(f, encoding="utf-8").read().split("\n"):
                check(para, rel, pid)
        print(f"  scanned {rel}", flush=True)
    by_loc = dict(stats.pop("hits_by_location", Counter()).most_common())
    res = {"withheld_papers": len(withheld), "match": MODE, "window": W, "stride": STRIDE, **stats, "hits_by_location": by_loc, "unexplained_hits": len(hits),
           "hits": hits[:200], "pass": not hits}
    (OUT / "VERIFICATION_RIGHTS_SCAN.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "hits"}, indent=1))
    for h in hits[:15]:
        print(h)
    sys.exit(0 if not hits else 1)


if __name__ == "__main__":
    main()
