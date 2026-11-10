"""
Configuration Constants
========================
Centralized configuration for all magic numbers, thresholds, and defaults.
This file eliminates magic numbers and makes the codebase more maintainable.
"""

from dataclasses import dataclass
from typing import Dict, List


# ============================================================================
# CONFIDENCE SCORING CONSTANTS
# ============================================================================

class ConfidenceThresholds:
    """
    Confidence scoring thresholds.

    All confidence scores are in the range [0.0, 1.0].
    These values are based on empirical testing and domain requirements.
    """

    # Base scores
    BASE_CONFIDENCE = 0.50  # Neutral starting point for all entities

    # Entity type priority bonuses (lower priority number = higher bonus)
    # Core entity types get higher confidence
    PRIORITY_HIGH_BONUS = 0.25      # Priority 1-2 (ORGANISM, CHEMICAL, DISEASE)
    PRIORITY_MEDIUM_BONUS = 0.18    # Priority 3-4 (GENE, PROTEIN, DNA_RNA, CELL_TYPE)
    PRIORITY_LOW_BONUS = 0.12       # Priority 5-8
    PRIORITY_MINIMAL_BONUS = 0.06   # Priority 9-10 (LAB_METHOD, DATA_ANALYSIS)

    # Pattern matching bonuses
    PATTERN_MATCH_BONUS = 0.15      # Matches regex pattern for entity type
    SCIENTIFIC_NAME_BONUS = 0.12    # Linnaean binomial format (e.g., "E. coli")
    GENE_SYMBOL_BONUS = 0.10        # Gene symbol format (e.g., "BRCA1")

    # Context quality bonuses
    CONTEXT_LONG_BONUS = 0.08       # Context >= 100 characters
    CONTEXT_MEDIUM_BONUS = 0.05     # Context >= 50 characters
    CONTEXT_SHORT_BONUS = 0.02      # Context >= 20 characters
    CONTEXT_CONTAINS_TERM_BONUS = 0.07  # Term appears in its context

    # Supporting evidence bonuses
    DEFINITION_BONUS = 0.04         # Has definition
    ALIAS_BONUS = 0.02              # Has alias
    EXAMPLE_BONUS = 0.02            # Has example

    # Microbiome relevance bonuses
    RELEVANCE_HIGH_BONUS = 0.15     # >= 3 microbiome keywords
    RELEVANCE_MEDIUM_BONUS = 0.12   # 2 microbiome keywords
    RELEVANCE_LOW_BONUS = 0.08      # 1 microbiome keyword
    CORE_CONTEXT_BONUS = 0.05       # Core entity in gut/microbiome context

    # Penalties
    VERY_SHORT_PENALTY = 0.6        # Length < 3
    SHORT_PENALTY = 0.8             # Length < 5
    SINGLE_WORD_PENALTY = 0.92      # Single word (not gene/chemical)
    SYMBOLS_ONLY_PENALTY = 0.3      # Only numbers/symbols

    # Mapping confidence thresholds
    MAPPING_THRESHOLD_DEFAULT = 0.7  # Default minimum for accepting mappings
    HIGH_CONFIDENCE_THRESHOLD = 0.8  # Threshold for "high confidence" classification

    # Confidence calculation components (UMLS/BioPortal/OLS)
    # Base confidence for ontology matches
    ONTOLOGY_BASE_CONFIDENCE = 0.5

    # Exact/Partial match bonuses
    ONTOLOGY_EXACT_MATCH_BONUS = 0.4      # Exact name match
    ONTOLOGY_PARTIAL_MATCH_BONUS = 0.2    # Partial match (contains)
    ONTOLOGY_SYNONYM_EXACT_BONUS = 0.25   # Exact synonym match
    ONTOLOGY_SYNONYM_PARTIAL_BONUS = 0.1  # Partial synonym match

    # Semantic type bonus
    ONTOLOGY_SEMANTIC_TYPE_BONUS = 0.1    # Expected semantic type matches

    # Standard concept bonus
    ONTOLOGY_STANDARD_CONCEPT_BONUS = 0.1 # Is a standard concept

    # Definition presence
    ONTOLOGY_DEFINITION_BONUS = 0.05      # Has definition


# ============================================================================
# SEMANTIC DEDUPLICATION CONSTANTS
# ============================================================================

class SemanticDeduplication:
    """
    Settings for semantic similarity-based deduplication.
    """

    # Similarity threshold for considering two entities as duplicates
    DEFAULT_THRESHOLD = 0.8  # 80% similarity = duplicate

    # Maximum batch size for encoding (to avoid memory issues)
    MAX_BATCH_SIZE = 32

    # Show progress bar for large operations
    SHOW_PROGRESS_MIN_ITEMS = 100


# ============================================================================
# ENTITY TYPE CONFIGURATION
# ============================================================================

@dataclass
class EntityTypeConfig:
    """Configuration for a single entity type."""
    description: str
    examples: List[str]
    patterns: List[str]
    priority: int  # Lower = more important
    domain_id: str  # OMOP domain ID


class EntityTypes:
    """
    All entity type configurations.
    """

    ORGANISM = EntityTypeConfig(
        description='Bacteria, archaea, fungi, viruses, microbiota, taxa, eukaryotic organisms',
        examples=['Bacteroides fragilis', 'E. coli', 'Firmicutes', 'Lactobacillus'],
        patterns=[
            r'\b([A-Z][a-z]+[a-z]*\s+[a-z]+(?:\s+[a-z]+)*)\b',
            r'\b([A-Z][a-z]+\s+sp[p]?)\b',
            r'\b\w*bacter\w*\b', r'\b\w*coccus\b', r'\b\w*aceae\b'
        ],
        priority=1,
        domain_id='Measurement'
    )

    CHEMICAL = EntityTypeConfig(
        description='Chemical compounds, metabolites, drugs, enzymes, hormones',
        examples=['butyrate', 'acetate', 'propionate', 'glucose', 'insulin'],
        patterns=[
            r'\b[A-Za-z0-9\-\']+(?:acid|ate|ose|ol|one|ase|ium|ide|ine)\b',
            r'\b(SCFA|short-chain fatty acid)s?\b'
        ],
        priority=2,
        domain_id='Drug'
    )

    GENE = EntityTypeConfig(
        description='Genes, genetic markers, DNA/RNA segments',
        examples=['BRCA1', '16S rRNA', 'NOD2', 'TLR4'],
        patterns=[
            r'\b[A-Z0-9\-]+(?:\s+gene)?\b',
            r'\b\w*gene\b'
        ],
        priority=3,
        domain_id='Genetic'
    )

    PROTEIN = EntityTypeConfig(
        description='Proteins, antibodies, cytokines',
        examples=['insulin', 'hemoglobin', 'TNF-alpha', 'interleukin'],
        patterns=[
            r'\b[A-Z0-9\-]+(?:\s+protein)?\b',
            r'\b\w*protein\b'
        ],
        priority=3,
        domain_id='Genetic'
    )

    DISEASE = EntityTypeConfig(
        description='Diseases, conditions, syndromes, disorders',
        examples=['Type 2 Diabetes', 'Crohn\'s disease', 'Obesity', 'IBD'],
        patterns=[
            r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Syndrome|Disease|Disorder)\b',
            r'\b\w*disease\b', r'\b\w*disorder\b'
        ],
        priority=2,
        domain_id='Condition'
    )

    CELL_TYPE = EntityTypeConfig(
        description='Cells, cell lines, tissues, cellular structures',
        examples=['macrophage', 'epithelial cell', 'neuron'],
        patterns=[r'\b\w*cell\b', r'\b\w*tissue\b'],
        priority=3,
        domain_id='Measurement'
    )

    DNA_RNA = EntityTypeConfig(
        description='DNA, RNA, plasmids, vectors, genetic material',
        examples=['16S rRNA', 'plasmid', 'mRNA', 'cDNA'],
        patterns=[r'\b\w*RNA\b', r'\b\w*DNA\b', r'\b\w*plasmid\b'],
        priority=3,
        domain_id='Genetic'
    )

    GENOMICS = EntityTypeConfig(
        description='Genomics, metagenomics, omics terms',
        examples=['metagenomics', 'transcriptomics', 'sequencing'],
        patterns=[r'\b\w*omics\b', r'\b\w*sequencing\b'],
        priority=4,
        domain_id='Measurement'
    )

    # Methodological types (lower priority)
    SAMPLE_METHOD = EntityTypeConfig(
        description='Sample collection, transport, storage methods',
        examples=['fecal sampling', 'swab collection', 'DNA extraction'],
        patterns=[r'\b([a-z]+\s+(?:kit|extraction|collection))\b'],
        priority=8,
        domain_id='Specimen'
    )

    LAB_METHOD = EntityTypeConfig(
        description='Lab methods: PCR, sequencing platforms',
        examples=['Illumina MiSeq', '16S rRNA PCR', 'library preparation'],
        patterns=[r'\b(Illumina\s+[A-Za-z0-9]+)\b'],
        priority=9,
        domain_id='Procedure'
    )

    DATA_ANALYSIS = EntityTypeConfig(
        description='Bioinformatics tools, software, databases',
        examples=['QIIME2', 'Mothur', 'DADA2', 'random forest'],
        patterns=[r'\b([A-Z]{3,})\b|\b([a-z]+(?:omics|pipeline))\b'],
        priority=10,
        domain_id='Procedure'
    )

    CLINICAL = EntityTypeConfig(
        description='Clinical terms, procedures, anatomy',
        examples=['diagnosis', 'treatment', 'gut', 'intestine'],
        patterns=[
            r'\b\w*clinica\w*\b',
            r'\b\w*diagnos\w*\b'
        ],
        priority=4,
        domain_id='Observation'
    )

    SCIENTIFIC_TERM = EntityTypeConfig(
        description='General scientific and biomedical terms',
        examples=['PCR', 'microscopy', 'chromatography'],
        patterns=[r'\b\w*laboratory\w*\b', r'\b\w*method\w*\b'],
        priority=5,
        domain_id='Observation'
    )


# ============================================================================
# CHUNKING STRATEGY
# ============================================================================

class Chunking:
    """
    Text chunking configuration for processing large texts.

    Chunks are sized to balance context preservation vs LLM token limits.
    Overlap helps prevent entities from being split across chunks.
    """

    # Chunk sizes (in characters)
    SMALL = 5000      # Short documents (< 10k chars)
    MEDIUM = 12500    # Medium documents (10k-50k chars)
    LARGE = 20000     # Long documents (50k-100k chars)
    XLARGE = 30000    # Very long documents (> 100k chars)

    # Overlap ratios (fraction of chunk size)
    # Higher overlap = better entity capture but more redundant processing
    SMALL_OVERLAP = 0.10     # 10% for small chunks (500 chars)
    MEDIUM_OVERLAP = 0.05    # 5% for medium chunks (625 chars)
    LARGE_OVERLAP = 0.03     # 3% for large chunks (600 chars)
    XLARGE_OVERLAP = 0.02    # 2% for xl chunks (600 chars)

    @classmethod
    def get_chunk_size(cls, text_length: int) -> int:
        """Determine optimal chunk size based on text length."""
        if text_length < 10000:
            return cls.SMALL
        elif text_length < 50000:
            return cls.MEDIUM
        elif text_length < 100000:
            return cls.LARGE
        else:
            return cls.XLARGE

    @classmethod
    def get_overlap(cls, chunk_size: int) -> int:
        """Get overlap size for a given chunk size."""
        if chunk_size <= cls.SMALL:
            return int(chunk_size * cls.SMALL_OVERLAP)
        elif chunk_size <= cls.MEDIUM:
            return int(chunk_size * cls.MEDIUM_OVERLAP)
        elif chunk_size <= cls.LARGE:
            return int(chunk_size * cls.LARGE_OVERLAP)
        else:
            return int(chunk_size * cls.XLARGE_OVERLAP)


# ============================================================================
# WINDOWED MULTI-PASS STRATEGY
# ============================================================================

class WindowedPasses:
    """
    Configuration for the windowed multi-pass extraction strategy.

    This strategy processes different text windows to ensure comprehensive
    entity extraction while managing computational cost.
    """

    # Window configurations (start_offset, length_in_chars)
    PASS_1 = (0, 8000)
    PASS_2 = (0, 8000)      # Duplicate for consensus
    PASS_3 = (10000, 8000)
    PASS_4 = (15000, 8000)
    PASS_5_CONDITIONAL = (20000, 8000)  # Only if < 100 entities found
    PASS_6_CONDITIONAL = (25000, 10000) # Only if < 50 entities found

    # Entity count thresholds for conditional passes
    PASS_5_THRESHOLD = 100  # Run Pass 5 if we have < 100 entities
    PASS_6_THRESHOLD = 50   # Run Pass 6 if we have < 50 entities


# ============================================================================
# LLM MODEL CONFIGURATIONS
# ============================================================================

class ModelConfigs:
    """
    Default configurations for various LLM models.

    These settings balance speed, cost, and quality.
    """

    # Format: (max_tokens, temperature, timeout_sec, context_window)
    PHI3_MINI = (2000, 0.1, 300, 4096)
    QWEN3_8B = (4000, 0.1, 600, 8192)
    QWEN3_14B = (8000, 0.3, 1200, 32768)
    GEMMA3_12B = (8000, 0.3, 1200, 16384)
    BIOMISTRAL_7B = (4000, 0.1, 600, 8192)
    DEEPSEEK_R1_8B = (8000, 0.1, 1200, 8192)
    GLM_4 = (4096, 0.1, 300, 8192)
    GLM_4_6 = (4096, 0.1, 300, 8192)
    GLM_4_FLASH = (4096, 0.1, 300, 128000)
    GLM_4_AIR = (4096, 0.1, 300, 128000)
    GLM_4_7 = (4096, 0.1, 300, 8192)


# ============================================================================
# PIPELINE LIMITS
# ============================================================================

class PipelineLimits:
    """
    Operational limits to prevent resource exhaustion.
    """

    # Entity limits
    MAX_ENTITIES_PER_CHUNK = 200   # Maximum entities to extract per chunk
    MAX_ENTITIES_FINAL = 500       # Maximum entities in final output
    MIN_CONFIDENCE_FILTER = 0.4    # Minimum confidence for inclusion

    # Processing limits
    MAX_WORKERS = 5                # Maximum parallel extraction workers
    MAX_FILE_WORKERS = 1           # Maximum parallel file processors
    MAX_FILE_SIZE_MB = 100         # Maximum input file size (100MB)
    MAX_TEXT_LENGTH = 10_000_000   # Maximum text length to process (10M chars)

    # Timeout limits (seconds)
    API_CALL_TIMEOUT = 600         # 10 minutes for LLM API calls
    FILE_PROCESSING_TIMEOUT = 3600 # 1 hour per file
    PIPELINE_TIMEOUT = 7200        # 2 hours for full pipeline


# ============================================================================
# FUZZY MATCHING
# ============================================================================

class FuzzyMatching:
    """
    Settings for fuzzy string matching (e.g., for OMOP vocabulary).
    """

    # Thresholds (0-100)
    DEFAULT_THRESHOLD = 95        # Very high threshold for entity matching
    LOOSE_THRESHOLD = 85          # More permissive matching
    MAX_MATCHES = 3               # Maximum matches to return per entity


# ============================================================================
# ONTOLOGY MAPPING
# ============================================================================

class OntologyMapping:
    """
    Configuration for ontology mapping (OMOP, UMLS, BioPortal, OLS).
    """

    # API timeouts (seconds)
    UMLS_TIMEOUT = 10
    BIOPORTAL_TIMEOUT = 10
    OLS_TIMEOUT = 10
    ATHENA_TIMEOUT = 10

    # Result limits
    MAX_RESULTS = 5                # Maximum results to fetch per API call

    # Cache sizes
    CACHE_SIZE = 1000              # Number of mappings to cache
    OMOP_CACHE_SIZE = 2000         # Larger cache for local OMOP vocab


# ============================================================================
# MICROPBIOME RELEVANCE
# ============================================================================

class MicrobiomeRelevance:
    """
    Keywords and thresholds for microbiome relevance scoring.
    """

    # Core keywords that indicate microbiome context
    CORE_KEYWORDS = {
        'gut', 'microbiome', 'microbiota', 'bacteria', 'bacterial',
        'intestinal', 'colon', 'fecal', 'faecal', 'stool', 'dysbiosis',
        'probiotic', 'prebiotic', 'fermentation', 'scfa',
        'short-chain fatty acid', 'mucosa', 'lumen', 'commensal',
        'pathogen', 'metabolite', 'butyrate', 'propionate', 'acetate'
    }

    # Relevance score thresholds
    HIGH_RELEVANCE = 0.7          # High relevance: > 0.7
    MEDIUM_RELEVANCE = 0.4        # Medium relevance: 0.4 - 0.7
    LOW_RELEVANCE = 0.0           # Low relevance: < 0.4

    # Keyword count bonuses
    HIGH_KEYWORD_COUNT = 3         # >= 3 keywords = high bonus
    MEDIUM_KEYWORD_COUNT = 2       # 2 keywords = medium bonus
    LOW_KEYWORD_COUNT = 1          # 1 keyword = low bonus


# ============================================================================
# BIOMISTRAL VALIDATION
# ============================================================================

class BioMistralValidation:
    """
    Settings for BioMistral-based biomedical validation.
    """

    # Validation thresholds
    CONFIDENCE_THRESHOLD = 0.7    # Minimum confidence for biomedical validity

    # Type correction settings
    BATCH_SIZE = 20               # Entities per batch for type correction
    MAX_TOKENS = 500              # Max tokens per correction request

    # Deduplication settings
    BIOMISTRAL_THRESHOLD = 0.7    # Threshold for BioMistral-based dedup
    SEMANTIC_THRESHOLD = 0.85     # Threshold for semantic similarity
    MAX_CANDIDATES = 10           # Max candidates for BioMistral comparison


# ============================================================================
# ENVIRONMENT AND PATHS
# ============================================================================

class Paths:
    """
    Default paths (can be overridden by environment variables).
    """

    # Project structure
    PROJECT_ROOT = None  # Set dynamically based on file location
    DATA_DIR = "data"
    OMOP_VOCAB_DIR = "data/omop_vocab"
    OUTPUT_DIR = "output"
    LOG_DIR = "logs"
    CHECKPOINT_DIR = "checkpoints"

    # Environment variable names
    ENV_OMOP_VOCAB = "OMOP_VOCAB_DIR"
    ENV_UMLS_KEY = "UMLS_API_KEY"
    ENV_BIOPORTAL_KEY = "BIOPORTAL_API_KEY"
    ENV_HUGGINGFACE_KEY = "HUGGINGFACE_API_KEY"
    ENV_LLM_BASE_URL = "LLM_BASE_URL"
    ENV_OLLAMA_BASE_URL = "OLLAMA_BASE_URL"


# ============================================================================
# LOGGING
# ============================================================================

class Logging:
    """Logging configuration."""

    # Log levels
    DEFAULT_LEVEL = "INFO"
    VERBOSE_LEVEL = "DEBUG"

    # Log formats
    TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    JSON_FORMAT = True  # Use JSON format in production

    # Log file settings
    MAX_FILE_SIZE_MB = 100
    BACKUP_COUNT = 5


# ============================================================================
# HELPERS
# ============================================================================

def get_entity_type_config(entity_type: str) -> EntityTypeConfig:
    """Get configuration for an entity type."""
    configs = {
        'ORGANISM': EntityTypes.ORGANISM,
        'CHEMICAL': EntityTypes.CHEMICAL,
        'GENE': EntityTypes.GENE,
        'PROTEIN': EntityTypes.PROTEIN,
        'DISEASE': EntityTypes.DISEASE,
        'CELL_TYPE': EntityTypes.CELL_TYPE,
        'DNA_RNA': EntityTypes.DNA_RNA,
        'GENOMICS': EntityTypes.GENOMICS,
        'SAMPLE_METHOD': EntityTypes.SAMPLE_METHOD,
        'LAB_METHOD': EntityTypes.LAB_METHOD,
        'DATA_ANALYSIS': EntityTypes.DATA_ANALYSIS,
        'CLINICAL': EntityTypes.CLINICAL,
        'SCIENTIFIC_TERM': EntityTypes.SCIENTIFIC_TERM,
    }
    return configs.get(entity_type.upper())


def get_model_config(model: str) -> tuple:
    """Get configuration for a model."""
    configs = {
        'phi3:mini': ModelConfigs.PHI3_MINI,
        'qwen3.5:9b': ModelConfigs.QWEN3_8B,
        'qwen3:8b': ModelConfigs.QWEN3_8B,
        'qwen3:14b': ModelConfigs.QWEN3_14B,
        'gemma3:12b': ModelConfigs.GEMMA3_12B,
        'biomistral-7B': ModelConfigs.BIOMISTRAL_7B,
        'deepseek-r1:8b': ModelConfigs.DEEPSEEK_R1_8B,
        'glm-4': ModelConfigs.GLM_4,
        'glm-4.6': ModelConfigs.GLM_4_6,
        'glm-4-flash': ModelConfigs.GLM_4_FLASH,
        'glm-4-air': ModelConfigs.GLM_4_AIR,
        'glm-4.7': ModelConfigs.GLM_4_7,
    }
    return configs.get(model.lower(), ModelConfigs.QWEN3_8B)  # Default to qwen3:8b
