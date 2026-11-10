"""
Semantic Deduplicator Module for CDM Pipeline
Uses Sentence Transformers for semantic similarity-based deduplication
"""

import logging
import numpy as np
from typing import List, Dict, Tuple, Optional
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None
from sklearn.metrics.pairwise import cosine_similarity

from config.cdm_config import CDMEntityConfig

logger = logging.getLogger(__name__)

from sklearn.feature_extraction.text import TfidfVectorizer

class TfidfSemanticModel:
    """Fallback semantic model using TF-IDF."""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words='english', analyzer='char_wb', ngram_range=(2, 4))
        self.is_fitted = False
        
    def encode(self, sentences: List[str], batch_size: int = 32, show_progress_bar: bool = False, convert_to_numpy: bool = True):
        """
        Encode sentences using TF-IDF. 
        """
        if not sentences:
            return np.array([])
            
        try:
            # Fit on the current batch for internal deduplication
            embeddings = self.vectorizer.fit_transform(sentences)
            self.is_fitted = True
            if convert_to_numpy:
                return embeddings.toarray()
            return embeddings
        except ValueError:
            return np.zeros((len(sentences), 1))


class SemanticDeduplicator:
    """Advanced semantic deduplication using Sentence Transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", similarity_threshold: float = 0.8):
        # Fix model name mapping for common model names
        self.model_name = self._get_valid_model_name(model_name)
        self.similarity_threshold = similarity_threshold
        self.model = None
        self.entity_config = CDMEntityConfig()

    def _get_valid_model_name(self, model_name: str) -> str:
        """Map common model names to valid HuggingFace model identifiers."""
        model_mapping = {
            "nomic-embed-text": "nomic-ai/nomic-embed-text-v1.5",
            "minilm": "sentence-transformers/all-MiniLM-L6-v2",
            "miniLM": "sentence-transformers/all-MiniLM-L6-v2",
            "mpnet": "sentence-transformers/all-mpnet-base-v2",
            "bert": "sentence-transformers/all-mpnet-base-v2"
        }
        return model_mapping.get(model_name.lower(), model_name)

    def load_model(self) -> bool:
        """Load the sentence transformer model."""
        try:
            logger.info(f"🔄 Loading sentence transformer model: {self.model_name}")
            # Add trust_remote_code=True for models that need it
            if 'nomic' in self.model_name.lower():
                self.model = SentenceTransformer(self.model_name, trust_remote_code=True)
            else:
                self.model = SentenceTransformer(self.model_name)
            logger.info(f"✅ Model loaded successfully")
            return True
        except ImportError:
            logger.warning("⚠️ sentence-transformers not installed. Using TF-IDF fallback.")
            self.model = TfidfSemanticModel()
            return True
        except Exception as e:
            logger.warning(f"⚠️ Failed to load sentence transformer model: {e}. Using TF-IDF fallback.")
            self.model = TfidfSemanticModel()
            return True


    def encode_entities(self, entities: List[Dict]) -> Optional[np.ndarray]:
        """Encode entities into semantic embeddings."""
        if not self.model:
            if not self.load_model():
                return None

        try:
            # Create text representations for encoding with nomic task prefixes
            entity_texts = []
            for entity in entities:
                # Combine entity name and context for better semantic representation
                # Add nomic task prefix for proper embedding
                text = f"search_document: {entity['entity']} {entity.get('context', '')} {entity['entity_type']}"
                entity_texts.append(text.strip())

            logger.info(f"🔄 Encoding {len(entity_texts)} entities with nomic task prefixes...")
            embeddings = self.model.encode(
                entity_texts,
                batch_size=32,
                show_progress_bar=False,
                convert_to_numpy=True
            )
            logger.info(f"✅ Encoded entities with shape: {embeddings.shape}")
            return embeddings

        except Exception as e:
            logger.error(f"❌ Failed to encode entities: {e}")
            return None

    def find_semantic_duplicates(self, entities: List[Dict], embeddings: np.ndarray) -> List[int]:
        """Find indices of semantically duplicate entities."""
        if len(entities) != len(embeddings):
            logger.error("Entities and embeddings length mismatch")
            return []

        duplicate_indices = []
        processed = set()

        try:
            # Calculate cosine similarity matrix
            similarity_matrix = cosine_similarity(embeddings)

            for i in range(len(entities)):
                if i in processed:
                    continue

                # Find similar entities (excluding self)
                similar_indices = np.where(similarity_matrix[i] > self.similarity_threshold)[0]
                similar_indices = [idx for idx in similar_indices if idx != i and idx not in processed]

                if similar_indices:
                    # Keep the entity with highest confidence
                    candidate_indices = [i] + similar_indices
                    confidences = [entities[idx]['confidence'] for idx in candidate_indices]
                    best_idx = candidate_indices[np.argmax(confidences)]

                    # Mark others as duplicates
                    for idx in candidate_indices:
                        if idx != best_idx:
                            duplicate_indices.append(idx)
                            processed.add(idx)

                    processed.add(best_idx)

            logger.info(f"🔄 Found {len(duplicate_indices)} semantic duplicates")
            return duplicate_indices

        except Exception as e:
            logger.error(f"❌ Error finding semantic duplicates: {e}")
            return []

    def apply_semantic_deduplication(self, entities: List[Dict]) -> List[Dict]:
        """Apply semantic deduplication to entities."""
        if not entities:
            return entities

        logger.info(f"🔄 Starting semantic deduplication for {len(entities)} entities")

        # Group entities by type for more efficient processing
        deduplicated = []
        total_duplicates = 0

        for entity_type in self.entity_config.ENTITY_TYPES:
            type_entities = [e for e in entities if e['entity_type'] == entity_type]

            if not type_entities:
                continue

            logger.info(f"🔄 Processing {len(type_entities)} {entity_type} entities")

            # Skip semantic deduplication for small groups
            if len(type_entities) <= 2:
                deduplicated.extend(type_entities)
                continue

            # Encode entities
            embeddings = self.encode_entities(type_entities)
            if embeddings is None:
                logger.warning(f"⚠️ Skipping semantic deduplication for {entity_type}")
                deduplicated.extend(type_entities)
                continue

            # Find duplicates
            duplicate_indices = self.find_semantic_duplicates(type_entities, embeddings)

            # Keep non-duplicate entities
            type_deduplicated = [
                entity for idx, entity in enumerate(type_entities)
                if idx not in duplicate_indices
            ]

            deduplicated.extend(type_deduplicated)
            total_duplicates += len(duplicate_indices)

            logger.info(f"✅ {entity_type}: {len(type_entities)} → {len(type_deduplicated)} (removed {len(duplicate_indices)})")

        logger.info(f"✅ Semantic deduplication complete: {len(entities)} → {len(deduplicated)} (removed {total_duplicates})")
        return deduplicated

    def calculate_entity_similarity(self, entity1: str, entity2: str) -> float:
        """Calculate semantic similarity between two entities."""
        if not self.model:
            if not self.load_model():
                return 0.0

        try:
            embeddings = self.model.encode([entity1, entity2])
            similarity = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
            return float(similarity)
        except Exception as e:
            logger.error(f"❌ Error calculating similarity: {e}")
            return 0.0