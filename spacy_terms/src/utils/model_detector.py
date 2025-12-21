"""
Dynamic spaCy model detection utilities.
Detects and validates available spaCy models for use in the pipeline.
"""

import subprocess
import sys
from typing import List, Dict, Set, Any
import spacy
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def get_installed_spacy_models() -> List[Dict[str, str]]:
    """
    Get list of installed spaCy models by parsing `spacy validate` output.
    Returns a list of dictionaries with model information.
    """
    try:
        # Security: Use whitelist of allowed commands and add timeout
        allowed_commands = [
            [sys.executable, "-m", "spacy", "validate"],
            [sys.executable, "-m", "spacy", "--version"]
        ]

        result = subprocess.run(
            allowed_commands[0],  # Use the first allowed command
            capture_output=True,
            text=True,
            check=True,
            timeout=30  # Prevent hanging
        )
        output = result.stdout

    except subprocess.CalledProcessError as e:
        logger.error(f"Error running spacy validate: {e}")
        return []
    except subprocess.TimeoutExpired:
        logger.error("spaCy validate command timed out")
        return []
    except FileNotFoundError:
        logger.error("spaCy not found. Please install spaCy.")
        return []

    models = []
    lines = output.split('\n')

    # Look for the table header and extract model information
    table_started = False
    for line in lines:
        if "NAME" in line and "SPACY" in line and "VERSION" in line:
            table_started = True
            continue

        if table_started and line.strip():
            # Parse model line
            parts = line.split()
            if len(parts) >= 3:
                model_name = parts[0]
                spacy_version = parts[1]
                version = parts[2] if len(parts) > 2 else "unknown"

                # Check if model is compatible (marked with ✔)
                if "✔" in line:
                    models.append({
                        "name": model_name,
                        "spacy_version": spacy_version,
                        "version": version,
                        "compatible": True
                    })
                else:
                    models.append({
                        "name": model_name,
                        "spacy_version": spacy_version,
                        "version": version,
                        "compatible": False
                    })

    return models


def filter_scientific_models(models: List[Dict[str, str]]) -> List[str]:
    """
    Filter models to keep only scientific/medical models suitable for biomedical NER.
    """
    scientific_patterns = [
        "en_core_sci",      # Core scientific models
        "en_ner_",          # NER models
        "en_core_web_sm",   # Basic English model (fallback)
        "en_core_web_md",   # Basic English model (fallback)
        "en_core_web_lg",   # Basic English model (fallback)
    ]

    compatible_scientific = []
    for model in models:
        if model["compatible"] and any(pattern in model["name"] for pattern in scientific_patterns):
            compatible_scientific.append(model["name"])

    return compatible_scientific


def verify_model_load(model_name: str, disabled_components: List[str] = None) -> bool:
    """
    Verify that a model can be successfully loaded.
    """
    try:
        disabled = disabled_components or ["parser"]
        nlp = spacy.load(model_name, disable=disabled)

        # Add sentencizer if not present (needed for sentence boundaries)
        if "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")

        return True

    except Exception as e:
        logger.warning(f"Failed to load model {model_name}: {e}")
        return False


def get_available_scientific_models(disabled_components: List[str] = None) -> List[str]:
    """
    Get list of available and loadable scientific spaCy models.
    """
    logger.info("Detecting available spaCy models...")

    # Get all installed models
    installed_models = get_installed_spacy_models()

    if not installed_models:
        logger.warning("No spaCy models found")
        return []

    # Filter for scientific models
    scientific_models = filter_scientific_models(installed_models)

    if not scientific_models:
        logger.warning("No scientific spaCy models found")
        return []

    # Verify each model can be loaded
    available_models = []
    for model_name in scientific_models:
        if verify_model_load(model_name, disabled_components):
            available_models.append(model_name)
            logger.info(f"✓ Model available: {model_name}")
        else:
            logger.warning(f"✗ Model unavailable: {model_name}")

    return available_models


def update_scispacy_config_with_available_models(config) -> None:
    """
    Update SciSpaCyConfig object to use only available models based on user preferences.
    """
    available_models = get_available_scientific_models(config.disabled_components)

    if not available_models:
        logger.error("No spaCy models available for scientific term extraction")
        logger.error("Please install at least one scientific spaCy model:")
        logger.error("  pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.1/en_core_sci_lg-0.5.1.tar.gz")
        logger.error("  pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.1/en_ner_bc5cdr_md-0.5.1.tar.gz")
        # Keep original models for fallback handling in TermsExtractor
        return

    # Determine which models to use based on configuration
    selected_models = []

    if config.preferred_models and config.auto_detect_models:
        # User has specified preferred models - use only those that are available
        logger.info("Using user-specified preferred models...")
        for preferred_model in config.preferred_models:
            if preferred_model in available_models:
                selected_models.append(preferred_model)
                logger.info(f"  ✓ {preferred_model}")
            else:
                logger.warning(f"  ✗ {preferred_model} - not available")

        # If no preferred models are available, fall back to available models
        if not selected_models:
            logger.warning("None of the preferred models are available. Using all available models...")
            selected_models = available_models.copy()

    elif config.use_all_available and config.auto_detect_models:
        # User wants to use all available models
        logger.info("Using all available scientific models...")
        selected_models = available_models.copy()

    elif config.auto_detect_models:
        # Filter default models to only include available ones
        logger.info("Filtering default models to available ones...")
        for model in config.models:
            if model in available_models:
                selected_models.append(model)
                logger.info(f"  ✓ {model}")
            else:
                logger.warning(f"  ✗ {model} - not available")

        # Add any additional available models that weren't in original config
        # to ensure we have at least some models
        if not selected_models and available_models:
            logger.info("No default models available, using available models...")
            selected_models = available_models.copy()

    else:
        # Don't auto-detect - use whatever is configured
        logger.info("Using configured models without auto-detection...")
        selected_models = config.models.copy()

    # Sort by priority
    selected_models = sort_models_by_priority(selected_models)

    # Update config with final selection
    config.models = selected_models

    logger.info(f"Final spaCy model configuration ({len(config.models)} models):")
    for i, model in enumerate(config.models, 1):
        priority_info = f"[Priority {i}]"
        logger.info(f"  {priority_info} {model}")

    return config.models


def set_preferred_models(config, models: List[str]) -> None:
    """
    Helper function to set user's preferred models.
    """
    config.preferred_models = models
    logger.info(f"Set preferred models: {models}")


def add_preferred_model(config, model: str) -> None:
    """
    Helper function to add a single preferred model.
    """
    if config.preferred_models is None:
        config.preferred_models = []

    if model not in config.preferred_models:
        config.preferred_models.append(model)
        logger.info(f"Added preferred model: {model}")
    else:
        logger.info(f"Model {model} already in preferred models")


def remove_preferred_model(config, model: str) -> None:
    """
    Helper function to remove a preferred model.
    """
    if config.preferred_models and model in config.preferred_models:
        config.preferred_models.remove(model)
        logger.info(f"Removed preferred model: {model}")
    else:
        logger.info(f"Model {model} not in preferred models")


def get_available_model_info(disabled_components: List[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Get detailed information about available models.
    """
    installed_models = get_installed_spacy_models()
    scientific_models = filter_scientific_models(installed_models)

    model_info = {}
    for model_name in scientific_models:
        model_info[model_name] = {
            "compatible": verify_model_load(model_name, disabled_components),
            "priority": get_model_priorities().get(model_name, 999),
            "type": "scientific" if "sci" in model_name or "ner" in model_name else "general"
        }

    return model_info


def get_model_priorities() -> Dict[str, int]:
    """
    Get priority values for different model types for optimal selection.
    Lower numbers = higher priority.
    """
    return {
        # High priority - specialized scientific models
        "en_core_sci_lg": 1,      # Large scientific model
        "en_core_sci_md": 2,      # Medium scientific model
        "en_ner_bc5cdr_md": 3,    # Chemical/disease NER
        "en_ner_craft_md": 4,     # General scientific NER
        "en_ner_jnlpba_md": 5,    # Biomedical NER
        "en_core_sci_scibert": 6, # SciBERT model

        # Medium priority - large general models
        "en_core_web_lg": 7,      # Large general English
        "en_core_web_md": 8,      # Medium general English

        # Low priority - basic models (fallback only)
        "en_core_web_sm": 9,      # Small general English
    }


def sort_models_by_priority(models: List[str]) -> List[str]:
    """
    Sort models by priority for optimal results.
    """
    priorities = get_model_priorities()

    return sorted(models, key=lambda x: priorities.get(x, 999))


def create_fallback_model_list() -> List[str]:
    """
    Create a fallback list of models that are commonly used.
    These models will be checked and used if available.
    """
    return [
        # Scientific models (highest priority)
        "en_core_sci_lg",
        "en_core_sci_md",
        "en_ner_bc5cdr_md",
        "en_ner_craft_md",
        "en_ner_jnlpba_md",
        "en_core_sci_scibert",

        # General models (fallback)
        "en_core_web_lg",
        "en_core_web_md",
        "en_core_web_sm",
    ]