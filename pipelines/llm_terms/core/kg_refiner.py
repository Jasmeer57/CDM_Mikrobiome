"""
Knowledge Graph Refiner Module
================================
Provides tools for cleaning, canonicalizing, and enhancing knowledge graphs.

This module handles:
- Entity canonicalization (merging duplicates, normalizing types)
- Relationship validation (type constraints, evidence typing)
- Node filtering (removing noise, non-biological entities)
- Subgraph labeling (mechanism/microbiome_metabolite/methods_provenance)
- KG export with proper schema
"""

import logging
import json
import re
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter
from pathlib import Path

# Import type normalization utilities
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config.type_normalization import (
    normalize_type_name,
    normalize_relationship_type,
    create_canonical_id,
    is_biological_type,
    is_noise_type,
    is_valid_type_pair,
    infer_subgraph_label,
    EvidenceType,
    SubgraphLabel,
    CORE_BIOLOGICAL_TYPES,
    NOISE_TYPES,
    VALID_RELATIONSHIP_TYPES,
    KG_SCOPE,
)

logger = logging.getLogger(__name__)


@dataclass
class CanonicalEntity:
    """Represents a canonicalized entity in the KG."""
    id: str
    term: str
    type: str
    subgraph: str = "mechanism"
    properties: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON export."""
        return {
            'id': self.id,
            'term': self.term,
            'type': self.type,
            'subgraph': self.subgraph,
            'properties': self.properties
        }


@dataclass
class CanonicalRelationship:
    """Represents a canonicalized relationship in the KG."""
    source: str
    target: str
    relationship: str
    subgraph: str = "mechanism"
    properties: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON export."""
        return {
            'source': self.source,
            'target': self.target,
            'relationship': self.relationship,
            'subgraph': self.subgraph,
            'properties': self.properties
        }


class EntityCanonicalizer:
    """
    Merge duplicate entities and normalize types.

    Handles:
    - Type normalization (GENES -> GENE)
    - Duplicate detection and merging
    - Canonical ID generation
    - Property consolidation
    """

    def __init__(self):
        self.entity_map = {}  # term -> CanonicalEntity
        self.term_variants = defaultdict(set)  # canonical_term -> variant_terms

    def canonicalize_entities(
        self,
        entities: List[Dict],
        min_confidence: float = 0.4
    ) -> List[CanonicalEntity]:
        """
        Canonicalize a list of entities.

        Args:
            entities: List of entity dicts with 'term', 'type', 'properties'
            min_confidence: Minimum confidence to include entity

        Returns:
            List of canonicalized entities
        """
        logger.info(f"Canonicalizing {len(entities)} entities")

        # Group by normalized term
        term_groups = defaultdict(list)
        for entity in entities:
            term = entity.get('term', '').strip()
            if not term:
                continue

            confidence = entity.get('properties', {}).get('confidence', 0.0)
            if confidence < min_confidence:
                continue

            # Normalize term for grouping (case-insensitive, trim)
            normalized_term = term.lower().strip()
            term_groups[normalized_term].append(entity)

        logger.info(f"Found {len(term_groups)} unique term groups")

        # Merge each group
        canonical_entities = []
        for normalized_term, group in term_groups.items():
            canonical = self._merge_entity_group(group, normalized_term)
            if canonical:
                canonical_entities.append(canonical)
                # Track variants
                for e in group:
                    variant = e.get('term', '').strip()
                    if variant and variant.lower() != normalized_term:
                        self.term_variants[normalized_term].add(variant)

        logger.info(f"Canonicalized to {len(canonical_entities)} entities")
        return canonical_entities

    def _merge_entity_group(
        self,
        group: List[Dict],
        normalized_term: str
    ) -> Optional[CanonicalEntity]:
        """
        Merge a group of duplicate entities.

        Keeps highest confidence, consolidates properties.
        """
        if not group:
            return None

        # Sort by confidence descending
        sorted_group = sorted(
            group,
            key=lambda e: e.get('properties', {}).get('confidence', 0.0),
            reverse=True
        )

        # Use highest confidence entity as base
        base = sorted_group[0]
        term = base.get('term', normalized_term)
        raw_type = base.get('type', 'UNKNOWN')

        # Normalize type
        canonical_type = normalize_type_name(raw_type)

        # Create canonical ID
        canonical_id = create_canonical_id(term, canonical_type)

        # Merge properties
        merged_props = self._merge_properties([
            e.get('properties', {}) for e in group
        ])

        # Add aliases from variants
        aliases = set()
        for e in group:
            aliases.add(e.get('term', '').strip())
        aliases.discard(term)  # Remove canonical term
        if aliases:
            merged_props['aliases'] = ', '.join(sorted(aliases))

        # Add canonical ID to properties
        merged_props['canonical_id'] = canonical_id

        # Infer subgraph label
        subgraph = self._infer_entity_subgraph(canonical_type)

        return CanonicalEntity(
            id=canonical_id,
            term=term,
            type=canonical_type,
            subgraph=subgraph,
            properties=merged_props
        )

    def _merge_properties(self, properties_list: List[Dict]) -> Dict:
        """
        Merge properties from multiple entities.

        Strategy:
        - Keep highest confidence
        - Concatenate non-empty definitions
        - Collect all aliases
        - Keep all UMLS/OMOP IDs
        """
        merged = {}

        # Confidence: max
        confidences = [p.get('confidence', 0.0) for p in properties_list if p.get('confidence')]
        if confidences:
            merged['confidence'] = max(confidences)

        # Definition: concatenate non-empty unique definitions
        definitions = set(p.get('definition', '').strip() for p in properties_list)
        definitions.discard('')
        if definitions:
            merged['definition'] = ' | '.join(sorted(definitions))

        # Aliases: collect all
        all_aliases = set()
        for p in properties_list:
            aliases = p.get('aliases', '')
            if aliases:
                all_aliases.update(a.strip() for a in aliases.split(',') if a.strip())
        if all_aliases:
            merged['aliases'] = ', '.join(sorted(all_aliases))

        # IDs: keep all non-empty (handle both string and non-string types)
        for id_field in ['umls_cui', 'omop_id', 'source']:
            values = set()
            for p in properties_list:
                val = p.get(id_field, '')
                # Convert to string if needed, skip if empty
                if val is not None and val != '':
                    val_str = str(val).strip() if not isinstance(val, (int, float)) else str(val)
                    if val_str:
                        values.add(val_str)
            if values:
                merged[id_field] = ', '.join(sorted(values))

        # Frequency: sum
        frequencies = [p.get('frequency', 0) for p in properties_list if p.get('frequency')]
        if frequencies:
            merged['frequency'] = sum(frequencies)

        return merged

    def _infer_entity_subgraph(self, entity_type: str) -> str:
        """
        Infer subgraph label for an entity based on its type.

        Methods -> methods_provenance
        Others -> mechanism (default)
        """
        if entity_type == 'DATA_ANALYSIS':
            return SubgraphLabel.METHODS_PROVENANCE
        return SubgraphLabel.MECHANISM


class RelationshipValidator:
    """
    Validate and enhance relationships.

    Handles:
    - Type constraint validation
    - Evidence type assignment
    - Subgraph labeling
    - Relationship type normalization
    """

    def __init__(self, entity_id_map: Dict[str, str]):
        """
        Initialize validator.

        Args:
            entity_id_map: Maps entity term to canonical ID
        """
        self.entity_id_map = entity_id_map
        self.valid_types = VALID_RELATIONSHIP_TYPES

    def validate_and_enhance_relationships(
        self,
        relationships: List[Dict],
        entity_type_map: Dict[str, str],
        min_confidence: float = 0.5
    ) -> Tuple[List[CanonicalRelationship], Dict]:
        """
        Validate and enhance relationships.

        Args:
            relationships: List of relationship dicts
            entity_type_map: Maps entity term to its type
            min_confidence: Minimum confidence to include relationship

        Returns:
            Tuple of (valid_relationships, validation_stats)
        """
        logger.info(f"Validating {len(relationships)} relationships")

        stats = {
            'total_input': len(relationships),
            'filtered_confidence': 0,
            'filtered_invalid_type_pair': 0,
            'filtered_missing_entities': 0,
            'evidence_types': defaultdict(int),
            'subgraph_distribution': defaultdict(int),
        }

        valid_relationships = []

        for rel in relationships:
            source = rel.get('source_entity', '').strip()
            target = rel.get('target_entity', '').strip()
            rel_type = rel.get('relationship_type', '').strip()
            confidence = rel.get('confidence', 0.0)

            # Filter by confidence
            if confidence < min_confidence:
                stats['filtered_confidence'] += 1
                continue

            # Check entities exist in map
            if source not in self.entity_id_map or \
               target not in self.entity_id_map:
                stats['filtered_missing_entities'] += 1
                continue

            # Normalize types
            source_type = normalize_type_name(
                entity_type_map.get(source, rel.get('source_type', 'UNKNOWN'))
            )
            target_type = normalize_type_name(
                entity_type_map.get(target, rel.get('target_type', 'UNKNOWN'))
            )
            normalized_rel = normalize_relationship_type(rel_type)

            # Validate type pair
            if not is_valid_type_pair(source_type, target_type, normalized_rel):
                stats['filtered_invalid_type_pair'] += 1
                continue

            # Infer evidence type
            evidence_type = self._infer_evidence_type(rel)

            # Infer subgraph label
            subgraph = infer_subgraph_label(source_type, target_type, normalized_rel)

            # Build enhanced properties
            enhanced_props = self._enhance_properties(rel, evidence_type)

            # Get canonical IDs
            source_id = self.entity_id_map[source]
            target_id = self.entity_id_map[target]

            canonical_rel = CanonicalRelationship(
                source=source_id,
                target=target_id,
                relationship=normalized_rel,
                subgraph=subgraph,
                properties=enhanced_props
            )

            valid_relationships.append(canonical_rel)

            # Update stats
            stats['evidence_types'][evidence_type] += 1
            stats['subgraph_distribution'][subgraph] += 1

        logger.info(f"Validated {len(valid_relationships)} relationships")
        logger.info(f"Filtered: {stats['filtered_confidence']} low confidence, "
                   f"{stats['filtered_invalid_type_pair']} invalid type pairs, "
                   f"{stats['filtered_missing_entities']} missing entities")

        return valid_relationships, dict(stats)

    def _infer_evidence_type(self, rel: Dict) -> str:
        """
        Infer evidence type for a relationship.

        Heuristics:
        - If source_context contains experimental terms -> experimental
        - If has paper_id and evidence -> literature
        - If derived from computational analysis -> computational
        """
        source_context = rel.get('source_context', '').lower()
        evidence = rel.get('evidence', '').lower()

        # Experimental indicators
        experimental_keywords = {
            'measured', 'assayed', 'quantified', 'detected',
            'experiment', 'assay', 'analysis', 'elisa', 'pcr',
            'sequenced', 'cultured', 'incubated'
        }
        if any(kw in source_context or kw in evidence for kw in experimental_keywords):
            return EvidenceType.EXPERIMENTAL

        # Literature indicators
        if rel.get('paper_id') and evidence:
            return EvidenceType.LITERATURE

        # Computational indicators
        computational_keywords = {
            'correlation', 'associated', 'predicted', 'modeled',
            'analysis', 'statistical', 'multivariate'
        }
        if any(kw in source_context or kw in evidence for kw in computational_keywords):
            return EvidenceType.COMPUTATIONAL

        # Default
        return EvidenceType.LITERATURE

    def _enhance_properties(self, rel: Dict, evidence_type: str) -> Dict:
        """Enhance relationship properties with evidence_type and other fields."""
        enhanced = {}

        # Core fields
        if 'confidence' in rel:
            enhanced['confidence'] = rel['confidence']
        if 'evidence' in rel:
            enhanced['evidence'] = rel['evidence'][:500]  # Limit length
        if 'source_context' in rel:
            enhanced['source_context'] = rel['source_context'][:1000]  # Limit length
        if 'paper_id' in rel:
            enhanced['paper_id'] = rel['paper_id']

        # Enhanced fields
        enhanced['evidence_type'] = evidence_type

        # UMLS CUIs
        if rel.get('umls_source_cui'):
            enhanced['umls_source_cui'] = rel['umls_source_cui']
        if rel.get('umls_target_cui'):
            enhanced['umls_target_cui'] = rel['umls_target_cui']

        return enhanced


class NodeFilter:
    """
    Filter nodes and relationships to remove noise.

    Handles:
    - Identification of noise nodes (instruments, software, statistical tests)
    - Filtering of non-biological entities
    - Edge filtering based on node survival
    """

    def __init__(self):
        self.noise_patterns = self._compile_noise_patterns()
        self.biological_types = CORE_BIOLOGICAL_TYPES

    def _compile_noise_patterns(self) -> List[re.Pattern]:
        """Compile regex patterns for noise detection."""
        patterns = [
            # Instruments
            r'\b\d+\s*(nm|µm|mm|cm)\b',  # Measurements
            r'\b(Tecan|BioRad|Illumina|Qiagen)\s+\w+\b',  # Instrument models
            r'\b kit\b',  # Kits

            # Statistical tests/software
            r'\b(SPSS|SAS|R\s*package|Python\s*\d+\.\d+)\b',
            r'\b(version\s*\d+\.\d+|v\d+\.\d+)\b',

            # Common non-biological terms
            r'\b(p\s*value|p\s*<\s*0\.05|confidence interval)\b',
            r'\b(n\s*=\s*\d+)\b',
        ]
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def identify_noise_nodes(
        self,
        entities: List[CanonicalEntity]
    ) -> Set[str]:
        """
        Identify noise nodes based on type and term patterns.

        Args:
            entities: List of canonical entities

        Returns:
            Set of canonical IDs to filter
        """
        noise_ids = set()

        for entity in entities:
            # Filter by type
            if is_noise_type(entity.type):
                noise_ids.add(entity.id)
                continue

            # Filter by term patterns
            for pattern in self.noise_patterns:
                if pattern.search(entity.term):
                    noise_ids.add(entity.id)
                    break

        logger.info(f"Identified {len(noise_ids)} noise nodes to filter")
        return noise_ids

    def filter_nodes_and_relationships(
        self,
        entities: List[CanonicalEntity],
        relationships: List[CanonicalRelationship],
        keep_biological_only: bool = True
    ) -> Tuple[List[CanonicalEntity], List[CanonicalRelationship], Dict]:
        """
        Filter entities and relationships.

        Args:
            entities: List of canonical entities
            relationships: List of canonical relationships
            keep_biological_only: If True, only keep core biological types

        Returns:
            Tuple of (filtered_entities, filtered_relationships, filter_stats)
        """
        logger.info(f"Filtering {len(entities)} entities and {len(relationships)} relationships")

        stats = {
            'entities_input': len(entities),
            'entities_filtered_type': 0,
            'entities_filtered_noise': 0,
            'relationships_input': len(relationships),
            'relationships_filtered_orphaned': 0,
        }

        # Identify noise nodes
        noise_ids = self.identify_noise_nodes(entities)

        # Build set of valid entity IDs
        valid_entity_ids = set()

        for entity in entities:
            # Skip noise
            if entity.id in noise_ids:
                stats['entities_filtered_noise'] += 1
                continue

            # Filter by biological type if requested
            if keep_biological_only and entity.type not in self.biological_types:
                stats['entities_filtered_type'] += 1
                continue

            valid_entity_ids.add(entity.id)

        # Filter entities
        filtered_entities = [
            e for e in entities
            if e.id in valid_entity_ids
        ]

        # Filter relationships (remove those with filtered endpoints)
        filtered_relationships = [
            rel for rel in relationships
            if rel.source in valid_entity_ids and rel.target in valid_entity_ids
        ]

        stats['relationships_filtered_orphaned'] = \
            len(relationships) - len(filtered_relationships)

        logger.info(f"Filtered to {len(filtered_entities)} entities "
                   f"and {len(filtered_relationships)} relationships")
        logger.info(f"Removed {stats['entities_filtered_type']} non-biological, "
                   f"{stats['entities_filtered_noise']} noise nodes, "
                   f"{stats['relationships_filtered_orphaned']} orphaned relationships")

        return filtered_entities, filtered_relationships, stats


class KGRefiner:
    """
    Main orchestrator for KG refinement.

    Coordinates:
    - Entity canonicalization
    - Relationship validation
    - Node filtering
    - KG export
    """

    def __init__(self):
        self.canonicalizer = EntityCanonicalizer()
        self.filter = NodeFilter()

    def refine_kg(
        self,
        kg_path: str,
        relationships_path: str,
        output_path: str,
        min_entity_confidence: float = 0.4,
        min_rel_confidence: float = 0.5,
        keep_biological_only: bool = True
    ) -> Dict:
        """
        Refine a knowledge graph from existing files.

        Args:
            kg_path: Path to existing KG JSON
            relationships_path: Path to relationships JSON
            output_path: Path to save refined KG
            min_entity_confidence: Min confidence for entities
            min_rel_confidence: Min confidence for relationships
            keep_biological_only: Filter to biological types only

        Returns:
            Summary statistics dict
        """
        logger.info(f"Refining KG from {kg_path} and {relationships_path}")

        # Load existing KG and relationships
        with open(kg_path, 'r') as f:
            kg_data = json.load(f)

        with open(relationships_path, 'r') as f:
            rels_data = json.load(f)

        entities = kg_data.get('nodes', [])
        relationships = rels_data.get('relationships', [])

        logger.info(f"Loaded {len(entities)} nodes and {len(relationships)} relationships")

        # Step 1: Canonicalize entities
        canonical_entities = self.canonicalizer.canonicalize_entities(
            entities,
            min_confidence=min_entity_confidence
        )

        # Build maps
        entity_id_map = {e.term: e.id for e in canonical_entities}
        entity_type_map = {e.term: e.type for e in canonical_entities}

        # Step 2: Validate and enhance relationships
        validator = RelationshipValidator(entity_id_map)
        canonical_relationships, val_stats = validator.validate_and_enhance_relationships(
            relationships,
            entity_type_map,
            min_confidence=min_rel_confidence
        )

        # Step 3: Filter noise
        filtered_entities, filtered_relationships, filter_stats = \
            self.filter.filter_nodes_and_relationships(
                canonical_entities,
                canonical_relationships,
                keep_biological_only=keep_biological_only
            )

        # Step 4: Build refined KG
        refined_kg = self._build_refined_kg(
            filtered_entities,
            filtered_relationships,
            kg_data.get('metadata', {})
        )

        # Step 5: Export
        self._export_refined_kg(refined_kg, output_path)

        # Compile summary
        summary = {
            'input_nodes': len(entities),
            'input_relationships': len(relationships),
            'output_nodes': len(filtered_entities),
            'output_relationships': len(filtered_relationships),
            'validation_stats': val_stats,
            'filter_stats': filter_stats,
        }

        logger.info(f"KG refinement complete. "
                   f"Output: {len(filtered_entities)} nodes, {len(filtered_relationships)} edges")

        return summary

    def _build_refined_kg(
        self,
        entities: List[CanonicalEntity],
        relationships: List[CanonicalRelationship],
        original_metadata: Dict
    ) -> Dict:
        """Build refined KG structure."""
        # Type distribution
        node_types = Counter(e.type for e in entities)
        edge_types = Counter(r.relationship for r in relationships)
        subgraph_dist_nodes = Counter(e.subgraph for e in entities)
        subgraph_dist_edges = Counter(r.subgraph for r in relationships)

        metadata = {
            'scope': KG_SCOPE,
            'total_nodes': len(entities),
            'total_edges': len(relationships),
            'node_types': dict(sorted(node_types.items())),
            'edge_types': dict(sorted(edge_types.items())),
            'subgraph_distribution': {
                'nodes': dict(sorted(subgraph_dist_nodes.items())),
                'edges': dict(sorted(subgraph_dist_edges.items())),
            },
            'relationship_types': sorted(VALID_RELATIONSHIP_TYPES),
            'evidence_types': sorted(EvidenceType.all()),
        }

        # Merge with original metadata if available
        if original_metadata:
            for key in ['source_files', 'extraction_date']:
                if key in original_metadata:
                    metadata[key] = original_metadata[key]

        return {
            'metadata': metadata,
            'nodes': [e.to_dict() for e in entities],
            'edges': [r.to_dict() for r in relationships],
        }

    def _export_refined_kg(self, kg: Dict, output_path: str):
        """Export refined KG to JSON."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(kg, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported refined KG to {output_path}")


def refine_kg_from_files(
    kg_path: str,
    relationships_path: str,
    output_path: str,
    **kwargs
) -> Dict:
    """
    Convenience function to refine KG from file paths.

    Args:
        kg_path: Path to existing KG JSON
        relationships_path: Path to relationships JSON
        output_path: Path to save refined KG
        **kwargs: Additional args for KGRefiner.refine_kg()

    Returns:
        Summary statistics dict
    """
    refiner = KGRefiner()
    return refiner.refine_kg(
        kg_path=kg_path,
        relationships_path=relationships_path,
        output_path=output_path,
        **kwargs
    )
