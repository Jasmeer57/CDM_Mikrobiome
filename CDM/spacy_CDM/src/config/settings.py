"""
Configuration settings for the microbiome term extraction pipeline.
All features preserved from original reference scripts.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Union
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

@dataclass
class ScispacyConfig:
    """Configuration for sciSpaCy models and processing."""
    models: List[str] = field(default_factory=lambda: [
        "en_ner_craft_md",
        "en_ner_bc5cdr_md",
        "en_core_sci_md",
        "en_ner_jnlpba_md"
    ])
    embedding_model: str = "all-MiniLM-L12-v2"
    batch_size: int = 32
    n_process: int = 4
    use_gpu: bool = True
    resolve_abbreviations: bool = True
    confidence_threshold: float = 0.5

@dataclass
class DeduplicationConfig:
    """Configuration for deduplication methods."""
    # Fuzzy deduplication
    fuzzy_threshold: int = 80
    fuzzy_scorer: str = "ratio"  # ratio, partial_ratio, token_sort_ratio, token_set_ratio

    # Semantic deduplication
    semantic_threshold: float = 0.7
    semantic_models: Dict[str, str] = field(default_factory=lambda: {
        "mini-lm": "all-MiniLM-L12-v2",
        "nomic": "nomic-embed-text-v1",
        "mpnet": "all-mpnet-base-v2"
    })
    semantic_model_choice: str = "mini-lm"  # User can change this via CLI
    batch_size_semantic: int = 32

    # Exact deduplication
    case_sensitive: bool = False
    normalize_terms: bool = True

@dataclass
class UmlsConfig:
    """Configuration for UMLS mapping."""
    api_key: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    batch_size: int = 32
    n_process: int = 4
    include_synonyms: bool = True
    include_definitions: bool = True
    include_semantic_types: bool = True
    target_ontologies: List[str] = field(default_factory=lambda: [
        "GO", "CHEBI", "DOID", "NCBITAXON", "HP", "MP", "SNOMEDCT",
        "UBERON", "PO", "EFO", "ENVO", "MESH"
    ])

@dataclass
class OmopConfig:
    """Configuration for OMOP vocabulary processing."""
    vocab_dir: str = "data/vocabulary"
    cache_dir: str = "data/cache"
    output_dir: str = "data/output"
    target_domains: List[str] = field(default_factory=lambda: [
        'Condition', 'Drug', 'Procedure', 'Measurement',
        'Observation', 'Device', 'Spec Anatomic Site'
    ])
    min_similarity_threshold: float = 0.8
    use_parallel: bool = True
    n_workers: int = 24
    cache_preprocessed: bool = True

@dataclass
class AIModelConfig:
    """Configuration for AI-powered term cleaning."""
    model_name: str = "mistralai/Mistral-7B-Instruct-v0.3"
    torch_dtype: str = "bfloat16"
    device_map: str = "auto"
    max_new_tokens: int = 512
    temperature: float = 0.1
    do_sample: bool = True
    top_p: float = 0.95
    top_k: int = 50
    use_gpu: bool = True

@dataclass
class FilteringConfig:
    """Configuration for term filtering and validation."""
    min_frequency: int = 2
    min_term_length: int = 3
    max_term_length: int = 100
    require_alphabetic: bool = True
    max_special_chars_ratio: float = 0.2
    use_semantic_filtering: bool = True
    semantic_relevance_threshold: float = 0.5
    top_k: int = 2000

@dataclass
class PipelineConfig:
    """Main pipeline configuration."""
    # Input/Output
    input_dir: str = "data/input"
    output_dir: str = "data/output"
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # Processing
    max_files: Optional[int] = None
    file_extensions: List[str] = field(default_factory=lambda: [".txt", ".md", ".csv"])
    encoding: str = "utf-8"

    # Sub-configurations
    scispacy: ScispacyConfig = field(default_factory=ScispacyConfig)
    deduplication: DeduplicationConfig = field(default_factory=DeduplicationConfig)
    umls: UmlsConfig = field(default_factory=UmlsConfig)
    omop: OmopConfig = field(default_factory=OmopConfig)
    ai_model: AIModelConfig = field(default_factory=AIModelConfig)
    filtering: FilteringConfig = field(default_factory=FilteringConfig)

    # Pipeline stages (user can enable/disable)
    enable_term_extraction: bool = True
    enable_fuzzy_deduplication: bool = True
    enable_semantic_deduplication: bool = True
    enable_umls_mapping: bool = True
    enable_ai_cleaning: bool = True
    enable_omop_mapping: bool = True

    # Quality control
    validate_inputs: bool = True
    validate_outputs: bool = True
    backup_intermediate: bool = True
    continue_on_error: bool = True

    def __post_init__(self):
        """Post-initialization validation and setup."""
        # Create output directories
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # Validate semantic model choice
        if self.deduplication.semantic_model_choice not in self.deduplication.semantic_models:
            logger.warning(f"Unknown semantic model: {self.deduplication.semantic_model_choice}")
            logger.info(f"Available models: {list(self.deduplication.semantic_models.keys())}")
            self.deduplication.semantic_model_choice = "mini-lm"

        # Update embedding model if semantic model is different
        if self.deduplication.semantic_model_choice in self.deduplication.semantic_models:
            self.scispacy.embedding_model = self.deduplication.semantic_models[self.deduplication.semantic_model_choice]

        # Set up logging
        self._setup_logging()

    def _setup_logging(self):
        """Set up logging configuration."""
        import logging

        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        handlers = [logging.StreamHandler()]
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(self.log_file))

        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format=log_format,
            handlers=handlers,
            force=True
        )

    @classmethod
    def from_file(cls, config_path: Union[str, Path]) -> "PipelineConfig":
        """Load configuration from JSON or YAML file."""
        import json
        import yaml
        from pathlib import Path

        config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, 'r') as f:
            if config_path.suffix.lower() in ['.yaml', '.yml']:
                data = yaml.safe_load(f)
            elif config_path.suffix.lower() == '.json':
                data = json.load(f)
            else:
                raise ValueError(f"Unsupported config format: {config_path.suffix}")

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineConfig":
        """Create configuration from dictionary."""
        # Handle nested configurations
        if 'scispacy' in data:
            data['scispacy'] = ScispacyConfig(**data['scispacy'])
        if 'deduplication' in data:
            data['deduplication'] = DeduplicationConfig(**data['deduplication'])
        if 'umls' in data:
            data['umls'] = UmlsConfig(**data['umls'])
        if 'omop' in data:
            data['omop'] = OmopConfig(**data['omop'])
        if 'ai_model' in data:
            data['ai_model'] = AIModelConfig(**data['ai_model'])
        if 'filtering' in data:
            data['filtering'] = FilteringConfig(**data['filtering'])

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        result = {}
        for key, value in self.__dict__.items():
            if hasattr(value, '__dict__'):
                result[key] = value.__dict__
            else:
                result[key] = value
        return result

    def save(self, config_path: Union[str, Path]):
        """Save configuration to file."""
        import json
        import yaml
        from pathlib import Path

        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()

        with open(config_path, 'w') as f:
            if config_path.suffix.lower() in ['.yaml', '.yml']:
                yaml.dump(data, f, default_flow_style=False, indent=2)
            elif config_path.suffix.lower() == '.json':
                json.dump(data, f, indent=2)
            else:
                raise ValueError(f"Unsupported config format: {config_path.suffix}")

    def update(self, **kwargs):
        """Update configuration with new values."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning(f"Unknown configuration key: {key}")