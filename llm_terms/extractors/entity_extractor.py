"""
Entity Extractor Module for CDM Pipeline
"""

import json
import logging
import re
from typing import List, Dict, Tuple, Optional
from config.cdm_config import CDMEntityConfig
from core.llm_client import LLMClient
from core.confidence_scorer import ConfidenceScorer

logger = logging.getLogger(__name__)

class CDMEntityExtractor:
    """Extracts CDM-structured biomedical entities from text."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.entity_config = CDMEntityConfig()
        self.confidence_scorer = ConfidenceScorer(self.entity_config)

    def create_extraction_prompt(self, chunk_text: str) -> str:
        """Create structured prompt for CDM entity extraction."""
        return f"""
Extract EVERY SINGLE biomedical and scientific term from this text.
Focus on capturing a comprehensive list of scientific concepts, biological entities, and medical terms.
Be EXTREMELY EXHAUSTIVE. Aim to extract 100+ terms if present.
Do not filter out common terms. If it is a scientific term, EXTRACT IT.
For longer texts, do not stop until you have extracted ALL relevant entities.

TEXT:
{chunk_text}

Return ONLY a JSON array with objects containing:
{{
  "entity": "extracted term",
  "entity_type": "one of: ORGANISM|PROTEIN|CHEMICAL|DISEASE|DNA_RNA|CELL_TYPE|SAMPLE_METHOD|LAB_METHOD|DATA_ANALYSIS|PATHWAY|EXPERIMENTAL_METHOD|STUDY_DESIGN|GENOMICS|CLINICAL",
  "context": "brief context or description"
}}

CDM Entity Types and Examples:
- ORGANISM: Bacteria, archaea, fungi, viruses, taxa, microbiota (e.g., "Bacteroides fragilis", "E. coli", "Firmicutes", "gut microbiota", "microbiome")
- PROTEIN: Proteins, enzymes, receptors, antibodies (e.g., "butyrate kinase", "lipopolysaccharide", "cytokine", "immunoglobulin")
- CHEMICAL: Metabolites, SCFAs, compounds, biochemical substances (e.g., "butyrate", "propionate", "glucose", "amino acids", "TMAO")
- DISEASE: Diseases, conditions, disorders, syndromes (e.g., "ulcerative colitis", "Crohn's disease", "diabetes", "cancer", "obesity")
- DNA_RNA: Genetic material, sequences, nucleic acids (e.g., "16S rRNA", "bacterial DNA", "mRNA", "mitochondrial DNA", "V4 region")
- CELL_TYPE: Cell types, immune cells, tissue types (e.g., "macrophages", "T-cells", "epithelial cells", "stem cells")
- SAMPLE_METHOD: Sample collection methods (e.g., "fecal samples", "oral gavage", "blood collection", "tissue biopsy")
- LAB_METHOD: Laboratory techniques and instruments (e.g., "Illumina MiSeq", "PCR", "sequencing", "mass spectrometry", "GC-MS", "LC-MS")
- DATA_ANALYSIS: Statistical and bioinformatics analysis methods (e.g., "OTUs", "UniFrac", "PCoA", "PERMANOVA", "Random Forests", "Shannon diversity")
- PATHWAY: Metabolic and signaling pathways (e.g., "glycolysis", "TCA cycle", "butyrate synthesis", "fatty acid metabolism")
- EXPERIMENTAL_METHOD: Experimental procedures (e.g., "calorie restriction", "cohousing", "fecal transplantation", "dietary intervention")
- STUDY_DESIGN: Study design terms (e.g., "case-control", "longitudinal", "CRON", "AMER", "twin cohort")
- GENOMICS: Genomics and omics technologies (e.g., "metagenomics", "phylogenetics", "gene content", "functional diversity")
- CLINICAL: Clinical terms and treatments (e.g., "probiotics", "antibiotics", "nutritional therapy", "BMI", "biomarkers")

Requirements:
1. Extract ALL relevant biomedical entities
2. Use exact entity_type from the list above
3. Provide accurate entity names
4. Keep entities concise and specific
5. Include only microbiome-related entities
"""

    def parse_llm_response(self, response: str, chunk_num: int) -> List[Dict]:
        """Parse LLM response and extract entities with robust cleaning."""
        entities = []
        try:
            # 1. Aggressive Cleanup of Chain-of-Thought (<think>...</think>)
            cleaned_response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
            if '<think>' in cleaned_response:
                 cleaned_response = re.sub(r'<think>.*', '', cleaned_response, flags=re.DOTALL)
            
            cleaned_response = re.sub(r'^Here is the list.*?:', '', cleaned_response, flags=re.IGNORECASE | re.MULTILINE)
            
            # Remove Markdown code blocks if present
            cleaned_response = re.sub(r'```[a-zA-Z]*\n', '', cleaned_response)
            cleaned_response = re.sub(r'```', '', cleaned_response)
            
            cleaned_response = cleaned_response.strip()

            # 2. Try to parse as JSON first (Robust substring search)
            # Find the JSON structure irrespective of surrounding noise
            try:
                json_start = -1
                json_end = -1
                
                # Check for array
                arr_start = cleaned_response.find('[')
                arr_end = cleaned_response.rfind(']')
                
                # Check for object
                obj_start = cleaned_response.find('{')
                obj_end = cleaned_response.rfind('}')
                
                # Determine which outer structure to capture (prefer array for entity list)
                if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
                    json_start = arr_start
                    json_end = arr_end + 1
                elif obj_start != -1 and obj_end != -1 and obj_end > obj_start:
                    json_start = obj_start
                    json_end = obj_end + 1
                    
                if json_start != -1:
                    json_str = cleaned_response[json_start:json_end]
                    import json
                    import json
                    data = json.loads(json_str)
                    
                    # If it's a dictionary wrapping the list (e.g. {"entities": [...]})
                    if isinstance(data, dict):
                        for key in ['entities', 'terms', 'results', 'output']:
                            if key in data and isinstance(data[key], list):
                                data = data[key]
                                break
                    
                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict): continue
                            
                            term = item.get('entity', item.get('term', '')).strip()
                            entity_type = item.get('entity_type', item.get('type', '')).upper()
                            context = item.get('context', '')
                            definition = item.get('definition', '')
                            aliases = item.get('aliases', [])
                            if isinstance(aliases, str): aliases = [a.strip() for a in aliases.split(',')]
                            examples = item.get('examples', [])
                            if isinstance(examples, str): examples = [e.strip() for e in examples.split(',')]
                            
                            # Map type
                            entity_type = self._map_hallucinated_type(entity_type)

                            # REJECT GENE entities - LLMs keep hallucinating this type
                            if entity_type == 'GENE':
                                continue

                            if self._validate_entity(term, entity_type):
                                entities.append({
                                    'entity': term,
                                    'entity_type': entity_type,
                                    'context': context,
                                    'definition': definition,
                                    'aliases': aliases,
                                    'examples': examples,
                                    'confidence': self.confidence_scorer.calculate_score({
                                        'entity': term,
                                        'entity_type': entity_type,
                                        'context': context,
                                        'definition': definition,
                                        'aliases': aliases,
                                        'examples': examples
                                    }),
                                    'source': f'chunk_{chunk_num}'
                                })
                        
                        if entities:
                            return entities
                            
            except json.JSONDecodeError:
                pass # Fallback to line parsing

            # 3. Strict Line-by-Line Parsing
            # We expect: "- Term (TYPE): Context"
            lines = cleaned_response.split('\n')
            for line in lines:
                line = line.strip()
                if not line: continue
                
                # Skip conversational lines
                if line.lower().startswith(('here are', 'sure', 'i have', 'note:', 'however', 'let\'s list', 'but', 'also', 'the text', 'actually', 'for example', 'in this text', 'output:', 'extracted terms:')):
                    continue

                # Split by pipe to separate main term info from extra details
                parts = line.split('|')
                main_part = parts[0].strip()
                
                # Regex to capture: Optional bullet, Term, (TYPE), Optional Context
                match = re.match(r'^(?:[\-\*0-9\.]+\s*)?(.+?)\s*\(([^)]+)\)(?:\s*[:\-]\s*(.+))?$', main_part)
                
                if match:
                    term = match.group(1).strip()
                    entity_type = match.group(2).strip().upper()
                    context = match.group(3).strip() if match.group(3) else ""
                    
                    # Cleanup term - Remove common JSON artifacts if regex matched them
                    # e.g. 'answer": "- Term' -> 'Term'
                    if '":' in term:
                         term = term.split('":')[-1].strip()
                    if '":"' in term:
                         term = term.split('":"')[-1].strip()
                    
                    term = term.strip('"\'').strip('-').strip()
                    
                    # Map hallucinated types
                    entity_type = self._map_hallucinated_type(entity_type)

                    # REJECT GENE entities - LLMs keep hallucinating this type
                    if entity_type == 'GENE':
                        continue

                    # Parse extra fields
                    definition = ""
                    aliases = []
                    examples = []
                    
                    for part in parts[1:]:
                        part = part.strip()
                        if part.lower().startswith("definition:"):
                            definition = part[11:].strip()
                        elif part.lower().startswith("aliases:"):
                            aliases_str = part[8:].strip()
                            if aliases_str and aliases_str.lower() != "none":
                                aliases = [a.strip() for a in aliases_str.split(',')]
                        elif part.lower().startswith("examples:"):
                            examples_str = part[9:].strip()
                            if examples_str and examples_str.lower() != "none":
                                examples = [e.strip() for e in examples_str.split(',')]

                    if self._validate_entity(term, entity_type):
                        entities.append({
                            'entity': term,
                            'entity_type': entity_type,
                            'context': context,
                            'definition': definition,
                            'aliases': aliases,
                            'examples': examples,
                            'confidence': self.confidence_scorer.calculate_score({
                                'entity': term,
                                'entity_type': entity_type,
                                'context': context,
                                'definition': definition,
                                'aliases': aliases,
                                'examples': examples
                            }),
                            'source': f'chunk_{chunk_num}'
                        })

        except Exception as e:
            logger.error(f"Error parsing LLM response for chunk {chunk_num}: {e}")
            
        return entities

    def _map_hallucinated_type(self, entity_type: str) -> str:
        """Map hallucinated or non-standard types to valid CDM types."""
        entity_type = entity_type.upper()
        
        # Direct mapping
        if entity_type in self.entity_config.ENTITY_TYPES:
            return entity_type
            
        # Common hallucinations
        mappings = {
            'BACTERIA': 'ORGANISM',
            'SPECIES': 'ORGANISM',
            'MICROBE': 'ORGANISM',
            'PROTEINS': 'PROTEIN',
            'METABOLITE': 'CHEMICAL',
            'COMPOUND': 'CHEMICAL',
            'DRUG': 'CHEMICAL',
            'CONDITION': 'DISEASE',
            'DISORDER': 'DISEASE',
            'PATHWAY': 'BIOINFO_TOOL',
            'METHOD': 'GENOMICS',
            'SEQUENCING': 'GENOMICS'
        }
        
        return mappings.get(entity_type, entity_type)

    def _validate_entity(self, term: str, entity_type: str) -> bool:
        """Validate entity structure and content."""
        if not term or not isinstance(term, str) or len(term) < 2:
            return False
            
        # Check if type is valid
        if entity_type not in self.entity_config.ENTITY_TYPES:
            return False

        # Check for pure numbers or simple units
        if re.match(r'^[\d\.,\s%±<>≤≥=°]+$', term):
            return False
            
        # Check specifically for temperature-like terms
        if '°' in term:
             return False
            
        # Check for generic words (stop words)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        if term.lower() in stop_words:
            return False

        # Convert to lowercase once for all comparisons
        term_lower = term.lower()

        # Noise terms to filter out (common non-entity terms)
        noise_terms = {
            'et al', 'figure', 'fig', 'table', 'supplemental', 'supplementary',
            'data', 'study', 'analysis', 'result', 'results', 'method', 'methods',
            'significant', 'significantly', 'associated', 'correlation', 'p-value',
            'abstract', 'introduction', 'discussion', 'conclusion', 'materials',
            'background', 'objective', 'design', 'setting', 'participants', 'measures',
            'compared', 'versus', 'vs', 'respectively', 'however', 'therefore', 'thus',
            'hence', 'although', 'though', 'whereas', 'whether', 'while', 'during',
            'following', 'before', 'after', 'between', 'among', 'within', 'without',
            'according', 'based', 'using', 'used', 'including', 'included', 'excluding'
        }

        # Check for Author names and Affiliations (Junk filtering)
        if 'et al' in term_lower:
            return False

        # Check for these terms (case-insensitive)
        if term_lower in noise_terms:
            return False

        # Check for terms that are just numbers with common units
        if re.match(r'^[\d\.]+\s*(?:mg|ml|ug|ng|mm|cm|kg|hr|min|sec|day|week|month|year|%|fold|log2|ratio)$', term):
            return False

        # Check for general scientific methods that are not entities
        if entity_type in ['DATA_ANALYSIS', 'EXPERIMENTAL_METHOD', 'STUDY_DESIGN']:
            if any(kw in term_lower for kw in ['method', 'analysis', 'protocol', 'technique', 'approach', 'study', 'design']):
                 return False

        # Additional patterns for tool/software/algorithm filtering (case-insensitive)
        tool_patterns = [
            r'.*algorithm.*', r'.*software.*', r'.*package.*', r'.*pipeline.*',
            r'.*tool.*', r'.*database.*', r'.*web_tool.*', r'.*web_application.*',
            r'.*r_package.*', r'.*python_package.*', r'.*toolchain.*', r'.*framework.*',
            r'.*approach.*', r'.*strategy.*', r'.*system.*', r'.*platform.*',
            r'.*principle.*', r'.*concept.*', r'.*process.*', r'.*technique.*',
            r'.*assay.*', r'.*kit.*', r'.*panel.*', r'.*array.*', r'.*sequencing_method.*',
            r'.*omics_method.*', r'.*microbiome_analyst.*', r'.*uparse.*',
            r'.*corrplot.*', r'.*bestglm.*', r'.*deseq2.*', r'.*qiime2.*', r'.*dada2.*',
            r'.*mothur.*', r'.*silva.*', r'.*greengenes.*', r'.*unifrac.*', r'.*bray_curtis.*',
            r'.*pca.*', r'.*random_forest.*', r'.*kegg.*', r'.*tigr.*', r'.*blast.*',
            r'.*hmmer.*', r'.*fastq.*', r'.*samtools.*', r'.*bowtie2.*', r'.*bwa.*',
            r'.*macs2.*', r'.*trimmomatic.*', r'.*snps.*', r'.*indel.*', r'.*mutation.*',
            r'.*genomic_region.*', r'.*exome.*', r'.*genome.*', r'.*transcriptome.*',
            r'.*proteome.*', r'.*metabolome.*', r'.*lipidome.*', r'.*epigenome.*',
            r'.*microbiome.*', r'.*microbiota.*', r'.*microbial_community.*',
            r'.*gut_microbiota.*', r'.*bacterial_community.*', r'.*archaeal_community.*',
            r'.*fungal_community.*', r'.*viral_community.*', r'.*pathogen.*', r'.*commensal.*',
            r'.*probiotic.*', r'.*prebiotic.*', r'.*antibiotic.*', r'.*antimicrobial.*',
            r'.*dysbiosis.*', r'.*eubiosis.*', r'.*health.*', r'.*disease.*',
            r'.*syndrome.*', r'.*condition.*', r'.*disorder.*', r'.*phenotype.*',
            r'.*genotype.*', r'.*haplotype.*', r'.*genotype_phenotype.*', r'.*meta_analysis.*'
        ]

        if any(re.match(pattern, term_lower) for pattern in tool_patterns):
            return False

        return True


    def _get_pass_prompt(self, pass_num: int, chunk_text: str, existing_terms: List[str] = None) -> str:
        """Generate specific prompt for each extraction pass."""

        # Few-shot examples for each entity type to prevent misclassification
        entity_examples = """
EXAMPLES OF CORRECT ENTITY CLASSIFICATION:

ORGANISM (microbes, animals, humans):
- "Bacteroides thetaiotaomicron" → ORGANISM
- "Faecalibacterium prausnitzii" → ORGANISM
- "C57BL/6J mice" → ORGANISM
- "Ruminococcus sp. Ce2" → ORGANISM
- "Bilophila wadsworthia" → ORGANISM

CHEMICAL (metabolites, compounds, molecules):
- "TMAO" → CHEMICAL
- "propionate" → CHEMICAL
- "acetate" → CHEMICAL
- "succinate" → CHEMICAL
- "lactate" → CHEMICAL
- "bile acids" → CHEMICAL
- "chiro-inositol" → CHEMICAL
- "alpha-ketoglutarate" → CHEMICAL

PROTEIN (specific named proteins):
- "insulin" → PROTEIN
- "amylase" → PROTEIN
- "TLR4" → PROTEIN

DISEASE:
- "atherosclerosis" → DISEASE
- "type 2 diabetes" → DISEASE
- "colorectal cancer" → DISEASE

DNA_RNA:
- "16S rRNA" → DNA_RNA
- "V4 region" → DNA_RNA
- "23S rRNA gene" → DNA_RNA

SAMPLE_METHOD (sample collection/prep):
- "fecal sampling" → SAMPLE_METHOD
- "bead beating" → SAMPLE_METHOD
- "frozen at -80°C" → SAMPLE_METHOD
- "RNAlater" → SAMPLE_METHOD

LAB_METHOD (lab techniques):
- "Illumina MiSeq" → LAB_METHOD
- "qPCR" → LAB_METHOD
- "V4 region PCR" → LAB_METHOD
- "flow cytometry" → LAB_METHOD
- "Nanopore sequencing" → LAB_METHOD

DATA_ANALYSIS (statistics/bioinformatics):
- "PERMANOVA" → DATA_ANALYSIS
- "Bray-Curtis" → DATA_ANALYSIS
- "Random Forest" → DATA_ANALYSIS
- "QIIME2" → DATA_ANALYSIS
- "Linear mixed-effects models" → DATA_ANALYSIS

EXPERIMENTAL_METHOD:
- "calorie restriction" → EXPERIMENTAL_METHOD
- "cohousing" → EXPERIMENTAL_METHOD
- "oral gavage" → EXPERIMENTAL_METHOD

PATHWAY:
- "glycolysis" → PATHWAY
- "TCA cycle" → PATHWAY
- "bile acid metabolism" → PATHWAY

STUDY_DESIGN:
- "case-control" → STUDY_DESIGN
- "longitudinal cohort" → STUDY_DESIGN
- "CRON diet" → STUDY_DESIGN

CLINICAL:
- "BMI" → CLINICAL
- "blood pressure" → CLINICAL
- "nutrient intake" → CLINICAL

GENOMICS:
- "metagenomics" → GENOMICS
- "metatranscriptomics" → GENOMICS
- "whole genome sequencing" → GENOMICS
"""

        system_context = f"""You are an expert biomedical NER (Named Entity Recognition) system. Your task is to extract and classify biomedical entities with HIGH PRECISION.

CRITICAL CLASSIFICATION RULES (READ CAREFULLY):
6. When uncertain, use the entity's CONTEXT and SCIENTIFIC DOMAIN to classify correctly

{entity_examples}

EXTRACTION RULES:
1. Extract ALL concrete biomedical entities from the text
2. Classify each entity into its correct type using the examples above
3. Pay attention to suffixes and prefixes:
   - Words ending in "-ate", "-ol", "-ine", "-ic acid" → likely CHEMICAL
   - Words ending in "-ase" → likely ENZYME/PROTEIN
   - Latin binomials (Genus species) → ORGANISM
   - Words starting with "PCR", "sequencing", "analysis" → METHODS
4. Include terms from ALL biomedical domains
5. NEVER extract your own instructions or conversational phrases

OUTPUT: Return ONLY a JSON array with objects containing:
{{
  "entity": "extracted term",
  "entity_type": "one of: ORGANISM|PROTEIN|CHEMICAL|DISEASE|DNA_RNA|CELL_TYPE|SAMPLE_METHOD|LAB_METHOD|DATA_ANALYSIS|PATHWAY|EXPERIMENTAL_METHOD|STUDY_DESIGN|GENOMICS|CLINICAL",
  "context": "brief description"
}}"""

        if pass_num == 1:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL biological organisms and taxonomic entities.

FOCUS ON - ORGANISM type:
- Bacterial species: "Bacteroides thetaiotaomicron", "Faecalibacterium prausnitzii"
- Bacterial genera: "Bacteroides", "Prevotella", "Ruminococcus"
- Fungi: "Candida albicans", "Saccharomyces"
- Viruses: "influenza A", "bacteriophage"
- Animals: "C57BL/6J mice", "gnotobiotic mice", " Sprague-Dawley rats"
- Humans: "human subjects", "patients"

CLASSIFICATION RULES:
- Use ORGANISM for all living things
- Include strain names: "Ruminococcus sp. Ce2" → ORGANISM

TEXT:
{chunk_text}"""

        elif pass_num == 2:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL chemicals, metabolites, and molecular entities.

FOCUS ON - CHEMICAL type:
- Short-chain fatty acids: "acetate", "propionate", "butyrate", "succinate"
- Bile acids: "cholic acid", "deoxycholic acid"
- Amino acids: "leucine", "isoleucine", "tryptophan"
- Sugars: "glucose", "inositol", "pinitol"
- Metabolites: "TMAO", "lactate", "pyruvate", "citrate"
- Compounds: "alpha-ketoglutarate", "methylmalonyl-CoA"

FOCUS ON - PROTEIN type:
- Enzymes: "amylase", "protease", "lipase"
- Proteins: "insulin", "glucagon", "cytokine"
- NOT generic terms

CLASSIFICATION RULES:
- Metabolites ending in "-ate", "-ol", "-ic acid" → CHEMICAL
- Enzymes ending in "-ase" → PROTEIN (or CHEMICAL if metabolic)
- Gene names usually include "gene" or are specific symbols: "lct gene"

TEXT:
{chunk_text}"""

        elif pass_num == 3:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL methodological terms - classify carefully into 3 categories:

1. SAMPLE_METHOD (sample collection/prep):
   - "fecal sampling" → SAMPLE_METHOD
   - "bead beating" → SAMPLE_METHOD
   - "frozen at -80°C" → SAMPLE_METHOD
   - "RNAlater" → SAMPLE_METHOD
   - "oral gavage" → SAMPLE_METHOD

2. LAB_METHOD (wet lab techniques):
   - "Illumina MiSeq" → LAB_METHOD
   - "qPCR" → LAB_METHOD
   - "V4 region PCR" → LAB_METHOD
   - "flow cytometry" → LAB_METHOD
   - "Nanopore sequencing" → LAB_METHOD
   - "Nextera XT" → LAB_METHOD (kit)
   - "GC-MS" → LAB_METHOD

3. DATA_ANALYSIS (computational/statistical methods):
   - "PERMANOVA" → DATA_ANALYSIS
   - "Bray-Curtis" → DATA_ANALYSIS
   - "Random Forest" → DATA_ANALYSIS
   - "QIIME2" → DATA_ANALYSIS
   - "Linear mixed-effects models" → DATA_ANALYSIS
   - "Shannon diversity" → DATA_ANALYSIS

CRITICAL RULES:
- Kits are LAB_METHOD, not CHEMICAL
- Be precise with the 3 categories

TEXT:
{chunk_text}"""

        elif pass_num == 4:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL diseases, clinical terms, and pathways.

FOCUS ON - DISEASE type:
- "atherosclerosis" → DISEASE
- "type 2 diabetes" → DISEASE
- "colorectal cancer" → DISEASE
- "inflammatory bowel disease" → DISEASE
- "obesity" → DISEASE

FOCUS ON - PATHWAY type:
- "glycolysis" → PATHWAY
- "TCA cycle" → PATHWAY
- "bile acid metabolism" → PATHWAY
- "fatty acid oxidation" → PATHWAY

FOCUS ON - EXPERIMENTAL_METHOD:
- "calorie restriction" → EXPERIMENTAL_METHOD
- "cohousing" → EXPERIMENTAL_METHOD
- "high-fat diet" → EXPERIMENTAL_METHOD

FOCUS ON - STUDY_DESIGN:
- "case-control" → STUDY_DESIGN
- "longitudinal" → STUDY_DESIGN
- "randomized controlled trial" → STUDY_DESIGN
- "CRON diet" → STUDY_DESIGN

FOCUS ON - CLINICAL:
- "BMI" → CLINICAL
- "blood pressure" → CLINICAL
- "nutrient intake" → CLINICAL
- "body weight" → CLINICAL

CRITICAL RULES:

TEXT:
{chunk_text}"""

        elif pass_num == 5:
            existing_str = ', '.join(existing_terms[:30]) if existing_terms else "None"
            return f"""{system_context}

EXTRACTION GOAL: Final comprehensive sweep - extract ANY remaining biomedical terms.

LOOK FOR:
- DNA/RNA terms: "16S rRNA", "V4 region", "23S rRNA gene" → DNA_RNA
- Genomics terms: "metagenomics", "metatranscriptomics" → GENOMICS
- Cell types: "macrophages", "T-cells", "enterocytes" → CELL_TYPE
- Any remaining organisms, chemicals, methods

REMEMBER CLASSIFICATION RULES:

TERMS ALREADY EXTRACTED:
{existing_str}

TEXT:
{chunk_text}"""

        elif pass_num == 6:
            return f"""{system_context}

EXTRACTION GOAL: AGGRESSIVE final sweep - extract ANY biomedical terms.

BE VERY INCLUSIVE BUT ACCURATE:
- Extract ANY scientific, technical, or biomedical term
- Double-check classifications:
- Use the examples from system context to guide classification

TEXT:
{chunk_text}"""
        
        return self.create_extraction_prompt(chunk_text)

    def run_extraction_pass(self, pass_data: Tuple[str, int, List[str]]) -> List[Dict]:
        """Execute a single extraction pass on a specific text window."""
        text, pass_num, existing_terms = pass_data
        logger.info(f"🚀 Starting Pass {pass_num} on {len(text)} chars")
        
        prompt = self._get_pass_prompt(pass_num, text, existing_terms)
        
        # Use lower temperature for aggressive pass
        # We can't easily set temp per call in current LLMClient, so we rely on prompt instructions
        response = self.llm_client.call_llm(prompt, max_tokens=4000)
        
        if not response:
            logger.warning(f"⚠️ Pass {pass_num} returned no response")
            return []
            
        # Limit logging to first 200 chars to avoid sensitive data leakage
        logger.debug(f"🔍 Raw LLM Response (Pass {pass_num}):\n{response[:200]}...")
        entities = self.parse_llm_response(response, pass_num)
        logger.info(f"✅ Pass {pass_num} found {len(entities)} entities")
        return entities

    def extract_entities_from_chunk(self, chunk_data: Tuple[str, int]) -> Tuple[int, List[Dict]]:
        """Extract entities from a single chunk."""
        chunk_text, chunk_num = chunk_data
        logger.info(f"📄 Processing chunk {chunk_num} ({len(chunk_text)} chars)")

        # Get LLM response
        prompt = self.create_extraction_prompt(chunk_text)
        response = self.llm_client.call_llm(prompt, max_tokens=4000)

        if not response:
            logger.warning(f"No LLM response for chunk {chunk_num}")
            return chunk_num, []

        # Parse entities from response
        entities = self.parse_llm_response(response, chunk_num)

        logger.info(f"    Chunk {chunk_num}: Found {len(entities)} entities")
        return chunk_num, entities

    def calculate_optimal_chunk_size(self, text_length: int) -> int:
        """Calculate optimal chunk size based on text length."""
        return self.entity_config.get_chunk_size(text_length)

    def calculate_overlap(self, chunk_size: int) -> int:
        """Calculate optimal overlap for chunking."""
        return self.entity_config.get_overlap(chunk_size)