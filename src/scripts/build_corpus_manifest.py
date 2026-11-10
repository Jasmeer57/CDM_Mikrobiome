#!/usr/bin/env python3
"""Build the canonical corpus manifest for the Microbiome-CDM release.

Walks data/papers_txt/*.txt, computes SHA-256 + size + md5 for every file, identifies
content-duplicate clusters (multiple files with the same md5), picks a canonical
representative per cluster (the file with the most entity mentions in the DB
ties the broken; otherwise the lexicographically smallest filename), then emits:

    - corpus_manifest.json  (machine-readable, in the release dir)
    - docs/corpus_dedup_decisions.md  (human-readable, decision log)

Run from repo root:

    python src/scripts/build_corpus_manifest.py \\
        --papers papers_txt \\
        --out   releases/v2.0-qwen-publication/corpus_manifest.json \\
        --db    releases/v2.0-qwen-publication/microbiome_cdm.db \\
        --log   docs/corpus_dedup_decisions.md
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def entity_mentions_for_file(conn: sqlite3.Connection, filename: str) -> int:
    """How many distinct entity mentions does the DB record for this paper?"""
    # The DB stores project_id (e.g. PRJEB17608) not the .txt filename. Strip suffix.
    pid = filename.replace(".txt", "")
    row = conn.execute(
        "SELECT COUNT(DISTINCT entity_id) FROM entity_project_mentions WHERE project_id=?",
        (pid,),
    ).fetchone()
    return row[0] if row else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--papers", default=str(REPO_ROOT / "data/papers_txt"),
                   help="data/papers_txt/ directory")
    p.add_argument("--out", required=True, help="output corpus_manifest.json")
    p.add_argument("--db", default=None,
                   help="optional DB for picking canonical duplicate")
    p.add_argument("--log", default=None, help="optional dedup-decision log .md")
    args = p.parse_args()

    papers_dir = Path(args.papers).resolve()
    txt_files = sorted(papers_dir.glob("*.txt"))
    if not txt_files:
        print(f"no .txt files found in {papers_dir}", file=sys.stderr)
        return 1

    conn = None
    if args.db and Path(args.db).exists():
        conn = sqlite3.connect(str(args.db))

    # 1) compute hash + metadata per file
    by_md5: dict[str, list[dict]] = defaultdict(list)
    records: list[dict] = []
    for path in txt_files:
        rec = {
            "accession": path.stem,
            "filename": path.name,
            "sha256": sha256_of(path),
            "md5": md5_of(path),
            "bytes": path.stat().st_size,
            "entity_mentions": entity_mentions_for_file(conn, path.name) if conn else 0,
        }
        records.append(rec)
        by_md5[rec["md5"]].append(rec)

    # 2) identify canonical per md5 cluster
    canonical_by_md5: dict[str, dict] = {}
    duplicates_log: list[dict] = []
    for md5, cluster in by_md5.items():
        if len(cluster) == 1:
            canonical_by_md5[md5] = cluster[0]
            continue
        # Pick canonical: most entity_mentions; ties broken by lex-min filename.
        sorted_by_priority = sorted(
            cluster, key=lambda r: (-r["entity_mentions"], r["filename"])
        )
        canonical = sorted_by_priority[0]
        canonical_by_md5[md5] = canonical
        duplicates_log.append({
            "md5": md5,
            "canonical": canonical["filename"],
            "canonical_entity_mentions": canonical["entity_mentions"],
            "duplicates": [
                {"filename": r["filename"], "entity_mentions": r["entity_mentions"]}
                for r in cluster if r is not canonical
            ],
        })

    # 3) emit manifest
    for r in records:
        r["canonical"] = (r["md5"] in canonical_by_md5
                          and canonical_by_md5[r["md5"]]["filename"] == r["filename"])
        r["duplicate_of"] = (None if r["canonical"]
                             else canonical_by_md5[r["md5"]]["filename"])

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_dir": str(papers_dir.relative_to(REPO_ROOT)),
        "total_files": len(records),
        "unique_contents": len({r["md5"] for r in records}),
        "duplicate_clusters": len([k for k, v in by_md5.items() if len(v) > 1]),
        "papers": records,
    }
    Path(args.out).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out}: {manifest['total_files']} files, "
          f"{manifest['unique_contents']} unique contents, "
          f"{manifest['duplicate_clusters']} duplicate clusters")

    # 4) emit dedup-decision log if requested
    if args.log:
        lines = ["# Corpus dedup decisions", "",
                 f"_Generated {manifest['generated_at']} from "
                 f"`{papers_dir}` ({len(records)} files, "
                 f"{manifest['unique_contents']} unique contents)_",
                 ""]
        if not duplicates_log:
            lines.append("No duplicate content detected.")
        else:
            lines.append("## Duplicate clusters")
            lines.append("")
            for d in duplicates_log:
                lines.append(f"### md5 `{d['md5']}`")
                lines.append(f"- **{d['canonical']}** (canonical — "
                              f"{d['canonical_entity_mentions']} entity mentions in DB)")
                for dup in d["duplicates"]:
                    lines.append(f"  - {dup['filename']} "
                                 f"({dup['entity_mentions']} entity mentions) → "
                                 f"`duplicate_of: {d['canonical']}`")
                lines.append("")
        Path(args.log).write_text("\n".join(lines) + "\n")
        print(f"wrote {args.log}")

    if conn:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())