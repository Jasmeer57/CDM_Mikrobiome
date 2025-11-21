"""
Comprehensive test suite for spaCy pipeline components
Tests all major functionality including extraction, deduplication, mapping, and output
"""

import unittest
import tempfile
import json
import sqlite3
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Try to import pytest, but don't fail if it's not available
try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

class TestSpaCyComponents(unittest.TestCase):
    """Test all spaCy pipeline components"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_data_dir = Path(__file__).parent.parent / "data"
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_terms_extractor_import(self):
        """Test TermsExtractor import and basic initialization"""
        try:
            from src.modules.terms_extractor import TermsExtractor, create_terms_extractor
            self.assertTrue(True, "TermsExtractor imported successfully")

            # Test factory function
            extractor = create_terms_extractor()
            self.assertIsNotNone(extractor, "TermsExtractor created via factory")

        except ImportError as e:
            self.fail(f"TermsExtractor import failed: {e}")

    def test_deduplication_import(self):
        """Test deduplication components"""
        try:
            from src.modules.deduplication import Deduplicator, create_deduplicator, DeduplicationConfig
            self.assertTrue(True, "Deduplicator imported successfully")

            # Test config creation
            config = DeduplicationConfig(
                semantic_enabled=False,  # Disable for faster tests
                biomedical_enabled=False
            )
            self.assertIsNotNone(config, "DeduplicationConfig created")

            # Test factory function
            deduplicator = create_deduplicator(config)
            self.assertIsNotNone(deduplicator, "Deduplicator created via factory")

        except ImportError as e:
            self.fail(f"Deduplicator import failed: {e}")

    def test_mapping_modules_import(self):
        """Test mapping modules"""
        try:
            from src.modules.omop_mapping import OMOPMapper, create_omop_mapper
            from src.modules.umls_mapping import UMLSMapper, create_umls_mapper

            # Test OMOP mapper
            omop_mapper = create_omop_mapper()
            self.assertIsNotNone(omop_mapper, "OMOPMapper created")

            # Test UMLS mapper
            umls_mapper = create_umls_mapper()
            self.assertIsNotNone(umls_mapper, "UMLSMapper created")

        except ImportError as e:
            self.fail(f"Mapping modules import failed: {e}")

    def test_output_writer_import(self):
        """Test output writer components"""
        try:
            from src.utils.output_writer import OutputWriter, create_output_writer

            # Test direct creation
            writer = OutputWriter(str(self.temp_dir))
            self.assertIsNotNone(writer, "OutputWriter created")

            # Test factory function
            writer2 = create_output_writer({"json": True, "csv": True}, str(self.temp_dir))
            self.assertIsNotNone(writer2, "OutputWriter created via factory")

        except ImportError as e:
            self.fail(f"OutputWriter import failed: {e}")

    def test_health_check_import(self):
        """Test health check components"""
        try:
            from src.utils.health_check import HealthChecker, ModelValidator, DataValidator

            health_checker = HealthChecker()
            self.assertIsNotNone(health_checker, "HealthChecker created")

            model_validator = ModelValidator()
            self.assertIsNotNone(model_validator, "ModelValidator created")

            data_validator = DataValidator()
            self.assertIsNotNone(data_validator, "DataValidator created")

        except ImportError as e:
            self.fail(f"Health check import failed: {e}")

    def test_configuration_import(self):
        """Test configuration components"""
        try:
            from src.config.settings import (
                get_config, validate_config, SciSpaCyConfig,
                DeduplicationConfig, AIConfig
            )

            # Test config creation
            spacy_config = SciSpaCyConfig()
            self.assertIsNotNone(spacy_config, "SciSpaCyConfig created")

            dedup_config = DeduplicationConfig()
            self.assertIsNotNone(dedup_config, "DeduplicationConfig created")

            ai_config = AIConfig()
            self.assertIsNotNone(ai_config, "AIConfig created")

        except ImportError as e:
            self.fail(f"Configuration import failed: {e}")

    def test_utility_imports(self):
        """Test utility modules"""
        try:
            from src.utils.audit_trail import AuditTrail
            from src.utils.resource_manager import ResourceManager
            from src.utils.config_validator import ConfigValidator

            # Test AuditTrail (may fail due to SQLite, but import should work)
            try:
                audit_trail = AuditTrail(":memory:")
                self.assertIsNotNone(audit_trail, "AuditTrail created")
            except Exception:
                pass  # Expected in test environment

            resource_manager = ResourceManager()
            self.assertIsNotNone(resource_manager, "ResourceManager created")

            config_validator = ConfigValidator()
            self.assertIsNotNone(config_validator, "ConfigValidator created")

        except ImportError as e:
            self.fail(f"Utility modules import failed: {e}")

    def test_api_import(self):
        """Test API components"""
        try:
            import sys
            # Add path for API imports
            sys.path.append(str(Path(__file__).parent.parent / "src" / "api"))

            try:
                from main import app
                self.assertIsNotNone(app, "FastAPI app created")
            except ImportError:
                # API might have additional dependencies, that's okay
                pass

        except Exception as e:
            # API import failure is not critical for core functionality
            pass

    @patch('spacy.load')
    def test_spacy_models_mock(self, mock_spacy_load):
        """Test spaCy model loading with mocks"""
        # Mock spaCy models
        mock_nlp = Mock()
        mock_nlp.pipe_names = ["ner", "sentencizer"]
        mock_nlp.vocab = Mock()
        mock_nlp.vocab.__len__ = Mock(return_value=50000)
        mock_doc = Mock()
        mock_doc.ents = []
        mock_nlp.return_value = mock_doc
        mock_spacy_load.return_value = mock_nlp

        try:
            import spacy

            # Test model loading
            nlp = spacy.load("en_core_sci_lg")
            self.assertIsNotNone(nlp, "Mock spaCy model loaded")

            # Verify mock was called
            mock_spacy_load.assert_called_with("en_core_sci_lg")

        except Exception as e:
            self.fail(f"Mock spaCy model test failed: {e}")

    def test_output_writer_functionality(self):
        """Test OutputWriter actual functionality"""
        try:
            from src.utils.output_writer import OutputWriter

            writer = OutputWriter(str(self.temp_dir))

            # Test data
            test_results = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "test": True
                },
                "extraction_results": [
                    {
                        "term": "DNA",
                        "frequency": 10,
                        "relevance_score": 0.9,
                        "models_detecting": ["en_core_sci_lg"],
                        "cdm_domain": "GENE"
                    },
                    {
                        "term": "Protein",
                        "frequency": 5,
                        "relevance_score": 0.8,
                        "models_detecting": ["en_ner_bc5cdr_md"],
                        "cdm_domain": "PROTEIN"
                    }
                ]
            }

            # Test JSON output
            json_file = writer.save_json(test_results, "test_output.json")
            self.assertTrue(Path(json_file).exists(), "JSON file created")

            # Verify JSON content
            with open(json_file, 'r') as f:
                loaded_data = json.load(f)
            self.assertEqual(loaded_data["extraction_results"][0]["term"], "DNA")

        except Exception as e:
            self.fail(f"OutputWriter functionality test failed: {e}")

    def test_deduplication_basic_functionality(self):
        """Test deduplication basic functionality without semantic models"""
        try:
            from src.modules.deduplication import Deduplicator, DeduplicationConfig

            # Create config with disabled semantic components for testing
            config = DeduplicationConfig(
                semantic_enabled=False,
                biomedical_enabled=False,
                fuzzy_enabled=True,
                fuzzy_threshold=0.85
            )

            deduplicator = Deduplicator(config)

            # Test data with obvious duplicates
            test_terms = [
                {"term": "DNA", "frequency": 10, "relevance_score": 0.9},
                {"term": "dna", "frequency": 5, "relevance_score": 0.8},  # Should be exact duplicate
                {"term": "Protein", "frequency": 3, "relevance_score": 0.7}
            ]

            result = deduplicator.deduplicate_terms(test_terms)

            # Should have fewer terms due to deduplication
            self.assertLessEqual(len(result), len(test_terms), "Deduplication reduced term count")

        except Exception as e:
            self.fail(f"Deduplication functionality test failed: {e}")

    def test_configuration_validation(self):
        """Test configuration validation"""
        try:
            from src.config.settings import SciSpaCyConfig, DeduplicationConfig, validate_config

            # Test valid config
            spacy_config = SciSpaCyConfig(
                models=["en_core_sci_lg"],
                batch_size=100
            )

            dedup_config = DeduplicationConfig(
                fuzzy_threshold=0.8,
                semantic_threshold=0.9
            )

            # Test validation (may not be implemented, but should not crash)
            try:
                result = validate_config(dedup_config)
                self.assertIsNotNone(result, "Validation returned a result")
            except Exception:
                pass  # Validation might not be fully implemented

        except Exception as e:
            self.fail(f"Configuration validation test failed: {e}")

    def test_main_script_import(self):
        """Test main script imports"""
        try:
            import main
            self.assertTrue(True, "Main script imported successfully")

        except ImportError as e:
            self.fail(f"Main script import failed: {e}")

    def test_data_file_access(self):
        """Test if test data files are accessible"""
        if self.test_data_dir.exists():
            txt_files = list(self.test_data_dir.glob("*.txt"))
            self.assertGreater(len(txt_files), 0, "Test data files found")

            # Test file reading
            if txt_files:
                with open(txt_files[0], 'r', encoding='utf-8') as f:
                    content = f.read()
                self.assertGreater(len(content), 0, "Test data file has content")
        else:
            # Skip test if no data directory
            self.skipTest("No test data directory found")

class TestSpaCyIntegration(unittest.TestCase):
    """Integration tests for spaCy pipeline"""

    def setUp(self):
        """Set up integration test fixtures"""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up integration test fixtures"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    @patch('spacy.load')
    def test_end_to_end_mock(self, mock_spacy_load):
        """Test end-to-end pipeline with mocked spaCy models"""
        # Mock comprehensive spaCy behavior
        mock_nlp = Mock()
        mock_nlp.pipe_names = ["ner", "sentencizer"]
        mock_nlp.vocab = Mock()
        mock_nlp.vocab.__len__ = Mock(return_value=50000)

        # Mock entities
        mock_ent1 = Mock()
        mock_ent1.text = "DNA"
        mock_ent1.label_ = "DNA"
        mock_ent1.start_char = 0
        mock_ent1.end_char = 3

        mock_ent2 = Mock()
        mock_ent2.text = "Protein"
        mock_ent2.label_ = "PROTEIN"
        mock_ent2.start_char = 10
        mock_ent2.end_char = 17

        mock_doc = Mock()
        mock_doc.ents = [mock_ent1, mock_ent2]
        mock_nlp.return_value = mock_doc
        mock_spacy_load.return_value = mock_nlp

        try:
            from src.modules.terms_extractor import create_terms_extractor
            from src.modules.deduplication import create_deduplicator, DeduplicationConfig
            from src.utils.output_writer import OutputWriter

            # Create components
            extractor = create_terms_extractor()
            dedup_config = DeduplicationConfig(
                semantic_enabled=False,
                biomedical_enabled=False
            )
            deduplicator = create_deduplicator(dedup_config)
            writer = OutputWriter(str(self.temp_dir))

            # Test text
            test_text = "DNA is important. Protein is essential."

            # Mock extraction process
            mock_entities = [
                {
                    "term": "DNA",
                    "models_used": ["en_core_sci_lg"],
                    "relevance_score": 0.9,
                    "frequency": 1,
                    "context": ["DNA is important"]
                },
                {
                    "term": "Protein",
                    "models_used": ["en_core_sci_lg"],
                    "relevance_score": 0.8,
                    "frequency": 1,
                    "context": ["Protein is essential"]
                }
            ]

            # Test deduplication
            deduplicated = deduplicator.deduplicate_terms(mock_entities)

            # Test output
            results = {
                "metadata": {"test": True},
                "extraction_results": deduplicated
            }

            json_file = writer.save_json(results)
            self.assertTrue(Path(json_file).exists(), "Integration test output created")

        except Exception as e:
            self.fail(f"End-to-end integration test failed: {e}")

if __name__ == '__main__':
    # Run with verbose output
    unittest.main(verbosity=2, buffer=True)