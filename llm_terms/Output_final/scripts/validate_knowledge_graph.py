#!/usr/bin/env python3
"""
Validate knowledge graph and generate quality metrics.

Performs comprehensive validation checks:
- All nodes have at least one connection (find orphans)
- No duplicate relationships
- Taxonomic hierarchies form valid DAG (no cycles)
- Confidence scores meet thresholds
- Evidence sources are valid
- Relationship integrity

Generates detailed quality report with recommendations.
"""

import json
import csv
import argparse
from typing import List, Dict, Set, Tuple
from pathlib import Path
import logging
from collections import defaultdict, Counter
from itertools import combinations

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KnowledgeGraphValidator:
    """Validate knowledge graph quality and integrity."""

    def __init__(
        self,
        nodes_file: str,
        relationships_file: str,
        entities_file: str = None
    ):
        self.nodes_file = Path(nodes_file)
        self.relationships_file = Path(relationships_file)
        self.entities_file = Path(entities_file) if entities_file else None

        self.nodes = []
        self.relationships = []
        self.entities = []

        self.validation_results = {
            'errors': [],
            'warnings': [],
            'info': [],
            'metrics': {}
        }

    def load_data(self):
        """Load nodes and relationships from CSV files."""
        logger.info("Loading data...")

        # Load nodes
        if self.nodes_file.exists():
            with open(self.nodes_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                self.nodes = list(reader)
            logger.info(f"Loaded {len(self.nodes)} nodes")
        else:
            logger.error(f"Nodes file not found: {self.nodes_file}")
            return False

        # Load relationships
        if self.relationships_file.exists():
            with open(self.relationships_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                self.relationships = list(reader)
            logger.info(f"Loaded {len(self.relationships)} relationships")
        else:
            logger.error(f"Relationships file not found: {self.relationships_file}")
            return False

        # Load entities if available
        if self.entities_file and self.entities_file.exists():
            with open(self.entities_file, 'r') as f:
                data = json.load(f)
                self.entities = data['results']
            logger.info(f"Loaded {len(self.entities)} entities")

        return True

    def check_orphan_nodes(self) -> dict:
        """Check for nodes without any connections."""
        logger.info("Checking for orphan nodes...")

        # Get all connected nodes
        connected = set()
        for rel in self.relationships:
            connected.add(rel['source'])
            connected.add(rel['target'])

        # Find orphans
        orphans = []
        for node in self.nodes:
            term = node['id:term']
            if term not in connected:
                orphans.append({
                    'term': term,
                    'entity_type': node['properties:entity_type'],
                    'paper_count': node['properties:paper_count']
                })

        self.validation_results['metrics']['orphan_count'] = len(orphans)

        if orphans:
            self.validation_results['warnings'].append(
                f"Found {len(orphans)} orphan nodes (no connections)"
            )
            self.validation_results['metrics']['orphans'] = orphans[:50]  # Limit output
        else:
            self.validation_results['info'].append("No orphan nodes found")

        return {
            'orphan_count': len(orphans),
            'orphans': orphans
        }

    def check_duplicate_relationships(self) -> dict:
        """Check for duplicate relationships."""
        logger.info("Checking for duplicate relationships...")

        # Group by (source, target, relationship_type)
        grouped = defaultdict(list)
        for i, rel in enumerate(self.relationships):
            key = (rel['source'], rel['target'], rel['relationship_type'])
            grouped[key].append(i)

        # Find duplicates
        duplicates = []
        for key, indices in grouped.items():
            if len(indices) > 1:
                duplicates.append({
                    'key': key,
                    'count': len(indices),
                    'indices': indices
                })

        self.validation_results['metrics']['duplicate_count'] = len(duplicates)

        if duplicates:
            self.validation_results['warnings'].append(
                f"Found {len(duplicates)} duplicate relationships"
            )
        else:
            self.validation_results['info'].append("No duplicate relationships found")

        return {
            'duplicate_count': len(duplicates),
            'duplicates': duplicates[:10]  # Limit output
        }

    def check_confidence_thresholds(self, min_confidence: float = 0.7) -> dict:
        """Check confidence score distribution."""
        logger.info(f"Checking confidence thresholds (min: {min_confidence})...")

        below_threshold = []
        confidence_distribution = Counter()

        for rel in self.relationships:
            conf = float(rel.get('confidence', 0.5))
            confidence_distribution[conf] += 1

            if conf < min_confidence:
                below_threshold.append({
                    'source': rel['source'],
                    'target': rel['target'],
                    'relationship_type': rel['relationship_type'],
                    'confidence': conf
                })

        self.validation_results['metrics']['below_threshold_count'] = len(below_threshold)
        self.validation_results['metrics']['confidence_distribution'] = dict(confidence_distribution)

        if below_threshold:
            self.validation_results['warnings'].append(
                f"Found {len(below_threshold)} relationships below confidence threshold {min_confidence}"
            )
        else:
            self.validation_results['info'].append(
                f"All relationships meet confidence threshold {min_confidence}"
            )

        return {
            'below_threshold_count': len(below_threshold),
            'below_threshold': below_threshold[:20]
        }

    def check_evidence_sources(self) -> dict:
        """Check evidence source distribution."""
        logger.info("Checking evidence sources...")

        source_distribution = Counter()
        invalid_sources = []

        valid_sources = {
            'UMLS', 'ChEBI', 'NCBI Taxonomy', 'Peer-Reviewed Literature',
            'OLS', 'BioPortal', 'LOINC', 'SNOMED', 'MeSH', 'GO'
        }

        for rel in self.relationships:
            source = rel.get('source_db', 'Unknown')
            source_distribution[source] += 1

            if source not in valid_sources and source != 'Unknown':
                invalid_sources.append({
                    'source': rel['source'],
                    'target': rel['target'],
                    'invalid_source': source
                })

        self.validation_results['metrics']['source_distribution'] = dict(source_distribution)
        self.validation_results['metrics']['invalid_source_count'] = len(invalid_sources)

        if invalid_sources:
            self.validation_results['warnings'].append(
                f"Found {len(invalid_sources)} relationships with invalid evidence sources"
            )

        return {
            'source_distribution': dict(source_distribution),
            'invalid_sources': invalid_sources[:10]
        }

    def check_self_loops(self) -> dict:
        """Check for self-loop relationships."""
        logger.info("Checking for self-loops...")

        self_loops = []
        for rel in self.relationships:
            if rel['source'] == rel['target']:
                self_loops.append(rel)

        self.validation_results['metrics']['self_loop_count'] = len(self_loops)

        if self_loops:
            self.validation_results['warnings'].append(
                f"Found {len(self_loops)} self-loop relationships"
            )
        else:
            self.validation_results['info'].append("No self-loop relationships found")

        return {
            'self_loop_count': len(self_loops),
            'self_loops': self_loops
        }

    def check_taxonomic_cycles(self) -> dict:
        """Check for cycles in taxonomic hierarchy."""
        logger.info("Checking for cycles in taxonomic hierarchy...")

        # Build graph for taxonomic relationships
        taxonomic_rels = [
            rel for rel in self.relationships
            if rel['relationship_type'] in ['PARENT_OF', 'CHILD_OF']
        ]

        # Create adjacency list
        graph = defaultdict(list)
        for rel in taxonomic_rels:
            graph[rel['source']].append(rel['target'])

        # Detect cycles using DFS
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node, path):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph[node]:
                if neighbor not in visited:
                    result = dfs(neighbor, path.copy())
                    if result:
                        cycles.append(result)
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)

            rec_stack.remove(node)
            return None

        for node in list(graph.keys()):
            if node not in visited:
                dfs(node, [])

        self.validation_results['metrics']['taxonomic_cycle_count'] = len(cycles)

        if cycles:
            self.validation_results['errors'].append(
                f"Found {len(cycles)} cycles in taxonomic hierarchy"
            )
        else:
            self.validation_results['info'].append("No cycles in taxonomic hierarchy")

        return {
            'cycle_count': len(cycles),
            'cycles': cycles[:5]
        }

    def check_entity_integrity(self) -> dict:
        """Check that all relationship sources/targets exist in node set."""
        logger.info("Checking entity integrity...")

        node_terms = {node['id:term'] for node in self.nodes}
        missing_sources = []
        missing_targets = []

        for rel in self.relationships:
            if rel['source'] not in node_terms:
                missing_sources.append({
                    'source': rel['source'],
                    'relationship': rel['relationship_type'],
                    'target': rel['target']
                })

            if rel['target'] not in node_terms:
                missing_targets.append({
                    'source': rel['source'],
                    'relationship': rel['relationship_type'],
                    'target': rel['target']
                })

        self.validation_results['metrics']['missing_source_count'] = len(missing_sources)
        self.validation_results['metrics']['missing_target_count'] = len(missing_targets)

        if missing_sources or missing_targets:
            self.validation_results['errors'].append(
                f"Found {len(missing_sources)} missing source entities and "
                f"{len(missing_targets)} missing target entities"
            )

        return {
            'missing_sources': missing_sources[:20],
            'missing_targets': missing_targets[:20]
        }

    def calculate_graph_metrics(self) -> dict:
        """Calculate overall graph metrics."""
        logger.info("Calculating graph metrics...")

        # Get connected entities
        connected = set()
        for rel in self.relationships:
            connected.add(rel['source'])
            connected.add(rel['target'])

        # Calculate node degrees
        node_degree = defaultdict(int)
        for rel in self.relationships:
            node_degree[rel['source']] += 1
            node_degree[rel['target']] += 1

        # Calculate average degree
        if connected:
            avg_degree = sum(node_degree.values()) / len(connected)
        else:
            avg_degree = 0

        # Calculate relationship type distribution
        rel_type_dist = Counter(rel['relationship_type'] for rel in self.relationships)

        # Calculate entity type distribution
        entity_type_dist = Counter(node['properties:entity_type'] for node in self.nodes)

        # Calculate connected components (simplified)
        visited = set()
        components = []

        def dfs_component(node, component):
            visited.add(node)
            component.add(node)

            for rel in self.relationships:
                if rel['source'] == node and rel['target'] not in visited:
                    dfs_component(rel['target'], component)
                if rel['target'] == node and rel['source'] not in visited:
                    dfs_component(rel['source'], component)

        for node in connected:
            if node not in visited:
                component = set()
                dfs_component(node, component)
                components.append(component)

        metrics = {
            'total_nodes': len(self.nodes),
            'total_edges': len(self.relationships),
            'connected_nodes': len(connected),
            'orphan_nodes': len(self.nodes) - len(connected),
            'connected_components': len(components),
            'average_degree': round(avg_degree, 2),
            'max_degree': max(node_degree.values()) if node_degree else 0,
            'relationship_type_distribution': dict(rel_type_dist),
            'entity_type_distribution': dict(entity_type_dist),
            'component_sizes': sorted([len(c) for c in components], reverse=True)[:10]
        }

        self.validation_results['metrics'].update(metrics)

        return metrics

    def generate_report(self, output_file: str = "knowledge_graph/validation_report.json"):
        """Generate validation report."""
        logger.info("=" * 60)
        logger.info("KNOWLEDGE GRAPH VALIDATION REPORT")
        logger.info("=" * 60)

        # Print summary
        metrics = self.validation_results['metrics']

        print(f"\nGraph Size:")
        print(f"  Total nodes: {metrics.get('total_nodes', 0)}")
        print(f"  Total edges: {metrics.get('total_edges', 0)}")
        print(f"  Connected nodes: {metrics.get('connected_nodes', 0)}")
        print(f"  Orphan nodes: {metrics.get('orphan_nodes', 0)}")
        print(f"  Connected components: {metrics.get('connected_components', 0)}")
        print(f"  Average degree: {metrics.get('average_degree', 0)}")

        print(f"\nQuality Metrics:")
        print(f"  Orphans: {metrics.get('orphan_count', 0)}")
        print(f"  Duplicates: {metrics.get('duplicate_count', 0)}")
        print(f"  Below confidence threshold: {metrics.get('below_threshold_count', 0)}")
        print(f"  Self-loops: {metrics.get('self_loop_count', 0)}")
        print(f"  Taxonomic cycles: {metrics.get('taxonomic_cycle_count', 0)}")
        print(f"  Missing entities: {metrics.get('missing_source_count', 0) + metrics.get('missing_target_count', 0)}")

        print(f"\nTop Relationship Types:")
        for rel_type, count in list(metrics.get('relationship_type_distribution', {}).items())[:5]:
            print(f"  {rel_type}: {count}")

        print(f"\nErrors:")
        for error in self.validation_results['errors'][:10]:
            print(f"  ❌ {error}")

        print(f"\nWarnings:")
        for warning in self.validation_results['warnings'][:10]:
            print(f"  ⚠️  {warning}")

        print(f"\nInfo:")
        for info in self.validation_results['info'][:5]:
            print(f"  ℹ️  {info}")

        # Save report to JSON
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(self.validation_results, f, indent=2)

        logger.info(f"\nSaved validation report to {output_path}")

        # Also save as markdown
        md_file = output_path.with_suffix('.md')
        self._generate_markdown_report(md_file)

    def _generate_markdown_report(self, output_file: Path):
        """Generate Markdown validation report."""
        metrics = self.validation_results['metrics']

        content = f"""# Knowledge Graph Validation Report

## Graph Statistics

- **Total Nodes**: {metrics.get('total_nodes', 0)}
- **Total Edges**: {metrics.get('total_edges', 0)}
- **Connected Nodes**: {metrics.get('connected_nodes', 0)}
- **Orphan Nodes**: {metrics.get('orphan_nodes', 0)}
- **Connected Components**: {metrics.get('connected_components', 0)}
- **Average Degree**: {metrics.get('average_degree', 0)}

## Quality Metrics

- **Orphans**: {metrics.get('orphan_count', 0)}
- **Duplicates**: {metrics.get('duplicate_count', 0)}
- **Below Confidence Threshold**: {metrics.get('below_threshold_count', 0)}
- **Self-loops**: {metrics.get('self_loop_count', 0)}
- **Taxonomic Cycles**: {metrics.get('taxonomic_cycle_count', 0)}
- **Missing Entities**: {metrics.get('missing_source_count', 0) + metrics.get('missing_target_count', 0)}

## Errors

"""

        for error in self.validation_results['errors']:
            content += f"- ❌ {error}\n"

        content += "\n## Warnings\n\n"
        for warning in self.validation_results['warnings']:
            content += f"- ⚠️  {warning}\n"

        content += "\n## Top Relationship Types\n\n"
        for rel_type, count in list(metrics.get('relationship_type_distribution', {}).items())[:10]:
            content += f"- {rel_type}: {count}\n"

        content += "\n## Entity Type Distribution\n\n"
        for etype, count in list(metrics.get('entity_type_distribution', {}).items())[:10]:
            content += f"- {etype}: {count}\n"

        with open(output_file, 'w') as f:
            f.write(content)

        logger.info(f"Saved Markdown report to {output_file}")

    def validate_all(self) -> dict:
        """Run all validation checks."""
        logger.info("=" * 60)
        logger.info("RUNNING VALIDATION CHECKS")
        logger.info("=" * 60)

        if not self.load_data():
            logger.error("Failed to load data")
            return {}

        # Run all checks
        self.check_orphan_nodes()
        self.check_duplicate_relationships()
        self.check_confidence_thresholds()
        self.check_evidence_sources()
        self.check_self_loops()
        self.check_taxonomic_cycles()
        self.check_entity_integrity()
        self.calculate_graph_metrics()

        # Generate report
        self.generate_report()

        return self.validation_results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Validate knowledge graph')
    parser.add_argument(
        '--nodes',
        default='knowledge_graph/nodes.csv',
        help='Path to nodes CSV file'
    )
    parser.add_argument(
        '--relationships',
        default='knowledge_graph/relationships.csv',
        help='Path to relationships CSV file'
    )
    parser.add_argument(
        '--entities',
        default=None,
        help='Path to entities JSON file (optional)'
    )
    parser.add_argument(
        '--output',
        default='knowledge_graph/validation_report.json',
        help='Output validation report file'
    )
    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.7,
        help='Minimum confidence threshold (default: 0.7)'
    )

    args = parser.parse_args()

    # Run validation
    validator = KnowledgeGraphValidator(
        nodes_file=args.nodes,
        relationships_file=args.relationships,
        entities_file=args.entities
    )

    validator.validate_all()


if __name__ == "__main__":
    main()
