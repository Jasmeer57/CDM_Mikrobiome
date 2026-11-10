#!/usr/bin/env python3
"""
Extract relationships from UMLS API for microbiome knowledge graph.

Uses UMLS REST API to extract evidence-based relationships between entities:
- Organism -> Chemical (production)
- Organism <-> Disease (associations)
- Chemical -> Disease (treats/causes)
- Protein -> Organism (expression)

Evidence Quality Tiers:
- Tier 1 (1.0): Experimentally validated (in vitro/in vivo)
- Tier 2 (0.8): Strong association (multiple human studies)
- Tier 3 (0.6): Correlation (observational studies)
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time

import requests
import json
import time
import csv
import os
from typing import List, Dict, Optional, Set
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UMLSRelationshipExtractor:
    """Extract scientifically validated relationships from UMLS."""

    API_KEY = os.getenv("UMLS_API_KEY", "")
    BASE_URL = "https://uts-ws.nlm.nih.gov/rest"

    # Semantic type mappings for entity types
    SEMANTIC_TYPE_MAPPING = {
        'ORGANISM': ['T047', 'T048'],  # Disease or Syndrome, Bacterium
        'CHEMICAL': ['T116', 'T123', 'T114', 'T109', 'T110'],  # Amino acid, Biologically active substance, etc.
        'DISEASE': ['T047'],  # Disease or Syndrome
        'PROTEIN': ['T116'],  # Amino acid, Peptide, or Protein
        'LAB_METHOD': ['T059'],  # Laboratory Procedure
        'PATHWAY': ['T033'],  # Finding
    }

    # Relationship type mappings (UMLS relation -> KG relation)
    RELATION_MAPPING = {
        'RO_0002455': 'PRODUCES',  # produces
        'RO_0002606': 'CAUSES',  # causes
        'RO_0016000': 'PROTECTS_AGAINST',  # protects_against
        'RO_0002558': 'INHABITS',  # has_location
        'RO_0000057': 'PARTICIPATES_IN',  # has_participant
    }

    def __init__(self, output_dir: str = "knowledge_graph/relationships"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        # Don't set apikey in session params to avoid duplication
        self.cache = {}

    def _make_request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make API request with rate limiting and caching."""
        cache_key = f"{endpoint}_{str(params)}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        url = f"{self.BASE_URL}{endpoint}"

        # Add required parameters for UMLS API
        if params is None:
            params = {}
        params['apikey'] = self.API_KEY

        try:
            response = self.session.get(url, params=params, timeout=30)

            # Handle 401 Unauthorized
            if response.status_code == 401:
                logger.error(f"UMLS API authentication failed for {url}")
                logger.error(f"Response: {response.text[:200]}")
                return None

            response.raise_for_status()
            result = response.json()
            self.cache[cache_key] = result
            time.sleep(0.34)  # Rate limiting (3 requests/second for free tier)
            return result
        except requests.exceptions.HTTPError as e:
            logger.warning(f"API request failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"API request failed: {e}")
            return None

    def get_cui_info(self, cui: str) -> Optional[dict]:
        """Get information about a CUI (Concept Unique Identifier)."""
        result = self._make_request(f"/content/{str(cui)}/current", {'pageSize': 100})
        if result and 'result' in result:
            return result['result']
        return None

    def get_semantic_types(self, cui: str) -> List[str]:
        """Get semantic types for a CUI."""
        info = self.get_cui_info(cui)
        if info and 'semanticTypes' in info:
            return [st['name'] for st in info['semanticTypes']]
        return []

    def get_relationships(self, cui: str) -> List[dict]:
        """Get relationships for a CUI."""
        relationships = []

        # Get atom-level relationships
        result = self._make_request(
            f"/content/{str(cui)}/atoms/neighbors",
            {'pageSize': 100}
        )

        if result and 'result' in result:
            for rel in result['result']:
                relationships.append({
                    'source_cui': cui,
                    'target_cui': rel.get('cui'),
                    'relation_label': rel.get('relationLabel'),
                    'source': 'UMLS'
                })

        return relationships

    def extract_relations_for_entity(
        self,
        entity_term: str,
        umls_id: str,
        entity_type: str
    ) -> List[dict]:
        """Extract all relationships for a single entity."""
        if not umls_id:
            return []

        logger.info(f"Extracting relationships for {entity_term} ({umls_id})")

        relationships = []

        # Get basic info
        cui_info = self.get_cui_info(umls_id)
        if not cui_info:
            logger.warning(f"No info found for {umls_id}")
            return []

        # Get direct relationships
        umls_rels = self.get_relationships(umls_id)

        for rel in umls_rels:
            target_cui = rel.get('target_cui')
            if not target_cui:
                continue

            # Get target entity info
            target_info = self.get_cui_info(target_cui)
            if not target_info:
                continue

            # Determine relationship type
            rel_type = self._map_relationship_type(rel.get('relation_label', ''))

            # Assign confidence based on evidence source
            confidence = self._assign_confidence(rel)

            if confidence >= 0.7:  # Only include high-confidence relationships
                relationships.append({
                    'source': entity_term,
                    'target': target_info.get('name', 'Unknown'),
                    'target_cui': target_cui,
                    'relationship_type': rel_type,
                    'source_db': 'UMLS',
                    'confidence': confidence,
                    'evidence': rel.get('relationLabel', 'UMLS relationship'),
                    'evidence_type': self._determine_evidence_type(rel),
                    'umls_relation': rel.get('relationLabel', ''),
                })

        return relationships

    def _map_relationship_type(self, umls_rel: str) -> str:
        """Map UMLS relationship to knowledge graph relationship type."""
        umls_rel_lower = umls_rel.lower()

        if any(term in umls_rel_lower for term in ['produces', 'produced_by', 'biosynthesis']):
            return 'PRODUCES'
        elif any(term in umls_rel_lower for term in ['causes', 'caused_by', 'induces']):
            return 'CAUSES'
        elif any(term in umls_rel_lower for term in ['treats', 'treatment']):
            return 'TREATS'
        elif any(term in umls_rel_lower for term in ['prevents', 'protects', 'protective']):
            return 'PROTECTS_AGAINST'
        elif any(term in umls_rel_lower for term in ['associated', 'association']):
            return 'ASSOCIATED_WITH'
        elif any(term in umls_rel_lower for term in ['inhabits', 'location', 'found_in']):
            return 'INHABITS'
        else:
            return 'RELATED_TO'

    def _assign_confidence(self, rel: dict) -> float:
        """Assign confidence score based on relationship evidence."""
        rel_label = rel.get('relationLabel', '').lower()

        # Tier 1: Experimental validation
        if any(term in rel_label for term in ['produces', 'inhibits', 'enzyme', 'catalyzes']):
            return 1.0

        # Tier 2: Strong observational evidence
        if any(term in rel_label for term in ['associated', 'correlation', 'linked']):
            return 0.8

        # Tier 3: General relationship
        if any(term in rel_label for term in ['related', 'similar']):
            return 0.6

        return 0.5  # Below threshold

    def _determine_evidence_type(self, rel: dict) -> str:
        """Determine the type of evidence for this relationship."""
        rel_label = rel.get('relationLabel', '').lower()

        if 'enzyme' in rel_label or 'catalyz' in rel_label:
            return 'Experimental'
        elif 'associated' in rel_label:
            return 'Observational'
        else:
            return 'Curated'

    def process_entities(
        self,
        entities: List[dict],
        output_file: str = "umls_relationships.csv"
    ) -> List[dict]:
        """Process all entities and extract relationships."""
        all_relationships = []

        # Filter entities with UMLS IDs
        umls_entities = [e for e in entities if e.get('UMLS_ID')]
        logger.info(f"Processing {len(umls_entities)} entities with UMLS IDs")

        for i, entity in enumerate(umls_entities):
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i + 1}/{len(umls_entities)}")

            rels = self.extract_relations_for_entity(
                entity['term'],
                entity['UMLS_ID'],
                entity.get('entity_type', 'UNKNOWN')
            )
            all_relationships.extend(rels)

        # Save to CSV
        self._save_to_csv(all_relationships, output_file)

        # Also save as JSON
        json_file = self.output_dir / output_file.replace('.csv', '.json')
        with open(json_file, 'w') as f:
            json.dump(all_relationships, f, indent=2)

        logger.info(f"Extracted {len(all_relationships)} relationships")
        logger.info(f"Saved to {output_file}")

        return all_relationships

    def _save_to_csv(self, relationships: List[dict], filename: str):
        """Save relationships to CSV file."""
        if not relationships:
            logger.warning("No relationships to save")
            return

        output_path = self.output_dir / filename

        # Get all unique keys
        fieldnames = set()
        for rel in relationships:
            fieldnames.update(rel.keys())

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=sorted(fieldnames))
            writer.writeheader()
            writer.writerows(relationships)

        logger.info(f"Saved {len(relationships)} relationships to {output_path}")


def main():
    """Main entry point."""
    # Load entities
    entities_file = Path(str(_CDM_ROOT / "pipelines/llm_terms/knowledge_graph/cdm_entities_final_v3_embeddings.json"))

    with open(entities_file, 'r') as f:
        data = json.load(f)
        entities = data['results']

    logger.info(f"Loaded {len(entities)} entities")

    # Extract relationships
    extractor = UMLSRelationshipExtractor()
    relationships = extractor.process_entities(
        entities,
        output_file="umls_relationships.csv"
    )

    # Print summary
    logger.info(f"\nSummary:")
    logger.info(f"  Total relationships: {len(relationships)}")
    logger.info(f"  Unique source entities: {len(set(r['source'] for r in relationships))}")
    logger.info(f"  Unique target entities: {len(set(r['target'] for r in relationships))}")

    # Relationship type distribution
    rel_types = {}
    for rel in relationships:
        rt = rel['relationship_type']
        rel_types[rt] = rel_types.get(rt, 0) + 1

    logger.info(f"\nRelationship type distribution:")
    for rt, count in sorted(rel_types.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {rt}: {count}")


if __name__ == "__main__":
    main()
