"""Verify rebuilt CDM database statistics."""
import sqlite3
import sys
from pathlib import Path

DB_PATH = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file()) / "paper" / "_multi_ner_runs" / "cdm_output" / "microbiome_cdm.db"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    print("=" * 60)
    print("CDM Database Verification")
    print("=" * 60)

    # Entity stats
    c.execute("SELECT COUNT(*) FROM entities")
    total_entities = c.fetchone()[0]
    print(f"\n--- Entities ({total_entities}) ---")

    c.execute("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC")
    for etype, cnt in c.fetchall():
        print(f"  {etype:25s} {cnt:6d}")

    # Mapping coverage
    c.execute("SELECT COUNT(*) FROM entities WHERE OLS IS NOT NULL AND OLS != ''")
    ols_mapped = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM entities WHERE NCBITaxon IS NOT NULL AND NCBITaxon != ''")
    ncbi_mapped = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM entities WHERE UMLS_ID IS NOT NULL AND UMLS_ID != ''")
    umls_mapped = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM entities WHERE Bioportal IS NOT NULL AND Bioportal != ''")
    bp_mapped = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM entities WHERE entity_type='ORGANISM'")
    organism_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM entities WHERE entity_type='ORGANISM' AND NCBITaxon IS NOT NULL AND NCBITaxon != ''")
    organism_ncbi = c.fetchone()[0]

    print(f"\n--- Mapping Coverage ---")
    print(f"  OLS:          {ols_mapped}/{total_entities} ({100*ols_mapped/total_entities:.1f}%)")
    print(f"  NCBITaxon:    {ncbi_mapped}/{total_entities} ({100*ncbi_mapped/total_entities:.1f}%)")
    print(f"  UMLS:         {umls_mapped}/{total_entities} ({100*umls_mapped/total_entities:.1f}%)")
    print(f"  BioPortal:    {bp_mapped}/{total_entities} ({100*bp_mapped/total_entities:.1f}%)")
    print(f"  ORGANISM→NCBITaxon: {organism_ncbi}/{organism_count} ({100*organism_ncbi/max(organism_count,1):.1f}%)")

    # Definitions
    c.execute("SELECT COUNT(*) FROM entities WHERE definition IS NOT NULL AND definition != ''")
    has_def = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM entities WHERE contextual_definition IS NOT NULL AND contextual_definition != ''")
    has_ctx = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM entities WHERE aliases IS NOT NULL AND aliases != ''")
    has_alias = c.fetchone()[0]
    print(f"\n--- Enrichment ---")
    print(f"  definition:           {has_def}/{total_entities} ({100*has_def/max(total_entities,1):.1f}%)")
    print(f"  contextual_definition:{has_ctx}/{total_entities} ({100*has_ctx/max(total_entities,1):.1f}%)")
    print(f"  aliases:              {has_alias}/{total_entities} ({100*has_alias/max(total_entities,1):.1f}%)")

    # Relationship stats
    c.execute("SELECT COUNT(*) FROM relationships")
    total_rels = c.fetchone()[0]
    print(f"\n--- Relationships ({total_rels}) ---")

    c.execute("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC")
    for rtype, cnt in c.fetchall():
        print(f"  {rtype:25s} {cnt:6d}")

    # Confidence distribution
    c.execute("""SELECT
      CASE
        WHEN confidence < 0.55 THEN '0.50-0.54'
        WHEN confidence < 0.60 THEN '0.55-0.59'
        WHEN confidence < 0.65 THEN '0.60-0.64'
        WHEN confidence < 0.70 THEN '0.65-0.69'
        WHEN confidence < 0.75 THEN '0.70-0.74'
        WHEN confidence < 0.80 THEN '0.75-0.79'
        WHEN confidence < 0.85 THEN '0.80-0.84'
        WHEN confidence < 0.90 THEN '0.85-0.89'
        WHEN confidence < 0.95 THEN '0.90-0.94'
        ELSE '0.95'
      END as bucket, COUNT(*)
    FROM relationships GROUP BY bucket ORDER BY bucket""")
    print(f"\n  Confidence distribution:")
    for bucket, cnt in c.fetchall():
        bar = "#" * min(int(cnt / max(total_rels, 1) * 100), 50)
        print(f"    {bucket:12s} {cnt:7d} {bar}")

    c.execute("SELECT MIN(confidence), MAX(confidence), AVG(confidence) FROM relationships")
    mn, mx, avg = c.fetchone()
    print(f"  min={mn}, max={mx}, avg={avg:.3f}")

    # Source DB distribution
    c.execute("SELECT source_db, COUNT(*) FROM relationships GROUP BY source_db ORDER BY COUNT(*) DESC")
    print(f"\n  Source DB:")
    for src, cnt in c.fetchall():
        print(f"    {src:30s} {cnt:7d}")

    # Validation status
    c.execute("SELECT validation_status, COUNT(*) FROM relationships GROUP BY validation_status ORDER BY COUNT(*) DESC")
    print(f"\n  Validation status:")
    for status, cnt in c.fetchall():
        print(f"    {status:30s} {cnt:7d}")

    # KB-curated edges with mechanism
    c.execute("SELECT mechanism, COUNT(*) FROM relationships WHERE mechanism IS NOT NULL AND mechanism != '' GROUP BY mechanism ORDER BY COUNT(*) DESC")
    has_mechanism = sum(cnt for _, cnt in c.fetchall()) if c.fetchone() is not None else 0
    c.execute("SELECT COUNT(*) FROM relationships WHERE mechanism IS NOT NULL AND mechanism != ''")
    mechanism_count = c.fetchone()[0]
    print(f"\n  KB-curated with mechanism: {mechanism_count}")
    c.execute("SELECT mechanism, COUNT(*) FROM relationships WHERE mechanism IS NOT NULL AND mechanism != '' GROUP BY mechanism ORDER BY COUNT(*) DESC")
    for mech, cnt in c.fetchall():
        print(f"    {mech:30s} {cnt:7d}")

    # Other tables
    c.execute("SELECT COUNT(*) FROM projects")
    print(f"\n--- Projects: {c.fetchone()[0]} ---")

    c.execute("SELECT COUNT(*) FROM entity_project_mentions")
    print(f"  Entity-project mentions: {c.fetchone()[0]}")

    c.execute("SELECT COUNT(*) FROM controlled_vocabularies")
    print(f"  Controlled vocab entries: {c.fetchone()[0]}")

    # New tables
    try:
        c.execute("SELECT COUNT(*) FROM edge_evidence")
        ev_count = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT relationship_id) FROM edge_evidence")
        ev_rels = c.fetchone()[0]
        print(f"  Edge evidence: {ev_count} rows across {ev_rels} relationships")
    except sqlite3.Error:
        print("  Edge evidence: table not found")

    try:
        c.execute("SELECT COUNT(*) FROM run_metadata")
        print(f"  Run metadata entries: {c.fetchone()[0]}")
    except sqlite3.Error:
        print("  Run metadata: table not found")

    try:
        c.execute("SELECT source_type, COUNT(*) FROM relationships GROUP BY 1 ORDER BY 2 DESC")
        print(f"\n  Source type distribution:")
        for st, cnt in c.fetchall():
            print(f"    {st or '(NULL)':30s} {cnt:7d}")
    except sqlite3.Error:
        pass

    try:
        c.execute("SELECT mapping_tier, COUNT(*) FROM controlled_vocabularies "
                   "WHERE mapping_tier IS NOT NULL GROUP BY 1 ORDER BY 1")
        print(f"\n  NCBITaxon mapping tier distribution:")
        for tier, cnt in c.fetchall():
            print(f"    tier {tier}: {cnt}")
    except sqlite3.Error:
        pass

    # DB size
    db_size = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\n  DB size: {db_size:.1f} MB")

    conn.close()
    print("=" * 60)


if __name__ == "__main__":
    main()
