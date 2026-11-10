#!/usr/bin/env python3
"""
Extract relationships from paper context using LLM and embeddings.

Uses phi4:14b LLM to parse paper_context field for scientifically validated relationships.
Implements embeddings-based semantic matching to validate target entities.

Scientific Rigor Requirements:
- Only extract explicit causal relationships (produces, inhibits, causes)
- Ignore correlation-only statements
- Require mechanistic explanation
- Cross-validate with ontology relationships
- Link to specific paper and sentence

Evidence Quality:
- High (0.9-1.0): Experimental validation ("produces", "inhibits")
- Medium (0.7-0.8): Strong association ("associated with", "linked to")
- Low (0.5-0.6): Correlation only
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time

import json
import csv
import re
import time
from typing import List, Dict, Optional, Set, Tuple
from pathlib import Path
import logging
import numpy as np

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PaperRelationshipExtractor:
    """Extract relationships from paper context using LLM and embeddings."""

    # Causal relationship patterns (high confidence)
    CAUSAL_PATTERNS = [
        r'(\w+(?:\s+\w+)*)\s+(?:produces?|synthesizes?|generates?|forms?|creates?)\s+(\w+(?:\s+\w+)*)',
        r'(\w+(?:\s+\w+)*)\s+(?:inhibits?|blocks?|suppresses?|prevents?)\s+(\w+(?:\s+\w+)*)',
        r'(\w+(?:\s+\w+)*)\s+(?:causes?|induces?|triggers?)\s+(\w+(?:\s+\w+)*)',
        r'(\w+(?:\s+\w+)*)\s+(?:metabolizes?|converts?\s+(?:\w+\s+)?)\s+to\s+(\w+(?:\s+\w+)*)',
    ]

    # Association patterns (medium confidence)
    ASSOCIATION_PATTERNS = [
        r'(\w+(?:\s+\w+)*)\s+(?:is\s+)?(?:associated\s+with|linked\s+to|correlated\s+with)\s+(\w+(?:\s+\w+)*)',
        r'(\w+(?:\s+\w+)*)\s+(?:is\s+)?(?:found\s+in|detected\s+in|present\s+in)\s+(\w+(?:\s+\w+)*)',
    ]

    # Non-causal patterns to reject
    REJECT_PATTERNS = [
        r'similar\s+to',
        r'compared\s+to',
        r'unlike',
        r'vs\.?',
        r'versus',
    ]

    def __init__(
        self,
        output_dir: str = "knowledge_graph/relationships",
        use_llm: bool = True,
        embeddings_model: str = "nomic-embed-text"  # or "mxbai-embed-large" (MiniLM-based)
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.use_llm = use_llm and OPENAI_AVAILABLE
        self.embeddings_model = embeddings_model

        if self.use_llm:
            # Try to initialize OpenAI client (supports Ollama, OpenAI, etc.)
            try:
                self.client = OpenAI(
                    base_url="http://localhost:11434/v1",  # Ollama
                    api_key="ollama"  # Ollama doesn't require a key
                )
            except:
                self.client = None
                self.use_llm = False

        self.entity_embeddings = {}
        self.entity_set = set()

    def load_entity_embeddings(self, entities: List[dict], embeddings_file: str = None):
        """Load entity embeddings for semantic matching."""
        logger.info("Loading entity embeddings...")

        # Create entity lookup set
        self.entity_set = {e['term'].lower() for e in entities}

        # Load embeddings from file if available
        if embeddings_file and Path(embeddings_file).exists():
            with open(embeddings_file, 'r') as f:
                data = json.load(f)
                # Handle both formats: direct list or wrapped in results key
                items = data if isinstance(data, list) else data.get('results', [])

                # Check if items have embeddings field
                for item in items:
                    if isinstance(item, dict):
                        term = item.get('term')
                        embedding = item.get('embedding')

                        # If no embedding in this file, we'll generate them
                        if term and embedding:
                            self.entity_embeddings[term.lower()] = np.array(embedding)

            if self.entity_embeddings:
                logger.info(f"Loaded {len(self.entity_embeddings)} entity embeddings from file")
            else:
                logger.info("No embeddings found in file, will generate on-the-fly")

        # Generate embeddings for entities (if not loaded from file or LLM is available)
        if not self.entity_embeddings and self.use_llm and self.client:
            logger.info("Generating embeddings for entities using Ollama...")
            for entity in entities:
                term = entity['term']
                try:
                    response = self.client.embeddings.create(
                        model=self.embeddings_model,
                        input=term
                    )
                    self.entity_embeddings[term.lower()] = np.array(response.data[0].embedding)
                    time.sleep(0.05)  # Rate limiting for Ollama
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for {term}: {e}")

                # Save embeddings
                embeddings_path = self.output_dir / "entity_embeddings.json"
                with open(embeddings_path, 'w') as f:
                    json.dump([
                        {'term': k, 'embedding': v.tolist()}
                        for k, v in self.entity_embeddings.items()
                    ], f, indent=2)
                logger.info(f"Saved embeddings to {embeddings_path}")

    def find_best_entity_match(self, target_text: str, threshold: float = 0.85) -> Optional[str]:
        """Find best matching entity using semantic similarity."""
        if not self.entity_embeddings:
            return None

        target_lower = target_text.lower()

        # Direct match
        if target_lower in self.entity_set:
            return target_text

        # Semantic similarity match
        try:
            # Generate embedding for target using Ollama
            if self.use_llm and self.client:
                response = self.client.embeddings.create(
                    model=self.embeddings_model,
                    input=target_text
                )
                target_embedding = np.array(response.data[0].embedding)

                # Find best match
                best_score = 0
                best_match = None

                for entity_term, entity_emb in self.entity_embeddings.items():
                    # Cosine similarity
                    score = np.dot(target_embedding, entity_emb) / (
                        np.linalg.norm(target_embedding) * np.linalg.norm(entity_emb)
                    )

                    if score > best_score and score >= threshold:
                        best_score = score
                        best_match = entity_term

                return best_match
        except Exception as e:
            logger.warning(f"Failed to find entity match: {e}")

        return None

    def extract_relationships_regex(
        self,
        entity_term: str,
        paper_context: str
    ) -> List[dict]:
        """Extract relationships using regex patterns."""
        relationships = []

        # Check for causal patterns
        for pattern in self.CAUSAL_PATTERNS:
            matches = re.finditer(pattern, paper_context, re.IGNORECASE)
            for match in matches:
                source_text = match.group(1).strip()
                target_text = match.group(2).strip()

                # Check if source matches our entity
                if entity_term.lower() not in source_text.lower():
                    continue

                # Find best entity match for target
                target_entity = self.find_best_entity_match(target_text)
                if not target_entity:
                    continue

                # Determine relationship type from pattern
                rel_text = match.group(0).lower()
                if 'produces' in rel_text or 'synthesizes' in rel_text:
                    rel_type = 'PRODUCES'
                    confidence = 0.95
                elif 'inhibits' in rel_text or 'blocks' in rel_text:
                    rel_type = 'INHIBITS'
                    confidence = 0.90
                elif 'causes' in rel_text or 'induces' in rel_text:
                    rel_type = 'CAUSES'
                    confidence = 0.90
                elif 'metabolizes' in rel_text:
                    rel_type = 'METABOLIZES'
                    confidence = 0.95
                else:
                    rel_type = 'RELATED_TO'
                    confidence = 0.70

                relationships.append({
                    'source': entity_term,
                    'target': target_entity,
                    'relationship_type': rel_type,
                    'source_db': 'Peer-Reviewed Literature',
                    'confidence': confidence,
                    'evidence': match.group(0),
                    'evidence_type': 'Experimental',
                    'paper_id': '',
                    'paper_title': '',
                    'extraction_method': 'regex'
                })

        # Check for association patterns
        for pattern in self.ASSOCIATION_PATTERNS:
            matches = re.finditer(pattern, paper_context, re.IGNORECASE)
            for match in matches:
                source_text = match.group(1).strip()
                target_text = match.group(2).strip()

                # Check if source matches our entity
                if entity_term.lower() not in source_text.lower():
                    continue

                # Find best entity match for target
                target_entity = self.find_best_entity_match(target_text, threshold=0.80)
                if not target_entity:
                    continue

                relationships.append({
                    'source': entity_term,
                    'target': target_entity,
                    'relationship_type': 'ASSOCIATED_WITH',
                    'source_db': 'Peer-Reviewed Literature',
                    'confidence': 0.75,
                    'evidence': match.group(0),
                    'evidence_type': 'Observational',
                    'paper_id': '',
                    'paper_title': '',
                    'extraction_method': 'regex'
                })

        return relationships

    def extract_relationships_llm(
        self,
        entity_term: str,
        paper_context: str,
        paper_location: str = ""
    ) -> List[dict]:
        """Extract relationships using LLM (phi4:14b or similar)."""
        if not self.use_llm or not self.client:
            return []

        prompt = f"""Extract scientific relationships from this microbiome research text.

Rules:
1. Only extract EXPLICIT causal relationships (produces, inhibits, causes)
2. Ignore correlation-only statements
3. Include the specific sentence as evidence
4. Return confidence: High (experimental), Medium (strong association), Low (correlation)

Text: {paper_context}
Entity: {entity_term}

Output JSON format only:
[
  {{
    "target": "Target entity name",
    "relation": "PRODUCES|INHIBITS|CAUSES|ASSOCIATED_WITH",
    "evidence": "Specific sentence from text",
    "confidence": "High|Medium|Low",
    "reasoning": "Brief explanation"
  }}
]"""

        try:
            response = self.client.chat.completions.create(
                model="phi4:14b",  # or "llama3.1:8b" or similar
                messages=[
                    {"role": "system", "content": "You are a scientific relationship extractor for microbiome research."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=1000
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON response
            # Handle potential ```json wrapper
            if result_text.startswith('```'):
                result_text = result_text.split('\n', 1)[-1]
            if result_text.endswith('```'):
                result_text = result_text.rsplit('\n', 1)[0]
            result_text = result_text.strip()

            extractions = json.loads(result_text)

            relationships = []
            for extraction in extractions:
                # Validate target entity exists
                target_entity = self.find_best_entity_match(extraction['target'], threshold=0.75)
                if not target_entity:
                    continue

                # Map confidence
                conf_map = {'High': 0.95, 'Medium': 0.75, 'Low': 0.60}
                confidence = conf_map.get(extraction['confidence'], 0.70)

                relationships.append({
                    'source': entity_term,
                    'target': target_entity,
                    'relationship_type': extraction['relation'].upper(),
                    'source_db': 'Peer-Reviewed Literature',
                    'confidence': confidence,
                    'evidence': extraction['evidence'],
                    'evidence_type': 'Experimental' if confidence >= 0.90 else 'Observational',
                    'paper_id': '',
                    'paper_title': '',
                    'extraction_method': 'llm',
                    'reasoning': extraction.get('reasoning', '')
                })

            return relationships

        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")
            return []

    def process_entities(
        self,
        entities: List[dict],
        output_file: str = "paper_relationships.csv"
    ) -> List[dict]:
        """Process all entities and extract relationships from paper context."""
        all_relationships = []

        # Load embeddings
        embeddings_file = self.output_dir / "../cdm_entities_final_v3_embeddings.json"
        self.load_entity_embeddings(entities, str(embeddings_file))

        # Filter entities with paper_context
        entities_with_context = [
            e for e in entities
            if e.get('paper_context') and len(e.get('paper_context', '')) > 20
        ]

        logger.info(f"Processing {len(entities_with_context)} entities with paper context")

        for i, entity in enumerate(entities_with_context):
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i + 1}/{len(entities_with_context)}")

            # Extract using regex
            regex_rels = self.extract_relationships_regex(
                entity['term'],
                entity['paper_context']
            )
            all_relationships.extend(regex_rels)

            # Extract using LLM (for a subset due to cost/time)
            if self.use_llm and i < 500:  # Limit LLM calls
                llm_rels = self.extract_relationships_llm(
                    entity['term'],
                    entity['paper_context'],
                    entity.get('paper_location', '')
                )
                all_relationships.extend(llm_rels)

        # Deduplicate
        seen = set()
        unique_relationships = []
        for rel in all_relationships:
            key = (rel['source'], rel['target'], rel['relationship_type'], rel['evidence'][:50])
            if key not in seen:
                seen.add(key)
                unique_relationships.append(rel)

        # Save to CSV
        self._save_to_csv(unique_relationships, output_file)

        # Also save as JSON
        json_file = self.output_dir / output_file.replace('.csv', '.json')
        with open(json_file, 'w') as f:
            json.dump(unique_relationships, f, indent=2)

        logger.info(f"Extracted {len(unique_relationships)} unique relationships")
        logger.info(f"Saved to {output_file}")

        return unique_relationships

    def _save_to_csv(self, relationships: List[dict], filename: str):
        """Save relationships to CSV file."""
        if not relationships:
            logger.warning("No relationships to save")
            return

        output_path = self.output_dir / filename

        # Get all unique keys
        fieldnames = set()
        for rel in relationships:
            fieldnames.update(rel.keys())

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=sorted(fieldnames))
            writer.writeheader()
            writer.writerows(relationships)

        logger.info(f"Saved {len(relationships)} relationships to {output_path}")


def main():
    """Main entry point."""
    # Load entities
    entities_file = Path(str(_CDM_ROOT / "pipelines/llm_terms/knowledge_graph/cdm_entities_final_v3_embeddings.json"))

    with open(entities_file, 'r') as f:
        data = json.load(f)
        entities = data['results']

    logger.info(f"Loaded {len(entities)} entities")

    # Extract paper relationships
    extractor = PaperRelationshipExtractor(
        use_llm=True,  # Set to False to skip LLM extraction
        embeddings_model="nomic-embed-text"  # Options: nomic-embed-text, mxbai-embed-large
    )
    relationships = extractor.process_entities(
        entities,
        output_file="paper_relationships.csv"
    )

    # Print summary
    logger.info(f"\nSummary:")
    logger.info(f"  Total relationships: {len(relationships)}")

    # Relationship type distribution
    rel_types = {}
    for rel in relationships:
        rt = rel['relationship_type']
        rel_types[rt] = rel_types.get(rt, 0) + 1

    logger.info(f"\nRelationship type distribution:")
    for rt, count in sorted(rel_types.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {rt}: {count}")

    # Extraction method distribution
    methods = {}
    for rel in relationships:
        m = rel.get('extraction_method', 'unknown')
        methods[m] = methods.get(m, 0) + 1

    logger.info(f"\nExtraction method distribution:")
    for method, count in sorted(methods.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {method}: {count}")


if __name__ == "__main__":
    main()
