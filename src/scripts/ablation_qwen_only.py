#!/usr/bin/env python3
"""Derive the Qwen-only, no-co-occurrence subset (v2.0 equivalent)
directly from frozen v2.1, with exact SQL and counts.

This replaces reliance on the v2.0-qwen-publication DB file for ablation.
Reports entity counts, relationship counts, and source breakdown
for the filtered subset.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB_PATH = REPO / "releases" / "v2.1-full-multiner" / "microbiome_cdm.db"


def main():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    print("=" * 70)
    print("ABLATION: Qwen-only, no-co-occurrence subset from frozen v2.1")
    print("=" * 70)
    print()

    # --- FULL v2.1 ---
    print("FULL v2.1:")
    total_entities = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    total_rels = db.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    print(f"  Entities: {total_entities}")
    print(f"  Relationships: {total_rels}")
    for r in db.execute("SELECT source_type, COUNT(*) as cnt FROM relationships GROUP BY source_type ORDER BY cnt DESC"):
        print(f"    {r['source_type']:20s} {r['cnt']}")
    print()

    # --- FILTER 1: Qwen-only entities ---
    print("FILTER 1: Entities WHERE ner_qwen = 1")
    qwen_entities = db.execute("SELECT COUNT(*) FROM entities WHERE ner_qwen = 1").fetchone()[0]
    print(f"  Qwen-found entities: {qwen_entities}")

    # Entity type distribution
    print("  By type:")
    for r in db.execute("""
        SELECT entity_type, COUNT(*) as cnt
        FROM entities WHERE ner_qwen = 1
        GROUP BY entity_type ORDER BY cnt DESC
    """):
        print(f"    {r['entity_type']:25s} {r['cnt']}")
    print()

    # --- FILTER 2: Relationships from non-co-occurrence sources ---
    print("FILTER 2: Relationships WHERE source_type != 'co_occurrence'")
    typed_rels = db.execute("SELECT COUNT(*) FROM relationships WHERE source_type != 'co_occurrence'").fetchone()[0]
    print(f"  Typed relationships (all): {typed_rels}")
    for r in db.execute("""
        SELECT source_type, COUNT(*) as cnt
        FROM relationships WHERE source_type != 'co_occurrence'
        GROUP BY source_type ORDER BY cnt DESC
    """):
        print(f"    {r['source_type']:20s} {r['cnt']}")
    print()

    # --- COMBINED: Qwen entities + typed relationships ---
    # Get Qwen entity IDs
    print("COMBINED: Qwen entities intersected with typed relationships")
    # Edges where BOTH endpoints are Qwen-found
    both_qwen = db.execute("""
        SELECT COUNT(*) FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities o ON r.target_id = o.id
        WHERE r.source_type != 'co_occurrence'
          AND s.ner_qwen = 1 AND o.ner_qwen = 1
    """).fetchone()[0]
    print(f"  Typed edges where BOTH endpoints are Qwen-found: {both_qwen}")

    for r in db.execute("""
        SELECT r.source_type, COUNT(*) as cnt
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities o ON r.target_id = o.id
        WHERE r.source_type != 'co_occurrence'
          AND s.ner_qwen = 1 AND o.ner_qwen = 1
        GROUP BY r.source_type ORDER BY cnt DESC
    """):
        print(f"    {r['source_type']:20s} {r['cnt']}")
    print()

    # --- Also check: typed edges where AT LEAST ONE endpoint is Qwen-found ---
    one_qwen = db.execute("""
        SELECT COUNT(*) FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities o ON r.target_id = o.id
        WHERE r.source_type != 'co_occurrence'
          AND (s.ner_qwen = 1 OR o.ner_qwen = 1)
    """).fetchone()[0]
    print(f"  Typed edges where AT LEAST ONE endpoint is Qwen-found: {one_qwen}")
    print()

    # --- v2.0 comparison ---
    print("v2.0-qwen-publication (for comparison):")
    v20_path = REPO / "releases" / "v2.0-qwen-publication" / "microbiome_cdm.db"
    if v20_path.exists():
        db20 = sqlite3.connect(str(v20_path))
        db20.row_factory = sqlite3.Row
        v20_ent = db20.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        v20_rel = db20.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        print(f"  Entities: {v20_ent}")
        print(f"  Relationships: {v20_rel}")
        for r in db20.execute("SELECT source_type, COUNT(*) as cnt FROM relationships GROUP BY source_type ORDER BY cnt DESC"):
            print(f"    {r['source_type']:20s} {r['cnt']}")
        # Check if v2.0 entities all have ner_qwen=1
        v20_qwen = db20.execute("SELECT COUNT(*) FROM entities WHERE ner_qwen = 1").fetchone()[0]
        v20_not_qwen = v20_ent - v20_qwen
        print(f"  ner_qwen=1: {v20_qwen}, ner_qwen=0: {v20_not_qwen}")
        db20.close()
    else:
        print("  DB not found")
    print()

    # --- Relationship type distribution for the Qwen-only subset ---
    print("Relationship type distribution (both endpoints Qwen, no co-occ):")
    for r in db.execute("""
        SELECT r.relationship_type, COUNT(*) as cnt
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities o ON r.target_id = o.id
        WHERE r.source_type != 'co_occurrence'
          AND s.ner_qwen = 1 AND o.ner_qwen = 1
        GROUP BY r.relationship_type ORDER BY cnt DESC
    """):
        print(f"    {r['relationship_type']:25s} {r['cnt']}")

    db.close()


if __name__ == "__main__":
    main()
