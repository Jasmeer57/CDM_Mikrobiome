#!/usr/bin/env python
"""Build an offline OMOP concept index from an Athena vocabulary bundle.

The OMOP Athena *API* is unusable (``map_omop`` in
``src/cdm_pipeline/mapping/mappers.py`` is a dead stub because
``api.ohdsi.org`` returns HTTP 500). A full Athena download, however, is
enough to resolve OMOP concepts entirely offline and deterministically.

This script converts the four files that matter into one SQLite database:

    outputs/results/omop_vocab/omop_index.sqlite

    concept(concept_id, norm, name, domain_id, vocabulary_id,
            concept_class_id, standard_concept, concept_code)
        one row per *preferred* concept name.

    term(norm, concept_id, is_preferred)
        every synonym/name -> concept_id, so a lookup is a single indexed
        equality test on ``norm``.

    maps_to(src_concept_id, concept_id, name, vocabulary_id, domain_id)
        resolved standard concepts via the ``Maps to`` relationship, so a
        non-standard source concept (e.g. a MeSH term) can be reported
        alongside the standard concept it routes to.

``norm`` is the same normalization the rest of the mapping layer uses
(``" ".join(s.lower().split())``), so index hits are consistent with
``._confidence`` string scoring.

Usage:
    python src/scripts/vllm_termpop/build_omop_index.py
    python src/scripts/vllm_termpop/build_omop_index.py --index outputs/results/omop_vocab/omop_index.sqlite
"""
import argparse
import csv
import os
import sqlite3
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
VOCAB_DIR = REPO_ROOT / "outputs/results" / "omop_vocab"


def norm(s):
    return " ".join((s or "").lower().split())


SCHEMA = """
DROP TABLE IF EXISTS concept;
DROP TABLE IF EXISTS term;
DROP TABLE IF EXISTS maps_to;
CREATE TABLE concept (
    concept_id       INTEGER,
    norm             TEXT,
    name             TEXT,
    domain_id        TEXT,
    vocabulary_id    TEXT,
    concept_class_id TEXT,
    standard_concept TEXT,
    concept_code     TEXT
);
CREATE TABLE term (
    norm        TEXT,
    concept_id  INTEGER,
    is_preferred INTEGER
);
CREATE TABLE maps_to (
    src_concept_id INTEGER,
    concept_id     INTEGER,
    name           TEXT,
    vocabulary_id  TEXT,
    domain_id      TEXT
);
"""

INDEXES = """
CREATE INDEX idx_concept_id   ON concept(concept_id);
CREATE INDEX idx_concept_norm ON concept(norm);
CREATE INDEX idx_term_norm    ON term(norm);
CREATE INDEX idx_maps_to_src  ON maps_to(src_concept_id);
"""


def build_concepts(cur, path, batch=100_000):
    """CONCEPT.csv -> concept + term (preferred name only)."""
    n = 0
    t0 = time.time()
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.DictReader(f, delimiter="\t")
        for r in rd:
            cid = r["concept_id"]
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                continue
            name = r.get("concept_name") or ""
            nm = norm(name)
            if not nm:
                continue
            rows.append((cid, nm, name, r.get("domain_id") or "",
                         r.get("vocabulary_id") or "",
                         r.get("concept_class_id") or "",
                         r.get("standard_concept") or "",
                         r.get("concept_code") or "", cid, 1))
            n += 1
            if len(rows) >= batch:
                cur.executemany(
                    "INSERT INTO concept VALUES (?,?,?,?,?,?,?,?)",
                    [x[:8] for x in rows])
                cur.executemany("INSERT INTO term VALUES (?,?,?)",
                                [(x[1], x[8], x[9]) for x in rows])
                rows.clear()
                print(f"    {n:,} concepts ({time.time()-t0:.0f}s)", flush=True)
    if rows:
        cur.executemany("INSERT INTO concept VALUES (?,?,?,?,?,?,?,?)",
                        [x[:8] for x in rows])
        cur.executemany("INSERT INTO term VALUES (?,?,?)",
                        [(x[1], x[8], x[9]) for x in rows])
    print(f"    concepts: {n:,} ({time.time()-t0:.0f}s)")
    return n


def build_synonyms(cur, path, batch=100_000):
    """CONCEPT_SYNONYM.csv -> term (synonym names)."""
    n = 0
    t0 = time.time()
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.DictReader(f, delimiter="\t")
        for r in rd:
            try:
                cid = int(r["concept_id"])
            except (TypeError, ValueError, KeyError):
                continue
            nm = norm(r.get("concept_synonym_name"))
            if not nm:
                continue
            rows.append((nm, cid, 0))
            n += 1
            if len(rows) >= batch:
                cur.executemany("INSERT INTO term VALUES (?,?,?)", rows)
                rows.clear()
                print(f"    {n:,} synonyms ({time.time()-t0:.0f}s)", flush=True)
    if rows:
        cur.executemany("INSERT INTO term VALUES (?,?,?)", rows)
    print(f"    synonyms: {n:,} ({time.time()-t0:.0f}s)")
    return n


def build_maps_to(cur, rel_path, concept_by_id, batch=100_000):
    """CONCEPT_RELATIONSHIP.csv (filtered to 'Maps to') -> maps_to rows.

    ``concept_by_id`` supplies the target concept's name/vocabulary/domain.
    """
    n = 0
    t0 = time.time()
    rows = []
    with open(rel_path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.DictReader(f, delimiter="\t")
        for r in rd:
            if (r.get("relationship_id") or "") != "Maps to":
                continue
            if (r.get("invalid_reason") or "").strip():
                continue
            try:
                src = int(r["concept_id_1"])
                dst = int(r["concept_id_2"])
            except (TypeError, ValueError, KeyError):
                continue
            tgt = concept_by_id.get(dst)
            if not tgt:
                continue
            rows.append((src, dst, tgt[0], tgt[1], tgt[2]))
            n += 1
            if len(rows) >= batch:
                cur.executemany("INSERT INTO maps_to VALUES (?,?,?,?,?)", rows)
                rows.clear()
                print(f"    {n:,} Maps-to rows ({time.time()-t0:.0f}s)", flush=True)
    if rows:
        cur.executemany("INSERT INTO maps_to VALUES (?,?,?,?,?)", rows)
    print(f"    Maps-to rows: {n:,} ({time.time()-t0:.0f}s)")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vocab_dir", default=str(VOCAB_DIR))
    ap.add_argument("--index", default=None,
                    help="output sqlite path (default <vocab_dir>/omop_index.sqlite)")
    ap.add_argument("--skip_maps_to", action="store_true",
                    help="omit CONCEPT_RELATIONSHIP processing (faster, smaller)")
    args = ap.parse_args()

    vd = Path(args.vocab_dir)
    concept_csv = vd / "CONCEPT.csv"
    syn_csv = vd / "CONCEPT_SYNONYM.csv"
    rel_csv = vd / "CONCEPT_RELATIONSHIP.csv"
    index = Path(args.index) if args.index else vd / "omop_index.sqlite"
    if index.exists():
        index.unlink()

    for p in (concept_csv, syn_csv):
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 2
    have_maps_to = rel_csv.exists() and not args.skip_maps_to
    if not have_maps_to:
        why = "(--skip_maps_to)" if args.skip_maps_to else "(CONCEPT_RELATIONSHIP.csv absent)"
        print(f"NOTE: Maps-to resolution disabled {why}")

    t0 = time.time()
    print("=" * 72)
    print("building offline OMOP index")
    print(f"  vocab_dir : {vd}")
    print(f"  index     : {index}")
    print(f"  maps_to   : {have_maps_to}")
    print("=" * 72)

    con = sqlite3.connect(str(index))
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA cache_size=-2000000")  # ~2 GB page cache
    cur = con.cursor()
    cur.executescript(SCHEMA)

    print("\n[1/3] CONCEPT.csv")
    n_con = build_concepts(cur, concept_csv, )
    con.commit()

    print("\n[2/3] CONCEPT_SYNONYM.csv")
    n_syn = build_synonyms(cur, syn_csv)
    con.commit()

    n_map = 0
    if have_maps_to:
        print("\n[3/3] CONCEPT_RELATIONSHIP.csv (Maps to)")
        print("      loading standard-concept lookup ...", flush=True)
        concept_by_id = {}
        for cid, name, vocab, dom in cur.execute(
                "SELECT concept_id, name, vocabulary_id, domain_id "
                "FROM concept WHERE standard_concept='S'"):
            concept_by_id[cid] = (name, vocab, dom)
        print(f"      {len(concept_by_id):,} standard concepts in memory")
        n_map = build_maps_to(cur, rel_csv, concept_by_id)
        con.commit()

    print("\n[4/4] building indexes")
    t1 = time.time()
    # unique index on concept_id collapses nothing here but speeds joins
    cur.executescript(INDEXES)
    con.commit()
    print(f"      done ({time.time()-t1:.0f}s)")

    cur.execute("ANALYZE")
    con.commit()
    con.close()

    size_gb = index.stat().st_size / (1024 ** 3)
    print("\n" + "=" * 72)
    print(f"index built in {time.time()-t0:.0f}s")
    print(f"  concepts   : {n_con:,}")
    print(f"  synonyms   : {n_syn:,}")
    print(f"  maps_to    : {n_map:,}")
    print(f"  size       : {size_gb:.2f} GB")
    print(f"  path       : {index}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
