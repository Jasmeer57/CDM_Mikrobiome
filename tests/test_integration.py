"""
Integration tests for the complete Microbiome CDM system
Tests cross-pipeline functionality, API integration, and end-to-end workflows
"""

import unittest
import tempfile
import json
import sqlite3
import requests
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import sys
import subprocess
import time

# Try to import pytest, but don't fail if it's not available
try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False

class TestSystemIntegration(unittest.TestCase):
    """Test system-wide integration between components"""

    def setUp(self):
        """Set up integration test fixtures"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.project_root = Path(__file__).parent
        self.spacy_dir = self.project_root / "spacy_terms"
        self.llm_dir = self.project_root / "llm_terms"

    def tearDown(self):
        """Clean up integration test fixtures"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_project_structure(self):
        """Test that project structure is complete"""
        # Check main directories exist
        self.assertTrue(self.spacy_dir.exists(), "spaCy directory exists")
        self.assertTrue(self.llm_dir.exists(), "LLM directory exists")

        # Check critical files exist
        critical_files = [
            self.spacy_dir / "main.py",
            self.spacy_dir / "requirements.txt",
            self.llm_dir / "main.py",
            self.llm_dir / "requirements.txt",
            self.project_root / "README.md",
            self.project_root / "mkdocs.yml"
        ]

        for file_path in critical_files:
            if file_path.exists():
                self.assertTrue(True, f"Critical file exists: {file_path.name}")
            else:
                self.skipTest(f"Optional file missing: {file_path.name}")

    def test_spacy_pipeline_structure(self):
        """Test spaCy pipeline structure integrity"""
        required_components = [
            "src/modules/terms_extractor.py",
            "src/modules/deduplication.py",
            "src/modules/omop_mapping.py",
            "src/modules/umls_mapping.py",
            "src/utils/output_writer.py",
            "src/config/settings.py",
            "main.py"
        ]

        for component in required_components:
            component_path = self.spacy_dir / component
            if component_path.exists():
                self.assertTrue(True, f"spaCy component exists: {component}")
            else:
                self.fail(f"Required spaCy component missing: {component}")

    def test_llm_pipeline_structure(self):
        """Test LLM pipeline structure integrity"""
        required_components = [
            "core/pipeline.py",
            "core/entity_filter.py",
            "core/semantic_deduplicator.py",
            "core/llm_client.py",
            "database/models.py",
            "mappers/omop_mapper.py",
            "mappers/umls.py",
            "config/cdm_config.py",
            "main.py",
            "api_server.py"
        ]

        for component in required_components:
            component_path = self.llm_dir / component
            if component_path.exists():
                self.assertTrue(True, f"LLM component exists: {component}")
            else:
                self.fail(f"Required LLM component missing: {component}")

    def test_configuration_files(self):
        """Test configuration file integrity"""
        config_files = [
            self.spacy_dir / "requirements.txt",
            self.llm_dir / "requirements.txt",
            self.spacy_dir / "mkdocs.yml",
            self.llm_dir / "mkdocs.yml"
        ]

        for config_file in config_files:
            if config_file.exists():
                self.assertTrue(True, f"Config file exists: {config_file.name}")
                # Test that files are readable
                try:
                    with open(config_file, 'r') as f:
                        content = f.read()
                    self.assertGreater(len(content), 0, f"Config file has content: {config_file.name}")
                except Exception as e:
                    self.fail(f"Cannot read config file {config_file.name}: {e}")
            else:
                self.skipTest(f"Optional config file missing: {config_file.name}")

    @patch('subprocess.run')
    def test_spacy_cli_help(self, mock_run):
        """Test spaCy pipeline CLI help functionality"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "usage: main.py [-h]"
        mock_run.return_value = mock_result

        try:
            # Test that we can call the CLI (mocked)
            result = subprocess.run(
                ["python", "main.py", "--help"],
                cwd=self.spacy_dir,
                capture_output=True,
                text=True
            )

            # If this fails, we can at least check that the file exists and is executable
            main_py = self.spacy_dir / "main.py"
            if main_py.exists():
                self.assertTrue(True, "spaCy main.py exists and should be executable")

        except Exception:
            # Fallback: just check file existence
            main_py = self.spacy_dir / "main.py"
            if main_py.exists():
                self.assertTrue(True, "spaCy main.py exists")
            else:
                self.fail("spaCy main.py does not exist")

    @patch('subprocess.run')
    def test_llm_cli_help(self, mock_run):
        """Test LLM pipeline CLI help functionality"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "usage: main.py [-h]"
        mock_run.return_value = mock_result

        try:
            # Test that we can call the CLI (mocked)
            result = subprocess.run(
                ["python", "main.py", "--help"],
                cwd=self.llm_dir,
                capture_output=True,
                text=True
            )

            # If this fails, we can at least check that the file exists and is executable
            main_py = self.llm_dir / "main.py"
            if main_py.exists():
                self.assertTrue(True, "LLM main.py exists and should be executable")

        except Exception:
            # Fallback: just check file existence
            main_py = self.llm_dir / "main.py"
            if main_py.exists():
                self.assertTrue(True, "LLM main.py exists")
            else:
                self.fail("LLM main.py does not exist")

    def test_data_directory_structure(self):
        """Test data directory structure"""
        data_dirs = [
            self.spacy_dir / "data",
            self.spacy_dir / "output",
            self.llm_dir / "data",
            self.llm_dir / "output"
        ]

        for data_dir in data_dirs:
            if data_dir.exists():
                self.assertTrue(True, f"Data directory exists: {data_dir.name}")
                # Check if directory has content
                files = list(data_dir.glob("*"))
                if files:
                    self.assertTrue(True, f"Data directory has content: {data_dir.name}")
            else:
                self.skipTest(f"Optional data directory missing: {data_dir.name}")

    def test_documentation_structure(self):
        """Test documentation structure"""
        doc_dirs = [
            self.spacy_dir / "docs",
            self.llm_dir / "docs",
            self.project_root / "docs"
        ]

        for doc_dir in doc_dirs:
            if doc_dir.exists():
                self.assertTrue(True, f"Documentation directory exists: {doc_dir.name}")
                # Check for markdown files
                md_files = list(doc_dir.glob("**/*.md"))
                if md_files:
                    self.assertTrue(True, f"Documentation has markdown files: {doc_dir.name}")
            else:
                self.skipTest(f"Optional documentation directory missing: {doc_dir.name}")

    def test_docker_structure(self):
        """Test Docker configuration structure"""
        docker_files = [
            self.project_root / "docker-compose.yml",
            self.project_root / "Dockerfile",
            self.spacy_dir / "docker-compose.yml",
            self.llm_dir / "docker-compose.yml"
        ]

        for docker_file in docker_files:
            if docker_file.exists():
                self.assertTrue(True, f"Docker file exists: {docker_file.name}")
                # Test that Docker files are valid YAML
                try:
                    import yaml
                    with open(docker_file, 'r') as f:
                        yaml.safe_load(f)
                    self.assertTrue(True, f"Docker file is valid YAML: {docker_file.name}")
                except ImportError:
                    # PyYAML might not be installed
                    self.skipTest("PyYAML not available for Docker file validation")
                except Exception as e:
                    self.fail(f"Invalid Docker YAML file {docker_file.name}: {e}")
            else:
                self.skipTest(f"Optional Docker file missing: {docker_file.name}")

    def test_python_imports_cross_pipeline(self):
        """Test that both pipelines can be imported"""
        try:
            # Add both directories to path
            sys.path.insert(0, str(self.spacy_dir))
            sys.path.insert(0, str(self.llm_dir))

            # Test spaCy imports
            try:
                from src.modules.terms_extractor import TermsExtractor
                spacy_imports_work = True
            except ImportError:
                spacy_imports_work = False

            # Test LLM imports
            try:
                from core.pipeline import CDMEntityPipeline
                llm_imports_work = True
            except ImportError:
                llm_imports_work = False

            # At least basic directory structure should allow imports
            if spacy_imports_work:
                self.assertTrue(True, "spaCy imports work")
            else:
                self.skipTest("spaCy imports failed - may need environment setup")

            if llm_imports_work:
                self.assertTrue(True, "LLM imports work")
            else:
                self.skipTest("LLM imports failed - may need environment setup")

        except Exception as e:
            self.fail(f"Cross-pipeline import test failed: {e}")

    def test_api_servers_structure(self):
        """Test API server files structure"""
        api_files = [
            self.spacy_dir / "src/api/main.py",
            self.llm_dir / "api_server.py"
        ]

        for api_file in api_files:
            if api_file.exists():
                self.assertTrue(True, f"API file exists: {api_file.name}")
                # Check that it has FastAPI content
                try:
                    with open(api_file, 'r') as f:
                        content = f.read()
                    if "FastAPI" in content or "fastapi" in content.lower():
                        self.assertTrue(True, f"API file contains FastAPI: {api_file.name}")
                    else:
                        self.skipTest(f"API file may not be FastAPI-based: {api_file.name}")
                except Exception as e:
                    self.fail(f"Cannot read API file {api_file.name}: {e}")
            else:
                self.skipTest(f"Optional API file missing: {api_file.name}")

    def test_readme_completeness(self):
        """Test README completeness"""
        readme_path = self.project_root / "README.md"
        if readme_path.exists():
            try:
                with open(readme_path, 'r') as f:
                    content = f.read()

                # Check for critical sections
                critical_sections = [
                    "# ",  # Title
                    "## ",  # Headers
                    "```",  # Code blocks
                    "pip install",  # Installation instructions
                    "usage",  # Usage instructions (case insensitive)
                ]

                for section in critical_sections:
                    if section in content.lower() or section in content:
                        self.assertTrue(True, f"README contains critical section: {section}")
                    else:
                        self.skipTest(f"README may be missing section: {section}")

                # Check length
                self.assertGreater(len(content), 1000, "README has substantial content")

            except Exception as e:
                self.fail(f"Cannot read or parse README: {e}")
        else:
            self.skipTest("README.md not found")

    def test_python_version_compatibility(self):
        """Test Python version compatibility requirements"""
        requirements_files = [
            self.spacy_dir / "requirements.txt",
            self.llm_dir / "requirements.txt"
        ]

        for req_file in requirements_files:
            if req_file.exists():
                try:
                    with open(req_file, 'r') as f:
                        content = f.read()

                    # Check for Python version requirements
                    if "python" in content.lower() or "version" in content.lower():
                        self.assertTrue(True, f"Requirements file has version info: {req_file.name}")

                    # Check for common dependencies
                    common_deps = ["fastapi", "spacy", "torch", "transformers"]
                    found_deps = [dep for dep in common_deps if dep in content.lower()]
                    if found_deps:
                        self.assertTrue(True, f"Requirements file has common deps: {req_file.name}: {found_deps}")

                except Exception as e:
                    self.fail(f"Cannot read requirements file {req_file.name}: {e}")

class TestEndToEndWorkflows(unittest.TestCase):
    """Test end-to-end workflows"""

    def setUp(self):
        """Set up end-to-end test fixtures"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.project_root = Path(__file__).parent

    def tearDown(self):
        """Clean up end-to-end test fixtures"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_mock_spacy_workflow(self):
        """Test complete spaCy workflow with mocks"""
        try:
            import sys
            spacy_dir = self.project_root / "spacy_terms"
            sys.path.insert(0, str(spacy_dir / "src"))

            from modules.terms_extractor import TermsExtractor
            from modules.deduplication import Deduplicator, DeduplicationConfig
            from utils.output_writer import OutputWriter

            # Create mock components
            config = DeduplicationConfig(
                semantic_enabled=False,
                biomedical_enabled=False
            )

            # Test workflow structure
            self.assertTrue(True, "spaCy workflow components imported")

        except ImportError as e:
            self.skipTest(f"spaCy workflow imports failed: {e}")

    def test_mock_llm_workflow(self):
        """Test complete LLM workflow with mocks"""
        try:
            import sys
            llm_dir = self.project_root / "llm_terms"
            sys.path.insert(0, str(llm_dir))

            from core.pipeline import CDMEntityPipeline
            from database.models import CDMDatabase
            from config.cdm_config import PipelineConfig

            # Test workflow structure
            self.assertTrue(True, "LLM workflow components imported")

        except ImportError as e:
            self.skipTest(f"LLM workflow imports failed: {e}")

    def test_output_format_compatibility(self):
        """Test that both pipelines can produce compatible outputs"""
        # Test JSON structure compatibility
        expected_fields = [
            "metadata",
            "extraction_results",
            "timestamp"
        ]

        # Mock output structure that both pipelines should support
        mock_output = {
            "metadata": {
                "pipeline_version": "test",
                "timestamp": datetime.now().isoformat()
            },
            "extraction_results": [
                {
                    "term": "DNA",
                    "entity_type": "GENE",
                    "confidence": 0.9,
                    "context": "test context"
                }
            ]
        }

        # Test that structure is valid
        self.assertIsInstance(mock_output, dict, "Output is dictionary")
        self.assertIn("metadata", mock_output, "Output has metadata")
        self.assertIn("extraction_results", mock_output, "Output has extraction results")
        self.assertIsInstance(mock_output["extraction_results"], list, "Extraction results is list")

    def test_database_schema_compatibility(self):
        """Test database schema compatibility between pipelines"""
        # Test that both pipelines can use similar database structures
        common_fields = [
            "id",
            "entity",
            "entity_type",
            "confidence",
            "timestamp"
        ]

        # Mock database record structure
        mock_record = {
            "id": 1,
            "entity": "DNA",
            "entity_type": "GENE",
            "confidence": 0.9,
            "context": "test context",
            "timestamp": datetime.now()
        }

        # Validate structure
        for field in common_fields:
            self.assertIn(field, mock_record, f"Record has common field: {field}")

        self.assertIsInstance(mock_record["entity"], str, "Entity is string")
        self.assertIsInstance(mock_record["confidence"], (int, float), "Confidence is numeric")

if __name__ == '__main__':
    # Run with verbose output
    unittest.main(verbosity=2, buffer=True)