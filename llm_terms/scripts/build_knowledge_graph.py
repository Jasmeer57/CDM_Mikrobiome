#!/usr/bin/env python3
"""
Main pipeline script to build microbiome knowledge graph.

Orchestrates relationship extraction from multiple sources:
1. UMLS relationships (disease-chemical-organism)
2. NCBI Taxonomy hierarchies
3. ChEBI metabolic relationships
4. Paper-based relationships (LLM + regex)
5. OLS/BioPortal relationships

Merges, deduplicates, and validates all relationships.
Exports to CSV and Neo4j formats.
"""

import json
import csv
import argparse
from typing import List, Dict, Set, Tuple
from pathlib import Path
import logging
from collections import defaultdict

# Import extractors
import sys
sys.path.append(str(Path(__file__).parent))

from extract_umls_scispacy import ScispaCyUMLSExtractor
from extract_taxonomic_hierarchy import TaxonomyHierarchyExtractor
from extract_chebi_relationships import ChEBIRelationshipExtractor
from extract_paper_relationships import PaperRelationshipExtractor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KnowledgeGraphBuilder:
    """Build knowledge graph from multiple relationship sources."""

    def __init__(
        self,
        entities_file: str,
        output_dir: str = "knowledge_graph",
        skip_apis: bool = False
    ):
        self.entities_file = Path(entities_file)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.relationships_dir = self.output_dir / "relationships"
        self.relationships_dir.mkdir(parents=True, exist_ok=True)
        self.skip_apis = skip_apis

        # Load entities
        self.entities = []
        self.entity_lookup = {}
        self._load_entities()

        # Relationship storage
        self.all_relationships = []

    def _load_entities(self):
        """Load entity data and create lookup."""
        logger.info(f"Loading entities from {self.entities_file}")

        with open(self.entities_file, 'r') as f:
            data = json.load(f)
            self.entities = data['results']

        # Create term -> entity lookup
        self.entity_lookup = {e['term']: e for e in self.entities}

        logger.info(f"Loaded {len(self.entities)} entities")

    def extract_umls_relationships(self, enabled: bool = True) -> List[dict]:
        """Extract UMLS relationships using scispaCy (offline)."""
        if not enabled:
            logger.info("Skipping UMLS relationship extraction")
            return []

        logger.info("=" * 60)
        logger.info("Extracting UMLS relationships (scispaCy offline)...")
        logger.info("=" * 60)

        extractor = ScispaCyUMLSExtractor(output_dir=str(self.relationships_dir))
        relationships = extractor.process_entities(
            self.entities,
            output_file="umls_relationships.csv"
        )

        logger.info(f"Extracted {len(relationships)} UMLS relationships")
        return relationships

    def extract_taxonomic_hierarchy(self, enabled: bool = True) -> List[dict]:
        """Extract NCBI Taxonomy hierarchy."""
        if not enabled or self.skip_apis:
            logger.info("Skipping taxonomic hierarchy extraction")
            return []

        logger.info("=" * 60)
        logger.info("Extracting NCBI Taxonomy hierarchy...")
        logger.info("=" * 60)

        extractor = TaxonomyHierarchyExtractor(output_dir=str(self.relationships_dir))
        relationships = extractor.process_entities(
            self.entities,
            output_file="taxonomic_hierarchy.csv"
        )

        logger.info(f"Extracted {len(relationships)} taxonomic relationships")
        return relationships

    def extract_chebi_relationships(self, enabled: bool = True) -> List[dict]:
        """Extract ChEBI metabolic relationships."""
        if not enabled or self.skip_apis:
            logger.info("Skipping ChEBI relationship extraction")
            return []

        logger.info("=" * 60)
        logger.info("Extracting ChEBI metabolic relationships...")
        logger.info("=" * 60)

        extractor = ChEBIRelationshipExtractor(output_dir=str(self.relationships_dir))
        relationships = extractor.process_entities(
            self.entities,
            output_file="chebi_relationships.csv"
        )

        logger.info(f"Extracted {len(relationships)} ChEBI relationships")
        return relationships

    def extract_paper_relationships(
        self,
        enabled: bool = True,
        use_llm: bool = True
    ) -> List[dict]:
        """Extract relationships from paper context."""
        if not enabled:
            logger.info("Skipping paper relationship extraction")
            return []

        logger.info("=" * 60)
        logger.info("Extracting relationships from paper context...")
        logger.info("=" * 60)

        extractor = PaperRelationshipExtractor(
            output_dir=str(self.relationships_dir),
            use_llm=use_llm
        )
        relationships = extractor.process_entities(
            self.entities,
            output_file="paper_relationships.csv"
        )

        logger.info(f"Extracted {len(relationships)} paper relationships")
        return relationships

    def validate_relationship(self, rel: dict) -> Tuple[bool, str]:
        """
        Validate a relationship meets scientific standards.

        Returns: (is_valid, reason)
        """
        # 1. Source and target must exist in entity set
        if rel['source'] not in self.entity_lookup:
            return False, "Source entity not found"

        if rel['target'] not in self.entity_lookup:
            return False, "Target entity not found"

        # 2. Confidence threshold
        confidence = rel.get('confidence', 0.5)
        if confidence < 0.6:
            return False, f"Confidence too low ({confidence})"

        # 3. Must have evidence source
        source_db = rel.get('source_db', '')
        valid_sources = {
            'UMLS', 'ChEBI', 'NCBI Taxonomy', 'Peer-Reviewed Literature',
            'OLS', 'BioPortal', 'LOINC', 'SNOMED', 'MeSH', 'GO'
        }
        if source_db not in valid_sources:
            return False, f"Invalid source: {source_db}"

        # 4. Relationship type validation
        valid_rel_types = {
            'PRODUCES', 'INHIBITS', 'CAUSES', 'TREATS', 'PROTECTS_AGAINST',
            'ASSOCIATED_WITH', 'EXACERBATES', 'PARENT_OF', 'CHILD_OF',
            'INHABITS', 'PARTICIPATES_IN', 'RELATED_TO', 'DETECTS',
            'MEASURES', 'METABOLIZES', 'PART_OF_PATHWAY', 'REGULATES',
            'INTERACTS_WITH', 'IDENTIFIES'
        }
        if rel['relationship_type'] not in valid_rel_types:
            return False, f"Invalid relationship type: {rel['relationship_type']}"

        # 5. Check for self-loops
        if rel['source'] == rel['target']:
            return False, "Self-loop detected"

        return True, "Valid"

    def merge_and_deduplicate(self, relationships: List[dict]) -> List[dict]:
        """Merge relationships from multiple sources and deduplicate."""
        logger.info("Merging and deduplicating relationships...")

        # Group by (source, target, relationship_type)
        grouped = defaultdict(list)
        for rel in relationships:
            key = (rel['source'], rel['target'], rel['relationship_type'])
            grouped[key].append(rel)

        # Merge duplicate relationships
        merged = []
        for key, rels in grouped.items():
            if len(rels) == 1:
                # Single source
                merged.append(rels[0])
            else:
                # Multiple sources - merge evidence
                merged_rel = self._merge_duplicate_relationships(rels)
                merged.append(merged_rel)

        logger.info(f"Merged {len(relationships)} relationships into {len(merged)} unique relationships")
        return merged

    def _merge_duplicate_relationships(self, rels: List[dict]) -> dict:
        """Merge multiple relationships with same source-target-type."""
        # Use highest confidence
        merged = rels[0].copy()
        merged['confidence'] = max(r.get('confidence', 0.5) for r in rels)

        # Combine evidence sources
        sources = list(set(r.get('source_db', '') for r in rels))
        merged['source_db'] = ', '.join(sources)

        # Combine evidence
        evidences = [r.get('evidence', '') for r in rels if r.get('evidence')]
        merged['evidence'] = ' | '.join(evidences[:3])  # Limit to 3

        # Track all sources
        merged['all_sources'] = sources

        return merged

    def validate_all_relationships(
        self,
        relationships: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """Validate all relationships and return (valid, invalid)."""
        logger.info("Validating relationships...")

        valid = []
        invalid = []

        for rel in relationships:
            is_valid, reason = self.validate_relationship(rel)
            if is_valid:
                valid.append(rel)
            else:
                invalid.append({**rel, 'validation_error': reason})

        logger.info(f"Valid: {len(valid)}, Invalid: {len(invalid)}")

        # Save invalid for review
        if invalid:
            invalid_file = self.relationships_dir / "invalid_relationships.csv"
            self._save_to_csv(invalid, invalid_file)
            logger.info(f"Saved {len(invalid)} invalid relationships to {invalid_file}")

        return valid, invalid

    def export_nodes_csv(self, filename: str = "nodes.csv"):
        """Export entities as nodes CSV."""
        logger.info("Exporting nodes to CSV...")

        output_path = self.output_dir / filename

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'id:term', 'labels', 'properties:entity_type',
                'properties:confidence_score', 'properties:paper_count',
                'properties:definition', 'properties:UMLS_ID', 'properties:OMOP',
                'properties:OLS', 'properties:Bioportal'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for entity in self.entities:
                # Determine labels based on entity_type
                labels = self._get_labels_for_entity(entity)

                writer.writerow({
                    'id:term': entity['term'],
                    'labels': labels,
                    'properties:entity_type': entity.get('entity_type', 'UNKNOWN'),
                    'properties:confidence_score': entity.get('confidence_score', 0.0),
                    'properties:paper_count': entity.get('paper_count', 0),
                    'properties:definition': entity.get('definition', '')[:500],  # Truncate long definitions
                    'properties:UMLS_ID': entity.get('UMLS_ID', ''),
                    'properties:OMOP': entity.get('OMOP', ''),
                    'properties:OLS': entity.get('OLS', ''),
                    'properties:Bioportal': entity.get('Bioportal', '')
                })

        logger.info(f"Exported {len(self.entities)} nodes to {output_path}")

    def _get_labels_for_entity(self, entity: dict) -> str:
        """Get Neo4j node labels for an entity."""
        entity_type = entity.get('entity_type', 'ENTITY')

        # Primary label
        label_mapping = {
            'ORGANISM': 'Organism',
            'CHEMICAL': 'Chemical',
            'DISEASE': 'Disease',
            'PROTEIN': 'Protein',
            'GENE': 'Gene',
            'PATHWAY': 'Pathway',
            'LAB_METHOD': 'Method',
            'BIOMARKER': 'Biomarker',
            'PHENOTYPE': 'Phenotype',
            'ANATOMICAL': 'Anatomical',
            'CELL_TYPE': 'CellType',
        }

        primary_label = label_mapping.get(entity_type, 'Entity')

        # Add Entity as a common label for all nodes
        return f"Entity;{primary_label}"

    def export_relationships_csv(self, relationships: List[dict], filename: str = "relationships.csv"):
        """Export relationships to CSV."""
        logger.info("Exporting relationships to CSV...")

        output_path = self.output_dir / filename

        # Define all possible fields
        fieldnames = [
            'source', 'target', 'relationship_type',
            'source_db', 'confidence', 'evidence', 'evidence_type',
            'mechanism', 'pubmed_ids', 'paper_doi', 'validation_status'
        ]

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()

            for rel in relationships:
                # Add validation status
                rel['validation_status'] = rel.get('validation_status', 'validated')

                writer.writerow(rel)

        logger.info(f"Exported {len(relationships)} relationships to {output_path}")

        # Also export full version with all fields
        output_path_full = self.output_dir / filename.replace('.csv', '_full.csv')
        with open(output_path_full, 'w', newline='', encoding='utf-8') as f:
            fieldnames_full = set()
            for rel in relationships:
                fieldnames_full.update(rel.keys())

            writer = csv.DictWriter(f, fieldnames=sorted(fieldnames_full))
            writer.writeheader()
            writer.writerows(relationships)

        logger.info(f"Exported full relationships to {output_path_full}")

    def generate_statistics(self, relationships: List[dict]):
        """Generate knowledge graph statistics."""
        logger.info("=" * 60)
        logger.info("KNOWLEDGE GRAPH STATISTICS")
        logger.info("=" * 60)

        stats = {
            'total_nodes': len(self.entities),
            'total_edges': len(relationships),
            'entity_types': self._count_entity_types(),
            'relationship_types': self._count_relationship_types(relationships),
            'source_databases': self._count_source_databases(relationships),
            'confidence_distribution': self._get_confidence_distribution(relationships),
            'connected_entities': len(set(r['source'] for r in relationships) | set(r['target'] for r in relationships))
        }

        # Print statistics
        print(f"\nNodes: {stats['total_nodes']}")
        print(f"Edges: {stats['total_edges']}")
        print(f"Connected entities: {stats['connected_entities']}")
        print(f"Average degree: {stats['total_edges'] * 2 / max(stats['connected_entities'], 1):.2f}")

        print(f"\nEntity Type Distribution:")
        for etype, count in sorted(stats['entity_types'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {etype}: {count}")

        print(f"\nRelationship Type Distribution:")
        for rtype, count in sorted(stats['relationship_types'].items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {rtype}: {count}")

        print(f"\nSource Database Distribution:")
        for source, count in sorted(stats['source_databases'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {source}: {count}")

        print(f"\nConfidence Distribution:")
        for conf, count in sorted(stats['confidence_distribution'].items()):
            print(f"  {conf}: {count}")

        # Save to JSON
        stats_file = self.output_dir / "graph_stats.json"
        with open(stats_file, 'w') as f:
            json.dump(stats, f, indent=2)

        logger.info(f"\nSaved statistics to {stats_file}")

    def _count_entity_types(self) -> dict:
        """Count entities by type."""
        counts = {}
        for entity in self.entities:
            etype = entity.get('entity_type', 'Unknown')
            counts[etype] = counts.get(etype, 0) + 1
        return counts

    def _count_relationship_types(self, relationships: List[dict]) -> dict:
        """Count relationships by type."""
        counts = {}
        for rel in relationships:
            rtype = rel['relationship_type']
            counts[rtype] = counts.get(rtype, 0) + 1
        return counts

    def _count_source_databases(self, relationships: List[dict]) -> dict:
        """Count relationships by source database."""
        counts = {}
        for rel in relationships:
            source = rel.get('source_db', 'Unknown')
            counts[source] = counts.get(source, 0) + 1
        return counts

    def _get_confidence_distribution(self, relationships: List[dict]) -> dict:
        """Get confidence score distribution."""
        distribution = {'0.6-0.7': 0, '0.7-0.8': 0, '0.8-0.9': 0, '0.9-1.0': 0}

        for rel in relationships:
            conf = rel.get('confidence', 0.5)
            if conf < 0.7:
                distribution['0.6-0.7'] += 1
            elif conf < 0.8:
                distribution['0.7-0.8'] += 1
            elif conf < 0.9:
                distribution['0.8-0.9'] += 1
            else:
                distribution['0.9-1.0'] += 1

        return distribution

    def _save_to_csv(self, data: List[dict], filepath: Path):
        """Helper to save data to CSV."""
        if not data:
            return

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            fieldnames = set()
            for item in data:
                fieldnames.update(item.keys())

            writer = csv.DictWriter(f, fieldnames=sorted(fieldnames))
            writer.writeheader()
            writer.writerows(data)

    def build(
        self,
        extract_umls: bool = True,
        extract_taxonomy: bool = True,
        extract_chebi: bool = True,
        extract_papers: bool = True,
        use_llm: bool = True
    ):
        """Build the complete knowledge graph."""

        logger.info("=" * 60)
        logger.info("MICROBIOME KNOWLEDGE GRAPH BUILDER")
        logger.info("=" * 60)

        # Extract relationships from all sources
        all_relationships = []

        if extract_umls:
            all_relationships.extend(self.extract_umls_relationships())

        if extract_taxonomy:
            all_relationships.extend(self.extract_taxonomic_hierarchy())

        if extract_chebi:
            all_relationships.extend(self.extract_chebi_relationships())

        if extract_papers:
            all_relationships.extend(self.extract_paper_relationships(use_llm=use_llm))

        # Merge and deduplicate
        merged_relationships = self.merge_and_deduplicate(all_relationships)

        # Validate
        valid_relationships, invalid_relationships = self.validate_all_relationships(merged_relationships)

        # Export
        self.export_nodes_csv()
        self.export_relationships_csv(valid_relationships)

        # Generate statistics
        self.generate_statistics(valid_relationships)

        logger.info("=" * 60)
        logger.info("KNOWLEDGE GRAPH BUILD COMPLETE")
        logger.info("=" * 60)
        logger.info(f"\nOutput files:")
        logger.info(f"  Nodes: {self.output_dir / 'nodes.csv'}")
        logger.info(f"  Relationships: {self.output_dir / 'relationships.csv'}")
        logger.info(f"  Statistics: {self.output_dir / 'graph_stats.json'}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Build microbiome knowledge graph')
    parser.add_argument(
        '--entities',
        default='/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/cdm_entities_final_v3_embeddings.json',
        help='Path to entities JSON file'
    )
    parser.add_argument(
        '--output-dir',
        default='knowledge_graph',
        help='Output directory for knowledge graph'
    )
    parser.add_argument(
        '--skip-umls',
        action='store_true',
        help='Skip UMLS relationship extraction'
    )
    parser.add_argument(
        '--skip-taxonomy',
        action='store_true',
        help='Skip taxonomic hierarchy extraction'
    )
    parser.add_argument(
        '--skip-chebi',
        action='store_true',
        help='Skip ChEBI relationship extraction'
    )
    parser.add_argument(
        '--skip-papers',
        action='store_true',
        help='Skip paper relationship extraction'
    )
    parser.add_argument(
        '--skip-llm',
        action='store_true',
        help='Skip LLM-based extraction (use regex only)'
    )
    parser.add_argument(
        '--skip-apis',
        action='store_true',
        help='Skip all API calls (use offline data only)'
    )

    args = parser.parse_args()

    # Build knowledge graph
    builder = KnowledgeGraphBuilder(
        entities_file=args.entities,
        output_dir=args.output_dir,
        skip_apis=args.skip_apis
    )

    builder.build(
        extract_umls=not args.skip_umls,
        extract_taxonomy=not args.skip_taxonomy,
        extract_chebi=not args.skip_chebi,
        extract_papers=not args.skip_papers,
        use_llm=not args.skip_llm
    )


if __name__ == "__main__":
    main()
