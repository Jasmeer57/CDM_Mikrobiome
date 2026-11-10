"""Finalize releases/zenodo_frozen after build_zenodo_frozen.py (run order: build -> finalize -> verify).

  * terminology/: canonical terms, concept mappings and definitions are exported from the public CDM (so they match it
    and inherit its redaction); the pre-review terminology 1.0.1 files and their stale summaries are removed;
  * triples/: relation triples and their evidence exported from the public CDM;
  * local filesystem paths are reduced to repository-relative paths in shipped metadata;
  * validation/: internal planning documents are replaced by the public TECHNICAL_VALIDATION.md (kept next to this
    script) plus the two benchmark result tables;
  * the database is gzip-compressed; --seal writes MANIFEST.sha256 and makes the folder read-only.
Idempotent: safe to re-run on an already finalized folder.

    python finalize_zenodo_frozen.py          # content
    python verify_zenodo_frozen.py            # rights scan
    python finalize_zenodo_frozen.py --seal   # manifest + read-only
    (add --out releases/<folder> to finalize another build, e.g. releases/zenodo_r2)
"""
from __future__ import annotations

import csv
import gzip
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OUT = ROOT / "releases/zenodo_frozen"
DBN = "microbiome_cdm_v3.0.3_public.db"
HERE = Path(__file__).resolve().parent
LOCAL_PREFIXES = (str(ROOT) + "/", "/home/jkalra_hpc/Microbiome-CDM/", "/home/jkalra_hpc/")


def export(c, sql, path):
    cur = c.execute(sql)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([d[0] for d in cur.description])
        n = 0
        for r in cur:
            w.writerow(r)
            n += 1
    print(f"  {path.relative_to(OUT)}: {n:,} rows")


def main():
    for p in [OUT, *OUT.rglob("*")]:
        p.chmod(p.stat().st_mode | 0o200)
    db = OUT / "cdm" / DBN
    gz = OUT / "cdm" / (DBN + ".gz")
    tmpdir = Path(tempfile.mkdtemp(dir=OUT.parent))
    if gz.exists():
        with gzip.open(gz, "rb") as fi, open(tmpdir / DBN, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        work = tmpdir / DBN
    else:
        work = db
    c = sqlite3.connect(f"file:{work}?mode=ro", uri=True)

    # terminology from the public CDM
    term = OUT / "terminology"
    for name in ("canonical_terms.jsonl", "canonical_terms.jsonl.gz", "term_ontology_mappings.jsonl",
                 "term_ontology_mappings.jsonl.gz", "term_definitions.jsonl", "canonical_terms_summary.json", "README.md"):
        if (term / name).exists():
            (term / name).unlink()
    export(c, "SELECT * FROM canonical_term ORDER BY term_id", term / "canonical_terms.csv.gz")
    export(c, "SELECT * FROM term_concept_map ORDER BY term_id, candidate_rank", term / "term_concept_mappings.csv.gz")
    export(c, "SELECT * FROM term_definition ORDER BY term_id", term / "term_definitions.csv.gz")

    # triples
    (OUT / "triples").mkdir(exist_ok=True)
    export(c, "SELECT * FROM relation ORDER BY canonical_triple_id", OUT / "triples/triples.csv.gz")
    export(c, "SELECT * FROM relation_evidence ORDER BY canonical_triple_id, paper_id, char_start",
           OUT / "triples/triple_evidence.csv.gz")
    c.close()

    # local paths -> repository-relative
    for f in OUT.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".md", ".csv") and f.name != "MANIFEST.sha256":
            s = f.read_text(encoding="utf-8")
            t = s
            for pre in LOCAL_PREFIXES:
                t = t.replace(pre, "")
            if t != s:
                f.write_text(t, encoding="utf-8")
                print(f"  paths scrubbed: {f.relative_to(OUT)}")

    # validation documents
    for name in ("MASTER_VALIDATION_REPORT.md", "BENCHMARK_FINAL_ANALYSIS.md"):
        if (OUT / "validation" / name).exists():
            (OUT / "validation" / name).unlink()
    shutil.copy2(HERE / "TECHNICAL_VALIDATION.md", OUT / "validation/TECHNICAL_VALIDATION.md")
    if (OUT / "rights" / "VOCABULARY_LABEL_ALLOWLIST.csv").exists():   # labels restricted (B23): ship the restore tool
        shutil.copy2(HERE / "restore_vocab_labels.py", OUT / "rights" / "restore_vocab_labels.py")
    readme = HERE / f"ZENODO_README_{OUT.name}.md"          # a later build may carry its own README
    shutil.copy2(readme if readme.exists() else HERE / "ZENODO_README.md", OUT / "README.md")

    # compress database, manifest
    if db.exists():
        with open(db, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo)
        db.unlink()
    shutil.rmtree(tmpdir)
    print("finalized; now run verify_zenodo_frozen.py, then finalize_zenodo_frozen.py --seal")


def seal():
    """Write MANIFEST.sha256 over every file and make the folder read-only (run after the rights scan)."""
    import hashlib
    for p in [OUT, *OUT.rglob("*")]:
        p.chmod(p.stat().st_mode | 0o200)
    files = sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    with open(OUT / "MANIFEST.sha256", "w") as fh:
        for p in files:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
            fh.write(f"{h.hexdigest()}  {p.relative_to(OUT)}\n")
    print(f"manifest: {len(files)} files")
    for p in [*OUT.rglob("*"), OUT]:
        p.chmod(p.stat().st_mode & ~0o222)


if __name__ == "__main__":
    import sys
    if "--out" in sys.argv:
        OUT = ROOT / sys.argv[sys.argv.index("--out") + 1]
    seal() if "--seal" in sys.argv else main()
