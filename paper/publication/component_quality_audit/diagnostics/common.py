"""Shared read-only helpers for the component quality audit.

Every diagnostic in this folder opens the frozen CDM strictly read-only
(`mode=ro`) and never writes to the release. No pipeline code is imported and no
network access is performed. Stdlib only (sqlite3, csv, json, hashlib, re).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DB = REPO / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
CAT = REPO / "releases/data_catalogue_v3/3.1.1"
TERM = REPO / "releases/terminology/1.0.1"
CORPUS = REPO / "pipelines/corpus_v2/releases/2.2.0/data"
SECTIONS = REPO / "data/segmented_sections_markdown"
AUDIT = REPO / "paper/publication/component_quality_audit"


def connect(path: Path | str = DB) -> sqlite3.Connection:
    """Open a frozen artifact strictly read-only. Fails loudly if unwritable path given."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def row(con: sqlite3.Connection, sql: str, params: tuple = ()):
    r = con.execute(sql, params).fetchone()
    return r[0] if r is not None else None


def rows(con: sqlite3.Connection, sql: str, params: tuple = ()):
    return con.execute(sql, params).fetchall()


def dist(con: sqlite3.Connection, table: str, col: str, limit: int = 40):
    sql = f'select "{col}", count(*) c from "{table}" group by 1 order by c desc limit {limit}'
    return [(r[0], r[1]) for r in con.execute(sql)]


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def emit(name: str, payload) -> None:
    """Write one diagnostic's machine-readable result next to the reports."""
    out = AUDIT / "diagnostics" / "results"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{name}.json"
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    print(f"[wrote] {dest.relative_to(REPO)}")
