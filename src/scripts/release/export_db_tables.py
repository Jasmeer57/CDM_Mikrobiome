"""Export a CDM SQLite database to easy-to-view files: one CSV per table, plus SCHEMA.json and README.md.

  * CSV: UTF-8 with BOM (Excel shows accents correctly), header row, one file per table; tables longer than
    1,000,000 rows (the spreadsheet limit) are split into numbered parts.
  * SCHEMA.json: every table with its columns, types and row count.
  * README.md: table list with row counts and file names.
The database is opened read-only; nothing in it is changed.

    python export_db_tables.py --db releases/cdm_v3/3.0.3/microbiome_cdm_v3.db --out <folder> [--internal]
--internal marks the export as containing text of withheld papers (not for sharing).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
MAX_ROWS = 1_000_000
csv.field_size_limit(sys.maxsize)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--internal", action="store_true")
    a = ap.parse_args()
    src = Path(a.db) if Path(a.db).is_absolute() else ROOT / a.db
    out = Path(a.out)
    if out.exists():
        sys.exit(f"{out} exists; refusing to overwrite")
    (out / "tables").mkdir(parents=True)
    tmp = None
    if src.suffix == ".gz":
        tmp = Path(tempfile.mkdtemp(dir=out.parent)) / src.stem
        with gzip.open(src, "rb") as fi, open(tmp, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        src = tmp
    c = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    schema = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        cols = [(r[1], r[2]) for r in c.execute(f'PRAGMA table_info("{t}")')]
        files, n, part, fh, w = [], 0, 0, None, None
        for row in c.execute(f'SELECT * FROM "{t}"'):
            if n % MAX_ROWS == 0:
                if fh:
                    fh.close()
                part += 1
                name = f"{t}.csv" if part == 1 else f"{t}.part{part}.csv"
                fh = open(out / "tables" / name, "w", newline="", encoding="utf-8-sig")
                w = csv.writer(fh)
                w.writerow([x for x, _ in cols])
                files.append(name)
            w.writerow(row)
            n += 1
        if fh:
            fh.close()
        if n == 0:
            with open(out / "tables" / f"{t}.csv", "w", newline="", encoding="utf-8-sig") as e:
                csv.writer(e).writerow([x for x, _ in cols])
            files = [f"{t}.csv"]
        if part > 1:   # rename part 1 consistently
            (out / "tables" / f"{t}.csv").rename(out / "tables" / f"{t}.part1.csv")
            files[0] = f"{t}.part1.csv"
        schema[t] = {"rows": n, "columns": [{"name": x, "type": y} for x, y in cols], "files": files}
        print(f"  {t}: {n:,} rows -> {len(files)} file(s)", flush=True)
    c.close()
    if tmp:
        shutil.rmtree(tmp.parent)
    (out / "SCHEMA.json").write_text(json.dumps({"source": str(Path(a.db)), "tables": schema}, indent=1) + "\n")
    L = [f"# Table export of `{Path(a.db).name}`", ""]
    if a.internal:
        L += ["**INTERNAL: contains the text of papers whose licence does not allow redistribution (179 withheld "
              "papers). Do not share or upload. For sharing, export the public bundle's database instead.**", ""]
    L += ["One CSV per table (UTF-8; opens in Excel / LibreOffice). Tables over 1,000,000 rows are split into parts. "
          "Column names and types: `SCHEMA.json`. The SQLite database remains the authoritative copy.", "",
          "| table | rows | columns | files |", "|---|---:|---:|---|"]
    for t, s in sorted(schema.items(), key=lambda kv: -kv[1]["rows"]):
        L.append(f"| {t} | {s['rows']:,} | {len(s['columns'])} | {', '.join(s['files'])} |")
    (out / "README.md").write_text("\n".join(L) + "\n")
    print("written", out)


if __name__ == "__main__":
    main()
