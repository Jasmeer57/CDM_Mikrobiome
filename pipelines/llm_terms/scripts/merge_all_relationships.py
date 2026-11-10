#!/usr/bin/env python3
"""
Merge all relationship sources into comprehensive knowledge graph.
Includes: Taxonomic hierarchy, ChEBI metabolic relationships, UMLS relationships, curated relationships
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import pandas as pd
import json
from pathlib import Path
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_relationships(file_path: str) -> pd.DataFrame:
    """Load relationships from CSV file."""
    try:
        df = pd.read_csv(file_path)
        logger.info(f"Loaded {len(df)} relationships from {file_path}")
        return df
    except Exception as e:
        logger.warning(f"Could not load {file_path}: {e}")
        return pd.DataFrame()


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names across different sources."""
    column_mapping = {
        'confidence': 'confidence',
        'evidence': 'evidence',
        'evidence_type': 'evidence_type',
        'mechanism': 'mechanism',
        'relationship_type': 'relationship_type',
        'source': 'source',
        'target': 'target',
        'source_db': 'source_db',
        'ec_number': 'ec_number',
        'kegg_pathway': 'kegg_pathway',
        'pubmed_ids': 'pubmed_ids',
        'paper_doi': 'paper_doi',
        'validation_status': 'validation_status'
    }

    # Keep only columns that exist
    existing_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
    df = df.rename(columns=existing_cols)
    return df


def deduplicate_relationships(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate relationships keeping highest confidence."""
    if df.empty:
        return df

    # Sort by confidence descending
    df = df.sort_values('confidence', ascending=False, na_position='last')

    # Drop duplicates based on source, target, relationship_type
    deduped = df.drop_duplicates(
        subset=['source', 'target', 'relationship_type'],
        keep='first'
    )

    removed = len(df) - len(deduped)
    if removed > 0:
        logger.info(f"Removed {removed} duplicate relationships")

    return deduped


def main():
    output_dir = Path(str(_CDM_ROOT / "pipelines/llm_terms/knowledge_graph"))
    relationships_dir = output_dir / "relationships"

    all_relationships = []

    # 1. Load taxonomic hierarchy
    taxonomic = load_relationships(relationships_dir / "taxonomic_hierarchy.csv")
    if not taxonomic.empty:
        taxonomic = standardize_columns(taxonomic)
        taxonomic['validation_status'] = taxonomic.get('validation_status', 'validated')
        all_relationships.append(taxonomic)

    # 2. Load ChEBI relationships
    chebi = load_relationships(relationships_dir / "chebi_relationships.csv")
    if not chebi.empty:
        chebi = standardize_columns(chebi)
        chebi['validation_status'] = chebi.get('validation_status', 'validated')
        all_relationships.append(chebi)

    # 3. Load UMLS relationships
    umls = load_relationships(relationships_dir / "umls_relationships.csv")
    if not umls.empty:
        umls = standardize_columns(umls)
        umls['validation_status'] = umls.get('validation_status', 'validated')
        all_relationships.append(umls)

    # 4. Load curated relationships
    curated = load_relationships(relationships_dir / "curated_relationships.csv")
    if not curated.empty:
        curated = standardize_columns(curated)
        curated['validation_status'] = curated.get('validation_status', 'validated')
        all_relationships.append(curated)

    if not all_relationships:
        logger.error("No relationships loaded!")
        return

    # 5. Merge all relationships
    merged = pd.concat(all_relationships, ignore_index=True)
    logger.info(f"Total relationships before deduplication: {len(merged)}")

    # 6. Deduplicate
    merged = deduplicate_relationships(merged)
    logger.info(f"Total relationships after deduplication: {len(merged)}")

    # 7. Ensure required columns
    required_cols = ['source', 'target', 'relationship_type', 'source_db', 'confidence']
    for col in required_cols:
        if col not in merged.columns:
            logger.warning(f"Missing required column: {col}")
            if col == 'confidence':
                merged[col] = 1.0
            elif col == 'validation_status':
                merged[col] = 'validated'
            else:
                merged[col] = ''

    # 8. Fill NaN values
    merged = merged.fillna('')

    # 9. Save merged relationships
    output_file = output_dir / "relationships_merged.csv"
    merged.to_csv(output_file, index=False)
    logger.info(f"Saved {len(merged)} merged relationships to {output_file}")

    # 10. Generate statistics
    stats = {
        'total_relationships': int(len(merged)),
        'relationship_types': merged['relationship_type'].value_counts().to_dict(),
        'source_databases': merged['source_db'].value_counts().to_dict(),
        'confidence_distribution': {
            '0.6-0.7': int(((merged['confidence'] >= 0.6) & (merged['confidence'] < 0.7)).sum()),
            '0.7-0.8': int(((merged['confidence'] >= 0.7) & (merged['confidence'] < 0.8)).sum()),
            '0.8-0.9': int(((merged['confidence'] >= 0.8) & (merged['confidence'] < 0.9)).sum()),
            '0.9-1.0': int((merged['confidence'] >= 0.9).sum())
        },
        'unique_entities': int(len(set(merged['source'].tolist() + merged['target'].tolist()))),
        'validation_status': merged.get('validation_status', pd.Series()).value_counts().to_dict()
    }

    stats_file = output_dir / "relationships_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)
    logger.info(f"Saved statistics to {stats_file}")

    # Print statistics
    logger.info("\n=== Relationship Statistics ===")
    logger.info(f"Total relationships: {stats['total_relationships']}")
    logger.info(f"Unique entities: {stats['unique_entities']}")
    logger.info(f"\nRelationship types:")
    for rel_type, count in stats['relationship_types'].items():
        logger.info(f"  {rel_type}: {count}")
    logger.info(f"\nSource databases:")
    for db, count in stats['source_databases'].items():
        logger.info(f"  {db}: {count}")


if __name__ == "__main__":
    main()
