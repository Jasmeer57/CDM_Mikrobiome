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
Extract structured biomedical entities for Microbiome Common Data Model from this text.

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