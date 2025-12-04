"""
Enhanced Entity Filter and Quality Control Module
Provides multi-layer filtering for high-quality CDM entities
"""

import logging
import re
from typing import List, Dict, Set, Tuple
from collections import defaultdict
from config.cdm_config import CDMEntityConfig

logger = logging.getLogger(__name__)

class EntityFilter:
    """Advanced entity filtering and quality control."""

    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.entity_config = CDMEntityConfig()

        # Blacklist of non-biomedical terms
        self.non_biomedical_blacklist = {
            'japanese population', 'population', 'study', 'analysis', 'method',
            'approach', 'technique', 'result', 'finding', 'data', 'sample',
            'group', 'cohort', 'patient', 'subject', 'participant', 'research',
            'paper', 'article', 'publication', 'investigation', 'examination',
            'observation', 'measurement', 'assessment', 'evaluation',
            'centrifugation', 'gut colonization', 'human gut'  # Lab techniques and processes
        }

        # Entity type correction rules
        self.type_corrections = {
            # Bacterial families should be ORGANISMS
            r'.*aceae$': 'ORGANISM',
            r'.*bacteri.*': 'ORGANISM',
            r'.*cocc.*': 'ORGANISM',
            r'.*bact.*': 'ORGANISM',

            # Viral terms should be ORGANISMS
            r'.*virus.*': 'ORGANISM',
            r'.*vir.*': 'ORGANISM',

            # Fungal terms should be ORGANISMS
            r'.*myc.*': 'ORGANISM',
            r'.*fung.*': 'ORGANISM',

            # Statistical methods should not be BIOINFO_TOOLS
            r'.*correlation.*': 'GENOMICS',
            r'.*analysis.*': 'GENOMICS',
            r'.*clustering.*': 'GENOMICS',
            r'.*statistical.*': 'GENOMICS',

            # Enzyme patterns
            r'.*kinase$': 'PROTEIN',
            r'.*ase$': 'PROTEIN',
            r'.*dehydrogenase$': 'PROTEIN',

            # Gene patterns
            r'.*gene$': 'GENE',
            r'^[A-Z]{2,}[0-9]*$': 'GENE',  # Like IL6, TNF

            # Chemical patterns
            r'.*acid$': 'CHEMICAL',
            r'.*ate$': 'CHEMICAL',
            r'.*ol$': 'CHEMICAL',

            # DNA/RNA patterns
            r'.*DNA.*': 'DNA_RNA',
            r'.*RNA.*': 'DNA_RNA',
            r'^16S.*': 'DNA_RNA',
            r'.*rRNA.*': 'DNA_RNA',

            # Disease patterns
            r'.*itis$': 'DISEASE',
            r'.*osis$': 'DISEASE',
            r'.*emia$': 'DISEASE',

            # Bioinformatics tools should be BIOINFO_TOOL, not GENE
            r'^BLAST$': 'BIOINFO_TOOL',
            r'.*BLAST.*': 'BIOINFO_TOOL',
            r'^MetaPhlAn$': 'BIOINFO_TOOL',
            r'.*MetaPhlAn.*': 'BIOINFO_TOOL',
            r'.*Qiime.*': 'BIOINFO_TOOL',
            r'.*QIIME.*': 'BIOINFO_TOOL',

            # Chemical patterns (short-chain fatty acids)
            r'^butyrate$': 'CHEMICAL',
            r'^Propionate$': 'CHEMICAL',
            r'^acetate$': 'CHEMICAL',
            r'.*fatty acid.*': 'CHEMICAL',

            # Non-biomedical processes to filter
            r'.*colonization$': None,  # Will be filtered out
            r'.*extraction$': None,     # Will be filtered out if not DNA specific
        }

        # Duplicate detection patterns
        self.duplicate_patterns = [
            # Remove "family", "group", "type" suffixes for duplicate detection
            r'\s+(family|group|type|strain|species)$',
            # Remove common prefixes
            r'^(genus|family|order|class|phylum)\s+',
            # Remove strain designations and JCM numbers
            r'\s+JCM\s+\d+$',
            r'\s+\d+$',
            r'\s+subsp\.',
        ]

        # Organism name normalization mappings
        self.organism_normalizations = {
            r'^E\.?\s*coli$': 'Escherichia coli',
            r'^B\.\s*fragilis$': 'Bacteroides fragilis',
            r'^Bifidobacterium\s+longum\s+.*': 'Bifidobacterium longum',
        }

    def apply_basic_filtering(self, entities: List[Dict]) -> List[Dict]:
        """Apply basic quality filters to entities."""
        logger.info(f"🔍 Applying basic filtering to {len(entities)} entities")

        filtered_entities = []
        removed_count = 0

        for entity in entities:
            entity_name = entity.get('entity', '').strip()
            entity_type = entity.get('entity_type', '')

            # Skip if missing required fields
            if not entity_name or not entity_type:
                removed_count += 1
                continue

            # Skip blacklisted non-biomedical terms
            if self._is_blacklisted(entity_name.lower()):
                removed_count += 1
                continue

            # Skip entities that are too short or too long
            if len(entity_name) < 2 or len(entity_name) > 100:
                removed_count += 1
                continue

            # Skip if confidence is too low
            confidence = entity.get('confidence', 0.0)
            if confidence < 0.5:
                removed_count += 1
                continue

            # Apply entity type corrections
            corrected_type = self._correct_entity_type(entity_name, entity_type)

            # If None is returned, filter out this entity
            if corrected_type is None:
                removed_count += 1
                continue

            if corrected_type != entity_type:
                entity['entity_type'] = corrected_type
                entity['original_type'] = entity_type

            # Validate entity type exists in our config
            if corrected_type not in self.entity_config.ENTITY_TYPES:
                removed_count += 1
                continue

            filtered_entities.append(entity)

        logger.info(f"✅ Basic filtering: {len(entities)} → {len(filtered_entities)} entities (removed {removed_count})")
        return filtered_entities

    def remove_exact_duplicates(self, entities: List[Dict]) -> List[Dict]:
        """Remove exact duplicates (same entity name and type)."""
        logger.info(f"🔄 Removing exact duplicates from {len(entities)} entities")

        seen = set()
        unique_entities = []
        duplicates_removed = 0

        for entity in entities:
            entity_key = f"{entity['entity'].lower()}_{entity['entity_type']}"

            if entity_key not in seen:
                seen.add(entity_key)
                unique_entities.append(entity)
            else:
                duplicates_removed += 1

        logger.info(f"✅ Exact duplicate removal: {len(entities)} → {len(unique_entities)} entities (removed {duplicates_removed})")
        return unique_entities

    def remove_semantic_duplicates_simple(self, entities: List[Dict]) -> List[Dict]:
        """Remove semantic duplicates using simple string matching."""
        logger.info(f"🔄 Removing semantic duplicates from {len(entities)} entities")

        # Group by entity type
        type_groups = defaultdict(list)
        for entity in entities:
            type_groups[entity['entity_type']].append(entity)

        deduplicated = []
        total_removed = 0

        for entity_type, type_entities in type_groups.items():
            if len(type_entities) <= 1:
                deduplicated.extend(type_entities)
                continue

            # Remove semantic duplicates within this type
            unique_for_type = []
            seen_normalized = set()

            for entity in type_entities:
                normalized = self._normalize_entity_name(entity['entity'])

                if normalized not in seen_normalized:
                    seen_normalized.add(normalized)
                    unique_for_type.append(entity)
                else:
                    total_removed += 1

            deduplicated.extend(unique_for_type)

        logger.info(f"✅ Semantic duplicate removal: {len(entities)} → {len(deduplicated)} entities (removed {total_removed})")
        return deduplicated

    def apply_biomedical_validation(self, entities: List[Dict]) -> List[Dict]:
        """Apply biomedical validation rules."""
        logger.info(f"🧪 Applying biomedical validation to {len(entities)} entities")

        validated_entities = []
        invalid_count = 0

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('entity_type', '')

            # Validate specific entity types
            if not self._is_valid_biomedical_entity(entity_name, entity_type):
                invalid_count += 1
                continue

            # Add quality score
            quality_score = self._calculate_quality_score(entity)
            entity['quality_score'] = quality_score

            validated_entities.append(entity)

        logger.info(f"✅ Biomedical validation: {len(entities)} → {len(validated_entities)} entities (removed {invalid_count})")
        return validated_entities

    def _is_blacklisted(self, entity_name: str) -> bool:
        """Check if entity is in the blacklist."""
        # Direct blacklist check
        if entity_name in self.non_biomedical_blacklist:
            return True

        # Pattern-based blacklist
        blacklist_patterns = [
            r'.*\b(study|analysis|method|approach|technique|result|finding)\b.*',
            r'.*\b(paper|article|publication|research)\b.*',
            r'.*\b(patient|subject|participant|cohort|group)\b.*'
        ]

        for pattern in blacklist_patterns:
            if re.search(pattern, entity_name, re.IGNORECASE):
                return True

        return False

    def _correct_entity_type(self, entity_name: str, current_type: str) -> str:
        """Correct entity type based on name patterns."""
        entity_lower = entity_name.lower()

        for pattern, correct_type in self.type_corrections.items():
            if re.search(pattern, entity_name, re.IGNORECASE):
                # If None, this means the entity should be filtered out
                if correct_type is None:
                    return None
                return correct_type

        return current_type

    def _normalize_entity_name(self, entity_name: str) -> str:
        """Normalize entity name for duplicate detection."""
        normalized = entity_name.lower().strip()

        # Apply organism-specific normalizations first
        for pattern, replacement in self.organism_normalizations.items():
            if re.search(pattern, entity_name, re.IGNORECASE):
                normalized = replacement.lower().strip()
                break

        # Remove suffixes/prefixes that don't change meaning
        for pattern in self.duplicate_patterns:
            normalized = re.sub(pattern, '', normalized).strip()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        return normalized

    def _is_valid_biomedical_entity(self, entity_name: str, entity_type: str) -> bool:
        """Validate that entity is a proper biomedical term."""

        # ORGANISM validation
        if entity_type == 'ORGANISM':
            # Should not be generic terms
            organism_blacklist = ['bacteria', 'microbe', 'organism', 'cell', 'cells']
            if entity_name.lower() in organism_blacklist:
                return False
            # Should have at least one biological indicator
            bio_indicators = ['bacter', 'virus', 'fung', 'cocc', 'bacill', 'entero', 'staph', 'strept']
            if not any(indicator in entity_name.lower() for indicator in bio_indicators):
                return len(entity_name.split()) > 1  # Allow multi-word organisms

        # GENE validation
        elif entity_type == 'GENE':
            # Should not be family names
            if entity_name.lower().endswith('family') or entity_name.lower().endswith('aceae'):
                return False

        # DISEASE validation
        elif entity_type == 'DISEASE':
            # Should not be populations or demographics
            disease_blacklist = ['population', 'japanese', 'american', 'cohort', 'group']
            if any(blacklisted in entity_name.lower() for blacklisted in disease_blacklist):
                return False

        # CHEMICAL validation
        elif entity_type == 'CHEMICAL':
            # Should not be processes or methods
            if entity_name.lower().endswith('tion') or entity_name.lower().endswith('ment'):
                return False

        # 5. Check for Author names and Affiliations (Junk filtering)
        if 'et al' in entity_name.lower():
            return False
            
        affiliation_keywords = {
            'university', 'institute', 'department', 'center', 'centre', 'college', 'school',
            'hospital', 'laboratory', 'foundation', 'group', 'consortium', 'ministry',
            'academy', 'division', 'unit', 'program', 'programme', 'council', 'bureau',
            'author', 'correspondence', 'email', 'address', 'tel', 'fax', 'phd', 'md',
            'professor', 'prof', 'dr', 'scientist', 'researcher'
        }
        
        # Check if any affiliation keyword is in the term
        term_lower = entity_name.lower()
        if any(keyword in term_lower.split() for keyword in affiliation_keywords):
            return False
            
        # Check for citation patterns like (Smith 2020) or [1]
        if re.search(r'\(\w+\s+\d{4}\)', entity_name) or re.search(r'\[\d+\]', entity_name):
            return False

        # 6. Check for Grant Numbers (e.g., R01HD078912)
        # Pattern: 1-3 letters, 2 digits, 1-3 letters, 5-6 digits
        if re.match(r'^[A-Z]{1,4}\d{2,5}[A-Z]{0,3}\d{4,8}$', entity_name, re.IGNORECASE):
            return False
        if re.search(r'\b(grant|award|contract)\s+(no\.?|number)?\s*[A-Z0-9-]+\b', term_lower):
            return False

        # 7. Check for Journal Names and Publishers
        journal_blocklist = {
            'frontiers in', 'bmj open', 'nature', 'science', 'cell host', 'plos one',
            'scientific reports', 'journal of', 'annals of', 'proceedings of',
            'nucleic acids res', 'genome biol', 'nat methods', 'sci transl med'
        }
        if any(j in term_lower for j in journal_blocklist):
            return False

        # 8. Check for Broad/Generic Terms
        broad_terms = {
            'microbiome', 'viral', 'amino acids', 'bacteria', 'fungi', 'archaea',
            'microbiota', 'gut microbiota', 'bacterial', 'microbial', 'pathogen',
            'probiotic', 'prebiotic', 'antibiotic', 'metabolome', 'genome',
            'metagenome', 'transcriptome', 'proteome', 'lipidome'
        }
        if term_lower in broad_terms:
            return False

        # Reject if term is in artifacts
        if entity_name.lower() in ['none', 'n/a', 'null', 'unknown']:
            return False

        return True

    def _calculate_quality_score(self, entity: Dict) -> float:
        """Calculate a quality score for the entity (0.0-1.0)."""
        score = 0.0

        # Base score from confidence
        score += entity.get('confidence', 0.0) * 0.4

        # Context presence bonus
        if entity.get('context', '').strip():
            score += 0.2

        # Entity length score (prefer moderate length)
        entity_length = len(entity.get('entity', ''))
        if 5 <= entity_length <= 30:
            score += 0.2
        elif 3 <= entity_length <= 50:
            score += 0.1

        # Multi-word entity bonus (often more specific)
        if len(entity.get('entity', '').split()) > 1:
            score += 0.1

        # Type appropriateness bonus
        if self._is_appropriate_type(entity.get('entity', ''), entity.get('entity_type', '')):
            score += 0.1

        return min(score, 1.0)

    def _is_appropriate_type(self, entity_name: str, entity_type: str) -> bool:
        """Check if the entity type is appropriate for the entity name."""
        # This is a simplified check - could be enhanced with more rules
        appropriate_patterns = {
            'ORGANISM': [r'.*bacter.*', r'.*virus.*', r'.*fung.*', r'.*cocc.*'],
            'GENE': [r'.*gene$', r'^[A-Z]{2,}[0-9]*$', r'.*[0-9]+$'],
            'PROTEIN': [r'.*protein$', r'.*enzyme$', r'.*kinase$', r'.*ase$'],
            'CHEMICAL': [r'.*acid$', r'.*ate$', r'.*ol$', r'.*ldehyde$'],
            'DISEASE': [r'.*itis$', r'.*osis$', r'.*emia$', r'.*cancer$'],
            'DNA_RNA': [r'.*DNA.*', r'.*RNA.*', r'^16S.*', r'.*rRNA.*'],
        }

        if entity_type in appropriate_patterns:
            for pattern in appropriate_patterns[entity_type]:
                if re.search(pattern, entity_name, re.IGNORECASE):
                    return True

        return True  # Default to appropriate if no specific pattern

    def apply_comprehensive_filtering(self, entities: List[Dict]) -> List[Dict]:
        """Apply all filtering steps in sequence."""
        logger.info(f"🚀 Starting comprehensive filtering on {len(entities)} entities")

        # Step 1: Basic filtering
        filtered = self.apply_basic_filtering(entities)

        # Step 2: Remove exact duplicates
        filtered = self.remove_exact_duplicates(filtered)

        # Step 3: Remove semantic duplicates
        filtered = self.remove_semantic_duplicates_simple(filtered)

        # Step 4: Biomedical validation
        filtered = self.apply_biomedical_validation(filtered)

        # Sort by quality score if available
        if filtered and 'quality_score' in filtered[0]:
            filtered.sort(key=lambda x: x.get('quality_score', 0), reverse=True)

        logger.info(f"✅ Comprehensive filtering complete: {len(entities)} → {len(filtered)} final entities")
        return filtered