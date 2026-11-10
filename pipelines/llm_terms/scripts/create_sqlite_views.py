#!/usr/bin/env python3
"""
Create SQLite Views for Common Queries

Creates useful views for querying the microbiome knowledge graph.
"""

import sqlite3
from pathlib import Path


def create_views(db_path: str) -> None:
    """
    Create all database views.

    Args:
        db_path: Path to SQLite database
    """
    print("Creating database views...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # View 1: Entity relationships with full names
    cursor.execute("DROP VIEW IF EXISTS v_entity_relationships")
    cursor.execute("""
        CREATE VIEW v_entity_relationships AS
        SELECT
            r.id as relationship_id,
            e1.term as source_term,
            e1.entity_type as source_type,
            e2.term as target_term,
            e2.entity_type as target_type,
            r.relationship_type,
            r.source_db,
            r.confidence,
            r.evidence,
            r.evidence_type,
            r.mechanism,
            r.ec_number,
            r.kegg_pathway,
            r.validation_status
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
    """)
    print("  Created: v_entity_relationships")

    # View 2: Project entities with details
    cursor.execute("DROP VIEW IF EXISTS v_project_entities")
    cursor.execute("""
        CREATE VIEW v_project_entities AS
        SELECT
            p.project_id,
            p.condition,
            p.sample_type,
            e.term,
            e.entity_type,
            e.categories,
            e.confidence_score,
            epm.mention_type,
            e.paper_context
        FROM entity_project_mentions epm
        JOIN projects p ON epm.project_id = p.project_id
        JOIN entities e ON epm.entity_id = e.id
        ORDER BY p.project_id, e.entity_type, e.term
    """)
    print("  Created: v_project_entities")

    # View 3: Sample entity counts
    cursor.execute("DROP VIEW IF EXISTS v_project_entity_counts")
    cursor.execute("""
        CREATE VIEW v_project_entity_counts AS
        SELECT
            p.project_id,
            p.condition,
            p.sample_type,
            COUNT(DISTINCT epm.entity_id) as entity_count,
            COUNT(DISTINCT CASE WHEN e.entity_type = 'ORGANISM' THEN epm.entity_id END) as organism_count,
            COUNT(DISTINCT CASE WHEN e.entity_type = 'CHEMICAL' THEN epm.entity_id END) as chemical_count,
            COUNT(DISTINCT CASE WHEN e.entity_type = 'DISEASE' THEN epm.entity_id END) as disease_count,
            COUNT(DISTINCT s.id) as sample_count
        FROM projects p
        LEFT JOIN entity_project_mentions epm ON p.project_id = epm.project_id
        LEFT JOIN entities e ON epm.entity_id = e.id
        LEFT JOIN samples s ON p.project_id = s.project_id
        GROUP BY p.project_id
        ORDER BY entity_count DESC
    """)
    print("  Created: v_project_entity_counts")

    # View 4: Disease-organism associations
    cursor.execute("DROP VIEW IF EXISTS v_disease_organisms")
    cursor.execute("""
        CREATE VIEW v_disease_organisms AS
        SELECT
            e1.term as disease,
            e2.term as organism,
            r.relationship_type,
            r.confidence,
            r.evidence,
            r.source_db
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
        WHERE e1.entity_type = 'DISEASE' AND e2.entity_type = 'ORGANISM'
           OR e2.entity_type = 'DISEASE' AND e1.entity_type = 'ORGANISM'
        ORDER BY r.confidence DESC
    """)
    print("  Created: v_disease_organisms")

    # View 5: Metabolite producers
    cursor.execute("DROP VIEW IF EXISTS v_metabolite_producers")
    cursor.execute("""
        CREATE VIEW v_metabolite_producers AS
        SELECT
            e1.term as organism,
            e2.term as metabolite,
            r.relationship_type,
            r.confidence,
            r.mechanism,
            r.ec_number,
            r.kegg_pathway
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
        WHERE r.relationship_type = 'PRODUCES'
          AND e1.entity_type = 'ORGANISM'
          AND e2.entity_type = 'CHEMICAL'
        ORDER BY r.confidence DESC, e1.term, e2.term
    """)
    print("  Created: v_metabolite_producers")

    # View 6: Entity summary with all metadata
    cursor.execute("DROP VIEW IF EXISTS v_entity_summary")
    cursor.execute("""
        CREATE VIEW v_entity_summary AS
        SELECT
            e.id,
            e.term,
            e.entity_type,
            e.categories,
            e.confidence_score,
            e.definition,
            e.UMLS_ID,
            e.OMOP,
            e.OLS,
            COUNT(DISTINCT r.id) as relationship_count,
            COUNT(DISTINCT epm.project_id) as project_mention_count,
            GROUP_CONCAT(DISTINCT epm.project_id) as projects
        FROM entities e
        LEFT JOIN relationships r ON (e.id = r.source_id OR e.id = r.target_id)
        LEFT JOIN entity_project_mentions epm ON e.id = epm.entity_id
        GROUP BY e.id
        ORDER BY relationship_count DESC, e.term
    """)
    print("  Created: v_entity_summary")

    # View 7: Samples with tags
    cursor.execute("DROP VIEW IF EXISTS v_samples_with_tags")
    cursor.execute("""
        CREATE VIEW v_samples_with_tags AS
        SELECT
            s.srs,
            s.project_id,
            p.condition,
            s.library_strategy,
            s.instrument,
            s.geo_loc_name,
            COUNT(st.id) as tag_count,
            GROUP_CONCAT(DISTINCT st.tag) as tags
        FROM samples s
        JOIN projects p ON s.project_id = p.project_id
        LEFT JOIN sample_tags st ON s.id = st.sample_id
        GROUP BY s.srs
        ORDER BY s.project_id, s.srs
    """)
    print("  Created: v_samples_with_tags")

    # View 8: Entity vocabulary mappings
    cursor.execute("DROP VIEW IF EXISTS v_entity_vocabularies")
    cursor.execute("""
        CREATE VIEW v_entity_vocabularies AS
        SELECT
            e.term,
            e.entity_type,
            cv.vocabulary_name,
            cv.vocabulary_id,
            cv.vocabulary_uri
        FROM entities e
        JOIN controlled_vocabularies cv ON e.id = cv.entity_id
        ORDER BY e.term, cv.vocabulary_name
    """)
    print("  Created: v_entity_vocabularies")

    # View 9: High-confidence relationships
    cursor.execute("DROP VIEW IF EXISTS v_high_confidence_relationships")
    cursor.execute("""
        CREATE VIEW v_high_confidence_relationships AS
        SELECT
            e1.term as source_term,
            e1.entity_type as source_type,
            e2.term as target_term,
            e2.entity_type as target_type,
            r.relationship_type,
            r.confidence,
            r.evidence,
            r.validation_status
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
        WHERE r.confidence >= 0.8
           OR r.validation_status = 'validated'
        ORDER BY r.confidence DESC, e1.term, e2.term
    """)
    print("  Created: v_high_confidence_relationships")

    conn.commit()

    # List all views
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name;"
    )
    views = cursor.fetchall()

    print(f"\nCreated {len(views)} views:")
    for view in views:
        print(f"  - {view[0]}")

    conn.close()


def main():
    """Main entry point."""
    base_dir = Path(__file__).parent.parent
    db_path = base_dir / "knowledge_graph" / "microbiome_cdm.db"

    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        print("Please run create_sqlite_schema.py first.")
        return

    create_views(str(db_path))
    print("\nViews created successfully!")


if __name__ == "__main__":
    main()
