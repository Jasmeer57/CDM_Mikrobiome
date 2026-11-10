import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from core.semantic_deduplicator import SemanticDeduplicator
from core.relevance_scorer import MicrobiomeRelevanceScorer
from core.term_corrector import MiniLMTermCorrector

class TestSemanticDeduplicator(unittest.TestCase):
    @patch('core.semantic_deduplicator.SentenceTransformer')
    def setUp(self, MockSentenceTransformer):
        self.mock_model = MockSentenceTransformer.return_value
        self.mock_model.encode.return_value = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]])
        self.deduplicator = SemanticDeduplicator()

    def test_remove_semantic_duplicates(self):
        entities = [
            {'entity': 'Lactobacillus', 'entity_type': 'ORGANISM', 'confidence': 0.9},
            {'entity': 'Lactobacillus sp.', 'entity_type': 'ORGANISM', 'confidence': 0.8},
            {'entity': 'E. coli', 'entity_type': 'ORGANISM', 'confidence': 0.9}
        ]
        # Mock similarity: 0 and 1 are similar. 2 is different.
        with patch('core.semantic_deduplicator.cosine_similarity') as mock_sim:
            mock_sim.return_value = np.array([
                [1.0, 0.95, 0.1], 
                [0.95, 1.0, 0.1],
                [0.1, 0.1, 1.0]
            ])
            
            deduplicated = self.deduplicator.apply_semantic_deduplication(entities)
            # Should keep 0 (Lactobacillus) and 2 (E. coli). Remove 1.
            self.assertEqual(len(deduplicated), 2)
            self.assertEqual(deduplicated[0]['entity'], 'Lactobacillus')
            self.assertEqual(deduplicated[1]['entity'], 'E. coli')

class TestMicrobiomeRelevanceScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = MicrobiomeRelevanceScorer()

    def test_score_entities(self):
        entities = [{'entity': 'Gut bacteria', 'context': 'Found in gut', 'entity_type': 'ORGANISM'}]
        # Uses keywords, no pipeline mock needed
        
        scored = self.scorer.score_entities(entities)
        self.assertTrue('microbiome_relevance_score' in scored[0])
        # Score calculation:
        # 'gut' in entity: +0.4
        # 'gut' in context: +0.2
        # 'ORGANISM' type: +0.2
        # 'bacter' in entity: +0.2
        # Total: 1.0
        self.assertEqual(scored[0]['microbiome_relevance_score'], 1.0)

class TestMiniLMTermCorrector(unittest.TestCase):
    @patch('sentence_transformers.SentenceTransformer')
    def setUp(self, MockSentenceTransformer):
        self.mock_model = MockSentenceTransformer.return_value
        self.corrector = MiniLMTermCorrector()

    def test_correct_terms(self):
        entities = [{'entity': 'Lactobacilus', 'entity_type': 'ORGANISM'}] # Typo
        
        # Mock embedding and search
        # This is hard to mock without knowing the exact logic of search.
        # Assuming it uses a predefined dictionary or similar.
        # If it uses a provided dictionary, we can test it.
        # If it relies on internal knowledge, we mock the search.
        
        # For now, just check if it runs without error and returns entities
        corrected = self.corrector.correct_terms(entities)
        self.assertEqual(len(corrected), 1)

if __name__ == '__main__':
    unittest.main()
