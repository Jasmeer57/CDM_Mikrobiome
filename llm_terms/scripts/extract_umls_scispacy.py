#!/usr/bin/env python3
"""
Extract UMLS relationships using scispaCy (offline, no API needed).

Uses scispaCy's entity linker to connect entities to UMLS concepts.
Extracts relationships based on co-occurrence and UMLS semantic types.

Requires: conda environment microbiome-cdm-env with scispaCy installed
"""

import json
import csv
from pathlib import Path
from typing import List, Dict, Set, Tuple
import logging
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ScispaCyUMLSExtractor:
    """Extract UMLS relationships using scispaCy entity linker."""

    # UMLS semantic type groups for microbiome entities
    SEMANTIC_GROUPS = {
        'ORGANISM': ['Bacteria', 'Virus', 'Fungus', 'Archaeon', 'Phylum'],
        'CHEMICAL': ['Pharmacologic Substance', 'Biomedical or Dental Material',
                     'Indicator, Reagent, or Diagnostic Aid', 'Antibiotic'],
        'DISEASE': ['Disease or Syndrome', 'Mental or Behavioral Dysfunction',
                   'Cell or Molecular Dysfunction', 'Pathologic Function'],
        'PROTEIN': ['Amino Acid, Peptide, or Protein', 'Gene or Genome'],
        'ANATOMICAL': ['Body Location or Region', 'Body System', 'Body Part, Organ, or Organ Component'],
    }

    def __init__(self, output_dir: str = "knowledge_graph/relationships"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Try to load scispaCy
        self.scispacy_available = False
        self.nlp = None

        try:
            # Try importing, but catch any errors (including numpy incompatibility)
            import spacy
            from scispacy.abbreviation import AbbreviationDetector
            from scispacy.linking import EntityLinker

            self.spacy = spacy
            self.scispacy_available = True
            logger.info("scispaCy is available")

        except Exception as e:
            logger.warning(f"scispaCy not available (will use rule-based extraction): {str(e)[:100]}")
            self.scispacy_available = False

    def load_model(self, model_name: str = "en_core_sci_md"):
        """Load scispaCy model with entity linker."""
        if not self.scispacy_available:
            return False

        try:
            import spacy
            from scispacy.linking import EntityLinker

            logger.info(f"Loading scispaCy model: {model_name}")
            self.nlp = spacy.load(model_name)

            # Add UMLS entity linker if not already present
            if 'scispacy_linker' not in self.nlp.pipe_names:
                logger.info("Adding UMLS entity linker...")
                self.nlp.add_pipe('scispacy_linker', config={
                    'resolve_abbreviations': True,
                    'linker_name': 'umls'
                })

            logger.info("✓ scispaCy model loaded with UMLS entity linker")
            return True

        except Exception as e:
            logger.warning(f"Failed to load model: {e}")
            return False

    def extract_from_umls_mappings(
        self,
        entities: List[dict],
        output_file: str = "umls_scispacy_relationships.csv"
    ) -> List[dict]:
        """Extract relationships using UMLS IDs from entity metadata."""

        logger.info("=" * 60)
        logger.info("Extracting UMLS-based relationships from entity metadata")
        logger.info("=" * 60)

        relationships = []

        # Build entity lookup by UMLS ID
        umls_to_entities = defaultdict(list)
        for entity in entities:
            umls_id = entity.get('UMLS_ID', '').strip()
            if umls_id:
                umls_to_entities[umls_id].append(entity)

        logger.info(f"Found {len(umls_to_entities)} entities with UMLS IDs")

        # Extract relationships based on entity types and UMLS IDs
        for entity in entities:
            entity_type = entity.get('entity_type', 'UNKNOWN')
            umls_id = entity.get('UMLS_ID', '').strip()

            if not umls_id:
                continue

            # Disease-Organism associations
            if entity_type == 'DISEASE':
                # Find organisms associated with this disease
                for other_entity in entities:
                    if (other_entity.get('entity_type') == 'ORGANISM' and
                        other_entity.get('paper_context', '')):

                        # Check if they co-occur in paper context
                        if entity['term'].lower() in other_entity.get('paper_context', '').lower():
                            relationships.append({
                                'source': other_entity['term'],
                                'target': entity['term'],
                                'relationship_type': 'ASSOCIATED_WITH',
                                'source_db': 'UMLS (scispaCy)',
                                'confidence': 0.75,
                                'evidence': f'Co-occurs in literature with UMLS ID {umls_id}',
                                'evidence_type': 'Literature Co-occurrence',
                                'umls_id': umls_id
                            })

            # Organism-Chemical production (based on known patterns)
            if entity_type == 'ORGANISM':
                for other_entity in entities:
                    if other_entity.get('entity_type') == 'CHEMICAL':
                        # Check if paper context suggests production
                        context = entity.get('paper_context', '')
                        target_term = other_entity['term'].lower()

                        # Production indicators
                        if any(word in context.lower() for word in
                               ['produces', 'produced by', 'synthesizes', 'generates']):
                            if target_term in context.lower():
                                relationships.append({
                                    'source': entity['term'],
                                    'target': other_entity['term'],
                                    'relationship_type': 'PRODUCES',
                                    'source_db': 'UMLS (scispaCy)',
                                    'confidence': 0.80,
                                    'evidence': 'Production relationship in literature',
                                    'evidence_type': 'Literature Extraction',
                                    'umls_id': umls_id
                                })

        logger.info(f"Extracted {len(relationships)} relationships")

        # Deduplicate
        seen = set()
        unique_relationships = []
        for rel in relationships:
            key = (rel['source'], rel['target'], rel['relationship_type'])
            if key not in seen:
                seen.add(key)
                unique_relationships.append(rel)

        logger.info(f"After deduplication: {len(unique_relationships)} unique relationships")

        # Save to CSV
        self._save_to_csv(unique_relationships, output_file)

        return unique_relationships

    def extract_with_entity_linker(
        self,
        entities: List[dict],
        output_file: str = "umls_scispacy_linked.csv"
    ) -> List[dict]:
        """Extract relationships using scispaCy entity linker for ALL entities."""

        if not self.scispacy_available or not self.nlp:
            logger.warning("Entity linker not available, skipping")
            return []

        logger.info("=" * 60)
        logger.info("Extracting UMLS relationships with scispaCy Entity Linker")
        logger.info("=" * 60)

        relationships = []

        # Build entity lookup
        entity_terms = {e['term'].lower(): e for e in entities}

        # Group entities by type
        organisms = [e for e in entities if e.get('entity_type') == 'ORGANISM']
        chemicals = [e for e in entities if e.get('entity_type') == 'CHEMICAL']
        diseases = [e for e in entities if e.get('entity_type') == 'DISEASE']
        methods = [e for e in entities if e.get('entity_type') == 'LAB_METHOD']

        logger.info(f"Entity type distribution:")
        logger.info(f"  Organisms: {len(organisms)}")
        logger.info(f"  Chemicals: {len(chemicals)}")
        logger.info(f"  Diseases: {len(diseases)}")
        logger.info(f"  Methods: {len(methods)}")

        # Process ALL entities with UMLS linking
        logger.info("Extracting UMLS links for all entities...")

        processed = 0
        for entity in entities:
            processed += 1
            if processed % 500 == 0:
                logger.info(f"Processed {processed}/{len(entities)} entities")

            # Link entity to UMLS
            try:
                doc = self.nlp(entity['term'])

                for ent in doc.ents:
                    if hasattr(ent._, 'kb_ents') and ent._.kb_ents:
                        for umls_id, linker_score in ent._.kb_ents:
                            if linker_score < 0.7:
                                continue

                            # Now find related entities by processing paper context
                            context = entity.get('paper_context', '')
                            if context and len(context) > 20:
                                try:
                                    context_doc = self.nlp(context)

                                    # Find other entities in this context
                                    for context_ent in context_doc.ents:
                                        if not hasattr(context_ent._, 'kb_ents') or not context_ent._.kb_ents:
                                            continue

                                        for target_umls_id, target_score in context_ent._.kb_ents:
                                            if target_score < 0.7:
                                                continue

                                            # Find matching entity in our set
                                            target_text = context_ent.text.lower()
                                            target_entity = None

                                            if target_text in entity_terms:
                                                target_entity = entity_terms[target_text]

                                            if target_entity and target_entity['term'] != entity['term']:
                                                # Infer relationship
                                                rel_type, confidence = self._infer_relationship_from_types(
                                                    entity,
                                                    target_entity,
                                                    context,
                                                    (linker_score + target_score) / 2
                                                )

                                                if confidence >= 0.75:
                                                    relationships.append({
                                                        'source': entity['term'],
                                                        'target': target_entity['term'],
                                                        'relationship_type': rel_type,
                                                        'source_db': 'UMLS (scispaCy)',
                                                        'confidence': confidence,
                                                        'evidence': f'UMLS {umls_id} → UMLS {target_umls_id}',
                                                        'evidence_type': 'Entity Linking',
                                                        'source_umls': umls_id,
                                                        'target_umls': target_umls_id
                                                    })

                                except Exception as e:
                                    logger.debug(f"Context processing failed: {e}")
                                    continue

            except Exception as e:
                logger.debug(f"Entity processing failed: {e}")
                continue

        logger.info(f"Extracted {len(relationships)} raw relationships")

        # Deduplicate and keep highest confidence
        rel_map = {}
        for rel in relationships:
            key = (rel['source'], rel['target'], rel['relationship_type'])
            if key not in rel_map or rel_map[key]['confidence'] < rel['confidence']:
                rel_map[key] = rel

        unique_relationships = list(rel_map.values())
        logger.info(f"After deduplication: {len(unique_relationships)} unique relationships")

        # Log distribution
        rel_types = {}
        for rel in unique_relationships:
            rt = rel['relationship_type']
            rel_types[rt] = rel_types.get(rt, 0) + 1

        logger.info("Relationship type distribution:")
        for rt, count in sorted(rel_types.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {rt}: {count}")

        self._save_to_csv(unique_relationships, output_file)

        return unique_relationships

    def _infer_relationship_type(self, source: str, target: str, context: str) -> str:
        """Infer relationship type from context."""
        context_lower = context.lower()

        # Check for production
        if any(word in context_lower for word in ['produces', 'produced by', 'synthesizes']):
            return 'PRODUCES'

        # Check for inhibition
        if any(word in context_lower for word in ['inhibits', 'blocks', 'suppresses']):
            return 'INHIBITS'

        # Check for causation
        if any(word in context_lower for word in ['causes', 'induces', 'triggers']):
            return 'CAUSES'

        # Check for association
        if any(word in context_lower for word in ['associated', 'linked', 'correlated']):
            return 'ASSOCIATED_WITH'

        # Default
        return 'RELATED_TO'

    def _infer_relationship_from_types(self, source: dict, target: dict, context: str, linker_conf: float) -> tuple:
        """Infer relationship type and confidence from entity types."""
        source_type = source.get('entity_type', 'UNKNOWN')
        target_type = target.get('entity_type', 'UNKNOWN')
        context_lower = context.lower()

        # Organism -> Chemical: Production
        if source_type == 'ORGANISM' and target_type == 'CHEMICAL':
            if any(word in context_lower for word in ['produces', 'synthesizes', 'generates']):
                return 'PRODUCES', min(linker_conf * 1.1, 0.95)
            return 'RELATED_TO', linker_conf * 0.8

        # Organism <-> Disease
        if source_type in ['ORGANISM', 'CHEMICAL'] and target_type == 'DISEASE':
            if any(word in context_lower for word in ['protects', 'prevents', 'protective']):
                return 'PROTECTS_AGAINST', min(linker_conf * 1.1, 0.95)
            elif any(word in context_lower for word in ['causes', 'exacerbates', 'worsens']):
                return 'EXACERBATES', min(linker_conf * 1.1, 0.95)
            return 'ASSOCIATED_WITH', linker_conf * 0.85

        # Chemical -> Disease
        if source_type == 'CHEMICAL' and target_type == 'DISEASE':
            if any(word in context_lower for word in ['treats', 'therapeutic', 'therapy']):
                return 'TREATS', min(linker_conf * 1.1, 0.95)
            return 'ASSOCIATED_WITH', linker_conf * 0.8

        # Method -> Entity
        if source_type == 'LAB_METHOD':
            if 'detects' in context_lower or 'measures' in context_lower:
                return 'DETECTS', linker_conf * 0.9
            return 'RELATED_TO', linker_conf * 0.7

        # Default
        return 'RELATED_TO', linker_conf * 0.75

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

    def map_all_entities_to_umls(
        self,
        entities: List[dict],
        output_file: str = "umls_entity_mappings.csv"
    ) -> Dict[str, dict]:
        """
        Map ALL entities to UMLS concepts using entity linker.

        Returns a dictionary mapping entity terms to their UMLS information.
        """
        if not self.scispacy_available or not self.nlp:
            logger.warning("Entity linker not available for UMLS mapping")
            return {}

        logger.info("=" * 60)
        logger.info("Mapping ALL Entities to UMLS Concepts")
        logger.info("=" * 60)

        entity_umls_map = {}
        unmapped_entities = []

        logger.info(f"Processing {len(entities)} entities for UMLS mapping...")

        for i, entity in enumerate(entities):
            if (i + 1) % 500 == 0:
                logger.info(f"  Processed {i + 1}/{len(entities)} entities")

            term = entity['term']
            entity_type = entity.get('entity_type', 'UNKNOWN')

            # Try to link the entity term to UMLS
            try:
                doc = self.nlp(term)

                best_umls_match = None
                best_score = 0.0

                # Get all UMLS links for this entity
                for ent in doc.ents:
                    if hasattr(ent._, 'kb_ents') and ent._.kb_ents:
                        for umls_id, score in ent._.kb_ents:
                            if score > best_score and score >= 0.7:
                                best_score = score
                                best_umls_match = {
                                    'umls_id': umls_id,
                                    'score': score,
                                    'matched_text': ent.text
                                }

                if best_umls_match:
                    entity_umls_map[term] = {
                        'term': term,
                        'entity_type': entity_type,
                        'umls_id': best_umls_match['umls_id'],
                        'linker_confidence': best_umls_match['score'],
                        'matched_text': best_umls_match['matched_text'],
                        'paper_count': entity.get('paper_count', 0),
                        'confidence_score': entity.get('confidence_score', 0.0)
                    }
                else:
                    unmapped_entities.append(term)

            except Exception as e:
                logger.debug(f"Failed to map entity {term}: {e}")
                unmapped_entities.append(term)

        # Save mappings to CSV
        output_path = self.output_dir / output_file
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['term', 'entity_type', 'umls_id', 'linker_confidence',
                          'matched_text', 'paper_count', 'confidence_score']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(entity_umls_map.values())

        logger.info(f"\nUMLS Mapping Complete:")
        logger.info(f"  Total entities: {len(entities)}")
        logger.info(f"  Mapped to UMLS: {len(entity_umls_map)} ({len(entity_umls_map)/len(entities)*100:.1f}%)")
        logger.info(f"  Unmapped: {len(unmapped_entities)}")
        logger.info(f"  Saved to: {output_path}")

        # Save unmapped entities list
        if unmapped_entities:
            unmapped_file = self.output_dir / "unmapped_entities.txt"
            with open(unmapped_file, 'w') as f:
                for term in unmapped_entities:
                    f.write(f"{term}\n")
            logger.info(f"  Unmapped entities saved to: {unmapped_file}")

        return entity_umls_map

    def process_entities(
        self,
        entities: List[dict],
        output_file: str = "umls_scispacy_relationships.csv"
    ) -> List[dict]:
        """Main processing method - extracts UMLS relationships for all entities."""

        # Try to load model first
        if self.scispacy_available:
            for model in ['en_core_sci_md']:
                if self.load_model(model):
                    logger.info(f"✓ Loaded model: {model}")

                    # STEP 1: Map ALL entities to UMLS concepts
                    logger.info("\n" + "=" * 60)
                    logger.info("STEP 1: Creating UMLS entity mappings")
                    logger.info("=" * 60)
                    umls_mappings = self.map_all_entities_to_umls(entities)

                    # STEP 2: Extract relationships using the mappings
                    logger.info("\n" + "=" * 60)
                    logger.info("STEP 2: Extracting relationships using UMLS mappings")
                    logger.info("=" * 60)
                    linker_rels = self.extract_with_entity_linker(entities, output_file)

                    # Return both the relationships and the mappings
                    # Store mappings in a special file for reference
                    if umls_mappings:
                        # Also save as JSON for easy access
                        mappings_json = self.output_dir / "umls_entity_mappings.json"
                        with open(mappings_json, 'w') as f:
                            json.dump(umls_mappings, f, indent=2)
                        logger.info(f"UMLS mappings saved to: {mappings_json}")

                    if linker_rels:
                        return linker_rels
                    break

        # Fall back to rule-based extraction
        logger.info("Using rule-based extraction from UMLS IDs")
        return self.extract_from_umls_mappings(entities, output_file)


def main():
    """Main entry point."""
    # Load entities
    entities_file = Path("/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/cdm_entities_final_v3_embeddings.json")

    with open(entities_file, 'r') as f:
        data = json.load(f)
        entities = data['results']

    logger.info(f"Loaded {len(entities)} entities")

    # Extract relationships
    extractor = ScispaCyUMLSExtractor()
    relationships = extractor.process_entities(
        entities,
        output_file="umls_scispacy_relationships.csv"
    )

    # Print summary
    logger.info(f"\nSummary:")
    logger.info(f"  Total relationships: {len(relationships)}")

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
