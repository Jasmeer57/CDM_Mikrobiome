"""
Knowledge Graph Builder Module
==============================
Builds and exports knowledge graphs from entities and relationships.
Supports NetworkX for graph operations and multiple export formats.
"""

import logging
import json
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
from pathlib import Path

logger = logging.getLogger(__name__)


class KnowledgeGraphBuilder:
    """Builds knowledge graphs from biomedical entities and relationships."""

    def __init__(self):
        self.graph = None
        self.entity_index = {}
        self.relationship_index = []

    def build_graph_from_entities(
        self,
        entities: List[Dict],
        relationships: List[Dict] = None
    ) -> Dict:
        """
        Build knowledge graph from entities and optional relationships.

        Args:
            entities: List of entity dicts with 'term' and 'categories'
            relationships: Optional list of relationship dicts

        Returns:
            Graph data structure with nodes and edges
        """
        logger.info(f"Building knowledge graph from {len(entities)} entities")

        # Build graph structure
        graph_data = {
            'nodes': [],
            'edges': [],
            'metadata': {
                'scope': 'This knowledge graph models biomedical entities and their relationships.',
                'total_nodes': 0,
                'total_edges': 0,
                'node_types': {},
                'edge_types': {}
            }
        }

        # Add nodes (entities)
        node_id_map = {}
        for i, entity in enumerate(entities):
            term = entity.get('term') or entity.get('entity', '')
            if not term:
                continue

            etype = entity.get('categories') or entity.get('entity_type', 'UNKNOWN')

            node = {
                'id': f"node_{i}",
                'term': term,
                'type': etype.upper(),
                'subgraph': 'mechanism',  # Default subgraph label
                'properties': {
                    'confidence': entity.get('confidence_score', entity.get('confidence', 0.0)),
                    'definition': entity.get('definition', ''),
                    'aliases': entity.get('aliases', ''),
                    'umls_cui': entity.get('UMLS_ID', ''),
                    'omop_id': entity.get('OMOP', ''),
                    'frequency': entity.get('frequency', 0),
                    'source': entity.get('source', '')
                }
            }

            graph_data['nodes'].append(node)
            node_id_map[term] = f"node_{i}"
            graph_data['metadata']['node_types'][etype.upper()] = \
                graph_data['metadata']['node_types'].get(etype.upper(), 0) + 1

        graph_data['metadata']['total_nodes'] = len(graph_data['nodes'])

        # Add edges (relationships)
        if relationships:
            for rel in relationships:
                source = rel.get('source_entity', '')
                target = rel.get('target_entity', '')

                if source not in node_id_map or target not in node_id_map:
                    continue

                edge = {
                    'source': node_id_map[source],
                    'target': node_id_map[target],
                    'relationship': rel.get('relationship_type', 'related_to'),
                    'subgraph': 'mechanism',  # Default subgraph label
                    'properties': {
                        'confidence': rel.get('confidence', 0.0),
                        'evidence': rel.get('evidence', ''),
                        'source_context': rel.get('source_context', ''),
                        'paper_id': rel.get('paper_id', ''),
                        'evidence_type': rel.get('evidence_type', 'literature')  # Support evidence typing
                    }
                }

                graph_data['edges'].append(edge)
                rel_type = rel.get('relationship_type', 'related_to')
                graph_data['metadata']['edge_types'][rel_type] = \
                    graph_data['metadata']['edge_types'].get(rel_type, 0) + 1

        graph_data['metadata']['total_edges'] = len(graph_data['edges'])

        logger.info(f"Built graph: {graph_data['metadata']['total_nodes']} nodes, "
                   f"{graph_data['metadata']['total_edges']} edges")

        self.graph = graph_data
        return graph_data

    def build_networkx_graph(
        self,
        entities: List[Dict],
        relationships: List[Dict] = None
    ):
        """
        Build NetworkX graph object for advanced analysis.

        Requires: networkx package
        """
        try:
            import networkx as nx
        except ImportError:
            logger.error("networkx not installed. Install with: pip install networkx")
            return None

        logger.info("Building NetworkX graph")

        G = nx.DiGraph()

        # Add nodes
        for i, entity in enumerate(entities):
            term = entity.get('term') or entity.get('entity', '')
            if not term:
                continue

            etype = entity.get('categories') or entity.get('entity_type', 'UNKNOWN')

            G.add_node(
                f"node_{i}",
                label=term,
                type=etype.upper(),
                confidence=entity.get('confidence_score', entity.get('confidence', 0.0)),
                umls_cui=entity.get('UMLS_ID', ''),
                omop_id=entity.get('OMOP', '')
            )

        # Add edges
        if relationships:
            node_id_map = {
                entity.get('term', '') or entity.get('entity', ''): f"node_{i}"
                for i, entity in enumerate(entities)
            }

            for rel in relationships:
                source = rel.get('source_entity', '')
                target = rel.get('target_entity', '')

                if source not in node_id_map or target not in node_id_map:
                    continue

                G.add_edge(
                    node_id_map[source],
                    node_id_map[target],
                    relationship=rel.get('relationship_type', 'related_to'),
                    confidence=rel.get('confidence', 0.0),
                    evidence=rel.get('evidence', '')
                )

        logger.info(f"NetworkX graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        return G

    def analyze_graph(self, graph_data: Dict = None) -> Dict:
        """
        Analyze graph structure and identify key insights.

        Args:
            graph_data: Graph dict (uses self.graph if not provided)

        Returns:
            Analysis results with centrality, communities, etc.
        """
        if graph_data is None:
            graph_data = self.graph

        if not graph_data:
            logger.error("No graph to analyze")
            return {}

        try:
            import networkx as nx
        except ImportError:
            logger.warning("networkx not available, returning basic stats")
            return self._basic_analysis(graph_data)

        # Build NetworkX graph for analysis
        G = nx.DiGraph()
        for node in graph_data['nodes']:
            G.add_node(node['id'], **node.get('properties', {}))
        for edge in graph_data['edges']:
            G.add_edge(edge['source'], edge['target'],
                      relationship=edge['relationship'])

        analysis = {
            'basic_stats': {
                'nodes': G.number_of_nodes(),
                'edges': G.number_of_edges(),
                'density': nx.density(G),
                'is_connected': nx.is_connected(G.to_undirected()) if nx.is_directed(G) else nx.is_connected(G)
            }
        }

        # Centrality measures (top 10)
        if G.number_of_nodes() > 0:
            try:
                degree_centrality = nx.degree_centrality(G if not nx.is_directed(G) else G.to_undirected())
                top_central = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:10]
                analysis['top_central_nodes'] = [
                    {'node_id': nid, 'centrality': float(cent)}
                    for nid, cent in top_central
                ]
            except Exception as e:
                logger.debug(f"Could not compute centrality: {e}")

            # Connected components
            if nx.is_directed(G):
                components = nx.weakly_connected_components(G)
            else:
                components = nx.connected_components(G)
            analysis['connected_components'] = len(list(components))

        return analysis

    def _basic_analysis(self, graph_data: Dict) -> Dict:
        """Basic analysis without NetworkX."""
        node_types = Counter(n['type'] for n in graph_data['nodes'])
        edge_types = Counter(e['relationship'] for e in graph_data['edges'])

        # Find nodes with most connections
        node_connections = defaultdict(int)
        for edge in graph_data['edges']:
            node_connections[edge['source']] += 1
            node_connections[edge['target']] += 1

        top_connected = sorted(node_connections.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            'basic_stats': {
                'nodes': len(graph_data['nodes']),
                'edges': len(graph_data['edges'])
            },
            'node_type_distribution': dict(node_types),
            'edge_type_distribution': dict(edge_types),
            'top_connected_nodes': [
                {'node_id': nid, 'connections': count}
                for nid, count in top_connected
            ]
        }

    def export_graphml(self, output_path: str, graph_data: Dict = None):
        """Export graph to GraphML format (requires networkx)."""
        import re
        try:
            import networkx as nx
        except ImportError:
            logger.error("networkx required for GraphML export")
            return False

        if graph_data is None:
            graph_data = self.graph

        if not graph_data:
            logger.error("No graph to export")
            return False

        G = nx.DiGraph()
        for node in graph_data['nodes']:
            # Sanitize label - remove control characters that cause XML errors
            label = node.get('term', '')
            if isinstance(label, str):
                label = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', label)
            G.add_node(node['id'], label=label, type=node['type'])
        for edge in graph_data['edges']:
            G.add_edge(edge['source'], edge['target'], relationship=edge['relationship'])

        nx.write_graphml(G, output_path)
        logger.info(f"Exported graph to GraphML: {output_path}")
        return True

    def export_gexf(self, output_path: str, graph_data: Dict = None):
        """Export graph to GEXF format (requires networkx)."""
        import re
        try:
            import networkx as nx
        except ImportError:
            logger.error("networkx required for GEXF export")
            return False

        if graph_data is None:
            graph_data = self.graph

        if not graph_data:
            logger.error("No graph to export")
            return False

        G = nx.DiGraph()
        for node in graph_data['nodes']:
            # Sanitize label - remove control characters that cause XML errors
            label = node.get('term', '')
            if isinstance(label, str):
                label = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', label)
            G.add_node(node['id'], label=label, type=node['type'])
        for edge in graph_data['edges']:
            G.add_edge(edge['source'], edge['target'], relationship=edge['relationship'])

        nx.write_gexf(G, output_path)
        logger.info(f"Exported graph to GEXF: {output_path}")
        return True

    def export_json(self, output_path: str, graph_data: Dict = None, add_scope: bool = True):
        """
        Export graph to JSON format.

        Args:
            output_path: Path to save JSON
            graph_data: Graph dict (uses self.graph if not provided)
            add_scope: Whether to add formal scope statement to metadata
        """
        if graph_data is None:
            graph_data = self.graph

        if not graph_data:
            logger.error("No graph to export")
            return False

        # Add scope if requested and not present
        if add_scope and 'metadata' in graph_data:
            if 'scope' not in graph_data['metadata']:
                graph_data['metadata']['scope'] = (
                    "This knowledge graph models biomedical entities and their "
                    "relationships extracted from scientific literature."
                )

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported graph to JSON: {output_path}")
        return True

    def export_cytoscape_json(self, output_path: str, graph_data: Dict = None):
        """Export to Cytoscape-compatible JSON format."""
        if graph_data is None:
            graph_data = self.graph

        if not graph_data:
            logger.error("No graph to export")
            return False

        # Convert to Cytoscape JSON format
        cyto_data = {
            'data': [],
            'elements': {
                'nodes': [
                    {
                        'data': {
                            'id': node['id'],
                            'name': node['term'],
                            'node_type': node['type'],
                            **node.get('properties', {})
                        }
                    }
                    for node in graph_data['nodes']
                ],
                'edges': [
                    {
                        'data': {
                            'source': edge['source'],
                            'target': edge['target'],
                            'relationship': edge['relationship'],
                            **edge.get('properties', {})
                        }
                    }
                    for edge in graph_data['edges']
                ]
            }
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(cyto_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported graph to Cytoscape JSON: {output_path}")
        return True

    def export_csv(self, nodes_path: str, edges_path: str, graph_data: Dict = None):
        """Export nodes and edges to CSV files."""
        if graph_data is None:
            graph_data = self.graph

        if not graph_data:
            logger.error("No graph to export")
            return False

        import csv

        # Export nodes
        with open(nodes_path, 'w', newline='', encoding='utf-8') as f:
            if graph_data['nodes']:
                writer = csv.DictWriter(f, fieldnames=['id', 'term', 'type',
                                                        'confidence', 'umls_cui', 'omop_id'])
                writer.writeheader()
                for node in graph_data['nodes']:
                    props = node.get('properties', {})
                    writer.writerow({
                        'id': node['id'],
                        'term': node['term'],
                        'type': node['type'],
                        'confidence': props.get('confidence', ''),
                        'umls_cui': props.get('umls_cui', ''),
                        'omop_id': props.get('omop_id', '')
                    })

        # Export edges
        with open(edges_path, 'w', newline='', encoding='utf-8') as f:
            if graph_data['edges']:
                writer = csv.DictWriter(f, fieldnames=['source', 'target', 'relationship',
                                                          'confidence', 'evidence'])
                writer.writeheader()
                for edge in graph_data['edges']:
                    props = edge.get('properties', {})
                    writer.writerow({
                        'source': edge['source'],
                        'target': edge['target'],
                        'relationship': edge['relationship'],
                        'confidence': props.get('confidence', ''),
                        'evidence': props.get('evidence', '')
                    })

        logger.info(f"Exported graph to CSV: {nodes_path}, {edges_path}")
        return True

    def generate_microbiome_summary(self, entities: List[Dict]) -> Dict:
        """Generate microbiome-specific summary statistics."""
        microbiome_entities = {
            'organisms': [],
            'chemicals': [],
            'diseases': [],
            'genes': [],
            'proteins': []
        }

        for entity in entities:
            term = entity.get('term') or entity.get('entity', '')
            etype = entity.get('categories') or entity.get('entity_type', '').upper()

            if etype == 'ORGANISM':
                microbiome_entities['organisms'].append(term)
            elif etype == 'CHEMICAL':
                microbiome_entities['chemicals'].append(term)
            elif etype == 'DISEASE':
                microbiome_entities['diseases'].append(term)
            elif etype == 'GENE':
                microbiome_entities['genes'].append(term)
            elif etype == 'PROTEIN':
                microbiome_entities['proteins'].append(term)

        summary = {
            'microbiome_stats': {
                'total_organisms': len(microbiome_entities['organisms']),
                'total_metabolites': len(microbiome_entities['chemicals']),
                'total_diseases': len(microbiome_entities['diseases']),
                'total_genes': len(microbiome_entities['genes']),
                'total_proteins': len(microbiome_entities['proteins'])
            },
            'top_organisms': microbiome_entities['organisms'][:20],
            'top_metabolites': microbiome_entities['chemicals'][:20]
        }

        return summary
