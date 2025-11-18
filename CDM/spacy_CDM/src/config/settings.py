"""
Configuration settings for the scientific term extraction pipeline
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path
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
    """Configuration for multi-layer deduplication"""
    exact_match: bool = True
    fuzzy_threshold: float = 0.85
    fuzzy_weight: float = 0.6
    semantic_threshold: float = 0.9
    semantic_model_choice: str = "mini-lm"  # Options: "nomic", "mini-lm", "mpnet"
    min_term_length: int = 3
    max_canonical_length: int = 100


@dataclass
class UMLSConfig:
    """Configuration for UMLS mapping"""
    api_key: Optional[str] = None
    bioportal_api_key: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    use_ncbo_annotator: bool = True
    use_ols: bool = True


@dataclass
class OMOPConfig:
    """Configuration for OMOP mapping"""
    vocab_data_dir: str = "omop_vocab"
    use_parquet: bool = True
    fuzzy_match_threshold: float = 0.8
    create_standard_concepts: bool = True


@dataclass
class AIConfig:
    """Configuration for AI-powered term cleaning"""
    model_name: str = "mistral-7b-instruct"
    api_base: str = "http://localhost:8000/v1"
    api_key: str = "not-needed"
    max_tokens: int = 100
    temperature: float = 0.1
    timeout: int = 30


@dataclass
class ProcessingConfig:
    """Configuration for text processing"""
    chunk_size: int = 100000
    overlap: int = 1000
    min_confidence: float = 0.1
    min_science_score: float = 0.5
    p1_min_length: int = 3
    p2_max_length: int = 100
    p3_no_websites: bool = True
    p4_require_alpha: bool = True
    p5_remove_leading_non_alpha: bool = True
    p6_remove_duplicates: bool = True
    p7_exclude_stopwords: bool = True
    p8_min_confidence: float = 0.1
    p9_min_science_score: float = 0.5
    p10_no_all_caps: bool = True
    p11_no_start_with_cap: bool = True
    p12_min_char_variety: int = 2


@dataclass
class PipelineConfig:
    """Main pipeline configuration"""
    # Data paths
    input_dir: str = "data"
    output_dir: str = "output"
    log_dir: str = "logs"

    # Module configurations
    scispacy: SciSpaCyConfig = field(default_factory=SciSpaCyConfig)
    deduplication: DeduplicationConfig = field(default_factory=DeduplicationConfig)
    umls: UMLSConfig = field(default_factory=UMLSConfig)
    omop: OMOPConfig = field(default_factory=OMOPConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)

    # Pipeline settings
    max_files: int = -1  # -1 for unlimited
    max_docs_per_file: int = -1
    save_intermediate: bool = True
    parallel_processing: bool = True
    num_workers: int = 4

    def __post_init__(self):
        """Create necessary directories"""
        for dir_path in [self.input_dir, self.output_dir, self.log_dir]:
            Path(dir_path).mkdir(exist_ok=True)

    @classmethod
    def from_args(cls, args: Dict[str, Any]) -> 'PipelineConfig':
        """Create config from CLI arguments"""
        config = cls()

        # Update config with CLI args
        if 'input_dir' in args:
            config.input_dir = args['input_dir']
        if 'output_dir' in args:
            config.output_dir = args['output_dir']
        if 'semantic_model' in args:
            config.deduplication.semantic_model_choice = args['semantic_model']
        if 'fuzzy_threshold' in args:
            config.deduplication.fuzzy_threshold = float(args['fuzzy_threshold'])
        if 'semantic_threshold' in args:
            config.deduplication.semantic_threshold = float(args['semantic_threshold'])
        if 'max_files' in args:
            config.max_files = int(args['max_files'])
        if 'max_docs' in args:
            config.max_docs_per_file = int(args['max_docs'])
        if 'scispacy_models' in args:
            config.scispacy.models = args['scispacy_models']
        if 'parallel' in args:
            config.parallel_processing = args['parallel']
        if 'workers' in args:
            config.num_workers = int(args['workers'])

        return config