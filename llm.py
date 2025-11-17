#!/usr/bin/env python3
"""
Comprehensive Biomedical Terminology Extractor v6.0
==================================================

ENHANCED VERSION: Extracts ALL biomedical terms including bioinformatics, molecules,
chemicals, organisms, species, and technical biomedical terms. Processes all files
in folder with minimum 50 terms per file.
"""

import os
import re
import json
import time
import requests
import argparse
import logging
import numpy as np
import faiss
from openai import OpenAI
from collections import defaultdict, Counter
from tqdm import tqdm
from thefuzz import fuzz
from sentence_transformers import SentenceTransformer, util
from typing import List, Dict, Set, Tuple, Optional
import warnings
import concurrent.futures
import hashlib
import pickle
from pathlib import Path
warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Core Configuration
INPUT_DIRECTORY = "/home/jkalra/thesis/papers_txt"
OUTPUT_FILE = "comprehensive_biomedical_terminology.json"
FAISS_INDEX_FILE = "corpus_index.faiss"
LOG_FILE = "extraction.log"
CACHE_DIR = "./cache/"
RESULTS_DIR = "./results/"

# Model Configuration
LLM_MODEL_NAME = "qwen3:30b"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Extraction Parameters - ENHANCED FOR MORE TERMS
TARGET_TERMS_MIN = 50  # Minimum 50 terms per file as requested
TARGET_TERMS_MAX = 200
TARGET_TERMS_OPTIMAL = 100

# Quality Thresholds (OPTIMIZED for comprehensive extraction)
MIN_CONFIDENCE_THRESHOLD = 0.05  # More lenient to capture more terms
MIN_SEMANTIC_ALIGNMENT = 0.03
MIN_QUALITY_SCORE = 0.03

# Deduplication Thresholds
FUZZY_SIMILARITY_THRESHOLD = 90
SEMANTIC_SIMILARITY_THRESHOLD = 0.92

# Processing Parameters
MAX_CHUNK_SIZE = 400  # Larger chunks for more context
CHUNK_OVERLAP = 200
RAG_RETRIEVAL_COUNT = 40
MAX_EXAMPLES_PER_TERM = 2
MAX_LLM_RETRIES = 3
DEFAULT_THREADS = 4 # Increased for faster processing on powerful hardware

# Quality Scoring Weights
WEIGHT_FREQUENCY = 0.25
WEIGHT_QUALITY = 0.35
WEIGHT_SEMANTIC = 0.40

# =============================================================================
# EXPANDED COMPREHENSIVE BIOMEDICAL VOCABULARY SYSTEM
# =============================================================================

# GREATLY EXPANDED Biomedical Categories
BIOMEDICAL_CATEGORIES = {
    # Taxonomic entities and organisms
    'taxonomic_ranks': {
        'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species', 'strain',
        'subspecies', 'subfamily', 'tribe', 'suborder', 'subclass', 'subphylum'
    },

    # Microorganisms (EXPANDED)
    'microorganisms': {
        'bacteria', 'archaea', 'fungi', 'virus', 'yeast', 'mold', 'protozoa', 'algae',
        'bacteroidetes', 'firmicutes', 'actinobacteria', 'proteobacteria', 'verrucomicrobia',
        'fusobacteria', 'tenericutes', 'spirochaetes', 'chloroflexi', 'planctomycetes',
        'ascomycota', 'basidiomycota', 'zygomycota', 'chytridiomycota', 'cyanobacteria',
        'mycoplasma', 'rickettsia', 'chlamydia', 'streptomyces', 'lactococcus'
    },

    # Bacterial genera (EXPANDED)
    'bacterial_genera': {
        'bacteroides', 'prevotella', 'faecalibacterium', 'bifidobacterium', 'lactobacillus',
        'clostridium', 'akkermansia', 'roseburia', 'ruminococcus', 'eubacterium', 'blautia',
        'dorea', 'coprococcus', 'anaerostipes', 'subdoligranulum', 'oscillibacter',
        'streptococcus', 'staphylococcus', 'escherichia', 'salmonella', 'listeria',
        'helicobacter', 'pseudomonas', 'bacillus', 'mycobacterium', 'campylobacter',
        'enterococcus', 'klebsiella', 'proteus', 'shigella', 'vibrio', 'yersinia'
    },

    # Eukaryotic organisms
    'eukaryotic_organisms': {
        'homo_sapiens', 'mus_musculus', 'rattus_norvegicus', 'drosophila_melanogaster',
        'caenorhabditis_elegans', 'saccharomyces_cerevisiae', 'arabidopsis_thaliana',
        'danio_rerio', 'xenopus_laevis', 'gallus_gallus', 'sus_scrofa', 'canis_lupus'
    },

    # Chemical compounds and metabolites (GREATLY EXPANDED)
    'chemicals_metabolites': {
        'short_chain_fatty_acids', 'scfa', 'butyrate', 'acetate', 'propionate', 'lactate',
        'bile_acids', 'tryptophan_metabolites', 'indole', 'choline', 'carnitine',
        'amino_acids', 'fatty_acids', 'vitamins', 'enzymes', 'hormones', 'neurotransmitters',
        'peptides', 'proteins', 'lipids', 'carbohydrates', 'nucleotides', 'steroids',
        'flavonoids', 'polyphenols', 'alkaloids', 'terpenes', 'glycosides',
        'glucose', 'fructose', 'sucrose', 'lactose', 'maltose', 'starch', 'cellulose',
        'cholesterol', 'triglycerides', 'phospholipids', 'prostaglandins', 'leukotrienes',
        'dopamine', 'serotonin', 'norepinephrine', 'gaba', 'glutamate', 'acetylcholine',
        'insulin', 'glucagon', 'cortisol', 'testosterone', 'estrogen', 'thyroxine'
    },

    # Molecular biology terms (EXPANDED)
    'molecular_biology': {
        'dna', 'rna', 'mrna', 'trna', 'rrna', 'nucleotide', 'gene', 'genome', 'transcriptome',
        'proteome', 'metabolome', 'chromosome', 'plasmid', 'transposon', 'operon', 'promoter',
        'enhancer', 'silencer', 'exon', 'intron', 'codon', 'anticodon', 'replication',
        'transcription', 'translation', 'expression', 'splicing', 'methylation', 'acetylation',
        'phosphorylation', 'ubiquitination', 'glycosylation', 'polymerase', 'ligase',
        'kinase', 'phosphatase', 'helicase', 'topoisomerase', 'nuclease', 'protease'
    },

    # Bioinformatics tools and methods (GREATLY EXPANDED)
    'bioinformatics': {
        'qiime', 'qiime2', 'mothur', 'dada2', 'vsearch', 'usearch', 'picrust', 'picrust2',
        'lefse', 'aldex2', 'deseq2', 'phyloseq', 'biom_format', 'kraken', 'metaphlan',
        'humann', 'eggnog', 'interproscan', 'blast', 'bowtie', 'bwa', 'samtools',
        'bedtools', 'gatk', 'plink', 'r', 'python', 'perl', 'java', 'c', 'cplusplus',
        'bioconductor', 'biopython', 'bioperl', 'ensembl', 'ncbi', 'uniprot', 'pdb',
        'sequence_alignment', 'multiple_sequence_alignment', 'phylogenetic_analysis',
        'gene_prediction', 'protein_structure_prediction', 'drug_design', 'cheminformatics'
    },

    # Sequencing and omics technologies (EXPANDED)
    'sequencing_omics': {
        '16s_rrna', '18s_rrna', 'its', 'illumina', 'nanopore', 'pacbio', 'sanger',
        'amplicon_sequencing', 'shotgun_sequencing', 'metagenomics', 'metatranscriptomics',
        'metaproteomics', 'metabolomics', 'genomics', 'transcriptomics', 'proteomics',
        'epigenomics', 'lipidomics', 'glycomics', 'multiomics', 'single_cell_sequencing',
        'spatial_transcriptomics', 'long_read_sequencing', 'short_read_sequencing',
        'rna_seq', 'chip_seq', 'atac_seq', 'whole_genome_sequencing', 'exome_sequencing'
    },

    # Statistical and computational methods (EXPANDED)
    'statistical_methods': {
        'alpha_diversity', 'beta_diversity', 'shannon_diversity', 'simpson_diversity',
        'chao1', 'ace', 'richness', 'evenness', 'faith_pd', 'phylogenetic_diversity',
        'pcoa', 'pca', 'nmds', 'permanova', 'anosim', 'unifrac', 'bray_curtis',
        'jaccard', 'weighted_unifrac', 'unweighted_unifrac', 'principal_coordinate_analysis',
        'correlation', 'regression', 'clustering', 'classification', 'machine_learning',
        'neural_networks', 'random_forest', 'svm', 'pca', 'tsne', 'umap', 'kmeans',
        'hierarchical_clustering', 'ward_linkage', 'kendall_correlation', 'pearson_correlation',
        'spearman_correlation', 't_test', 'anova', 'manova', 'chi_square', 'fisher_exact',
        'logistic_regression', 'cox_regression', 'kaplan_meier', 'survival_analysis'
    },

    # Medical and clinical terms (EXPANDED)
    'medical_clinical': {
        'disease', 'infection', 'inflammation', 'cancer', 'diabetes', 'obesity',
        'cardiovascular', 'neurological', 'autoimmune', 'allergy', 'asthma',
        'ibd', 'ibs', 'crohns', 'colitis', 'celiac', 'liver_disease', 'kidney_disease',
        'diagnosis', 'prognosis', 'treatment', 'therapy', 'drug', 'vaccine',
        'clinical_trial', 'cohort', 'case_control', 'randomized_controlled_trial',
        'hypertension', 'alzheimer', 'parkinson', 'arthritis', 'osteoporosis',
        'depression', 'anxiety', 'schizophrenia', 'bipolar_disorder', 'autism'
    },

    # Pharmaceuticals and drugs
    'pharmaceuticals': {
        'antibiotics', 'antivirals', 'antifungals', 'chemotherapy', 'immunotherapy',
        'biologics', 'small_molecules', 'generic_drugs', 'brand_name_drugs',
        'clinical_pharmacology', 'pharmacokinetics', 'pharmacodynamics',
        'drug_metabolism', 'drug_interactions', 'adverse_effects', 'side_effects'
    },

    # Laboratory methods and techniques (EXPANDED)
    'laboratory_methods': {
        'pcr', 'qpcr', 'rt_pcr', 'digital_pcr', 'electrophoresis', 'chromatography',
        'mass_spectrometry', 'nmr', 'microscopy', 'flow_cytometry', 'elisa',
        'western_blot', 'northern_blot', 'southern_blot', 'immunohistochemistry',
        'cell_culture', 'fermentation', 'extraction', 'purification', 'amplification',
        'cloning', 'sequencing', 'synthesis', 'crystallization', 'centrifugation',
        'spectrophotometry', 'fluorometry', 'luminescence', 'radioimmunoassay'
    },

    # Biomedical imaging techniques
    'biomedical_imaging': {
        'mri', 'ct_scan', 'pet_scan', 'ultrasound', 'x_ray', 'microscopy',
        'confocal_microscopy', 'electron_microscopy', 'fluorescence_microscopy',
        'endoscopy', 'colonoscopy', 'bronchoscopy', 'angiography', 'mammography'
    },

    # Cellular and molecular processes
    'cellular_processes': {
        'cell_division', 'apoptosis', 'necrosis', 'autophagy', 'differentiation',
        'proliferation', 'migration', 'invasion', 'metastasis', 'angiogenesis',
        'signal_transduction', 'cell_cycle', 'dna_repair', 'protein_synthesis',
        'membrane_transport', 'endocytosis', 'exocytosis', 'phagocytosis'
    },

    # Anatomy and physiology terms
    'anatomy_physiology': {
        'gastrointestinal_tract', 'cardiovascular_system', 'nervous_system',
        'respiratory_system', 'urinary_system', 'reproductive_system',
        'endocrine_system', 'immune_system', 'musculoskeletal_system',
        'integumentary_system', 'homeostasis', 'metabolism', 'respiration',
        'circulation', 'digestion', 'neural_transmission', 'hormonal_regulation'
    }
}

# Create flattened set of all biomedical terms
ALL_BIOMEDICAL_TERMS = set()
for category_terms in BIOMEDICAL_CATEGORIES.values():
    ALL_BIOMEDICAL_TERMS.update(category_terms)

# Extended stopwords for academic filtering
ACADEMIC_STOPWORDS = {
    'abstract', 'introduction', 'discussion', 'conclusion', 'results', 'methods',
    'materials', 'supplementary', 'acknowledgement', 'references', 'bibliography',
    'author', 'contribution', 'figure', 'table', 'manuscript', 'review', 'article',
    'publication', 'journal', 'editor', 'license', 'copyright', 'permission',
    'doi', 'pmid', 'pmcid', 'url', 'website', 'http', 'https', 'www',
    'institute', 'university', 'department', 'laboratory', 'funding', 'grant',
    'competing_interest', 'conflict', 'disclosure', 'ethics', 'consent',
    'approval', 'committee', 'institutional', 'review', 'board'
}

# LLM artifacts and conversational patterns to filter
LLM_ARTIFACTS = {
    'the_text', 'the_given_text', 'the_actual_text', 'mentioned_above', 'as_follows',
    'no_general_terms', 'specific_terms_only', 'avoid_general', 'so_compiling_these',
    'user_said', 'if_mentioned', 'avoided', 'so_avoid', 'categories_avoided',
    'user_requested', 'focusing_on', 'prioritizing', 'use_snake_case_note'
}

# Generic terms to exclude
GENERIC_TERMS = {
    'age_related_composition', 'age_related_shifts', 'adult_like_configuration',
    'country_based_differences', 'sequential_changes', 'age_related_clusters',
    'age_based_clustering', 'age_related_groups', 'microbiota_trends_over_age'
}

# =============================================================================
# ENHANCED PROMPT ENGINEERING FOR ALL BIOMEDICAL TERMS
# =============================================================================

SYSTEM_CONTEXT = """You are a comprehensive biomedical terminology extractor. Extract ALL concrete scientific terms from the text including bioinformatics, molecules, chemicals, organisms, species, and technical biomedical terms.

CRITICAL RULES:
1. Extract ALL biomedical terms: bioinformatics tools, molecules, chemicals, organisms, species, technical terms
2. Include terms from ALL biomedical domains: molecular biology, biochemistry, genetics, bioinformatics, pharmacology, etc.
3. NEVER extract your own instructions, notes, or conversational phrases
4. ONLY extract terms that would be valid entries in a biomedical ontology
5. Be comprehensive - extract any term that appears biomedical or technical in nature

VALID CATEGORIES TO EXTRACT:
- ALL biological entities (organisms, species, genera, phyla)
- ALL chemical compounds, metabolites, molecules
- ALL molecular biology terms (genes, proteins, pathways, enzymes)
- ALL bioinformatics tools, methods, and pipelines
- ALL sequencing technologies and omics platforms
- ALL statistical and computational methods
- ALL medical, clinical, and pharmaceutical terms
- ALL laboratory methods and techniques
- ALL anatomical and physiological terms
- ANY technical biomedical term

OUTPUT: Comma-separated snake_case terms ONLY. No explanations, no notes."""

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(level=logging.INFO):
    """Configure logging with file and console handlers."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, mode='w'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# =============================================================================
# CACHE MANAGEMENT SYSTEM
# =============================================================================

def setup_cache():
    """Initialize cache directory."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    logger.info(f"✅ Cache directory initialized: {CACHE_DIR}")

def get_cache_key(filename: str, pass_num: int, model: str) -> str:
    """Generate cache key for LLM responses."""
    content = f"{filename}_pass{pass_num}_{model}"
    return hashlib.md5(content.encode()).hexdigest()

def save_to_cache(cache_key: str, data: str):
    """Save LLM response to cache."""
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({"response": data, "timestamp": time.time()}, f)
    except Exception as e:
        logger.warning(f"Could not save to cache: {e}")

def load_from_cache(cache_key: str) -> Optional[str]:
    """Load LLM response from cache."""
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                if time.time() - cached_data["timestamp"] < 86400:
                    return cached_data["response"]
    except Exception as e:
        logger.warning(f"Could not load from cache: {e}")
    return None

# =============================================================================
# ENHANCED TEXT PREPROCESSING
# =============================================================================

def enhanced_preprocess_text(text: str) -> str:
    """Advanced text preprocessing with noise reduction."""

    # Remove boilerplate sections
    patterns = [
        r"(\n\s*(?:References|Bibliography|Acknowledgments?|Author[s]? Contribution[s]?|Funding|Competing [Ii]nterest[s]?)\s*.*?)(?=\n\s*\w|\Z)",
        r"(\n\s*(?:Supplementary [Mm]aterial|Additional [Ff]ile[s]?|Supporting [Ii]nformation)\s*.*?)(?=\n\s*\w|\Z)",
        r"(\n\s*(?:Ethics [Ss]tatement|Consent|IRB [Aa]pproval)\s*.*?)(?=\n\s*\w|\Z)",
        r"(\n\s*(?:Abbreviations|Data [Aa]vailability)\s*.*?)(?=\n\s*\w|\Z)"
    ]

    for pattern in patterns:
        text = re.sub(pattern, "\n", text, flags=re.DOTALL | re.IGNORECASE)

    # Remove citations and references
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\([^)]*?\d{4}[^)]*?\)', '', text)

    # Remove page numbers and headers
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)

    # Clean whitespace
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    text = re.sub(r'\s+', ' ', text)

    return text.strip()

# =============================================================================
# LLM CLIENT AND UTILITIES
# =============================================================================

def setup_llm_client():
    """Initialize OpenAI client for Ollama."""
    try:
        client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        logger.info("✅ LLM client configured for Ollama")
        return client
    except Exception as e:
        logger.error(f"❌ Error setting up LLM client: {e}")
        raise

def load_stopwords():
    """Load stopwords with fallback."""
    try:
        url = "https://gist.githubusercontent.com/sebleier/554280/raw/7e0e4a1ce04c2bb7bd41089c9821dbcf6d0c786c/NLTK's%2520list%2520of%2520english%2520stopwords"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        external_stopwords = set(response.text.strip().split('\n'))
        logger.info(f"  - Loaded {len(external_stopwords)} external stopwords")
        # Combine all stopword sets
        all_stopwords = external_stopwords.union(ACADEMIC_STOPWORDS).union(LLM_ARTIFACTS).union(GENERIC_TERMS)
        logger.info(f"  - Total stopwords: {len(all_stopwords)}")
        return all_stopwords
    except Exception as e:
        logger.warning(f"  - Could not load external stopwords: {e}")
        return ACADEMIC_STOPWORDS.union(LLM_ARTIFACTS).union(GENERIC_TERMS)

# =============================================================================
# EXPANDED TERM VALIDATION FOR ALL BIOMEDICAL TERMS
# =============================================================================

def is_biomedical_relevant_term(term: str) -> bool:
    """Check if term is relevant to biomedical research (EXPANDED SCOPE)."""
    term_lower = term.lower()

    # Direct matches with biomedical vocabulary
    if term_lower in ALL_BIOMEDICAL_TERMS:
        return True

    # GREATLY EXPANDED pattern matching for biomedical terms
    biomedical_patterns = [
        r'\b\w*bacter\w*\b',           # bacterial names
        r'\b\w*coccus\b',              # coccus endings
        r'\b\w*aceae\b',               # family endings
        r'\b\w*ales\b',                # order endings
        r'\b\w*idae\b',                # subfamily endings
        r'\b\w*(diversity|richness|evenness)\b', # diversity metrics
        r'\b\w*seq\w*\b',              # sequencing terms
        r'\b\w*(microbiome|microbiota|microbial)\b', # core terms
        r'\b\w*phyla\b',               # phylum terms
        r'\b\w*genus\b',               # genus terms
        r'\b\w*species\b',             # species terms
        r'\b\w*protein\b',             # protein terms
        r'\b\w*enzyme\b',              # enzyme terms
        r'\b\w*gene\b',                # gene terms
        r'\b\w*pathway\b',             # pathway terms
        r'\b\w*metabolit\w*\b',        # metabolite terms
        r'\b\w*compound\b',            # compound terms
        r'\b\w*analysis\b',            # analysis terms
        r'\b\w*sequencing\b',          # sequencing terms
        r'\b\w*clustering\b',          # clustering terms
        r'\b\w*correlation\b',         # correlation terms
        r'\b\w*abundance\b',           # abundance terms
        r'\b\w*composition\b',         # composition terms
        r'\b\w*function\b',            # function terms
        r'\b\w*annotation\b',          # annotation terms
        r'\b\w*taxonom\w*\b',          # taxonomy terms
        r'\b\w*phylogen\w*\b',         # phylogeny terms
        r'\b\w*metagenom\w*\b',        # metagenomics terms
        r'\b\w*transcriptom\w*\b',     # transcriptomics terms
        r'\b\w*proteom\w*\b',          # proteomics terms
        r'\b\w*metabolom\w*\b',        # metabolomics terms
        r'\b\w*bioinformat\w*\b',      # bioinformatics terms
        r'\b\w*cheminformat\w*\b',     # cheminformatics terms
        r'\b\w*pharmac\w*\b',          # pharmacology terms
        r'\b\w*therap\w*\b',           # therapy terms
        r'\b\w*diagnos\w*\b',          # diagnosis terms
        r'\b\w*clinica\w*\b',          # clinical terms
        r'\b\w*molecul\w*\b',          # molecular terms
        r'\b\w*cellula\w*\b',          # cellular terms
        r'\b\w*genetic\w*\b',          # genetic terms
        r'\b\w*genomic\w*\b',          # genomic terms
        r'\b\w*structur\w*\b',         # structural terms
        r'\b\w*computational\w*\b',    # computational terms
        r'\b\w*statistical\w*\b',      # statistical terms
        r'\b\w*laboratory\w*\b',       # laboratory terms
        r'\b\w*experimental\w*\b',     # experimental terms
    ]

    for pattern in biomedical_patterns:
        if re.search(pattern, term_lower):
            return True

    # EXPANDED Chemical and molecular patterns
    chemical_patterns = [
        r'\b\w*acid\b',                # acid compounds
        r'\b\w*ate\b',                 # compound endings
        r'\b\w*ose\b',                 # sugar endings
        r'\b\w*ol\b',                  # alcohol endings
        r'\b\w*one\b',                 # ketone endings
        r'\b\w*ase\b',                 # enzyme endings
        r'\b\w*ium\b',                 # element endings
        r'\b\w*ide\b',                 # compound endings
        r'\b\w*ine\b',                 # amine/alkaloid endings
    ]

    for pattern in chemical_patterns:
        if re.search(pattern, term_lower):
            return True

    return False

def strict_term_cleaning(term: str, stopwords: Set[str]) -> Optional[str]:
    """Term cleaning that filters out artifacts but keeps biomedical terms."""
    if not isinstance(term, str) or len(term) < 2:
        return None

    # Initial cleaning
    cleaned = term.lower().strip()

    # Enhanced normalization
    greek_replacements = {
        'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta',
        'ε': 'epsilon', 'ζ': 'zeta', 'η': 'eta', 'θ': 'theta',
        'ι': 'iota', 'κ': 'kappa', 'λ': 'lambda', 'μ': 'mu',
        'ν': 'nu', 'ξ': 'xi', 'ο': 'omicron', 'π': 'pi',
        'ρ': 'rho', 'σ': 'sigma', 'τ': 'tau', 'υ': 'upsilon',
        'φ': 'phi', 'χ': 'chi', 'ψ': 'psi', 'ω': 'omega'
    }

    for greek_char, replacement in greek_replacements.items():
        cleaned = cleaned.replace(greek_char, replacement)

    # Auto-expand known abbreviations
    abbreviation_expansions = {
        'fmt': 'fecal_microbiota_transplantation',
        'scfa': 'short_chain_fatty_acids',
        'otu': 'operational_taxonomic_unit',
        'asv': 'amplicon_sequence_variant',
        'pcoa': 'principal_coordinate_analysis',
        'nmds': 'non_metric_multidimensional_scaling',
        'pcr': 'polymerase_chain_reaction',
        'dna': 'deoxyribonucleic_acid',
        'rna': 'ribonucleic_acid',
        'mrna': 'messenger_rna',
        'trna': 'transfer_rna',
        'rrna': 'ribosomal_rna',
        'pdb': 'protein_data_bank',
        'ncbi': 'national_center_for_biotechnology_information',
        'blast': 'basic_local_alignment_search_tool'
    }

    if cleaned in abbreviation_expansions:
        cleaned = abbreviation_expansions[cleaned]

    # Remove problematic prefixes/suffixes
    prefix_patterns = [
        r'^(such_as|e_g|eg|for_example|including|like)[\s_]+',
        r'^(the|a|an|this|these|that|those)[\s_]+',
        r'^(and|or|but|however|therefore|thus)[\s_]+',
        r'[\s_]+(etc|et_al|and_so_on|respectively)$'
    ]

    for pattern in prefix_patterns:
        cleaned = re.sub(pattern, '', cleaned)

    # Convert to snake_case
    cleaned = re.sub(r'[\s\-\.]+', '_', cleaned)
    cleaned = re.sub(r'[^\w_]', '', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')

    if not cleaned or len(cleaned) < 2:
        return None

    # STRICTER validation checks
    parts = cleaned.split('_')

    # Reject problematic patterns
    reject_patterns = [
        r'^\d+$',                      # pure numbers
        r'^(figure|table|fig|tab)_?\d*$', # figure references
        r'^[a-z]{1}$',                 # single letters
        r'.*conversational.*',         # conversational terms
        r'.*instructional.*',          # instructional terms
        r'.*procedural.*',             # procedural terms
        r'.*note.*',                   # note terms
        r'.*maybe.*',                  # uncertain terms
        r'.*seems.*',                  # uncertain terms
        r'.*might.*',                  # uncertain terms
        r'.*probably.*',               # uncertain terms
    ]

    for pattern in reject_patterns:
        if re.match(pattern, cleaned):
            return None

    # Reject if in stopwords or artifacts
    if cleaned in stopwords or cleaned in LLM_ARTIFACTS:
        return None

    # Reject conversational patterns
    conversational_indicators = [
        'so_', 'user_', 'mentioned_', 'if_', 'avoided_', 'note_', 'conversational_',
        'looking_', 'rules_', 'avoid_', 'sample_', 'text_', 'given_', 'actual_',
        'focusing_', 'prioritizing_', 'compiling_', 'categories_', 'requested_'
    ]

    if any(cleaned.startswith(indicator) for indicator in conversational_indicators):
        return None

    # Must contain at least one letter
    if not re.search(r'[a-z]', cleaned):
        return None

    # Must be biomedical relevant - MORE LENIENT for comprehensive extraction
    if not is_biomedical_relevant_term(cleaned):
        # Allow some terms that might be biomedical but didn't match patterns
        if len(parts) >= 2 and any(len(part) > 3 for part in parts):
            return cleaned  # Allow multi-word terms that might be valid
        return None

    return cleaned

# =============================================================================
# LLM INTERACTION WITH RETRY LOGIC AND CACHING
# =============================================================================
def save_embeddings_and_index(terms: List[str], embed_model: SentenceTransformer, output_dir: str = RESULTS_DIR):
    """Save term embeddings as .npy and create FAISS index."""
    logger.info("💾 Saving embeddings and FAISS index...")

    try:
        # Create embeddings with progress bar
        logger.info(f"  - Creating embeddings for {len(terms)} terms...")
        embeddings = embed_model.encode(terms, convert_to_tensor=False, show_progress_bar=True)

        # Save embeddings as .npy file
        npy_file = os.path.join(output_dir, "term_embeddings.npy")
        np.save(npy_file, embeddings)
        logger.info(f"✅ Embeddings saved to: {npy_file}")

        # Create and save FAISS index
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatIP(dimension)  # Inner product index for cosine similarity

        # Normalize embeddings for cosine similarity
        embeddings_normalized = embeddings.astype(np.float32)
        faiss.normalize_L2(embeddings_normalized)
        index.add(embeddings_normalized)

        # Save FAISS index
        faiss_file = os.path.join(output_dir, FAISS_INDEX_FILE)
        faiss.write_index(index, faiss_file)
        logger.info(f"✅ FAISS index saved to: {faiss_file}")

        # Save term mapping
        term_mapping_file = os.path.join(output_dir, "term_mapping.json")
        term_mapping = {i: term for i, term in enumerate(terms)}
        with open(term_mapping_file, 'w', encoding='utf-8') as f:
            json.dump(term_mapping, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ Term mapping saved to: {term_mapping_file}")

        # Log statistics
        logger.info(f"📊 Embedding stats: {len(terms)} terms, {dimension} dimensions, "
                    f"index size: {index.ntotal} vectors")

        return npy_file, faiss_file, term_mapping_file

    except Exception as e:
        logger.error(f"❌ Failed to save embeddings and index: {e}")
        raise

def validate_embeddings(npy_file: str, faiss_file: str, mapping_file: str) -> bool:
    """Validate that embedding files were created correctly."""
    try:
        # Check if files exist
        if not all(os.path.exists(f) for f in [npy_file, faiss_file, mapping_file]):
            logger.error("❌ One or more embedding files are missing")
            return False

        # Load and validate embeddings
        embeddings = np.load(npy_file)
        index = faiss.read_index(faiss_file)

        with open(mapping_file, 'r') as f:
            mapping = json.load(f)

        # Check consistency
        if len(embeddings) != len(mapping) or len(embeddings) != index.ntotal:
            logger.error(f"❌ Inconsistent counts: embeddings={len(embeddings)}, mapping={len(mapping)}, index={index.ntotal}")
            return False

        logger.info(f"✅ Embeddings validated: {len(embeddings)} terms, {embeddings.shape[1]} dimensions")
        return True

    except Exception as e:
        logger.error(f"❌ Embedding validation failed: {e}")
        return False

def call_llm_with_retry(client: OpenAI, prompt: str, model: str,
                        temperature: float = 0.1, max_retries: int = 3,
                        cache_key: Optional[str] = None) -> Optional[str]:
    """Call LLM with exponential backoff retry logic and caching."""

    # Check cache first
    if cache_key:
        cached_response = load_from_cache(cache_key)
        if cached_response:
            logger.info("    - Using cached LLM response")
            return cached_response

    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=4000,
                stream=True
            )

            response_content = ""
            for chunk in completion:
                if chunk.choices[0].delta.content:
                    response_content += chunk.choices[0].delta.content

            response_content = response_content.strip()

            # Cache the response
            if cache_key and response_content:
                save_to_cache(cache_key, response_content)

            return response_content

        except Exception as e:
            logger.warning(f"    - LLM call attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error(f"    - All LLM attempts failed")
                return None
    return None

def parse_llm_response(response: str, stopwords: Set[str]) -> List[str]:
    """Parse and validate LLM response with filtering."""
    if not response:
        return []

    # Clean response
    response = re.sub(r'<[^>]+>', '', response)
    response = re.sub(r'^.*?:', '', response)
    response = re.sub(r'[\n\r]+', ',', response)

    # Extract terms
    raw_terms = [t.strip().strip('"\'') for t in response.split(',')]

    valid_terms = []
    for term in raw_terms:
        if not term or len(term) > 100:
            continue

        # Skip only obvious sentences
        if any(punct in term for punct in ['.', '?', '!']) or len(term.split()) > 8:
            continue

        cleaned = strict_term_cleaning(term, stopwords)
        if cleaned:
            valid_terms.append(cleaned)

    return valid_terms

# =============================================================================
# COMPREHENSIVE MULTI-PASS TERM EXTRACTION FOR ALL BIOMEDICAL TERMS
# =============================================================================

def extract_terms_comprehensive(text: str, filename: str, client: OpenAI, model: str,
                                stopwords: Set[str], embed_model: SentenceTransformer,
                                target_terms_min: int) -> List[str]:
    """
    Comprehensive multi-pass term extraction for ALL biomedical terms.
    """
    logger.info(f"  - Comprehensive biomedical extraction for {filename}")
    all_terms = set()

    # -------------------------------------------------------------------------
    # PASS 1: ALL BIOLOGICAL ENTITIES, ORGANISMS, AND SPECIES
    # -------------------------------------------------------------------------
    pass1_prompt = f"""{SYSTEM_CONTEXT}

EXTRACTION GOAL: Extract ALL biological entities, organisms, species, and taxonomic terms from the text.

FOCUS ON:
- ALL bacterial, archaeal, fungal genera and species mentioned
- ALL viral strains and types mentioned
- ALL eukaryotic organisms mentioned (human, mouse, rat, etc.)
- ALL taxonomic ranks and classifications mentioned
- ANY organism names that appear in the text
- Species names, genus names, family names, etc.

IMPORTANT: Extract ALL biological entities you find, not just microbiome-related.

TEXT:
{text[:8000]}"""

    cache_key1 = get_cache_key(filename, 1, model)
    response = call_llm_with_retry(client, pass1_prompt, model, cache_key=cache_key1)
    if response:
        terms = parse_llm_response(response, stopwords)
        all_terms.update(terms)
        logger.info(f"    - Pass 1 (Biological Entities): {len(terms)} terms extracted")

    # -------------------------------------------------------------------------
    # PASS 2: ALL CHEMICALS, MOLECULES, METABOLITES, AND COMPOUNDS
    # -------------------------------------------------------------------------
    pass2_prompt = f"""{SYSTEM_CONTEXT}

EXTRACTION GOAL: Extract ALL chemical compounds, metabolites, molecules, and biochemical terms from the text.

FOCUS ON:
- ALL metabolites mentioned (SCFAs, bile acids, amino acids, lipids, etc.)
- ALL drugs, pharmaceuticals, compounds mentioned
- ALL proteins, enzymes, hormones, neurotransmitters mentioned
- ALL genes, DNA, RNA molecules mentioned
- ALL metabolic pathways and processes mentioned
- ANY chemical or molecular entity that appears in the text
- Small molecules, large molecules, organic compounds, inorganic compounds

IMPORTANT: Extract ALL chemical and molecular terms you find.

TEXT:
{text[5000:13000]}"""

    cache_key2 = get_cache_key(filename, 2, model)
    response = call_llm_with_retry(client, pass2_prompt, model, cache_key=cache_key2)
    if response:
        terms = parse_llm_response(response, stopwords)
        all_terms.update(terms)
        logger.info(f"    - Pass 2 (Chemicals/Molecules): {len(terms)} additional terms")

    # -------------------------------------------------------------------------
    # PASS 3: ALL BIOINFORMATICS, COMPUTATIONAL, AND TECHNICAL METHODS
    # -------------------------------------------------------------------------
    pass3_prompt = f"""{SYSTEM_CONTEXT}

EXTRACTION GOAL: Extract ALL bioinformatics tools, computational methods, and technical approaches from the text.

FOCUS ON:
- ALL sequencing platforms and methods mentioned
- ALL bioinformatics tools, software, and pipelines mentioned
- ALL statistical and computational methods mentioned
- ALL machine learning and AI approaches mentioned
- ALL database and resource names mentioned
- ANY computational or technical approach that appears in the text
- Programming languages, algorithms, data structures mentioned

IMPORTANT: Extract ALL bioinformatics and computational terms you find.

TEXT:
{text[10000:18000]}"""

    cache_key3 = get_cache_key(filename, 3, model)
    response = call_llm_with_retry(client, pass3_prompt, model, cache_key=cache_key3)
    if response:
        terms = parse_llm_response(response, stopwords)
        all_terms.update(terms)
        logger.info(f"    - Pass 3 (Bioinformatics/Methods): {len(terms)} additional terms")

    # -------------------------------------------------------------------------
    # PASS 4: ALL MEDICAL, CLINICAL, AND PHARMACEUTICAL TERMS
    # -------------------------------------------------------------------------
    pass4_prompt = f"""{SYSTEM_CONTEXT}

EXTRACTION GOAL: Extract ALL medical, clinical, pharmaceutical, and disease-related terms from the text.

FOCUS ON:
- ALL diseases, disorders, and medical conditions mentioned
- ALL drugs, pharmaceuticals, and treatments mentioned
- ALL clinical procedures and diagnostic methods mentioned
- ALL anatomical terms and body systems mentioned
- ALL physiological processes and pathways mentioned
- ANY medical or clinical term that appears in the text

IMPORTANT: Extract ALL medical and clinical terms you find.

TEXT:
{text[15000:23000]}"""

    cache_key4 = get_cache_key(filename, 4, model)
    response = call_llm_with_retry(client, pass4_prompt, model, cache_key=cache_key4)
    if response:
        terms = parse_llm_response(response, stopwords)
        all_terms.update(terms)
        logger.info(f"    - Pass 4 (Medical/Clinical): {len(terms)} additional terms")

    # -------------------------------------------------------------------------
    # PASS 5: CATCH-ALL FOR ANY MISSING BIOMEDICAL TERMS
    # -------------------------------------------------------------------------
    if len(all_terms) < target_terms_min:
        pass5_prompt = f"""{SYSTEM_CONTEXT}

EXTRACTION GOAL: Extract ANY remaining biomedical terms from ALL categories that haven't been captured yet.

LOOK FOR:
- ANY scientific term related to biology, medicine, chemistry, biochemistry
- ANY technical term mentioned in the text
- ANY domain-specific terminology that appears biomedical
- ANY term that could be part of a biomedical ontology
- Laboratory techniques, experimental methods, analytical approaches
- ANY term from biomedical research that you haven't extracted yet

CRITICAL: Extract comprehensively to reach at least {target_terms_min} terms per file.

TERMS ALREADY EXTRACTED (don't repeat these):
{', '.join(list(all_terms)[:30])}

TEXT:
{text[20000:28000]}"""

        cache_key5 = get_cache_key(filename, 5, model)
        response = call_llm_with_retry(client, pass5_prompt, model, cache_key=cache_key5)
        if response:
            terms = parse_llm_response(response, stopwords)
            all_terms.update(terms)
            logger.info(f"    - Pass 5 (Catch-all): {len(terms)} additional terms")

        # If still below minimum, do one more aggressive pass
    if len(all_terms) < target_terms_min:
        logger.info(f"    - Only {len(all_terms)} terms extracted, doing aggressive extraction")
        # Use remaining text for one more pass
        remaining_text = text[25000:35000] if len(text) > 35000 else text[20000:30000]
        pass6_prompt = f"""{SYSTEM_CONTEXT}

EXTRACTION GOAL: AGGRESSIVELY extract ANY biomedical terms to reach minimum {target_terms_min} terms.
BE VERY INCLUSIVE:
- Extract ANY term that sounds scientific, technical, or biomedical
- Include method names, technique names, approach names
- Include any compound, molecule, or chemical mentioned
- Include any organism, species, or biological entity
- Include any computational, statistical, or analytical method
- Include any medical, clinical, or pharmaceutical term

CRITICAL: We need at least {target_terms_min} terms total. Be comprehensive.

TEXT:
{remaining_text}"""

        cache_key6 = get_cache_key(filename, 6, model)
        response = call_llm_with_retry(client, pass6_prompt, model, temperature=0.3, cache_key=cache_key6)
        if response:
            terms = parse_llm_response(response, stopwords)
            all_terms.update(terms)
            logger.info(f"    - Pass 6 (Aggressive): {len(terms)} additional terms")

    return list(all_terms)

# =============================================================================
# SEMANTIC ALIGNMENT SCORING
# =============================================================================

def calculate_semantic_alignment_score(term: str, embed_model: SentenceTransformer) -> float:
    """Calculate semantic alignment with biomedical vocabulary."""
    if not hasattr(calculate_semantic_alignment_score, 'core_embeddings'):
        core_terms = list(ALL_BIOMEDICAL_TERMS)
        calculate_semantic_alignment_score.core_embeddings = embed_model.encode(
            core_terms, convert_to_tensor=True, show_progress_bar=False
        )
        calculate_semantic_alignment_score.core_terms = core_terms

    try:
        term_embedding = embed_model.encode([term], convert_to_tensor=True)
        similarities = util.cos_sim(term_embedding, calculate_semantic_alignment_score.core_embeddings)
        max_similarity = similarities.max().item()

        if max_similarity > 0.6:
            return max_similarity
        elif max_similarity > 0.4:
            return max_similarity * 0.8
        else:
            return max_similarity * 0.6

    except Exception as e:
        logger.warning(f"Semantic alignment calculation failed for '{term}': {e}")
        return 0.3

# =============================================================================
# QUALITY SCORING
# =============================================================================

def calculate_term_quality_score(term: str) -> float:
    """Quality scoring for terms."""
    score = 0.5

    term_lower = term.lower()
    parts = term.split('_')

    # Core vocabulary bonus
    if term_lower in ALL_BIOMEDICAL_TERMS:
        score += 0.3

    # Domain relevance bonus
    if is_biomedical_relevant_term(term):
        score += 0.2

    # Multi-word compound bonus
    if len(parts) in [2, 3, 4]:
        score += 0.15

    # Length optimization
    term_len = len(term)
    if 4 <= term_len <= 25:
        score += 0.1

    # Pattern bonuses
    biomedical_patterns = [
        ('aceae', 0.15), ('ales', 0.1), ('idae', 0.1), ('bacter', 0.15),
        ('coccus', 0.15), ('myces', 0.1), ('virus', 0.1), ('protein', 0.1),
        ('enzyme', 0.1), ('gene', 0.1), ('pathway', 0.1), ('metabolit', 0.1),
        ('sequencing', 0.1), ('analysis', 0.05), ('diversity', 0.1),
        ('bioinformat', 0.1), ('computational', 0.1), ('statistical', 0.1),
        ('clinical', 0.1), ('medical', 0.1), ('pharmaceutical', 0.1)
    ]

    for pattern, bonus in biomedical_patterns:
        if pattern in term_lower:
            score += bonus
            break

    return min(max(score, 0.1), 1.0)

# =============================================================================
# DEDUPLICATION AND FINAL PROCESSING
# =============================================================================

def fuzzy_deduplicate_terms(terms: List[str], threshold: int = FUZZY_SIMILARITY_THRESHOLD) -> Tuple[List[str], Dict[str, Set[str]]]:
    """Fuzzy string deduplication."""
    logger.info(f"  - Fuzzy deduplication (threshold={threshold})")

    canonical_terms = []
    aliases_map = defaultdict(set)
    processed = set()

    terms_with_scores = [(term, calculate_term_quality_score(term)) for term in terms]
    terms_with_scores.sort(key=lambda x: x[1], reverse=True)
    sorted_terms = [term for term, _ in terms_with_scores]

    for term in sorted_terms:
        if term in processed:
            continue

        similar_terms = [term]
        for other_term in sorted_terms:
            if other_term != term and other_term not in processed:
                ratio_sim = fuzz.ratio(term, other_term)
                partial_sim = fuzz.partial_ratio(term, other_term)
                token_sim = fuzz.token_set_ratio(term, other_term)

                max_similarity = max(ratio_sim, partial_sim, token_sim)
                if max_similarity >= threshold:
                    similar_terms.append(other_term)

        canonical = max(similar_terms, key=lambda t: (
            t.lower() in ALL_BIOMEDICAL_TERMS,
            calculate_term_quality_score(t),
            len(t),
        ))

        canonical_terms.append(canonical)
        for similar_term in similar_terms:
            if similar_term != canonical:
                aliases_map[canonical].add(similar_term)
            processed.add(similar_term)

    logger.info(f"    - Fuzzy dedup: {len(terms)} → {len(canonical_terms)} terms")
    return canonical_terms, aliases_map

def get_optimized_chunks(directory: str) -> Tuple[List[str], List[str]]:
    """Create optimized overlapping chunks."""
    logger.info("  - Creating optimized text chunks")

    all_chunks = []
    chunk_to_filename = []

    txt_files = [f for f in os.listdir(directory) if f.endswith('.txt')]

    for filename in tqdm(txt_files, desc="Processing documents"):
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = enhanced_preprocess_text(f.read())

            sentences = re.split(r'(?<=[.!?])\s+', text)
            current_chunk = []
            current_length = 0

            for sentence in sentences:
                words = sentence.split()
                sentence_length = len(words)

                if current_length + sentence_length > MAX_CHUNK_SIZE and current_chunk:
                    chunk_text = ' '.join(current_chunk)
                    if len(chunk_text.strip()) > 50:
                        all_chunks.append(chunk_text)
                        chunk_to_filename.append(filename)

                    overlap_sentences = current_chunk[-2:] if len(current_chunk) > 2 else current_chunk
                    current_chunk = overlap_sentences + [sentence]
                    current_length = sum(len(s.split()) for s in current_chunk)
                else:
                    current_chunk.append(sentence)
                    current_length += sentence_length

            if current_chunk:
                chunk_text = ' '.join(current_chunk)
                if len(chunk_text.strip()) > 50:
                    all_chunks.append(chunk_text)
                    chunk_to_filename.append(filename)

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")

    logger.info(f"  - Created {len(all_chunks)} chunks from {len(txt_files)} files")
    return all_chunks, chunk_to_filename

def find_example_sentences(term: str, aliases: Set[str], chunks: List[str],
                         max_examples: int = MAX_EXAMPLES_PER_TERM) -> List[str]:
    """Find example sentences."""
    examples = set()
    search_terms = [term] + list(aliases)

    patterns = []
    for search_term in search_terms:
        variations = [
            search_term,
            search_term.replace('_', ' '),
            search_term.replace('_', '-'),
        ]
        for variant in variations:
            patterns.append(re.compile(r'\b' + re.escape(variant) + r'\b', re.IGNORECASE))

    for chunk in chunks:
        if len(examples) >= max_examples:
            break

        for pattern in patterns:
            if pattern.search(chunk):
                sentences = re.split(r'(?<=[.!?])\s+', chunk)
                for sentence in sentences:
                    if pattern.search(sentence):
                        clean_sentence = sentence.strip()
                        if 20 <= len(clean_sentence) <= 250 and clean_sentence not in examples:
                            examples.add(clean_sentence)
                            break
                break

    return list(examples)[:max_examples]

# =============================================================================
# MAIN PROCESSING PIPELINE
# =============================================================================

def process_single_file(filepath: str, client: OpenAI, model: str,
                        embed_model: SentenceTransformer, stopwords: Set[str],
                        all_chunks: List[str], target_terms_min: int, faiss_manager=None) -> Dict:
    """Process a single file for comprehensive biomedical terminology extraction."""
    filename = os.path.basename(filepath)
    study_id = os.path.splitext(filename)[0]

    logger.info(f"Processing {filename}")

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            full_text = f.read()

        processed_text = enhanced_preprocess_text(full_text)

        # Extract terms using comprehensive approach
        extracted_terms = extract_terms_comprehensive(
            processed_text, filename, client, model, stopwords, embed_model, target_terms_min
        )

        # Ensure minimum terms
        if len(extracted_terms) < target_terms_min:
            logger.warning(f"  - Only {len(extracted_terms)} terms extracted for {filename}, below minimum {target_terms_min}")

        # Fuzzy deduplication
        terms_after_fuzzy, fuzzy_aliases = fuzzy_deduplicate_terms(extracted_terms)

        # Merge aliases
        all_aliases = defaultdict(set)
        for term in terms_after_fuzzy:
            all_aliases[term].update(fuzzy_aliases.get(term, set()))

        # Score and rank terms with LENIENT thresholds for comprehensive extraction
        scored_terms = []
        for term in terms_after_fuzzy:
            quality_score = calculate_term_quality_score(term)
            frequency_score = 1.0
            semantic_alignment_score = calculate_semantic_alignment_score(term, embed_model)

            confidence_score = (
                WEIGHT_QUALITY * quality_score +
                WEIGHT_FREQUENCY * frequency_score +
                WEIGHT_SEMANTIC * semantic_alignment_score
            )

            # Apply LENIENT quality thresholds for comprehensive extraction
            if (confidence_score < MIN_CONFIDENCE_THRESHOLD or
                    semantic_alignment_score < MIN_SEMANTIC_ALIGNMENT or
                    quality_score < MIN_QUALITY_SCORE):
                continue

            examples = find_example_sentences(term, all_aliases[term], all_chunks)

            # Categorize term
            categories = []
            for category_name, category_terms in BIOMEDICAL_CATEGORIES.items():
                if term.lower() in category_terms:
                    categories.append(category_name)

            term_data = {
                "term": term,
                "confidence_score": round(confidence_score, 4),
                "quality_score": round(quality_score, 3),
                "semantic_alignment_score": round(semantic_alignment_score, 3),
                "categories": categories,
                "aliases": sorted(list(all_aliases[term])),
                "examples": examples,
                "is_core_term": term.lower() in ALL_BIOMEDICAL_TERMS,
            }

            scored_terms.append(term_data)

        # Sort by confidence score
        scored_terms.sort(key=lambda x: x['confidence_score'], reverse=True)

        return {
            "study_id": study_id,
            "terms": scored_terms,
            "term_count": len(scored_terms),
            "high_quality_count": sum(1 for t in scored_terms if t['confidence_score'] > 0.7),
            "avg_confidence_score": round(sum(t['confidence_score'] for t in scored_terms) / len(scored_terms), 3) if scored_terms else 0,
        }

    except Exception as e:
        logger.error(f"Error processing {filepath}: {e}")
        return {
            "study_id": study_id,
            "terms": [],
            "term_count": 0,
            "high_quality_count": 0,
            "avg_confidence_score": 0,
        }
def load_embeddings_and_index(output_dir: str = RESULTS_DIR):
    """Load saved embeddings and FAISS index."""
    npy_file = os.path.join(output_dir, "term_embeddings.npy")
    faiss_file = os.path.join(output_dir, FAISS_INDEX_FILE)
    mapping_file = os.path.join(output_dir, "term_mapping.json")

    embeddings = np.load(npy_file)
    index = faiss.read_index(faiss_file)

    with open(mapping_file, 'r') as f:
        term_mapping = json.load(f)

    return embeddings, index, term_mapping

def cleanup_memory(client: OpenAI, embed_model: SentenceTransformer):
    """Clean up memory-intensive objects."""
    try:
        # Clear embedding model cache
        if hasattr(embed_model, 'to'):
            embed_model.to('cpu')
        # Clear any cached embeddings
        if hasattr(calculate_semantic_alignment_score, 'core_embeddings'):
            del calculate_semantic_alignment_score.core_embeddings
        logger.info("✅ Memory cleanup completed")
    except Exception as e:
        logger.warning(f"Memory cleanup warning: {e}")
# =============================================================================
# GLOBAL DEDUPLICATION ACROSS ALL FILES
# =============================================================================

def deduplicate_across_files(all_results: List[Dict], top_k: int = 10000) -> Dict:
    """Deduplicate terms across all files and return top terms."""
    logger.info(f"🔍 Performing global deduplication across {len(all_results)} files")

    # Collect all terms from all files
    all_terms_data = []
    for result in all_results:
        for term_data in result['terms']:
            all_terms_data.append(term_data)

    logger.info(f"  - Total terms before global deduplication: {len(all_terms_data)}")

    # Group by term text for frequency counting
    term_groups = defaultdict(list)
    for term_data in all_terms_data:
        term_groups[term_data['term']].append(term_data)

    # Calculate aggregate scores
    aggregated_terms = []
    for term, instances in term_groups.items():
        avg_confidence = sum(t['confidence_score'] for t in instances) / len(instances)
        max_confidence = max(t['confidence_score'] for t in instances)
        frequency = len(instances)

        # Boost score based on frequency
        frequency_boost = min(0.3, frequency * 0.05)
        final_score = avg_confidence + frequency_boost

        # Get best examples and categories
        all_examples = []
        all_categories = set()
        all_aliases = set()

        for instance in instances:
            all_examples.extend(instance['examples'])
            all_categories.update(instance['categories'])
            all_aliases.update(instance['aliases'])

        # Remove duplicates and limit examples
        unique_examples = list(dict.fromkeys(all_examples))[:MAX_EXAMPLES_PER_TERM]

        aggregated_terms.append({
            "term": term,
            "confidence_score": round(final_score, 4),
            "avg_confidence_score": round(avg_confidence, 4),
            "max_confidence_score": round(max_confidence, 4),
            "frequency": frequency,
            "categories": sorted(list(all_categories)),
            "aliases": sorted(list(all_aliases)),
            "examples": unique_examples,
            "is_core_term": any(t['is_core_term'] for t in instances),
            "files_found_in": [os.path.basename(r['study_id']) for r in all_results
                               if any(t['term'] == term for t in r['terms'])]
        })

    # Sort by final confidence score
    aggregated_terms.sort(key=lambda x: x['confidence_score'], reverse=True)

    # Take top K terms
    final_terms = aggregated_terms[:top_k]

    logger.info(f"  - Final deduplicated terms: {len(final_terms)}")

    return {
        "deduplicated_terms": final_terms,
        "total_unique_terms": len(aggregated_terms),
        "top_k_terms": len(final_terms),
        "coverage_info": {
            "files_processed": len(all_results),
            "total_terms_before_dedup": len(all_terms_data),
            "unique_terms_after_dedup": len(aggregated_terms)
        }
    }

# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    """Main pipeline execution."""
    parser = argparse.ArgumentParser(description="Comprehensive Biomedical Terminology Extractor v6.0")
    parser.add_argument("--input", type=str, default=INPUT_DIRECTORY, help="Input directory containing text files")
    parser.add_argument("--file", type=str, help="Process single file")
    parser.add_argument("--model", type=str, default=LLM_MODEL_NAME, help="LLM model name")
    parser.add_argument("--min_terms", type=int, default=TARGET_TERMS_MIN, help="Minimum terms per file (default: 50)")
    parser.add_argument("--max_terms", type=int, default=TARGET_TERMS_MAX, help="Maximum terms per file")
    parser.add_argument("--min_confidence", type=float, default=MIN_CONFIDENCE_THRESHOLD, help="Minimum confidence threshold")
    parser.add_argument("--min_semantic", type=float, default=MIN_SEMANTIC_ALIGNMENT, help="Minimum semantic alignment threshold")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS, help="Number of parallel threads")
    parser.add_argument("--output", type=str, default=RESULTS_DIR, help="Output directory for results")
    parser.add_argument("--top_k", type=int, default=10000, help="Top K terms to keep after deduplication")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Use local variables instead of trying to modify global constants
    target_terms_min = args.min_terms
    min_confidence_threshold = args.min_confidence
    min_semantic_alignment = args.min_semantic

    if args.debug:
        logger.setLevel(logging.DEBUG)

    logger.info("🚀 Starting Comprehensive Biomedical Terminology Extraction v6.0")
    logger.info("🔬 ENHANCED: Extracting ALL biomedical terms including bioinformatics, molecules, chemicals, organisms")
    logger.info(f"🎯 Target: Minimum {target_terms_min} terms per file, Top {args.top_k} deduplicated terms")
    start_time = time.time()

    # Initialize components
    setup_cache()
    client = setup_llm_client()
    embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    stopwords = load_stopwords()

    # Check input directory
    if not os.path.exists(args.input):
        logger.error(f"Input directory {args.input} not found")
        return

    txt_files = [f for f in os.listdir(args.input) if f.endswith('.txt')]
    if not txt_files:
        logger.error("No .txt files found")
        return

    # Process files
    if args.file:
        if args.file not in txt_files:
            logger.error(f"File {args.file} not found")
            return
        files_to_process = [args.file]
        output_filename = f"terms_{os.path.splitext(args.file)[0]}.json"
    else:
        files_to_process = txt_files
        output_filename = os.path.join(args.output, OUTPUT_FILE)

    logger.info(f"📂 Processing {len(files_to_process)} file(s) with {args.threads} threads")

    # Create optimized chunks for example extraction
    all_chunks, _ = get_optimized_chunks(args.input)

    # Prepare arguments for parallel processing
    process_args = [
        (os.path.join(args.input, filename), client, args.model, embed_model, stopwords, all_chunks, target_terms_min, None)
        for filename in files_to_process
    ]

    # Process files
    results = []
    if args.threads > 1 and len(files_to_process) > 1:
        logger.info(f"🔄 Starting parallel processing with {args.threads} threads")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            future_to_file = {
                executor.submit(process_single_file, *arg): arg[0]
                for arg in process_args
            }

            for future in tqdm(concurrent.futures.as_completed(future_to_file),
                               total=len(files_to_process), desc="Processing files"):
                try:
                    result = future.result()
                    results.append(result)
                    logger.info(f"✅ {result['study_id']}: {result['term_count']} terms "
                                f"(high quality: {result['high_quality_count']})")
                except Exception as e:
                    logger.error(f"❌ Parallel processing failed: {e}")
    else:
        logger.info("🔄 Starting sequential processing")
        for arg in tqdm(process_args, desc="Processing files"):
            result = process_single_file(*arg)
            results.append(result)
            logger.info(f"✅ {result['study_id']}: {result['term_count']} terms "
                        f"(high quality: {result['high_quality_count']})")

    # Check if any terms were extracted at all
    total_terms_extracted = sum(r['term_count'] for r in results)
    if total_terms_extracted == 0:
        logger.error("❌ CRITICAL: No terms extracted from any files. Check input files and LLM connection.")
        return

    if not results:
        logger.error("❌ CRITICAL: No files processed successfully.")
        return

    # Generate individual output files
    os.makedirs(args.output, exist_ok=True)
    individual_files = []
    for result in results:
        individual_file = os.path.join(args.output, f"{result['study_id']}_terms.json")
        with open(individual_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        individual_files.append(individual_file)


    # Generate combined output with deduplicated terms
    total_terms = sum(r['term_count'] for r in results)
    high_quality_terms = sum(r['high_quality_count'] for r in results)

    # Perform global deduplication
    logger.info("🔄 Performing global deduplication across all files")
    deduplicated_results = deduplicate_across_files(results, top_k=args.top_k)

    # NEW: Save embeddings and FAISS index for the top terms
    top_terms = [term_data['term'] for term_data in deduplicated_results['deduplicated_terms']]
    if top_terms:
        npy_file, faiss_file, mapping_file = save_embeddings_and_index(top_terms, embed_model, args.output)
        # Validate the embeddings were created successfully
        if validate_embeddings(npy_file, faiss_file, mapping_file):
            logger.info("✅ Embeddings and index validated successfully")
        else:
            logger.error("❌ Embedding validation failed")
    else:
        logger.warning("❌ No terms extracted - skipping embedding creation")
        npy_file, faiss_file, mapping_file = "none", "none", "none"

    output_data = {
        "extraction_info": {
            "npy_embeddings": npy_file,
            "faiss_index": faiss_file,
            "term_mapping": mapping_file,
            "version": "6.0",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model_used": args.model,
            "embedding_model": EMBEDDING_MODEL_NAME,
            "files_processed": len(files_to_process),
            "total_terms_extracted": total_terms,
            "high_quality_terms": high_quality_terms,
            "avg_terms_per_file": round(total_terms / len(files_to_process), 1) if files_to_process else 0,
            "processing_threads": args.threads,
            "min_terms_per_file": target_terms_min,
            "top_k_deduplicated": args.top_k,
        },
        "individual_results": results,
        "deduplicated_results": deduplicated_results
    }

    # Save combined output
    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Save deduplicated terms separately
    deduplicated_file = os.path.join(args.output, f"top_{args.top_k}_deduplicated_terms.json")
    with open(deduplicated_file, 'w', encoding='utf-8') as f:
        json.dump(deduplicated_results, f, indent=2, ensure_ascii=False)

    end_time = time.time()
    # Clean up memory
    cleanup_memory(client, embed_model)


    # Final summary
    logger.info("\n" + "="*50)
    logger.info("🎉 EXTRACTION COMPLETE - SUMMARY")
    logger.info("="*50)
    logger.info(f"📁 Output Directory: {args.output}")
    logger.info(f"⏱️  Total Time: {end_time - start_time:.1f} seconds ({((end_time - start_time)/60):.1f} minutes)")
    logger.info(f"📄 Files Processed: {len(files_to_process)}")
    logger.info(f"🔢 Total Terms Extracted: {total_terms:,}")
    logger.info(f"⭐ High Quality Terms: {high_quality_terms:,}")
    logger.info(f"📊 Average Terms/File: {output_data['extraction_info']['avg_terms_per_file']}")
    logger.info(f"🔄 Unique Terms After Dedup: {deduplicated_results['total_unique_terms']:,}")
    logger.info(f"🏆 Top Terms Saved: {args.top_k:,}")

    if top_terms:
        logger.info(f"💾 Embedding Files Created:")
        logger.info(f"    - {npy_file}")
        logger.info(f"    - {faiss_file}")
        logger.info(f"    - {mapping_file}")

    logger.info("="*50)

if __name__ == "__main__":
    main()

