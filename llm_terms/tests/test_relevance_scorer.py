import unittest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.relevance_scorer import MicrobiomeRelevanceScorer

class TestMicrobiomeRelevanceScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = MicrobiomeRelevanceScorer()

    def test_high_relevance_organism(self):
        entity = {
            'entity': 'Bacteroides fragilis',
            'entity_type': 'ORGANISM',
            'context': 'Bacteroides fragilis is a common gut bacterium.'
        }
        score = self.scorer.calculate_score(entity)
        self.assertGreater(score, 0.5)

    def test_low_relevance_generic(self):
        entity = {
            'entity': 'cell',
            'entity_type': 'CELL_TYPE',
            'context': 'The cell is the basic unit of life.'
        }
        score = self.scorer.calculate_score(entity)
        self.assertLess(score, 0.5)

    def test_scfa_relevance(self):
        entity = {
            'entity': 'butyrate',
            'entity_type': 'CHEMICAL',
            'context': 'Butyrate is a short-chain fatty acid.'
        }
        score = self.scorer.calculate_score(entity)
        self.assertGreater(score, 0.6)

    def test_score_entities_list(self):
        entities = [
            {'entity': 'Bacteroides', 'entity_type': 'ORGANISM'},
            {'entity': 'unknown', 'entity_type': 'UNKNOWN'}
        ]
        scored = self.scorer.score_entities(entities)
        self.assertEqual(len(scored), 2)
        self.assertIn('microbiome_relevance_score', scored[0])
        self.assertIn('microbiome_relevance_score', scored[1])
        self.assertGreater(scored[0]['microbiome_relevance_score'], scored[1]['microbiome_relevance_score'])

if __name__ == '__main__':
    unittest.main()
