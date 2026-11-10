#!/usr/bin/env python3
"""
Create SQLite Database Schema for Microbiome CDM Knowledge Graph

Creates all tables, indexes, and constraints for the microbiome database.
"""

import sqlite3
import os
from pathlib import Path


def create_schema(db_path: str) -> None:
    """
    Create the complete database schema.

    Args:
        db_path: Path to the SQLite database file
    """
    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    # ========================================
    # Core Tables
    # ========================================

    # 1. Entity Types reference table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entity_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name TEXT UNIQUE NOT NULL,
            description TEXT,
            parent_type TEXT
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_types_name ON entity_types(type_name);")

    # 2. Entities table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT UNIQUE NOT NULL,
            entity_type TEXT,
            categories TEXT,
            confidence_score REAL,
            paper_count INTEGER,
            frequency INTEGER,
            definition TEXT,
            contextual_definition TEXT,
            aliases TEXT,
            examples TEXT,
            is_core_term BOOLEAN,
            relevance_classification TEXT,
            is_computed_metric BOOLEAN,
            files_found_in TEXT,
            paper_location TEXT,
            paper_context TEXT,
            UMLS_ID TEXT,
            OMOP TEXT,
            OLS TEXT,
            Bioportal TEXT,
            umls_mapped BOOLEAN,
            umls_concepts TEXT,
            umls_best_match TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_term ON entities(term);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_umls ON entities(UMLS_ID);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_omop ON entities(OMOP);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_confidence ON entities(confidence_score);")

    # 3. Relationships table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            relationship_type TEXT NOT NULL,
            source_db TEXT,
            confidence REAL,
            evidence TEXT,
            evidence_type TEXT,
            mechanism TEXT,
            ec_number TEXT,
            kegg_pathway TEXT,
            pubmed_ids TEXT,
            paper_doi TEXT,
            validation_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES entities(id),
            FOREIGN KEY (target_id) REFERENCES entities(id)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_confidence ON relationships(confidence);")

    # 4. Projects table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT UNIQUE NOT NULL,
            link TEXT,
            amplicon TEXT,
            avg_length REAL,
            bead_beating BOOLEAN,
            kit TEXT,
            sample_type TEXT,
            condition TEXT,
            subjects TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_projects_project_id ON projects(project_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_projects_condition ON projects(condition);")

    # 5. Samples table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            srs TEXT UNIQUE NOT NULL,
            project_id TEXT NOT NULL,
            srr TEXT,
            library_strategy TEXT,
            library_source TEXT,
            pubdate TEXT,
            total_bases INTEGER,
            instrument TEXT,
            geo_loc_name TEXT,
            iso TEXT,
            region TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_srs ON samples(srs);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_project ON samples(project_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_instrument ON samples(instrument);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_samples_geo ON samples(geo_loc_name);")

    # 6. Sample Tags table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sample_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sample_id) REFERENCES samples(id)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sample_tags_sample ON sample_tags(sample_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sample_tags_tag ON sample_tags(tag);")

    # 7. Entity-Project Mentions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entity_project_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            mention_type TEXT,
            paper_context TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (entity_id) REFERENCES entities(id),
            UNIQUE(entity_id, project_id, mention_type)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_project_entity ON entity_project_mentions(entity_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_project_project ON entity_project_mentions(project_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_project_type ON entity_project_mentions(mention_type);")

    # 8. Controlled Vocabularies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS controlled_vocabularies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            vocabulary_name TEXT NOT NULL,
            vocabulary_id TEXT,
            vocabulary_uri TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (entity_id) REFERENCES entities(id)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cv_entity ON controlled_vocabularies(entity_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cv_vocabulary ON controlled_vocabularies(vocabulary_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cv_vocab_id ON controlled_vocabularies(vocabulary_id);")

    # Commit schema creation
    conn.commit()

    print(f"Schema created successfully at: {db_path}")
    print("\nTables created:")
    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    ).fetchall()
    for table in tables:
        print(f"  - {table[0]}")

    print("\nIndexes created:")
    indexes = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name;"
    ).fetchall()
    for idx in indexes:
        print(f"  - {idx[0]}")

    conn.close()


def main():
    """Main entry point."""
    # Default database path
    db_path = "knowledge_graph/microbiome_cdm.db"

    create_schema(db_path)


if __name__ == "__main__":
    main()
