"""
Local OMOP CDM Mapper for Microbiome Entities
Maps extracted entities to OMOP Common Data Model using local vocabulary files
Based on the fast mapping implementation from omop_mapping/mapping.py
"""

import os
import re
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from rapidfuzz import process, fuzz
import tempfile
import subprocess

logger = logging.getLogger(__name__)

@dataclass
class OMOPMapping:
    """OMOP mapping result."""
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    standard_concept: str
    concept_code: str
    valid_start_date: str
    valid_end_date: str
    invalid_reason: str
    create_time: str
    mapping_confidence: float
    mapping_method: str

class OMOPLocalMapper:
    """Maps CDM entities to OMOP standard concepts using local vocabulary."""

    def __init__(self, vocab_dir: str = None, fuzzy_threshold: int = 95, max_matches: int = 3):
        """
        Initialize the OMOP local mapper.

        Args:
            vocab_dir: Path to OMOP vocabulary directory
            fuzzy_threshold: Minimum fuzzy matching score (default: 95)
            max_matches: Maximum matches per entity (default: 3)
        """
        # Use project-relative path as default instead of user-specific path
        if vocab_dir:
            self.vocab_dir = vocab_dir
        else:
            # Default to data/omop_vocab relative to project root
            default_dir = Path(__file__).parent.parent.parent / 'data' / 'omop_vocab'
            self.vocab_dir = os.environ.get('OMOP_VOCAB_DIR', str(default_dir))

        self.fuzzy_threshold = fuzzy_threshold
        self.max_matches = max_matches

        # Initialize lookup tables
        self.lookup_df = None
        self.standard_concepts = None
        self._initialize_lookup()

        # Entity type to OMOP domain mappings
        self.entity_type_mappings = {
            "GENE": {
                "domain_id": "Genetic",
                "concept_classes": ["Gene", "Gene Variant", "Genomic Finding"]
            },
            "PROTEIN": {
                "domain_id": "Genetic",
                "concept_classes": ["Protein", "Biomarker", "Enzyme"]
            },
            "CHEMICAL": {
                "domain_id": "Drug",
                "concept_classes": ["Drug", "Compound", "Chemical Substance", "Clinical Drug"]
            },
            "DISEASE": {
                "domain_id": "Condition",
                "concept_classes": ["Clinical Finding", "Disease", "Disorder"]
            },
            "CELL_TYPE": {
                "domain_id": "Measurement",
                "concept_classes": ["Cell Type", "Cell Finding", "Laboratory Test"]
            },
            "DNA_RNA": {
                "domain_id": "Genetic",
                "concept_classes": ["DNA Sequence", "RNA Sequence", "Genomic Finding"]
            },
            "ORGANISM": {
                "domain_id": "Measurement",
                "concept_classes": ["Organism", "Microorganism", "Bacterial Finding"]
            },
            "CLINICAL": {
                "domain_id": "Observation",
                "concept_classes": ["Clinical Finding", "Observation", "Sign", "Clinical Observation"]
            }
        }

    def _initialize_lookup(self):
        """Initialize OMOP lookup tables from vocabulary files."""
        try:
            if not os.path.exists(self.vocab_dir):
                logger.warning(f"OMOP vocabulary directory not found: {self.vocab_dir}")
                self.lookup_df = pd.DataFrame(columns=['concept_id', 'term_lower', 'term_len'])
                self.standard_concepts = pd.DataFrame()
                return

            logger.info(f"Initializing OMOP lookup from: {self.vocab_dir}")

            # Load concepts and synonyms
            concepts = self._load_concepts()
            synonyms = self._load_synonyms()

            # Build lookup table
            self.lookup_df, self.standard_concepts = self._build_lookup(concepts, synonyms)

            logger.info(f"✅ OMOP lookup initialized with {len(self.lookup_df):,} entries")

        except Exception as e:
            logger.error(f"Failed to initialize OMOP lookup: {e}")
            self.lookup_df = pd.DataFrame(columns=['concept_id', 'term_lower', 'term_len'])
            self.standard_concepts = pd.DataFrame()

    def _preprocess_term(self, term: str) -> str:
        """Preprocess term for matching."""
        if not isinstance(term, str) or not term.strip():
            return ""
        term = term.lower()
        term = re.sub(r'[^a-z0-9\s]', ' ', term)
        term = re.sub(r'\b(and|or|of|the|a|an|with|for|in|on|to|at|by|as)\b', ' ', term)
        term = re.sub(r'\s+', ' ', term).strip()
        return term

    def _load_concepts(self) -> pd.DataFrame:
        """Load CONCEPT.csv file."""
        logger.info("Loading CONCEPT.csv...")
        path = os.path.join(self.vocab_dir, 'CONCEPT.csv')

        if not os.path.exists(path):
            logger.warning(f"CONCEPT.csv not found at: {path}")
            return pd.DataFrame()

        df = pd.read_csv(
            path, sep='\t',
            usecols=['concept_id', 'concept_name', 'standard_concept', 'invalid_reason', 'domain_id', 'vocabulary_id', 'concept_class_id'],
            dtype=str, na_filter=False
        )
        df = df[df['invalid_reason'] == '']
        logger.info(f"Loaded {len(df):,} valid concepts")
        return df

    def _load_synonyms(self) -> pd.DataFrame:
        """Load CONCEPT_SYNONYM.csv file."""
        logger.info("Loading CONCEPT_SYNONYM.csv...")
        path = os.path.join(self.vocab_dir, 'CONCEPT_SYNONYM.csv')

        if not os.path.exists(path):
            logger.warning(f"CONCEPT_SYNONYM.csv not found at: {path}")
            return pd.DataFrame()

        df = pd.read_csv(
            path, sep='\t',
            usecols=['concept_id', 'concept_synonym_name'],
            dtype=str, na_filter=False
        )
        return df[df['concept_synonym_name'] != '']

    def _build_lookup(self, concepts: pd.DataFrame, synonyms: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build lookup table from concepts and synonyms."""
        if concepts.empty:
            return pd.DataFrame(), pd.DataFrame()

        # Filter to standard concepts only
        standard_concepts = concepts[concepts['standard_concept'] == 'S'].copy()
        standard_ids = set(standard_concepts['concept_id'])

        # Get synonyms for standard concepts
        synonym_std = synonyms[synonyms['concept_id'].isin(standard_ids)].copy()

        # Build lookup from concept names
        names = standard_concepts[['concept_id', 'concept_name']].copy()
        names['term_lower'] = names['concept_name'].apply(self._preprocess_term)

        # Build lookup from synonyms
        synonym_std['term_lower'] = synonym_std['concept_synonym_name'].apply(self._preprocess_term)

        # Combine names and synonyms
        lookup = pd.concat([
            names[['concept_id', 'term_lower']],
            synonym_std[['concept_id', 'term_lower']]
        ], ignore_index=True)

        # Clean up lookup
        lookup = lookup[lookup['term_lower'] != '']
        lookup.drop_duplicates(['term_lower', 'concept_id'], inplace=True)
        lookup['term_len'] = lookup['term_lower'].str.len()

        logger.info(f"Built lookup with {len(lookup):,} entries from {len(standard_concepts):,} standard concepts")
        return lookup, standard_concepts

    def _get_fuzzy_matches(self, term: str) -> List[Tuple[str, int, float]]:
        """Get fuzzy matches for a term."""
        if not term or self.lookup_df.empty:
            return []

        # Get candidate terms by length (optimization)
        tlen = len(term)
        candidates_df = self.lookup_df[
            (self.lookup_df['term_len'] >= max(1, tlen - 3)) &
            (self.lookup_df['term_len'] <= tlen + 3)
        ]

        if candidates_df.empty:
            candidates_df = self.lookup_df

        candidate_terms = candidates_df['term_lower'].tolist()

        # Use rapidfuzz for fast fuzzy matching
        results = process.extract(
            term, candidate_terms,
            scorer=fuzz.ratio,
            limit=self.max_matches * 2  # Get more results, filter later
        )

        matches = []
        for matched_term, score, _ in results:
            if score < self.fuzzy_threshold:
                break
            if len(matches) >= self.max_matches:
                break

            concept_id = candidates_df.loc[
                candidates_df['term_lower'] == matched_term, 'concept_id'
            ].iloc[0]
            matches.append((concept_id, matched_term, score))

        return matches

    def _get_exact_matches(self, term: str) -> List[Tuple[str, int, float]]:
        """Get exact matches for a term."""
        if not term or self.lookup_df.empty:
            return []

        term_clean = self._preprocess_term(term)
        matches = self.lookup_df[self.lookup_df['term_lower'] == term_clean]

        return [(row['concept_id'], term_clean, 100.0) for _, row in matches.iterrows()]

    def map_entity_to_omop(self, entity_name: str, entity_type: str) -> List[OMOPMapping]:
        """Map a single entity to OMOP concepts."""
        mappings = []

        try:
            # Get entity type configuration
            entity_config = self.entity_type_mappings.get(entity_type, {})

            # Try exact matching first
            exact_matches = self._get_exact_matches(entity_name)

            # If no exact matches, try fuzzy matching
            fuzzy_matches = self._get_fuzzy_matches(entity_name) if not exact_matches else []

            all_matches = exact_matches + fuzzy_matches

            for concept_id, matched_term, score in all_matches:
                # Get concept details
                concept_info = self.standard_concepts[
                    self.standard_concepts['concept_id'] == concept_id
                ]

                if concept_info.empty:
                    continue

                concept_row = concept_info.iloc[0]

                # Check if matches entity type domain
                target_domain = entity_config.get('domain_id')
                if target_domain and concept_row['domain_id'] != target_domain:
                    # Still include but with lower confidence
                    confidence_adjustment = 0.8
                else:
                    confidence_adjustment = 1.0

                # Create mapping
                mapping = OMOPMapping(
                    concept_id=int(concept_row['concept_id']),
                    concept_name=concept_row['concept_name'],
                    domain_id=concept_row['domain_id'],
                    vocabulary_id=concept_row['vocabulary_id'],
                    concept_class_id=concept_row['concept_class_id'],
                    standard_concept=concept_row['standard_concept'],
                    concept_code=concept_row['concept_id'],  # Use concept_id as code
                    valid_start_date="1970-01-01",
                    valid_end_date="2099-12-31",
                    invalid_reason="",
                    create_time="",
                    mapping_confidence=min(score / 100.0 * confidence_adjustment, 1.0),
                    mapping_method="Exact" if score == 100.0 else "Fuzzy"
                )
                mappings.append(mapping)

            # Sort by confidence and limit results
            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)
            mappings = mappings[:self.max_matches]

        except Exception as e:
            logger.debug(f"Error mapping {entity_name} to OMOP: {e}")

        return mappings

    def map_entity_list(self, entities: List[Dict]) -> List[Dict]:
        """Map a list of entities to OMOP concepts."""
        if self.lookup_df is None or self.lookup_df.empty:
            logger.warning("OMOP lookup not initialized, skipping mapping")
            return entities

        mapped_entities = []
        mapping_count = 0

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('type', '')

            if not entity_name or not entity_type:
                mapped_entities.append(entity)
                continue

            # Get OMOP mappings
            omop_mappings = self.map_entity_to_omop(entity_name, entity_type)

            if omop_mappings:
                mapping_count += 1

            # Enhance entity with OMOP mappings
            enhanced_entity = {
                **entity,
                'omop_mappings': [vars(mapping) for mapping in omop_mappings],
                'has_omop_mapping': len(omop_mappings) > 0,
                'best_omop_confidence': max([m.mapping_confidence for m in omop_mappings], default=0.0),
                'omop_domain_id': omop_mappings[0].domain_id if omop_mappings else None,
                'omop_concept_count': len(omop_mappings)
            }

            mapped_entities.append(enhanced_entity)

        logger.info(f"🏥 OMOP mapping: {mapping_count}/{len(entities)} entities mapped using local vocabulary")
        return mapped_entities

    def generate_omop_summary(self, entities: List[Dict]) -> Dict:
        """Generate summary statistics for OMOP mappings."""
        mapped_entities = [e for e in entities if e.get('has_omop_mapping', False)]

        domain_counts = {}
        vocab_counts = {}
        method_counts = {}
        total_mappings = 0
        high_confidence_count = 0

        for entity in mapped_entities:
            mappings = entity.get('omop_mappings', [])
            total_mappings += len(mappings)

            for mapping in mappings:
                domain_id = mapping.get('domain_id', 'Unknown')
                vocab_id = mapping.get('vocabulary_id', 'Unknown')
                method = mapping.get('mapping_method', 'Unknown')
                confidence = mapping.get('mapping_confidence', 0)

                domain_counts[domain_id] = domain_counts.get(domain_id, 0) + 1
                vocab_counts[vocab_id] = vocab_counts.get(vocab_id, 0) + 1
                method_counts[method] = method_counts.get(method, 0) + 1

                if confidence >= 0.8:
                    high_confidence_count += 1

        return {
            "total_entities": len(entities),
            "mapped_entities": len(mapped_entities),
            "mapping_rate": len(mapped_entities) / len(entities) if entities else 0,
            "total_mappings": total_mappings,
            "high_confidence_mappings": high_confidence_count,
            "domain_distribution": domain_counts,
            "vocabulary_distribution": vocab_counts,
            "method_distribution": method_counts,
            "average_confidence": sum([e.get('best_omop_confidence', 0) for e in entities]) / len(entities) if entities else 0,
            "lookup_entries": len(self.lookup_df) if self.lookup_df is not None else 0
        }

# Convenience function to initialize mapper with environment variable
def get_omop_mapper(vocab_dir: str = None, fuzzy_threshold: int = 95, max_matches: int = 3) -> OMOPLocalMapper:
    """Get OMOP local mapper instance."""
    return OMOPLocalMapper(
        vocab_dir=vocab_dir,
        fuzzy_threshold=fuzzy_threshold,
        max_matches=max_matches
    )