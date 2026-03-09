"""
CDM Pipeline Configuration
"""

from typing import Dict, List
import os
from dataclasses import dataclass

@dataclass
class CDMEntityConfig:
    """Configuration for CDM entity types."""

    # Enhanced entity type definitions based on specification
    ENTITY_TYPES = {
        # Microorganisms, Organisms, Taxonomy
        'ORGANISM': {
            'description': 'Bacteria, archaea, fungi, viruses, microbiota, taxa',
            'examples': ['Bacteroides fragilis', 'E. coli', 'Lactobacillus spp.', 'Firmicutes', 'Bacteroidetes', 'Archaea', 'Methanobrevibacter'],
            'patterns': [r'\b([A-Z][a-z]+[a-z]*\s+[a-z]+(?:\s+[a-z]+)*)\b|\b([A-Z][a-z]+\s+sp[p]?)\b'],
            'priority': 1
        },

        # Proteins, Enzymes, Molecular Components
        'PROTEIN': {
            'description': 'Proteins, enzymes, receptors, signaling molecules, antibodies',
            'examples': ['butyrate kinase', 'lipopolysaccharide', 'cytokine', 'chemokine', 'immunoglobulin', 'hemoglobin', 'collagen'],
            'patterns': [r'\b([a-z]+(?:kinase|receptor|factor|protein|enzyme|antibody))\b'],
            'priority': 3
        },

        # Metabolites, Compounds, Chemicals
        'CHEMICAL': {
            'description': 'Metabolites, SCFAs, drugs, compounds, biochemical substances',
            'examples': ['butyrate', 'propionate', 'acetate', 'lactate', 'lipopolysaccharide', 'glucose', 'amino acids', 'fatty acids', 'vitamins'],
            'patterns': [r'\b([a-z]+(?:ate|ine|ol|one|acid|lactate|butyrate|propionate|acetate|glucose))\b'],
            'priority': 4
        },

        # Diseases, Medical Conditions
        'DISEASE': {
            'description': 'Diseases, conditions, disorders, syndromes, clinical terms',
            'examples': ['ulcerative colitis', 'Crohn\'s disease', 'type 2 diabetes', 'inflammation', 'obesity', 'autoimmune disease', 'cancer'],
            'patterns': [r'\b([A-Z][a-z]*(?:osis|itis|emia| syndrome| disease| disorder| cancer))\b'],
            'priority': 5
        },

        # DNA/RNA, Genetic Material
        'DNA_RNA': {
            'description': 'Genetic material, sequences, nucleic acids, genes',
            'examples': ['16S rRNA', 'bacterial DNA', 'microbiome sequencing', 'RNA polymerase', 'mRNA', 'tRNA', 'mitochondrial DNA', 'plasmids'],
            'patterns': [r'\b(\d+S\s+rRNA)\b|\b([a-z]+\s+(?:DNA|RNA))\b'],
            'priority': 6
        },

        # Cell Types, Tissues
        'CELL_TYPE': {
            'description': 'Cell types, immune cells, tissue types, cellular components',
            'examples': ['macrophages', 'T-cells', 'dendritic cells', 'epithelial cells', 'stem cells', 'neurons', 'hepatocytes'],
            'patterns': [r'\b([a-z]+\s+cells?)\b'],
            'priority': 7
        },

        # Sample Collection, Transport, Storage (Wet Lab - Pre-processing)
        'SAMPLE_METHOD': {
            'description': 'Methods for sample collection, transport, storage, and DNA extraction',
            'examples': ['fecal sampling', 'swab collection', 'frozen at -80C', 'RNAlater', 'PowerSoil DNA Kit', 'bead beating', 'DNA extraction'],
            'patterns': [r'\b([a-z]+\s+(?:kit|extraction|collection|storage))\b'],
            'priority': 8
        },

        # Laboratory Methods & Sequencing (Wet Lab - Sequencing)
        'LAB_METHOD': {
            'description': 'Library preparation, PCR, sequencing platforms, and wet-lab techniques',
            'examples': ['Illumina MiSeq', '16S rRNA PCR', 'V4 region', 'library preparation', 'Nextera XT', 'Nanopore', 'shotgun sequencing', 'PCR amplification'],
            'patterns': [r'\b(Illumina\s+[A-Za-z0-9]+)\b|\b([A-Z][a-z]+\s+(?:sequencing|PCR))\b'],
            'priority': 9
        },

        # Data Analysis & Bioinformatics (Dry Lab)
        'DATA_ANALYSIS': {
            'description': 'Bioinformatics tools, software, databases, statistical methods, and QC',
            'examples': ['QIIME2', 'Mothur', 'DADA2', 'Silva database', 'GreenGenes', 'UniFrac', 'Bray-Curtis', 'PCA', 'random forest', 'quality control'],
            'patterns': [r'\b([A-Z]{3,})\b|\b([a-z]+(?:omics|pipeline|analysis))\b'],
            'priority': 10
        },

        # Genomics, Omics, Molecular Biology
        'GENOMICS': {
            'description': 'Genomics, transcriptomics, proteomics, metabolomics, omics technologies',
            'examples': ['genomics', 'transcriptomics', 'proteomics', 'metabolomics', 'microbiomics', 'epigenomics', 'single-cell sequencing'],
            'patterns': [r'\b([a-z]+(?:omics|sequencing|genome))\b'],
            'priority': 9
        },

        # Metabolic and Signaling Pathways (Phase 2 - PATHWAY type)
        'PATHWAY': {
            'description': 'Metabolic pathways, signaling pathways, biological processes, cascades',
            'examples': ['glycolysis', 'TCA cycle', 'Leloir pathway', 'MAPK signaling', 'Bifid shunt', 'Inflammasome activation', 'NF-κB signaling', 'butyrate synthesis'],
            'patterns': [r'\b([A-Z][a-z]+\s+(?:pathway|cycle|signaling|shunt|cascade))\b|\b([A-Z][a-z]+\s+synthesis)\b'],
            'priority': 3
        },

        # Experimental Methods (Phase 1 - EXPERIMENTAL_METHOD type)
        'EXPERIMENTAL_METHOD': {
            'description': 'Experimental techniques, laboratory methods, measurement techniques',
            'examples': ['Sequencing', 'Genome binning', 'DNA extraction', 'Metagenomics', 'qPCR', 'ELISA', 'Western blot', 'Chromatography', 'Mass spectrometry'],
            'patterns': [r'\b([A-Z][a-z]+(?:sequencing|extraction|binning|omics))\b|\b([A-Z][a-z]+\s+(?:PCR|blot|assay))\b'],
            'priority': 8
        },

        # Study Design (Phase 1 - STUDY_DESIGN type)
        'STUDY_DESIGN': {
            'description': 'Study designs, experimental groups, control groups, cohort types',
            'examples': ['Cross-sectional', 'Longitudinal', 'Case-control', 'Randomized controlled trial', 'Control group', 'Standard control', 'Placebo'],
            'patterns': [r'\b([A-Z][a-z]+(?:sectional|tional|control|randomized))\b|\b(Control\s+group|Standard\s+Control)\b'],
            'priority': 8
        },

        # Clinical, Medical, Healthcare Terms
        'CLINICAL': {
            'description': 'Clinical terms, medical procedures, treatments, healthcare',
            'examples': ['diagnosis', 'therapy', 'treatment', 'clinical trial', 'patient', 'symptoms', 'medication', 'surgery'],
            'patterns': [r'\b([a-z]+(?:therapy|treatment|clinical|medical|patient|diagnosis))\b'],
            'priority': 10
        }
    }

    # Chunking strategies
    CHUNK_SIZES = {
        'small': 2000,    # < 10k chars
        'medium': 3500,   # < 50k chars
        'large': 5000,    # < 100k chars
        'xlarge': 7000    # > 100k chars
    }

    OVERLAP_RATIOS = {
        'small': 0.1,     # 10% overlap
        'medium': 0.05,   # 5% overlap
        'large': 0.03,    # 3% overlap
        'xlarge': 0.02    # 2% overlap
    }

    # Model configurations
    MODEL_CONFIGS = {
        'phi3:mini': {
            'max_tokens': 2000,
            'temperature': 0.1,
            'timeout': 1800,
            'num_ctx': 4096
        },
        'mistral': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'qwen3:8b': {
            'max_tokens': 4000,
            'temperature': 0.1,
            'timeout': 600,
            'num_ctx': 8192
        },
        'qwen3:14b': {
            'max_tokens': 2000,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'qwen3:30b': {
            'max_tokens': 3000,
            'temperature': 0.1,
            'timeout': 180,
            'num_ctx': 16384
        },
        'Qwen/Qwen2.5-14B-Instruct': {
            'max_tokens': 2000,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'Qwen/Qwen3-8B': {
            'max_tokens': 2000,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'gemma3:12b': {
            'max_tokens': 8000,
            'temperature': 0.3,
            'timeout': 1200,
            'num_ctx': 16384
        },
        'biomistral-7B': {
            'max_tokens': 4000,
            'temperature': 0.1,
            'timeout': 600,
            'num_ctx': 8192
        },
        'deepseek-r1:8b': {
            'max_tokens': 8000,
            'temperature': 0.1,
            'timeout': 1200,
            'num_ctx': 8192
        },
        'glm-4': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'glm-4-6': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'glm-4-flash': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 128000
        },
        'glm-4-air': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 128000
        },
        'glm-4.6': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 3000,
            'num_ctx': 128000
        },
        'glm-4.7': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 600,
            'num_ctx': 128000
        },
        'claude-3-5-sonnet-20240620': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 200000
        }
    }

    @classmethod
    def get_chunk_size(cls, text_length: int) -> int:
        """Get optimal chunk size based on text length."""
        if text_length < 10000:
            return cls.CHUNK_SIZES['small']
        elif text_length < 50000:
            return cls.CHUNK_SIZES['medium']
        elif text_length < 100000:
            return cls.CHUNK_SIZES['large']
        else:
            return cls.CHUNK_SIZES['xlarge']

    @classmethod
    def get_overlap(cls, chunk_size: int) -> int:
        """Get optimal overlap based on chunk size."""
        if chunk_size <= cls.CHUNK_SIZES['small']:
            return int(chunk_size * cls.OVERLAP_RATIOS['small'])
        elif chunk_size <= cls.CHUNK_SIZES['medium']:
            return int(chunk_size * cls.OVERLAP_RATIOS['medium'])
        elif chunk_size <= cls.CHUNK_SIZES['large']:
            return int(chunk_size * cls.OVERLAP_RATIOS['large'])
        else:
            return int(chunk_size * cls.OVERLAP_RATIOS['xlarge'])

@dataclass
class PipelineConfig:
    """Main pipeline configuration."""
    default_model: str = "qwen3:8b"
    default_base_url: str = os.environ.get("LLM_BASE_URL", "http://localhost:11434")
    max_workers: int = 1  # Reduced to prevent rate limiting (sequential processing)
    max_entities: int = 200
    min_confidence: float = 0.6


@dataclass
class ValidationConfig:
    """Configuration for dual-model validation (Phase 5)."""
    extractor_model: str = "qwen3:32b"
    validator_model: str = "mistral"  # Different model for independent validation
    confidence_threshold: float = 0.8
    human_calibration_ratio: float = 0.1  # 10% for human review