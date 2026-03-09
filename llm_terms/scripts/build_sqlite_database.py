#!/usr/bin/env python3
"""
Main Orchestration Script for Building Microbiome SQLite Database

This script orchestrates the complete database creation process:
1. Create schema
2. Import entities
3. Import relationships
4. Import projects and samples
5. Import sample tags
6. Link entities to projects
7. Create views

Usage:
    python build_sqlite_database.py [--skip-existing]
"""

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def run_script(script_path: str, description: str) -> bool:
    """
    Run a Python script and report success/failure.

    Args:
        script_path: Path to the script to run
        description: Description of what the script does

    Returns:
        True if successful, False otherwise
    """
    print(f"\n{'='*60}")
    print(f"Step: {description}")
    print(f"Script: {script_path}")
    print(f"{'='*60}")

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            check=True,
            capture_output=False,
            text=True
        )
        print(f"✓ {description} - Complete")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {description} - Failed (exit code: {e.returncode})")
        return False
    except Exception as e:
        print(f"✗ {description} - Error: {e}")
        return False


def verify_database(db_path: str) -> None:
    """
    Run verification queries on the database.

    Args:
        db_path: Path to SQLite database
    """
    print(f"\n{'='*60}")
    print("Database Verification")
    print(f"{'='*60}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count all records
    print("\nRecord counts:")
    print("-" * 40)

    tables = [
        'entities',
        'relationships',
        'projects',
        'samples',
        'sample_tags',
        'entity_project_mentions',
        'controlled_vocabularies'
    ]

    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  {table:30s}: {count:>12,}")
        except Exception as e:
            print(f"  {table:30s}: Error - {e}")

    # Top entities by relationship count
    print("\nTop 10 entities by relationship count:")
    print("-" * 40)

    cursor.execute("""
        SELECT e.term, e.entity_type, COUNT(*) as rel_count
        FROM relationships r
        JOIN entities e ON (r.source_id = e.id OR r.target_id = e.id)
        GROUP BY e.id
        ORDER BY rel_count DESC
        LIMIT 10
    """)

    for term, entity_type, count in cursor.fetchall():
        print(f"  {term:40s} ({entity_type}): {count}")

    # Top projects by entity mentions
    print("\nTop 10 projects by entity mentions:")
    print("-" * 40)

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

    for project_id, condition, count in cursor.fetchall():
        condition_str = f" ({condition})" if condition else ""
        print(f"  {project_id}: {count} entities{condition_str}")

    # Entity type distribution
    print("\nEntity type distribution:")
    print("-" * 40)

    cursor.execute("""
        SELECT entity_type, COUNT(*) as count
        FROM entities
        GROUP BY entity_type
        ORDER BY count DESC
    """)

    for entity_type, count in cursor.fetchall():
        print(f"  {entity_type:20s}: {count:>6,}")

    # Relationship type distribution
    print("\nRelationship type distribution:")
    print("-" * 40)

    cursor.execute("""
        SELECT relationship_type, COUNT(*) as count
        FROM relationships
        GROUP BY relationship_type
        ORDER BY count DESC
    """)

    for rel_type, count in cursor.fetchall():
        print(f"  {rel_type:20s}: {count:>6,}")

    # Database file size
    db_size_mb = Path(db_path).stat().st_size / (1024 * 1024)
    print(f"\nDatabase file size: {db_size_mb:.2f} MB")

    conn.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build Microbiome CDM SQLite Database"
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip steps if data already exists in tables'
    )
    parser.add_argument(
        '--verify-only',
        action='store_true',
        help='Only run verification on existing database'
    )

    args = parser.parse_args()

    # Paths
    scripts_dir = Path(__file__).parent
    base_dir = scripts_dir.parent
    db_path = base_dir / "knowledge_graph" / "microbiome_cdm.db"

    print(f"Database path: {db_path}")
    print(f"Scripts directory: {scripts_dir}")
    print(f"Base directory: {base_dir}")

    # Verify only mode
    if args.verify_only:
        if not db_path.exists():
            print(f"Error: Database not found: {db_path}")
            sys.exit(1)

        verify_database(str(db_path))
        sys.exit(0)

    # Check if we should skip existing data
    if args.skip_existing and db_path.exists():
        print("Database exists, checking for existing data...")

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM entities")
        entity_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM projects")
        project_count = cursor.fetchone()[0]

        conn.close()

        if entity_count > 0:
            print(f"Found {entity_count} entities, skipping entity import")

        if project_count > 0:
            print(f"Found {project_count} projects, skipping metadata import")

    # Start time
    start_time = datetime.now()
    print(f"\nBuild started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Define steps
    steps = [
        ("create_sqlite_schema.py", "Create database schema"),
        ("import_entities_to_sqlite.py", "Import entities"),
        ("import_relationships_to_sqlite.py", "Import relationships"),
        ("import_metadata_to_sqlite.py", "Import metadata (projects, samples, tags)"),
        ("link_entities_projects.py", "Link entities to projects"),
        ("create_sqlite_views.py", "Create database views"),
    ]

    # Execute steps
    failed_steps = []

    for script_name, description in steps:
        script_path = scripts_dir / script_name

        if not script_path.exists():
            print(f"✗ Script not found: {script_path}")
            failed_steps.append((description, "Script not found"))
            continue

        # Skip entity import if already done
        if args.skip_existing and "entities" in description:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM entities")
            if cursor.fetchone()[0] > 8600:  # Expected ~8657 entities
                conn.close()
                print(f"Skipping: {description} (already imported)")
                continue
            conn.close()

        # Skip metadata import if already done
        if args.skip_existing and "metadata" in description:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM projects")
            if cursor.fetchone()[0] > 400:  # Expected ~482 projects
                conn.close()
                print(f"Skipping: {description} (already imported)")
                continue
            conn.close()

        success = run_script(str(script_path), description)

        if not success:
            failed_steps.append((description, "Execution failed"))
            print(f"\n⚠ Warning: {description} failed, continuing...")

    # End time
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(f"\n{'='*60}")
    print(f"Build completed at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
    print(f"{'='*60}")

    # Report failures
    if failed_steps:
        print("\n⚠ Failed steps:")
        for description, reason in failed_steps:
            print(f"  - {description}: {reason}")

    # Verify database
    if db_path.exists():
        verify_database(str(db_path))
        print(f"\n✓ Database created successfully: {db_path}")
    else:
        print(f"\n✗ Database creation failed: {db_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
