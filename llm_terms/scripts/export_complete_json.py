#!/usr/bin/env python3
"""
Export complete knowledge graph to JSON.

Creates a single comprehensive JSON file containing:
- All entities with full metadata
- All relationships with evidence
- All projects with metadata
- All samples with metadata
- Entity-project links
- Statistics and metadata
"""

import json
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any


def export_entities(cursor: sqlite3.Cursor) -> List[Dict]:
    """Export all entities from the database."""
    print("Exporting entities...")
    cursor.execute("""
        SELECT
            term, entity_type, categories, confidence_score,
            paper_count, frequency, definition, contextual_definition,
            aliases, examples, is_core_term, relevance_classification,
            is_computed_metric, files_found_in, paper_location, paper_context,
            UMLS_ID, OMOP, OLS, Bioportal, umls_mapped,
            umls_concepts, umls_best_match
        FROM entities
        ORDER BY term
    """)

    entities = []
    for row in cursor.fetchall():
        entity = {
            'term': row[0],
            'entity_type': row[1],
            'categories': row[2],
            'confidence_score': row[3],
            'paper_count': row[4],
            'frequency': row[5],
            'definition': row[6],
            'contextual_definition': row[7],
            'aliases': row[8],
            'examples': row[9],
            'is_core_term': bool(row[10]),
            'relevance_classification': row[11],
            'is_computed_metric': bool(row[12]),
            'files_found_in': row[13],
            'paper_location': row[14],
            'paper_context': row[15],
            'UMLS_ID': row[16],
            'OMOP': row[17],
            'OLS': row[18],
            'Bioportal': row[19],
            'umls_mapped': bool(row[20]),
            'umls_concepts': json.loads(row[21]) if row[21] else [],
            'umls_best_match': json.loads(row[22]) if row[22] else {}
        }
        entities.append(entity)

    print(f"  Exported {len(entities)} entities")
    return entities


def export_relationships(cursor: sqlite3.Cursor, relationships_csv: str) -> List[Dict]:
    """Export ALL relationships from CSV, with validation status."""
    print("Exporting all relationships from CSV...")

    # Load all relationships from original CSV
    df = pd.read_csv(relationships_csv)
    print(f"  Loaded {len(df)} relationships from CSV")

    # Build entity term -> type mapping
    cursor.execute("SELECT term, entity_type FROM entities")
    entity_types = {row[0]: row[1] for row in cursor.fetchall()}

    relationships = []
    validated_count = 0

    for _, row in df.iterrows():
        source = row.get('source', '')
        target = row.get('target', '')

        # Check if validated (both entities exist in database)
        is_validated = source in entity_types and target in entity_types
        if is_validated:
            validated_count += 1

        rel = {
            'source': source,
            'source_type': entity_types.get(source),
            'target': target,
            'target_type': entity_types.get(target),
            'relationship_type': row.get('relationship_type', 'ASSOCIATED_WITH'),
            'source_db': row.get('source_db', ''),
            'confidence': float(row['confidence']) if pd.notna(row.get('confidence')) else None,
            'evidence': row.get('evidence', ''),
            'evidence_type': row.get('evidence_type', ''),
            'mechanism': row.get('mechanism', ''),
            'ec_number': row.get('ec_number', ''),
            'kegg_pathway': row.get('kegg_pathway', ''),
            'pubmed_ids': row.get('pubmed_ids', ''),
            'paper_doi': row.get('paper_doi', ''),
            'validation_status': row.get('validation_status', ''),
            'validated_in_database': is_validated
        }
        relationships.append(rel)

    print(f"  Exported {len(relationships)} relationships ({validated_count} validated)")
    return relationships


def export_projects(cursor: sqlite3.Cursor) -> List[Dict]:
    """Export all projects."""
    print("Exporting projects...")
    cursor.execute("""
        SELECT
            project_id, link, amplicon, avg_length,
            bead_beating, kit, sample_type, condition,
            subjects, notes
        FROM projects
        ORDER BY project_id
    """)

    projects = []
    for row in cursor.fetchall():
        project = {
            'project_id': row[0],
            'link': row[1],
            'amplicon': row[2],
            'avg_length': row[3],
            'bead_beating': bool(row[4]),
            'kit': row[5],
            'sample_type': row[6],
            'condition': row[7],
            'subjects': row[8],
            'notes': row[9]
        }
        projects.append(project)

    print(f"  Exported {len(projects)} projects")
    return projects


def export_samples(cursor: sqlite3.Cursor, limit: int = None) -> List[Dict]:
    """Export all samples (with optional limit for file size)."""
    print(f"Exporting samples{' (limited)' if limit else ''}...")

    if limit:
        cursor.execute("""
            SELECT
                srs, project_id, srr, library_strategy,
                library_source, pubdate, total_bases, instrument,
                geo_loc_name, iso, region
            FROM samples
            ORDER BY project_id, srs
            LIMIT ?
        """, (limit,))
    else:
        cursor.execute("""
            SELECT
                srs, project_id, srr, library_strategy,
                library_source, pubdate, total_bases, instrument,
                geo_loc_name, iso, region
            FROM samples
            ORDER BY project_id, srs
        """)

    samples = []
    for row in cursor.fetchall():
        sample = {
            'srs': row[0],
            'project_id': row[1],
            'srr': row[2],
            'library_strategy': row[3],
            'library_source': row[4],
            'pubdate': row[5],
            'total_bases': row[6],
            'instrument': row[7],
            'geo_loc_name': row[8],
            'iso': row[9],
            'region': row[10]
        }
        samples.append(sample)

    print(f"  Exported {len(samples)} samples")
    return samples


def export_entity_project_links(cursor: sqlite3.Cursor) -> List[Dict]:
    """Export entity-project mentions."""
    print("Exporting entity-project links...")
    cursor.execute("""
        SELECT
            e.term,
            epm.project_id,
            epm.mention_type,
            epm.paper_context,
            p.condition
        FROM entity_project_mentions epm
        JOIN entities e ON epm.entity_id = e.id
        LEFT JOIN projects p ON epm.project_id = p.project_id
        ORDER BY epm.project_id, e.term
    """)

    links = []
    for row in cursor.fetchall():
        link = {
            'entity': row[0],
            'project_id': row[1],
            'mention_type': row[2],
            'paper_context': row[3],
            'project_condition': row[4]
        }
        links.append(link)

    print(f"  Exported {len(links)} entity-project links")
    return links


def export_vocabulary_mappings(cursor: sqlite3.Cursor) -> List[Dict]:
    """Export controlled vocabulary mappings."""
    print("Exporting vocabulary mappings...")
    cursor.execute("""
        SELECT
            e.term,
            cv.vocabulary_name,
            cv.vocabulary_id,
            cv.vocabulary_uri
        FROM controlled_vocabularies cv
        JOIN entities e ON cv.entity_id = e.id
        ORDER BY e.term, cv.vocabulary_name
    """)

    mappings = []
    for row in cursor.fetchall():
        mapping = {
            'entity': row[0],
            'vocabulary': row[1],
            'vocabulary_id': row[2],
            'vocabulary_uri': row[3]
        }
        mappings.append(mapping)

    print(f"  Exported {len(mappings)} vocabulary mappings")
    return mappings


def compute_statistics(cursor: sqlite3.Cursor) -> Dict:
    """Compute statistics about the knowledge graph."""
    print("Computing statistics...")

    stats = {}

    # Entity counts by type
    cursor.execute("""
        SELECT entity_type, COUNT(*) as count
        FROM entities
        GROUP BY entity_type
        ORDER BY count DESC
    """)
    stats['entity_types'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Relationship counts by type
    cursor.execute("""
        SELECT relationship_type, COUNT(*) as count
        FROM relationships
        GROUP BY relationship_type
        ORDER BY count DESC
    """)
    stats['relationship_types'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Project conditions
    cursor.execute("""
        SELECT condition, COUNT(*) as count
        FROM projects
        WHERE condition IS NOT NULL AND condition != ''
        GROUP BY condition
        ORDER BY count DESC
    """)
    stats['project_conditions'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Vocabulary mappings
    cursor.execute("""
        SELECT vocabulary_name, COUNT(*) as count
        FROM controlled_vocabularies
        GROUP BY vocabulary_name
        ORDER BY count DESC
    """)
    stats['vocabularies'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Top entities by relationship count
    cursor.execute("""
        SELECT e.term, e.entity_type, COUNT(*) as rel_count
        FROM relationships r
        JOIN entities e ON (r.source_id = e.id OR r.target_id = e.id)
        GROUP BY e.id
        ORDER BY rel_count DESC
        LIMIT 20
    """)
    stats['top_entities_by_relationships'] = [
        {'term': row[0], 'type': row[1], 'count': row[2]}
        for row in cursor.fetchall()
    ]

    # Top projects by entity count
    cursor.execute("""
        SELECT epm.project_id, p.condition,
               COUNT(DISTINCT epm.entity_id) as entity_count
        FROM entity_project_mentions epm
        LEFT JOIN projects p ON epm.project_id = p.project_id
        GROUP BY epm.project_id
        ORDER BY entity_count DESC
        LIMIT 20
    """)
    stats['top_projects_by_entities'] = [
        {'project_id': row[0], 'condition': row[1], 'entity_count': row[2]}
        for row in cursor.fetchall()
    ]

    return stats


def main():
    """Main entry point."""
    db_path = "/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/microbiome_cdm.db"
    relationships_csv = "/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/relationships_merged.csv"
    output_dir = Path("/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph")
    output_file = output_dir / "microbiome_cdm_complete.json"

    print("="*60)
    print("Exporting Microbiome CDM Knowledge Graph to JSON")
    print("="*60)

    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Export all components
    entities = export_entities(cursor)
    relationships = export_relationships(cursor, relationships_csv)
    projects = export_projects(cursor)
    samples = export_samples(cursor)  # Export all samples
    entity_project_links = export_entity_project_links(cursor)
    vocabulary_mappings = export_vocabulary_mappings(cursor)
    statistics = compute_statistics(cursor)

    conn.close()

    # Build complete JSON structure
    print("\nBuilding complete JSON structure...")
    timestamp = datetime.now().isoformat()

    complete_data = {
        'metadata': {
            'title': 'Microbiome Common Data Model Knowledge Graph',
            'version': '1.0.0',
            'generated_at': timestamp,
            'description': 'Complete knowledge graph with entities, relationships, projects, samples, and metadata derived from 168,000 samples across 482 studies',
            'source': 'Microbiome CDM Project',
            'format': 'JSON'
        },
        'statistics': {
            'total_entities': len(entities),
            'total_relationships': len(relationships),
            'total_projects': len(projects),
            'total_samples': len(samples),
            'total_entity_project_links': len(entity_project_links),
            'total_vocabulary_mappings': len(vocabulary_mappings),
            'entity_type_distribution': statistics['entity_types'],
            'relationship_type_distribution': statistics['relationship_types'],
            'project_conditions': statistics['project_conditions'],
            'vocabulary_distribution': statistics['vocabularies'],
            'top_entities_by_relationships': statistics['top_entities_by_relationships'],
            'top_projects_by_entities': statistics['top_projects_by_entities']
        },
        'entities': entities,
        'relationships': relationships,
        'projects': projects,
        'samples': samples,
        'entity_project_links': entity_project_links,
        'vocabulary_mappings': vocabulary_mappings
    }

    # Save to file
    print(f"\nSaving to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(complete_data, f, indent=2, ensure_ascii=False)

    file_size_mb = output_file.stat().st_size / (1024 * 1024)

    print("\n" + "="*60)
    print("Export Complete!")
    print("="*60)
    print(f"\nFile: {output_file}")
    print(f"Size: {file_size_mb:.2f} MB")
    print(f"\nContents:")
    print(f"  - Entities: {len(entities):,}")
    print(f"  - Relationships: {len(relationships):,}")
    print(f"  - Projects: {len(projects):,}")
    print(f"  - Samples: {len(samples):,}")
    print(f"  - Entity-Project Links: {len(entity_project_links):,}")
    print(f"  - Vocabulary Mappings: {len(vocabulary_mappings):,}")
    print("\n" + "="*60)


if __name__ == "__main__":
    main()
