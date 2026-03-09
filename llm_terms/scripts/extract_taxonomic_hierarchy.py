#!/usr/bin/env python3
"""
Extract NCBI Taxonomy hierarchy for organism entities.

Builds parent-child taxonomic relationships:
- Bacteria (Kingdom)
  └→ Firmicutes (Phylum)
      └→ Clostridia (Class)
          └→ Clostridiales (Order)
              └→ Lachnospiraceae (Family)
                  └→ Faecalibacterium (Genus)
                      └→ Faecalibacterium prausnitzii (Species)

Uses BioPython Entrez to query NCBI Taxonomy database.
"""

import json
import csv
import time
from typing import List, Dict, Optional, Set
from pathlib import Path
import logging
import re

try:
    from Bio import Entrez
    BIOPYTHON_AVAILABLE = True
except ImportError:
    BIOPYTHON_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TaxonomyHierarchyExtractor:
    """Extract taxonomic hierarchies from NCBI Taxonomy."""

    # NCBI Taxonomy email required by Entrez
    EMAIL = "microbiome-cdm@example.com"

    # Taxonomic ranks in order
    RANK_ORDER = [
        'kingdom',
        'phylum',
        'class',
        'order',
        'family',
        'genus',
        'species',
        'strain'
    ]

    def __init__(self, output_dir: str = "knowledge_graph/relationships"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if BIOPYTHON_AVAILABLE:
            Entrez.email = self.EMAIL

        self.taxonomy_cache = {}
        self.lineage_cache = {}

    def extract_ncbi_taxon_id(self, ols_id: str) -> Optional[str]:
        """Extract NCBI Taxon ID from OLS identifier."""
        if not ols_id:
            return None

        # Pattern: http://purl.obolibrary.org/obo/NCBITaxon_12345
        match = re.search(r'NCBITaxon_(\d+)', ols_id)
        if match:
            return match.group(1)

        return None

    def get_taxon_info(self, taxon_id: str) -> Optional[dict]:
        """Get taxon information from NCBI."""
        if not BIOPYTHON_AVAILABLE:
            logger.warning("BioPython not available, skipping taxonomy extraction")
            return None

        if taxon_id in self.taxonomy_cache:
            return self.taxonomy_cache[taxon_id]

        try:
            handle = Entrez.efetch(
                db="taxonomy",
                id=str(taxon_id),
                retmode="xml"
            )
            records = Entrez.read(handle)

            if records and len(records) > 0:
                taxon = records[0]
                self.taxonomy_cache[taxon_id] = {
                    'taxon_id': taxon_id,
                    'name': taxon.get('ScientificName', ''),
                    'rank': taxon.get('Rank', ''),
                    'lineage': taxon.get('Lineage', []),
                    'lineage_ex': taxon.get('LineageEx', [])
                }
                time.sleep(0.34)  # NCBI rate limit (3 requests/second)
                return self.taxonomy_cache[taxon_id]

        except Exception as e:
            logger.warning(f"Failed to fetch taxon {taxon_id}: {e}")

        return None

    def get_lineage(self, taxon_id: str) -> List[dict]:
        """Get full taxonomic lineage for a taxon."""
        if taxon_id in self.lineage_cache:
            return self.lineage_cache[taxon_id]

        taxon_info = self.get_taxon_info(taxon_id)
        if not taxon_info:
            return []

        lineage = []

        # Build lineage from LineageEx (includes IDs and ranks)
        for item in taxon_info.get('lineage_ex', []):
            lineage.append({
                'taxon_id': item.get('TaxId'),
                'name': item.get('ScientificName'),
                'rank': item.get('Rank')
            })

        # Add the taxon itself
        lineage.append({
            'taxon_id': taxon_id,
            'name': taxon_info.get('name'),
            'rank': taxon_info.get('rank')
        })

        self.lineage_cache[taxon_id] = lineage
        return lineage

    def build_taxonomy_relationships(
        self,
        entity_term: str,
        taxon_id: str
    ) -> List[dict]:
        """Build parent-child relationships for an organism."""
        if not BIOPYTHON_AVAILABLE:
            return []

        logger.debug(f"Building taxonomy for {entity_term} (NCBITaxon:{taxon_id})")

        lineage = self.get_lineage(taxon_id)
        if not lineage:
            return []

        relationships = []

        # Create parent-child relationships
        for i in range(len(lineage) - 1):
            parent = lineage[i]
            child = lineage[i + 1]

            # Only include recognized ranks
            if parent['rank'] in self.RANK_ORDER and child['rank'] in self.RANK_ORDER:
                relationships.append({
                    'source': parent['name'],
                    'source_taxon_id': parent['taxon_id'],
                    'source_rank': parent['rank'],
                    'target': child['name'],
                    'target_taxon_id': child['taxon_id'],
                    'target_rank': child['rank'],
                    'relationship_type': 'PARENT_OF',
                    'source_db': 'NCBI Taxonomy',
                    'confidence': 1.0,
                    'evidence': f"Taxonomic hierarchy: {parent['rank']} → {child['rank']}",
                    'evidence_type': 'Curated',
                    'ncbi_taxon_id': f"NCBITaxon:{child['taxon_id']}"
                })

        return relationships

    def process_entities(
        self,
        entities: List[dict],
        output_file: str = "taxonomic_hierarchy.csv"
    ) -> List[dict]:
        """Process all organism entities and extract taxonomic relationships."""
        all_relationships = []
        processed_taxa = set()

        # Filter organism entities with OLS NCBITaxon IDs
        organism_entities = []
        for entity in entities:
            if entity.get('entity_type') == 'ORGANISM' and entity.get('OLS'):
                taxon_id = self.extract_ncbi_taxon_id(entity['OLS'])
                if taxon_id:
                    organism_entities.append({
                        'term': entity['term'],
                        'taxon_id': taxon_id,
                        'entity': entity
                    })

        logger.info(f"Processing {len(organism_entities)} organisms with NCBI Taxonomy IDs")

        for i, org in enumerate(organism_entities):
            if (i + 1) % 50 == 0:
                logger.info(f"Progress: {i + 1}/{len(organism_entities)}")

            # Avoid duplicate processing
            if org['taxon_id'] in processed_taxa:
                continue
            processed_taxa.add(org['taxon_id'])

            rels = self.build_taxonomy_relationships(
                org['term'],
                org['taxon_id']
            )
            all_relationships.extend(rels)

        # Save to CSV
        self._save_to_csv(all_relationships, output_file)

        # Also save as JSON
        json_file = self.output_dir / output_file.replace('.csv', '.json')
        with open(json_file, 'w') as f:
            json.dump(all_relationships, f, indent=2)

        logger.info(f"Extracted {len(all_relationships)} taxonomic relationships")
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
    entities_file = Path("/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/cdm_entities_final_v3_embeddings.json")

    with open(entities_file, 'r') as f:
        data = json.load(f)
        entities = data['results']

    logger.info(f"Loaded {len(entities)} entities")

    # Extract taxonomic hierarchies
    extractor = TaxonomyHierarchyExtractor()
    relationships = extractor.process_entities(
        entities,
        output_file="taxonomic_hierarchy.csv"
    )

    # Print summary
    logger.info(f"\nSummary:")
    logger.info(f"  Total taxonomic relationships: {len(relationships)}")
    logger.info(f"  Unique parent taxa: {len(set(r['source'] for r in relationships))}")
    logger.info(f"  Unique child taxa: {len(set(r['target'] for r in relationships))}")

    # Rank distribution
    rank_pairs = {}
    for rel in relationships:
        pair = f"{rel['source_rank']} → {rel['target_rank']}"
        rank_pairs[pair] = rank_pairs.get(pair, 0) + 1

    logger.info(f"\nRank pair distribution:")
    for pair, count in sorted(rank_pairs.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {pair}: {count}")


if __name__ == "__main__":
    main()
