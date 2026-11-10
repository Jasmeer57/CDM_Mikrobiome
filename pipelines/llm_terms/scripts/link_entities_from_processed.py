#!/usr/bin/env python3
"""
Link Entities to Projects from Processed Files

Reads the processed JSON files from stage1_extracted_full/processed/
and creates entity-project links based on actual entity mentions per project.
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Set


def load_processed_entities(processed_dir: str) -> Dict[str, List[str]]:
    """
    Load all entities from processed JSON files.

    Args:
        processed_dir: Path to processed directory with JSON files

    Returns:
        Dictionary mapping project_id -> set of entity terms
    """
    processed_path = Path(processed_dir)
    project_entities: Dict[str, Set[str]] = {}

    json_files = list(processed_path.glob("*.json"))
    print(f"Found {len(json_files)} processed files")

    for json_file in json_files:
        # Extract project ID from filename
        project_id = json_file.stem  # e.g., PRJNA449103.json -> PRJNA449103

        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

            entities = data.get('entities', [])
            entity_terms = set()

            for entity_data in entities:
                entity_term = entity_data.get('entity', '').strip()
                if entity_term:
                    entity_terms.add(entity_term)

            project_entities[project_id] = entity_terms

        except Exception as e:
            print(f"  Error reading {json_file.name}: {e}")
            continue

    print(f"Loaded entities from {len(project_entities)} projects")
    return project_entities


def link_entities_to_projects(
    project_entities: Dict[str, List[str]],
    db_path: str
) -> None:
    """
    Link entities to projects in the database.

    Args:
        project_entities: Dictionary mapping project_id -> entity terms
        db_path: Path to SQLite database
    """
    print("Linking entities to projects...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Clear existing entity-project mentions
    cursor.execute("SELECT COUNT(*) FROM entity_project_mentions")
    existing_count = cursor.fetchone()[0]
    print(f"  Clearing {existing_count} existing links...")

    cursor.execute("DELETE FROM entity_project_mentions")
    conn.commit()

    # Build entity term -> ID mapping
    print("  Building entity term to ID mapping...")
    cursor.execute("SELECT id, term FROM entities")
    entity_id_map = {row[1]: row[0] for row in cursor.fetchall()}
    print(f"  Found {len(entity_id_map)} entities in database")

    # Get valid project IDs
    cursor.execute("SELECT project_id FROM projects")
    valid_projects = {row[0] for row in cursor.fetchall()}
    print(f"  Found {len(valid_projects)} valid projects in database")

    # Insert new links
    links_created = 0
    skipped_no_project = 0
    skipped_no_entity = 0
    total_entities = 0

    for project_id, entity_terms in project_entities.items():
        # Check if project exists in database
        if project_id not in valid_projects:
            skipped_no_project += 1
            continue

        for entity_term in entity_terms:
            total_entities += 1

            # Look up entity ID
            entity_id = entity_id_map.get(entity_term)
            if not entity_id:
                skipped_no_entity += 1
                continue

            # Insert link
            try:
                cursor.execute("""
                    INSERT INTO entity_project_mentions
                    (entity_id, project_id, mention_type)
                    VALUES (?, ?, ?)
                """, (entity_id, project_id, 'extracted_from_paper'))
                links_created += 1
            except Exception as e:
                pass

        # Commit in batches
        if links_created % 10000 == 0:
            conn.commit()
            print(f"  Progress: {links_created:,} links created...")

    conn.commit()

    print(f"\nLinking complete!")
    print(f"  Total entity mentions in files: {total_entities:,}")
    print(f"  Links created: {links_created:,}")
    print(f"  Skipped (project not in DB): {skipped_no_project}")
    print(f"  Skipped (entity not in DB): {skipped_no_entity:,}")

    # Verification
    cursor.execute("SELECT COUNT(*) FROM entity_project_mentions")
    total_links = cursor.fetchone()[0]

    print(f"\nTotal entity-project mentions in database: {total_links:,}")

    # Show top projects by entity mentions
    cursor.execute("""
        SELECT
            epm.project_id,
            p.condition,
            COUNT(DISTINCT epm.entity_id) as entity_count
        FROM entity_project_mentions epm
        LEFT JOIN projects p ON epm.project_id = p.project_id
        GROUP BY epm.project_id
        ORDER BY entity_count DESC
        LIMIT 10
    """)

    print("\nTop 10 projects by entity mentions:")
    for project_id, condition, count in cursor.fetchall():
        condition_str = f" ({condition})" if condition else ""
        print(f"  {project_id}: {count} entities{condition_str}")

    conn.close()


def main():
    """Main entry point."""
    processed_dir = str(_CDM_ROOT / "pipelines/llm_terms/outputs/stage1_extracted_full/processed")
    db_path = str(_CDM_ROOT / "pipelines/llm_terms/knowledge_graph/microbiome_cdm.db")

    if not Path(processed_dir).exists():
        print(f"Error: Processed directory not found: {processed_dir}")
        return

    if not Path(db_path).exists():
        print(f"Error: Database not found: {db_path}")
        return

    # Load entity-project mappings from processed files
    project_entities = load_processed_entities(processed_dir)

    # Link entities to projects in database
    link_entities_to_projects(project_entities, db_path)


if __name__ == "__main__":
    main()
