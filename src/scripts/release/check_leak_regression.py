"""Regression check for a public bundle: no string that exists only in withheld papers' text may be shipped.

Independent of the build and of verify_zenodo_frozen.py (which scan the bundle against windows of the withheld text).
This check works the other way round, from the source data:

  1. candidates: every text value of >= 50 characters in the frozen sources that could end up in a bundle -- CDM 3.0.3
     canonical terms, triple labels, definition text, and every column of the data catalogue 3.1.1 tables (minus
     bibliographic metadata: title, authors, journal, doi, and ontology concept labels);
  2. a candidate is "withheld-only" if some 40-letter/digit window of it (lower case, everything else removed) occurs
     in the text of a withheld paper and in neither the text of a text-included paper nor the bibliographic metadata;
     its first such window is its key;
  3. every value of every file of the bundle (SQLite: every text cell of every table; CSV/JSONL(.gz): every field;
     Markdown: every line; JSON: every value) is normalised the same way and searched for every key, one value at a
     time (fixed-string search, ugrep/grep -F). PASS requires 0 keys inside any single value.
     Also reported, not part of PASS: keys found only when a whole file is concatenated (across adjacent values).
     These can be artefacts (unrelated neighbouring cells) or a passage reconstructed from several short values;
     they are listed by file for inspection. (Until 2026-11-05 the check searched whole files only, which mixes both.)

  4. (--vocab-labels) the shipped CDM's concept table must carry no label of a vocabulary outside
     VOCABULARY_LABEL_ALLOWLIST.csv (blocker B23); classification as in build_zenodo_frozen.vocabulary_of.

Pass = 0 keys found (and, with --vocab-labels, 0 non-allow-listed labels). Writes <bundle>/VERIFICATION_LEAK_REGRESSION.json (or --report PATH for a sealed bundle).
On the frozen deposit (releases/zenodo_frozen) it must find withheld-only strings (the original 2026-11-05 count, 1,308,
used term and triple-label candidates only; with catalogue candidates the count is larger).

    python check_leak_regression.py --out releases/zenodo_r2
    python check_leak_regression.py --out releases/zenodo_frozen --report outputs/results/release/leak_regression_zenodo_frozen.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
CAT = ROOT / "releases/data_catalogue_v3/3.1.1/tables"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
EXEMPT_COLS = {"title", "authors", "journal", "doi", "concept_label", "standard_concept_label"}
MIN_LEN, W, STRIDE = 50, 40, 8
csv.field_size_limit(sys.maxsize)


def squash(s) -> str:
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())


def candidates(c) -> set[str]:
    out = set()
    for (t,) in c.execute("SELECT term FROM canonical_term WHERE length(term) >= ?", (MIN_LEN,)):
        out.add(t)
    for s, o in c.execute("SELECT subject_display_label, object_display_label FROM relation"):
        out.update(x for x in (s, o) if x and len(x) >= MIN_LEN)
    for (t,) in c.execute("SELECT definition_text FROM term_definition WHERE length(definition_text) >= ?", (MIN_LEN,)):
        out.add(t)
    for f in sorted(CAT.glob("*.csv")):
        for r in csv.DictReader(io.StringIO(f.read_text(encoding="utf-8").replace("\0", ""))):
            out.update(v for k, v in r.items() if k not in EXEMPT_COLS and isinstance(v, str) and len(v) >= MIN_LEN)
    return out


def file_text(f: Path) -> str:
    raw = gzip.open(f, "rb").read() if f.suffix == ".gz" else f.read_bytes()
    return squash(raw.decode("utf-8", "ignore"))


def cells(f: Path, rel: str, withheld: set):
    """Yield (normalised value, location, paper layer) for every value of a bundle file."""
    import shutil
    import tempfile

    def layer(pid):
        return "no_paper" if not pid else ("withheld" if pid in withheld else "included")

    def walk(o, where, pid=None):
        if isinstance(o, dict):
            pid = o.get("paper_id", pid)
            for k, x in o.items():
                yield from walk(x, f"{where}.{k}", pid)
        elif isinstance(o, list):
            for x in o:
                yield from walk(x, where, pid)
        elif isinstance(o, str):
            yield squash(o), where, layer(pid)
    if f.name.endswith(".db.gz") or f.suffix == ".db":
        dbf = f
        if f.suffix == ".gz":
            tmp = tempfile.NamedTemporaryFile(suffix=".db", dir=f.parent.parent.parent, delete=False)
            with gzip.open(f, "rb") as fi:
                shutil.copyfileobj(fi, tmp)
            tmp.close()
            dbf = Path(tmp.name)
        c = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            info = list(c.execute(f'PRAGMA table_info("{t}")'))
            cols = [r[1] for r in info if (r[2] or "").upper() in ("TEXT", "")]
            if not cols:
                continue
            haspid = "paper_id" in [r[1] for r in info]
            sel = ", ".join(f'"{x}"' for x in cols)
            for row in c.execute(f'SELECT {"paper_id, " if haspid else ""}{sel} FROM "{t}"'):
                pid = row[0] if haspid else None
                for x, v in zip(cols, row[1:] if haspid else row):
                    if isinstance(v, str) and len(v) >= W:
                        yield squash(v), f"{rel}:{t}.{x}", layer(pid)
        c.close()
        if dbf != f:
            dbf.unlink()
    elif f.name.endswith(".csv") or f.name.endswith(".csv.gz"):
        op = gzip.open if f.suffix == ".gz" else open
        with op(f, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(io.StringIO(fh.read().replace("\0", ""))):
                for k, v in r.items():
                    if isinstance(v, str) and len(v) >= W:
                        yield squash(v), f"{rel}:{k}", layer(r.get("paper_id"))
    elif f.name.endswith(".jsonl") or f.name.endswith(".jsonl.gz"):
        op = gzip.open if f.suffix == ".gz" else open
        with op(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield from walk(json.loads(line), rel)
    elif f.suffix == ".json":
        yield from walk(json.load(open(f, encoding="utf-8")), rel)
    else:   # Markdown and other text: one line at a time
        pid = f.stem if f.stem.startswith("HMPAPER_") else None
        for line in open(f, encoding="utf-8", errors="ignore"):
            yield squash(line), rel, layer(pid)


def fixed_string_search(keys: list[str], lines_path: Path, keys_path: Path) -> list[int]:
    """Line numbers (1-based) of lines_path containing any key; ugrep/grep -F (Aho-Corasick); no text is printed."""
    import subprocess
    keys_path.write_text("\n".join(keys) + "\n")
    out = subprocess.run(["grep", "-n", "-F", "-f", str(keys_path), str(lines_path)], capture_output=True, text=True)
    if out.returncode not in (0, 1):
        raise SystemExit("grep failed: " + out.stderr[:300])
    return [int(l.split(":", 1)[0]) for l in out.stdout.splitlines() if l]


def vocab_label_check(bundle: Path) -> dict:
    import shutil
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_zenodo_frozen as B
    allow = {r["vocabulary"].upper() for r in csv.DictReader(open(B.ALLOWLIST, encoding="utf-8"))}
    gz = next(bundle.glob("cdm/*.db.gz"))
    tmp = tempfile.NamedTemporaryFile(suffix=".db", dir=bundle.parent, delete=False)
    with gzip.open(gz, "rb") as fi:
        shutil.copyfileobj(fi, tmp)
    tmp.close()
    c = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
    rows = c.execute("SELECT concept_id, source_service FROM concept WHERE concept_label IS NOT NULL AND concept_label != ''").fetchall()
    c.close()
    Path(tmp.name).unlink()
    o = sqlite3.connect(f"file:{B.OMOP_INDEX}?mode=ro", uri=True)
    by = Counter()
    for cid, svc in rows:
        v = B.vocabulary_of(cid, svc)
        if v == "OMOP":
            r = o.execute("SELECT vocabulary_id FROM concept WHERE concept_id = ?", (int(cid),)).fetchone()
            v = B.OMOP_VOCAB.get(r[0] if r else "UNKNOWN", "OMOP:" + (r[0] if r else "UNKNOWN"))
        by[v] += 1
    o.close()
    bad = {k: n for k, n in by.items() if k not in allow}
    return {"labels_by_vocabulary": dict(by.most_common()), "non_allowlisted_labels": sum(bad.values()),
            "non_allowlisted_by_vocabulary": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="bundle folder, relative to the repository root")
    ap.add_argument("--vocab-labels", action="store_true", help="also check concept labels against the allow-list")
    ap.add_argument("--report", help="where to write the result (default <bundle>/VERIFICATION_LEAK_REGRESSION.json)")
    a = ap.parse_args()
    bundle = ROOT / a.out
    rights = {r["paper_id"]: r["proposed_release_decision"] for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))}
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    withheld, included = [], []
    for pid, t in c.execute("SELECT paper_id, section_text_original FROM section"):
        (included if rights.get(pid) == "INCLUDE_TEXT" else withheld).append(t or "")
    bib = [x or "" for row in c.execute("SELECT title, journal, authors, keywords FROM paper") for x in row]
    w_txt, i_txt, b_txt = squash("\n".join(withheld)), squash("\n".join(included)), squash("\n".join(bib))
    cands = candidates(c)
    c.close()
    keys = {}
    for x in cands:
        q = squash(x)
        for i in range(0, max(1, len(q) - W + 1), STRIDE):
            k = q[i:i + W]
            if len(k) == W and k in w_txt and k not in i_txt and k not in b_txt:
                keys[k] = x
                break
    print(f"candidates {len(cands):,}; withheld-only {len(keys):,}", flush=True)
    import tempfile
    withheld_ids = {p for p, r in rights.items() if r != "INCLUDE_TEXT"}
    work = Path(tempfile.mkdtemp(dir=bundle.parent, prefix=".leakcheck_"))   # keys are withheld text: kept local, deleted
    try:
        lines_path, keys_path = work / "values.txt", work / "keys.txt"
        index, filelevel = [], Counter()
        with open(lines_path, "w", encoding="utf-8") as fh:
            for f in sorted(bundle.rglob("*")):
                if not f.is_file() or f.suffix in (".png", ".pdf", ".sha256", ".py") or f.name.startswith("VERIFICATION_"):
                    continue
                rel = str(f.relative_to(bundle))
                n0 = len(index)
                for v, loc, lay in cells(f, rel, withheld_ids):
                    if len(v) >= W:
                        fh.write(v + "\n")
                        index.append((loc, lay))
                print(f"  {rel}: {len(index) - n0:,} values", flush=True)
        hits = fixed_string_search(list(keys), lines_path, keys_path)
        hit_lines = set(hits)
        found_keys, loc_count = set(), Counter()
        with open(lines_path, encoding="utf-8") as fh:
            for n, v in enumerate(fh, 1):
                if n in hit_lines:
                    loc, lay = index[n - 1]
                    loc_count[f"{loc} [{lay}]"] += 1
                    found_keys.update(k for k in keys if k in v)
        # whole-file concatenation (diagnostic only): keys found per file that are in no single value
        for f in sorted(bundle.rglob("*")):
            if not f.is_file() or f.suffix in (".png", ".pdf", ".sha256", ".py") or f.name.startswith("VERIFICATION_"):
                continue
            (work / "file.txt").write_text(file_text(f) + "\n")
            if fixed_string_search(list(keys), work / "file.txt", keys_path):
                out = __import__("subprocess").run(["grep", "-o", "-F", "-f", str(keys_path), str(work / "file.txt")],
                                                   capture_output=True, text=True).stdout.split()
                cross = {k for k in out if k in keys} - found_keys
                if cross:
                    filelevel[str(f.relative_to(bundle))] = len(cross)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    res = {"bundle": a.out, "method": "per value (fixed-string search); whole-file concatenation reported separately",
           "window_letters_digits": W, "min_candidate_chars": MIN_LEN, "candidates": len(cands),
           "withheld_only_strings": len(keys), "values_scanned": len(index),
           "strings_found_in_single_values": len(found_keys), "values_with_hits": len(hit_lines),
           "hits_by_location": dict(loc_count.most_common()),
           "cross_value_only_by_file": dict(filelevel.most_common()), "pass": not found_keys,
           "examples": [{"string_sha256": hashlib.sha256(keys[k].encode()).hexdigest(), "chars": len(keys[k])}
                        for k in list(found_keys)[:20]]}   # hashes only: a report must not quote withheld text
    if a.vocab_labels:
        res["vocab_labels"] = vocab_label_check(bundle)
        res["pass"] = res["pass"] and res["vocab_labels"]["non_allowlisted_labels"] == 0
    rep = Path(a.report) if a.report else bundle / "VERIFICATION_LEAK_REGRESSION.json"
    rep = rep if rep.is_absolute() else ROOT / rep
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "examples"}, indent=1))
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
