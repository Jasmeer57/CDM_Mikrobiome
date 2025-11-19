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

    def _calculate_science_relevance(self, term: str, context: str = "") -> float:
        """Calculate science relevance score for a term"""
        if not term or len(term) < 2:
            return 0.0

        # Base score from length (longer terms tend to be more scientific)
        length_score = min(len(term) / 10.0, 1.0)

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

        total_score = min(length_score + keyword_score + capitalization_score + context_score, 1.0)
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

                    # Calculate relevance score
                    relevance_score = self._calculate_science_relevance(term, sent)
                    if relevance_score < 0.1:  # Skip very low relevance terms
                        continue

                    term_data = {
                        'term': term,
                        'label': ent.label_,
                        'model': model_name,
                        'start': ent.start_char,
                        'end': ent.end_char,
                        'context': sent,
                        'relevance_score': relevance_score,
                        'confidence': 1.0  # Default confidence
                    }

                    all_terms.append(term_data)
                    term_contexts[term.lower()].append(sent)

            except Exception as e:
                logger.warning(f"Error processing with model {model_name}: {e}")
                continue

        # Aggregate terms by text (case-insensitive)
        aggregated_terms = {}
        for term_data in all_terms:
            term = term_data['term']
            term_lower = term.lower()

            if term_lower not in aggregated_terms:
                aggregated_terms[term_lower] = {
                    'term': term,
                    'models_used': [],
                    'labels': [],
                    'examples': [],
                    'relevance_score': 0.0,
                    'frequency': 0,
                    'raw_entities': []
                }

            agg = aggregated_terms[term_lower]
            agg['models_used'].append(term_data['model'])
            agg['labels'].append(term_data['label'])
            agg['examples'].append(term_data['context'])
            agg['relevance_score'] = max(agg['relevance_score'], term_data['relevance_score'])
            agg['frequency'] += 1
            agg['raw_entities'].append(term_data)

        # Final cleanup and de-duplication
        final_terms = []
        for term_data in aggregated_terms.values():
            # Keep the most common capitalization
            term_variants = [e['term'] for e in term_data['raw_entities']]
            most_common = Counter(term_variants).most_common(1)[0][0]
            term_data['term'] = most_common

            # Clean up lists
            term_data['models_used'] = list(set(term_data['models_used']))
            term_data['labels'] = list(set(term_data['labels']))
            term_data['examples'] = list(set(term_data['examples']))[:3]  # Keep top 3 unique examples

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