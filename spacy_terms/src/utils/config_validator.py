"""
Configuration validation and error recovery system.
Ensures pipeline configuration is valid and provides recovery mechanisms.
"""

import logging
import json
import os
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """Validation severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationResult:
    """Result of configuration validation"""
    is_valid: bool
    level: ValidationLevel
    message: str
    field: str = ""
    suggested_fix: str = ""
    auto_fixable: bool = False


@dataclass
class ConfigSchema:
    """Schema definition for configuration validation"""
    required_fields: List[str] = field(default_factory=list)
    field_types: Dict[str, type] = field(default_factory=dict)
    field_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    field_options: Dict[str, List[Any]] = field(default_factory=dict)
    custom_validators: Dict[str, List[str]] = field(default_factory=dict)


class ConfigValidator:
    """Comprehensive configuration validator"""

    def __init__(self):
        self.schemas = {}
        self._register_default_schemas()

    def _register_default_schemas(self):
        """Register default configuration schemas"""

        # Pipeline configuration schema
        self.schemas['pipeline'] = ConfigSchema(
            required_fields=['input_dir', 'output_dir', 'top_k'],
            field_types={
                'input_dir': str,
                'output_dir': str,
                'top_k': int,
                'max_files': int,
                'min_frequency': int,
                'semantic_threshold': float,
                'fuzzy_threshold': float
            },
            field_ranges={
                'top_k': (1, 100000),
                'max_files': (1, 10000),
                'min_frequency': (1, 1000),
                'semantic_threshold': (0.0, 1.0),
                'fuzzy_threshold': (0.0, 1.0)
            },
            custom_validators={
                'input_dir': ['check_directory_exists'],
                'output_dir': ['check_directory_writable']
            }
        )

        # SciSpaCy configuration schema
        self.schemas['scispacy'] = ConfigSchema(
            required_fields=['models'],
            field_types={
                'models': list,
                'disabled_components': list,
                'batch_size': int
            },
            field_ranges={
                'batch_size': (1, 10000)
            },
            field_options={
                'disabled_components': [['parser'], ['parser', 'tagger'], []]
            },
            custom_validators={
                'models': ['validate_scispacy_models']
            }
        )

        # AI correction configuration schema
        self.schemas['ai_correction'] = ConfigSchema(
            field_types={
                'enabled': bool,
                'model_name': str,
                'api_key': str,
                'temperature': float,
                'max_tokens': int,
                'batch_size': int
            },
            field_ranges={
                'temperature': (0.0, 2.0),
                'max_tokens': (1, 4096),
                'batch_size': (1, 100)
            },
            custom_validators={
                'model_name': ['validate_ai_model'],
                'api_key': ['validate_api_key_if_enabled']
            }
        )

        # UMLS configuration schema
        self.schemas['umls'] = ConfigSchema(
            field_types={
                'enabled': bool,
                'api_key': str,
                'timeout': int,
                'retry_attempts': int,
                'batch_size': int,
                'sources': list
            },
            field_ranges={
                'timeout': (1, 300),
                'retry_attempts': (0, 10),
                'batch_size': (1, 1000)
            },
            field_options={
                'sources': [['SNOMEDCT_US', 'MSH', 'CUI'], ['SNOMEDCT_US']]
            },
            custom_validators={
                'api_key': ['validate_api_key_if_enabled']
            }
        )

        # Deduplication configuration schema
        self.schemas['deduplication'] = ConfigSchema(
            field_types={
                'exact_enabled': bool,
                'fuzzy_enabled': bool,
                'semantic_enabled': bool,
                'fuzzy_threshold': float,
                'semantic_threshold': float,
                'semantic_models': dict,
                'biomedical_enabled': bool,
                'biomedical_confidence_threshold': float
            },
            field_ranges={
                'fuzzy_threshold': (0.0, 1.0),
                'semantic_threshold': (0.0, 1.0),
                'biomedical_confidence_threshold': (0.0, 1.0)
            },
            field_options={
                'semantic_models': [
                    ['mini-lm', 'nomic', 'mpnet'],
                    {'mini-lm': 'sentence-transformers/all-MiniLM-L12-v2'}
                ]
            },
            custom_validators={
                'semantic_models': ['validate_semantic_model_dict']
            }
        )

    def validate_config(self, config: Dict[str, Any], schema_name: str) -> List[ValidationResult]:
        """Validate configuration against schema"""
        if schema_name not in self.schemas:
            return [ValidationResult(
                is_valid=False,
                level=ValidationLevel.ERROR,
                message=f"Unknown schema: {schema_name}"
            )]

        schema = self.schemas[schema_name]
        results = []

        # Check required fields
        for field in schema.required_fields:
            if field not in config:
                results.append(ValidationResult(
                    is_valid=False,
                    level=ValidationLevel.CRITICAL,
                    message=f"Required field missing: {field}",
                    field=field,
                    suggested_fix=f"Add '{field}' to configuration"
                ))

        # Validate field types
        for field, expected_type in schema.field_types.items():
            if field in config and config[field] is not None:
                if not isinstance(config[field], expected_type):
                    results.append(ValidationResult(
                        is_valid=False,
                        level=ValidationLevel.ERROR,
                        message=f"Field {field} has wrong type: expected {expected_type.__name__}, got {type(config[field]).__name__}",
                        field=field,
                        suggested_fix=f"Convert {field} to {expected_type.__name__}"
                    ))

        # Validate field ranges
        for field, (min_val, max_val) in schema.field_ranges.items():
            if field in config and isinstance(config[field], (int, float)):
                value = config[field]
                if value < min_val or value > max_val:
                    results.append(ValidationResult(
                        is_valid=False,
                        level=ValidationLevel.WARNING,
                        message=f"Field {field} value {value} outside range [{min_val}, {max_val}]",
                        field=field,
                        suggested_fix=f"Set {field} to value between {min_val} and {max_val}",
                        auto_fixable=True
                    ))

        # Validate field options
        for field, valid_options in schema.field_options.items():
            if field in config:
                value = config[field]
                if value not in valid_options:
                    # For lists, check if any option is valid
                    if isinstance(value, list):
                        if not any(option in value for option in valid_options):
                            results.append(ValidationResult(
                                is_valid=False,
                                level=ValidationLevel.WARNING,
                                message=f"Field {field} has invalid options: {value}",
                                field=field,
                                suggested_fix=f"Choose from: {valid_options}"
                            ))
                    else:
                        results.append(ValidationResult(
                            is_valid=False,
                            level=ValidationLevel.ERROR,
                            message=f"Field {field} has invalid value: {value}",
                            field=field,
                            suggested_fix=f"Choose from: {valid_options}"
                        ))

        # Run custom validators
        for field, validators in schema.custom_validators.items():
            if field in config:
                for validator_name in validators:
                    try:
                        validator_method = getattr(self, f'_{validator_name}')
                        validation_results = validator_method(config[field], field, config)
                        results.extend(validation_results)
                    except AttributeError:
                        results.append(ValidationResult(
                            is_valid=False,
                            level=ValidationLevel.WARNING,
                            message=f"Unknown validator: {validator_name}",
                            field=field
                        ))

        return results

    def validate_full_config(self, config: Dict[str, Any]) -> List[ValidationResult]:
        """Validate full pipeline configuration"""
        all_results = []

        # Validate each config section
        for schema_name in self.schemas.keys():
            if schema_name in config:
                results = self.validate_config(config[schema_name], schema_name)
                all_results.extend(results)

        # Cross-section validation
        all_results.extend(self._validate_cross_dependencies(config))

        return all_results

    def _validate_cross_dependencies(self, config: Dict[str, Any]) -> List[ValidationResult]:
        """Validate dependencies between config sections"""
        results = []

        # Check AI correction dependencies
        ai_config = config.get('ai_correction', {})
        if ai_config.get('enabled', False):
            if not ai_config.get('model_name'):
                results.append(ValidationResult(
                    is_valid=False,
                    level=ValidationLevel.ERROR,
                    message="AI correction enabled but no model specified",
                    suggested_fix="Set ai_correction.model_name"
                ))

        # Check UMLS dependencies
        umls_config = config.get('umls', {})
        if umls_config.get('enabled', False):
            if not umls_config.get('api_key'):
                results.append(ValidationResult(
                    is_valid=False,
                    level=ValidationLevel.WARNING,
                    message="UMLS mapping enabled but no API key provided",
                    suggested_fix="Set UMLS_API_KEY environment variable or umls.api_key",
                    auto_fixable=False
                ))

        # Check deduplication dependencies
        dedup_config = config.get('deduplication', {})
        if dedup_config.get('semantic_enabled', False):
            semantic_models = dedup_config.get('semantic_models', {})
            default_model = dedup_config.get('default_semantic_model', 'mini-lm')
            if default_model not in semantic_models:
                results.append(ValidationResult(
                    is_valid=False,
                    level=ValidationLevel.ERROR,
                    message=f"Default semantic model '{default_model}' not found in semantic_models",
                    suggested_fix=f"Add '{default_model}' to deduplication.semantic_models or change default_semantic_model"
                ))

        return results

    def _check_directory_exists(self, value: str, field: str, config: Dict[str, Any]) -> List[ValidationResult]:
        """Check if directory exists"""
        path = Path(value)
        if not path.exists():
            return [ValidationResult(
                is_valid=False,
                level=ValidationLevel.ERROR,
                message=f"Directory does not exist: {value}",
                field=field,
                suggested_fix=f"Create directory {value} or update path",
                auto_fixable=False
            )]
        return []

    def _check_directory_writable(self, value: str, field: str, config: Dict[str, Any]) -> List[ValidationResult]:
        """Check if directory is writable"""
        path = Path(value)
        try:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            # Test writability
            test_file = path / '.write_test'
            test_file.touch()
            test_file.unlink()
        except (OSError, PermissionError) as e:
            return [ValidationResult(
                is_valid=False,
                level=ValidationLevel.ERROR,
                message=f"Directory not writable: {value} ({str(e)})",
                field=field,
                suggested_fix=f"Check permissions for {value}",
                auto_fixable=False
            )]
        return []

    def _validate_scispacy_models(self, value: List[str], field: str, config: Dict[str, Any]) -> List[ValidationResult]:
        """Validate sciSpaCy model names"""
        valid_models = [
            "en_core_sci_lg",
            "en_core_sci_md",
            "en_core_sci_sm",
            "en_ner_craft_md",
            "en_ner_bc5cdr_md",
            "en_ner_jnlpba_md",
            "en_ner_bionlp13cg_md"
        ]

        results = []
        for model in value:
            if model not in valid_models:
                results.append(ValidationResult(
                    is_valid=False,
                    level=ValidationLevel.WARNING,
                    message=f"Unknown sciSpaCy model: {model}",
                    field=field,
                    suggested_fix=f"Choose from: {valid_models}"
                ))

        return results

    def _validate_ai_model(self, value: str, field: str, config: Dict[str, Any]) -> List[ValidationResult]:
        """Validate AI model name"""
        valid_models = [
            "BioMistral/BioMistral-7B",
            "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
            "microsoft/DialoGPT-medium",
            "mistralai/Mistral-7B-Instruct-v0.3"
        ]

        if value not in valid_models:
            return [ValidationResult(
                is_valid=False,
                level=ValidationLevel.WARNING,
                message=f"Unknown AI model: {value}",
                field=field,
                suggested_fix=f"Choose from: {valid_models} or ensure model is available"
            )]
        return []

    def _validate_api_key_if_enabled(self, value: str, field: str, config: Dict[str, Any]) -> List[ValidationResult]:
        """Validate API key when feature is enabled"""
        # This would be called when we have the full config context
        return []

    def _validate_semantic_model_dict(self, value: Dict[str, str], field: str, config: Dict[str, Any]) -> List[ValidationResult]:
        """Validate semantic model dictionary structure"""
        if not isinstance(value, dict):
            return [ValidationResult(
                is_valid=False,
                level=ValidationLevel.ERROR,
                message="semantic_models must be a dictionary",
                field=field,
                suggested_fix="Provide semantic_models as {'key': 'model_name'}"
            )]

        valid_models = [
            "sentence-transformers/all-MiniLM-L12-v2",
            "nomic-ai/nomic-embed-text-v1.5",
            "sentence-transformers/all-mpnet-base-v2"
        ]

        results = []
        for key, model in value.items():
            if model not in valid_models:
                results.append(ValidationResult(
                    is_valid=False,
                    level=ValidationLevel.WARNING,
                    message=f"Unknown semantic model: {model}",
                    field=f"{field}.{key}",
                    suggested_fix=f"Choose from: {valid_models}"
                ))

        return results

    def auto_fix_config(self, config: Dict[str, Any], validation_results: List[ValidationResult]) -> Tuple[Dict[str, Any], List[ValidationResult]]:
        """Auto-fix configuration issues where possible"""
        fixed_config = config.copy()
        unfixed_results = []

        for result in validation_results:
            if result.auto_fixable and result.field:
                try:
                    if result.field in fixed_config:
                        # Auto-fix range issues
                        if 'range' in result.message.lower():
                            # Clamp to valid range (need schema to get ranges)
                            if hasattr(self, '_get_field_range'):
                                min_val, max_val = self._get_field_range(result.field)
                                if isinstance(fixed_config[result.field], (int, float)):
                                    fixed_config[result.field] = max(min_val, min(max_val, fixed_config[result.field]))
                        # Add other auto-fix logic here
                    else:
                        unfixed_results.append(result)
                except Exception as e:
                    logger.error(f"Auto-fix failed for {result.field}: {e}")
                    unfixed_results.append(result)
            else:
                unfixed_results.append(result)

        return fixed_config, unfixed_results


def create_config_validator() -> ConfigValidator:
    """Factory function to create config validator"""
    return ConfigValidator()


def validate_and_fix_config(config: Dict[str, Any], auto_fix: bool = True) -> Tuple[Dict[str, Any], List[ValidationResult], bool]:
    """Validate and optionally auto-fix configuration"""
    validator = create_config_validator()
    results = validator.validate_full_config(config)

    # Separate errors by severity
    critical_errors = [r for r in results if r.level == ValidationLevel.CRITICAL]
    errors = [r for r in results if r.level == ValidationLevel.ERROR]
    warnings = [r for r in results if r.level == ValidationLevel.WARNING]

    logger.info(f"Config validation: {len(critical_errors)} critical, {len(errors)} errors, {len(warnings)} warnings")

    if critical_errors or errors:
        for error in critical_errors + errors:
            logger.error(f"Config error: {error.message}")
            if error.suggested_fix:
                logger.info(f"Suggested fix: {error.suggested_fix}")

    for warning in warnings:
        logger.warning(f"Config warning: {warning.message}")

    # Auto-fix if requested and possible
    fixed_config = config
    unfixed_results = results

    if auto_fix and any(r.auto_fixable for r in results):
        fixed_config, unfixed_results = validator.auto_fix_config(config, results)
        logger.info(f"Auto-fixed {len(results) - len(unfixed_results)} configuration issues")

    is_valid = len(critical_errors) == 0 and len([r for r in unfixed_results if r.level in [ValidationLevel.CRITICAL, ValidationLevel.ERROR]]) == 0

    return fixed_config, unfixed_results, is_valid