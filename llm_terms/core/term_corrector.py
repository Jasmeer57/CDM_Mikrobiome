import logging
import json
import numpy as np
from typing import List, Dict, Tuple
from collections import Counter, defaultdict
from sklearn.metrics.pairwise import cosine_similarity
from .llm_client import LLMClient
from config.cdm_config import CDMEntityConfig

logger = logging.getLogger(__name__)

class MiniLMTermCorrector:
    """Corrects terms using MiniLM semantic embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", similarity_threshold: float = 0.9):
        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.model = None
        
    def load_model(self) -> bool:
        try:
            if self.model is None:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name)
            return True
        except Exception as e:
            logger.error(f"Failed to load MiniLM for correction: {e}")
            return False

    def correct_terms(self, entities: List[Dict]) -> List[Dict]:
        """Correct terms by clustering similar entities and mapping to the most frequent canonical form."""
        if not entities or len(entities) < 2:
            return entities
            
        if not self.load_model():
            return entities

        logger.info(f"🔧 Starting MiniLM term correction for {len(entities)} entities")
        
        # Group by entity type to only correct within same type
        type_groups = defaultdict(list)
        for i, entity in enumerate(entities):
            type_groups[entity['entity_type']].append(i)

        corrected_count = 0
        
        for entity_type, indices in type_groups.items():
            if len(indices) < 2:
                continue
                
            # Get texts for this group
            texts = [entities[i]['entity'] for i in indices]
            
            # Encode
            try:
                embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
                
                # Calculate similarity matrix
                similarity_matrix = cosine_similarity(embeddings)
                
                # Find clusters/corrections
                term_counts = Counter(texts)
                processed_indices = set()
                
                for i in range(len(texts)):
                    if i in processed_indices:
                        continue
                        
                    # Find similar terms
                    similar_indices = np.where(similarity_matrix[i] > self.similarity_threshold)[0]
                    
                    if len(similar_indices) > 1:
                        # We have a cluster of similar terms
                        cluster_indices = similar_indices
                        cluster_texts = [texts[idx] for idx in cluster_indices]
                        
                        # Find canonical term (most frequent, then alphabetical)
                        canonical_term = max(cluster_texts, key=lambda t: (term_counts[t], t))
                        
                        # Apply correction
                        for idx in cluster_indices:
                            original_term = texts[idx]
                            if original_term != canonical_term:
                                entities[indices[idx]]['entity'] = canonical_term
                                entities[indices[idx]]['original_entity'] = original_term
                                entities[indices[idx]]['correction_method'] = 'MiniLM_Semantic'
                                corrected_count += 1
                                
                            processed_indices.add(idx)
                            
            except Exception as e:
                logger.error(f"Error correcting terms for type {entity_type}: {e}")
                continue

        logger.info(f"✅ MiniLM term correction: Corrected {corrected_count} terms")
        return entities
