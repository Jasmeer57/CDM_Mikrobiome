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
  "entity_type": "one of: ORGANISM|GENE|PROTEIN|CHEMICAL|DISEASE|DNA_RNA|CELL_TYPE|BIOINFO_TOOL|GENOMICS|CLINICAL",
  "context": "brief context or description"
}}

CDM Entity Types and Examples:
- ORGANISM: Bacteria, archaea, fungi, viruses, taxa (e.g., "Bacteroides fragilis", "E. coli", "Firmicutes", "Archaea")
- GENE: Gene names, genetic markers, transcription factors (e.g., "IL6", "TNF-alpha", "TLR4", "NF-kB", "p53")
- PROTEIN: Proteins, enzymes, receptors, antibodies (e.g., "butyrate kinase", "lipopolysaccharide", "cytokine", "immunoglobulin")
- CHEMICAL: Metabolites, SCFAs, compounds, biochemical substances (e.g., "butyrate", "propionate", "glucose", "amino acids")
- DISEASE: Diseases, conditions, disorders, syndromes (e.g., "ulcerative colitis", "Crohn's disease", "diabetes", "cancer")
- DNA_RNA: Genetic material, sequences, nucleic acids (e.g., "16S rRNA", "bacterial DNA", "mRNA", "mitochondrial DNA")
- CELL_TYPE: Cell types, immune cells, tissue types (e.g., "macrophages", "T-cells", "epithelial cells", "stem cells")
- BIOINFO_TOOL: Bioinformatics tools, software, databases (e.g., "BLAST", "Qiime", "MetaPhlAn", "shotgun sequencing")
- GENOMICS: Genomics, omics technologies (e.g., "genomics", "transcriptomics", "proteomics", "metabolomics")
- CLINICAL: Clinical terms, medical procedures, treatments (e.g., "therapy", "diagnosis", "clinical trial", "medication")

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
            'GENES': 'GENE',
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
            
        # Check for Author names and Affiliations (Junk filtering)
        if 'et al' in term.lower():
            return False
            
        # Reject if term is in artifacts
        if term.lower() in ['none', 'n/a', 'null', 'unknown']:
            return False
            
        return True


    def _get_pass_prompt(self, pass_num: int, chunk_text: str, existing_terms: List[str] = None) -> str:
        """Generate specific prompt for each extraction pass."""
        
        system_context = """You are a comprehensive biomedical terminology extractor. Extract ALL concrete scientific terms from the text including bioinformatics, molecules, chemicals, organisms, species, and technical biomedical terms.

CRITICAL RULES:
1. Extract ALL biomedical terms: bioinformatics tools, molecules, chemicals, organisms, species, technical terms
2. Include terms from ALL biomedical domains: molecular biology, biochemistry, genetics, bioinformatics, pharmacology, etc.
3. NEVER extract your own instructions, notes, or conversational phrases
4. ONLY extract terms that would be valid entries in a biomedical ontology
5. Be EXTREMELY COMPREHENSIVE - extract any term that appears biomedical or technical in nature.
6. Do not filter out terms because they seem "too common" or "generic". If it is scientific, extract it.

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

OUTPUT: Return ONLY a JSON array with objects containing:
{
  "entity": "extracted term",
  "entity_type": "one of: ORGANISM|GENE|PROTEIN|CHEMICAL|DISEASE|DNA_RNA|CELL_TYPE|BIOINFO_TOOL|GENOMICS|CLINICAL|SCIENTIFIC_TERM",
  "context": "brief context or description"
}"""

        if pass_num == 1:
            return f"""{system_context}

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
{chunk_text}"""

        elif pass_num == 2:
            return f"""{system_context}

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
{chunk_text}"""

        elif pass_num == 3:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL methodological and technical terms, classifying them into these 3 categories:

1. SAMPLE_METHOD:
   - Sample collection (e.g., "fecal sampling", "swabs")
   - Transport & Storage (e.g., "frozen at -80C", "RNAlater")
   - DNA/RNA Extraction (e.g., "PowerSoil Kit", "bead beating")

2. LAB_METHOD:
   - Library Preparation (e.g., "Nextera XT", "V4 region PCR")
   - Sequencing Platforms (e.g., "Illumina MiSeq", "Nanopore")
   - Wet-lab techniques (e.g., "qPCR", "flow cytometry")

3. DATA_ANALYSIS:
   - Bioinformatics Tools (e.g., "QIIME2", "Mothur", "DADA2")
   - Databases (e.g., "SILVA", "GreenGenes", "KEGG")
   - Statistical Methods (e.g., "Bray-Curtis", "PERMANOVA", "Random Forest")

FOCUS ON:
- Capturing the specific commercial names of kits and tools (e.g., "QIAamp DNA Stool Mini Kit").
- Capturing specific sequencing regions (e.g., "V3-V4").
- Capturing software versions if mentioned.

IMPORTANT: You MUST classify each term into one of these 3 types (`SAMPLE_METHOD`, `LAB_METHOD`, `DATA_ANALYSIS`).

TEXT:
{chunk_text}"""

        elif pass_num == 4:
            return f"""{system_context}

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
{chunk_text}"""

        elif pass_num == 5:
            existing_str = ', '.join(existing_terms[:30]) if existing_terms else "None"
            return f"""{system_context}

EXTRACTION GOAL: Extract ANY remaining biomedical terms from ALL categories that haven't been captured yet.

LOOK FOR:
- ANY scientific term related to biology, medicine, chemistry, biochemistry
- ANY technical term mentioned in the text
- ANY domain-specific terminology that appears biomedical
- ANY term that could be part of a biomedical ontology
- Laboratory techniques, experimental methods, analytical approaches
- ANY term from biomedical research that you haven't extracted yet

TERMS ALREADY EXTRACTED (examples):
{existing_str}

TEXT:
{chunk_text}"""

        elif pass_num == 6:
            return f"""{system_context}

EXTRACTION GOAL: AGGRESSIVELY extract ANY biomedical terms.
BE VERY INCLUSIVE:
- Extract ANY term that sounds scientific, technical, or biomedical
- Include method names, technique names, approach names
- Include any compound, molecule, or chemical mentioned
- Include any organism, species, or biological entity
- Include any computational, statistical, or analytical method
- Include any medical, clinical, or pharmaceutical term

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