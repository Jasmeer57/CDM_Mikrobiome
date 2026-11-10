#!/usr/bin/env python3
"""Remove 818 paper_count=0 PubMedBERT artifact entities from the v2.1.1-clean DB.

Operates on the COPY at releases/v2.1.1-clean/microbiome_cdm.db — never touches
the frozen v2.1-full-multiner original.

These entities have paper_count=0 (never mentioned in any paper) and were found
only by PubMedBERT (ner_pubmedbert=1, all other ner_* = 0). They are extraction
artifacts (truncated fragments like "e of", "Clin", "Progression of").

Cascading removals:
  - 818 entities (paper_count=0, ner_pubmedbert=1)
  - 11 relationships (all llm_extracted, artifact as target)
  - 0 edge_evidence rows (none for these 11 relationships)
  - 0 entity_project_mentions rows
  - 2,559 controlled_vocabularies rows (UMLS/ontology mappings)

Usage:
  python src/scripts/remove_artifacts.py --dry-run   # show counts only
  python src/scripts/remove_artifacts.py --apply     # execute removal

All removed rows are saved to archive/removed_artifacts/ before deletion.
SHA-256 checksums of both the frozen original and the cleaned copy are recorded.
The script runs in a single transaction — if any step fails, nothing is changed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
FROZEN_DB = REPO / "releases" / "v2.1-full-multiner" / "microbiome_cdm.db"
CLEAN_DB = REPO / "releases" / "v2.1.1-clean" / "microbiome_cdm.db"
ARCHIVE_DIR = REPO / "archive" / "removed_artifacts"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Remove PubMedBERT artifact entities")
    parser.add_argument("--dry-run", action="store_true", help="Show counts only, no changes")
    parser.add_argument("--apply", action="store_true", help="Execute removal")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: specify --dry-run or --apply", file=sys.stderr)
        sys.exit(1)
    if args.dry_run and args.apply:
        print("ERROR: cannot use --dry-run and --apply together", file=sys.stderr)
        sys.exit(1)

    if not CLEAN_DB.exists():
        print(f"ERROR: Clean DB not found: {CLEAN_DB}", file=sys.stderr)
        print(f"Create it with: cp {FROZEN_DB} {CLEAN_DB}", file=sys.stderr)
        sys.exit(1)

    # --- Record SHA-256 of frozen original ---
    frozen_sha = sha256(FROZEN_DB)
    clean_sha_before = sha256(CLEAN_DB)
    print("=" * 70)
    print("ARTIFACT REMOVAL — v2.1.1-clean")
    print("=" * 70)
    print(f"Frozen v2.1 DB:  {FROZEN_DB}")
    print(f"  SHA-256: {frozen_sha}")
    print(f"Clean DB (copy):  {CLEAN_DB}")
    print(f"  SHA-256: {clean_sha_before}")
    if frozen_sha == clean_sha_before:
        print("  [OK] Copy is identical to frozen original")
    else:
        print("  [WARNING] Copy differs from frozen original!")
    print()

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(CLEAN_DB))
    db.row_factory = sqlite3.Row

    # --- Gather artifact entity IDs ---
    artifact_ids = [
        row[0] for row in db.execute(
            "SELECT id FROM entities WHERE paper_count = 0 AND ner_pubmedbert = 1"
        )
    ]
    n_entities = len(artifact_ids)
    print(f"Artifact entities to remove: {n_entities}")

    id_placeholders = ",".join("?" * n_entities)

    # --- Count cascading rows ---
    rel_ids = [
        row[0] for row in db.execute(f"""
            SELECT DISTINCT r.id FROM relationships r
            JOIN entities e ON (r.source_id = e.id OR r.target_id = e.id)
            WHERE e.id IN ({id_placeholders})
        """, artifact_ids)
    ]
    n_relationships = len(rel_ids)
    print(f"Relationships to remove: {n_relationships}")

    rel_placeholders = ",".join("?" * n_relationships) if rel_ids else ""

    n_edge_evidence = 0
    if rel_ids:
        n_edge_evidence = db.execute(
            f"SELECT COUNT(*) FROM edge_evidence WHERE relationship_id IN ({rel_placeholders})",
            rel_ids
        ).fetchone()[0]
    print(f"edge_evidence rows to remove: {n_edge_evidence}")

    n_epm = db.execute(f"""
        SELECT COUNT(*) FROM entity_project_mentions WHERE entity_id IN ({id_placeholders})
    """, artifact_ids).fetchone()[0]
    print(f"entity_project_mentions rows to remove: {n_epm}")

    n_cv = db.execute(f"""
        SELECT COUNT(*) FROM controlled_vocabularies WHERE entity_id IN ({id_placeholders})
    """, artifact_ids).fetchone()[0]
    print(f"controlled_vocabularies rows to remove: {n_cv}")

    # --- Pre-removal counts ---
    pre_entities = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    pre_rels = db.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    pre_typed = db.execute("SELECT COUNT(*) FROM relationships WHERE source_type != 'co_occurrence'").fetchone()[0]
    pre_co_occ = db.execute("SELECT COUNT(*) FROM relationships WHERE source_type = 'co_occurrence'").fetchone()[0]
    pre_cv = db.execute("SELECT COUNT(*) FROM controlled_vocabularies").fetchone()[0]
    pre_umls = db.execute("SELECT COUNT(DISTINCT entity_id) FROM controlled_vocabularies WHERE vocabulary_name = 'UMLS'").fetchone()[0]

    print(f"\nPre-removal counts:")
    print(f"  Entities:       {pre_entities}")
    print(f"  Relationships:  {pre_rels} (typed {pre_typed}, co-occ {pre_co_occ})")
    print(f"  Controlled vocab: {pre_cv}")
    print(f"  UMLS-mapped entities: {pre_umls}")

    if args.dry_run:
        print("\n[DRY RUN] No changes made. Run with --apply to execute.")
        # Show sample artifact entities
        print("\nSample artifact entities:")
        for r in db.execute(f"""
            SELECT id, term, entity_type FROM entities
            WHERE id IN ({id_placeholders})
            ORDER BY RANDOM() LIMIT 10
        """, artifact_ids):
            print(f"  id={r['id']:6d} term='{r['term'][:50]}' type={r['entity_type']}")
        # Show the relationships
        if rel_ids:
            print("\nRelationships to remove:")
            for r in db.execute(f"""
                SELECT r.id, r.source_type, r.relationship_type,
                       s.term as subj, o.term as obj
                FROM relationships r
                JOIN entities s ON r.source_id = s.id
                JOIN entities o ON r.target_id = o.id
                WHERE r.id IN ({rel_placeholders})
                ORDER BY r.id
            """, rel_ids):
                print(f"  rel_id={r['id']} [{r['source_type']}] {r['subj']} {r['relationship_type']} {r['obj']}")
        db.close()
        return

    # --- APPLY MODE ---
    # Save artifacts to CSV
    entity_cols = [r[1] for r in db.execute("PRAGMA table_info(entities)")]
    entity_archive = ARCHIVE_DIR / "removed_entities.csv"
    with open(entity_archive, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(entity_cols)
        for row in db.execute(
            f"SELECT * FROM entities WHERE id IN ({id_placeholders}) ORDER BY id",
            artifact_ids
        ):
            writer.writerow(row)
    print(f"\nSaved {n_entities} entity rows to {entity_archive}")

    # Save removed relationships
    rel_archive = ARCHIVE_DIR / "removed_relationships.csv"
    if rel_ids:
        rel_cols = [r[1] for r in db.execute("PRAGMA table_info(relationships)")]
        with open(rel_archive, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(rel_cols)
            for row in db.execute(
                f"SELECT * FROM relationships WHERE id IN ({rel_placeholders}) ORDER BY id",
                rel_ids
            ):
                writer.writerow(row)
        print(f"Saved {n_relationships} relationship rows to {rel_archive}")

    # Save removed controlled_vocabularies
    cv_archive = ARCHIVE_DIR / "removed_controlled_vocabularies.csv"
    cv_cols = [r[1] for r in db.execute("PRAGMA table_info(controlled_vocabularies)")]
    with open(cv_archive, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cv_cols)
        for row in db.execute(
            f"SELECT * FROM controlled_vocabularies WHERE entity_id IN ({id_placeholders}) ORDER BY id",
            artifact_ids
        ):
            writer.writerow(row)
    print(f"Saved {n_cv} controlled_vocabularies rows to {cv_archive}")

    # --- Execute removal in a single transaction ---
    print("\nExecuting removal transaction...")
    try:
        db.execute("BEGIN")

        if rel_ids:
            db.execute(
                f"DELETE FROM edge_evidence WHERE relationship_id IN ({rel_placeholders})",
                rel_ids
            )
            print(f"  Deleted {n_edge_evidence} edge_evidence rows")

            db.execute(
                f"DELETE FROM relationships WHERE id IN ({rel_placeholders})",
                rel_ids
            )
            print(f"  Deleted {n_relationships} relationship rows")

        db.execute(
            f"DELETE FROM controlled_vocabularies WHERE entity_id IN ({id_placeholders})",
            artifact_ids
        )
        print(f"  Deleted {n_cv} controlled_vocabularies rows")

        db.execute(
            f"DELETE FROM entity_project_mentions WHERE entity_id IN ({id_placeholders})",
            artifact_ids
        )
        print(f"  Deleted {n_epm} entity_project_mentions rows")

        db.execute(
            f"DELETE FROM entities WHERE id IN ({id_placeholders})",
            artifact_ids
        )
        print(f"  Deleted {n_entities} entity rows")

        # Record in run_metadata
        db.execute("""
            INSERT INTO run_metadata (key, value, created_at)
            VALUES (?, ?, ?)
        """, (
            "artifact_removal_v2.1.1",
            f"Removed {n_entities} paper_count=0 PubMedBERT artifact entities, "
            f"{n_relationships} relationships, {n_cv} controlled_vocabularies rows. "
            f"Archive: archive/removed_artifacts/. "
            f"Frozen v2.1 SHA-256: {frozen_sha}",
            datetime.now().isoformat()
        ))

        db.commit()
        print("\nTransaction committed successfully.")

    except Exception as e:
        db.rollback()
        print(f"\nERROR: Transaction rolled back: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Post-removal verification ---
    print("\n=== Post-removal verification ===")
    final_entities = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    final_rels = db.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    final_typed = db.execute("SELECT COUNT(*) FROM relationships WHERE source_type != 'co_occurrence'").fetchone()[0]
    final_co_occ = db.execute("SELECT COUNT(*) FROM relationships WHERE source_type = 'co_occurrence'").fetchone()[0]
    final_cv = db.execute("SELECT COUNT(*) FROM controlled_vocabularies").fetchone()[0]
    final_umls = db.execute("SELECT COUNT(DISTINCT entity_id) FROM controlled_vocabularies WHERE vocabulary_name = 'UMLS'").fetchone()[0]

    print(f"  Entities:         {final_entities} (was {pre_entities}, removed {n_entities})")
    print(f"  Relationships:    {final_rels} (was {pre_rels}, removed {n_relationships})")
    print(f"    Typed:          {final_typed} (was {pre_typed})")
    print(f"    Co-occurrence:  {final_co_occ} (was {pre_co_occ})")
    print(f"  Controlled vocab: {final_cv} (was {pre_cv}, removed {n_cv})")
    print(f"  UMLS-mapped:      {final_umls} (was {pre_umls})")
    print(f"  UMLS rate:        {final_umls}/{final_entities} = {final_umls/final_entities*100:.1f}%")

    db.close()

    # --- Record SHA-256 of cleaned DB ---
    clean_sha_after = sha256(CLEAN_DB)
    print(f"\nSHA-256 checksums:")
    print(f"  Frozen v2.1 (unchanged):  {frozen_sha}")
    print(f"  v2.1.1-clean (before):    {clean_sha_before}")
    print(f"  v2.1.1-clean (after):      {clean_sha_after}")

    # Write checksums file
    checksum_file = ARCHIVE_DIR / "checksums.txt"
    with open(checksum_file, "w") as f:
        f.write(f"# Artifact removal checksums\n")
        f.write(f"# Date: {datetime.now().isoformat()}\n")
        f.write(f"frozen_v2.1_full_multiner  {frozen_sha}  releases/v2.1-full-multiner/microbiome_cdm.db\n")
        f.write(f"v2.1.1_clean_before        {clean_sha_before}  releases/v2.1.1-clean/microbiome_cdm.db\n")
        f.write(f"v2.1.1_clean_after         {clean_sha_after}  releases/v2.1.1-clean/microbiome_cdm.db\n")
    print(f"  Saved to {checksum_file}")

    print(f"\nv2.1.1-clean is the paper's release DB.")


if __name__ == "__main__":
    main()
