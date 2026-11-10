import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
from core.pipeline import CDMEntityPipeline
from core.llm_client import LLMClient
from biomedical.biomistral_validator import BioMistralValidator

class TestLLMClient(unittest.TestCase):
    def setUp(self):
        self.client = LLMClient(model="qwen3.5:9b", base_url="http://localhost:11434")

    @patch('requests.post')
    def test_call_llm_ollama(self, mock_post):
        # Mock successful Ollama response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'response': 'Test response'}
        mock_post.return_value = mock_response

        response = self.client.call_llm("Test prompt")
        self.assertEqual(response, 'Test response')
        
        # Verify correct endpoint called
        # Note: Actual implementation uses default config values if not provided
        mock_post.assert_called_with(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen3.5:9b",
                "prompt": "Test prompt",
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0,
                    "top_p": 0.9,
                    "seed": 42,
                    "num_predict": 4000
                }
            },
            timeout=600
        )

class TestBioMistralValidator(unittest.TestCase):
    @patch('biomedical.biomistral_validator.AutoModelForCausalLM')
    @patch('biomedical.biomistral_validator.AutoTokenizer')
    def setUp(self, MockTokenizer, MockModel):
        self.validator = BioMistralValidator()
        self.validator.tokenizer = MockTokenizer.return_value
        self.validator.model = MockModel.return_value

    def test_validate_entity_list(self):
        entities = [{'entity': 'Valid Term', 'entity_type': 'DISEASE'}]
        
        # Mock generation to return "yes"
        self.validator.tokenizer.decode.return_value = "yes"
        self.validator.model.generate.return_value = [[1, 2, 3]]
        
        validated = self.validator.validate_entity_list(entities)
        self.assertTrue('biomistral_validation' in validated[0])
        self.assertTrue(validated[0].get('is_biomedically_valid') is not None)

class TestCDMEntityPipeline(unittest.TestCase):
    @patch('core.pipeline.CDMEntityExtractor')
    @patch('core.pipeline.EntityFilter')
    @patch('core.pipeline.LLMClient')
    def setUp(self, MockLLMClient, MockFilter, MockExtractor):
        self.pipeline = CDMEntityPipeline()
        self.pipeline.extractor = MockExtractor.return_value
        self.pipeline.filter = MockFilter.return_value

    def test_extract_entities(self):
        # Setup mocks
        # run_extraction_pass returns list of entities
        self.pipeline.extractor.run_extraction_pass.return_value = [{'entity': 'E1', 'entity_type': 'ORGANISM', 'confidence': 0.9}]
        # post_process_entities returns filtered entities
        self.pipeline.post_process_entities = MagicMock(return_value=[{'entity': 'E1', 'entity_type': 'ORGANISM', 'confidence': 0.9}])
        
        text = "Some text content"
        entities = self.pipeline.extract_entities(text)
        
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]['entity'], 'E1')

if __name__ == '__main__':
    unittest.main()
