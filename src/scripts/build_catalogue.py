#!/usr/bin/env python3
"""Regenerate data_catalogue.json from a release DB.

Usage:
    python src/scripts/build_catalogue.py \\
        --db releases/v2.0-qwen-publication/microbiome_cdm.db \\
        --out releases/v2.0-qwen-publication/data_catalogue.json \\
        --release-name v2.0-qwen-publication
"""
from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--release-name", required=True)
    p.add_argument("--build-type", default="(person)",
                   help="free-form description; usually 'Qwen-primary ...' or 'Full multi-NER + co-occurrence + KB'")
    args = p.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    def scalar(q):
        return con.execute(q).fetchone()[0]

    def pairs(q):
        return [(r[0], r[1]) for r in con.execute(q).fetchall()]

    meta = dict(con.execute("SELECT key,value FROM run_metadata").fetchall())
    # Always derive totals from the DB, not from run_metadata (which can be stale).
    total_entities = scalar("SELECT COUNT(*) FROM entities")
    total_relationships = scalar("SELECT COUNT(*) FROM relationships")
    total_edge_evidence = scalar("SELECT COUNT(DISTINCT relationship_id) FROM edge_evidence")
    total_controlled_vocabularies = scalar("SELECT COUNT(*) FROM controlled_vocabularies")
    total_mentions = scalar("SELECT COUNT(*) FROM entity_project_mentions")

    mapped = scalar("SELECT COUNT(*) FROM entities WHERE umls_mapped=1")
    mapping_rate = round(100 * mapped / total_entities, 1) if total_entities else 0.0

    ebt = dict(pairs("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type"))
    rbt = dict(pairs("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY 1"))
    rbs = dict(pairs("SELECT source_type, COUNT(*) FROM relationships GROUP BY 1"))
    rbs_db = dict(pairs(
        "SELECT source_db, COUNT(*) FROM relationships "
        "WHERE source_db IS NOT NULL GROUP BY 1"
    ))

    # Optional provenance_type column (only present on v2.0-qwen and beyond)
    cols = {r[1] for r in con.execute("PRAGMA table_info(relationships)").fetchall()}
    if "provenance_type" in cols:
        prov = dict(pairs(
            "SELECT provenance_type, COUNT(*) FROM relationships GROUP BY 1"
        ))
    else:
        prov = None

    # vocab_by_name for finer-grained breakdown (beyond the count)
    vocab_by_name = dict(pairs(
        "SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies "
        "GROUP BY 1 ORDER BY 2 DESC"
    ))

    top_freq = [
        {"term": r[0], "type": r[1], "frequency": int(r[2])}
        for r in con.execute(
            "SELECT term, entity_type, paper_count FROM entities ORDER BY paper_count DESC LIMIT 20"
        ).fetchall()
    ]
    top_map = [
        {"term": r[0], "type": r[1], "paper_count": int(r[2])}
        for r in con.execute(
            "SELECT term, entity_type, paper_count FROM entities WHERE umls_mapped=1 ORDER BY paper_count DESC LIMIT 20"
        ).fetchall()
    ]
    vocabs = [v[0] for v in pairs(
        "SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies GROUP BY 1 ORDER BY 2 DESC"
    )]

    cat = {
        "name": "Microbiome Common Data Model",
        "version": meta.get("version", "unknown"),
        "release_name": args.release_name,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_papers": scalar("SELECT COUNT(*) FROM projects"),
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "total_edge_evidence": total_edge_evidence,
        "total_controlled_vocabularies": total_controlled_vocabularies,
        "total_mentions": total_mentions,
        "mapped_entities": mapped,
        "mapping_rate": f"{mapping_rate}%",
        "cdm_types": scalar("SELECT COUNT(*) FROM entity_types"),
        "build_type": args.build_type,
        "vocabularies": vocabs,
        "entities_by_type": ebt,
        "relationships_by_type": rbt,
        "relationships_by_source": rbs,
        "relationships_by_source_db": rbs_db,
        "vocab_by_name": vocab_by_name,
        "edges_by_provenance": prov,
        "top_entities_by_frequency": top_freq,
        "top_entities_by_mapping": top_map,
    }

    Path(args.out).write_text(json.dumps(cat, indent=2) + "\n")
    print(f"wrote {args.out}: {total_entities} entities, {total_relationships} relationships, "
          f"{mapping_rate}% mapped, {len(vocabs)} vocabularies")
    return 0


if __name__ == "__main__":
    sys.exit(main())