"""
Critical component tests for pipeline safety and reliability.
Tests core functionality with emphasis on medical safety and data integrity.
"""

import pytest
import unittest
import tempfile
import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.modules.terms_extractor import TermsExtractor, SAFE_SYNONYM_MAP, CLINICAL_SPECIFICITY_TERMS
from src.modules.deduplication import Deduplicator
from src.utils.health_check import HealthChecker, ModelValidator, DataValidator
from src.utils.audit_trail import AuditTrail, DecisionType, DecisionOutcome
from src.utils.resource_manager import ResourceManager, RateLimiter


class TestClinicalSafety(unittest.TestCase):
    """Test clinical safety and specificity preservation"""

    def setUp(self):
        """Set up test fixtures"""
        self.extractor = Mock(spec=TermsExtractor)
        self.extractor._normalize_term = TermsExtractor._normalize_term

    def test_clinical_specificity_preservation(self):
        """Test that clinical terms are never normalized"""
        clinical_terms = [
            "Crohn's disease",
            "Ulcerative colitis",
            "Inflammatory bowel disease",
            "Type 1 diabetes",
            "Multiple sclerosis",
            "Rheumatoid arthritis"
        ]

        for term in clinical_terms:
            with self.subTest(term=term):
                # Should return exactly the same term
                result = self.extractor._normalize_term(self.extractor, term, use_synonym_map=True)
                self.assertEqual(result, term, f"Clinical term '{term}' should not be normalized")

    def test_safe_synonym_mapping(self):
        """Test that only safe synonyms are applied"""
        safe_mappings = {
            "gut flora": "gut microbiota",
            "e. coli": "escherichia coli",
            "16s ribosomal rna": "16s rrna",
            "short chain fatty acids": "short-chain fatty acids"
        }

        for input_term, expected in safe_mappings.items():
            with self.subTest(term=input_term):
                result = self.extractor._normalize_term(self.extractor, input_term, use_synonym_map=True)
                self.assertEqual(result, expected, f"Safe synonym mapping failed for '{input_term}'")

    def test_dangerous_synonym_avoidance(self):
        """Test that dangerous synonym mappings are avoided"""
        dangerous_inputs = [
            "inflammatory bowel disease",  # Should NOT become "ibd"
            "crohn's disease",             # Should NOT become "ibd"
            "ulcerative colitis",          # Should NOT become "ibd"
        ]

        for term in dangerous_inputs:
            with self.subTest(term=term):
                result = self.extractor._normalize_term(self.extractor, term, use_synonym_map=True)
                self.assertNotEqual(result, "ibd", f"Dangerous normalization occurred for '{term}'")
                self.assertIn(term, result.lower() or result, f"Original term '{term}' lost in normalization")

    def test_abbreviation_expansion_safety(self):
        """Test that abbreviation expansion preserves safety"""
        from src.modules.terms_extractor import ABBREVIATION_EXPANSION

        # Test safe expansions
        self.assertEqual(ABBREVIATION_EXPANSION["scfa"], "short-chain fatty acid")
        self.assertEqual(ABBREVIATION_EXPANSION["gi"], "gastrointestinal")

        # Test that expanded terms don't conflict with clinical specificity
        for abbr, expanded in ABBREVIATION_EXPANSION.items():
            with self.subTest(abbr=abbr):
                if expanded in CLINICAL_SPECIFICITY_TERMS:
                    self.fail(f"Abbreviation expansion '{abbr}' -> '{expanded}' conflicts with clinical specificity")


class TestHealthCheckSystem(unittest.TestCase):
    """Test health check and validation system"""

    def setUp(self):
        """Set up test fixtures"""
        self.health_checker = HealthChecker()
        self.model_validator = ModelValidator()

    def test_system_metrics_collection(self):
        """Test system metrics collection"""
        # Mock psutil functions
        with patch('src.utils.health_check.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 45.5
            mock_psutil.virtual_memory.return_value = Mock(
                percent=60.0,
                available=8 * 1024**3  # 8GB
            )
            mock_psutil.disk_usage.return_value = Mock(percent=75.0)
            mock_psutil.pids.return_value = [1, 2, 3, 4, 5]
            mock_psutil.Process.return_value.memory_info.return_value.rss = 512 * 1024**2  # 512MB
            mock_psutil.Process.return_value.memory_percent.return_value = 2.5

            health = self.health_checker.check_system_health()

            self.assertIsNotNone(health)
            self.assertEqual(health.system_metrics["cpu_percent"], 45.5)
            self.assertEqual(health.system_metrics["memory_percent"], 60.0)
            self.assertEqual(health.system_metrics["disk_usage_percent"], 75.0)

    def test_spacy_model_validation(self):
        """Test spaCy model validation"""
        with patch('src.utils.health_check.spacy') as mock_spacy:
            # Mock successful model load
            mock_nlp = Mock()
            mock_nlp.pipe_names = ["ner", "sentencizer"]
            mock_nlp.vocab = Mock()
            mock_nlp.vocab.__len__ = Mock(return_value=50000)

            mock_doc = Mock()
            mock_doc.ents = []

            mock_nlp.return_value = mock_doc
            mock_spacy.load.return_value = mock_nlp

            status, message, metrics = self.model_validator.validate_spacy_model("en_core_sci_lg")

            self.assertEqual(status, "healthy")
            self.assertIn("fully functional", message.lower())
            self.assertIn("load_time_seconds", metrics)
            self.assertIn("vocab_size", metrics)

    def test_transformer_model_validation(self):
        """Test transformer model validation"""
        with patch('src.utils.health_check.SentenceTransformer') as mock_st, \
             patch('src.utils.health_check.torch') as mock_torch:

            # Mock successful transformer load
            mock_model = Mock()
            mock_model.device = "cpu"
            mock_model.encode.return_value = Mock(shape=(2, 384))  # 2 sentences, 384 dimensions

            mock_torch.no_grad = Mock()
            mock_torch.no_grad.return_value.__enter__ = Mock()
            mock_torch.no_grad.return_value.__exit__ = Mock()

            mock_st.return_value = mock_model

            status, message, metrics = self.model_validator.validate_transformer_model("all-MiniLM-L12-v2")

            self.assertEqual(status, "healthy")
            self.assertIn("fully functional", message.lower())
            self.assertIn("embedding_dim", metrics)
            self.assertEqual(metrics["embedding_dim"], 384)

    def test_data_validation(self):
        """Test data quality validation"""
        # Test valid data
        valid_terms = [
            {"term": "DNA", "models_used": ["model1"], "relevance_score": 0.8, "frequency": 5, "examples": ["DNA replication"]},
            {"term": "Protein", "models_used": ["model2"], "relevance_score": 0.9, "frequency": 3, "examples": ["Protein folding"]}
        ]

        status, message, metrics = DataValidator.validate_term_data(valid_terms)
        self.assertEqual(status, "healthy")
        self.assertEqual(metrics["total_terms"], 2)
        self.assertEqual(metrics["invalid_terms"], 0)

        # Test invalid data
        invalid_terms = [
            {"term": "", "models_used": ["model1"], "relevance_score": 0.1, "frequency": 1, "examples": []},  # Empty term
            {"models_used": ["model2"]},  # Missing required fields
            {"term": "Good Term", "models_used": ["model3"], "relevance_score": 0.0, "frequency": 0}  # Low quality
        ]

        status, message, metrics = DataValidator.validate_term_data(invalid_terms)
        self.assertNotEqual(status, "healthy")
        self.assertGreater(metrics["invalid_terms"], 0)

    def test_deduplication_validation(self):
        """Test deduplication quality validation"""
        # Test normal reduction
        status, message, metrics = DataValidator.validate_deduplication_quality(1000, 300, 0.7)
        self.assertEqual(status, "healthy")

        # Test excessive reduction (>95%)
        status, message, metrics = DataValidator.validate_deduplication_quality(1000, 20, 0.98)
        self.assertEqual(status, "unhealthy")
        self.assertIn("excessive", message.lower())

        # Test insufficient reduction (<10%)
        status, message, metrics = DataValidator.validate_deduplication_quality(1000, 950, 0.05)
        self.assertEqual(status, "degraded")
        self.assertIn("insufficient", message.lower())


class TestAuditTrail(unittest.TestCase):
    """Test audit trail system for regulatory compliance"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.audit_trail = AuditTrail(str(Path(self.temp_dir) / "test_audit.db"))

    def tearDown(self):
        """Clean up test fixtures"""
        self.audit_trail.finalize_session()
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_decision_recording(self):
        """Test decision recording and retrieval"""
        decision_id = self.audit_trail.record_decision(
            decision_type=DecisionType.AI_CORRECTION,
            term="test term",
            original_term="original term",
            outcome=DecisionOutcome.CORRECTED,
            reasoning="Test correction",
            confidence=0.85
        )

        self.assertIsNotNone(decision_id)

        # Retrieve decision history
        history = self.audit_trail.get_decision_history(term="test term")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].term, "test term")
        self.assertEqual(history[0].original_term, "original term")
        self.assertEqual(history[0].outcome, DecisionOutcome.CORRECTED)

    def test_term_provenance(self):
        """Test complete term provenance tracking"""
        # Record multiple decisions for the same term
        self.audit_trail.record_decision(
            decision_type=DecisionType.TERM_EXTRACTION,
            term="DNA",
            outcome=DecisionOutcome.KEPT,
            reasoning="Valid biological term"
        )

        self.audit_trail.record_decision(
            decision_type=DecisionType.AI_CORRECTION,
            term="DNA",
            original_term="DNA",
            outcome=DecisionOutcome.KEPT,
            reasoning="Term is correct",
            confidence=0.95
        )

        provenance = self.audit_trail.get_term_provenance("DNA")

        self.assertEqual(provenance["term"], "DNA")
        self.assertEqual(provenance["total_decisions"], 2)
        self.assertEqual(len(provenance["decision_timeline"]), 2)
        self.assertEqual(provenance["final_outcome"], "kept")

    def test_data_integrity_validation(self):
        """Test data integrity validation"""
        # Add some test decisions
        for i in range(5):
            self.audit_trail.record_decision(
                decision_type=DecisionType.TERM_EXTRACTION,
                term=f"term_{i}",
                outcome=DecisionOutcome.KEPT,
                confidence=0.8 + (i * 0.02)  # Varying confidence
            )

        # Validate integrity
        integrity_report = self.audit_trail.validate_data_integrity(self.audit_trail.session_id)

        self.assertIn("integrity_score", integrity_report)
        self.assertIn("issues_found", integrity_report)
        self.assertEqual(integrity_report["session_id"], self.audit_trail.session_id)
        self.assertGreaterEqual(integrity_report["integrity_score"], 0.0)
        self.assertLessEqual(integrity_report["integrity_score"], 1.0)


class TestResourceManager(unittest.TestCase):
    """Test resource management and memory optimization"""

    def setUp(self):
        """Set up test fixtures"""
        self.resource_manager = ResourceManager()

    def tearDown(self):
        """Clean up test fixtures"""
        self.resource_manager.cleanup_all()

    def test_rate_limiting(self):
        """Test rate limiting functionality"""
        rate_limiter = RateLimiter(max_calls=3, time_window=1.0)

        # Should allow initial calls
        self.assertTrue(rate_limiter.acquire())
        self.assertTrue(rate_limiter.acquire())
        self.assertTrue(rate_limiter.acquire())

        # Should block additional calls
        self.assertFalse(rate_limiter.acquire())

        # Check status
        status = rate_limiter.get_status()
        self.assertEqual(status["calls_in_window"], 3)
        self.assertEqual(status["available_slots"], 0)

    def test_model_pool_basic_functionality(self):
        """Test basic model pool functionality"""
        from src.utils.resource_manager import ModelPool

        pool = ModelPool(max_models=2)

        # Mock load function
        load_count = 0
        def mock_load(name):
            nonlocal load_count
            load_count += 1
            mock_model = Mock()
            mock_model.name = name
            return mock_model

        # First call should load model
        with pool.get_model("test_model", mock_load) as model:
            self.assertEqual(load_count, 1)
            self.assertEqual(model.name, "test_model")

        # Second call should reuse model
        with pool.get_model("test_model", mock_load) as model:
            self.assertEqual(load_count, 1)  # Should not increase
            self.assertEqual(model.name, "test_model")

        # New model should load second model
        with pool.get_model("test_model_2", mock_load) as model:
            self.assertEqual(load_count, 2)
            self.assertEqual(model.name, "test_model_2")

    def test_resource_stats_collection(self):
        """Test resource statistics collection"""
        with patch('src.utils.resource_manager.psutil') as mock_psutil:
            mock_process = Mock()
            mock_process.memory_info.return_value.rss = 1024 * 1024 * 1024  # 1GB
            mock_process.memory_percent.return_value = 25.5
            mock_process.cpu_percent.return_value = 45.2
            mock_process.open_files.return_value = [1, 2, 3, 4, 5]
            mock_process.num_threads.return_value = 8

            mock_psutil.Process.return_value = mock_process

            stats = self.resource_manager.get_current_stats()

            self.assertEqual(stats.memory_mb, 1024.0)
            self.assertEqual(stats.memory_percent, 25.5)
            self.assertEqual(stats.cpu_percent, 45.2)
            self.assertEqual(stats.open_files, 5)
            self.assertEqual(stats.threads, 8)

    def test_resource_summary(self):
        """Test resource summary generation"""
        # Mock some stats
        self.resource_manager.resource_stats = [
            Mock(memory_mb=1000, cpu_percent=50.0),
            Mock(memory_mb=1100, cpu_percent=55.0),
            Mock(memory_mb=1050, cpu_percent=52.0)
        ]

        summary = self.resource_manager.get_resource_summary()

        self.assertIn("current", summary)
        self.assertIn("averages", summary)
        self.assertEqual(summary["total_stats_collected"], 3)
        self.assertGreater(summary["averages"]["memory_mb"], 0)
        self.assertGreater(summary["averages"]["cpu_percent"], 0)


class TestDeduplicationSafety(unittest.TestCase):
    """Test deduplication safety and biomedical awareness"""

    def setUp(self):
        """Set up test fixtures"""
        from src.config.settings import DeduplicationConfig

        self.config = DeduplicationConfig(
            semantic_enabled=False,  # Disable for unit tests
            biomedical_enabled=False
        )
        self.deduplicator = Deduplicator(self.config)

    def test biomedical_deduplication_safety(self):
        """Test that biomedical deduplication preserves clinical meaning"""
        # Test terms that should NOT be merged (clinical specificity)
        clinically_distinct_terms = [
            "Crohn's disease",
            "Ulcerative colitis",
            "Type 1 diabetes",
            "Type 2 diabetes"
        ]

        # Create mock term data
        term_data = []
        for term in clinically_distinct_terms:
            term_data.append({
                'term': term,
                'frequency': 1,
                'relevance_score': 0.8
            })

        # Test that deduplication doesn't merge distinct clinical terms
        # (This is a simplified test - real biomedical deduplication would be more complex)
        result = self.deduplicator.deduplicate_terms(term_data)

        # Should preserve all distinct clinical terms
        self.assertEqual(len(result), len(clinically_distinct_terms))

        # All original terms should be present
        result_terms = [t['term'] for t in result]
        for original_term in clinically_distinct_terms:
            self.assertIn(original_term, result_terms)


if __name__ == '__main__':
    # Run tests with detailed output
    unittest.main(verbosity=2, buffer=True)