"""Schema migration: add demotion tracking columns to the relationships table.

Adds three columns:
  - original_predicate:   the predicate before demotion (NULL if never demoted)
  - demotion_reason:      why it was demoted (e.g. "llm_over_interpreted", "type_pair_violation")
  - direction_demoted_to: what it was demoted to (usually "associated_with")

Usage:
  python -m cdm_pipeline.quality.schema_migration --db path/to/microbiome_cdm.db
  python -m cdm_pipeline.quality.schema_migration --db path/to/microbiome_cdm.db --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

NEW_COLUMNS = [
    ("original_predicate", "TEXT"),
    ("demotion_reason", "TEXT"),
    ("direction_demoted_to", "TEXT"),
]


def get_existing_columns(conn: sqlite3.Connection, table: str = "relationships") -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def migrate(db_path: Path, dry_run: bool = False) -> dict:
    """Add demotion tracking columns if missing. Returns a summary dict."""
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    existing = get_existing_columns(conn)

    added = []
    skipped = []
    for col_name, col_type in NEW_COLUMNS:
        if col_name in existing:
            skipped.append(col_name)
        else:
            sql = f"ALTER TABLE relationships ADD COLUMN {col_name} {col_type}"
            if not dry_run:
                conn.execute(sql)
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_relationships_{col_name} "
                    f"ON relationships({col_name})"
                )
            added.append(col_name)

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        "db": str(db_path),
        "dry_run": dry_run,
        "added": added,
        "skipped": skipped,
    }


def backup_db(db_path: Path, suffix: str = ".pre_migration.bak") -> Path:
    """Make a timestamped backup of the DB before migration."""
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = db_path.with_suffix(f".{ts}{suffix}")
    shutil.copy2(str(db_path), str(bak))
    return bak


def main():
    ap = argparse.ArgumentParser(description="Add demotion tracking columns to relationships table")
    ap.add_argument("--db", required=True, help="Path to microbiome_cdm.db")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change without modifying")
    ap.add_argument("--no-backup", action="store_true", help="Skip automatic backup")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not args.no_backup and not args.dry_run:
        bak = backup_db(db_path)
        print(f"Backup: {bak}")

    result = migrate(db_path, dry_run=args.dry_run)
    print(f"DB: {result['db']}")
    print(f"Dry run: {result['dry_run']}")
    if result["added"]:
        print(f"Added columns: {result['added']}")
    if result["skipped"]:
        print(f"Already present (skipped): {result['skipped']}")
    if not result["added"] and not result["skipped"]:
        print("No changes needed.")


if __name__ == "__main__":
    main()
