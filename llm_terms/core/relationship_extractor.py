"""
Entity Relationship Extractor Module
==================================
Extracts relationships between biomedical entities using LLM analysis.
Builds knowledge graphs for microbiome-domain entities.
"""

import logging
import json
import re
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

logger = logging.getLogger(__name__)


@dataclass
class EntityRelationship:
    """Represents a relationship between two entities."""
    source_entity: str
    source_type: str
    target_entity: str
    target_type: str
    relationship_type: str
    confidence: float
    evidence: str
    source_context: str
    paper_id: Optional[str] = None
    umls_source_cui: Optional[str] = None
    umls_target_cui: Optional[str] = None
    evidence_type: Optional[str] = None  # New: literature|experimental|computational


class RelationshipExtractor:
    """Extracts relationships between biomedical entities using LLM."""

    # Microbiome-specific relationship types
    RELATIONSHIP_TYPES = {
        # Organism interactions
        'ORGANISM-causes-DISEASE': 'Organism causes disease',
        'ORGANISM-treats-DISEASE': 'Organism (probiotic) treats disease',
        'ORGANISM-associates_with-DISEASE': 'Organism associated with disease',
        'ORGANISM-produces-CHEMICAL': 'Organism produces chemical/metabolite',
        'ORGANISM-consumes-CHEMICAL': 'Organism consumes chemical',

        # Molecular interactions
        'GENE-encodes-PROTEIN': 'Gene encodes protein',
        'GENE-regulates-GENE': 'Gene regulates another gene',
        'PROTEIN-interacts_with-PROTEIN': 'Protein-protein interaction',
        'PROTEIN-inhibits-PROTEIN': 'Protein inhibits another protein',
        'PROTEIN-activates-PROTEIN': 'Protein activates another protein',

        # Chemical relationships
        'CHEMICAL-treats-DISEASE': 'Chemical treats disease',
        'CHEMICAL-causes-DISEASE': 'Chemical causes disease',
        'CHEMICAL-binds_to-PROTEIN': 'Chemical binds to protein',
        'CHEMICAL-inhibits-PROTEIN': 'Chemical inhibits protein',

        # Disease relationships
        'DISEASE-has_symptom-CLINICAL': 'Disease has clinical symptom',
        'DISEASE-characterized_by-CLINICAL': 'Disease characterized by clinical finding',

        # General associations
        'ENTITY-co_occurs_with-ENTITY': 'Entities mentioned together',
        'ENTITY-correlates_with-ENTITY': 'Statistical correlation',

        # Entity-Microbiome relationships (NEW)
        'ORGANISM-inhabits-MICROBIOME': 'Organism lives in microbiome/gut',
        'ORGANISM-alters-MICROBIOME': 'Organism changes microbiome composition',
        'CHEMICAL-disrupts-MICROBIOME': 'Chemical disrupts microbiome (e.g., antibiotics)',
        'CHEMICAL-modulates-MICROBIOME': 'Chemical modulates microbiome (e.g., prebiotics)',
        'DISEASE-alters-MICROBIOME': 'Disease changes microbiome composition',
        'DISEASE-associated_with-MICROBIOME': 'Disease linked to microbiome state',
        'GENE-expressed_in-MICROBIOME': 'Gene expressed in microbiome context',
        'PROTEIN-affects-MICROBIOME': 'Protein affects microbiome function',

        # Experimental/Method relationships (NEW)
        'ENTITY-measured_by-DATA_ANALYSIS': 'Entity measured by method',
        'ENTITY-analyzed_by-DATA_ANALYSIS': 'Entity analyzed by method',
        'ENTITY-derived_from-DATA_ANALYSIS': 'Entity derived from analysis',
    }

    # Type compatibility for relationships
    VALID_TYPE_PAIRS = {
        ('ORGANISM', 'DISEASE'): ['causes', 'treats', 'associates_with', 'exacerbates', 'ameliorates'],
        ('DISEASE', 'ORGANISM'): ['caused_by', 'treated_by', 'associated_with'],
        ('ORGANISM', 'CHEMICAL'): ['produces', 'consumes', 'metabolizes'],
        ('CHEMICAL', 'ORGANISM'): ['produced_by', 'consumed_by'],
        ('GENE', 'PROTEIN'): ['encodes', 'regulates', 'transcribes'],
        ('PROTEIN', 'GENE'): ['encoded_by'],
        ('PROTEIN', 'PROTEIN'): ['interacts_with', 'inhibits', 'activates', 'binds_to', 'modifies'],
        ('CHEMICAL', 'PROTEIN'): ['binds_to', 'inhibits', 'activates', 'modifies'],
        ('PROTEIN', 'CHEMICAL'): ['binds', 'inhibited_by'],
        ('CHEMICAL', 'DISEASE'): ['treats', 'causes', 'prevents', 'exacerbates'],
        ('DISEASE', 'CHEMICAL'): ['treated_by', 'caused_by'],
        ('DISEASE', 'CLINICAL'): ['has_symptom', 'characterized_by'],
        ('DNA_RNA', 'GENE'): ['transcribes_to'],
        ('GENE', 'DNA_RNA'): ['transcribed_from'],

        # Experimental/Method relationships (NEW)
        ('ORGANISM', 'DATA_ANALYSIS'): ['measured_by', 'analyzed_by', 'derived_from'],
        ('CHEMICAL', 'DATA_ANALYSIS'): ['measured_by', 'analyzed_by', 'derived_from'],
        ('GENE', 'DATA_ANALYSIS'): ['measured_by', 'analyzed_by'],
        ('PROTEIN', 'DATA_ANALYSIS'): ['measured_by', 'analyzed_by'],
        ('DISEASE', 'DATA_ANALYSIS'): ['measured_by', 'analyzed_by', 'derived_from'],
        ('CLINICAL', 'DATA_ANALYSIS'): ['measured_by', 'analyzed_by', 'derived_from'],
    }

    def __init__(self, llm_client, min_confidence: float = 0.6):
        self.llm_client = llm_client
        self.min_confidence = min_confidence

        # Microbiome-specific context keywords
        self.microbiome_context = {
            'gut', 'microbiome', 'microbiota', 'fecal', 'stool', 'intestinal',
            'colon', 'ileum', 'cecum', 'mucosa', 'lumen', 'mucus',
            'dysbiosis', 'symbiosis', 'commensal', 'pathogen',
            'fermentation', 'metabolite', 'scfa', 'short-chain', 'butyrate',
            'propionate', 'acetate', 'lactate', 'succinate', 'formate',
            'firmicutes', 'bacteroidetes', 'proteobacteria', 'actinobacteria',
            'prevotella', 'bacteroides', 'faecalibacterium', 'lactobacillus',
            'bifidobacterium', 'clostridium', 'escherichia', 'enterobacteriaceae'
        }

        # Fuzzy matching: entity normalization dictionary
        self.entity_normalization_map = {
            # Common variations
            'e.coli': 'escherichia coli',
            'e. coli': 'escherichia coli',
            'e coli': 'escherichia coli',
            'ecoli': 'escherichia coli',
            # Clinical terms normalization
            'high cu microbiomes': 'high carbohydrate unavailable microbiomes',
            'low cu microbiomes': 'low carbohydrate unavailable microbiomes',
            'cu microbiomes': 'carbohydrate unavailable microbiomes',
            # Organism name standardization
            'f. prausnitzii': 'faecalibacterium prausnitzii',
            'bifido': 'bifidobacterium',
            'lacto': 'lactobacillus',
            'strep': 'streptococcus',
        }

        # Invalid entity patterns (generic terms that shouldn't be entities)
        self.invalid_entity_patterns = [
            r'^high\s+\w+\s+microrob?iomes?$',
            r'^low\s+\w+\s+microrob?iomes?$',
            r'^\d+\s*(samples|subjects|patients)$',
            r'^figure\s+\d+[a-z]?$',
            r'^table\s+\d+[a-z]?$',
        ]

    def normalize_entity_name(self, entity_name: str) -> str:
        """
        Normalize entity name using fuzzy matching and lookup tables.
        Returns the normalized name or original if no match found.
        """
        if not entity_name:
            return entity_name

        entity_lower = entity_name.lower().strip()

        # Check if it's in our normalization map
        if entity_lower in self.entity_normalization_map:
            return self.entity_normalization_map[entity_lower]

        # Check invalid patterns
        import re
        for pattern in self.invalid_entity_patterns:
            if re.match(pattern, entity_lower, re.IGNORECASE):
                logger.debug(f"Filtered invalid entity pattern: {entity_name}")
                return None  # Signal that this entity should be filtered

        # Try fuzzy matching for organism names
        from fuzzywuzzy import fuzz
        for normalized, full_name in self.entity_normalization_map.items():
            if fuzz.ratio(entity_lower, normalized) > 85:
                logger.debug(f"Fuzzy matched {entity_name} -> {full_name}")
                return full_name

        return entity_name

    def calculate_entity_similarity(self, entity1: str, entity2: str) -> float:
        """
        Calculate semantic similarity between two entity names using multiple strategies.
        Returns similarity score 0.0-1.0.
        """
        if not entity1 or not entity2:
            return 0.0

        # Strategy 1: Exact match (after normalization)
        norm1 = self.normalize_entity_name(entity1.lower())
        norm2 = self.normalize_entity_name(entity2.lower())
        if norm1 and norm2 and norm1 == norm2:
            return 1.0

        # Strategy 2: Fuzzy string matching
        from fuzzywuzzy import fuzz
        fuzzy_score = fuzz.ratio(entity1.lower(), entity2.lower()) / 100.0

        # Strategy 3: Contains relationship
        if entity1.lower() in entity2.lower() or entity2.lower() in entity1.lower():
            return 0.9

        # Strategy 4: Taxonomic similarity (for organisms)
        # Split by space and check if they share genus/species
        words1 = set(entity1.lower().split())
        words2 = set(entity2.lower().split())
        if words1 & words2:  # Intersection
            shared_ratio = len(words1 & words2) / max(len(words1), len(words2))
            return max(fuzzy_score, shared_ratio)

        return fuzzy_score

    def validate_entity_pair(self, entity_a: Dict, entity_b: Dict, context: str) -> Tuple[bool, str]:
        """
        Validate if an entity pair should have a relationship extracted.
        Uses multiple strategies: fuzzy matching, semantic validation, LLM verification.

        Returns:
            (is_valid, reason)
        """
        term_a = entity_a.get('term', '').strip()
        term_b = entity_b.get('term', '').strip()

        # Normalize entity names
        norm_a = self.normalize_entity_name(term_a)
        norm_b = self.normalize_entity_name(term_b)

        # Filter invalid entities
        if norm_a is None or norm_b is None:
            return False, "Invalid entity pattern"

        # Check for self-relationships
        if norm_a == norm_b:
            return False, "Self-relationship"

        # Check if entities are too generic (single words that are common)
        generic_terms = {'study', 'analysis', 'data', 'result', 'group', 'sample', 'level'}
        if term_a.lower() in generic_terms or term_b.lower() in generic_terms:
            return False, "Too generic"

        # Check if entities actually co-occur in context
        if not self._entities_co_occur_in_context(term_a, term_b, context):
            return False, "No co-occurrence in context"

        # Check semantic similarity - if too similar, likely same entity
        similarity = self.calculate_entity_similarity(term_a, term_b)
        if similarity > 0.95:
            return False, f"Too similar (similarity: {similarity:.2f})"

        # Entity type compatibility check
        type_a = entity_a.get('categories', entity_a.get('entity_type', 'UNKNOWN'))
        type_b = entity_b.get('categories', entity_b.get('entity_type', 'UNKNOWN'))

        # Discourage certain type combinations
        discouraged_pairs = [
            ('CLINICAL', 'CLINICAL'),
            ('DATA_ANALYSIS', 'DATA_ANALYSIS'),
            ('SCIENTIFIC_TERM', 'SCIENTIFIC_TERM'),
        ]

        if (type_a, type_b) in discouraged_pairs:
            # Only allow if explicitly stated with high confidence
            return True, "Allowed with caution"

        return True, "Valid"

    def score_microbiome_relevance(self, entity: Dict) -> float:
        """
        Score how relevant an entity is to microbiome research (0.0-1.0).
        Based on contextual definition and entity properties.
        """
        term = entity.get('term', '').lower()
        context = entity.get('contextual_definition', entity.get('definition', '')).lower()
        category = entity.get('categories', entity.get('entity_type', ''))

        score = 0.0

        # High relevance: direct microbiome terms
        if any(mw in term for mw in ['microbiome', 'microbiota', 'gut', 'fecal', 'stool']):
            score += 0.5

        # Check context for microbiome keywords
        mw_keywords = {
            'microbiome', 'microbiota', 'gut flora', 'intestinal flora',
            'fecal', 'stool', 'commensal', 'dysbiosis', 'symbiosis',
            'probiotic', 'prebiotic', 'synbiotic', 'postbiotic',
            'short-chain fatty acid', 'scfa', 'butyrate', 'propionate',
            'lactobacillus', 'bifidobacterium', 'bacteroides', 'firmicutes',
            'bacteroidetes', 'faecalibacterium', 'akkermansia',
            'intestinal', 'colon', 'ileum', 'cecum', 'mucosa'
        }

        context_hits = sum(1 for kw in mw_keywords if kw in context)
        score += min(context_hits * 0.1, 0.5)

        # Entity type relevance
        if category == 'ORGANISM':
            score += 0.2
        elif category in ['CHEMICAL', 'GENE', 'PROTEIN']:
            # Check if explicitly related to microbiome in context
            if any(mw in context for mw in ['microbi', 'gut', 'intestinal', 'fecal']):
                score += 0.3
        elif category in ['DISEASE', 'CLINICAL']:
            # Many diseases are microbiome-related
            if any(mw in context for mw in ['microbi', 'gut', 'intestinal']):
                score += 0.2

        return min(score, 1.0)

    def extract_relationship_with_llm_verification(
        self,
        entity_a: Dict,
        entity_b: Dict,
        context: str,
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """
        Extract relationship with enhanced LLM verification using contextual definitions
        and microbiome relevance scoring. Uses qwen3:30B for better understanding.
        """
        term_a = entity_a.get('term', '').strip()
        term_b = entity_b.get('term', '').strip()
        type_a = entity_a.get('categories', entity_a.get('entity_type', 'UNKNOWN'))
        type_b = entity_b.get('categories', entity_b.get('entity_type', 'UNKNOWN'))

        # Get contextual definitions
        ctx_a = entity_a.get('contextual_definition', entity_a.get('definition', ''))[:800]
        ctx_b = entity_b.get('contextual_definition', entity_b.get('definition', ''))[:800]

        # Score microbiome relevance
        relevance_a = self.score_microbiome_relevance(entity_a)
        relevance_b = self.score_microbiome_relevance(entity_b)
        avg_relevance = (relevance_a + relevance_b) / 2

        # Normalize entity names
        norm_a = self.normalize_entity_name(term_a)
        norm_b = self.normalize_entity_name(term_b)

        if not norm_a or not norm_b:
            return []

        # Use normalized names in prompt
        display_a = norm_a if norm_a != term_a else term_a
        display_b = norm_b if norm_b != term_b else term_b

        # Enhanced prompt with contextual definitions and microbiome analysis
        prompt = f"""You are an expert biomedical relationship extractor with deep knowledge of microbiome science, molecular biology, and clinical research.

## TASK
Extract the relationship between two entities based on their contextual definitions and the text where they co-occur.

## ENTITY A
Name: {display_a} {"(original: " + term_a + ")" if norm_a != term_a else ""}
Type: {type_a}
Contextual Definition: {ctx_a if ctx_a else "Not provided"}
Microbiome Relevance Score: {relevance_a:.2f}

## ENTITY B
Name: {display_b} {"(original: " + term_b + ")" if norm_b != term_b else ""}
Type: {type_b}
Contextual Definition: {ctx_b if ctx_b else "Not provided"}
Microbiome Relevance Score: {relevance_b:.2f}

## SHARED CONTEXT (where both entities appear)
\"\"\"
{context}
\"\"\"

## VALID RELATIONSHIP TYPES

**Causal/Treatment:**
- causes: Entity A directly causes Entity B (disease, symptom, condition)
- treats: Entity A treats Entity B (drug, probiotic, therapy)
- prevents: Entity A prevents Entity B
- exacerbates: Entity A makes Entity B worse

**Molecular/Genetic:**
- encodes: Gene encodes protein/RNA
- regulates: Gene/protein regulates another
- inhibits: Entity A inhibits Entity B
- activates: Entity A activates Entity B
- binds_to: Physical binding interaction
- interacts_with: General molecular interaction

**Metabolic/Functional:**
- produces: Organism produces chemical/metabolite (e.g., bacteria produces butyrate)
- consumes: Organism consumes substrate
- metabolizes: Organism transforms chemical

**Statistical/Associative:**
- associated_with: General association or correlation
- correlates_with: Statistical correlation
- co_occurs_with: Found together (not necessarily causal)

**Experimental/Methodological:**
- measured_by: Entity measured by method/experiment
- analyzed_by: Entity analyzed by method
- derived_from: Entity derived from analysis

## VALIDATION RULES (STRICT)

1. **Co-occurrence Required:** BOTH entities must be explicitly mentioned in the shared context
2. **Direct Relationship:** The relationship must be clearly stated or strongly implied
3. **Reject Generic Terms:** Do not extract relationships with generic phrases like:
   - "high X microbiomes" (unless X is a specific clinical entity)
   - "data analysis", "statistical test", "p-value"
   - "Figure X", "Table Y", "Supplemental"
4. **Microbiome Context:** Give HIGHER confidence (0.8-1.0) for:
   - Organism-disease relationships with explicit microbiome context
   - Metabolite production/consumption by gut bacteria
   - Probiotic/prebiotic therapeutic effects
5. **Statistical Associations:** Give LOWER confidence (0.6-0.7) for:
   - Correlations without clear mechanism
   - "Associated with" statements without causality
6. **Directionality:** Maintain correct direction (A→B vs B→A)

## OUTPUT FORMAT
For each valid relationship found, output ONE line:
SOURCE||TARGET||RELATIONSHIP||CONFIDENCE||EVIDENCE||MICROBIOME_RELEVANCE

Example output:
Faecalibacterium prausnitzii||butyrate||produces||0.95||F. prausnitzii is a major butyrate producer in the gut||1.0

If NO valid relationship exists, output:
NONE

Begin extraction:"""

        try:
            response = self.llm_client.call_llm(prompt, temperature=0.1)
            relationships = self._parse_enhanced_response(
                response,
                entity_a,
                entity_b,
                context,
                paper_id,
                norm_a,
                norm_b,
                avg_relevance
            )
            return relationships

        except Exception as e:
            logger.error(f"Error in LLM verification: {e}")
            return []

    def _parse_enhanced_response(
        self,
        response: str,
        entity_a: Dict,
        entity_b: Dict,
        source_context: str,
        paper_id: str,
        norm_a: str,
        norm_b: str,
        microbiome_relevance: float
    ) -> List[EntityRelationship]:
        """Parse LLM response with microbiome relevance support."""
        relationships = []
        lines = response.strip().split('\n')

        term_a = entity_a.get('term', '')
        term_b = entity_b.get('term', '')
        type_a = entity_a.get('categories', entity_a.get('entity_type', 'UNKNOWN')).upper()
        type_b = entity_b.get('categories', entity_b.get('entity_type', 'UNKNOWN')).upper()

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue

            if line.upper().startswith('NONE'):
                return []

            parts = line.split('||')
            if len(parts) < 5:
                continue

            source = parts[0].strip()
            target = parts[1].strip()
            rel_type = parts[2].strip().lower().replace(' ', '_')

            try:
                confidence = float(parts[3].strip())
            except ValueError:
                confidence = 0.5

            evidence = parts[4].strip() if len(parts) > 4 else ''

            # Adjust confidence based on microbiome relevance
            if microbiome_relevance > 0.7 and confidence < 0.9:
                confidence = min(confidence + 0.1, 1.0)
            elif microbiome_relevance < 0.3 and confidence > 0.7:
                confidence = max(confidence - 0.1, 0.5)

            # Validate entity matching
            if source.lower() not in [term_a.lower(), term_b.lower(), norm_a.lower(), norm_b.lower()]:
                continue
            if target.lower() not in [term_a.lower(), term_b.lower(), norm_a.lower(), norm_b.lower()]:
                continue

            # Determine direction
            if source.lower() in [term_a.lower(), norm_a.lower()]:
                source_ent, target_ent = entity_a, entity_b
                source_type, target_type = type_a, type_b
                source_name = norm_a if norm_a != term_a else term_a
                target_name = norm_b if norm_b != term_b else term_b
            else:
                source_ent, target_ent = entity_b, entity_a
                source_type, target_type = type_b, type_a
                source_name = norm_b if norm_b != term_b else term_b
                target_name = norm_a if norm_a != term_a else term_a

            if not self._is_valid_relationship(source_type, target_type, rel_type):
                continue

            relationship = EntityRelationship(
                source_entity=source_name,
                source_type=source_type,
                target_entity=target_name,
                target_type=target_type,
                relationship_type=rel_type,
                confidence=confidence,
                evidence=evidence[:500],
                source_context=source_context[:1000],
                paper_id=paper_id,
                umls_source_cui=source_ent.get('UMLS_ID', ''),
                umls_target_cui=target_ent.get('UMLS_ID', '')
            )

            if confidence >= self.min_confidence:
                relationships.append(relationship)

        return relationships

        # Fuzzy matching: entity normalization dictionary
        self.entity_normalization_map = {
            # Common variations
            'e.coli': 'escherichia coli',
            'e. coli': 'escherichia coli',
            'e coli': 'escherichia coli',
            'ecoli': 'escherichia coli',

            # Clinical terms normalization
            'high cu microbiomes': 'high carbohydrate unavailable microbiomes',
            'low cu microbiomes': 'low carbohydrate unavailable microbiomes',
            'cu microbiomes': 'carbohydrate unavailable microbiomes',
            'high uc': 'high ulcerative colitis',
            'low uc': 'low ulcerative colitis',

            # Organism name standardization
            'f. prausnitzii': 'faecalibacterium prausnitzii',
            'bifido': 'bifidobacterium',
            'lacto': 'lactobacillus',
            'strep': 'streptococcus',
            'staph': 'staphylococcus',
            'entero': 'enterobacteriaceae',

            # Disease/condition normalization
            'ibd': 'inflammatory bowel disease',
            'ibs': 'irritable bowel syndrome',
            'uc': 'ulcerative colitis',
            'cd': 'crohn disease',
            't2d': 'type 2 diabetes',
            't1d': 'type 1 diabetes',
            'c.diff': 'clostridioides difficile',
            'c. diff': 'clostridioides difficile',
        }

        # Invalid entity patterns (generic terms that shouldn't be entities)
        self.invalid_entity_patterns = [
            r'^high\s+\w+\s+microrob?iomes?$',
            r'^low\s+\w+\s+microrob?iomes?$',
            r'^\d+\s*(samples|subjects|patients)$',
            r'^figure\s+\d+[a-z]?$',
            r'^table\s+\d+[a-z]?$',
            r'^p\s*[<>=]+\s*0\.\d+$',
            r'^data\s+not\s+shown$',
        ]

    def extract_relationships_from_text(
        self,
        text: str,
        entities: List[Dict],
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """
        Extract relationships from text containing known entities.

        Args:
            text: Full text or chunk from paper
            entities: List of entities with 'term' and 'categories' fields
            paper_id: Optional paper identifier
        """
        logger.info(f"Extracting relationships from text with {len(entities)} entities")

        # Filter high-confidence entities
        high_conf_entities = [
            e for e in entities
            if e.get('confidence_score', e.get('confidence', 0)) >= self.min_confidence
            and len(e.get('term', '').strip()) >= 2
        ]

        if len(high_conf_entities) < 2:
            logger.warning("Not enough high-confidence entities for relationship extraction")
            return []

        # Group entities by type
        entities_by_type = defaultdict(list)
        entity_map = {}
        for entity in high_conf_entities:
            term = entity.get('term', '').strip()
            etype = entity.get('categories', entity.get('entity_type', 'UNKNOWN')).upper()
            entities_by_type[etype].append(term)
            entity_map[term] = entity

        # Find entity mentions in text with context
        entity_mentions = self._find_entity_mentions(text, high_conf_entities)

        # Build sentences/segments containing multiple entities
        segments = self._build_multi_entity_segments(text, entity_mentions)

        if not segments:
            logger.info("No segments with multiple entities found")
            return []

        logger.info(f"Found {len(segments)} segments with multiple entities")

        # Extract relationships from each segment using LLM
        relationships = []
        for segment in segments:
            segment_rels = self._extract_relationships_from_segment(
                segment, entity_map, paper_id
            )
            relationships.extend(segment_rels)

        logger.info(f"Extracted {len(relationships)} raw relationships")

        # Deduplicate and filter relationships
        unique_relationships = self._deduplicate_relationships(relationships)

        logger.info(f"After deduplication: {len(unique_relationships)} relationships")
        return unique_relationships

    def _find_entity_mentions(
        self,
        text: str,
        entities: List[Dict]
    ) -> Dict[str, List[Tuple[int, int, str]]]:
        """Find where entities are mentioned in text (start, end, term)."""
        mentions = defaultdict(list)
        text_lower = text.lower()

        for entity in entities:
            term = entity.get('term', '').strip()
            if not term:
                continue

            # Find exact matches
            start = 0
            while True:
                pos = text_lower.find(term.lower(), start)
                if pos == -1:
                    break

                # Check word boundaries
                before_ok = (pos == 0 or not text[pos-1].isalnum())
                after_ok = (pos + len(term) >= len(text) or not text[pos + len(term)].isalnum())

                if before_ok and after_ok:
                    mentions[term].append((pos, pos + len(term), term))

                start = pos + 1

        return dict(mentions)

    def _build_multi_entity_segments(
        self,
        text: str,
        entity_mentions: Dict[str, List[Tuple[int, int, str]]],
        window_size: int = 500
    ) -> List[Dict]:
        """Build text segments containing multiple entities."""
        segments = []

        # Get all mention positions
        all_mentions = []
        for term, positions in entity_mentions.items():
            for start, end, _ in positions:
                all_mentions.append((start, end, term))

        # Sort by position
        all_mentions.sort()

        # Build windows with multiple entities
        for i, (start, end, term1) in enumerate(all_mentions):
            nearby_entities = [(start, end, term1)]

            # Find nearby entities within window
            for j in range(i + 1, len(all_mentions)):
                s2, e2, term2 = all_mentions[j]
                if s2 - start > window_size:
                    break
                nearby_entities.append((s2, e2, term2))

            if len(nearby_entities) >= 2:
                # Get text segment
                seg_start = max(0, nearby_entities[0][0] - 50)
                seg_end = min(len(text), nearby_entities[-1][1] + 50)
                segment_text = text[seg_start:seg_end]

                segments.append({
                    'text': segment_text,
                    'entities': [term for _, _, term in nearby_entities],
                    'positions': nearby_entities,
                    'offset': seg_start
                })

        return segments

    def _extract_relationships_from_segment(
        self,
        segment: Dict,
        entity_map: Dict[str, Dict],
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """Use LLM to extract relationships from a text segment."""
        entities = segment['entities']
        text = segment['text']

        if len(entities) < 2:
            return []

        # Build entity info for prompt
        entity_info = []
        for term in entities[:10]:  # Limit to 10 entities
            if term in entity_map:
                e = entity_map[term]
                etype = e.get('categories', e.get('entity_type', 'UNKNOWN'))
                entity_info.append(f"- {term} ({etype})")

        entity_list_str = "\n".join(entity_info)

        # Build prompt
        prompt = f"""You are a biomedical relationship extraction expert. Analyze the following text and extract relationships between the entities.

TEXT SEGMENT:
\"\"\"
{text}
\"\""

ENTITIES IN SEGMENT:
{entity_list_str}

VALID RELATIONSHIP TYPES:
- causes: Entity A causes Entity B (e.g., bacteria causes disease)
- treats: Entity A treats Entity B (e.g., probiotic treats disease, drug treats disease)
- produces: Organism produces chemical (e.g., bacteria produces butyrate)
- consumes: Organism consumes chemical (e.g., bacteria consumes fiber)
- encodes: Gene encodes protein
- interacts_with: Physical interaction (e.g., protein-protein)
- inhibits: Entity A inhibits Entity B (e.g., drug inhibits protein)
- activates: Entity A activates Entity B
- binds_to: Physical binding interaction
- associated_with: General association/correlation
- regulates: Gene/protein regulates another
- measured_by: Entity measured by method/experiment (e.g., bacteria measured by ELISA)
- analyzed_by: Entity analyzed by method (e.g., metabolite analyzed by chromatography)
- derived_from: Entity derived from analysis (e.g., results derived from statistical model)
- correlates_with: Statistical correlation between entities

EXTRACT RELATIONSHIPS:
For each relationship found, output in this EXACT format:
SOURCE||TARGET||RELATIONSHIP||CONFIDENCE||EVIDENCE

Example:
Escherichia coli||diarrhea||causes||0.95||Enterotoxigenic E. coli causes traveler's diarrhea

Rules:
- Only extract relationships explicitly supported by the text
- CONFIDENCE: 0.0-1.0 based on how explicit the relationship is stated
- EVIDENCE: Brief quote from text supporting the relationship
- Focus on microbiome-relevant relationships
- OUTPUT ONE RELATIONSHIP PER LINE

Begin extraction:"""

        try:
            response = self.llm_client.call_llm(prompt, temperature=0.1)
            return self._parse_relationship_response(response, entity_map, segment, paper_id)
        except Exception as e:
            logger.error(f"Error extracting relationships: {e}")
            return []

    def _parse_relationship_response(
        self,
        response: str,
        entity_map: Dict[str, Dict],
        segment: Dict,
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """Parse LLM response into EntityRelationship objects."""
        relationships = []
        lines = response.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue

            parts = line.split('||')
            if len(parts) < 4:
                continue

            source = parts[0].strip()
            target = parts[1].strip()
            rel_type = parts[2].strip().lower().replace(' ', '_')
            try:
                confidence = float(parts[3].strip())
            except ValueError:
                confidence = 0.5

            evidence = parts[4].strip() if len(parts) > 4 else ''

            # Validate entities exist in our map
            if source not in entity_map or target not in entity_map:
                continue

            source_ent = entity_map[source]
            target_ent = entity_map[target]

            source_type = source_ent.get('categories', source_ent.get('entity_type', 'UNKNOWN')).upper()
            target_type = target_ent.get('categories', target_ent.get('entity_type', 'UNKNOWN')).upper()

            # Validate relationship type is compatible with entity types
            if not self._is_valid_relationship(source_type, target_type, rel_type):
                continue

            # Create relationship
            relationship = EntityRelationship(
                source_entity=source,
                source_type=source_type,
                target_entity=target,
                target_type=target_type,
                relationship_type=rel_type,
                confidence=confidence,
                evidence=evidence[:500],  # Limit evidence length
                source_context=segment['text'][:1000],
                paper_id=paper_id,
                umls_source_cui=source_ent.get('UMLS_ID', ''),
                umls_target_cui=target_ent.get('UMLS_ID', '')
            )

            if confidence >= self.min_confidence:
                relationships.append(relationship)

        return relationships

    def _is_valid_relationship(self, source_type: str, target_type: str, rel_type: str) -> bool:
        """Check if relationship type is valid for entity types."""
        key = (source_type, target_type)
        if key in self.VALID_TYPE_PAIRS:
            return rel_type in self.VALID_TYPE_PAIRS[key]
        return True  # Allow unknown type pairs with explicit relationships

    def _deduplicate_relationships(
        self,
        relationships: List[EntityRelationship]
    ) -> List[EntityRelationship]:
        """Remove duplicate relationships, keeping highest confidence."""
        seen = {}
        unique = []

        for rel in relationships:
            # Create key
            key = (
                rel.source_entity.lower(),
                rel.target_entity.lower(),
                rel.relationship_type
            )

            if key not in seen or seen[key].confidence < rel.confidence:
                seen[key] = rel

        return list(seen.values())

    def extract_relationships_from_entities_file(
        self,
        entities_file: str,
        text_files_dir: str = None,
        max_workers: int = 4
    ) -> List[EntityRelationship]:
        """
        Extract relationships from entities JSON file with optional text files.

        Args:
            entities_file: Path to JSON file with entities
            text_files_dir: Optional directory containing source text files
            max_workers: Parallel processing workers
        """
        logger.info(f"Loading entities from {entities_file}")

        with open(entities_file, 'r') as f:
            data = json.load(f)

        entities = data.get('results', [])
        if not entities:
            logger.error("No entities found in file")
            return []

        # Group entities by source file if available
        entities_by_file = defaultdict(list)
        for entity in entities:
            source_file = entity.get('files_found_in', entity.get('source_file', 'unknown'))
            if isinstance(source_file, list):
                source_file = source_file[0] if source_file else 'unknown'
            entities_by_file[source_file].append(entity)

        all_relationships = []

        # Process each file
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}

            for source_file, file_entities in entities_by_file.items():
                if text_files_dir:
                    # Try to load source text
                    import os
                    text_path = os.path.join(text_files_dir, source_file.replace('.txt', '.txt'))
                    if os.path.exists(text_path):
                        with open(text_path, 'r', encoding='utf-8') as tf:
                            text = tf.read()

                        future = executor.submit(
                            self.extract_relationships_from_text,
                            text, file_entities, source_file
                        )
                        futures[future] = source_file

            # Collect results
            for future in tqdm(as_completed(futures), total=len(futures), desc="Extracting relationships"):
                try:
                    relationships = future.result()
                    all_relationships.extend(relationships)
                except Exception as e:
                    logger.error(f"Error processing {futures[future]}: {e}")

        return all_relationships

    def generate_relationship_summary(self, relationships: List[EntityRelationship]) -> Dict:
        """Generate summary statistics for extracted relationships."""
        if not relationships:
            return {}

        rel_type_counts = Counter(r.relationship_type for r in relationships)
        source_type_counts = Counter(r.source_type for r in relationships)
        target_type_counts = Counter(r.target_type for r in relationships)

        # Top entity pairs
        pair_counts = Counter(
            (r.source_entity, r.target_entity)
            for r in relationships
        ).most_common(20)

        avg_confidence = sum(r.confidence for r in relationships) / len(relationships)

        return {
            'total_relationships': len(relationships),
            'unique_entity_pairs': len(set((r.source_entity, r.target_entity) for r in relationships)),
            'relationship_type_distribution': dict(rel_type_counts),
            'source_type_distribution': dict(source_type_counts),
            'target_type_distribution': dict(target_type_counts),
            'top_entity_pairs': [
                {'source': s, 'target': t, 'count': c}
                for (s, t), c in pair_counts
            ],
            'average_confidence': round(avg_confidence, 3)
        }

    def save_relationships(self, relationships: List[EntityRelationship], output_path: str):
        """Save relationships to JSON file."""
        rels_data = [asdict(r) for r in relationships]

        output = {
            'metadata': {
                'total_relationships': len(relationships),
                'extraction_method': 'LLM-based relationship extraction'
            },
            'relationships': rels_data
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(relationships)} relationships to {output_path}")

    def _extract_relationships_from_batch(
        self,
        entities: List[Dict],
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """
        OPTIMIZED: Extract relationships from multiple entity pairs in single LLM call.

        Batches up to 15 entity pairs that co-occur in shared contexts into one prompt.
        Much faster than individual calls per pair.

        Args:
            entities: List of entity dicts with 'term', 'categories', 'contextual_definition'
            paper_id: Optional paper identifier
        """
        if len(entities) < 2:
            return []

        relationships = []

        # Collect co-occurring entity pairs with their shared contexts
        entity_pairs = []
        max_pairs = 15  # Process at most 15 pairs per batch to keep prompt manageable
        max_entities = 15  # Only check first 15 entities

        for i, entity_a in enumerate(entities[:max_entities]):
            term_a = entity_a.get('term', '').strip()
            if not term_a:
                continue

            context_a = entity_a.get('contextual_definition', entity_a.get('definition', ''))[:800]
            if not context_a or len(context_a) < 50:
                continue

            # Find entities that co-occur with entity_a
            for entity_b in entities[i+1:max_entities]:
                term_b = entity_b.get('term', '').strip()
                if not term_b:
                    continue

                # Quick co-occurrence check (both must appear in context)
                if not self._entities_co_occur_in_context(term_a, term_b, context_a):
                    continue

                entity_pairs.append({
                    'entity_a': entity_a,
                    'entity_b': entity_b,
                    'context': context_a
                })

                if len(entity_pairs) >= max_pairs:
                    break

            if len(entity_pairs) >= max_pairs:
                break

        if not entity_pairs:
            logger.debug(f"No co-occurring entity pairs found for paper {paper_id}")
            return []

        logger.info(f"Processing {len(entity_pairs)} entity pairs for paper {paper_id}")

        # Batch extract all pairs in one LLM call
        try:
            relationships = self._batch_extract_relationships(entity_pairs, paper_id)
        except Exception as e:
            logger.error(f"Batch extraction failed for paper {paper_id}: {e}")
            return []

        return relationships

    def _batch_extract_relationships(
        self,
        entity_pairs: List[Dict],
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """
        Extract relationships from multiple entity pairs in a single LLM call.

        Args:
            entity_pairs: List of dicts with 'entity_a', 'entity_b', 'context'
            paper_id: Optional paper identifier
        """
        # Build batch prompt
        prompt_parts = ["Extract relationships between the following entity pairs based on the provided text.\n\n"]

        for idx, pair in enumerate(entity_pairs, 1):
            term_a = pair['entity_a'].get('term', '')
            type_a = pair['entity_a'].get('categories', 'UNKNOWN')
            term_b = pair['entity_b'].get('term', '')
            type_b = pair['entity_b'].get('categories', 'UNKNOWN')
            context = pair['context'][:600]

            prompt_parts.append(f"PAIR {idx}:\n")
            prompt_parts.append(f"Entity A: {term_a} ({type_a})\n")
            prompt_parts.append(f"Entity B: {term_b} ({type_b})\n")
            prompt_parts.append(f"Context: {context}\n\n")

        prompt_parts.append("""RELATIONSHIP TYPES:
- causes: A causes B (e.g., bacteria causes disease)
- treats: A treats B (e.g., probiotic treats disease)
- produces: A produces B (e.g., bacteria produces butyrate)
- consumes: A consumes B (e.g., bacteria consumes fiber)
- inhibits: A inhibits B (e.g., antibiotic inhibits bacteria)
- associated_with: A associated with B (e.g., bacteria associated with disease)

CRITICAL RULES:
1. Only extract if BOTH entities appear together in the context
2. Relationship must be explicitly stated or strongly implied
3. Confidence: 0.0-1.0 (explicit = 0.9+, implied = 0.7-0.8, weak = 0.6)
4. If NO relationship, output "NONE"

OUTPUT FORMAT (one line per valid relationship):
PAIR_NUM||SOURCE||TARGET||RELATIONSHIP||CONFIDENCE||EVIDENCE

Example:
1||E. coli||diarrhea||causes||0.95||Enterotoxigenic E. coli causes traveler's diarrhea

Begin extraction:""")

        prompt = "".join(prompt_parts)

        try:
            response = self.llm_client.call_llm(prompt, temperature=0.1, timeout=180)
            return self._parse_batch_response(response, entity_pairs, paper_id)
        except Exception as e:
            logger.error(f"Batch LLM call failed: {e}")
            return []

    def _parse_batch_response(
        self,
        response: str,
        entity_pairs: List[Dict],
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """Parse the batch LLM response and create EntityRelationship objects."""
        relationships = []
        lines = response.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.upper() == 'NONE':
                continue

            parts = line.split('||')
            if len(parts) < 6:
                continue

            try:
                pair_num = int(parts[0]) - 1  # Convert to 0-indexed
                if pair_num < 0 or pair_num >= len(entity_pairs):
                    continue

                pair = entity_pairs[pair_num]
                entity_a = pair['entity_a']
                entity_b = pair['entity_b']

                source = parts[1].strip()
                target = parts[2].strip()
                rel_type = parts[3].strip()
                confidence = float(parts[4])
                evidence = parts[5].strip()

                # Get entity types
                source_type = entity_a.get('categories', entity_a.get('entity_type', 'UNKNOWN'))
                target_type = entity_b.get('categories', entity_b.get('entity_type', 'UNKNOWN'))

                # Normalize entities
                norm_source = self.normalize_entity_name(source)
                norm_target = self.normalize_entity_name(target)

                rel = EntityRelationship(
                    source_entity=norm_source,
                    source_type=source_type,
                    target_entity=norm_target,
                    target_type=target_type,
                    relationship_type=rel_type,
                    confidence=confidence,
                    evidence=evidence,
                    source_context=pair.get('context', '')[:200],
                    paper_id=paper_id,
                    evidence_type='literature'
                )
                relationships.append(rel)

            except (ValueError, IndexError) as e:
                logger.debug(f"Failed to parse line: {line} - {e}")
                continue

        return relationships

    def _entities_co_occur_in_context(self, term_a: str, term_b: str, context: str) -> bool:
        """Check if both entity terms appear in the context text."""
        context_lower = context.lower()
        term_a_lower = term_a.lower()
        term_b_lower = term_b.lower()

        # Check word boundaries to avoid partial matches
        a_appears = False
        b_appears = False

        # Simple word boundary check
        import re
        pattern_a = r'\b' + re.escape(term_a_lower) + r'\b'
        pattern_b = r'\b' + re.escape(term_b_lower) + r'\b'

        a_appears = re.search(pattern_a, context_lower) is not None
        b_appears = re.search(pattern_b, context_lower) is not None

        return a_appears and b_appears

    def _extract_pairwise_relationship(
        self,
        entity_a: Dict,
        entity_b: Dict,
        source_context: str,
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """Extract relationship between a specific entity pair using their shared context."""
        term_a = entity_a.get('term', '')
        type_a = entity_a.get('categories', entity_a.get('entity_type', 'UNKNOWN'))
        term_b = entity_b.get('term', '')
        type_b = entity_b.get('categories', entity_b.get('entity_type', 'UNKNOWN'))

        # Build prompt for pairwise extraction
        prompt = f"""You are a biomedical relationship extraction expert. Analyze the following text and extract relationships between the two entities.

TEXT:
\"\"\"
{source_context}
\"\""

ENTITY A: {term_a} (Type: {type_a})
ENTITY B: {term_b} (Type: {type_b})

VALID RELATIONSHIP TYPES:
- causes: Entity A causes Entity B (e.g., bacteria causes disease)
- treats: Entity A treats Entity B (e.g., probiotic treats disease, drug treats disease)
- produces: Organism produces chemical (e.g., bacteria produces butyrate)
- consumes: Organism consumes chemical (e.g., bacteria consumes fiber)
- encodes: Gene encodes protein
- interacts_with: Physical interaction (e.g., protein-protein)
- inhibits: Entity A inhibits Entity B (e.g., drug inhibits protein)
- activates: Entity A activates Entity B
- binds_to: Physical binding interaction
- associated_with: General association/correlation
- regulates: Gene/protein regulates another
- measured_by: Entity measured by method/experiment (e.g., bacteria measured by ELISA)
- analyzed_by: Entity analyzed by method (e.g., metabolite analyzed by chromatography)
- derived_from: Entity derived from analysis (e.g., results derived from statistical model)
- correlates_with: Statistical correlation between entities

CRITICAL RULES:
- Only extract a relationship if BOTH entities are explicitly mentioned together in the text
- The relationship must be DIRECTLY stated or strongly implied in the text
- If the entities are mentioned in different sentences without clear connection, DO NOT extract
- CONFIDENCE: 0.0-1.0 based on how explicit the relationship is stated
- EVIDENCE: Brief quote or explanation from the text supporting the relationship

OUTPUT FORMAT:
SOURCE||TARGET||RELATIONSHIP||CONFIDENCE||EVIDENCE

Example:
Escherichia coli||diarrhea||causes||0.95||Enterotoxigenic E. coli causes traveler's diarrhea

If NO relationship is explicitly stated in the text, output:
NONE

Begin extraction:"""

        try:
            response = self.llm_client.call_llm(prompt, temperature=0.1)
            return self._parse_pairwise_response(
                response,
                entity_a,
                entity_b,
                source_context,
                paper_id
            )
        except Exception as e:
            logger.error(f"Error extracting pairwise relationship: {e}")
            return []

    def _parse_pairwise_response(
        self,
        response: str,
        entity_a: Dict,
        entity_b: Dict,
        source_context: str,
        paper_id: str = None
    ) -> List[EntityRelationship]:
        """Parse LLM response for pairwise relationship extraction."""
        relationships = []
        lines = response.strip().split('\n')

        term_a = entity_a.get('term', '')
        term_b = entity_b.get('term', '')
        type_a = entity_a.get('categories', entity_a.get('entity_type', 'UNKNOWN')).upper()
        type_b = entity_b.get('categories', entity_b.get('entity_type', 'UNKNOWN')).upper()

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue

            # Check for NONE response (no relationship found)
            if line.upper().startswith('NONE'):
                return []

            parts = line.split('||')
            if len(parts) < 4:
                continue

            source = parts[0].strip()
            target = parts[1].strip()
            rel_type = parts[2].strip().lower().replace(' ', '_')
            try:
                confidence = float(parts[3].strip())
            except ValueError:
                confidence = 0.5

            evidence = parts[4].strip() if len(parts) > 4 else ''

            # Validate the entities match (can be in either direction)
            if source.lower() != term_a.lower() and source.lower() != term_b.lower():
                continue
            if target.lower() != term_a.lower() and target.lower() != term_b.lower():
                continue

            # Determine direction and assign correct entity types
            if source.lower() == term_a.lower():
                source_ent, target_ent = entity_a, entity_b
                source_type, target_type = type_a, type_b
            else:
                source_ent, target_ent = entity_b, entity_a
                source_type, target_type = type_b, type_a

            # Validate relationship type is compatible
            if not self._is_valid_relationship(source_type, target_type, rel_type):
                continue

            # Create relationship with VERIFIED source context
            relationship = EntityRelationship(
                source_entity=source_ent.get('term', ''),
                source_type=source_type,
                target_entity=target_ent.get('term', ''),
                target_type=target_type,
                relationship_type=rel_type,
                confidence=confidence,
                evidence=evidence[:500],
                source_context=source_context[:1000],
                paper_id=paper_id,
                umls_source_cui=source_ent.get('UMLS_ID', ''),
                umls_target_cui=target_ent.get('UMLS_ID', '')
            )

            if confidence >= self.min_confidence:
                relationships.append(relationship)

        return relationships
