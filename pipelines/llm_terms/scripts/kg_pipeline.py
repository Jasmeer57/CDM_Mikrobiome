#!/usr/bin/env python3
"""
CDM Knowledge Graph Construction Pipeline
Single-file implementation of the complete KG construction pipeline.

Phases:
  0: Pre-pipeline data repair
  1: Smart entity pair selection
  2: Batch LLM relationship extraction
  3: Knowledge graph construction
  4: Interactive HTML visualization
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time

import argparse
import json
import logging
import os
import re
import sys
import math
import random
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any, Union
from itertools import combinations
import hashlib

# Third-party imports
import networkx as nx
from community import community_louvain
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/kg_pipeline.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Pipeline configuration constants."""

    # Paths
    INPUT_DIR = Path("outputs/normalized")
    OUTPUT_DIR = Path("knowledge_graph")
    LOG_DIR = Path("logs")
    TEMP_DIR = Path("temp")

    # Input files
    INPUT_FILE = INPUT_DIR / "cdm_entities_clean.json"

    # Phase 0 thresholds
    MIN_CONFIDENCE = 0.7
    MIN_DEFINITION_LENGTH = 50

    # Phase 1 thresholds
    MIN_CONTEXT_WINDOW = 50
    CROSS_PAPER_THRESHOLD = 3
    CROSS_PAPER_BONUS = 0.2
    UMLS_BONUS = 0.1

    # Phase 2 thresholds
    PASS1_CONFIDENCE_THRESHOLD = 0.6
    PASS2_CONFIDENCE_FLOOR = 0.65
    MIN_RELATIONSHIP_CONFIDENCE = 0.7
    BATCH_SIZE_EXTRACTION = 15
    BATCH_SIZE_VALIDATION = 50

    # Phase 3 thresholds
    MIN_NODE_DEGREE = 1
    CORE_TERM_KEEP_THRESHOLD = 0.9
    MIN_COMMUNITY_SIZE = 5

    # Phase 4 visualization
    DEFAULT_TOP_NODES = 200
    DEFAULT_MIN_EDGE_CONFIDENCE = 0.85

    # LLM Server (llama.cpp with Qwen3-14B)
    LLM_HOST = "127.0.0.1"
    LLM_PORT = 8000  # Dynamic port 8000-8999
    EXTRACTION_MODEL = "Qwen3-14B"
    VALIDATION_MODEL = "Qwen3-14B"

    # Entity types and valid pairs
    ENTITY_TYPES = [
        "GENE", "DATA_ANALYSIS", "CLINICAL", "ORGANISM", "CHEMICAL",
        "DISEASE", "PROTEIN", "GENOMICS", "DNA_RNA", "CELL_TYPE",
        "PATHWAY", "EXPERIMENTAL_METHOD", "STUDY_DESIGN"
    ]

    # Valid type pairs with bonuses
    VALID_TYPE_PAIRS = {
        ("ORGANISM", "DISEASE"): 0.3,
        ("DISEASE", "ORGANISM"): 0.3,
        ("ORGANISM", "CHEMICAL"): 0.3,
        ("CHEMICAL", "ORGANISM"): 0.3,
        ("ORGANISM", "PATHWAY"): 0.3,
        ("PATHWAY", "ORGANISM"): 0.3,
        ("CHEMICAL", "DISEASE"): 0.3,
        ("DISEASE", "CHEMICAL"): 0.3,
        ("GENE", "PROTEIN"): 0.3,
        ("PROTEIN", "GENE"): 0.3,
        ("PATHWAY", "CHEMICAL"): 0.3,
        ("CHEMICAL", "PATHWAY"): 0.3,
        ("PATHWAY", "GENE"): 0.3,
        ("GENE", "PATHWAY"): 0.3,
        ("PATHWAY", "PROTEIN"): 0.3,
        ("PROTEIN", "PATHWAY"): 0.3,
        ("ORGANISM", "ORGANISM"): 0.15,
        ("DISEASE", "DISEASE"): 0.15,
        ("PROTEIN", "CHEMICAL"): 0.15,
        ("CHEMICAL", "PROTEIN"): 0.15,
        ("GENE", "DISEASE"): 0.15,
        ("DISEASE", "GENE"): 0.15,
        ("CELL_TYPE", "ORGANISM"): 0.15,
        ("ORGANISM", "CELL_TYPE"): 0.15,
        ("EXPERIMENTAL_METHOD", "ORGANISM"): 0.05,
        ("ORGANISM", "EXPERIMENTAL_METHOD"): 0.05,
        ("EXPERIMENTAL_METHOD", "GENE"): 0.05,
        ("GENE", "EXPERIMENTAL_METHOD"): 0.05,
        ("EXPERIMENTAL_METHOD", "DISEASE"): 0.05,
        ("DISEASE", "EXPERIMENTAL_METHOD"): 0.05,
        ("STUDY_DESIGN", "DISEASE"): 0.05,
        ("DISEASE", "STUDY_DESIGN"): 0.05,
        ("STUDY_DESIGN", "ORGANISM"): 0.05,
        ("ORGANISM", "STUDY_DESIGN"): 0.05,
    }

    # Relationship types
    RELATIONSHIP_TYPES = [
        "causes", "treats", "prevents", "exacerbates", "associated_with",
        "correlates_with", "co_occurs_with", "encodes", "regulates",
        "inhibits", "activates", "binds_to", "interacts_with",
        "produces", "consumes", "metabolizes", "utilizes_pathway",
        "detects", "measures"
    ]

    # Type-specific relationship constraints
    INVALID_RELATIONSHIPS = {
        ("DISEASE", "ORGANISM"): ["produces", "encodes", "metabolizes"],
        ("DISEASE", "GENE"): ["produces", "encodes", "treats", "prevents"],
        ("GENE", "DISEASE"): ["produces", "metabolizes"],
        ("CHEMICAL", "ORGANISM"): ["encodes"],
        ("ORGANISM", "CHEMICAL"): ["encodes"],
        # Add more as needed
    }

    # Entity type colors for visualization
    TYPE_COLORS = {
        "ORGANISM": "#4CAF50",
        "CHEMICAL": "#2196F3",
        "GENE": "#9C27B0",
        "DISEASE": "#F44336",
        "PROTEIN": "#FF9800",
        "PATHWAY": "#00BCD4",
        "EXPERIMENTAL_METHOD": "#795548",
        "STUDY_DESIGN": "#9E9E9E",
        "GENOMICS": "#E91E63",
        "DNA_RNA": "#3F51B5",
        "CELL_TYPE": "#009688",
        "CLINICAL": "#607D8B",
        "DATA_ANALYSIS": "#9E9E9E"
    }


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Entity:
    """Represents a biomedical entity."""
    term: str
    contextual_definition: str
    definition: str
    confidence_score: float
    avg_confidence_score: float
    max_confidence_score: float
    frequency: int
    categories: str
    aliases: str
    examples: str
    files_found_in: str
    is_core_term: bool
    relevance_classification: str
    UMLS_ID: str = ""
    OMOP: str = ""
    OLS: str = ""
    Bioportal: str = ""
    entity_type: str = ""
    is_computed_metric: bool = False
    paper_count: int = 0

    def __post_init__(self):
        if self.paper_count == 0:
            self.paper_count = len(self.get_paper_list())

    def get_paper_list(self) -> List[str]:
        """Parse files_found_in into a list of paper IDs."""
        if not self.files_found_in:
            return []
        return [f.strip() for f in self.files_found_in.split(',') if f.strip()]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Create Entity from dictionary."""
        # Filter out unexpected fields
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


@dataclass
class EntityPair:
    """Represents a pair of entities for relationship extraction."""
    entity_a: Entity
    entity_b: Entity
    shared_papers: List[str] = field(default_factory=list)
    co_occurrence_contexts: List[str] = field(default_factory=list)
    priority_score: float = 0.0
    cross_paper_bonus: float = 0.0
    type_pair_bonus: float = 0.0
    umls_bonus: float = 0.0
    # Preliminary relationship from LLM inference (Phase 1)
    preliminary_relationship: str = ""
    preliminary_evidence: str = ""
    preliminary_confidence: float = 0.0

    def __hash__(self):
        return hash((self.entity_a.term, self.entity_b.term))

    def __eq__(self, other):
        if not isinstance(other, EntityPair):
            return False
        return (self.entity_a.term == other.entity_a.term and
                self.entity_b.term == other.entity_b.term)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "entity_a": self.entity_a.term,
            "entity_b": self.entity_b.term,
            "entity_a_type": self.entity_a.entity_type,
            "entity_b_type": self.entity_b.entity_type,
            "shared_papers": self.shared_papers,
            "priority_score": self.priority_score,
            "type_pair_bonus": self.type_pair_bonus,
            "cross_paper_bonus": self.cross_paper_bonus,
            "umls_bonus": self.umls_bonus,
            "preliminary_relationship": self.preliminary_relationship,
            "preliminary_evidence": self.preliminary_evidence,
            "preliminary_confidence": self.preliminary_confidence
        }


@dataclass
class Relationship:
    """Represents an extracted relationship."""
    source_entity: str
    target_entity: str
    source_type: str
    target_type: str
    relationship_type: str
    confidence: float
    evidence: str
    source_context: str
    paper_id: str
    pass1_confidence: float = 0.0
    pass2_verdict: str = ""
    is_cross_paper: bool = False
    evidence_strength: float = 0.0

    def get_key(self) -> Tuple[str, str, str]:
        """Get unique key for deduplication."""
        return (self.source_entity, self.target_entity, self.relationship_type)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def ensure_directories():
    """Create necessary directories."""
    for dir_path in [Config.OUTPUT_DIR, Config.LOG_DIR, Config.TEMP_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)


def load_json(filepath: Path) -> Any:
    """Load JSON file."""
    logger.info(f"Loading {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Any, filepath: Path, pretty: bool = True):
    """Save data to JSON file."""
    logger.info(f"Saving {filepath}")
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        if pretty:
            json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            json.dump(data, f, ensure_ascii=False)


def load_entities(input_file: Path) -> List[Entity]:
    """Load entities from JSON file."""
    data = load_json(input_file)

    if "results" in data:
        entities_data = data["results"]
    else:
        entities_data = data

    entities = []
    for e_data in entities_data:
        try:
            entities.append(Entity.from_dict(e_data))
        except Exception as ex:
            logger.warning(f"Failed to load entity: {e_data.get('term', 'Unknown')}: {ex}")

    logger.info(f"Loaded {len(entities)} entities")
    return entities


def normalize_term(term: str) -> str:
    """Normalize entity term for comparison."""
    return term.strip().lower()


def is_placeholder_definition(definition: str) -> bool:
    """Check if definition is a placeholder."""
    placeholders = [
        "context sentence",
        "gut microbiota",
        "microbiome",
        "not specified",
        "not available",
        "n/a",
        "unknown",
        "to be added"
    ]
    def_lower = definition.strip().lower()
    return any(p in def_lower for p in placeholders) or len(definition) < Config.MIN_DEFINITION_LENGTH


# ============================================================================
# LLM CLIENT
# ============================================================================

class LLMClient:
    """Client for LLM inference via an Ollama server.

    Originally built for llama.cpp's OpenAI-compatible /v1/chat/completions
    endpoint, but that path does NOT honor Ollama's `think: false` param - a
    thinking-capable model (qwen3.5:9b) burned its ENTIRE max_tokens budget on
    chain-of-thought reasoning and returned 0 characters of actual content,
    even at max_tokens=6000, even for a 1-pair prompt. Switched to Ollama's
    native /api/generate endpoint instead, where `think: false` is honored
    (this is the exact fix already proven in core/llm_client.py's Ollama
    client - see that file's _call_ollama for the original diagnosis).
    """

    def __init__(self, base_url: str = None, model: str = None):
        configured = base_url or os.getenv("LLM_SERVER_BASE_URL", "http://127.0.0.1:8000/v1")
        # Accept either an OpenAI-style base (".../v1") or a bare Ollama host -
        # normalize to the bare host since we hit /api/generate directly.
        self.base_url = configured.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[: -len("/v1")]
        self.model = model or os.getenv("LLM_MODEL", "Qwen3-14B")

    def _make_request(self, prompt: str, temperature: float = 0,
                      max_tokens: int = 2048, timeout: int = 600) -> str:
        """Make request to Ollama's native /api/generate endpoint."""
        import urllib.request
        import urllib.error

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "seed": 42,
                "num_predict": max_tokens,
            },
        }

        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('response', '').strip()
        except urllib.error.URLError as e:
            logger.error(f"LLM request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM request error: {e}")
            raise

    def generate_definition(self, term: str, entity_type: str,
                           context: str = "") -> str:
        """Generate definition for an entity."""
        prompt = f"""You are a biomedical expert in microbiome research. Generate a precise definition for the following term.

Term: {term}
Type: {entity_type}
Context: {context if context else "Used in microbiome literature"}

Requirements:
- Provide a clear, scientific definition (1-2 sentences)
- Focus on relevance to microbiome/gut microbiota research where applicable
- Be specific and accurate
- Do not include phrases like "refers to" or "is a term that"
- CRITICAL: Output ONLY the definition itself. Do NOT include your thinking process, reasoning, or any meta-commentary.

Definition:"""

        # max_tokens bumped from 300: this Ollama-served model reasons heavily
        # before emitting `content` regardless of prompt size (measured ~296
        # tokens of chain-of-thought for a one-word answer) - 300 was leaving
        # empty/truncated definitions most of the time.
        response = self._make_request(prompt, max_tokens=1500, temperature=0.0)

        # Remove any chain-of-thought prefixes
        cleanup_patterns = [
            r"^(Let me|First, I|I need to|Okay,|I think|Based on|The user|From the context).*?(?=[A-Z][a-z]+ is)",
            r"^(I'll|I should|Let's|To define).*?(?=[A-Z][a-z]+ is)",
            r"\n\n.*?(?=[A-Z][a-z]+ is)",
        ]

        for pattern in cleanup_patterns:
            response = re.sub(pattern, "", response, flags=re.DOTALL)

        return response.strip()

    def infer_preliminary_relationship(self, entity_a: Entity, entity_b: Entity,
                                       context: str = "") -> Dict[str, Any]:
        """Infer preliminary relationship between two entities using LLM."""
        prompt = f"""You are an expert biomedical knowledge extraction system. Infer the most likely relationship between these two entities.

Entity A: {entity_a.term}
Type A: {entity_a.entity_type}
Definition A: {entity_a.definition[:300] if entity_a.definition else 'N/A'}

Entity B: {entity_b.term}
Type B: {entity_b.entity_type}
Definition B: {entity_b.definition[:300] if entity_b.definition else 'N/A'}

Context: {context[:800] if context else 'These entities co-occur in microbiome research literature'}

Determine the most likely relationship type from:
- causes: A directly causes B
- treats: A treats or ameliorates B
- prevents: A prevents B
- exacerbates: A worsens or exacerbates B
- associated_with: A is statistically associated with B
- correlates_with: A correlates with B
- co_occurs_with: A and B frequently co-occur
- encodes: A encodes or is a gene for B
- regulates: A regulates the expression or activity of B
- inhibits: A inhibits B
- activates: A activates B
- binds_to: A binds to B
- interacts_with: A physically or functionally interacts with B
- produces: A produces or synthesizes B
- consumes: A consumes or degrades B
- metabolizes: A metabolizes B
- utilizes_pathway: A utilizes the metabolic pathway B
- detects: A is used to detect B
- measures: A is used to measure B
- unknown: relationship cannot be determined

Output JSON: {{"relationship_type": "...", "confidence": 0.0-1.0, "evidence": "brief explanation (max 200 chars)"}}"""

        response = self._make_request(prompt, max_tokens=2000, temperature=0)  # see note above re: reasoning overhead

        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                # Ensure required fields
                result.setdefault('relationship_type', 'unknown')
                result.setdefault('confidence', 0.5)
                result.setdefault('evidence', '')
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback to unknown
        return {"relationship_type": "unknown", "confidence": 0.0, "evidence": "Failed to parse LLM response"}

    def extract_relationships(self, pairs: List[EntityPair]) -> List[Dict]:
        """Extract relationships from entity pairs."""
        prompt = """You are an expert biomedical knowledge extraction system. Extract relationships between entity pairs from the provided context.

For each pair, output a JSON object with:
- source_entity: name of source entity
- target_entity: name of target entity
- relationship_type: one of: causes, treats, prevents, exacerbates, associated_with, correlates_with, co_occurs_with, encodes, regulates, inhibits, activates, binds_to, interacts_with, produces, consumes, metabolizes, utilizes_pathway, detects, measures
- confidence: float 0-1
- evidence: brief explanation (max 200 chars)

Output format: [{"source_entity": "...", ...}, ...]

Entity Pairs:

"""
        for i, pair in enumerate(pairs, 1):
            ctx = pair.co_occurrence_contexts[0] if pair.co_occurrence_contexts else "No context available"
            prompt += f"\n{i}. {pair.entity_a.term} ({pair.entity_a.entity_type}) <-> {pair.entity_b.term} ({pair.entity_b.entity_type})\n"
            prompt += f"   Context: {ctx[:500]}...\n"

        response = self._make_request(prompt, max_tokens=6000, temperature=0.0)  # see reasoning-overhead note above

        if os.getenv("KG_DEBUG_RAW_RESPONSE"):
            logger.info(f"  [DEBUG] raw response ({len(response)} chars):\n{response}")

        try:
            # Extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON")

        return []

    def validate_relationship(self, relationship: Relationship,
                             context: str) -> Dict[str, Any]:
        """Validate a relationship using a different LLM."""
        prompt = f"""You are a biomedical fact-checker. Validate the following extracted relationship.

Source: {relationship.source_entity} ({relationship.source_type})
Target: {relationship.target_entity} ({relationship.target_type})
Relationship: {relationship.relationship_type}
Evidence: {relationship.evidence}
Context: {context[:800]}

Answer these questions with yes/no/reversed/suggest:
1. Is this biologically plausible?
2. Is the directionality correct?
3. Is the relationship type appropriate?
4. Does the evidence support this claim?

Respond as JSON: {{"plausible": "yes/no", "direction": "yes/no/reversed", "type_appropriate": "yes/no/suggest", "evidence_support": "yes/partial/no", "suggested_type": "if applicable"}}"""

        response = self._make_request(prompt, max_tokens=1500, temperature=0.0)  # see reasoning-overhead note above

        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

        return {"plausible": "no", "direction": "no", "type_appropriate": "no",
                "evidence_support": "no", "suggested_type": ""}


# ============================================================================
# PHASE 0: DATA REPAIR
# ============================================================================

class Phase0DataRepair:
    """Phase 0: Pre-pipeline data repair."""

    def __init__(self):
        self.stats = defaultdict(int)
        self.removed_entities = []

    def run(self, entities: List[Entity]) -> List[Entity]:
        """Run all Phase 0 repair steps."""
        logger.info("=" * 60)
        logger.info("PHASE 0: DATA REPAIR")
        logger.info("=" * 60)

        # Step 0.1: Fix files_found_in aggregation
        logger.info("\n[0.1] Fixing files_found_in aggregation...")
        entities = self._fix_files_found_in(entities)

        # Step 0.2: Split DATA_ANALYSIS
        logger.info("\n[0.2] Splitting DATA_ANALYSIS type...")
        entities = self._split_data_analysis(entities)

        # Step 0.3: Add PATHWAY type
        logger.info("\n[0.3] Adding PATHWAY entity type...")
        entities = self._add_pathway_type(entities)

        # Step 0.4: Regenerate placeholder definitions
        logger.info("\n[0.4] Regenerating placeholder definitions...")
        entities = self._regenerate_definitions(entities)

        # Step 0.5: Remove low confidence entities
        logger.info("\n[0.5] Removing low-confidence entities...")
        entities = self._filter_low_confidence(entities)

        # Step 0.6: UMLS enrichment (placeholder for QuickUMLS)
        logger.info("\n[0.6] Running UMLS enrichment...")
        entities = self._umls_enrichment(entities)

        # Step 0.7: Reclassify ratio pseudo-entities
        logger.info("\n[0.7] Reclassifying ratio pseudo-entities...")
        entities = self._reclassify_ratios(entities)

        # Log statistics
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 0 COMPLETE - STATISTICS:")
        for key, value in sorted(self.stats.items()):
            logger.info(f"  {key}: {value}")
        logger.info("=" * 60)

        return entities

    def _fix_files_found_in(self, entities: List[Entity]) -> List[Entity]:
        """
        Fix files_found_in aggregation by detecting and merging duplicate terms.

        This is a critical fix - the normalization pipeline removed duplicates
        but didn't merge their paper lists.
        """
        # Group entities by normalized term
        term_groups = defaultdict(list)
        for entity in entities:
            norm_term = normalize_term(entity.term)
            term_groups[norm_term].append(entity)

        fixed_entities = []
        merge_count = 0
        multi_paper_count = 0

        for norm_term, group in term_groups.items():
            if len(group) == 1:
                entity = group[0]
                entity.paper_count = len(entity.get_paper_list())
                fixed_entities.append(entity)
            else:
                # Merge duplicates
                merge_count += len(group) - 1

                # Merge paper lists
                all_papers = set()
                total_freq = 0
                best_entity = max(group, key=lambda e: e.confidence_score)

                for entity in group:
                    all_papers.update(entity.get_paper_list())
                    total_freq += entity.frequency

                # Update best entity with merged data
                best_entity.files_found_in = ','.join(sorted(all_papers))
                best_entity.frequency = total_freq
                best_entity.paper_count = len(all_papers)
                fixed_entities.append(best_entity)

                if len(all_papers) > 1:
                    multi_paper_count += 1

        self.stats["merged_duplicates"] = merge_count
        self.stats["multi_paper_entities"] = multi_paper_count

        logger.info(f"  Merged {merge_count} duplicate entities")
        logger.info(f"  {multi_paper_count} entities now show multiple papers")

        return fixed_entities

    def _split_data_analysis(self, entities: List[Entity]) -> List[Entity]:
        """Split DATA_ANALYSIS into EXPERIMENTAL_METHOD and STUDY_DESIGN."""
        experimental_keywords = [
            "sequencing", "pcr", "extraction", "assay", "staining",
            "microscopy", "culture", "elisa", "flow cytometry",
            "chromatography", "spectrometry", "amplification",
            "genotyping", "hybridization", "binned"
        ]

        study_design_keywords = [
            "control", "cohort", "study", "trial", "group",
            "baseline", "cross-sectional", "longitudinal",
            "case-control", "randomized", "placebo", "intervention"
        ]

        reclassified_exp = 0
        reclassified_study = 0
        reclassified_organism = 0

        for entity in entities:
            if entity.entity_type == "DATA_ANALYSIS":
                term_lower = entity.term.lower()

                # Check for experimental method
                if any(kw in term_lower for kw in experimental_keywords):
                    entity.entity_type = "EXPERIMENTAL_METHOD"
                    reclassified_exp += 1
                # Check for study design
                elif any(kw in term_lower for kw in study_design_keywords):
                    entity.entity_type = "STUDY_DESIGN"
                    reclassified_study += 1
                # Check for misclassified organisms
                elif any(kw in term_lower for kw in ["bacteria", "microbiome", "gut", "luminal", "fecal"]):
                    entity.entity_type = "ORGANISM"
                    reclassified_organism += 1

        self.stats["reclassified_to_experimental_method"] = reclassified_exp
        self.stats["reclassified_to_study_design"] = reclassified_study
        self.stats["reclassified_to_organism"] = reclassified_organism

        logger.info(f"  Reclassified {reclassified_exp} to EXPERIMENTAL_METHOD")
        logger.info(f"  Reclassified {reclassified_study} to STUDY_DESIGN")
        logger.info(f"  Reclassified {reclassified_organism} to ORGANISM")

        return entities

    def _add_pathway_type(self, entities: List[Entity]) -> List[Entity]:
        """Add PATHWAY entity type by reclassifying from GENE/GENOMICS."""
        pathway_keywords = [
            "pathway", "shunt", "cycle", "synthesis", "metabolism",
            "biosynthesis", "degradation", "catabolism", "anabolism"
        ]

        protein_keywords = [
            "receptor", "synthase", "transferase", "kinase", "phosphatase",
            "hydroxylase", "dehydrogenase", "lyase", "ligase", "transporter"
        ]

        pathways_found = 0
        proteins_found = 0

        for entity in entities:
            term_lower = entity.term.lower()

            # Find pathways in GENE and GENOMICS
            if entity.entity_type in ["GENE", "GENOMICS"]:
                if any(kw in term_lower for kw in pathway_keywords):
                    entity.entity_type = "PATHWAY"
                    pathways_found += 1
                elif any(kw in term_lower for kw in protein_keywords):
                    entity.entity_type = "PROTEIN"
                    proteins_found += 1

        self.stats["reclassified_to_pathway"] = pathways_found
        self.stats["reclassified_to_protein"] = proteins_found

        logger.info(f"  Reclassified {pathways_found} to PATHWAY")
        logger.info(f"  Reclassified {proteins_found} to PROTEIN")

        return entities

    def _regenerate_definitions(self, entities: List[Entity]) -> List[Entity]:
        """Regenerate placeholder definitions using LLM."""
        placeholder_entities = [
            e for e in entities if is_placeholder_definition(e.definition)
        ]

        self.stats["placeholder_definitions"] = len(placeholder_entities)

        if not placeholder_entities:
            logger.info("  No placeholder definitions found")
            return entities

        logger.info(f"  Found {len(placeholder_entities)} placeholder definitions")

        # Check if LLM server is available
        try:
            client = LLMClient()
            client._make_request("test", max_tokens=10)
        except Exception as e:
            logger.warning(f"  LLM server not available: {e}")
            logger.warning("  Skipping definition regeneration")
            return entities

        regenerated = 0
        batch_size = 50

        for i in range(0, len(placeholder_entities), batch_size):
            batch = placeholder_entities[i:i+batch_size]
            logger.info(f"  Regenerating definitions {i+1}-{min(i+batch_size, len(placeholder_entities))}")

            for entity in batch:
                try:
                    new_def = client.generate_definition(
                        entity.term,
                        entity.entity_type,
                        entity.contextual_definition
                    )
                    if new_def and len(new_def) > Config.MIN_DEFINITION_LENGTH:
                        entity.definition = new_def
                        regenerated += 1
                except Exception as e:
                    logger.warning(f"    Failed to regenerate {entity.term}: {e}")

        self.stats["definitions_regenerated"] = regenerated

        logger.info(f"  Regenerated {regenerated}/{len(placeholder_entities)} definitions")

        return entities

    def _filter_low_confidence(self, entities: List[Entity]) -> List[Entity]:
        """Remove entities with confidence below threshold."""
        filtered = [e for e in entities if e.confidence_score >= Config.MIN_CONFIDENCE]
        removed = len(entities) - len(filtered)

        self.stats["low_confidence_removed"] = removed
        self.removed_entities = [
            e.to_dict() for e in entities if e.confidence_score < Config.MIN_CONFIDENCE
        ]

        # Save removed entities for audit
        save_json(self.removed_entities,
                 Config.OUTPUT_DIR / "removed_low_conf.json")

        logger.info(f"  Removed {removed} low-confidence entities (<{Config.MIN_CONFIDENCE})")

        return filtered

    def _umls_enrichment(self, entities: List[Entity]) -> List[Entity]:
        """
        Enrich entities with UMLS IDs using QuickUMLS.
        """
        already_has_umls = sum(1 for e in entities if e.UMLS_ID)
        self.stats["umls_before"] = already_has_umls
        self.stats["umls_missing"] = len(entities) - already_has_umls

        logger.info(f"  UMLS coverage before: {already_has_umls}/{len(entities)} ({100*already_has_umls/len(entities):.1f}%)")

        # Check for QuickUMLS path from environment
        quickumls_path = os.getenv("QUICKUMLS_PATH",
                                   os.path.expanduser("~/.quickumls"))

        # Try to import and use QuickUMLS
        try:
            from quickumls import QuickUMLS

            if not os.path.exists(quickumls_path):
                logger.warning(f"  QuickUMLS data not found at {quickumls_path}")
                logger.warning("  Skipping UMLS enrichment")
                logger.warning("  Install with: quickumls_install <umls_archive> ~/.quickumls")
                return entities

            logger.info(f"  Loading QuickUMLS from {quickumls_path}...")
            matcher = QuickUMLS(quickumls_path, overlapping_criteria="length")

            enriched = 0
            batch_size = 100

            for i in range(0, len(entities), batch_size):
                batch = entities[i:i+batch_size]
                logger.info(f"  Processing UMLS batch {i//batch_size + 1}/{(len(entities)+batch_size-1)//batch_size}...")

                for entity in batch:
                    if not entity.UMLS_ID:
                        try:
                            matches = matcher.match(entity.term, best_match=True)
                            if matches and matches[0]:
                                match = matches[0][0]
                                # Check semantic type and score
                                if match['score'] >= 0.85:
                                    entity.UMLS_ID = match['cui']
                                    # Also add semantic type if available
                                    if 'semtypes' in match:
                                        entity.semantic_types = match['semtypes']
                                    enriched += 1
                        except Exception as e:
                            logger.debug(f"    UMLS lookup failed for {entity.term}: {e}")

            self.stats["umls_enriched"] = enriched

            # Calculate new coverage
            new_coverage = sum(1 for e in entities if e.UMLS_ID)
            logger.info(f"  ✓ Enriched {enriched} entities with UMLS IDs")
            logger.info(f"  UMLS coverage after: {new_coverage}/{len(entities)} ({100*new_coverage/len(entities):.1f}%)")

        except ImportError:
            logger.warning("  QuickUMLS not installed - skipping UMLS enrichment")
            logger.warning("  Install with: pip install quickumls")

        return entities

    def _reclassify_ratios(self, entities: List[Entity]) -> List[Entity]:
        """Reclassify ratio/composite pseudo-entities."""
        ratio_keywords = ["ratio", "f/b", "bacteroidetes/firmicutes",
                         "prevotella/bacteroides"]

        reclassified = 0

        for entity in entities:
            if entity.entity_type == "ORGANISM":
                term_lower = entity.term.lower()
                if any(kw in term_lower for kw in ratio_keywords):
                    entity.entity_type = "GENOMICS"
                    entity.is_computed_metric = True
                    reclassified += 1

        self.stats["ratios_reclassified"] = reclassified

        logger.info(f"  Reclassified {reclassified} ratio entities to GENOMICS")

        return entities


# ============================================================================
# PHASE 1: ENTITY PAIR GENERATION
# ============================================================================

class Phase1PairGeneration:
    """Phase 1: Smart entity pair selection."""

    def __init__(self):
        self.stats = defaultdict(int)

    def run(self, entities: List[Entity]) -> List[EntityPair]:
        """Generate high-value entity pairs."""
        logger.info("=" * 60)
        logger.info("PHASE 1: ENTITY PAIR GENERATION")
        logger.info("=" * 60)

        # Build paper index
        logger.info("\n[1.2] Building paper co-occurrence index...")
        paper_to_entities = self._build_paper_index(entities)

        # Generate co-occurring pairs
        logger.info("\nGenerating co-occurring pairs...")
        pairs = self._generate_cooccurring_pairs(entities, paper_to_entities)

        logger.info(f"\n  Generated {len(pairs)} initial pairs")

        # Filter by type compatibility
        logger.info("\n[1.3] Filtering by type compatibility...")
        pairs = self._filter_by_type_compatibility(pairs)
        logger.info(f"  {len(pairs)} pairs after type filtering")

        # Score and rank pairs
        logger.info("\n[1.5] Computing priority scores...")
        pairs = self._score_pairs(pairs)

        # Sort by priority
        pairs.sort(key=lambda p: p.priority_score, reverse=True)

        # Log top pairs
        logger.info("\nTop 20 pairs by priority:")
        for i, pair in enumerate(pairs[:20], 1):
            logger.info(f"  {i}. {pair.entity_a.term} <-> {pair.entity_b.term} "
                       f"(score: {pair.priority_score:.3f})")

        # Infer preliminary relationships using LLM
        logger.info("\n[1.6] Inferring preliminary relationships using LLM...")
        pairs = self._infer_preliminary_relationships(pairs)

        logger.info("\n" + "=" * 60)
        logger.info(f"PHASE 1 COMPLETE - {len(pairs)} pairs generated")
        logger.info("=" * 60)

        return pairs

    def _build_paper_index(self, entities: List[Entity]) -> Dict[str, List[Entity]]:
        """Build inverted index: paper_id -> list of entities."""
        paper_to_entities = defaultdict(list)

        for entity in entities:
            for paper_id in entity.get_paper_list():
                paper_to_entities[paper_id].append(entity)

        self.stats["total_papers"] = len(paper_to_entities)

        logger.info(f"  Found entities in {len(paper_to_entities)} papers")

        return paper_to_entities

    def _generate_cooccurring_pairs(self, entities: List[Entity],
                                   paper_to_entities: Dict[str, List[Entity]]) -> List[EntityPair]:
        """Generate entity pairs that co-occur in papers."""
        pair_dict = {}

        for paper_id, paper_entities in paper_to_entities.items():
            # Generate all pairs within this paper
            for entity_a, entity_b in combinations(paper_entities, 2):
                # Skip if both are computed metrics or low priority types
                if entity_a.is_computed_metric or entity_b.is_computed_metric:
                    continue

                # Create consistent key (sort alphabetically)
                if entity_a.term < entity_b.term:
                    key = (entity_a.term, entity_b.term)
                else:
                    key = (entity_b.term, entity_a.term)

                if key not in pair_dict:
                    a, b = (entity_a, entity_b) if entity_a.term < entity_b.term else (entity_b, entity_a)
                    pair = EntityPair(
                        entity_a=a,
                        entity_b=b,
                        shared_papers=[paper_id],
                        # co_occurrence_contexts was never populated anywhere in this
                        # file despite being read in 3 places downstream (extraction
                        # prompt context, preliminary-relationship context, and the
                        # rule-based filter's "entity names must appear in context"
                        # gate). An empty context meant `_rule_based_filter` rejected
                        # every single relationship unconditionally. Our corpus
                        # aggregates entities across papers (no per-mention sentence
                        # linking two specific entities survives that aggregation),
                        # so this is a synthetic paper-level co-mention statement, not
                        # a real extracted sentence - it exists to (a) satisfy the
                        # name-presence gate and (b) give the LLM a minimal, honest
                        # co-occurrence signal. Real semantic judgment for the
                        # relationship still comes primarily from entity type +
                        # definition, not this string.
                        co_occurrence_contexts=[
                            f"{a.term} and {b.term} both appear in paper {paper_id} of this microbiome research corpus."
                        ],
                    )
                    pair_dict[key] = pair
                else:
                    pair_dict[key].shared_papers.append(paper_id)

        pairs = list(pair_dict.values())

        # Count cross-paper pairs
        cross_paper = sum(1 for p in pairs if len(p.shared_papers) >= Config.CROSS_PAPER_THRESHOLD)
        self.stats["cross_paper_pairs"] = cross_paper

        logger.info(f"  {cross_paper} pairs occur in {Config.CROSS_PAPER_THRESHOLD}+ papers")

        return pairs

    def _filter_by_type_compatibility(self, pairs: List[EntityPair]) -> List[EntityPair]:
        """Filter pairs by valid type combinations."""
        valid_pairs = []

        for pair in pairs:
            type_pair = (pair.entity_a.entity_type, pair.entity_b.entity_type)

            if type_pair in Config.VALID_TYPE_PAIRS:
                pair.type_pair_bonus = Config.VALID_TYPE_PAIRS[type_pair]
                pair.umls_bonus = (Config.UMLS_BONUS if pair.entity_a.UMLS_ID
                                  and pair.entity_b.UMLS_ID else 0)
                valid_pairs.append(pair)

        # Count by type pair
        type_counts = Counter(
            (p.entity_a.entity_type, p.entity_b.entity_type) for p in valid_pairs
        )

        logger.info("  Top 10 type pair combinations:")
        for (t1, t2), count in type_counts.most_common(10):
            logger.info(f"    {t1} <-> {t2}: {count}")

        return valid_pairs

    def _score_pairs(self, pairs: List[EntityPair]) -> List[EntityPair]:
        """Compute priority scores for pairs."""
        for pair in pairs:
            # Type pair bonus (already set)
            type_bonus = pair.type_pair_bonus

            # Average confidence
            avg_conf = (pair.entity_a.confidence_score +
                       pair.entity_b.confidence_score) / 2

            # Frequency bonus (logarithmic to prevent dominance)
            max_freq = max(pair.entity_a.frequency, pair.entity_b.frequency)
            freq_bonus = min(0.3, math.log10(max(1, max_freq)) * 0.15)

            # Core term bonus
            core_bonus = 0.1 if (pair.entity_a.is_core_term or
                                pair.entity_b.is_core_term) else 0

            # Cross-paper bonus
            cross_bonus = (Config.CROSS_PAPER_BONUS
                          if len(pair.shared_papers) >= Config.CROSS_PAPER_THRESHOLD else 0)

            # Microbiome relevance bonus
            rel_bonus = 0
            if pair.entity_a.relevance_classification == "High":
                rel_bonus += 0.05
            if pair.entity_b.relevance_classification == "High":
                rel_bonus += 0.05

            # UMLS bonus (already set)
            umls_bonus = pair.umls_bonus

            # Total score
            pair.priority_score = (type_bonus + avg_conf + freq_bonus +
                                  core_bonus + cross_bonus + rel_bonus + umls_bonus)
            pair.cross_paper_bonus = cross_bonus

        self.stats["avg_priority_score"] = np.mean([p.priority_score for p in pairs])
        self.stats["max_priority_score"] = max(p.priority_score for p in pairs)

        return pairs

    def _infer_preliminary_relationships(self, pairs: List[EntityPair]) -> List[EntityPair]:
        """Infer preliminary relationships for top pairs using LLM."""
        if os.getenv("KG_SKIP_PRELIM_INFERENCE"):
            # This step is UNBATCHED (one LLM call per pair, up to 5000 pairs) and
            # purely preliminary/advisory - Phase 2's extract_relationships() does
            # the real extraction properly batched (15 pairs/call). At this model's
            # reasoning-overhead cost per call, 5000 sequential calls here would run
            # ~20+ hours for output that gets superseded by Phase 2 anyway.
            logger.info("  KG_SKIP_PRELIM_INFERENCE set - skipping (redundant with Phase 2's batched extraction)")
            return pairs
        # Check LLM availability
        try:
            client = LLMClient()
            client._make_request("test", max_tokens=10, timeout=30)
        except Exception as e:
            logger.warning(f"  LLM server not available: {e}")
            logger.warning("  Skipping preliminary relationship inference")
            return pairs

        # Limit to top pairs to avoid excessive API calls
        # Use configurable limit from config or default to top 5000
        max_pairs = min(len(pairs), 5000)
        top_pairs = pairs[:max_pairs]

        logger.info(f"  Inferring relationships for {len(top_pairs)} pairs "
                   f"(out of {len(pairs)} total)...")

        inferred = 0
        failed = 0
        batch_size = 50

        for i in range(0, len(top_pairs), batch_size):
            batch = top_pairs[i:i+batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(top_pairs) + batch_size - 1) // batch_size

            logger.info(f"  Batch {batch_num}/{total_batches} ({len(batch)} pairs)...")

            for pair in batch:
                try:
                    # Get context from co-occurrence if available
                    context = ""
                    if pair.co_occurrence_contexts:
                        context = pair.co_occurrence_contexts[0]
                    elif pair.entity_a.contextual_definition:
                        context = f"{pair.entity_a.term}: {pair.entity_a.contextual_definition[:200]}"

                    # Infer relationship
                    result = client.infer_preliminary_relationship(
                        pair.entity_a,
                        pair.entity_b,
                        context
                    )

                    pair.preliminary_relationship = result.get('relationship_type', 'unknown')
                    pair.preliminary_confidence = result.get('confidence', 0.0)
                    pair.preliminary_evidence = result.get('evidence', '')

                    inferred += 1

                except Exception as e:
                    logger.debug(f"    Failed to infer {pair.entity_a.term} <-> {pair.entity_b.term}: {e}")
                    failed += 1

            # Small delay between batches to avoid overwhelming the server
            if batch_num < total_batches:
                import time
                time.sleep(0.5)

        self.stats["preliminary_relationships_inferred"] = inferred
        self.stats["preliminary_relationships_failed"] = failed

        logger.info(f"  ✓ Inferred {inferred} preliminary relationships")
        if failed > 0:
            logger.info(f"  ✗ Failed to infer {failed} relationships")

        # Log distribution of relationship types
        type_counts = Counter(p.preliminary_relationship for p in pairs if p.preliminary_relationship)
        if type_counts:
            logger.info("\n  Preliminary relationship type distribution:")
            for rel_type, count in type_counts.most_common(10):
                logger.info(f"    {rel_type}: {count}")

        return pairs


# ============================================================================
# PHASE 2: RELATIONSHIP EXTRACTION
# ============================================================================

class Phase2RelationshipExtraction:
    """Phase 2: LLM relationship extraction and validation."""

    def __init__(self):
        self.stats = defaultdict(int)
        self.client = None

    def run(self, pairs: List[EntityPair]) -> List[Relationship]:
        """Run relationship extraction and validation."""
        logger.info("=" * 60)
        logger.info("PHASE 2: RELATIONSHIP EXTRACTION")
        logger.info("=" * 60)

        # Check LLM availability
        try:
            self.client = LLMClient()
            self.client._make_request("test", max_tokens=10, timeout=30)
            logger.info("  LLM server available")
        except Exception as e:
            logger.error(f"  LLM server not available: {e}")
            logger.error("  Please start llama.cpp server before running Phase 2")
            logger.error("  Skipping Phase 2 - returning empty relationships")
            return []

        # Pass 1: Extraction
        logger.info("\n[2.2] PASS 1: Extraction...")
        raw_relationships = self._pass1_extraction(pairs)
        self.stats["raw_relationships"] = len(raw_relationships)

        # Post-process
        logger.info("\n[2.4] Post-processing...")
        relationships = self._post_process(raw_relationships, pairs)

        # Pass 2: Validation
        logger.info("\n[2.3] PASS 2: Validation...")
        validated = self._pass2_validation(relationships)
        self.stats["validated_relationships"] = len(validated)

        # Final filtering
        logger.info("\nFinal filtering...")
        final = [r for r in validated
                if r.confidence >= Config.MIN_RELATIONSHIP_CONFIDENCE]

        self.stats["final_relationships"] = len(final)

        # Log statistics by relationship type
        type_counts = Counter(r.relationship_type for r in final)
        logger.info("\nRelationship type distribution:")
        for rel_type, count in type_counts.most_common():
            logger.info(f"  {rel_type}: {count}")

        logger.info("\n" + "=" * 60)
        logger.info(f"PHASE 2 COMPLETE - {len(final)} relationships")
        logger.info("=" * 60)

        return final

    def _pass1_extraction(self, pairs: List[EntityPair]) -> List[Relationship]:
        """Extract relationships using LLM."""
        relationships = []
        batch_size = Config.BATCH_SIZE_EXTRACTION

        # Filter to high-priority pairs only
        pairs = [p for p in pairs if p.priority_score > 0.5]
        logger.info(f"  Processing {len(pairs)} high-priority pairs")

        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i+batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(pairs) + batch_size - 1) // batch_size

            logger.info(f"  Batch {batch_num}/{total_batches} ({len(batch)} pairs)...")

            try:
                extracted = self.client.extract_relationships(batch)

                for ext in extracted:
                    # Find the corresponding entities
                    source = next((e for p in batch
                                  for e in [p.entity_a, p.entity_b]
                                  if e.term == ext.get('source_entity')), None)
                    target = next((e for p in batch
                                  for e in [p.entity_a, p.entity_b]
                                  if e.term == ext.get('target_entity')), None)

                    if source and target:
                        rel = Relationship(
                            source_entity=ext.get('source_entity', ''),
                            target_entity=ext.get('target_entity', ''),
                            source_type=source.entity_type,
                            target_type=target.entity_type,
                            relationship_type=ext.get('relationship_type', ''),
                            confidence=ext.get('confidence', 0.0),
                            evidence=ext.get('evidence', ''),
                            source_context='',
                            paper_id='',
                            pass1_confidence=ext.get('confidence', 0.0)
                        )

                        # Add context from pairs
                        for p in batch:
                            if (p.entity_a.term == rel.source_entity and
                                p.entity_b.term == rel.target_entity):
                                rel.source_context = p.co_occurrence_contexts[0] if p.co_occurrence_contexts else ''
                                rel.paper_id = p.shared_papers[0] if p.shared_papers else ''
                                rel.is_cross_paper = len(p.shared_papers) >= Config.CROSS_PAPER_THRESHOLD
                                break

                        if rel.confidence >= Config.PASS1_CONFIDENCE_THRESHOLD:
                            relationships.append(rel)

            except Exception as e:
                logger.warning(f"    Batch {batch_num} failed: {e}")

        logger.info(f"  Extracted {len(relationships)} relationships")
        return relationships

    def _post_process(self, relationships: List[Relationship],
                     pairs: List[EntityPair]) -> List[Relationship]:
        """Clean and deduplicate relationships."""
        # Remove invalid relationships
        cleaned = [r for r in relationships
                  if r.relationship_type and r.relationship_type != "NONE"
                  and r.source_entity != r.target_entity]

        # Deduplicate by key, keeping highest confidence
        rel_dict = {}
        for rel in cleaned:
            key = rel.get_key()
            if key not in rel_dict or rel.confidence > rel_dict[key].confidence:
                rel_dict[key] = rel

        logger.info(f"  After deduplication: {len(rel_dict)} unique relationships")

        self.stats["deduped_relationships"] = len(rel_dict)

        return list(rel_dict.values())

    def _pass2_validation(self, relationships: List[Relationship]) -> List[Relationship]:
        """Validate relationships using rule-based and LLM checks."""
        validated = []

        # Track A: Rule-based pre-filter
        logger.info("  Track A: Rule-based filtering...")
        rule_passed = self._rule_based_filter(relationships)
        logger.info(f"    {len(rule_passed)} passed rule-based filter")

        # Track B: LLM validation (on a sample for efficiency)
        logger.info("  Track B: LLM validation...")
        sample_size = min(1000, len(rule_passed))
        sample = random.sample(rule_passed, sample_size)

        for rel in sample:
            try:
                verdict = self.client.validate_relationship(rel, rel.source_context)

                # Check validation criteria
                if (verdict.get('plausible') == 'yes' and
                    verdict.get('direction') in ['yes', 'reversed'] and
                    verdict.get('evidence_support') in ['yes', 'partial']):

                    # Handle reversed direction
                    if verdict.get('direction') == 'reversed':
                        rel.source_entity, rel.target_entity = rel.source_entity, rel.target_entity
                        rel.source_type, rel.target_type = rel.target_type, rel.source_type

                    # Apply suggested type if provided
                    suggested = verdict.get('suggested_type', '')
                    if suggested and suggested != rel.relationship_type:
                        rel.relationship_type = suggested

                    # Set verdict and adjust confidence
                    rel.pass2_verdict = "VALID"
                    evidence_mult = 1.0 if verdict.get('evidence_support') == 'yes' else 0.9
                    rel.confidence = rel.pass1_confidence * evidence_mult

                    # Compute evidence strength
                    rel.evidence_strength = (
                        rel.pass1_confidence * 0.6 +
                        (1.0 if rel.pass2_verdict == 'VALID' else 0) * 0.3 +
                        (0.2 if rel.is_cross_paper else 0) * 0.1
                    )

                    validated.append(rel)

            except Exception as e:
                logger.debug(f"    Validation failed for {rel.source_entity}: {e}")

        logger.info(f"    {len(validated)}/{sample_size} relationships validated")

        return validated

    def _rule_based_filter(self, relationships: List[Relationship]) -> List[Relationship]:
        """Apply rule-based filters."""
        passed = []

        for rel in relationships:
            # Confidence floor
            if rel.pass1_confidence < Config.PASS2_CONFIDENCE_FLOOR:
                continue

            # Type-relationship compatibility check
            type_pair = (rel.source_type, rel.target_type)
            invalid_rels = Config.INVALID_RELATIONSHIPS.get(type_pair, [])

            if rel.relationship_type in invalid_rels:
                continue

            # Context verification
            if not rel.source_context:
                continue

            # Entity names must appear in context
            if (rel.source_entity.lower() not in rel.source_context.lower() or
                rel.target_entity.lower() not in rel.source_context.lower()):
                continue

            passed.append(rel)

        return passed


# ============================================================================
# PHASE 3: GRAPH CONSTRUCTION
# ============================================================================

class Phase3GraphConstruction:
    """Phase 3: Knowledge graph construction."""

    def __init__(self):
        self.stats = defaultdict(int)

    def run(self, entities: List[Entity],
           relationships: List[Relationship]) -> nx.MultiDiGraph:
        """Build enriched knowledge graph."""
        logger.info("=" * 60)
        logger.info("PHASE 3: GRAPH CONSTRUCTION")
        logger.info("=" * 60)

        # Create graph
        logger.info("\n[3.1] Building graph structure...")
        graph = self._build_graph(entities, relationships)

        # Compute metrics
        logger.info("\n[3.3] Computing network metrics...")
        graph = self._compute_metrics(graph)

        # Detect communities
        logger.info("\n[3.2] Running community detection...")
        graph = self._detect_communities(graph)

        # Filter graph
        logger.info("\n[3.4] Filtering graph...")
        graph = self._filter_graph(graph)

        # Collect statistics
        self._collect_statistics(graph)

        logger.info("\n" + "=" * 60)
        logger.info("PHASE 3 COMPLETE - STATISTICS:")
        for key, value in sorted(self.stats.items()):
            logger.info(f"  {key}: {value}")
        logger.info("=" * 60)

        return graph

    def _build_graph(self, entities: List[Entity],
                    relationships: List[Relationship]) -> nx.MultiDiGraph:
        """Build NetworkX graph from entities and relationships."""
        graph = nx.MultiDiGraph()

        # Add nodes
        for entity in entities:
            graph.add_node(
                entity.term,
                term=entity.term,
                type=entity.entity_type,
                confidence=entity.confidence_score,
                definition=entity.definition,
                aliases=entity.aliases,
                umls_cui=entity.UMLS_ID,
                omop_id=entity.OMOP,
                ols=entity.OLS,
                bioportal=entity.Bioportal,
                frequency=entity.frequency,
                relevance=entity.relevance_classification,
                is_core_term=entity.is_core_term,
                paper_count=entity.paper_count,
                is_computed_metric=entity.is_computed_metric
            )

        self.stats["nodes"] = graph.number_of_nodes()

        # Add edges
        for rel in relationships:
            graph.add_edge(
                rel.source_entity,
                rel.target_entity,
                relationship_type=rel.relationship_type,
                confidence=rel.confidence,
                pass1_confidence=rel.pass1_confidence,
                pass2_verdict=rel.pass2_verdict,
                evidence=rel.evidence,
                source_context=rel.source_context,
                paper_id=rel.paper_id,
                is_cross_paper=rel.is_cross_paper,
                evidence_strength=rel.evidence_strength
            )

        self.stats["edges"] = graph.number_of_edges()

        logger.info(f"  Graph: {self.stats['nodes']} nodes, {self.stats['edges']} edges")

        return graph

    def _compute_metrics(self, graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        """Compute network metrics."""
        # Convert to undirected for some metrics
        undirected = graph.to_undirected()

        # Degree centrality
        degree_centrality = nx.degree_centrality(graph)
        nx.set_node_attributes(graph, degree_centrality, 'degree_centrality')

        # Betweenness centrality (sample for large graphs)
        if graph.number_of_nodes() < 5000:
            betweenness = nx.betweenness_centrality(undirected)
        else:
            k = min(500, graph.number_of_nodes())
            betweenness = nx.betweenness_centrality(undirected, k=k)
        nx.set_node_attributes(graph, betweenness, 'betweenness_centrality')

        # PageRank
        pagerank = nx.pagerank(graph)
        nx.set_node_attributes(graph, pagerank, 'pagerank')

        # Edge betweenness (sample)
        if graph.number_of_edges() < 5000:
            edge_betweenness = nx.edge_betweenness_centrality(undirected)
        else:
            k = min(500, graph.number_of_edges())
            edge_betweenness = nx.edge_betweenness_centrality(undirected, k=k)

        nx.set_edge_attributes(graph, edge_betweenness, 'edge_betweenness')

        logger.info("  Computed degree, betweenness, PageRank metrics")

        return graph

    def _detect_communities(self, graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        """Detect communities using Louvain algorithm."""
        undirected = graph.to_undirected()

        try:
            partition = community_louvain.best_partition(undirected)

            # Add community to node attributes
            nx.set_node_attributes(graph, partition, 'community')

            # Count communities
            num_communities = max(partition.values()) + 1
            self.stats["communities"] = num_communities

            # Label communities based on dominant types
            community_labels = self._label_communities(graph, partition)
            nx.set_node_attributes(graph, community_labels, 'community_label')

            logger.info(f"  Detected {num_communities} communities")

        except Exception as e:
            logger.warning(f"  Community detection failed: {e}")
            nx.set_node_attributes(graph, {n: 0 for n in graph.nodes()}, 'community')
            nx.set_node_attributes(graph, {n: "unknown" for n in graph.nodes()}, 'community_label')

        return graph

    def _label_communities(self, graph: nx.MultiDiGraph,
                          partition: Dict[str, int]) -> Dict[str, str]:
        """Generate labels for communities based on dominant types."""
        community_types = defaultdict(Counter)

        for node, comm_id in partition.items():
            node_type = graph.nodes[node].get('type', 'UNKNOWN')
            community_types[comm_id][node_type] += 1

        labels = {}
        for node, comm_id in partition.items():
            type_counts = community_types[comm_id]
            total = sum(type_counts.values())

            # Get top 2 types
            top_types = [t for t, _ in type_counts.most_common(2)]

            # Generate label
            if 'ORGANISM' in top_types and 'DISEASE' in top_types:
                label = 'host_pathogen'
            elif 'ORGANISM' in top_types and 'CHEMICAL' in top_types:
                label = 'metabolite_production'
            elif 'GENE' in top_types or 'PROTEIN' in top_types:
                label = 'genomic_regulation'
            elif 'EXPERIMENTAL_METHOD' in top_types:
                label = 'methods_provenance'
            elif 'DISEASE' in top_types and 'CHEMICAL' in top_types:
                label = 'therapeutic_targets'
            elif 'CLINICAL' in top_types:
                label = 'clinical_phenotypes'
            elif len(top_types) >= 2:
                label = f"{top_types[0].lower()}_{top_types[1].lower()}"
            else:
                label = top_types[0].lower() if top_types else 'mixed'

            labels[node] = label

        return labels

    def _filter_graph(self, graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        """Filter graph based on criteria."""
        nodes_to_remove = []

        for node in graph.nodes():
            data = graph.nodes[node]
            degree = graph.degree(node)

            # Remove orphan nodes unless core term or high confidence
            if (degree == 0 and
                not data.get('is_core_term', False) and
                data.get('confidence', 0) < Config.CORE_TERM_KEEP_THRESHOLD):
                nodes_to_remove.append(node)

        graph.remove_nodes_from(nodes_to_remove)

        # Log isolated subgraphs
        components = list(nx.weakly_connected_components(graph))
        small_components = [c for c in components if len(c) < Config.MIN_COMMUNITY_SIZE]

        self.stats["isolated_nodes_removed"] = len(nodes_to_remove)
        self.stats["small_components"] = len(small_components)
        self.stats["final_nodes"] = graph.number_of_nodes()
        self.stats["final_edges"] = graph.number_of_edges()

        logger.info(f"  Removed {len(nodes_to_remove)} isolated nodes")
        logger.info(f"  Found {len(small_components)} small components")

        return graph

    def _collect_statistics(self, graph: nx.MultiDiGraph):
        """Collect and save graph statistics."""
        stats = {
            'nodes': graph.number_of_nodes(),
            'edges': graph.number_of_edges(),
            'avg_degree': np.mean([d for _, d in graph.degree()]),
            'density': nx.density(graph),
            'weakly_connected_components': nx.number_weakly_connected_components(graph),
            'entity_types': dict(Counter([graph.nodes[n].get('type', 'UNKNOWN')
                                        for n in graph.nodes()])),
            # graph is a MultiDiGraph - graph.edges() without keys=True yields 2-tuples,
            # but graph.edges[e] indexing requires the 3-tuple (u, v, key) form (that's
            # what threw ValueError: not enough values to unpack here originally).
            'relationship_types': dict(Counter([graph.edges[e].get('relationship_type', 'UNKNOWN')
                                               for e in graph.edges(keys=True)])),
            'communities': len(set([graph.nodes[n].get('community', 0)
                                   for n in graph.nodes()])),
            'avg_confidence': np.mean([graph.nodes[n].get('confidence', 0)
                                      for n in graph.nodes()]),
            'core_terms': sum(1 for n in graph.nodes()
                            if graph.nodes[n].get('is_core_term', False)),
            'umls_coverage': sum(1 for n in graph.nodes()
                                 if graph.nodes[n].get('umls_cui', '')) / graph.number_of_nodes()
        }

        # Community statistics
        communities = defaultdict(list)
        for node in graph.nodes():
            comm = graph.nodes[node].get('community', 0)
            communities[comm].append(node)

        stats['community_sizes'] = {str(k): len(v) for k, v in communities.items()}

        save_json(stats, Config.OUTPUT_DIR / "kg_statistics.json")

    def export_formats(self, graph: nx.MultiDiGraph):
        """Export graph in multiple formats."""
        logger.info("\n[3.5] Exporting graph formats...")

        # JSON format (enriched)
        data = nx.node_link_data(graph)
        save_json(data, Config.OUTPUT_DIR / "cdm_kg_enriched.json")

        # GEXF for Gephi
        nx.write_gexf(graph, Config.OUTPUT_DIR / "cdm_kg_enriched.gexf")
        logger.info("  Exported GEXF format")

        # GraphML for Cytoscape
        # Convert sets to lists for GraphML compatibility
        graph_ml = graph.copy()
        for node in graph_ml.nodes():
            for key, value in list(graph_ml.nodes[node].items()):
                if isinstance(value, (set, tuple)):
                    graph_ml.nodes[node][key] = list(value)

        nx.write_graphml(graph_ml, Config.OUTPUT_DIR / "cdm_kg_enriched.graphml")
        logger.info("  Exported GraphML format")


# ============================================================================
# PHASE 4: VISUALIZATION
# ============================================================================

class Phase4Visualization:
    """Phase 4: Interactive HTML visualization."""

    def __init__(self):
        self.stats = defaultdict(int)

    def run(self, graph: nx.MultiDiGraph):
        """Generate interactive HTML visualization."""
        logger.info("=" * 60)
        logger.info("PHASE 4: VISUALIZATION")
        logger.info("=" * 60)

        logger.info("\n[4.1] Preparing visualization data...")

        # Convert graph to JSON format for D3.js
        graph_data = self._prepare_graph_data(graph)

        # Generate HTML
        logger.info("\n[4.2] Generating HTML...")
        html = self._generate_html(graph_data, graph)

        # Save HTML
        output_file = Config.OUTPUT_DIR / "cdm_kg_interactive.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        logger.info(f"\n[4.3] Saved visualization to {output_file}")
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 4 COMPLETE")
        logger.info("=" * 60)

    def _prepare_graph_data(self, graph: nx.MultiDiGraph) -> Dict:
        """Convert graph to D3.js compatible format."""
        nodes = []
        links = []

        for node, data in graph.nodes(data=True):
            nodes.append({
                'id': node,
                'type': data.get('type', 'UNKNOWN'),
                'confidence': data.get('confidence', 0),
                'pagerank': data.get('pagerank', 0),
                'degree_centrality': data.get('degree_centrality', 0),
                'community': data.get('community', 0),
                'community_label': data.get('community_label', 'unknown'),
                'is_core_term': data.get('is_core_term', False),
                'umls_cui': data.get('umls_cui', ''),
                'definition': data.get('definition', ''),
                'paper_count': data.get('paper_count', 0)
            })

        for source, target, data in graph.edges(data=True):
            links.append({
                'source': source,
                'target': target,
                'relationship_type': data.get('relationship_type', ''),
                'confidence': data.get('confidence', 0),
                'is_cross_paper': data.get('is_cross_paper', False),
                'evidence_strength': data.get('evidence_strength', 0),
                'evidence': data.get('evidence', ''),
                'source_context': data.get('source_context', '')
            })

        return {'nodes': nodes, 'links': links}

    def _generate_html(self, graph_data: Dict, graph: nx.MultiDiGraph) -> str:
        """Generate complete HTML file with D3.js visualization."""

        # Get all unique types for filter
        entity_types = sorted(set(n['type'] for n in graph_data['nodes']))
        relationship_types = sorted(set(l['relationship_type'] for l in graph_data['links']))
        communities = sorted(set(n['community_label'] for n in graph_data['nodes']))

        type_colors = json.dumps(Config.TYPE_COLORS)

        # Write data to JSON file that HTML will load
        data_file = Config.OUTPUT_DIR / "cdm_kg_data.json"
        save_json(graph_data, data_file, pretty=True)

        # Generate standalone HTML that loads data via fetch
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDM Knowledge Graph Visualization</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1a1a2e; color: #eaeaea; overflow: hidden; }
        #container { display: flex; height: 100vh; }
        #sidebar { width: 320px; background-color: #16213e; padding: 20px; overflow-y: auto; border-right: 1px solid #0f3460; }
        #main { flex: 1; position: relative; }
        #viz { width: 100%; height: 100%; }
        h1 { font-size: 1.5rem; margin-bottom: 20px; color: #e94560; }
        h2 { font-size: 1.1rem; margin: 15px 0 10px; color: #533483; }
        .control-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; font-size: 0.9rem; color: #a8a8a8; }
        select, input { width: 100%; padding: 8px; background-color: #0f3460; border: 1px solid #533483; color: #eaeaea; border-radius: 4px; font-size: 0.9rem; }
        button { width: 100%; padding: 10px; margin-top: 10px; background-color: #e94560; border: none; color: white; border-radius: 4px; cursor: pointer; font-weight: bold; }
        button:hover { background-color: #ff6b6b; }
        .checkbox-group { max-height: 200px; overflow-y: auto; }
        .checkbox-item { display: flex; align-items: center; margin-bottom: 5px; }
        .checkbox-item input { width: auto; margin-right: 8px; }
        .checkbox-item label { margin: 0; }
        #stats { margin-top: 20px; padding: 15px; background-color: #0f3460; border-radius: 4px; font-size: 0.85rem; }
        #stats div { margin-bottom: 5px; }
        #node-info, #edge-info { position: absolute; background-color: rgba(22, 33, 62, 0.95); padding: 15px; border-radius: 8px; border: 1px solid #533483; max-width: 400px; max-height: 300px; overflow-y: auto; pointer-events: none; opacity: 0; transition: opacity 0.3s; z-index: 1000; }
        #node-info.visible, #edge-info.visible { opacity: 1; }
        #node-info h3, #edge-info h3 { color: #e94560; margin-bottom: 10px; }
        #node-info p, #edge-info p { margin-bottom: 8px; font-size: 0.9rem; line-height: 1.4; }
        #node-info a, #edge-info a { color: #533483; text-decoration: none; }
        .legend { margin-top: 20px; }
        .legend-item { display: flex; align-items: center; margin-bottom: 5px; font-size: 0.85rem; }
        .legend-color { width: 20px; height: 20px; margin-right: 10px; border-radius: 3px; }
        .badge { display: inline-block; padding: 2px 6px; background-color: #e94560; border-radius: 3px; font-size: 0.75rem; margin-left: 5px; }
        #loading { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 1.5rem; color: #e94560; }
    </style>
</head>
<body>
    <div id="loading">Loading knowledge graph...</div>
    <div id="container" style="display:none;">
        <div id="sidebar">
            <h1>CDM Knowledge Graph</h1>
            <div class="control-group">
                <label>View Mode</label>
                <select id="view-mode">
                    <option value="summary">Summary (Top 200)</option>
                    <option value="subgraph">By Community</option>
                    <option value="full">Full Graph</option>
                </select>
            </div>
            <div class="control-group" id="community-select" style="display:none;">
                <label>Community</label>
                <select id="community-filter"><option value="all">All Communities</option></select>
            </div>
            <div class="control-group">
                <label>Min Edge Confidence: <span id="conf-value">0.85</span></label>
                <input type="range" id="confidence-slider" min="0" max="1" step="0.05" value="0.85">
            </div>
            <div class="control-group">
                <h2>Filter by Entity Type</h2>
                <div class="checkbox-group" id="entity-type-filters"></div>
            </div>
            <div class="control-group">
                <h2>Filter by Relationship</h2>
                <div class="checkbox-group" id="relationship-filters"></div>
            </div>
            <div class="control-group">
                <label>Search Nodes</label>
                <input type="text" id="search-input" placeholder="Search...">
            </div>
            <div class="control-group">
                <button id="reset-zoom">Reset Zoom</button>
                <button id="export-json">Export Subgraph (JSON)</button>
            </div>
            <div class="legend">
                <h2>Entity Types</h2>
                <div id="legend-items"></div>
            </div>
            <div id="stats">
                <div><strong>Statistics</strong></div>
                <div id="stats-content"></div>
            </div>
        </div>
        <div id="main">
            <div id="viz"></div>
            <div id="node-info"></div>
            <div id="edge-info"></div>
        </div>
    </div>

    <script>
        let fullData = {nodes: [], links: []};
        let currentData = {nodes: [], links: []};
        const typeColors = """ + type_colors + """;
        let simulation, svg, g, zoom;
        let selectedNode = null;
        let highlightedNodes = new Set();
        let pathNodes = new Set();

        // Load data
        fetch('cdm_kg_data.json')
            .then(r => r.json())
            .then(data => {
                fullData = data;
                document.getElementById('loading').style.display = 'none';
                document.getElementById('container').style.display = 'flex';
                initializeFilters();
                initializeVisualization();
                updateStats();
            })
            .catch(err => {
                document.getElementById('loading').textContent = 'Error loading data: ' + err;
            });

        function initializeFilters() {
            const entityTypes = [...new Set(fullData.nodes.map(n => n.type))].sort();
            const relTypes = [...new Set(fullData.links.map(l => l.relationship_type))].sort();
            const communities = [...new Set(fullData.nodes.map(n => n.community_label))].sort();

            const entityTypeContainer = document.getElementById('entity-type-filters');
            entityTypes.forEach(type => {
                const div = document.createElement('div');
                div.className = 'checkbox-item';
                div.innerHTML = `<input type="checkbox" id="type-${type}" value="${type}" checked>
                    <label for="type-${type}">${type}</label>`;
                entityTypeContainer.appendChild(div);
            });

            const relContainer = document.getElementById('relationship-filters');
            relTypes.forEach(rel => {
                const div = document.createElement('div');
                div.className = 'checkbox-item';
                div.innerHTML = `<input type="checkbox" id="rel-${rel}" value="${rel}" checked>
                    <label for="rel-${rel}">${rel}</label>`;
                relContainer.appendChild(div);
            });

            const commSelect = document.getElementById('community-filter');
            communities.forEach(comm => {
                const option = document.createElement('option');
                option.value = comm;
                option.textContent = comm;
                commSelect.appendChild(option);
            });

            const legendContainer = document.getElementById('legend-items');
            entityTypes.forEach(type => {
                const div = document.createElement('div');
                div.className = 'legend-item';
                div.innerHTML = `<div class="legend-color" style="background-color: ${typeColors[type] || '#888'}"></div>
                    <span>${type}</span>`;
                legendContainer.appendChild(div);
            });
        }

        function initializeVisualization() {
            const width = document.getElementById('main').clientWidth;
            const height = document.getElementById('main').clientHeight;

            svg = d3.select('#viz').append('svg').attr('width', width).attr('height', height);
            g = svg.append('g');

            zoom = d3.zoom().scaleExtent([0.1, 4]).on('zoom', (e) => {
                g.attr('transform', e.transform);
            });
            svg.call(zoom);

            const defs = svg.append('defs');
            ['causal', 'molecular', 'metabolic', 'statistical'].forEach(type => {
                const markerColor = type === 'causal' ? '#ff6b6b' : type === 'molecular' ? '#4dabf7' : type === 'metabolic' ? '#51cf66' : '#adb5bd';
                defs.append('marker')
                    .attr('id', `arrow-${type}`)
                    .attr('viewBox', '0 -5 10 10')
                    .attr('refX', 20)
                    .attr('refY', 0)
                    .attr('markerWidth', 8)
                    .attr('markerHeight', 8)
                    .attr('orient', 'auto')
                    .append('path')
                    .attr('fill', markerColor)
                    .attr('d', 'M0,-5L10,0L0,5');
            });

            applyFilters();
            document.getElementById('view-mode').addEventListener('change', handleViewChange);
            document.getElementById('confidence-slider').addEventListener('input', handleConfidenceChange);
            document.getElementById('community-filter').addEventListener('change', applyFilters);
            document.getElementById('search-input').addEventListener('input', handleSearch);
            document.getElementById('reset-zoom').addEventListener('click', resetZoom);
            document.getElementById('export-json').addEventListener('click', exportSubgraph);
            document.querySelectorAll('#entity-type-filters input, #relationship-filters input').forEach(cb => {
                cb.addEventListener('change', applyFilters);
            });
        }

        function handleViewChange() {
            const mode = document.getElementById('view-mode').value;
            document.getElementById('community-select').style.display = mode === 'subgraph' ? 'block' : 'none';
            applyFilters();
        }

        function handleConfidenceChange(e) {
            document.getElementById('conf-value').textContent = e.target.value;
            applyFilters();
        }

        function applyFilters() {
            const mode = document.getElementById('view-mode').value;
            const minConf = parseFloat(document.getElementById('confidence-slider').value);
            const community = document.getElementById('community-filter').value;

            const selectedTypes = new Set();
            document.querySelectorAll('#entity-type-filters input:checked').forEach(cb => selectedTypes.add(cb.value));

            const selectedRels = new Set();
            document.querySelectorAll('#relationship-filters input:checked').forEach(cb => selectedRels.add(cb.value));

            let nodes = fullData.nodes;
            if (mode === 'summary') {
                nodes = nodes.sort((a, b) => b.pagerank - a.pagerank).slice(0, 200);
            } else if (mode === 'subgraph' && community !== 'all') {
                nodes = nodes.filter(n => n.community_label === community);
            }
            nodes = nodes.filter(n => selectedTypes.has(n.type));
            const nodeIds = new Set(nodes.map(n => n.id));

            let links = fullData.links.filter(l => nodeIds.has(l.source) && nodeIds.has(l.target) && l.confidence >= minConf && selectedRels.has(l.relationship_type));
            links = links.map(l => ({...l, source: nodes.find(n => n.id === l.source), target: nodes.find(n => n.id === l.target)})).filter(l => l.source && l.target);

            currentData = {nodes, links};
            renderGraph();
        }

        function renderGraph() {
            const width = document.getElementById('main').clientWidth;
            const height = document.getElementById('main').clientHeight;
            g.selectAll('*').remove();

            if (currentData.nodes.length === 0) {
                g.append('text').attr('x', width/2).attr('y', height/2).attr('text-anchor', 'middle').attr('fill', '#888').text('No matching nodes');
                return;
            }

            simulation = d3.forceSimulation(currentData.nodes)
                .force('link', d3.forceLink(currentData.links).id(d => d.id).distance(d => 100 / (d.confidence + 0.1)))
                .force('charge', d3.forceManyBody().strength(-300))
                .force('center', d3.forceCenter(width/2, height/2))
                .force('collision', d3.forceCollide().radius(30));

            const getEdgeColor = d => {
                if (['causes', 'treats'].includes(d.relationship_type)) return '#ff6b6b';
                if (['produces', 'metabolizes'].includes(d.relationship_type)) return '#51cf66';
                if (['encodes', 'regulates', 'activates'].includes(d.relationship_type)) return '#4dabf7';
                return '#adb5bd';
            };

            const link = g.append('g').selectAll('line').data(currentData.links).join('line')
                .attr('stroke', getEdgeColor).attr('stroke-opacity', d => 0.3 + d.confidence * 0.5)
                .attr('stroke-width', d => 1 + d.evidence_strength * 3)
                .attr('stroke-dasharray', d => d.is_cross_paper ? 'none' : '5,5')
                .on('click', (e, d) => { e.stopPropagation(); handleEdgeHover(e, d); })
                .on('mouseover', handleEdgeHover).on('mouseout', () => hideEdgeInfo());

            const node = g.append('g').selectAll('circle').data(currentData.nodes).join('circle')
                .attr('r', d => 4 + d.pagerank * 16).attr('fill', d => typeColors[d.type] || '#888')
                .attr('stroke', d => d.is_core_term ? '#e94560' : '#fff')
                .attr('stroke-width', d => d.is_core_term ? 3 : 1).style('cursor', 'pointer')
                .call(d3.drag().on('start', dragstarted).on('drag', dragged).on('end', dragended))
                .on('click', handleNodeClick).on('mouseover', handleNodeHover).on('mouseout', hideNodeInfo);

            const label = g.append('g').selectAll('text').data(currentData.nodes.filter(n => n.pagerank > 0.01 || n.is_core_term)).join('text')
                .text(d => d.id).attr('font-size', 10).attr('fill', '#ccc').attr('text-anchor', 'middle').attr('dy', -20).style('pointer-events', 'none');

            simulation.on('tick', () => {
                link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
                node.attr('cx', d => d.x).attr('cy', d => d.y);
                label.attr('x', d => d.x).attr('y', d => d.y);
            });
            updateStats();
        }

        function handleNodeClick(e, d) {
            e.stopPropagation();
            selectedNode = d;
            highlightedNodes.clear();
            highlightedNodes.add(d.id);
            currentData.links.filter(l => l.source.id === d.id || l.target.id === d.id).forEach(l => {
                highlightedNodes.add(l.source.id);
                highlightedNodes.add(l.target.id);
            });
            g.selectAll('circle').attr('opacity', n => highlightedNodes.has(n.id) ? 1 : 0.3);
            g.selectAll('line').attr('opacity', l => (l.source.id === d.id || l.target.id === d.id) ? 1 : 0.1);
            showNodeInfo(d, e);
        }

        function handleNodeHover(e, d) {
            if (selectedNode) return;
            showNodeInfo(d, e);
        }

        function showNodeInfo(d, e) {
            const info = document.getElementById('node-info');
            const umlsLink = d.umls_cui ? `<a href="https://identifier.nlm.nih.gov/mesh/${d.umls_cui}" target="_blank">UMLS: ${d.umls_cui}</a>` : '';
            info.innerHTML = `<h3>${d.id}</h3><p><strong>Type:</strong> ${d.type}</p><p><strong>Confidence:</strong> ${d.confidence.toFixed(2)}</p>
                <p><strong>PageRank:</strong> ${d.pagerank.toFixed(4)}</p><p><strong>Community:</strong> ${d.community_label}</p>
                ${d.is_core_term ? '<p><span class="badge">Core Term</span></p>' : ''}
                ${umlsLink ? `<p>${umlsLink}</p>` : ''}
                <p style="margin-top:10px;"><strong>Definition:</strong></p><p style="font-size:0.85rem;color:#aaa;">${d.definition || 'No definition'}</p>`;
            info.style.left = (e.pageX + 15) + 'px';
            info.style.top = (e.pageY + 15) + 'px';
            info.classList.add('visible');
        }

        function hideNodeInfo() {
            if (!selectedNode) document.getElementById('node-info').classList.remove('visible');
        }

        function hideEdgeInfo() {
            document.getElementById('edge-info').classList.remove('visible');
        }

        function handleEdgeHover(e, d) {
            const info = document.getElementById('edge-info');
            info.innerHTML = `<h3>${d.source.id} → ${d.target.id}</h3><p><strong>Relationship:</strong> ${d.relationship_type}</p>
                <p><strong>Confidence:</strong> ${d.confidence.toFixed(2)}</p>
                ${d.is_cross_paper ? '<p><span class="badge">Cross-Paper</span></p>' : ''}
                <p style="margin-top:10px;"><strong>Evidence:</strong></p><p style="font-size:0.85rem;color:#aaa;">${d.evidence || 'No evidence'}</p>`;
            info.style.left = (e.pageX + 15) + 'px';
            info.style.top = (e.pageY + 15) + 'px';
            info.classList.add('visible');
        }

        function handleSearch(e) {
            const query = e.target.value.toLowerCase();
            if (!query) {
                highlightedNodes.clear();
                g.selectAll('circle').attr('opacity', 1);
                return;
            }
            highlightedNodes.clear();
            currentData.nodes.filter(n => n.id.toLowerCase().includes(query)).forEach(n => highlightedNodes.add(n.id));
            g.selectAll('circle').attr('opacity', n => highlightedNodes.has(n.id) ? 1 : 0.2);
        }

        function resetZoom() {
            svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity);
            selectedNode = null;
            highlightedNodes.clear();
            pathNodes.clear();
            g.selectAll('circle').attr('opacity', 1);
            g.selectAll('line').attr('opacity', 1);
        }

        function exportSubgraph() {
            const dataStr = JSON.stringify(currentData, null, 2);
            const blob = new Blob([dataStr], {type: 'application/json'});
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'cdm_kg_subgraph.json';
            a.click();
        }

        function updateStats() {
            const stats = document.getElementById('stats-content');
            const avgConf = currentData.nodes.length > 0 ? (currentData.nodes.reduce((s, n) => s + n.confidence, 0) / currentData.nodes.length).toFixed(2) : 0;
            const density = currentData.nodes.length > 1 ? (currentData.links.length / (currentData.nodes.length * (currentData.nodes.length - 1) / 2)).toFixed(4) : 0;
            stats.innerHTML = `<div>Nodes: ${currentData.nodes.length}</div><div>Links: ${currentData.links.length}</div><div>Density: ${density}</div><div>Avg Confidence: ${avgConf}</div>`;
        }

        function dragstarted(e, d) { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
        function dragged(e, d) { d.fx = e.x; d.fy = e.y; }
        function dragended(e, d) { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }
    </script>
</body>
</html>"""
        return html


# ============================================================================
# CHECKPOINT MANAGER - AUTO-SAVE EVERY 10 MINUTES
# ============================================================================

class CheckpointManager:
    """Manages periodic checkpointing for long-running phases."""

    def __init__(self, checkpoint_interval: int = 600):
        """
        Args:
            checkpoint_interval: Seconds between checkpoints (default: 600 = 10 min)
        """
        self.checkpoint_interval = checkpoint_interval
        self.last_checkpoint = {}
        self.checkpoint_dir = Config.TEMP_DIR / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def should_checkpoint(self, phase: str, key: str = "default") -> bool:
        """Check if enough time has passed since last checkpoint."""
        current_time = time.time()
        last_time = self.last_checkpoint.get(f"{phase}_{key}", 0)
        return (current_time - last_time) >= self.checkpoint_interval

    def save_checkpoint(self, phase: str, key: str, data: Any):
        """Save checkpoint data."""
        checkpoint_file = self.checkpoint_dir / f"{phase}_{key}.json"
        save_json(data, checkpoint_file, pretty=False)
        self.last_checkpoint[f"{phase}_{key}"] = time.time()
        logger.info(f"  Checkpoint saved: {checkpoint_file}")

    def load_checkpoint(self, phase: str, key: str = "default") -> Any:
        """Load checkpoint data if exists."""
        checkpoint_file = self.checkpoint_dir / f"{phase}_{key}.json"
        if checkpoint_file.exists():
            logger.info(f"  Loading checkpoint: {checkpoint_file}")
            return load_json(checkpoint_file)
        return None

    def clear_checkpoints(self, phase: str = None):
        """Clear checkpoints for a phase or all phases."""
        if phase:
            for f in self.checkpoint_dir.glob(f"{phase}_*.json"):
                f.unlink()
        else:
            for f in self.checkpoint_dir.glob("*.json"):
                f.unlink()


# ============================================================================
# PHASE 5: METADATA INTEGRATION
# ============================================================================

class Phase5MetadataIntegration:
    """Phase 5: Metadata Integration with bioproject database and sample metadata."""

    def __init__(self, checkpoint_manager: CheckpointManager = None):
        self.checkpoint = checkpoint_manager or CheckpointManager()
        self.stats = defaultdict(int)

    def run(self, graph: nx.MultiDiGraph, entities: List[Entity],
             bioproject_db: str = str(_CDM_ROOT / "bioproject_database.db"),
             samples_dir: Path = Path(str(_CDM_ROOT / "data/168000-samples-paper"))) -> nx.MultiDiGraph:
        """Run metadata integration."""
        logger.info("=" * 60)
        logger.info("PHASE 5: METADATA INTEGRATION")
        logger.info("=" * 60)

        # Step 5.1: Load bioproject database
        logger.info("\n[5.1] Loading bioproject database...")
        bioproject_entities = self._load_bioproject_db(bioproject_db)

        # Step 5.2: Link KG entities to bioprojects
        logger.info("\n[5.2] Linking entities to bioprojects...")
        entity_to_bioprojects = self._link_to_bioprojects(entities, bioproject_entities)
        self.stats["entities_with_bioprojects"] = len(entity_to_bioprojects)

        # Step 5.3: Load sample metadata (if available)
        logger.info("\n[5.3] Loading sample metadata...")
        sample_metadata = self._load_sample_metadata(samples_dir)

        # Step 5.4: Enrich graph nodes with metadata
        logger.info("\n[5.4] Enriching graph nodes with metadata...")
        graph = self._enrich_graph(graph, entity_to_bioprojects, sample_metadata)

        # Step 5.5: Generate metadata statistics
        logger.info("\n[5.5] Generating metadata statistics...")
        stats = self._generate_metadata_stats(graph, entity_to_bioprojects, sample_metadata)
        save_json(stats, Config.OUTPUT_DIR / "metadata_statistics.json")

        # Step 5.6: Export metadata-enriched graph
        logger.info("\n[5.6] Exporting metadata-enriched graph...")
        self._export_metadata_graph(graph, stats)

        logger.info("\n" + "=" * 60)
        logger.info("PHASE 5 COMPLETE - STATISTICS:")
        for key, value in sorted(self.stats.items()):
            logger.info(f"  {key}: {value}")
        logger.info("=" * 60)

        return graph

    def _load_bioproject_db(self, db_path: str) -> Dict[str, List[Dict]]:
        """Load entities from bioproject database."""
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Load all entities grouped by bioproject_id
        cursor.execute("""
            SELECT bioproject_id, entity, entity_type, confidence, definition
            FROM entities
            ORDER BY bioproject_id, confidence DESC
        """)

        bioproject_entities = defaultdict(list)
        for row in cursor.fetchall():
            bioproject_entities[row["bioproject_id"]].append(dict(row))

        conn.close()

        self.stats["total_bioprojects"] = len(bioproject_entities)
        self.stats["total_db_entities"] = sum(len(v) for v in bioproject_entities.values())

        logger.info(f"  Loaded {len(bioproject_entities)} bioprojects")
        logger.info(f"  Total entities in DB: {self.stats['total_db_entities']}")

        return bioproject_entities

    def _link_to_bioprojects(self, entities: List[Entity],
                             bioproject_entities: Dict[str, List[Dict]]) -> Dict[str, List[str]]:
        """Link KG entities to bioprojects."""
        entity_to_bioprojects = defaultdict(set)

        # Create a lookup map for DB entities
        db_entity_map = defaultdict(dict)
        for bp_id, entities_list in bioproject_entities.items():
            for ent in entities_list:
                term = ent["entity"].lower()
                db_entity_map[term][bp_id] = ent["confidence"]

        # Match KG entities to bioprojects
        matched_count = 0
        for entity in entities:
            term_lower = entity.term.lower()
            if term_lower in db_entity_map:
                for bp_id, conf in db_entity_map[term_lower].items():
                    entity_to_bioprojects[entity.term].add(bp_id)
                    matched_count += 1

        # Convert sets to lists for JSON serialization
        entity_to_bioprojects = {k: list(v) for k, v in entity_to_bioprojects.items()}

        self.stats["entities_matched_to_bioprojects"] = matched_count
        logger.info(f"  Matched {matched_count} entity-bioproject pairs")
        logger.info(f"  {len(entity_to_bioprojects)} entities have bioproject links")

        return entity_to_bioprojects

    def _load_sample_metadata(self, samples_dir: Path) -> Dict[str, Any]:
        """Load sample metadata from 168000-samples-paper."""
        metadata = {
            "samples_dir": str(samples_dir),
            "available_files": [],
            "bioprojects": {},
            "samples_count": 0
        }

        # Check what files are available
        for f in samples_dir.iterdir():
            if f.is_file():
                metadata["available_files"].append(f.name)

        # Try to load projects.csv
        projects_file = samples_dir / "projects.csv"
        if projects_file.exists():
            try:
                import pandas as pd
                df = pd.read_csv(projects_file)
                metadata["bioprojects"] = df.to_dict('records')
                metadata["bioprojects_count"] = len(df)
                logger.info(f"  Loaded {len(df)} bioprojects from projects.csv")
            except Exception as e:
                logger.warning(f"  Could not load projects.csv: {e}")

        # Try to load sample metadata
        sample_metadata_file = samples_dir / "sample_metadata.tsv"
        if sample_metadata_file.exists():
            try:
                import pandas as pd
                df = pd.read_csv(sample_metadata_file, sep='\t')
                metadata["samples_count"] = len(df)
                metadata["sample_columns"] = list(df.columns)
                logger.info(f"  Loaded {len(df)} samples from sample_metadata.tsv")
            except Exception as e:
                logger.warning(f"  Could not load sample_metadata.tsv: {e}")

        self.stats["available_metadata_files"] = len(metadata["available_files"])
        logger.info(f"  Found {len(metadata['available_files'])} metadata files")

        return metadata

    def _enrich_graph(self, graph: nx.MultiDiGraph,
                      entity_to_bioprojects: Dict[str, List[str]],
                      sample_metadata: Dict) -> nx.MultiDiGraph:
        """Enrich graph nodes with metadata."""
        # Add bioproject information to nodes
        bioproject_count = 0
        for node, data in graph.nodes(data=True):
            if node in entity_to_bioprojects:
                graph.nodes[node]["bioprojects"] = entity_to_bioprojects[node]
                graph.nodes[node]["bioproject_count"] = len(entity_to_bioprojects[node])
                bioproject_count += 1

        self.stats["nodes_with_bioprojects"] = bioproject_count

        # Add sample metadata summary
        if sample_metadata.get("samples_count"):
            graph.graph["sample_metadata"] = {
                "samples_dir": sample_metadata["samples_dir"],
                "total_samples": sample_metadata["samples_count"],
                "bioprojects_count": sample_metadata.get("bioprojects_count", 0)
            }

        logger.info(f"  Enriched {bioproject_count} nodes with bioproject links")
        return graph

    def _generate_metadata_stats(self, graph: nx.MultiDiGraph,
                                 entity_to_bioprojects: Dict[str, List[str]],
                                 sample_metadata: Dict) -> Dict:
        """Generate metadata integration statistics."""
        stats = {
            "timestamp": datetime.now().isoformat(),
            "graph_nodes": graph.number_of_nodes(),
            "graph_edges": graph.number_of_edges(),
            "nodes_with_bioprojects": sum(1 for _, d in graph.nodes(data=True)
                                         if d.get("bioproject_count", 0) > 0),
            "total_entity_bioproject_links": sum(len(v) for v in entity_to_bioprojects.values()),
            "unique_bioprojects_represented": len(set(bp for bps in entity_to_bioprojects.values()
                                                    for bp in bps)),
            "sample_metadata_available": sample_metadata.get("samples_count", 0) > 0,
        }

        # Top bioprojects by entity count
        bp_counts = defaultdict(int)
        for bps in entity_to_bioprojects.values():
            for bp in bps:
                bp_counts[bp] += 1

        stats["top_bioprojects"] = [
            {"bioproject_id": bp, "entity_count": count}
            for bp, count in sorted(bp_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        ]

        return stats

    def _export_metadata_graph(self, graph: nx.MultiDiGraph, stats: Dict):
        """Export metadata-enriched graph in multiple formats."""
        # JSON
        data = nx.node_link_data(graph)
        save_json(data, Config.OUTPUT_DIR / "cdm_kg_metadata_enriched.json", pretty=False)

        # GEXF for Gephi
        nx.write_gexf(graph, Config.OUTPUT_DIR / "cdm_kg_metadata_enriched.gexf")

        # GraphML for Cytoscape
        graph_ml = graph.copy()
        for node in graph_ml.nodes():
            for key, value in list(graph_ml.nodes[node].items()):
                if isinstance(value, (set, tuple, list)):
                    graph_ml.nodes[node][key] = list(value) if not isinstance(value, str) else value

        nx.write_graphml(graph_ml, Config.OUTPUT_DIR / "cdm_kg_metadata_enriched.graphml")

        logger.info("  Exported metadata-enriched graph files")


# ============================================================================
# MAIN PIPELINE
# ============================================================================

class CDMKnowledgeGraphPipeline:
    """Complete CDM Knowledge Graph Construction Pipeline."""

    def __init__(self, start_phase: int = 0, end_phase: int = 5):
        self.start_phase = start_phase
        self.end_phase = end_phase
        self.checkpoint_manager = CheckpointManager(checkpoint_interval=600)  # 10 minutes

    def run(self):
        """Run the complete pipeline."""
        logger.info("=" * 80)
        logger.info("CDM KNOWLEDGE GRAPH CONSTRUCTION PIPELINE")
        logger.info("=" * 80)
        logger.info(f"Start Phase: {self.start_phase}, End Phase: {self.end_phase}")
        logger.info("")

        ensure_directories()

        # Load or initialize data
        entities = None
        pairs = None
        relationships = None
        graph = None

        # Check for intermediate files
        repaired_file = Config.OUTPUT_DIR / "cdm_entities_repaired.json"
        pairs_file = Config.OUTPUT_DIR / "entity_pairs_v2.json"
        relationships_file = Config.OUTPUT_DIR / "kg_relationships_validated.json"

        if self.start_phase > 0 and repaired_file.exists():
            logger.info(f"Loading intermediate data from {repaired_file}")
            entities = load_entities(repaired_file)

        if self.start_phase > 1 and pairs_file.exists():
            logger.info(f"Loading intermediate data from {pairs_file}")
            pairs_data = load_json(pairs_file)
            # Reconstruct pairs from saved data
            entities = load_entities(repaired_file) if not entities else entities
            entity_dict = {e.term: e for e in entities}
            pairs = []
            for p_data in pairs_data:
                pair = EntityPair(
                    entity_a=entity_dict.get(p_data['entity_a']),
                    entity_b=entity_dict.get(p_data['entity_b']),
                    shared_papers=p_data.get('shared_papers', []),
                    priority_score=p_data.get('priority_score', 0.0),
                    type_pair_bonus=p_data.get('type_pair_bonus', 0.0),
                    cross_paper_bonus=p_data.get('cross_paper_bonus', 0.0),
                    umls_bonus=p_data.get('umls_bonus', 0.0),
                    preliminary_relationship=p_data.get('preliminary_relationship', ''),
                    preliminary_evidence=p_data.get('preliminary_evidence', ''),
                    preliminary_confidence=p_data.get('preliminary_confidence', 0.0)
                )
                if pair.entity_a and pair.entity_b:
                    pairs.append(pair)

        if self.start_phase > 2 and relationships_file.exists():
            logger.info(f"Loading intermediate data from {relationships_file}")
            rels_data = load_json(relationships_file)
            relationships = [Relationship(**r) for r in rels_data]

        # ====================================================================
        # PHASE 0: DATA REPAIR
        # ====================================================================
        if self.start_phase <= 0 <= self.end_phase:
            if entities is None:
                entities = load_entities(Config.INPUT_FILE)

            phase0 = Phase0DataRepair()
            entities = phase0.run(entities)

            # Save repaired entities
            repaired_data = {
                'total_entities': len(entities),
                'results': [e.to_dict() for e in entities]
            }
            save_json(repaired_data, Config.OUTPUT_DIR / "cdm_entities_repaired.json")

        # ====================================================================
        # PHASE 1: PAIR GENERATION
        # ====================================================================
        if self.start_phase <= 1 <= self.end_phase:
            if entities is None:
                entities = load_entities(repaired_file)

            phase1 = Phase1PairGeneration()
            pairs = phase1.run(entities)

            # Phase 2 extraction is properly batched (BATCH_SIZE_EXTRACTION pairs/call)
            # but still one call per batch - at full corpus scale, pair counts run into
            # the tens of thousands (55k+ pairs even at 100-paper scale), which would be
            # thousands of sequential LLM calls (many hours) to extract relationships for
            # long-tail pairs that barely co-occur. Cap to the top-N by priority_score
            # (already sorted descending by Phase 1) - this is a real, disclosed scope
            # limit, not a silent truncation: see run_log for the actual pair count kept.
            max_pairs = int(os.getenv("KG_MAX_PAIRS", "0")) or None
            if max_pairs and len(pairs) > max_pairs:
                logger.info(f"  KG_MAX_PAIRS={max_pairs}: keeping top {max_pairs} of {len(pairs)} "
                            f"pairs by priority_score (relationship extraction is O(pairs), "
                            f"this bounds it to a finishable scope)")
                pairs = pairs[:max_pairs]

            # Save pairs using to_dict method (includes preliminary relationships)
            pairs_data = [p.to_dict() for p in pairs]

            save_json(pairs_data, Config.OUTPUT_DIR / "entity_pairs_v2.json")

        # ====================================================================
        # PHASE 2: RELATIONSHIP EXTRACTION
        # ====================================================================
        if self.start_phase <= 2 <= self.end_phase:
            if pairs is None:
                logger.error("Phase 2 requires pairs from Phase 1")
                return

            phase2 = Phase2RelationshipExtraction()
            relationships = phase2.run(pairs)

            # Save relationships
            rels_data = [r.to_dict() for r in relationships]
            save_json(rels_data, Config.OUTPUT_DIR / "kg_relationships_validated.json")

        # ====================================================================
        # PHASE 3: GRAPH CONSTRUCTION
        # ====================================================================
        if self.start_phase <= 3 <= self.end_phase:
            if entities is None:
                entities = load_entities(repaired_file)
            if relationships is None:
                rels_data = load_json(relationships_file)
                relationships = [Relationship(**r) for r in rels_data]

            phase3 = Phase3GraphConstruction()
            graph = phase3.run(entities, relationships)

            # Export formats
            phase3.export_formats(graph)

        # ====================================================================
        # PHASE 4: VISUALIZATION
        # ====================================================================
        if self.start_phase <= 4 <= self.end_phase:
            if graph is None:
                # Load graph from JSON
                graph_data = load_json(Config.OUTPUT_DIR / "cdm_kg_enriched.json")
                graph = nx.node_link_graph(graph_data, directed=True, multigraph=True)

            phase4 = Phase4Visualization()
            phase4.run(graph)

        # ====================================================================
        # PHASE 5: METADATA INTEGRATION
        # ====================================================================
        if self.start_phase <= 5 <= self.end_phase:
            if graph is None:
                # Load graph from JSON
                graph_data = load_json(Config.OUTPUT_DIR / "cdm_kg_enriched.json")
                graph = nx.node_link_graph(graph_data, directed=True, multigraph=True)

            if entities is None:
                entities = load_entities(repaired_file)

            phase5 = Phase5MetadataIntegration(checkpoint_manager=self.checkpoint_manager)
            graph = phase5.run(graph, entities)

        # ====================================================================
        # COMPLETE
        # ====================================================================
        logger.info("")
        logger.info("=" * 80)
        logger.info("PIPELINE COMPLETE!")
        logger.info("=" * 80)
        logger.info("")
        logger.info("Output files:")
        logger.info(f"  - {Config.OUTPUT_DIR / 'cdm_entities_repaired.json'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'entity_pairs_v2.json'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'kg_relationships_validated.json'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'cdm_kg_enriched.json'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'cdm_kg_enriched.gexf'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'cdm_kg_enriched.graphml'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'kg_statistics.json'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'cdm_kg_interactive.html'}")
        logger.info(f"  - {Config.OUTPUT_DIR / 'cdm_kg_metadata_enriched.json'} (PHASE 5)")
        logger.info(f"  - {Config.OUTPUT_DIR / 'metadata_statistics.json'} (PHASE 5)")
        logger.info("")
        logger.info("Open cdm_kg_interactive.html in a browser to explore the knowledge graph!")


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="CDM Knowledge Graph Construction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run complete pipeline
  python kg_pipeline.py

  # Run only Phase 0 (data repair)
  python kg_pipeline.py --phase 0

  # Run from Phase 1 to Phase 3
  python kg_pipeline.py --start-phase 1 --end-phase 3

  # Run with custom input
  python kg_pipeline.py --input data/entities.json --output results
        """
    )

    parser.add_argument(
        '--start-phase', '-s',
        type=int,
        default=0,
        choices=[0, 1, 2, 3, 4, 5],
        help='Starting phase (default: 0)'
    )

    parser.add_argument(
        '--end-phase', '-e',
        type=int,
        default=5,
        choices=[0, 1, 2, 3, 4, 5],
        help='Ending phase (default: 5)'
    )

    parser.add_argument(
        '--input', '-i',
        type=Path,
        default=None,
        help='Input JSON file (default: outputs/normalized/cdm_entities_clean.json)'
    )

    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=None,
        help='Output directory (default: knowledge_graph)'
    )

    args = parser.parse_args()

    # Update config if provided
    if args.input:
        Config.INPUT_FILE = args.input
    if args.output:
        Config.OUTPUT_DIR = args.output

    # Validate phase range
    if args.start_phase > args.end_phase:
        parser.error("start-phase must be <= end-phase")

    # Run pipeline
    pipeline = CDMKnowledgeGraphPipeline(
        start_phase=args.start_phase,
        end_phase=args.end_phase
    )

    try:
        pipeline.run()
    except KeyboardInterrupt:
        logger.info("\nPipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
