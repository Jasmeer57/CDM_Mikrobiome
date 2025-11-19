"""
CDM Pipeline Configuration
"""

from typing import Dict, List
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

        # Genes, Genetic Markers
        'GENE': {
            'description': 'Gene names, genetic markers, gene families, transcription factors',
            'examples': ['IL6', 'TNF-alpha', 'TLR4', 'NF-kB', 'IFN-gamma', 'p53', 'BRCA1', 'STAT3', 'NOD2'],
            'patterns': [r'\b([A-Z]{2,}[0-9]*(?:-[a-z]+)?)\b'],
            'priority': 2
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

        # Bioinformatics Tools, Methods, Technologies
        'BIOINFO_TOOL': {
            'description': 'Bioinformatics tools, software, databases, analytical methods',
            'examples': ['BLAST', 'FASTA', 'GenBank', 'Qiime', 'MetaPhlAn', 'HUMAnN', 'shotgun sequencing', 'metagenomics', 'phylogenetic analysis'],
            'patterns': [r'\b([A-Z]{3,})\b|\b([a-z]+(?:omics|sequencing|analysis|pipeline))\b'],
            'priority': 8
        },

        # Genomics, Omics, Molecular Biology
        'GENOMICS': {
            'description': 'Genomics, transcriptomics, proteomics, metabolomics, omics technologies',
            'examples': ['genomics', 'transcriptomics', 'proteomics', 'metabolomics', 'microbiomics', 'epigenomics', 'single-cell sequencing'],
            'patterns': [r'\b([a-z]+(?:omics|sequencing|genome))\b'],
            'priority': 9
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
            'timeout': 300
        },
        'qwen3:8b': {
            'max_tokens': 4000,
            'temperature': 0.1,
            'timeout': 600
        },
        'qwen3:4b': {
            'max_tokens': 3000,
            'temperature': 0.2,
            'timeout': 450
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
    default_base_url: str = "http://localhost:11434"
    max_workers: int = 3
    max_entities: int = 200
    min_confidence: float = 0.6