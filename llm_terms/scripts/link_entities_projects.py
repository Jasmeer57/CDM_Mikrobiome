#!/usr/bin/env python3
"""
Link Entities to Projects

Extracts project IDs from entity fields and creates
entity_project_mentions relationships.
"""

import sqlite3
import re
from pathlib import Path


def normalize_project_id(project_id: str) -> str:
    """
    Normalize and validate project ID.

    Args:
        project_id: Raw project ID string

    Returns:
        Normalized project ID or empty string if invalid
    """
    if not project_id:
        return ""

    # Remove file extension
    project_id = project_id.replace('.txt', '')

    # Extract project ID from location string (e.g., "PRJDB10528:745")
    if ':' in project_id:
        project_id = project_id.split(':')[0]

    # Validate format
    if re.match(r'^PRJ[ANEB]\d+$', project_id):
        return project_id

    return ""


def extract_projects_from_field(field_value: str) -> list:
    """
    Extract all project IDs from a field value.

    Args:
        field_value: Field content (files_found_in or paper_location)

    Returns:
        List of normalized project IDs
    """
    if not field_value:
        return []

    project_ids = set()

    # Pattern for PRJNA, PRJDB, PRJE, PRJN prefixes
    matches = re.findall(r'PRJ[ANEB]\d+', field_value)
    project_ids.update(matches)

    # Handle comma-separated values
    for part in field_value.split(','):
        part = part.strip()
        project_id = normalize_project_id(part)
        if project_id:
            project_ids.add(project_id)

    return sorted(list(project_ids))


def link_entities_to_projects(db_path: str) -> None:
    """
    Link entities to projects based on files_found_in and paper_location fields.

    Args:
        db_path: Path to SQLite database
    """
    print("Linking entities to projects...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    # Get all entities with files_found_in or paper_location
    cursor.execute("""
        SELECT id, term, files_found_in, paper_location, paper_context
        FROM entities
        WHERE files_found_in IS NOT NULL AND files_found_in != ''
           OR paper_location IS NOT NULL AND paper_location != ''
    """)

    entities = cursor.fetchall()
    print(f"Found {len(entities)} entities with project mentions")

    links_created = 0
    entities_processed = 0

    for entity_id, term, files_found_in, paper_location, paper_context in entities:
        # Extract project IDs from both fields
        project_ids = set()

        if files_found_in:
            project_ids.update(extract_projects_from_field(files_found_in))

        if paper_location:
            project_ids.update(extract_projects_from_field(paper_location))

        # Create links
        for project_id in project_ids:
            # Check if project exists
            cursor.execute("SELECT COUNT(*) FROM projects WHERE project_id = ?", (project_id,))
            if cursor.fetchone()[0] == 0:
                continue

            # Determine mention type
            mention_type = None
            if files_found_in and project_id in files_found_in:
                mention_type = 'files_found_in'
            elif paper_location and project_id in paper_location:
                mention_type = 'paper_location'

            # Insert link (ignore if exists)
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO entity_project_mentions
                    (entity_id, project_id, mention_type, paper_context)
                    VALUES (?, ?, ?, ?)
                """, (entity_id, project_id, mention_type, paper_context))
                links_created += 1
            except Exception as e:
                pass

        entities_processed += 1

        if entities_processed % 1000 == 0:
            conn.commit()
            print(f"  Progress: {entities_processed}/{len(entities)} entities processed")

    conn.commit()

    print(f"\nLinking complete!")
    print(f"  Entities processed: {entities_processed}")
    print(f"  Links created: {links_created}")

    # Verify
    cursor.execute("SELECT COUNT(*) FROM entity_project_mentions")
    total_links = cursor.fetchone()[0]

    print(f"\nTotal entity-project mentions in database: {total_links}")

    # Show top projects by entity mentions
    cursor.execute("""
        SELECT epm.project_id, p.condition, COUNT(*) as entity_count
        FROM entity_project_mentions epm
        LEFT JOIN projects p ON epm.project_id = p.project_id
        GROUP BY epm.project_id
        ORDER BY entity_count DESC
        LIMIT 10
    """)

    print("\nTop 10 projects by entity mentions:")
    for project_id, condition, count in cursor.fetchall():
        condition_str = f" ({condition})" if condition else ""
        print(f"  {project_id}{condition_str}: {count} entities")

    conn.close()


def main():
    """Main entry point."""
    base_dir = Path(__file__).parent.parent
    db_path = base_dir / "knowledge_graph" / "microbiome_cdm.db"

    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        print("Please run create_sqlite_schema.py first.")
        return

    link_entities_to_projects(str(db_path))


if __name__ == "__main__":
    main()
