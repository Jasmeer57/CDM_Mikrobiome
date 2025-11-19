"""
Configuration settings for the advanced scientific term extraction pipeline.
Includes all modules: NER, deduplication, AI correction, UMLS/OMOP mapping.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import os


@dataclass
class SciSpaCyConfig:
    """Configuration for sciSpaCy models"""
    models: List[str] = field(default_factory=lambda: [
        "en_core_sci_lg",
        "en_ner_craft_md",
        "en_ner_bc5cdr_md",
        "en_ner_jnlpba_md"
    ])
    disabled_components: List[str] = field(default_factory=lambda: ["parser"])
    batch_size: int = 1000


@dataclass
class DeduplicationConfig:
    """Configuration for deduplication layers"""
    exact_enabled: bool = True
    fuzzy_threshold: float = 0.85
    fuzzy_enabled: bool = True
    semantic_threshold: float = 0.9
    semantic_enabled: bool = True
    semantic_models: Dict[str, str] = field(default_factory=lambda: {
        "mini-lm": "sentence-transformers/all-MiniLM-L12-v2",
        "nomic": "nomic-ai/nomic-embed-text-v1.5",
        "mpnet": "sentence-transformers/all-mpnet-base-v2"
    })
    default_semantic_model: str = "mini-lm"


@dataclass
class AIConfig:
    """Configuration for AI correction and validation"""
    enabled: bool = True
    model_name: str = "mistralai/Mistral-7B-Instruct-v0.2"
    api_key: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 512
    system_prompt: str = """You are a scientific term validation expert. Your task is to:
1. Validate if the given term is a legitimate scientific/biomedical term
2. Correct any spelling or formatting errors
3. Provide a brief definition if available
4. Suggest standardized terminology if possible

Respond in JSON format:
{
    "is_valid": true/false,
    "corrected_term": "corrected version",
    "confidence": 0.0-1.0,
    "definition": "brief definition",
    "standardized_term": "standardized version",
    "category": "biological/chemical/medical/technical"
}"""
    batch_size: int = 10


@dataclass
class UMLSConfig:
    """Configuration for UMLS mapping"""
    enabled: bool = True
    api_key: Optional[str] = None
    timeout: int = 30
    retry_attempts: int = 3
    sources: List[str] = field(default_factory=lambda: [
        "SNOMEDCT_US", "MSH", "CUI", "LNC", "CST", "MDR"
    ])
    batch_size: int = 50


@dataclass
class BioPortalConfig:
    """Configuration for BioPortal API"""
    enabled: bool = True
    api_key: Optional[str] = None
    base_url: str = "http://data.bioontology.org"
    timeout: int = 30
    ontologies: List[str] = field(default_factory=lambda: [
        "SNOMEDCT", "GO", "CHEBI", "DOID", "EFO", "HP", "NCIT"
    ])
    max_results: int = 10


@dataclass
class OMOPConfig:
    """Configuration for OMOP vocabulary mapping"""
    enabled: bool = True
    vocab_dir: Optional[str] = None
    vocabularies: Dict[str, str] = field(default_factory=lambda: {
        "Condition": "CONCEPT",
        "Drug": "CONCEPT",
        "Measurement": "CONCEPT",
        "Procedure": "CONCEPT",
        "Device": "CONCEPT"
    })
    use_fuzzy_matching: bool = True
    fuzzy_threshold: float = 0.85
    concept_cache_file: str = "omop_concepts.json"


@dataclass
class PipelineConfig:
    """Main pipeline configuration"""
    input_dir: str = "./data"
    output_dir: str = "./output"
    max_files: int = 100
    top_k: int = 200
    min_frequency: int = 1
    include_definitions: bool = True
    include_ai_correction: bool = True
    include_umls_mapping: bool = True
    include_omop_mapping: bool = True

    # Module configurations
    scispacy: SciSpaCyConfig = field(default_factory=SciSpaCyConfig)
    deduplication: DeduplicationConfig = field(default_factory=DeduplicationConfig)
    ai_correction: AIConfig = field(default_factory=AIConfig)
    umls: UMLSConfig = field(default_factory=UMLSConfig)
    bioportal: BioPortalConfig = field(default_factory=BioPortalConfig)
    omop: OMOPConfig = field(default_factory=OMOPConfig)

    # File patterns
    input_patterns: List[str] = field(default_factory=lambda: [
        "*.txt", "*.md", "*.csv", "*.json"
    ])

    # Output formats
    output_formats: List[str] = field(default_factory=lambda: [
        "json", "csv", "sqlite"
    ])


@dataclass
class LoggingConfig:
    """Logging configuration"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: str = "pipeline.log"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


def get_config() -> PipelineConfig:
    """Get pipeline configuration from environment variables or defaults"""
    config = PipelineConfig()

    # Override with environment variables if present
    if os.getenv("INPUT_DIR"):
        config.input_dir = os.getenv("INPUT_DIR")
    if os.getenv("OUTPUT_DIR"):
        config.output_dir = os.getenv("OUTPUT_DIR")
    if os.getenv("MAX_FILES"):
        config.max_files = int(os.getenv("MAX_FILES"))
    if os.getenv("SEMANTIC_MODEL"):
        config.deduplication.default_semantic_model = os.getenv("SEMANTIC_MODEL")
    if os.getenv("FUZZY_THRESHOLD"):
        config.deduplication.fuzzy_threshold = float(os.getenv("FUZZY_THRESHOLD"))
    if os.getenv("SEMANTIC_THRESHOLD"):
        config.deduplication.semantic_threshold = float(os.getenv("SEMANTIC_THRESHOLD"))

    # API Keys
    if os.getenv("OPENAI_API_KEY"):
        config.ai_correction.api_key = os.getenv("OPENAI_API_KEY")
    if os.getenv("UMLS_API_KEY"):
        config.umls.api_key = os.getenv("UMLS_API_KEY")
    if os.getenv("BIOPORTAL_API_KEY"):
        config.bioportal.api_key = os.getenv("BIOPORTAL_API_KEY")

    return config


def validate_config(config: PipelineConfig) -> List[str]:
    """Validate configuration and return list of warnings/errors"""
    warnings = []

    # Check if required API keys are present for enabled features
    if config.ai_correction.enabled and not config.ai_correction.api_key:
        warnings.append("AI correction enabled but no API key provided")
    if config.umls.enabled and not config.umls.api_key:
        warnings.append("UMLS mapping enabled but no API key provided")
    if config.bioportal.enabled and not config.bioportal.api_key:
        warnings.append("BioPortal mapping enabled but no API key provided")

    # Check if directories exist
    if not os.path.exists(config.input_dir):
        warnings.append(f"Input directory does not exist: {config.input_dir}")

    # Check if sciSpaCy models are installed
    for model in config.scispacy.models:
        try:
            import spacy
            spacy.load(model)
        except OSError:
            warnings.append(f"sciSpaCy model not installed: {model}")

    return warnings