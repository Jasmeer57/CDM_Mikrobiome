"""
Multi-sciSpaCy model term extraction module.
Extracts scientific terms using multiple sciSpaCy models with comprehensive filtering.
"""

import logging
import spacy
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
from collections import defaultdict, Counter
from ..config.settings import SciSpaCyConfig

logger = logging.getLogger(__name__)


# ENHANCED: Safer Synonym/Normalization maps preserving clinical specificity
# Only normalizes truly equivalent terms, not clinically distinct conditions
SAFE_SYNONYM_MAP = {
    # Safe microbiome synonyms (truly equivalent concepts)
    "gut flora": "gut microbiota",
    "intestinal flora": "intestinal microbiota",
    "microbial flora": "microbiota",

    # Safe technical variations
    "16s ribosomal rna": "16s rrna",
    "16s ribosomal ribosomal rna": "16s rrna",
    "16s ribosomal rna gene": "16s rrna gene",
    "16s rrn": "16s rrna",

    # Safe metabolic term variations
    "short chain fatty acids": "short-chain fatty acids",
    "scfas": "scfa",
    "short chain fatty acid": "short-chain fatty acid",

    # Safe bacterial name variations
    "e. coli": "escherichia coli",
    "c. difficile": "clostridioides difficile",
    "c. diff": "clostridioides difficile",
    "bacteroides fragilis": "bacteroides fragilis group",

    # Safe methodological terms
    "next generation sequencing": "next-generation sequencing",
    "high throughput sequencing": "high-throughput sequencing",
    "amplicon sequencing": "amplicon sequencing",  # No change, just normalization
    "metagenomic sequencing": "metagenomic sequencing",  # No change, just normalization
}

# DANGEROUS mappings that were previously included - now AVOIDED:
# DO NOT collapse distinct clinical conditions:
# - "inflammatory bowel disease" → "ibd" (loses specificity between Crohn's and UC)
# - "crohn's disease" → "ibd" (dangerous loss of diagnostic specificity)
# - "ulcerative colitis" → "ibd" (dangerous loss of diagnostic specificity)
# - "irritable bowel syndrome" → "ibs" (acceptable but let's preserve full name)
# - "small intestinal bacterial overgrowth" → "sibo" (acceptable but preserve full name for clarity)

# BALANCED Clinical specificity - only CRITICAL terms protected to maintain term quantity
CRITICAL_CLINICAL_TERMS = {
    # Only the most important diagnostic terms that should never be collapsed
    "crohn's disease",
    "ulcerative colitis",
    "type 1 diabetes",
    "type 2 diabetes",
    "multiple sclerosis",
    "rheumatoid arthritis"
}

# Less critical clinical terms that can be normalized to maintain quantity
PERMISSIBLE_CLINICAL_TERMS = {
    "inflammatory bowel disease",  # Can be safely normalized if needed
    "crohn disease",              # Variant spelling
    "irritable bowel syndrome",
    "small intestinal bacterial overgrowth",
    "spondyloarthritis",
    "lupus erythematosus"
}

# Abbreviation expansion map - expand abbreviations but don't collapse to them
ABBREVIATION_EXPANSION = {
    "ibd": "inflammatory bowel disease",
    "ibs": "irritable bowel syndrome",
    "sibo": "small intestinal bacterial overgrowth",
    "scfa": "short-chain fatty acid",
    "scfas": "short-chain fatty acids",
    "uc": "ulcerative colitis",
    "cd": "crohn's disease",
    "ra": "rheumatoid arthritis",
    "ms": "multiple sclerosis",
    "gi": "gastrointestinal",
    "gvhd": "graft-versus-host disease"
}

# ENHANCED: Entity refinement rules from reference terms.py (P6/P11 Fix)
ENTITY_REFINEMENT_RULES = {
    'ORGANISM': [r'\b(bacter|coccus|sp\.|spp\.|phage|virus)\b', r'[A-Z][a-z]+ [a-z]+'],
    'DISEASE': [r'\b(disease|syndrome|infection|itis|osis)\b'],
    'CHEMICAL': [r'\b(acid|peptide|protein|enzyme|lipid|ol|ate)\b'],
}

# ENHANCED: Entity weights from reference terms.py for better scoring
ENTITY_WEIGHTS = {
    'ORGANISM': 0.35,
    'TAXON': 0.35,
    'GENE': 0.25,
    'GENE_OR_GENE_PRODUCT': 0.25,
    'CHEMICAL': 0.20,
    'DISEASE': 0.18,
    'SO': 0.15,
    'GO': 0.15,
    'CL': 0.15,
    'CHEBI': 0.20,
    'OTHER': 0.10
}


class TermsExtractor:
    """Multi-model sciSpaCy term extraction with comprehensive filtering"""

    # P1-P12 Filters from original terms.py
    FILTER_PATTERNS = {
        # Original P1-P12 filters
        'P1': r'\b[A-Z]\.?\b',  # Single letters (with optional period)
        'P2': r'\b(etal|fig|figure|table|tab)\b\.?',  # Citations and figure references
        'P3': r'^\d+$',  # Pure numbers
        'P4': r'^[a-zA-Z]$',  # Single characters
        'P5': r'^[^a-zA-Z]+$',  # No alphabetic characters
        'P6': r'^.{1,2}$',  # Very short terms (1-2 chars)
        'P7': r'^\W+$',  # Only non-word characters
        'P8': r'^[0-9\W]+$',  # Only numbers and symbols
        'P9': r'\b(and|or|the|of|in|on|at|to|for|with|by|as)\b',  # Common stop words
        'P10': r'^[a-z]{1,3}$',  # Very short lowercase words
        'P11': r'^\W*\d+\W*$',  # Numbers with optional surrounding symbols
        'P12': r'^[^a-zA-Z]*[a-z][^a-zA-Z]*$',  # Single lowercase letter with symbols

        # Enhanced P13-P28 filters for low-quality term removal
        'P13': r'^[A-Z][a-z]+[0-9]+(?:\*|†)?$',  # Author names with numbers and asterisks (e.g., "Odamaki1", "Odamaki1*")
        'P14': r'^[A-Z][a-z]+ [A-Z][a-z]+[0-9]+(?:\*|†)?$',  # Two author names with numbers (e.g., "John Doe1")
        'P15': r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+[0-9]+,\s*[0-9]+',  # Multiple authors with numbers (e.g., "Smith1, Jones2")
        'P16': r'https?://[^\s]+',  # URLs
        'P17': r'\b(?:university|department|institute|college|hospital|center|centre)\b',  # Institutional terms
        'P18': r'\b(?:abstract|introduction|methods|results|discussion|conclusion|references)\b',  # Paper sections
        'P19': r'\b(?:doi|isbn|issn|pmid|pmcid)\b',  # Publication identifiers
        'P20': r'\b(?:email|phone|fax|address|correspondence)\b',  # Contact information
        'P21': r'\b(?:study|research|paper|article|report|manuscript)\b',  # Generic academic terms
        'P22': r'\b(?:cross-?sectional|prospective|retrospective|observational)\b\s+study',  # Study design terms
        'P23': r'^[A-Z][a-z]+,\s*[A-Z]\.?\s*[A-Z][a-z]+$',  # Author format: "Smith, J. John"
        'P24': r'^[A-Z][a-z]+(?:-[A-Z][a-z]+)?\s+[A-Z]\.\s*[A-Z][a-z]+$',  # Author format: "Smith-Jones J. John"
        'P25': r'\b(?:professor|dr|md|phd)\b',  # Academic titles
        'P26': r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,}\s*[0-9]*\*?$',  # Three or more names with numbers
        'P27': r'/[A-Za-z0-9_\-./]+',  # File paths
        'P28': r'^[A-Z][a-z]+\s+et\s+al\.$'  # "et al" patterns
    }

    # Enhanced noise terms blocklist from reference terms.py
    NOISE_TERMS_BLOCKLIST = {
        # Latin placeholder text
        "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit",
        "proin", "ornare", "etiam", "condimentum", "mauris", "consequat", "fermentum",
        "phasellus", "elementum", "habitant", "morbi", "tristique", "senectus",
        # Common English stopwords
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
        "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were", "will", "with",
        # Generic verbs and adjectives found in publications
        "see", "show", "shown", "study", "studies", "result", "results", "figure", "table",
        "introduction", "methods", "conclusion", "abstract", "background", "discussion",
        "significant", "high", "low", "increase", "decrease", "effect", "effects", "author",
        "copyright", "reserved", "rights", "publication", "published", "journal", "university",
        "et", "al", "fig", "supplementary", "data", "information", "available", "online",
        "author contributions", "funding", "acknowledgments", "competing interests"
    }

    def __init__(self, config: SciSpaCyConfig):
        self.config = config
        self.models = {}
        self._load_models()

        # Enhanced validation patterns for quality filtering
        import re
        self.INVALID_PATTERNS = [
            # Original patterns
            re.compile(r'^\W*\d+\.\d+\W*$'),
            re.compile(r'^\W*\d+\W*$'),
            re.compile(r'^[A-Z]\W*$'),
            re.compile(r'.*\.(png|jpg|pdf|html)$', re.I),
            re.compile(r'^\W*(fig|table)\W*\d*\W*$', re.I),
            re.compile(r'^\W*p\s*[<>=]\s*0\.\d+\W*$', re.I),
            re.compile(r'^\W*doi:.*$', re.I),

            # Enhanced patterns for quality improvement
            # URLs and web links
            re.compile(r'^\W*https?://.*$', re.I),
            re.compile(r'^\W*www\..*$', re.I),
            re.compile(r'.*\.com\W*$|.*\.org\W*$|.*\.edu\W*$', re.I),

            # Company names and institutions
            re.compile(r'.*Co\.\W*$|.*Inc\.\W*$|.*Ltd\.\W*$', re.I),
            re.compile(r'.*Company\W*$|.*Corporation\W*$', re.I),
            re.compile(r'.*University\W*$|.*Institute\W*$', re.I),

            # Software versions and product names
            re.compile(r'.*version\s*\d+[\.\d]*\W*$', re.I),
            re.compile(r'.*v\d+[\.\d]*\W*$'),  # v1.0, v2.3.1
            re.compile(r'^\w*\s*v\d+.*\s*\d+\W*'),  # QIIME v1.8.0

            # Author names and citations
            re.compile(r'^[A-Z][a-z]+\s+[A-Z][a-z]*\d*\W*$'),  # First Last
            re.compile(r'^[A-Z]\.\s*[A-Z][a-z]*\W*$'),  # J. Smith
            re.compile(r'^[A-Z][a-z]+\s+[A-Z]\.\W*$'),  # Smith J.
            re.compile(r'.*et\s+al\.\W*$', re.I),  # et al.
            re.compile(r'^[A-Z][a-z]+,\s*[A-Z]\.\W*'),  # Smith, J.
            re.compile(r'.*\*\s*[A-Z][a-z]+\d*.*,\s*[A-Z][a-z]+\s*[A-Z]*\d*'),  # Author1*, Author2
            re.compile(r'^[A-Z][a-z]+\s+[A-Z][a-z]+\d*\*,\s*[A-Z][a-z]+\s+[A-Z][a-z]+\d*'),  # John Smith*, Jane Doe
            re.compile(r'.*[A-Z][a-z]+\d*\*,.*[A-Z][a-z]+\d*\W*'),  # Any pattern with name1*, name2

            # Fragmented text and punctuation
            re.compile(r'.*[,:;]\W*$'),  # trailing punctuation
            re.compile(r'^[^a-zA-Z]*[0-9]+[^a-zA-Z]*$'),  # mostly numbers
            re.compile(r'^[A-Z]\.\W*$'),  # single letter abbreviations

            # Common non-biomedical terms
            re.compile(r'^\W*(and|or|the|but|for|with|from|this|that|these|those)\W*$', re.I),
            re.compile(r'^\W*(can|could|would|should|may|might|must)\W*$', re.I),

            # Publication references
            re.compile(r'.*figure\s*\d*\W*$', re.I),
            re.compile(r'.*table\s*\d*\W*$', re.I),
            re.compile(r'.*supplementary.*\W*$', re.I),
            re.compile(r'.*additional\s+file.*\W*$', re.I),
        ]

    def _load_models(self):
        """Load all configured sciSpaCy models"""
        logger.info(f"Loading {len(self.config.models)} sciSpaCy models...")

        for model_name in self.config.models:
            try:
                logger.info(f"Loading model: {model_name}")
                nlp = spacy.load(model_name, disable=self.config.disabled_components)

                # Add sentencizer for sentence boundaries if not present
                if "sentencizer" not in nlp.pipe_names:
                    nlp.add_pipe("sentencizer")

                self.models[model_name] = nlp
                logger.info(f"✓ Successfully loaded: {model_name}")
            except Exception as e:
                logger.error(f"✗ Failed to load model {model_name}: {e}")
                continue

        if not self.models:
            raise RuntimeError("No sciSpaCy models could be loaded. Please install required models.")

        logger.info(f"Successfully loaded {len(self.models)}/{len(self.config.models)} models")

    def _normalize_term(self, term: str, use_synonym_map: bool = True) -> str:
        """
        ENHANCED: Safer term normalization preserving clinical specificity
        Normalizes entity to a deterministic canonical form without losing diagnostic precision
        """
        try:
            import re
            original_term = term.strip()
            term_lower = original_term.lower()

            # BALANCED SAFETY CHECK: Only protect the most critical clinical terms
            if original_term in CRITICAL_CLINICAL_TERMS:
                return original_term  # Preserve exact clinical terminology for critical conditions only

            # Allow normalization for less critical clinical terms to maintain quantity
            # This balances safety with the requirement for ≥75 terms per file

            # Step 1: Expand abbreviations (preserve specificity)
            if term_lower in ABBREVIATION_EXPANSION:
                expanded = ABBREVIATION_EXPANSION[term_lower]
                # Only expand if it doesn't conflict with clinical specificity
                if expanded not in CLINICAL_SPECIFICITY_TERMS:
                    original_term = expanded
                    term_lower = expanded.lower()

            # Step 2: Basic lemmatization and cleaning
            tokens = []
            for token_char in term_lower.split():
                cleaned = re.sub(r'[^\w\s-]', '', token_char).strip()
                if cleaned and len(cleaned) > 1:
                    tokens.append(cleaned)

            # Create normalized form (sorted for consistency)
            sorted_tokens = sorted(tokens)
            normalized_form = " ".join(sorted_tokens) if sorted_tokens else ""

            # Step 3: Apply SAFE synonym mapping only if enabled and safe
            if use_synonym_map:
                original_lemmatized = " ".join(tokens)

                # Check safe synonym map first
                if original_lemmatized in SAFE_SYNONYM_MAP:
                    candidate = SAFE_SYNONYM_MAP[original_lemmatized]
                    # Final safety check: ensure we're not collapsing clinical terms
                    if candidate not in CLINICAL_SPECIFICITY_TERMS:
                        return candidate
                    else:
                        # Safety: if synonym would collapse clinical terms, keep original
                        return original_term

                if normalized_form in SAFE_SYNONYM_MAP:
                    candidate = SAFE_SYNONYM_MAP[normalized_form]
                    if candidate not in CLINICAL_SPECIFICITY_TERMS:
                        return candidate
                    else:
                        return original_term

            # Return normalized form or original term if no normalization applied
            return normalized_form if normalized_form else original_term

        except Exception as e:
            # Safety: return original term if normalization fails
            logger.warning(f"Term normalization failed for '{term}': {e}")
            return term.strip()

    def _refine_entity_label(self, term_text: str, original_label: str) -> str:
        """
        ENHANCED: Entity label refinement from reference terms.py (P6/P11 Fix)
        Refine generic entity labels using rule-based patterns
        """
        import re

        if original_label not in ['ENTITY', 'OTHER']:
            return original_label

        term_lower = term_text.lower()
        for specific_label, patterns in ENTITY_REFINEMENT_RULES.items():
            for pattern in patterns:
                if re.search(pattern, term_lower):
                    return specific_label

        return original_label

    def _apply_filters(self, term: str) -> bool:
        """Apply P1-P12 filters plus enhanced noise filtering to determine if term should be kept"""
        import re

        term_lower = term.lower().strip()

        # Apply original P1-P28 pattern filters
        for filter_name, pattern in self.FILTER_PATTERNS.items():
            if re.match(pattern, term, re.IGNORECASE):
                return False  # Filter out this term

        # Apply enhanced noise terms blocklist from reference terms.py
        if term_lower in self.NOISE_TERMS_BLOCKLIST:
            return False

        # Additional validation patterns from reference terms.py
        for pattern in self.INVALID_PATTERNS:
            if pattern.match(term):
                return False

        # Length and content validation
        if len(term) < 2 or len(term) > 100:
            return False

        if not any(c.isalpha() for c in term):
            return False

        # Advanced quality checks
        if not self._advanced_quality_check(term, context if 'context' in locals() else ""):
            return False

        # Strict biomedical term filtering - eliminate generic terms
        if not self._is_biomedical_term(term, context if 'context' in locals() else ""):
            return False

        # CDM-specific filtering - optimize for Common Data Model
        if not self._is_cdm_relevant(term, context if 'context' in locals() else ""):
            return False

        return True  # Term passes all filters

    def _advanced_quality_check(self, term: str, context: str = "") -> bool:
        """Advanced quality checks for sophisticated filtering"""
        import re  # Import re module for this function

        term_lower = term.lower()

        # Skip terms that are mostly single characters repeated
        if len(set(term.lower())) <= 2 and len(term) > 3:
            return False

        # Skip terms that look like random character combinations
        vowel_count = sum(1 for c in term_lower if c in 'aeiou')
        if len(term) > 5 and vowel_count == 0:
            return False

        # Skip terms that are clearly author names in citations
        context_lower = context.lower()
        if any(indicator in context_lower for indicator in ['et al', 'doi:', 'published by', 'institute', 'university']):
            # Look for name patterns
            if re.match(r'^[A-Z][a-z]+\s+[A-Z][a-z]+', term):
                return False
            if re.match(r'^[A-Z]\.\s*[A-Z][a-z]+', term):
                return False

        # Skip product names and manufacturers
        product_patterns = [
            r'.*kit\s*$',
            r'.*reagent\s*$',
            r'.*systems?\s*$',
            r'.*technolog(?:y|ies)\s*$',
            r'.*instrument(?:s)?\s*$',
            r'.*solution(?:s)?\s*$',
        ]
        for pattern in product_patterns:
            if re.search(pattern, term_lower):
                return False

        # Skip overly generic terms unless in scientific context
        generic_terms = {
            'data', 'results', 'method', 'study', 'analysis', 'model', 'system',
            'process', 'approach', 'technique', 'procedure', 'protocol'
        }
        if term_lower in generic_terms:
            # Allow if in scientific context
            scientific_context = [
                'microbi', 'bacteri', 'gene', 'protein', 'cell', 'sequencing',
                'analysis', 'experiment', 'laboratory', 'clinical', 'medical'
            ]
            if not any(ctx in context_lower for ctx in scientific_context):
                return False

        # Keep terms that look like specific biological/medical entities
        biological_patterns = [
            r'.*microbi.*',
            r'.*bacteri.*',
            r'.*virus.*',
            r'.*enzyme.*',
            r'.*protein.*',
            r'.*gene.*',
            r'.*dna\s*\w*',
            r'.*rna\s*\w*',
            r'.*cell.*',
            r'.*tissue.*',
            r'.*organ.*',
            r'.*symbio.*',
            r'.*metabol.*',
        ]

        # Allow if it matches biological patterns (even if generic)
        for pattern in biological_patterns:
            if re.search(pattern, term_lower):
                return True

        return True  # Passes advanced checks by default

    def _is_biomedical_term(self, term: str, context: str = "") -> bool:
        """Strict filtering to keep only high-value biomedical/technical terms"""
        import re

        term_lower = term.lower()

        # HIGH-VALUE BIOMEDICAL KEYWORDS - must contain at least one
        biomedical_keywords = {
            # Microbiology/Bacteria
            'microbi', 'microbe', 'bacteri', 'microbiota', 'microbiome',
            'pathogen', 'commensal', 'symbio', 'probiot', 'prebiot',

            # Genetics/Molecular Biology
            'gene', 'dna', 'rna', 'protein', 'enzyme', 'genome', 'genom',
            'transcript', 'express', 'mutat', 'sequenc', 'amplif',
            'polymeras', 'primer', 'nucleotid',

            # Microbial Taxonomy
            'phylum', 'class', 'order', 'family', 'genus', 'species',
            'strain', 'isolat', 'culture', 'colony',

            # Microbial Groups
            'actinobacteri', 'proteobacteri', 'bacteroidet', 'firmicut',
            'firmicutes', 'bacteroidetes', 'proteobacteria', 'actinobacteria',
            'enterobacteri', 'bifidobacteri', 'lactobacillus', 'eubacteri',
            'clostridi', 'streptococc', 'escherichi', 'salmonell',

            # Analytical Techniques
            'sequencing', 'pcr', 'amplification', 'extraction', 'purification',
            'quantification', 'amplif', 'denaturing', 'gel electrophores',
            'chromatograph', 'spectromet', 'biochem',

            # Microbial Ecology
            'diversity', 'abundance', 'richness', 'evenness', 'composition',
            'community', 'population', 'clustering', 'phylogen', 'taxonom',
            'ecolog', 'habitat', 'niche',

            # Analytical Methods
            '16s', 'rrna', 'ribosomal', 'v3-v4', 'region', 'amplicon',
            'otu', 'asv', 'picrust', 'uchime', 'qiime', 'mothur',

            # Health/Medical Context
            'clinical', 'medical', 'health', 'disease', 'therapeut',
            'antibiot', 'antimicrobial', 'resistance', 'susceptibilit',
            'infection', 'inflammation', 'immune', 'immunolog',

            # Biochemical Processes
            'metabol', 'catabol', 'anabol', 'ferment', 'oxidation',
            'reduction', 'synthesis', 'pathway', 'catalyt', 'enzymat',

            # Cell Biology
            'cellular', 'membrane', 'cytoplasm', 'nucleus', 'organelle',
            'mitochondria', 'chloroplast', 'vacuole', 'ribosome',
        }

        # Must contain at least one biomedical keyword
        has_biomedical_keyword = any(keyword in term_lower for keyword in biomedical_keywords)

        if not has_biomedical_keyword:
            return False

        # BLOCKED GENERIC TERMS - even if they contain biomedical keywords
        blocked_terms = {
            # Generic descriptors
            'new', 'old', 'big', 'small', 'large', 'tiny', 'huge',
            'good', 'bad', 'high', 'low', 'more', 'less', 'many', 'few',

            # Common verbs/adjectives
            'used', 'found', 'made', 'done', 'given', 'taken', 'seen',
            'analyzed', 'studied', 'investigated', 'examined', 'tested',
            'important', 'significant', 'major', 'minor', 'main',

            # Generic temporal/quantitative
            'years', 'months', 'days', 'hours', 'time', 'period',
            'number', 'count', 'amount', 'quantity', 'level',
            'percent', 'ratio', 'proportion', 'fraction',

            # Generic location/context
            'human', 'people', 'person', 'individual', 'subject', 'patient',
            'sample', 'specimen', 'data', 'result', 'finding',
            'study', 'research', 'analysis', 'experiment', 'test',

            # Generic states
            'changes', 'change', 'difference', 'similar', 'different',
            'increase', 'decrease', 'rise', 'fall', 'growth', 'decline',
        }

        if term_lower in blocked_terms:
            return False

        # SPECIFIC ALLOWED TERMS - exceptions that are valuable
        allowed_exceptions = {
            'gut microbiota', 'human gut microbiota', 'bacterial diversity',
            'microbial diversity', '16s rrna', '16s rrna gene', 'bacterial composition',
            'microbial community', 'bacterial community', 'gut bacteria',
            'intestinal microbiota', 'fecal microbiota', 'oral microbiota',
            'microbial ecology', 'bacterial ecology', 'molecular analysis',
            'genetic analysis', 'biochemical analysis', 'clinical isolates',
            'bacterial isolates', 'environmental samples', 'dna extraction',
            'rna extraction', 'protein extraction', 'gene expression',
            'protein expression', 'bacterial growth', 'microbial growth',
            'cell growth', 'tissue culture', 'bacterial culture',
        }

        if term_lower in allowed_exceptions:
            return True

        # Additional filters for high-value terms
        # Terms should be substantial (not too short) and meaningful
        if len(term) < 3:
            return False

        # Avoid single-word very generic terms unless they're clearly biomedical
        if len(term.split()) == 1 and term_lower not in {
            'microbiota', 'microbiome', 'bacterial', 'microbial', 'genetic',
            'molecular', 'cellular', 'clinical', 'medical', 'bacteria',
            'protein', 'enzyme', 'gene', 'dna', 'rna', 'antibiotic',
            'metabolite', 'pathway', 'community', 'diversity'
        }:
            # For single words, require higher specificity
            if not any(bio in term_lower for bio in ['bacteri', 'microbi', 'gene', 'protein', 'dna', 'rna']):
                return False

        return True  # Passes biomedical filtering

    def _is_cdm_relevant(self, term: str, context: str = "") -> bool:
        """CDM-specific filtering to optimize for Common Data Model terminology"""
        import re

        term_lower = term.lower()

        # CDM ESSENTIAL DOMAINS AND KEYWORDS
        cdm_keywords = {
            # Person/Subject Domain
            'patient', 'subject', 'individual', 'population', 'human', 'people',
            'participant', 'cohort', 'healthy', 'diseased', 'infected', 'affected',

            # Condition/Disease Domain
            'disease', 'disorder', 'syndrome', 'infection', 'inflammation',
            'antibiotic', 'antimicrobial', 'resistance', 'susceptibility',
            'immune', 'immunolog', 'autoimmune', 'allerg', 'reaction',
            'cancer', 'tumor', 'metabol', 'deficiency', 'mutation',
            'pain', 'fever', 'symptom', 'complication', 'mortality',

            # Drug/Substance Domain
            'drug', 'medication', 'medicine', 'pharmaceutical', 'compound',
            'therapy', 'treatment', 'therapeut', 'dose', 'administration',
            'antibiot', 'antimicrobial', 'vaccin', 'immune', 'supplement',
            'toxin', 'poison', 'chemical', 'biomarker', 'marker',

            # Procedure/Observation Domain
            'procedure', 'protocol', 'method', 'technique', 'surgery',
            'diagnosis', 'exam', 'test', 'screening', 'monitor', 'assessment',
            'biopsy', 'culture', 'laboratory', 'lab', 'imaging', 'scan',
            'separation', 'purification', 'extraction', 'isolation',

            # Measurement/Result Domain
            'measurement', 'analysis', 'result', 'value', 'level', 'concentration',
            'quantity', 'count', 'rate', 'ratio', 'proportion', 'percentage',
            'score', 'index', 'marker', 'biomarker', 'endpoint', 'outcome',

            # Microorganism Domain (High priority for CDM)
            'bacteria', 'bacteri', 'microbe', 'microbi', 'microorganism', 'pathogen',
            'virus', 'viral', 'fungi', 'parasite', 'yeast', 'mold', 'protozoa',
            'strain', 'isolat', 'serotype', 'genotype', 'phenotype', 'virulenc',

            # Genetic/Molecular Domain
            'gene', 'genetic', 'dna', 'rna', 'protein', 'enzyme', 'genome',
            'sequencing', 'sequence', 'variant', 'mutation', 'expression',
            'amplification', 'pcr', 'polymeras', 'primer', 'probe', 'hybridiz',

            # Clinical/Health Domain
            'clinical', 'medical', 'health', 'hospital', 'clinic', 'nursing',
            'emergency', 'outpatient', 'inpatient', 'ambulatory', 'rehabilitation',
            'prevention', 'wellness', 'fitness', 'nutrition', 'diet', 'exercise',

            # Data/Metadata Domain
            'record', 'data', 'study', 'research', 'trial', 'cohort', 'observation',
            'longitudinal', 'prospective', 'retrospective', 'case', 'control'
        }

        # Must contain at least one CDM keyword
        has_cdm_keyword = any(keyword in term_lower for keyword in cdm_keywords)

        if not has_cdm_keyword:
            return False

        # BLOCK NON-CDM TERMS (even if they contain keywords)
        blocked_cdm_terms = {
            # Purely technical research terms without clinical application
            'phylogenetic tree construction', 'evolutionary analysis',
            'comparative genomics', 'phylogeography',
            'environmental sampling', 'ecological survey',
            'agricultural', 'veterinary', 'plant', 'animal model',
            'experimental design', 'statistical method',

            # Academic/administrative
            'university', 'institution', 'department', 'faculty', 'research group',
            'funding', 'grant', 'publication', 'citation', 'reference',
            'journal', 'conference', 'meeting', 'abstract', 'introduction',
            'methods section', 'results section', 'discussion section',
            'conclusion', 'limitations', 'future work',

            # Software/technical details
            'version', 'software', 'package', 'program', 'algorithm',
            'computer', 'system', 'platform', 'database', 'repository',
            'statistical analysis', 'bioinformatics', 'pipeline',

            # Purely descriptive without clinical relevance
            'relatively abundant', 'significantly increased', 'highly correlated',
            'statistically significant', 'p value', 'confidence interval',
            'sample size', 'power analysis', 'effect size',
        }

        if any(blocked in term_lower for blocked in blocked_cdm_terms):
            return False

        # CDM PRIORITY TERMS (always keep)
        cdm_priority_terms = {
            # Patient demographics and basic info
            'age', 'gender', 'sex', 'ethnicity', 'race', 'height', 'weight',
            'bmi', 'birth date', 'diagnosis date', 'admission date',

            # Core clinical concepts
            'gut microbiota', 'intestinal microbiota', 'fecal microbiota',
            'bacterial infection', 'antibiotic treatment', 'drug resistance',
            'clinical outcome', 'patient outcome', 'treatment response',

            # Laboratory/clinical measurements
            'clinical laboratory', 'blood test', 'urine test', 'stool sample',
            'bacterial culture', 'antibiotic susceptibility', 'minimum inhibitory',
            'blood count', 'inflammatory markers', 'immune response',

            # Microbiome-specific clinical relevance
            'microbiome composition', 'microbial diversity', 'dysbiosis',
            'probiotic treatment', 'microbiota modulation', 'fecal transplantation',
            'bacterial overgrowth', 'small intestinal bacterial overgrowth',
            'clostridium difficile', 'helicobacter pylori', 'escherichia coli',
            'staphylococcus aureus', 'streptococcus pneumoniae',

            # Therapeutic interventions
            'antibiotic therapy', 'pharmacological treatment', 'immunotherapy',
            'vaccination', 'probiotic supplementation', 'prebiotic fiber',
            'dietary intervention', 'lifestyle modification',

            # Disease/conditions with microbiome link
            'inflammatory bowel disease', 'crohn disease', 'ulcerative colitis',
            'irritable bowel syndrome', 'antibiotic-associated diarrhea',
            'necrotizing enterocolitis', 'sepsis', 'multiple sclerosis',
            'rheumatoid arthritis', 'type 1 diabetes', 'obesity', 'allergic disease'
        }

        if term_lower in cdm_priority_terms:
            return True

        # ADDITIONAL FILTERING FOR HIGH-VALUE CDM TERMS
        # Prioritize terms that have clear clinical application
        clinical_indicators = [
            'antibiotic resistance', 'drug susceptibility', 'clinical isolate',
            'patient derived', 'human derived', 'clinical sample',
            'treatment outcome', 'therapeutic response', 'adverse event',
            'side effect', 'complication', 'prognosis', 'mortality',
            'hospital acquired', 'nosocomial', 'community acquired'
        ]

        if any(indicator in term_lower for indicator in clinical_indicators):
            return True

        # FILTER OUT VERY LOW FREQUENCY, LOW-VALUE TERMS
        # (this will be handled by frequency-based filtering later)

        return True  # Passes CDM filtering

    def _calculate_science_relevance(self, term: str, context: str = "", entity_label: str = "OTHER") -> float:
        """
        ENHANCED: Calculate science relevance score using entity weights from reference terms.py
        Incorporates entity type weighting for better scoring accuracy
        """
        if not term or len(term) < 2:
            return 0.0

        # Base score from length (longer terms tend to be more scientific)
        length_score = min(len(term) / 10.0, 1.0)

        # Entity type weighting from reference terms.py
        entity_weight = ENTITY_WEIGHTS.get(entity_label, 0.1)

        # Enhanced science-related keywords with biomedical focus
        science_keywords = {
            'biological': [
                'cell', 'gene', 'protein', 'enzyme', 'dna', 'rna', 'bacteria', 'virus', 'organism',
                'microbi', 'microbe', 'pathogen', 'immun', 'metabol', 'genome', 'proteom',
                'transcript', 'seque', 'mutat', 'express', 'regulat', 'signa', 'pathway'
            ],
            'chemical': [
                'acid', 'base', 'compound', 'molecule', 'reaction', 'synthesis', 'catalyst',
                'substrate', 'inhibit', 'binding', 'receptor', 'ligand', 'cofactor'
            ],
            'medical': [
                'disease', 'treatment', 'therapy', 'diagnosis', 'symptom', 'patient',
                'clinical', 'pharma', 'drug', 'medic', 'therapeut', 'toxic'
            ],
            'technical': [
                'method', 'technique', 'analysis', 'measurement', 'experiment', 'study',
                'assay', 'protocol', 'proced', 'valid', 'quantif', 'character'
            ]
        }

        keyword_score = 0.0
        term_lower = term.lower()
        for category, keywords in science_keywords.items():
            if any(keyword in term_lower for keyword in keywords):
                keyword_score += 0.2

        # Capitalization patterns (scientific terms often have specific capitalization)
        capitalization_score = 0.0
        if term[0].isupper() and not term.isupper():  # Title case
            capitalization_score = 0.1
        elif term.isupper() and len(term) > 2:  # Acronym
            capitalization_score = 0.15

        # Context relevance (if context provided)
        context_score = 0.0
        if context:
            context_lower = context.lower()
            context_keywords = ['study', 'research', 'analysis', 'experiment', 'results', 'data']
            if any(keyword in context_lower for keyword in context_keywords):
                context_score = 0.1

        # Word complexity bonus (multi-word terms are often more specific)
        word_count = len(term.split())
        complexity_score = 0.0
        if 2 <= word_count <= 4:
            complexity_score = 0.1
        elif word_count == 1:
            complexity_score = -0.05

        total_score = min(0.3 + entity_weight + keyword_score + capitalization_score + context_score + complexity_score, 1.0)
        return total_score

    def extract_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Extract terms from a single text document"""
        if not text or not text.strip():
            return []

        all_terms = []
        term_contexts = defaultdict(list)

        for model_name, nlp in self.models.items():
            try:
                doc = nlp(text)

                for ent in doc.ents:
                    term = ent.text.strip()
                    if len(term) < 2:  # Skip very short terms
                        continue

                    # Get context (sentence)
                    sent = ent.sent.text if ent.sent else ""

                    # Apply filters
                    if not self._apply_filters(term):
                        continue

                    # ENHANCED: Apply normalization and entity refinement from reference terms.py
                    canonical_form = self._normalize_term(term, use_synonym_map=True)
                    if not canonical_form:
                        continue

                    original_label = ent.label_
                    refined_label = self._refine_entity_label(canonical_form, original_label)

                    # Calculate relevance score with refined entity label
                    relevance_score = self._calculate_science_relevance(canonical_form, sent, refined_label)
                    if relevance_score < 0.1:  # Skip very low relevance terms
                        continue

                    term_data = {
                        'term': canonical_form,  # Use normalized form
                        'primary_form': term,    # Keep original for reference
                        'label': refined_label,  # Use refined label
                        'original_label': original_label,  # Keep original for traceability
                        'model': model_name,
                        'start': ent.start_char,
                        'end': ent.end_char,
                        'context': sent,
                        'relevance_score': relevance_score,
                        'confidence': 1.0  # Default confidence
                    }

                    all_terms.append(term_data)
                    term_contexts[canonical_form.lower()].append(sent)

            except Exception as e:
                logger.warning(f"Error processing with model {model_name}: {e}")
                continue

        # Aggregate terms by canonical form (case-insensitive)
        aggregated_terms = {}
        for term_data in all_terms:
            canonical_term = term_data['term']
            canonical_lower = canonical_term.lower()

            if canonical_lower not in aggregated_terms:
                aggregated_terms[canonical_lower] = {
                    'term': canonical_term,  # Normalized canonical form
                    'primary_forms': [],      # List of original forms
                    'models_used': [],
                    'labels': [],
                    'original_labels': [],    # Track original entity labels
                    'examples': [],
                    'relevance_score': 0.0,
                    'frequency': 0,
                    'raw_entities': []
                }

            agg = aggregated_terms[canonical_lower]
            agg['models_used'].append(term_data['model'])
            agg['labels'].append(term_data['label'])
            agg['original_labels'].append(term_data.get('original_label', term_data['label']))
            agg['examples'].append(term_data['context'])
            agg['primary_forms'].append(term_data.get('primary_form', canonical_term))
            agg['relevance_score'] = max(agg['relevance_score'], term_data['relevance_score'])
            agg['frequency'] += 1
            agg['raw_entities'].append(term_data)

        # Final cleanup and de-duplication
        final_terms = []
        for term_data in aggregated_terms.values():
            # Keep the canonical term as already normalized
            # Get the most common primary form for display purposes
            if term_data['primary_forms']:
                most_common_primary = Counter(term_data['primary_forms']).most_common(1)[0][0]
            else:
                most_common_primary = term_data['term']

            # Clean up lists and remove duplicates
            term_data['models_used'] = list(set(term_data['models_used']))
            term_data['labels'] = list(set(term_data['labels']))
            term_data['original_labels'] = list(set(term_data['original_labels']))
            term_data['examples'] = list(set(term_data['examples']))[:3]  # Keep top 3 unique examples
            term_data['primary_forms'] = list(set(term_data['primary_forms']))[:5]  # Keep top 5 variants

            # Add the most common primary form for reference
            term_data['display_form'] = most_common_primary

            final_terms.append(term_data)

        return final_terms

    def extract_from_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Extract terms from a file"""
        try:
            file_path = Path(file_path)

            if file_path.suffix.lower() == '.json':
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Handle different JSON structures
                    if isinstance(data, list):
                        text = ' '.join(str(item) for item in data)
                    elif isinstance(data, dict):
                        # Try common text fields
                        text = data.get('text', data.get('content', str(data)))
                    else:
                        text = str(data)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()

            return self.extract_from_text(text)

        except Exception as e:
            logger.error(f"Error extracting terms from {file_path}: {e}")
            return []


def create_terms_extractor(config: SciSpaCyConfig) -> TermsExtractor:
    """Factory function to create terms extractor"""
    return TermsExtractor(config)