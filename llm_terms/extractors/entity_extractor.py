"""
Entity Extractor Module for CDM Pipeline
"""

import json
import logging
import re
from typing import List, Dict, Tuple, Optional
from config.cdm_config import CDMEntityConfig
from core.llm_client import LLMClient

logger = logging.getLogger(__name__)

class CDMEntityExtractor:
    """Extracts CDM-structured biomedical entities from text."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.entity_config = CDMEntityConfig()

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
        """Parse LLM response and extract entities."""
        entities = []

        try:
            # Clean the response - remove common LLM artifacts
            cleaned_response = response.strip()

            # Try multiple JSON parsing strategies
            json_entities = self._try_json_parsing(cleaned_response)
            if json_entities:
                entities = json_entities
            else:
                # Fallback: extract entities from unstructured text
                entities.extend(self._extract_from_unstructured_text(cleaned_response, chunk_num))

        except Exception as e:
            logger.error(f"Error parsing LLM response for chunk {chunk_num}: {e}")
            entities.extend(self._fallback_regex_extraction(response, chunk_num))

        return entities

    def _try_json_parsing(self, response: str) -> List[Dict]:
        """Try multiple JSON parsing strategies."""
        entities = []

        # Strategy 1: Direct JSON array parsing
        try:
            if response.startswith('[') and response.endswith(']'):
                parsed = json.loads(response)
                if isinstance(parsed, list):
                    for item in parsed:
                        if self._validate_entity(item):
                            entities.append(self._format_entity(item, 0, 0.9))
                    return entities
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON from text (find JSON blocks)
        try:
            json_blocks = self._extract_json_blocks(response)
            for json_block in json_blocks:
                try:
                    parsed = json.loads(json_block)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if self._validate_entity(item):
                                entities.append(self._format_entity(item, 0, 0.9))
                    elif isinstance(parsed, dict) and self._validate_entity(parsed):
                        entities.append(self._format_entity(parsed, 0, 0.9))
                except json.JSONDecodeError:
                    continue
            if entities:
                return entities
        except Exception:
            pass

        # Strategy 3: Parse line-by-line JSON objects
        try:
            lines = response.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith('{') and line.endswith('}'):
                    try:
                        parsed = json.loads(line)
                        if self._validate_entity(parsed):
                            entities.append(self._format_entity(parsed, 0, 0.9))
                    except json.JSONDecodeError:
                        continue
            if entities:
                return entities
        except Exception:
            pass

        return []

    def _extract_json_blocks(self, text: str) -> List[str]:
        """Extract JSON blocks from mixed text."""
        json_blocks = []
        stack = []
        start_idx = None

        for i, char in enumerate(text):
            if char == '{':
                if not stack:
                    start_idx = i
                stack.append(char)
            elif char == '}':
                if stack:
                    stack.pop()
                    if not stack and start_idx is not None:
                        # Found complete JSON object
                        json_block = text[start_idx:i+1]
                        json_blocks.append(json_block)
                        start_idx = None

        return json_blocks

    def _validate_entity(self, entity: Dict) -> bool:
        """Validate entity structure and content."""
        if not isinstance(entity, dict):
            return False

        required_fields = ['entity', 'entity_type']
        if not all(field in entity for field in required_fields):
            return False

        if entity['entity_type'] not in self.entity_config.ENTITY_TYPES:
            return False

        entity_name = entity['entity'].strip()
        if len(entity_name) < 2 or len(entity_name) > 100:
            return False

        return True

    def _format_entity(self, entity: Dict, chunk_num: int, confidence: float) -> Dict:
        """Format entity into standard structure."""
        return {
            'entity': entity['entity'].strip(),
            'entity_type': entity['entity_type'],
            'context': entity.get('context', '').strip()[:200],
            'source': f'chunk_{chunk_num}',
            'confidence': confidence
        }

    def _extract_from_unstructured_text(self, text: str, chunk_num: int) -> List[Dict]:
        """Extract entities from unstructured LLM response."""
        entities = []
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.startswith(('#', '//', '-', '*')):
                continue

            # Look for entity type indicators
            for entity_type in self.entity_config.ENTITY_TYPES:
                if entity_type in line.upper():
                    # Extract entity before or after the type
                    entity_match = re.search(r'([A-Za-z0-9\s\-_\.]+)', line)
                    if entity_match:
                        entity = entity_match.group(1).strip()
                        if len(entity) > 2 and len(entity) < 100:
                            entities.append(self._format_entity({
                                'entity': entity,
                                'entity_type': entity_type,
                                'context': line[:100]
                            }, chunk_num, 0.7))
                    break

        return entities

    def _fallback_regex_extraction(self, text: str, chunk_num: int) -> List[Dict]:
        """Fallback extraction using regex patterns."""
        entities = []

        for entity_type, config in self.entity_config.ENTITY_TYPES.items():
            if 'patterns' in config:
                for pattern in config['patterns']:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = [m for m in match if m][0] if match else ""
                        if match and len(match) > 2:
                            entities.append(self._format_entity({
                                'entity': match.strip(),
                                'entity_type': entity_type,
                                'context': f"Regex extraction from chunk {chunk_num}"
                            }, chunk_num, 0.6))

        return entities

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
            
        logger.debug(f"🔍 Raw LLM Response (Pass {pass_num}):\n{response[:500]}...") # Log first 500 chars
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