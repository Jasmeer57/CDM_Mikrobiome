#!/usr/bin/env python3
"""
Import Metadata to SQLite Database

Loads projects, samples, and sample tags from CSV/TSV files.
- projects.csv → projects table
- sample_metadata.tsv → samples table
- tags.tsv → sample_tags table
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time

import csv
import sqlite3
from pathlib import Path
from typing import Optional


def parse_boolean(value: str) -> Optional[bool]:
    """
    Parse string to boolean.

    Args:
        value: String value (TRUE, FALSE, etc.)

    Returns:
        Boolean or None
    """
    if not value or value.strip() == '':
        return None
    return value.strip().upper() in ('TRUE', '1', 'YES', 'T', 'Y')


def import_projects(csv_path: str, db_path: str) -> int:
    """
    Import projects from CSV.

    Args:
        csv_path: Path to projects CSV file
        db_path: Path to SQLite database

    Returns:
        Number of projects imported
    """
    print(f"Loading projects from: {csv_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    imported = 0

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for row in reader:
            project_id = row.get('project', '').strip()
            if not project_id:
                continue

            link = row.get('link', '')
            amplicon = row.get('amplicon', '')
            avg_length = float(row['avg_length']) if row.get('avg_length') else None
            bead_beating = parse_boolean(row.get('bead_beating', ''))
            kit = row.get('kit', '')
            sample_type = row.get('sample_type', '')
            condition = row.get('condition', '')
            subjects = row.get('subjects', '')
            notes = row.get('notes', '')

            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO projects
                    (project_id, link, amplicon, avg_length, bead_beating, kit,
                     sample_type, condition, subjects, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    project_id, link, amplicon, avg_length, bead_beating, kit,
                    sample_type, condition, subjects, notes
                ))
                imported += 1
            except Exception as e:
                print(f"  Error importing project {project_id}: {e}")
                continue

    conn.commit()
    print(f"  Imported {imported} projects")

    conn.close()
    return imported


def import_samples(tsv_path: str, db_path: str, batch_size: int = 1000) -> int:
    """
    Import samples from TSV.

    Args:
        tsv_path: Path to sample metadata TSV file
        db_path: Path to SQLite database
        batch_size: Number of samples per commit batch

    Returns:
        Number of samples imported
    """
    print(f"Loading samples from: {tsv_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    imported = 0
    total = 0

    with open(tsv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')

        for i, row in enumerate(reader, 1):
            total += 1

            srs = row.get('srs', '').strip()
            project_id = row.get('project', '').strip()
            srr = row.get('srr', '')
            library_strategy = row.get('library_strategy', '')
            library_source = row.get('library_source', '')
            pubdate = row.get('pubdate', '')
            total_bases = int(row['total_bases']) if row.get('total_bases') else None
            instrument = row.get('instrument', '')
            geo_loc_name = row.get('geo_loc_name', '')
            iso = row.get('iso', '')
            region = row.get('region', '')

            if not srs or not project_id:
                continue

            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO samples
                    (srs, project_id, srr, library_strategy, library_source,
                     pubdate, total_bases, instrument, geo_loc_name, iso, region)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    srs, project_id, srr, library_strategy, library_source,
                    pubdate, total_bases, instrument, geo_loc_name, iso, region
                ))
                imported += 1

                # Commit in batches
                if i % batch_size == 0:
                    conn.commit()
                    print(f"  Progress: {i}/{total} ({100*i/total:.1f}%)")

            except Exception as e:
                print(f"  Error importing sample {srs}: {e}")
                continue

    conn.commit()
    print(f"  Imported {imported} samples")

    conn.close()
    return imported


def build_sample_id_map(cursor: sqlite3.Cursor) -> dict:
    """
    Build mapping from SRS ID to database sample ID.

    Args:
        cursor: SQLite cursor

    Returns:
        Dictionary mapping SRS -> sample_id
    """
    cursor.execute("SELECT srs, id FROM samples")
    return {row[0]: row[1] for row in cursor.fetchall()}


def import_sample_tags(
    tsv_path: str,
    db_path: str,
    batch_size: int = 10000
) -> int:
    """
    Import sample tags from TSV.

    Args:
        tsv_path: Path to tags TSV file
        db_path: Path to SQLite database
        batch_size: Number of tags per commit batch

    Returns:
        Number of tags imported
    """
    print(f"Loading sample tags from: {tsv_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Build sample ID mapping
    print("  Building sample ID mapping...")
    sample_id_map = build_sample_id_map(cursor)
    print(f"  Found {len(sample_id_map)} samples in database")

    imported = 0
    skipped = 0
    total = 0

    with open(tsv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')

        for i, row in enumerate(reader, 1):
            total += 1

            srs = row.get('srs', '').strip()
            tag = row.get('tag', '')
            value = row.get('value', '')

            if not srs or not tag:
                skipped += 1
                continue

            # Look up sample ID
            sample_id = sample_id_map.get(srs)
            if not sample_id:
                skipped += 1
                continue

            try:
                cursor.execute("""
                    INSERT INTO sample_tags (sample_id, tag, value)
                    VALUES (?, ?, ?)
                """, (sample_id, tag, value))
                imported += 1

                # Commit in batches
                if i % batch_size == 0:
                    conn.commit()
                    print(f"  Progress: {i:,} processed, {imported:,} imported, {skipped:,} skipped")

            except Exception as e:
                # Skip duplicates
                skipped += 1
                continue

    conn.commit()
    print(f"  Imported {imported:,} sample tags (skipped {skipped:,})")

    conn.close()
    return imported


def main():
    """Main entry point."""
    base_dir = Path(str(_CDM_ROOT / "data/168000-samples-paper"))
    kg_dir = Path(__file__).parent.parent / "knowledge_graph"

    projects_path = base_dir / "projects.csv"
    samples_path = base_dir / "sample_metadata.tsv"
    tags_path = base_dir / "tags.tsv"
    db_path = kg_dir / "microbiome_cdm.db"

    # Check if database exists
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        print("Please run create_sqlite_schema.py first.")
        return

    # Import projects
    if projects_path.exists():
        import_projects(str(projects_path), str(db_path))
    else:
        print(f"Warning: Projects file not found: {projects_path}")

    # Import samples
    if samples_path.exists():
        import_samples(str(samples_path), str(db_path))
    else:
        print(f"Warning: Samples file not found: {samples_path}")

    # Import sample tags
    if tags_path.exists():
        import_sample_tags(str(tags_path), str(db_path))
    else:
        print(f"Warning: Tags file not found: {tags_path}")

    # Final verification
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM projects")
    projects = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM samples")
    samples = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM sample_tags")
    tags = cursor.fetchone()[0]

    print("\nFinal database state:")
    print(f"  Projects: {projects:,}")
    print(f"  Samples: {samples:,}")
    print(f"  Sample tags: {tags:,}")

    conn.close()


if __name__ == "__main__":
    main()
