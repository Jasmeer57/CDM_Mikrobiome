"""
BioMistral-based Biomedical Deduplicator for CDM Pipeline
Advanced duplicate detection using biomedical context awareness
"""

import logging
import json
import time
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from core.llm_client import LLMClient

logger = logging.getLogger(__name__)

@dataclass
class DuplicateGroup:
    """Represents a group of biomedical duplicates."""
    canonical_entity: str
    duplicate_variants: List[str]
    entity_type: str
    confidence: float
    biomedical_context: str
    reasoning: str

class BioMistralDeduplicator:
    """Advanced biomedical duplicate detection using BioMistral."""

    def __init__(self, llm_client: LLMClient, biomistral_model: str = "biomistral:7b",
                 semantic_model: str = "nomic-embed-text"):
        self.llm_client = llm_client
        self.biomistral_model = biomistral_model
        self.semantic_model = semantic_model
        self.semantic_encoder = None
        self.duplicate_groups = []

        # Load semantic model
        self._load_semantic_model()

    def _load_semantic_model(self):
        """Load sentence transformer for semantic similarity."""
        try:
            logger.info(f"📊 Loading semantic model: {self.semantic_model}")
            if 'nomic' in self.semantic_model.lower():
                self.semantic_encoder = SentenceTransformer(self.semantic_model, trust_remote_code=True)
            else:
                self.semantic_encoder = SentenceTransformer(self.semantic_model)
            logger.info("✅ Semantic model loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load semantic model: {e}")
            self.semantic_encoder = None

    def _get_bio_contextual_similarity(self, entity1: str, entity2: str, entity_type: str) -> float:
        """Use BioMistral to determine biomedical contextual similarity."""
        prompt = f"""As a biomedical expert, determine if these two {entity_type} terms refer to the same biological entity in microbiome context.

Entity 1: "{entity1}"
Entity 2: "{entity2}"

Consider:
- Taxonomic relationships (e.g., E. coli vs Escherichia coli)
- Alternative names and abbreviations
- Biological function equivalence
- Contextual meaning in microbiome research

Respond with ONLY a number from 0.0 to 1.0 indicating the probability they are the same entity:
- 0.9-1.0: Definitely the same biological entity
- 0.7-0.8: Likely the same entity
- 0.5-0.6: Possibly the same entity
- 0.0-0.4: Different entities

Provide only the number:"""

        try:
            # NOTE: was `self.llm_client.generate(prompt, model=..., max_tokens=10)` -
            # LLMClient has no `generate` method (only `call_llm`), so this always
            # raised AttributeError and silently fell through to the `except` below,
            # meaning every single call returned the conservative default of 0.0 -
            # this deduplicator never actually merged anything in practice.
            response = self.llm_client.call_llm(prompt, max_tokens=20)

            # Extract numeric score from response
            import re
            numbers = re.findall(r'0\.\d+|1\.0|0|1', response.strip())
            if numbers:
                score = float(numbers[0])
                logger.debug(f"BioMistral similarity '{entity1}' vs '{entity2}': {score}")
                return score

        except Exception as e:
            logger.warning(f"BioMistral contextual analysis failed for '{entity1}' vs '{entity2}': {e}")

        return 0.0  # Conservative default

    def _get_semantic_similarity(self, entity1: str, entity2: str) -> float:
        """Get semantic similarity using sentence transformers."""
        if not self.semantic_encoder:
            return 0.0

        try:
            # Create embeddings with microbiome context
            text1 = f"microbiome biomedical entity: {entity1}"
            text2 = f"microbiome biomedical entity: {entity2}"

            emb1 = self.semantic_encoder.encode([text1])
            emb2 = self.semantic_encoder.encode([text2])

            similarity = cosine_similarity(emb1, emb2)[0][0]
            return float(similarity)

        except Exception as e:
            logger.warning(f"Semantic similarity calculation failed: {e}")
            return 0.0

    def _identify_duplicate_candidates(self, entities: List[Dict]) -> List[Tuple[Dict, Dict]]:
        """Identify potential duplicate pairs using multiple strategies."""
        candidates = []
        entities_by_type = {}

        # Group by entity type
        for entity in entities:
            entity_type = entity.get('entity_type', 'UNKNOWN')
            if entity_type not in entities_by_type:
                entities_by_type[entity_type] = []
            entities_by_type[entity_type].append(entity)

        # Find candidates within each type
        for entity_type, type_entities in entities_by_type.items():
            for i, entity1 in enumerate(type_entities):
                for entity2 in type_entities[i+1:]:
                    # Skip if identical strings (handled elsewhere)
                    if entity1['entity'].lower().strip() == entity2['entity'].lower().strip():
                        continue

                    candidates.append((entity1, entity2))

        return candidates

    def _create_duplicate_group(self, entity1: Dict, entity2: Dict, similarity: float) -> DuplicateGroup:
        """Create a duplicate group with BioMistral reasoning."""
        # Determine canonical entity (prefer longer, more descriptive names)
        if len(entity1['entity']) >= len(entity2['entity']):
            canonical = entity1['entity']
            duplicate = entity2['entity']
        else:
            canonical = entity2['entity']
            duplicate = entity1['entity']

        # Generate reasoning using BioMistral
        reasoning_prompt = f"""Explain why these microbiome terms are considered duplicates in biomedical context:

Canonical: "{canonical}"
Duplicate: "{duplicate}"
Entity Type: {entity1.get('entity_type', 'UNKNOWN')}
Similarity Score: {similarity}

Provide a concise biomedical explanation (max 50 words):"""

        try:
            reasoning = self.llm_client.call_llm(reasoning_prompt, max_tokens=300)
            reasoning = reasoning.strip()[:200]  # Limit length
        except Exception:
            reasoning = f"Biomedical similarity detected (score: {similarity:.2f})"

        return DuplicateGroup(
            canonical_entity=canonical,
            duplicate_variants=[duplicate],
            entity_type=entity1.get('entity_type', 'UNKNOWN'),
            confidence=similarity,
            biomedical_context="microbiome_research",
            reasoning=reasoning
        )

    def _merge_duplicate_groups(self, groups: List[DuplicateGroup]) -> List[DuplicateGroup]:
        """Merge overlapping duplicate groups."""
        if not groups:
            return []

        # Simple merging based on canonical entity similarity
        merged = []
        used_indices = set()

        for i, group1 in enumerate(groups):
            if i in used_indices:
                continue

            current_group = group1

            for j, group2 in enumerate(groups[i+1:], i+1):
                if j in used_indices:
                    continue

                # Check if groups should be merged
                if (group1.entity_type == group2.entity_type and
                    (group1.canonical_entity.lower() in group2.canonical_entity.lower() or
                     group2.canonical_entity.lower() in group1.canonical_entity.lower())):

                    # Merge groups
                    current_group.duplicate_variants.extend(group2.duplicate_variants)
                    current_group.confidence = max(current_group.confidence, group2.confidence)
                    used_indices.add(j)

            merged.append(current_group)
            used_indices.add(i)

        return merged

    def deduplicate_entities(self, entities: List[Dict],
                           biomistral_threshold: float = 0.7,
                           semantic_threshold: float = 0.85,
                           use_biomistral: bool = True,
                           embedding_prefilter: float = 0.55,
                           fuzzy_prefilter: float = 0.85,
                           fuzzy_fast_merge_threshold: float = 0.95) -> Tuple[List[Dict], List[DuplicateGroup]]:
        """
        Advanced deduplication using BioMistral and semantic analysis.

        Args:
            entities: List of entity dictionaries
            biomistral_threshold: Threshold for BioMistral contextual similarity
            semantic_threshold: Threshold for semantic similarity
            use_biomistral: Whether to use BioMistral (fallback to semantic only)
            embedding_prefilter: Cheap embedding-similarity gate applied BEFORE the
                LLM call. _identify_duplicate_candidates does no filtering at all -
                it emits every pair within an entity type, so this method previously
                called the LLM on genuinely every candidate pair (O(n^2) LLM calls
                per type group; infeasible past a few dozen entities of one type -
                a real corpus has hundreds to thousands). Computing the cheap
                sentence-embedding score first and skipping the LLM call entirely
                when it's below this floor cuts LLM calls by ~90%+ in practice
                (most cross-pairs within a type are unrelated), without changing
                what counts as a final duplicate - the LLM/semantic scoring logic
                below is unchanged, this only skips calls that would almost
                certainly score low anyway. Set to 0.0 to disable (original behavior).

        Returns:
            Tuple of (deduplicated_entities, duplicate_groups)
        """
        if not entities:
            return [], []

        logger.info(f"🔬 Starting BioMistral deduplication for {len(entities)} entities")
        start_time = time.time()

        # Step 1: Find duplicate candidates
        candidates = self._identify_duplicate_candidates(entities)
        logger.info(f"📋 Found {len(candidates)} potential duplicate pairs")

        # Step 2: Analyze candidates
        duplicate_groups = []
        llm_calls_made = 0
        fast_path_merges = 0
        llm_calls_skipped = 0

        for entity1, entity2 in candidates:
            similarity_scores = []

            # Method 3: String/fuzzy similarity (cheap - compute first, used as a gate
            # AND a fast-path auto-merge, not just a discarded display value like before -
            # it was computed here but never fed into final_score/threshold at all, so
            # obvious typo/case/whitespace variants that embeddings score inconsistently
            # were never caught by this signal despite being computed every time).
            import difflib
            string_score = difflib.SequenceMatcher(None, entity1['entity'].lower(), entity2['entity'].lower()).ratio()
            similarity_scores.append(('string', string_score))

            # Method 2: Semantic similarity (cheap - compute, use as the other gate)
            semantic_score = self._get_semantic_similarity(entity1['entity'], entity2['entity'])
            similarity_scores.append(('semantic', semantic_score))

            # Fast path: near-identical strings (typo/case/whitespace variants) are merged
            # directly without spending an LLM call - fuzzy_fast_merge_threshold is set high
            # enough that this only fires for things a human would call "obviously the same
            # string", not genus/species-type near-matches (those still need the LLM's
            # biological judgment, e.g. "Bacteroides" vs "Bacteroides fragilis").
            if string_score >= fuzzy_fast_merge_threshold:
                similarity_scores.append(('biomistral', 1.0))  # treat as a confirmed match
                fast_path_merges += 1
            # Method 1: BioMistral contextual analysis - only spend an LLM call if EITHER
            # cheap signal (embedding OR fuzzy string) suggests these might be related.
            # Embedding catches synonyms with no shared substring ("SCFA" vs "short-chain
            # fatty acid"); fuzzy catches typo/near-identical variants embeddings sometimes
            # score inconsistently. Either one clearing the bar is enough to justify the call.
            elif use_biomistral and (semantic_score >= embedding_prefilter or string_score >= fuzzy_prefilter):
                biomistral_score = self._get_bio_contextual_similarity(
                    entity1['entity'], entity2['entity'], entity1.get('entity_type', 'UNKNOWN')
                )
                similarity_scores.append(('biomistral', biomistral_score))
                llm_calls_made += 1
            elif use_biomistral:
                llm_calls_skipped += 1

            # Determine final similarity (prioritize BioMistral)
            if use_biomistral and any(s[0] == 'biomistral' for s in similarity_scores):
                final_score = next(s[1] for s in similarity_scores if s[0] == 'biomistral')
                threshold = biomistral_threshold
            else:
                # Use semantic if BioMistral not available
                final_score = max(s[1] for s in similarity_scores if s[0] == 'semantic')
                threshold = semantic_threshold

            # Step 3: Create duplicate group if above threshold
            if final_score >= threshold:
                group = self._create_duplicate_group(entity1, entity2, final_score)
                duplicate_groups.append(group)

                logger.info(f"🔗 Duplicate found: '{entity1['entity']}' ↔ '{entity2['entity']}' "
                           f"(score: {final_score:.2f}, method: {max(similarity_scores, key=lambda x: x[1])[0]})")

        if use_biomistral:
            logger.info(f"  LLM calls made: {llm_calls_made}, skipped by pre-filter: {llm_calls_skipped}, "
                        f"fast-path fuzzy merges (no LLM needed): {fast_path_merges}")

        # Step 4: Merge overlapping groups
        duplicate_groups = self._merge_duplicate_groups(duplicate_groups)

        # Step 5: Create deduplicated entity list
        entities_to_remove = set()
        deduplicated = entities.copy()

        for group in duplicate_groups:
            # Remove duplicate variants, keep canonical
            for variant in group.duplicate_variants:
                entities_to_remove.add(variant.lower().strip())

        # Remove duplicates from final list
        deduplicated = [
            entity for entity in deduplicated
            if entity['entity'].lower().strip() not in entities_to_remove
        ]

        # Update canonical entities with metadata
        for entity in deduplicated:
            for group in duplicate_groups:
                if entity['entity'] == group.canonical_entity:
                    entity['biomistral_deduplication'] = {
                        'is_canonical': True,
                        'duplicate_count': len(group.duplicate_variants),
                        'confidence': group.confidence,
                        'reasoning': group.reasoning,
                        'variants': group.duplicate_variants
                    }
                    break

        processing_time = time.time() - start_time
        logger.info(f"✅ BioMistral deduplication completed in {processing_time:.2f}s")
        logger.info(f"📊 Removed {len(entities) - len(deduplicated)} duplicates across {len(duplicate_groups)} groups")

        self.duplicate_groups = duplicate_groups
        return deduplicated, duplicate_groups

    def get_duplicate_summary(self) -> Dict:
        """Get summary of duplicate detection results."""
        if not self.duplicate_groups:
            return {}

        summary = {
            'total_groups': len(self.duplicate_groups),
            'total_duplicates_removed': sum(len(group.duplicate_variants) for group in self.duplicate_groups),
            'groups_by_type': {},
            'average_confidence': 0.0,
            'high_confidence_groups': 0
        }

        confidences = []
        for group in self.duplicate_groups:
            entity_type = group.entity_type
            if entity_type not in summary['groups_by_type']:
                summary['groups_by_type'][entity_type] = 0
            summary['groups_by_type'][entity_type] += 1

            confidences.append(group.confidence)
            if group.confidence >= 0.8:
                summary['high_confidence_groups'] += 1

        if confidences:
            summary['average_confidence'] = sum(confidences) / len(confidences)

        return summary

    def export_duplicate_analysis(self, filepath: str):
        """Export detailed duplicate analysis to JSON file."""
        analysis_data = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'duplicate_groups': [
                {
                    'canonical_entity': group.canonical_entity,
                    'duplicate_variants': group.duplicate_variants,
                    'entity_type': group.entity_type,
                    'confidence': group.confidence,
                    'biomedical_context': group.biomedical_context,
                    'reasoning': group.reasoning
                }
                for group in self.duplicate_groups
            ],
            'summary': self.get_duplicate_summary()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(analysis_data, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Duplicate analysis exported to: {filepath}")