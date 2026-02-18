#!/usr/bin/env python3
"""
Interactive Knowledge Graph Visualization
Generates an interactive HTML visualization using pyvis
"""
import json
import networkx as nx
from pyvis.network import Network
from collections import Counter

# Color scheme for different entity types
TYPE_COLORS = {
    'ORGANISM': '#ff6b6b',      # Red
    'DISEASE': '#4ecdc4',       # Teal
    'GENE': '#ffe66d',          # Yellow
    'PROTEIN': '#ff9ff3',       # Pink
    'SCIENTIFIC_TERM': '#54a0ff', # Blue
    'DRUG': '#1dd1a1',          # Green
    'CLINICAL': '#fd79a8',      # Light pink
    'DATA_ANALYSIS': '#fdcb6e', # Orange
    'default': '#95a5a6'        # Gray
}

def load_graph(json_path):
    """Load knowledge graph from JSON file"""
    with open(json_path) as f:
        data = json.load(f)

    G = nx.DiGraph()

    # Add nodes
    print(f"Loading {len(data['nodes'])} nodes...")
    for node in data['nodes']:
        node_id = node['id']
        G.add_node(
            node_id,
            label=node['term'],
            title=f"{node['term']}\nType: {node['type']}\nConfidence: {node['properties'].get('confidence', 'N/A')}\nDefinition: {node['properties'].get('definition', 'N/A')[:100]}...",
            type=node['type'],
            confidence=node['properties'].get('confidence', 0),
            frequency=node['properties'].get('frequency', 0)
        )

    # Add edges
    print(f"Loading {len(data['edges'])} edges...")
    for edge in data['edges']:
        G.add_edge(
            edge['source'],
            edge['target'],
            title=edge.get('relationship', 'related_to'),
            edge_type=edge.get('relationship', 'related_to')
        )

    return G

def create_interactive_viz(G, output_html='knowledge_graph_visualization.html', max_nodes=None):
    """Create interactive pyvis visualization"""

    # Optionally limit to high-degree nodes if graph is too large
    if max_nodes and len(G.nodes()) > max_nodes:
        print(f"Graph too large ({len(G.nodes())} nodes). Limiting to top {max_nodes} nodes by degree...")
        degrees = dict(G.degree())
        top_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:max_nodes]
        G = G.subgraph([n for n, _ in top_nodes])

    # Create network
    net = Network(height='1000px', width='100%', bgcolor='#1e1e1e', font_color='white', directed=True)

    # Convert to networkx graph with custom styling
    print("Creating visualization...")

    # Add nodes with custom styling
    for node_id in G.nodes():
        node_data = G.nodes[node_id]
        node_type = node_data.get('type', 'default')
        color = TYPE_COLORS.get(node_type, TYPE_COLORS['default'])

        # Size based on degree and confidence
        degree = G.degree(node_id)
        confidence = node_data.get('confidence', 0.5)
        size = 10 + (degree * 3) + (confidence * 10)

        net.add_node(
            node_id,
            label=node_data['label'],
            title=node_data['title'],
            color=color,
            size=min(size, 100),  # Cap max size
            font={'size': 10 if size < 30 else 12}
        )

    # Add edges
    for source, target in G.edges():
        edge_data = G.edges[source, target]
        net.add_edge(source, target, title=edge_data.get('title', ''), color='#666666')

    # Physics configuration for better layout
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -8000,
          "centralGravity": 0.3,
          "springLength": 150,
          "springConstant": 0.04,
          "damping": 0.09,
          "avoidOverlap": 0.5
        },
        "solver": "barnesHut"
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 200,
        "zoomView": true,
        "dragView": true
      },
      "nodes": {
        "borderWidth": 2,
        "borderWidthSelected": 3
      },
      "edges": {
        "width": 1,
        "smooth": {
          "type": "continuous"
        },
        "arrows": {
          "to": {
            "enabled": true,
            "scaleFactor": 0.5
          }
        }
      }
    }
    """)

    # Save and show stats
    net.save_graph(output_html)
    print(f"\n✓ Visualization saved to: {output_html}")
    print(f"\nGraph Statistics:")
    print(f"  Nodes: {len(G.nodes())}")
    print(f"  Edges: {len(G.edges())}")

    # Show node type distribution
    type_counts = Counter([G.nodes[n].get('type', 'unknown') for n in G.nodes()])
    print(f"\nNode Type Distribution:")
    for node_type, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        color = TYPE_COLORS.get(node_type, TYPE_COLORS['default'])
        print(f"  {color} {node_type}: {count}")

    return output_html

if __name__ == '__main__':
    import sys

    json_path = '/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/cdm_kg.json'

    # Load graph
    print("Loading knowledge graph...")
    G = load_graph(json_path)

    # Create visualization
    # Use max_nodes=500 to show only well-connected nodes, or None for all nodes
    output = create_interactive_viz(
        G,
        output_html='knowledge_graph_visualization.html',
        max_nodes=500  # Set to None to show all 12,175 nodes
    )

    print(f"\n📊 Open {output} in your browser to explore the graph!")
