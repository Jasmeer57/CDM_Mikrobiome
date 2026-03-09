import json
import pandas as pd
from collections import Counter

with open('microbiome_cdm_complete.json', 'r') as f:
    data = json.load(f)

entities = data['entities']
rels = data['relationships']
links = data.get('entity_project_links', [])

# 1. Are the OMOP/UMLS IDs actually real?
print("--- Checking ID formats ---")
invalid_umls = [e['UMLS_ID'] for e in entities if e.get('UMLS_ID') and not str(e['UMLS_ID']).startswith('C')]
print(f"Invalid UMLS IDs (should start with C): {len(invalid_umls)}")

# 2. What are the orphan nodes actually doing?
connected_nodes = set()
for r in rels:
    connected_nodes.add(r['source'])
    connected_nodes.add(r['target'])

orphans = [e for e in entities if e['term'] not in connected_nodes]
orphan_types = Counter(e['entity_type'] for e in orphans)
print("\n--- Orphan Node Types ---")
for k, v in orphan_types.most_common(5):
    print(f"{k}: {v}")

# 3. How strong is the non-taxonomic relationship evidence?
non_tax_rels = [r for r in rels if r['relationship_type'] != 'PARENT_OF']
evidence_types = Counter(r.get('evidence_type', 'Unknown') for r in non_tax_rels)
sources = Counter(r.get('source_db', 'Unknown') for r in non_tax_rels)

print("\n--- Non-Taxonomic Edge Quality ---")
print(f"Total Non-Taxonomic Edges: {len(non_tax_rels)}")
print(f"Evidence Types: {dict(evidence_types)}")
print(f"Source DBs: {dict(sources)}")

# 4. Are there completely empty entities?
empty_defs = [e['term'] for e in entities if not e.get('definition') or e['definition'].strip() == '']
print(f"\nEntities with completely empty definitions: {len(empty_defs)}")
