#!/usr/bin/env python3
"""Regenerate db_statistics.json from a release DB.

Reads the same numbers as data_catalogue.json plus a few extras
(entities_by_type, vocab_by_name, evidence coverage).
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
    p.add_argument("--build-type", default="(regenerated)")
    args = p.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    def scalar(q):
        return con.execute(q).fetchone()[0]

    def pairs(q):
        return [(r[0], int(r[1])) for r in con.execute(q).fetchall()]

    meta = dict(con.execute("SELECT key,value FROM run_metadata").fetchall())
    total_entities = int(meta.get("total_entities", scalar("SELECT COUNT(*) FROM entities")))
    total_rels = int(meta.get("total_relationships", scalar("SELECT COUNT(*) FROM relationships")))

    ebt = dict(pairs("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type"))
    rbt = dict(pairs("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY 1"))
    rbs_db = dict(pairs(
        "SELECT source_db, COUNT(*) FROM relationships "
        "WHERE source_db IS NOT NULL GROUP BY 1"
    ))
    rbs_type = dict(pairs("SELECT source_type, COUNT(*) FROM relationships GROUP BY 1"))
    vocab_by_name = dict(pairs(
        "SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies "
        "GROUP BY 1 ORDER BY 2 DESC"
    ))

    mapped = scalar("SELECT COUNT(*) FROM entities WHERE umls_mapped=1")
    n_with_ev = scalar("SELECT COUNT(DISTINCT relationship_id) FROM edge_evidence")
    n_orphans = scalar("""
        SELECT COUNT(*) FROM relationships r
        LEFT JOIN edge_evidence e ON e.relationship_id = r.id
        WHERE e.relationship_id IS NULL
    """)

    stats = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "database": Path(args.db).name,
        "release_name": args.release_name,
        "build_type": args.build_type,
        "version": meta.get("version", "unknown"),
        "build_timestamp": meta.get("build_timestamp"),
        "total_entities": total_entities,
        "total_relationships": total_rels,
        "entity_types_count": scalar("SELECT COUNT(*) FROM entity_types"),
        "umls_mapped": int(mapped),
        "umls_mapping_rate": round(100 * mapped / total_entities, 1) if total_entities else 0.0,
        "entities_by_type": ebt,
        "relationships_by_type": rbt,
        "relationships_by_source_db": rbs_db,
        "relationships_by_source_type": rbs_type,
        "vocab_by_name": vocab_by_name,
        "total_cv_entries": int(meta.get("total_controlled_vocabularies",
                                          scalar("SELECT COUNT(*) FROM controlled_vocabularies"))),
        "total_edge_evidence": int(n_with_ev),
        "edge_evidence_coverage_pct": round(100 * n_with_ev / total_rels, 1) if total_rels else 0.0,
        "relationships_without_evidence": int(n_orphans),
        "total_mentions": int(meta.get("total_mentions",
                                        scalar("SELECT COUNT(*) FROM entity_project_mentions"))),
        "projects_with_mentions": scalar(
            "SELECT COUNT(DISTINCT project_id) FROM entity_project_mentions"
        ),
    }

    Path(args.out).write_text(json.dumps(stats, indent=2) + "\n")
    print(f"wrote {args.out}: {total_entities} entities, {total_rels} relationships, "
          f"{stats['edge_evidence_coverage_pct']}% edge-evidence coverage")
    return 0


if __name__ == "__main__":
    sys.exit(main())