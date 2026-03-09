#!/usr/bin/env python3
"""
Import Entities to SQLite Database

Loads 8,657 entities from cdm_entities_final_v3_embeddings.json
and inserts them into the entities and controlled_vocabularies tables.
"""

import json
import sqlite3
import re
from pathlib import Path
from typing import Any, Dict, List


def extract_project_ids(files_found_in: str, paper_location: str) -> List[str]:
    """
    Extract project IDs from files_found_in and paper_location fields.

    Args:
        files_found_in: String like "PRJNA541332.txt" or "PRJDB9469.txt"
        paper_location: String like "PRJDB10528:745" or "PRJNA476770:160"

    Returns:
        List of unique project IDs (e.g., ["PRJNA541332", "PRJDB9469"])
    """
    project_ids = set()

    # Extract from files_found_in
    if files_found_in:
        # Pattern: PRJNA12345.txt or PRJDB12345.txt
        matches = re.findall(r'(PRJ[ANEB]\d+)', files_found_in)
        project_ids.update(matches)

    # Extract from paper_location
    if paper_location:
        # Pattern: PRJDB10528:745 or PRJNA476770:160
        # Take everything before the colon
        for loc in paper_location.split(','):
            loc = loc.strip()
            if ':' in loc:
                project_id = loc.split(':')[0].strip()
                if project_id.startswith('PRJ'):
                    project_ids.add(project_id)
            elif loc.startswith('PRJ'):
                project_ids.add(loc)

    return sorted(list(project_ids))


def insert_entity(cursor: sqlite3.Cursor, entity: Dict[str, Any]) -> int:
    """
    Insert a single entity into the database.

    Args:
        cursor: SQLite cursor
        entity: Entity dictionary from JSON

    Returns:
        Entity ID
    """
    # Extract basic fields
    term = entity.get('term', '')
    entity_type = entity.get('entity_type', '')
    categories = entity.get('categories', '')
    confidence_score = entity.get('confidence_score', 0.0)
    paper_count = entity.get('paper_count', 0)
    frequency = entity.get('frequency', 0)
    definition = entity.get('definition', '')
    contextual_definition = entity.get('contextual_definition', '')
    aliases = entity.get('aliases', '')
    examples = entity.get('examples', '')
    is_core_term = entity.get('is_core_term', False)
    relevance_classification = entity.get('relevance_classification', '')
    is_computed_metric = entity.get('is_computed_metric', False)
    files_found_in = entity.get('files_found_in', '')
    paper_location = entity.get('paper_location', '')
    paper_context = entity.get('paper_context', '')
    umls_id = entity.get('UMLS_ID', '')
    omop = entity.get('OMOP', '')
    ols = entity.get('OLS', '')
    bioportal = entity.get('Bioportal', '')
    umls_mapped = entity.get('umls_mapped', False)
    umls_concepts = json.dumps(entity.get('umls_concepts', []))
    umls_best_match = json.dumps(entity.get('umls_best_match', {}))

    # Insert entity
    cursor.execute("""
        INSERT OR REPLACE INTO entities (
            term, entity_type, categories, confidence_score, paper_count, frequency,
            definition, contextual_definition, aliases, examples, is_core_term,
            relevance_classification, is_computed_metric, files_found_in,
            paper_location, paper_context, UMLS_ID, OMOP, OLS, Bioportal,
            umls_mapped, umls_concepts, umls_best_match
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        term, entity_type, categories, confidence_score, paper_count, frequency,
        definition, contextual_definition, aliases, examples, is_core_term,
        relevance_classification, is_computed_metric, files_found_in,
        paper_location, paper_context, umls_id, omop, ols, bioportal,
        umls_mapped, umls_concepts, umls_best_match
    ))

    entity_id = cursor.lastrowid

    # Insert controlled vocabulary mappings
    if umls_id:
        cursor.execute("""
            INSERT INTO controlled_vocabularies
            (entity_id, vocabulary_name, vocabulary_id, vocabulary_uri)
            VALUES (?, ?, ?, ?)
        """, (entity_id, 'UMLS', umls_id, None))

    if omop:
        cursor.execute("""
            INSERT INTO controlled_vocabularies
            (entity_id, vocabulary_name, vocabulary_id, vocabulary_uri)
            VALUES (?, ?, ?, ?)
        """, (entity_id, 'OMOP', str(omop), None))

    if ols:
        cursor.execute("""
            INSERT INTO controlled_vocabularies
            (entity_id, vocabulary_name, vocabulary_id, vocabulary_uri)
            VALUES (?, ?, ?, ?)
        """, (entity_id, 'OLS', None, ols))

    if bioportal:
        cursor.execute("""
            INSERT INTO controlled_vocabularies
            (entity_id, vocabulary_name, vocabulary_id, vocabulary_uri)
            VALUES (?, ?, ?, ?)
        """, (entity_id, 'Bioportal', None, bioportal))

    return entity_id


def insert_entity_project_links(
    cursor: sqlite3.Cursor,
    entity_id: int,
    entity: Dict[str, Any]
) -> None:
    """
    Insert entity-project mention links.

    Args:
        cursor: SQLite cursor
        entity_id: Entity ID
        entity: Entity dictionary from JSON
    """
    files_found_in = entity.get('files_found_in', '')
    paper_location = entity.get('paper_location', '')
    paper_context = entity.get('paper_context', '')

    project_ids = extract_project_ids(files_found_in, paper_location)

    for project_id in project_ids:
        # Link from files_found_in
        if files_found_in and project_id in files_found_in:
            cursor.execute("""
                INSERT OR IGNORE INTO entity_project_mentions
                (entity_id, project_id, mention_type, paper_context)
                VALUES (?, ?, ?, ?)
            """, (entity_id, project_id, 'files_found_in', paper_context))

        # Link from paper_location
        if paper_location and project_id in paper_location:
            cursor.execute("""
                INSERT OR IGNORE INTO entity_project_mentions
                (entity_id, project_id, mention_type, paper_context)
                VALUES (?, ?, ?, ?)
            """, (entity_id, project_id, 'paper_location', paper_context))


def import_entities(
    json_path: str,
    db_path: str,
    batch_size: int = 100
) -> None:
    """
    Import all entities from JSON to SQLite.

    Args:
        json_path: Path to entities JSON file
        db_path: Path to SQLite database
        batch_size: Number of entities per commit batch
    """
    print(f"Loading entities from: {json_path}")

    with open(json_path, 'r') as f:
        data = json.load(f)

    entities = data.get('results', [])
    total = len(entities)

    print(f"Found {total} entities to import")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    imported = 0
    with_vocab_links = 0
    with_project_links = 0

    for i, entity in enumerate(entities, 1):
        try:
            entity_id = insert_entity(cursor, entity)
            imported += 1

            # Check for vocabulary links
            if (entity.get('UMLS_ID') or entity.get('OMOP') or
                entity.get('OLS') or entity.get('Bioportal')):
                with_vocab_links += 1

            # Insert project links
            insert_entity_project_links(cursor, entity_id, entity)

            # Check for project links
            if entity.get('files_found_in') or entity.get('paper_location'):
                with_project_links += 1

            # Commit in batches
            if i % batch_size == 0:
                conn.commit()
                print(f"  Progress: {i}/{total} ({100*i/total:.1f}%)")

        except Exception as e:
            print(f"  Error importing entity '{entity.get('term', 'unknown')}': {e}")
            continue

    # Final commit
    conn.commit()

    # Print statistics
    print(f"\nImport complete!")
    print(f"  Entities imported: {imported}")
    print(f"  With vocabulary links: {with_vocab_links}")
    print(f"  With project links: {with_project_links}")

    # Verify counts
    cursor.execute("SELECT COUNT(*) FROM entities")
    entity_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM controlled_vocabularies")
    cv_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM entity_project_mentions")
    link_count = cursor.fetchone()[0]

    print(f"\nDatabase verification:")
    print(f"  Total entities in DB: {entity_count}")
    print(f"  Total vocabulary mappings: {cv_count}")
    print(f"  Total entity-project links: {link_count}")

    conn.close()


def main():
    """Main entry point."""
    base_dir = Path(__file__).parent.parent

    json_path = base_dir / "knowledge_graph" / "cdm_entities_final_v3_embeddings.json"
    db_path = base_dir / "knowledge_graph" / "microbiome_cdm.db"

    if not json_path.exists():
        print(f"Error: Entities file not found: {json_path}")
        return

    import_entities(str(json_path), str(db_path))


if __name__ == "__main__":
    main()
