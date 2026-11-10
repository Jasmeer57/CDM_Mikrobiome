#!/usr/bin/env python3
"""
Import Relationships to SQLite Database

Loads 839 relationships from relationships_merged.csv
and inserts them into the relationships table.
"""

import csv
import sqlite3
from pathlib import Path
from typing import Dict, Optional


def get_entity_id(cursor: sqlite3.Cursor, term: str) -> Optional[int]:
    """
    Look up entity ID by term name.

    Args:
        cursor: SQLite cursor
        term: Entity term name

    Returns:
        Entity ID or None if not found
    """
    cursor.execute("SELECT id FROM entities WHERE term = ?", (term,))
    result = cursor.fetchone()
    return result[0] if result else None


def normalize_term(term: str) -> str:
    """
    Normalize entity term for lookup.

    Args:
        term: Raw term string

    Returns:
        Normalized term
    """
    if not term:
        return ""
    # Strip whitespace
    term = term.strip()
    # Remove extra quotes if present
    if term.startswith('"') and term.endswith('"'):
        term = term[1:-1]
    return term


def insert_relationship(
    cursor: sqlite3.Cursor,
    row: Dict[str, str],
    entity_id_cache: Dict[str, int]
) -> bool:
    """
    Insert a single relationship into the database.

    Args:
        cursor: SQLite cursor
        row: CSV row as dictionary
        entity_id_cache: Cache of entity term -> ID mappings

    Returns:
        True if inserted, False otherwise
    """
    # Get source and target terms
    source_term = normalize_term(row.get('source', ''))
    target_term = normalize_term(row.get('target', ''))

    if not source_term or not target_term:
        return False

    # Look up entity IDs (use cache if available)
    if source_term in entity_id_cache:
        source_id = entity_id_cache[source_term]
    else:
        source_id = get_entity_id(cursor, source_term)
        if source_id:
            entity_id_cache[source_term] = source_id

    if target_term in entity_id_cache:
        target_id = entity_id_cache[target_term]
    else:
        target_id = get_entity_id(cursor, target_term)
        if target_id:
            entity_id_cache[target_term] = target_id

    if not source_id or not target_id:
        return False

    # Extract other fields
    relationship_type = row.get('relationship_type', '')
    source_db = row.get('source_db', '')
    confidence = float(row.get('confidence', 0.0)) if row.get('confidence') else None
    evidence = row.get('evidence', '')
    evidence_type = row.get('evidence_type', '')
    mechanism = row.get('mechanism', '')
    ec_number = row.get('ec_number', '')
    kegg_pathway = row.get('kegg_pathway', '')
    pubmed_ids = row.get('pubmed_ids', '')
    paper_doi = row.get('paper_doi', '')
    validation_status = row.get('validation_status', '')

    # Insert relationship
    try:
        cursor.execute("""
            INSERT INTO relationships (
                source_id, target_id, relationship_type, source_db, confidence,
                evidence, evidence_type, mechanism, ec_number, kegg_pathway,
                pubmed_ids, paper_doi, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source_id, target_id, relationship_type, source_db, confidence,
            evidence, evidence_type, mechanism, ec_number, kegg_pathway,
            pubmed_ids, paper_doi, validation_status
        ))
        return True
    except Exception as e:
        print(f"  Error inserting relationship {source_term} -> {target_term}: {e}")
        return False


def import_relationships(
    csv_path: str,
    db_path: str,
    batch_size: int = 100
) -> None:
    """
    Import all relationships from CSV to SQLite.

    Args:
        csv_path: Path to relationships CSV file
        db_path: Path to SQLite database
        batch_size: Number of relationships per commit batch
    """
    print(f"Loading relationships from: {csv_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    # Check if entities table is populated
    cursor.execute("SELECT COUNT(*) FROM entities")
    entity_count = cursor.fetchone()[0]

    if entity_count == 0:
        print("Warning: No entities found in database. Please import entities first.")
        conn.close()
        return

    print(f"Found {entity_count} entities in database")

    entity_id_cache: Dict[str, int] = {}

    imported = 0
    skipped = 0
    total = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader, 1):
            total += 1

            if insert_relationship(cursor, row, entity_id_cache):
                imported += 1
            else:
                skipped += 1

            # Commit in batches
            if i % batch_size == 0:
                conn.commit()
                print(f"  Progress: {i} processed, {imported} imported, {skipped} skipped")

    # Final commit
    conn.commit()

    print(f"\nImport complete!")
    print(f"  Total rows in CSV: {total}")
    print(f"  Relationships imported: {imported}")
    print(f"  Relationships skipped (entities not found): {skipped}")

    # Verify counts
    cursor.execute("SELECT COUNT(*) FROM relationships")
    relationship_count = cursor.fetchone()[0]

    print(f"\nDatabase verification:")
    print(f"  Total relationships in DB: {relationship_count}")

    # Show relationship type distribution
    cursor.execute("""
        SELECT relationship_type, COUNT(*) as count
        FROM relationships
        GROUP BY relationship_type
        ORDER BY count DESC
    """)

    print("\nRelationship type distribution:")
    for rel_type, count in cursor.fetchall():
        print(f"  {rel_type}: {count}")

    conn.close()


def main():
    """Main entry point."""
    base_dir = Path(__file__).parent.parent

    csv_path = base_dir / "knowledge_graph" / "relationships_merged.csv"
    db_path = base_dir / "knowledge_graph" / "microbiome_cdm.db"

    if not csv_path.exists():
        print(f"Error: Relationships file not found: {csv_path}")
        return

    import_relationships(str(csv_path), str(db_path))


if __name__ == "__main__":
    main()
