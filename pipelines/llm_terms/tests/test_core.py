import unittest
from unittest.mock import MagicMock, patch
import json
from core.entity_filter import EntityFilter
from extractors.entity_extractor import CDMEntityExtractor
from core.llm_client import LLMClient
from mappers.mapping import ComprehensiveMapper

class TestEntityFilter(unittest.TestCase):
    def setUp(self):
        self.filter = EntityFilter()

    def test_validate_entity_valid(self):
        # Using internal method for unit testing
        self.assertTrue(self.filter._is_valid_biomedical_entity('Lactobacillus acidophilus', 'ORGANISM'))

    def test_validate_entity_invalid_short(self):
        self.assertFalse(self.filter._is_valid_biomedical_entity('A', 'ORGANISM'))

    def test_validate_entity_blocklist(self):
        self.assertFalse(self.filter._is_valid_biomedical_entity('bacteria', 'ORGANISM'))

class TestCDMEntityExtractor(unittest.TestCase):
    def setUp(self):
        self.mock_llm_client = MagicMock(spec=LLMClient)
        self.extractor = CDMEntityExtractor(self.mock_llm_client)

    def test_parse_llm_response_pipe_format(self):
        response = "- Lactobacillus (ORGANISM): Bacteria found in gut | Definition: Bacteria found in gut | Aliases: L. acidophilus | Examples: Yogurt"
        entities = self.extractor.parse_llm_response(response, chunk_num=1)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]['entity'], 'Lactobacillus')
        self.assertEqual(entities[0]['entity_type'], 'ORGANISM')
        self.assertEqual(entities[0]['definition'], 'Bacteria found in gut')



class TestComprehensiveMapper(unittest.TestCase):
    @patch('mappers.mapping.OMOPLocalMapper')
    @patch('mappers.mapping.OMOPMapper')
    def setUp(self, MockOMOPMapper, MockOMOPLocalMapper):
        self.mapper = ComprehensiveMapper(use_local_omop=False)
        # Mock the mappers
        self.mapper.omop_mapper = MockOMOPMapper.return_value
        self.mapper.umls_mapper = MagicMock()
        self.mapper.bioportal_mapper = MagicMock()
        self.mapper.ols_mapper = MagicMock()

    def test_map_entity_comprehensive(self):
        # Setup mocks
        self.mapper.bioportal_mapper.search.return_value = [{'concept_id': 'BP1'}]
        
        # OLS mock
        mock_ols_result = MagicMock()
        mock_ols_result.to_dict.return_value = {'iri': 'OLS1'}
        self.mapper.ols_mapper.map_entity.return_value = [mock_ols_result]
        
        # UMLS mock
        self.mapper.umls_mapper.map_term.return_value = [MagicMock(to_dict=lambda: {'cui': 'C1'})]
        
        # OMOP mock
        mock_omop_result = MagicMock()
        # vars() works on objects with __dict__. MagicMock has __dict__.
        # But to control vars(mock), we might need to set attributes.
        mock_omop_result.concept_id = 123
        self.mapper.omop_mapper.map_entity_to_omop.return_value = [mock_omop_result]

        result = self.mapper.map_entity_comprehensive("Lactobacillus", "ORGANISM")
        
        self.assertTrue(result['has_any_mapping'])
        self.assertEqual(result['bioportal_mappings'][0]['concept_id'], 'BP1')
        self.assertEqual(result['omop_mappings'][0]['concept_id'], 123)

if __name__ == '__main__':
    unittest.main()
