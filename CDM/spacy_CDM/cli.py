#!/usr/bin/env python3
"""
Enhanced CLI interface for the Microbiome Term Extraction Pipeline.
Provides comprehensive command-line interface with advanced features.
"""

import argparse
import json
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.config.settings import PipelineConfig
from main import MicrobiomePipeline


class EnhancedCLI:
    """Enhanced CLI with advanced features and better user experience."""

    def __init__(self):
        self.logger = self._setup_logging()
        self.pipeline = None

    def _setup_logging(self, level: str = "INFO") -> logging.Logger:
        """Setup logging configuration."""
        logging.basicConfig(
            level=getattr(logging, level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('pipeline.log')
            ]
        )
        return logging.getLogger(__name__)

    def create_parser(self) -> argparse.ArgumentParser:
        """Create comprehensive argument parser."""
        parser = argparse.ArgumentParser(
            description="🚀 Microbiome Term Extraction Pipeline - Advanced CLI",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Basic usage
  python cli.py run --input-dir ./data --output-dir ./results

  # With semantic model selection
  python cli.py run --semantic-model nomic --fuzzy-threshold 85

  # Enable all optional modules
  python cli.py run --enable-umls --enable-ai --enable-omop

  # Configuration file
  python cli.py run --config config.yaml

  # Pipeline validation
  python cli.py validate --config config.yaml

  # Generate example config
  python cli.py init-config --output config.yaml

  # Pipeline status and info
  python cli.py status
            """
        )

        subparsers = parser.add_subparsers(dest='command', help='Available commands')

        # RUN command
        run_parser = subparsers.add_parser('run', help='Run the complete pipeline')
        self._add_run_arguments(run_parser)

        # VALIDATE command
        validate_parser = subparsers.add_parser('validate', help='Validate configuration')
        validate_parser.add_argument('--config', '-c', type=str, help='Configuration file path')
        validate_parser.add_argument('--check-models', action='store_true',
                                   help='Check if required models are available')

        # INIT-CONFIG command
        init_parser = subparsers.add_parser('init-config', help='Generate example configuration')
        init_parser.add_argument('--output', '-o', type=str, default='config.yaml',
                                help='Output configuration file path')
        init_parser.add_argument('--format', choices=['yaml', 'json'], default='yaml',
                                help='Configuration format')

        # STATUS command
        status_parser = subparsers.add_parser('status', help='Show pipeline status and information')
        status_parser.add_argument('--verbose', '-v', action='store_true',
                                  help='Show detailed information')

        # INFO command
        info_parser = subparsers.add_parser('info', help='Show detailed module information')
        info_parser.add_argument('--module', choices=['terms', 'dedup', 'umls', 'ai', 'omop'],
                                help='Show information for specific module')

        return parser

    def _add_run_arguments(self, parser: argparse.ArgumentParser):
        """Add arguments for the run command."""
        # Input/Output
        parser.add_argument('--input-dir', '-i', type=str, required=True,
                           help='Input directory containing documents')
        parser.add_argument('--output-dir', '-o', type=str, default='./output',
                           help='Output directory for results')
        parser.add_argument('--config', '-c', type=str, help='Configuration file')

        # Processing options
        parser.add_argument('--max-files', type=int, help='Maximum files to process')
        parser.add_argument('--batch-size', type=int, help='Batch size for processing')
        parser.add_argument('--n-process', type=int, help='Number of processes')

        # Filtering options
        parser.add_argument('--min-frequency', type=int, help='Minimum term frequency')
        parser.add_argument('--top-k', type=int, help='Maximum number of terms')

        # Semantic model selection
        parser.add_argument('--semantic-model',
                           choices=['mini-lm', 'nomic', 'mpnet'],
                           help='Semantic deduplication model')

        # Deduplication thresholds
        parser.add_argument('--fuzzy-threshold', type=float, help='Fuzzy deduplication threshold')
        parser.add_argument('--semantic-threshold', type=float,
                           help='Semantic deduplication threshold')

        # Optional modules
        parser.add_argument('--enable-umls', action='store_true', help='Enable UMLS mapping')
        parser.add_argument('--enable-ai', action='store_true', help='Enable AI cleaning')
        parser.add_argument('--enable-omop', action='store_true', help='Enable OMOP mapping')

        # Logging
        parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                           default='INFO', help='Log level')
        parser.add_argument('--log-file', type=str, help='Log file path')

        # Performance
        parser.add_argument('--gpu', action='store_true', help='Use GPU when available')
        parser.add_argument('--cache-models', action='store_true', default=True,
                           help='Cache models in memory')

        # Output format
        parser.add_argument('--output-format', choices=['json', 'csv', 'parquet', 'all'],
                           default='all', help='Output format(s)')

        # Dry run
        parser.add_argument('--dry-run', action='store_true',
                           help='Show what would be done without executing')

    def run_pipeline(self, args: argparse.Namespace) -> Dict[str, Any]:
        """Run the pipeline with given arguments."""
        try:
            # Load or create configuration
            if args.config:
                config = PipelineConfig.from_file(args.config)
            else:
                config = PipelineConfig.from_cli_args(args)

            # Override with CLI arguments
            if args.input_dir:
                config.input_dir = args.input_dir
            if args.output_dir:
                config.output_dir = args.output_dir
            if args.semantic_model:
                config.deduplication.semantic_model_choice = args.semantic_model
            if args.fuzzy_threshold:
                config.deduplication.fuzzy_threshold = args.fuzzy_threshold
            if args.semantic_threshold:
                config.deduplication.semantic_threshold = args.semantic_threshold
            if args.enable_umls:
                config.enable_umls_mapping = True
            if args.enable_ai:
                config.enable_ai_cleaning = True
            if args.enable_omop:
                config.enable_omop_mapping = True

            # Create pipeline
            self.pipeline = MicrobiomePipeline(config)

            if args.dry_run:
                self.logger.info("🔍 DRY RUN MODE - Showing configuration only")
                return self._show_dry_run_info(config)

            # Run pipeline
            self.logger.info("🚀 Starting Microbiome Term Extraction Pipeline")
            results = self.pipeline.run(args.input_dir, args.output_dir)

            return results

        except Exception as e:
            self.logger.error(f"❌ Pipeline failed: {e}")
            return {'error': str(e)}

    def validate_configuration(self, args: argparse.Namespace) -> Dict[str, Any]:
        """Validate pipeline configuration."""
        try:
            if args.config:
                config = PipelineConfig.from_file(args.config)
            else:
                config = PipelineConfig()

            validation_results = {
                'config_valid': True,
                'errors': [],
                'warnings': [],
                'checks': {}
            }

            # Check input directory
            if config.input_dir and not Path(config.input_dir).exists():
                validation_results['errors'].append(f"Input directory does not exist: {config.input_dir}")
                validation_results['config_valid'] = False

            # Check output directory
            if config.output_dir:
                try:
                    Path(config.output_dir).mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    validation_results['errors'].append(f"Cannot create output directory: {e}")
                    validation_results['config_valid'] = False

            # Check models if requested
            if args.check_models:
                model_checks = self._check_models(config)
                validation_results['checks']['models'] = model_checks

                if not model_checks['all_available']:
                    validation_results['warnings'].append("Some required models are not available")

            return validation_results

        except Exception as e:
            return {
                'config_valid': False,
                'errors': [f"Configuration validation failed: {e}"],
                'warnings': [],
                'checks': {}
            }

    def generate_config(self, args: argparse.Namespace) -> Dict[str, Any]:
        """Generate example configuration file."""
        try:
            config = PipelineConfig()

            output_path = Path(args.output)

            if args.format == 'yaml':
                content = config.to_yaml()
            else:
                content = config.to_json()

            output_path.write_text(content, encoding='utf-8')

            return {
                'success': True,
                'output_file': str(output_path),
                'format': args.format,
                'message': f"Configuration file generated: {output_path}"
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def show_status(self, args: argparse.Namespace) -> Dict[str, Any]:
        """Show pipeline status and information."""
        try:
            status = {
                'pipeline_version': '1.0.0',
                'python_version': sys.version,
                'working_directory': os.getcwd(),
                'modules': {
                    'terms_extractor': 'available',
                    'deduplication': 'available',
                    'umls_mapper': 'available',
                    'ai_cleaner': 'available',
                    'omop_processor': 'available'
                },
                'dependencies': self._check_dependencies(),
                'models': self._check_available_models()
            }

            if args.verbose:
                status['detailed_info'] = self._get_detailed_status()

            return status

        except Exception as e:
            return {'error': str(e)}

    def show_info(self, args: argparse.Namespace) -> Dict[str, Any]:
        """Show detailed module information."""
        info = {
            'available_modules': [
                {
                    'name': 'terms_extractor',
                    'description': 'SciSpaCy-based term extraction with multiple models',
                    'features': ['P1-P12 fixes', 'Multi-model processing', 'Semantic relevance scoring']
                },
                {
                    'name': 'deduplication',
                    'description': 'Multi-layer deduplication (exact, fuzzy, semantic)',
                    'features': ['Configurable thresholds', 'Multiple semantic models', 'Detailed reporting']
                },
                {
                    'name': 'umls_mapper',
                    'description': 'UMLS and ontology integration',
                    'features': ['SciSpaCy UMLS linking', 'BioPortal search', 'OLS integration', 'NCBO Annotator']
                },
                {
                    'name': 'ai_cleaner',
                    'description': 'AI-powered term cleaning and correction',
                    'features': ['Mistral-7B-Instruct integration', 'Context-aware correction', 'Batch processing']
                },
                {
                    'name': 'omop_processor',
                    'description': 'OMOP vocabulary preprocessing and mapping',
                    'features': ['Parquet conversion', 'Fuzzy matching', 'Domain filtering']
                }
            ]
        }

        if args.module:
            module_info = next((m for m in info['available_modules'] if m['name'] == args.module), None)
            if module_info:
                return {'selected_module': module_info}
            else:
                return {'error': f'Module {args.module} not found'}

        return info

    def _show_dry_run_info(self, config: PipelineConfig) -> Dict[str, Any]:
        """Show dry run information."""
        return {
            'dry_run': True,
            'configuration': config.to_dict(),
            'stages': [
                '1. Load documents from: ' + config.input_dir,
                '2. Extract terms using ' + str(len(config.scispacy.models)) + ' SciSpaCy models',
                '3. Apply multi-layer deduplication',
                '4. UMLS mapping' if config.enable_umls_mapping else '4. Skip UMLS mapping',
                '5. AI cleaning' if config.enable_ai_cleaning else '5. Skip AI cleaning',
                '6. OMOP mapping' if config.enable_omop_mapping else '6. Skip OMOP mapping',
                '7. Export results to: ' + config.output_dir
            ]
        }

    def _check_models(self, config: PipelineConfig) -> Dict[str, Any]:
        """Check model availability."""
        checks = {'scispacy_models': {}, 'semantic_model': {}, 'ai_model': {}}

        # Check SciSpaCy models
        for model_name in config.scispacy.models:
            try:
                import spacy
                spacy.load(model_name)
                checks['scispacy_models'][model_name] = True
            except OSError:
                checks['scispacy_models'][model_name] = False

        # Check semantic model
        try:
            from sentence_transformers import SentenceTransformer
            model_name = config.deduplication.semantic_models[config.deduplication.semantic_model_choice]
            SentenceTransformer(model_name)
            checks['semantic_model']['available'] = True
        except Exception:
            checks['semantic_model']['available'] = False

        # Check AI model
        if config.enable_ai_cleaning:
            try:
                from transformers import pipeline
                checks['ai_model']['available'] = True
            except Exception:
                checks['ai_model']['available'] = False

        checks['all_available'] = all([
            all(checks['scispacy_models'].values()),
            checks['semantic_model'].get('available', False),
            checks['ai_model'].get('available', True)  # AI is optional
        ])

        return checks

    def _check_dependencies(self) -> Dict[str, bool]:
        """Check if required dependencies are installed."""
        dependencies = {
            'spacy': False,
            'scispacy': False,
            'sentence_transformers': False,
            'transformers': False,
            'pandas': False,
            'numpy': False,
            'thefuzz': False,
            'requests': False,
            'pyyaml': False
        }

        for dep in dependencies:
            try:
                __import__(dep.replace('-', '_'))
                dependencies[dep] = True
            except ImportError:
                pass

        return dependencies

    def _check_available_models(self) -> Dict[str, Any]:
        """Check available models."""
        models = {
            'scispacy': [],
            'sentence_transformers': []
        }

        # Check SciSpaCy models
        scispacy_models = [
            'en_ner_craft_md', 'en_ner_bc5cdr_md',
            'en_core_sci_lg', 'en_ner_jnlpba_md'
        ]

        for model in scispacy_models:
            try:
                import spacy
                spacy.load(model)
                models['scispacy'].append(model)
            except OSError:
                pass

        # Check sentence transformers
        st_models = ['all-MiniLM-L12-v2', 'nomic-embed-text-v1', 'all-mpnet-base-v2']
        for model in st_models:
            try:
                from sentence_transformers import SentenceTransformer
                SentenceTransformer(model)
                models['sentence_transformers'].append(model)
            except Exception:
                pass

        return models

    def _get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed status information."""
        return {
            'system_info': {
                'platform': os.name,
                'cpu_count': os.cpu_count(),
                'memory_available': 'N/A'  # Could add psutil dependency
            },
            'configuration_examples': {
                'minimal': 'python cli.py run --input-dir ./data',
                'full': 'python cli.py run --input-dir ./data --enable-umls --enable-ai --enable-omop --semantic-model nomic',
                'config_file': 'python cli.py run --config config.yaml'
            }
        }

    def main(self):
        """Main CLI entry point."""
        parser = self.create_parser()
        args = parser.parse_args()

        if not args.command:
            parser.print_help()
            return

        # Setup logging level
        if hasattr(args, 'log_level'):
            self.logger = self._setup_logging(args.log_level)

        # Route to appropriate command
        if args.command == 'run':
            results = self.run_pipeline(args)
        elif args.command == 'validate':
            results = self.validate_configuration(args)
        elif args.command == 'init-config':
            results = self.generate_config(args)
        elif args.command == 'status':
            results = self.show_status(args)
        elif args.command == 'info':
            results = self.show_info(args)
        else:
            results = {'error': f'Unknown command: {args.command}'}

        # Output results
        if isinstance(results, dict) and 'error' in results:
            print(f"❌ Error: {results['error']}")
            sys.exit(1)
        else:
            print(json.dumps(results, indent=2, default=str))


if __name__ == '__main__':
    cli = EnhancedCLI()
    cli.main()