"""Generate doc-number consistency stats from the CDM SQLite DB.

Produces a JSON + human-readable report with counts that should match the
numbers cited in the manuscript. Run this after any DB rebuild to verify
consistency.

Usage:
    python -m cdm_pipeline.export.doc_stats --db cdm_output/microbiome_cdm.db
"""
import argparse
import json
import sqlite3
from pathlib import Path

from ..config import CDM_OUTPUT_DIR


def generate_stats(db_path: Path) -> dict:
    """Query the DB and return a stats dict."""
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    stats = {}

    # Entity counts
    c.execute("SELECT COUNT(*) FROM entities")
    stats["total_entities"] = c.fetchone()[0]

    c.execute("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC")
    stats["entities_by_type"] = dict(c.fetchall())

    # NER source counts
    ner_sources = ["ner_gliner", "ner_pubmedbert", "ner_pubtator3", "ner_qwen", "ner_scispacy"]
    stats["entities_by_ner_source"] = {}
    for src in ner_sources:
        c.execute(f"SELECT COUNT(*) FROM entities WHERE {src} = 1")
        stats["entities_by_ner_source"][src] = c.fetchone()[0]

    # Relationship counts
    c.execute("SELECT COUNT(*) FROM relationships")
    stats["total_relationships"] = c.fetchone()[0]

    c.execute("SELECT validation_status, COUNT(*) FROM relationships GROUP BY validation_status")
    stats["relationships_by_validation"] = dict(c.fetchall())

    c.execute("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC")
    stats["relationships_by_type"] = dict(c.fetchall())

    c.execute("SELECT source_db, COUNT(*) FROM relationships GROUP BY source_db")
    stats["relationships_by_source"] = dict(c.fetchall())

    # CV mapping counts
    c.execute("SELECT COUNT(*) FROM controlled_vocabularies")
    stats["total_cv_mappings"] = c.fetchone()[0]

    c.execute("SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies GROUP BY vocabulary_name ORDER BY COUNT(*) DESC LIMIT 20")
    stats["cv_by_vocabulary"] = dict(c.fetchall())

    c.execute("SELECT mapping_source, COUNT(*) FROM controlled_vocabularies GROUP BY mapping_source")
    stats["cv_by_source"] = dict(c.fetchall())

    # NCBITaxon coverage
    c.execute("""
        SELECT COUNT(DISTINCT entity_id) FROM controlled_vocabularies WHERE vocabulary_name = 'NCBITAXON'
    """)
    stats["ncbitaxon_mapped_entities"] = c.fetchone()[0]
    stats["ncbitaxon_coverage_pct"] = round(
        stats["ncbitaxon_mapped_entities"] / max(stats["total_entities"], 1) * 100, 1
    )

    # Project counts
    c.execute("SELECT COUNT(*) FROM projects")
    stats["total_projects"] = c.fetchone()[0]

    # Mention counts
    c.execute("SELECT COUNT(*) FROM entity_project_mentions")
    stats["total_mentions"] = c.fetchone()[0]

    # DB file size
    stats["db_size_mb"] = round(db_path.stat().st_size / 1024 / 1024, 1)

    conn.close()
    return stats


def format_report(stats: dict) -> str:
    """Format stats as a human-readable report."""
    lines = [
        "=" * 60,
        "Microbiome-CDM: Document Number Consistency Report",
        "=" * 60,
        f"DB size: {stats['db_size_mb']} MB",
        f"Projects: {stats['total_projects']}",
        f"Entities: {stats['total_entities']}",
        f"Relationships: {stats['total_relationships']}",
        f"CV mappings: {stats['total_cv_mappings']}",
        f"Mentions: {stats['total_mentions']}",
        "",
        "Entities by type:",
    ]
    for t, n in stats["entities_by_type"].items():
        lines.append(f"  {t}: {n}")

    lines.append("\nEntities by NER source:")
    for s, n in stats["entities_by_ner_source"].items():
        lines.append(f"  {s}: {n}")

    lines.append("\nRelationships by type:")
    for t, n in stats["relationships_by_type"].items():
        lines.append(f"  {t}: {n}")

    lines.append("\nRelationships by validation status:")
    for t, n in stats["relationships_by_validation"].items():
        lines.append(f"  {t}: {n}")

    lines.append("\nRelationships by source:")
    for t, n in stats["relationships_by_source"].items():
        lines.append(f"  {t}: {n}")

    lines.append(f"\nNCBITaxon coverage: {stats['ncbitaxon_mapped_entities']} / "
                 f"{stats['total_entities']} ({stats['ncbitaxon_coverage_pct']}%)")

    lines.append("\nCV by vocabulary (top 20):")
    for v, n in stats["cv_by_vocabulary"].items():
        lines.append(f"  {v}: {n}")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    p = argparse.ArgumentParser(description="Generate doc-number consistency stats from CDM DB")
    p.add_argument("--db", type=Path, default=CDM_OUTPUT_DIR / "microbiome_cdm.db")
    p.add_argument("--out", type=Path, default=CDM_OUTPUT_DIR / "doc_stats.json")
    args = p.parse_args()

    stats = generate_stats(args.db)
    args.out.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(format_report(stats))
    print(f"\nJSON saved to {args.out}")
