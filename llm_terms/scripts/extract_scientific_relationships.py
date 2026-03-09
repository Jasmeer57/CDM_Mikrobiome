#!/usr/bin/env python3
"""
Scientific Relationship Extraction using Qwen3.5-9B
Extracts relationships between microbiome entities with high scientific validity.
"""

import json
import argparse
import logging
from typing import List, Dict, Tuple
from collections import Counter
import re
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Scientific relationship types
RELATIONSHIP_TYPES = [
    # Organism-Chemical (high confidence)
    ("ORGANISM", "produces", "CHEMICAL", "Organism produces metabolite"),
    ("ORGANISM", "consumes", "CHEMICAL", "Organism consumes chemical"),
    ("ORGANISM", "metabolizes", "CHEMICAL", "Organism metabolizes compound"),

    # Organism-Disease
    ("ORGANISM", "causes", "DISEASE", "Organism causes disease"),
    ("ORGANISM", "treats", "DISEASE", "Probiotic treats disease"),
    ("ORGANISM", "protects_against", "DISEASE", "Organism protects against disease"),
    ("ORGANISM", "exacerbates", "DISEASE", "Organism worsens disease"),
    ("ORGANISM", "associated_with", "DISEASE", "Organism associated with disease"),

    # Chemical-Disease
    ("CHEMICAL", "treats", "DISEASE", "Chemical/drug treats disease"),
    ("CHEMICAL", "causes", "DISEASE", "Chemical causes disease"),
    ("CHEMICAL", "inhibits", "DISEASE", "Chemical inhibits disease"),

    # Gene-Protein
    ("GENE", "encodes", "PROTEIN", "Gene encodes protein"),
    ("GENE", "expresses", "PROTEIN", "Gene expresses protein"),

    # Pathway
    ("PATHWAY", "produces", "CHEMICAL", "Pathway produces metabolite"),
    ("PATHWAY", "involved_in", "DISEASE", "Pathway involved in disease"),

    # General
    ("ENTITY", "correlates_with", "ENTITY", "Entities correlated"),
    ("ENTITY", "interacts_with", "ENTITY", "Entities interact"),
]

CATEGORY_TYPES = ["ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "GENE", "PATHWAY", "CELL_TYPE", "CLINICAL", "GENOMICS", "DNA_RNA"]


class QwenRelationshipExtractor:
    """Extract scientific relationships using Qwen3.5-9B."""

    def __init__(self, model_path: str):
        logger.info(f"Loading Qwen model: {model_path}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        # Load with quantization
        try:
            from transformers import BitsAndBytesConfig
            quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
        except:
            quant = None

        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            device_map="auto",
            quantization_config=quant,
            trust_remote_code=True,
            torch_dtype=torch.float16
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Model loaded on {self.device}")

    def build_prompt(self, entities: List[Dict], existing_rels: set) -> str:
        """Build prompt for relationship extraction."""

        # Get entities by category
        by_cat = {cat: [] for cat in CATEGORY_TYPES}
        for e in entities:
            cat = e.get('categories', 'UNKNOWN')
            if cat in by_cat:
                by_cat[cat].append(e['term'])

        # Sample some entities to include
        samples = []
        for cat in ['ORGANISM', 'CHEMICAL', 'DISEASE', 'GENE', 'PATHWAY']:
            samples.extend(by_cat[cat][:20])

        rel_examples = """
Examples of relationships to extract:
- Bifidobacterium | produces | short-chain fatty acid
- Lactobacillus | treats | inflammatory bowel disease
- Escherichia coli | produces | indole
- Butyrate | treats | colitis
- gene_xyz | encodes | protein_abc
"""

        prompt = f"""You are a microbiome relationship extraction expert.

Extract scientific relationships from microbiome research.

Entities to consider:
{', '.join(samples[:100])}

Relationship types to find:
- organism PRODUCES chemical (e.g., Bacteroides produces propionate)
- organism TREATS disease (e.g., Lactobacillus treats colitis)
- organism CAUSES disease (e.g., pathogen causes infection)
- organism ASSOCIATED_WITH disease (e.g., dysbiosis associated with IBD)
- chemical TREATS disease (e.g., butyrate treats colitis)
- gene ENCODES protein
- pathway PRODUCES chemical

Respond with JSON array of relationships:
[{{"source": "X", "target": "Y", "relation": "RELATION", "evidence": "brief evidence"}}]

Only include well-established scientific relationships from microbiome literature.
{rel_examples}

Extract relationships:"""
        return prompt

    def extract_batch(self, entities: List[Dict], batch_size: int = 50) -> List[Dict]:
        """Extract relationships in batches."""

        all_rels = []

        # Create entity lookup
        entity_lookup = {e['term'].lower(): e for e in entities}

        for i in range(0, len(entities), batch_size):
            batch = entities[i:i+batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(entities)-1)//batch_size + 1}")

            prompt = self.build_prompt(batch, set())

            messages = [
                {"role": "system", "content": "You are a microbiome expert. Extract scientific relationships."},
                {"role": "user", "content": prompt}
            ]

            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                chat_template_kwargs={"enable_thinking": False}
            )

            inputs = self.tokenizer([text], return_tensors="pt").to(self.device)

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=1024,
                    do_sample=False,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )

            response = self.tokenizer.decode(
                outputs[0][inputs.input_ids.shape[1]:],
                skip_special_tokens=True
            )

            # Parse relationships
            rels = self._parse_response(response, entity_lookup)
            all_rels.extend(rels)

        return all_rels

    def _parse_response(self, response: str, entity_lookup: dict) -> List[Dict]:
        """Parse LLM response to extract relationships."""
        import re

        rels = []

        # Try to find JSON array
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if not match:
            return rels

        try:
            data = json.loads(match.group())
            if not isinstance(data, list):
                return rels

            for item in data:
                src = item.get('source', '')
                tgt = item.get('target', '')
                rel = item.get('relation', '')
                evidence = item.get('evidence', '')

                if src and tgt and rel:
                    # Find entity types
                    src_lower = src.lower()
                    tgt_lower = tgt.lower()

                    src_type = None
                    for term, e in entity_lookup.items():
                        if src_lower in term or term in src_lower:
                            src_type = e.get('categories', 'UNKNOWN')
                            break

                    tgt_type = None
                    for term, e in entity_lookup.items():
                        if tgt_lower in term or term in tgt_lower:
                            tgt_type = e.get('categories', 'UNKNOWN')
                            break

                    if src_type and tgt_type:
                        rels.append({
                            'source': src,
                            'source_type': src_type,
                            'target': tgt,
                            'target_type': tgt_type,
                            'relationship': rel,
                            'evidence': evidence,
                            'confidence': 0.8
                        })

        except Exception as e:
            logger.warning(f"Failed to parse response: {e}")

        return rels


def load_entities(path: str) -> List[Dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get('results', [])


def save_relationships(rels: List[Dict], path: str):
    with open(path, 'w') as f:
        json.dump({'relationships': rels}, f, indent=2)
    logger.info(f"Saved {len(rels)} relationships to {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--model", default="/home/jkalra/Microbiome-CDM/models/Qwen3.5-9B-Base")
    args = parser.parse_args()

    # Load entities
    entities = load_entities(args.input)
    logger.info(f"Loaded {len(entities)} entities")

    # Extract relationships
    extractor = QwenRelationshipExtractor(args.model)
    relationships = extractor.extract_batch(entities)

    # Save
    save_relationships(relationships, args.output)

    # Summary
    logger.info(f"\nExtracted {len(relationships)} relationships")
    types = Counter(r['relationship'] for r in relationships)
    for rt, cnt in types.most_common(10):
        logger.info(f"  {rt}: {cnt}")


if __name__ == "__main__":
    main()
