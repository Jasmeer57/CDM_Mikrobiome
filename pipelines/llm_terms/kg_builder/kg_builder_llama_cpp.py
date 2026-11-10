#!/usr/bin/env python3
"""
Microbiome CDM Knowledge Graph Builder - llama_cpp version
Uses llama_cpp server with Phi model instead of Ollama

Dependencies:
  pip install llama-cpp-python sentence-transformers numpy scikit-learn huggingface_hub
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time

import os
import re
import json
import time
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import urllib.request
import urllib.error
import urllib.parse
import csv
import traceback

import numpy as np
import networkx as nx

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
MODEL_NAME        = "phi-4"           # llama_cpp model name
TOP_K_CANDIDATES  = 15              # Top-k semantic neighbours per entity
BATCH_SIZE        = 20               # Reduced from 40 - fewer candidates per prompt
MAX_RELATIONS_PER_TERM = 15
MIN_CONFIDENCE    = 0.65             # Raised to match prompt rule threshold
MIN_COOC_SCORE    = 0.0             # Minimum co-occurrence to accept relation
CHECKPOINT_FILE   = "kg_checkpoint.json"
OUTPUT_DIR        = "new_output"
LLM_TEMPERATURE   = 0.1
LLM_MAX_TOKENS    = 4096
PAPERS_DIR        = str(_CDM_ROOT / "data/papers_txt")

# ──────────────────────────────────────────────
# Negated edges audit (FEATURE 1)
# ──────────────────────────────────────────────
_NEGATED_EDGES: List[Dict] = []
_NEGATED_EDGES_LOCK = threading.Lock()

# ──────────────────────────────────────────────
# Known entity type corrections (fix misclassifications)
# ──────────────────────────────────────────────
KNOWN_ENTITY_TYPES: Dict[str, str] = {
    "bss": "clinical_assessment_tool",
    "bristol stool scale": "clinical_assessment_tool",
    "bristol stool scale score": "clinical_assessment_tool",
    "national institutes of biomedical innovation": "institution",
    "nibiohn": "institution",
    "morinaga": "institution",
    "osaka university": "institution",
    "keio university": "institution",
    "tokyo university": "institution",
    "japanese cohort": "cohort_type",
    "nibiohn cohort": "cohort_type",
    "ibe cohort": "cohort_type",
}


# ──────────────────────────────────────────────
# FEATURE 2: Entity normalization (NCBI Taxonomy + ChEBI)
# ──────────────────────────────────────────────
_NORM_CACHE: Dict[str, Dict] = {}
_NORM_CACHE_LOCK = threading.Lock()

def normalize_organism(name: str) -> Dict[str, Optional[str]]:
    key = f"taxon:{name.lower()}"
    with _NORM_CACHE_LOCK:
        if key in _NORM_CACHE:
            return _NORM_CACHE[key]
    result: Dict[str, Optional[str]] = {
        "taxon_id": None, "canonical_name": None, "rank": None
    }
    try:
        url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=taxonomy&term={urllib.parse.quote(name)}&retmode=json"
        )
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if ids:
            furl = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                f"?db=taxonomy&id={ids[0]}&retmode=json"
            )
            with urllib.request.urlopen(furl, timeout=5) as r:
                fdata = json.loads(r.read())
            doc = fdata.get("result", {}).get(ids[0], {})
            result = {
                "taxon_id": ids[0],
                "canonical_name": doc.get("scientificname"),
                "rank": doc.get("rank"),
            }
        time.sleep(0.34)
    except Exception as exc:
        logging.debug(f"NCBI lookup failed for '{name}': {exc}")
    with _NORM_CACHE_LOCK:
        _NORM_CACHE[key] = result
    return result

def normalize_metabolite(name: str) -> Dict[str, Optional[str]]:
    key = f"chebi:{name.lower()}"
    with _NORM_CACHE_LOCK:
        if key in _NORM_CACHE:
            return _NORM_CACHE[key]
    result: Dict[str, Optional[str]] = {
        "chebi_id": None, "canonical_name": None
    }
    try:
        url = (
            "https://www.ebi.ac.uk/webservices/chebi/2.0/test/"
            f"getLiteEntity?search={urllib.parse.quote(name)}"
            "&searchCategory=ALL&maximumResults=1&stars=ALL"
        )
        with urllib.request.urlopen(url, timeout=5) as r:
            raw = r.read().decode("utf-8")
        chebi_id = re.search(r'<chebiId>(CHEBI:\d+)</chebiId>', raw)
        chebi_name = re.search(
            r'<chebiAsciiName>([^<]+)</chebiAsciiName>', raw
        )
        if chebi_id:
            result = {
                "chebi_id": chebi_id.group(1),
                "canonical_name": (
                    chebi_name.group(1) if chebi_name else None
                ),
            }
    except Exception as exc:
        logging.debug(f"ChEBI lookup failed for '{name}': {exc}")
    with _NORM_CACHE_LOCK:
        _NORM_CACHE[key] = result
    return result

def normalize_entity(name: str, etype: str) -> Dict[str, Optional[str]]:
    if etype == "organism":
        return normalize_organism(name)
    elif etype == "metabolite":
        return normalize_metabolite(name)
    return {}

def save_normalization_cache(output_dir: str) -> None:
    cache_path = os.path.join(output_dir, "normalization_cache.json")
    with _NORM_CACHE_LOCK:
        cache_copy = dict(_NORM_CACHE)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_copy, f, indent=2)
    logging.info(f"Normalization cache saved: {len(cache_copy)} entries")

def load_normalization_cache(output_dir: str) -> None:
    global _NORM_CACHE
    cache_path = os.path.join(output_dir, "normalization_cache.json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            loaded = json.load(f)
        with _NORM_CACHE_LOCK:
            _NORM_CACHE.update(loaded)
        logging.info(f"Loaded normalization cache: {len(loaded)} entries")


# ──────────────────────────────────────────────
# Context hints for disambiguation
# ──────────────────────────────────────────────
CONTEXT_HINTS: Dict[str, str] = {
    "bss": "BSS = Bristol Stool Scale (1-7 stool form types), NOT Barrett's Segment Score",
    "bristol stool scale": "Bristol Stool Scale is a medical classification of stool form types 1-7",
    "bss scores": "BSS = Bristol Stool Scale scores (1-7), clinical tool for bowel habit assessment",
    "japanese": "Japanese population context - gut microbiome studies in Japan",
    "nibiohn": "NIBIOHN = National Institutes of Biomedical Innovation, Health and Nutrition (Japan)",
    "nibiohn cohort": "NIBIOHN cohort = Japanese gut microbiome cohort study (NIBIOHN)",
}

# ──────────────────────────────────────────────
# Trivial patterns to filter (definitionally true, no scientific value)
# ──────────────────────────────────────────────
TRIVIAL_PATTERNS: Set[Tuple[str, str, str]] = {
    # Common trivial mappings
    ("stool", "feces", "is_a"),
    ("feces", "stool", "is_a"),
    ("bowel", "intestine", "is_a"),
    ("bowel", "gastrointestinal tract", "part_of"),
    ("gut", "gastrointestinal tract", "part_of"),
    ("japan", "asia", "part_of"),
    ("japan", "japan", "part_of"),
    ("gut microbiome", "gut", "part_of"),
    ("gut microbiota", "gut", "part_of"),
    ("microbiome", "microbiota", "is_a"),
    ("bacteria", "microorganism", "is_a"),
    ("16s rrna", "sequencing", "is_a"),
    ("diversity", "alpha diversity", "is_a"),
    ("16s rrna sequencing", "metagenomics", "part_of"),
}

# ──────────────────────────────────────────────
# Relation types, by entity-type pair
# ──────────────────────────────────────────────
GENERIC_RELATIONS = [
    "part_of", "derived_from",
]

TYPED_RELATIONS: Dict[Tuple[str, str], List[str]] = {
    ("organism",   "metabolite"):   ["produces", "consumes", "converts_to"],
    ("organism",   "gene"):         ["encodes", "regulates", "upregulates", "downregulates"],
    ("organism",   "organism"):     ["inhibits_growth_of", "promotes_growth_of", "competes_with"],
    ("organism",   "disease"):      ["causes", "ameliorates", "risk_factor_for", "protects_against"],
    ("gene",       "metabolite"):   ["encodes", "produces", "converts_to"],
    ("gene",       "gene"):         ["activates", "inhibits", "co-expressed_with"],
    ("metabolite", "disease"):      ["causes", "protects_against", "biomarker_for"],
    ("metabolite", "organism"):     ["inhibits", "derived_from"],
    ("disease",    "organism"):     ["co-occurs_with", "risk_factor_for", "biomarker_for"],
    ("pathway",    "gene"):         ["part_of", "regulates"],
    ("pathway",    "metabolite"):   ["part_of", "converts_to"],
}

SYSTEM_PROMPT = """\
You are a biomedical knowledge graph extraction specialist with deep \
expertise in gut microbiome research, microbial ecology, and clinical \
metagenomics.

Your primary directive: ACCURACY over COVERAGE.
It is better to extract 3 correct edges than 10 uncertain ones.

Core principles:
1. GROUNDING: Every edge must be traceable to specific text in \
   the provided context. If you cannot quote the evidence, \
   the edge does not exist.

2. MECHANISM over ASSOCIATION: Prefer mechanistic relations \
   (produces, inhibits, activates) over vague associations. \
   "associated_with" is NEVER acceptable — always determine \
   the actual direction and mechanism.

3. DIRECTION MATTERS:
   "Lactobacillus produces lactate" ≠ "lactate produces Lactobacillus"
   Always verify which entity is the agent and which is the target.

4. CONFIDENCE CALIBRATION:
   - Your confidence MUST reflect the strength of textual evidence
   - 0.9+ = verbatim explicit statement with data
   - 0.7–0.89 = experimental result without explicit statement
   - Below 0.65 = do not return this edge

5. SCOPE: You are working on microbiome research. Reject any \
   relation that is generic biology not specific to microbiome \
   context (e.g., "stool is_a feces" = trivially true, worthless).

When in doubt: return an empty array. False negatives are \
acceptable. False positives destroy the graph.

6. NEGATION (NON-NEGOTIABLE):
   Before extracting ANY edge, scan the evidence for negation signals:
   "did not", "was not", "were not", "failed to", "no significant",
   "not detected", "absent", "lacked", "could not confirm", "no effect",
   "no change", "not associated", "neither...nor"
   If ANY negation signal modifies the proposed relation → set
   "negated": true and DO NOT extract it as a positive edge.
   Example: "Bacteroides did not significantly produce butyrate"
   → MUST NOT become Bacteroides --[produces]--> butyrate

7. TAXONOMIC SPECIFICITY:
   Claims are species- and strain-specific. NEVER generalize:
   ❌ "Lactobacillus produces lactic acid" (genus-level — too broad)
   ✅ "Lactobacillus rhamnosus GG produces lactic acid" (strain-specific)
   If the evidence mentions a strain (GG, DSM 12246, ATCC 53103 etc.),
   the source entity MUST include the strain designation.
   If only genus is mentioned, set "strain_level": false and cap
   confidence at 0.75.
"""


def get_context_hint(term: str) -> str:
    """Get context hint for a term if available."""
    term_lower = term.lower()
    for key, hint in CONTEXT_HINTS.items():
        if key in term_lower or term_lower in key:
            return f"\nIMPORTANT CONTEXT: {hint}"
    return ""


USER_PROMPT_TEMPLATE = """\
You are a strict biomedical relation extractor. Your ONLY job is to \
find relations that are EXPLICITLY stated in the GROUNDING CONTEXT below. \
Do NOT use prior knowledge. Do NOT infer. Do NOT speculate.

══════════════════════════════════════════════
GROUNDING CONTEXT (the ONLY valid source of evidence):
══════════════════════════════════════════════
{RETRIEVED_CONTEXT}

══════════════════════════════════════════════
EXTRACTION TASK
══════════════════════════════════════════════
Focus term : {TERM}  (entity type: {ETYPE})
{CONTEXT_HINT}

Candidates (find relations FROM focus term TO these only):
{TERM_LIST}

Allowed relation types: [{RELATION_TYPES}]

══════════════════════════════════════════════
STRICT RULES — violating ANY rule = rejection:
══════════════════════════════════════════════
1. The "evidence" field MUST be a verbatim or near-verbatim quote \
from the GROUNDING CONTEXT above. If you cannot find one, skip \
this pair entirely.
2. source MUST always be exactly: {TERM}
3. confidence ≥ 0.85 only if the relation is EXPLICITLY stated \
(e.g. "X produces Y", "X inhibits Y")
4. confidence 0.65–0.84 if the relation is strongly implied with \
direct numeric/experimental data
5. confidence < 0.65 → do NOT include the edge at all
6. If a candidate term does not appear in the GROUNDING CONTEXT \
→ skip it entirely
7. Never use "associated_with" — if you cannot determine the \
mechanism, skip the pair
8. The "evidence" string must contain at least one of the candidate \
target terms, verbatim

9. CAUSATION vs CORRELATION:
   - "associated with", "correlated with", "elevated in patients with"
     → CORRELATIVE only. Set "causal_or_correlative": "correlative"
     → Confidence MUST NOT exceed 0.75
     → Only allowed relation types: ["co-occurs_with", "biomarker_for",
       "risk_factor_for"]
   - "produces", "inhibits", "activates", "administration of X led to Y"
     → CAUSAL. Set "causal_or_correlative": "causal"
     → Confidence allowed 0.85–1.0
   - NEVER use causal relation_types ("produces", "inhibits", "activates",
     "causes") for correlative findings.

10. CONDITIONALITY:
     Many microbiome relations only hold under specific conditions.
     Examples:
       "Akkermansia muciniphila increases only during caloric restriction"
       → "conditionality": "caloric restriction required"
       "Clostridium produces butyrate under anaerobic conditions"
       → "conditionality": "anaerobic conditions required"
     If NO condition is mentioned → "conditionality": null
     If the relation IS conditional but conditionality is not captured
     → confidence must be ≤ 0.70

══════════════════════════════════════════════
OUTPUT FORMAT
══════════════════════════════════════════════
Return ONLY a raw JSON array. No markdown, no prose, no explanation.
Each object:
{{
  "source":        "{TERM}",
  "target":        <exact string from candidate list>,
  "relation_type": <one of the allowed relation types>,
  "direction":     "source_to_target" | "target_to_source" | "undirected",
  "confidence":    <float 0.65–1.0>,
  "evidence":      "<verbatim or near-verbatim quote from GROUNDING CONTEXT>",
  "evidence_location": "<section name where quote was found, e.g. 'Methods', 'Results'>",
  "entity_types":  {{"source": "{ETYPE}", "target": <target entity type>}},
  "study_context":          "in_vitro | in_vivo_animal | in_vivo_human | clinical_trial | meta_analysis | review | computational",
  "species_specificity":    "human | mouse | rat | pig | in_vitro | unspecified",
  "strain_level":           true | false,
  "causal_or_correlative":  "causal | correlative | mechanistic | unclear",
  "negated":                false,
  "conditionality":         "<condition string or null>",
  "statistical_support": {{
    "p_value_mentioned":    true | false,
    "effect_size_mentioned": true | false,
    "sample_size":          "<e.g. n=120 or null>"
  }},
  "evidence_section":       "Abstract | Introduction | Methods | Results | Discussion",
  "replicated":             "yes | no | unknown"
}}

If no valid relations found → return exactly: []
"""


# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        handlers=[
            logging.FileHandler("kg_build.log"),
            logging.StreamHandler(),
        ],
    )


# ──────────────────────────────────────────────
# Entity loading
# ──────────────────────────────────────────────
def load_entities(jsonl_path: str) -> List[Dict]:
    """Load and deduplicate entities."""
    entities_raw = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entities_raw.append(json.loads(line))

    from collections import Counter as _Counter

    name_types: Dict[str, _Counter] = defaultdict(_Counter)
    name_docs:  Dict[str, Set[str]] = defaultdict(set)
    name_canonical: Dict[str, str] = {}

    for ent in entities_raw:
        name  = ent.get("entity", "").strip()
        etype = ent.get("entity_type", "unknown").strip().lower()
        if not name or len(name) <= 1:
            continue
        key = name.lower()
        if key not in name_canonical:
            name_canonical[key] = name   # preserve original casing first seen
        # Override with KNOWN_ENTITY_TYPES if available
        corrected = KNOWN_ENTITY_TYPES.get(key, etype)
        name_types[key][corrected] += 1
        doc = (ent.get("source_paper") or ent.get("source_doc")
               or ent.get("doc_id") or ent.get("pmid"))
        if doc:
            name_docs[key].add(str(doc))

    result = []
    for key, type_counter in name_types.items():
        best_type = type_counter.most_common(1)[0][0]
        result.append({
            "entity": name_canonical[key],
            "entity_type": best_type,
            "source_docs": sorted(name_docs[key]),
        })

    logging.info(f"Loaded {len(result)} unique entities from {jsonl_path}")
    return result


# ──────────────────────────────────────────────
# FEATURE 1: Paper metadata loader
# ──────────────────────────────────────────────
def load_paper_metadata(papers_dir: str) -> Dict[str, Dict]:
    """
    Load PMID, year, DOI for each paper.
    Falls back to parsing PMID from filename if no metadata file.
    """
    meta_path = os.path.join(papers_dir, "papers_metadata.json")
    metadata: Dict[str, Dict] = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            metadata = json.load(f)
        logging.info(f"Loaded paper metadata for {len(metadata)} papers")
        return metadata
    logging.warning(
        "papers_metadata.json not found — extracting PMID from filenames"
    )
    pmid_re = re.compile(r'(\d{7,9})')
    for fname in os.listdir(papers_dir):
        m = pmid_re.search(fname)
        metadata[fname] = {
            "pmid": m.group(1) if m else None,
            "year": None,
            "doi": None,
        }
    return metadata


# ──────────────────────────────────────────────
# Semantic candidate selection using sentence-transformers (CPU)
# ──────────────────────────────────────────────
def build_embeddings(terms: List[str]) -> np.ndarray:
    """Embed all terms via sentence-transformers. Returns (N, D) float32 array."""
    from sentence_transformers import SentenceTransformer
    logging.info(f"Computing embeddings with sentence-transformers for {len(terms)} terms...")

    # Use a fast, high-quality embedding model - force CPU to avoid CUDA issues
    model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")

    # Batch encode for efficiency
    embeddings = model.encode(terms, batch_size=128, show_progress_bar=True, normalize_embeddings=True)

    result = np.array(embeddings, dtype=np.float32)
    logging.info(f"Embeddings ready: {result.shape}")
    return result


def top_k_neighbours(
    focal_idx: int,
    embeddings: np.ndarray,
    k: int,
    exclude_indices: Optional[set] = None,
) -> List[int]:
    """Return indices of top-k nearest neighbours by cosine sim."""
    q = embeddings[focal_idx]
    sims = embeddings @ q
    sims[focal_idx] = -1.0
    if exclude_indices:
        for idx in exclude_indices:
            sims[idx] = -1.0
    top_idx = np.argpartition(sims, -k)[-k:]
    top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]
    return top_idx.tolist()


# ──────────────────────────────────────────────
# Sentence-level text indexing for grounding
# ──────────────────────────────────────────────
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Global sentence index and cache key (set by build_sentence_index)
_SENTENCE_INDEX: Dict[str, List[Tuple[str, str]]] = {}
_SENTENCE_INDEX_KEY: int = 0


def split_sentences(text: str) -> List[str]:
    """Split text into sentences, filtering short fragments."""
    sentences = SENTENCE_SPLIT_RE.split(text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def build_sentence_index(entities: List[Dict], papers_dir: str) -> Dict[str, List[Tuple[str, str]]]:
    """
    Build a sentence-level index mapping terms to (doc_id, sentence) tuples.
    O(sentences) using inverted index — iterates sentences once, not entities.
    Sets _SENTENCE_INDEX and _SENTENCE_INDEX_KEY for caching.
    """
    global _SENTENCE_INDEX, _SENTENCE_INDEX_KEY

    # Step 1: Build term lookup structures
    single_terms: Dict[str, List[str]] = defaultdict(list)
    multi_terms: List[str] = []

    for ent in entities:
        name = ent["entity"].lower()
        words = name.split()
        if len(words) == 1:
            single_terms[name].append(name)
        else:
            multi_terms.append(name)

    multi_terms.sort(key=len, reverse=True)

    # Collect referenced paper names
    referenced_papers: Set[str] = set()
    for ent in entities:
        for doc in ent.get("source_docs", []):
            referenced_papers.add(doc)

    logging.info(f"Building sentence index for {len(referenced_papers)} papers...")

    sentence_index: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    processed = 0

    for doc_id in referenced_papers:
        paper_path = os.path.join(papers_dir, doc_id)
        if not os.path.exists(paper_path):
            continue
        try:
            with open(paper_path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue

        sentences = split_sentences(text)
        for sentence in sentences:
            sent_lower = sentence.lower()

            # Fast single-word matching via set intersection
            words_in_sent = set(re.findall(r'[a-z0-9]+', sent_lower))
            for term in words_in_sent & set(single_terms.keys()):
                for canonical in single_terms[term]:
                    sentence_index[canonical].append((doc_id, sentence))

            # Multi-word terms via substring (fewer, still fast)
            for term in multi_terms:
                if term in sent_lower:
                    sentence_index[term].append((doc_id, sentence))

        processed += 1
        if processed % 50 == 0:
            logging.info(f"  Indexed {processed}/{len(referenced_papers)} papers...")

    # Deduplicate and sort
    for term in list(sentence_index.keys()):
        seen: Set[Tuple[str, str]] = set()
        unique: List[Tuple[str, str]] = []
        for item in sentence_index[term]:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        sentence_index[term] = sorted(unique, key=lambda x: (x[0], x[1]))

    logging.info(f"Sentence index built: {len(sentence_index)} terms indexed")
    total_sentences = sum(len(v) for v in sentence_index.values())
    logging.info(f"Total sentence entries: {total_sentences}")

    _SENTENCE_INDEX = dict(sentence_index)
    _SENTENCE_INDEX_KEY = hash(tuple(sorted(_SENTENCE_INDEX.keys())))
    retrieve_sentences_cached.cache_clear()

    return _SENTENCE_INDEX


def term_in_sentence(term: str, sentence_lower: str) -> bool:
    """Check if term appears in sentence (case-insensitive, word-boundary aware)."""
    # Simple substring match for multi-word terms
    # For single words, check word boundaries
    term_lower = term.lower()
    if " " in term_lower:
        # Multi-word: direct substring
        return term_lower in sentence_lower
    else:
        # Single word: check it's surrounded by non-alphanumeric
        pattern = r'\b' + re.escape(term_lower) + r'\b'
        return bool(re.search(pattern, sentence_lower))


@lru_cache(maxsize=100_000)
def retrieve_sentences_cached(
    term_a: str,
    term_b: str,
    index_key: int,
    max_sentences: int = 5,
) -> Tuple[str, ...]:
    """
    Cached sentence retrieval using global _SENTENCE_INDEX.
    Returns tuple (hashable) for lru_cache compatibility.
    """
    if index_key != _SENTENCE_INDEX_KEY:
        # Index was rebuilt — return empty
        return ()

    term_a_lower = term_a.lower()
    term_b_lower = term_b.lower()

    sentences_a = _SENTENCE_INDEX.get(term_a_lower, [])
    sentences_b = _SENTENCE_INDEX.get(term_b_lower, [])

    if not sentences_a or not sentences_b:
        return ()

    b_set = {(doc, sent) for doc, sent in sentences_b}

    matching = []
    for doc, sent in sentences_a:
        if (doc, sent) in b_set:
            matching.append(sent)
        else:
            sent_lower = sent.lower()
            if term_b_lower in sent_lower or term_in_sentence(term_b_lower, sent_lower):
                matching.append(sent)

    seen = set()
    unique = []
    for s in matching:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return tuple(unique[:max_sentences])


def retrieve_sentences(
    term_a: str,
    term_b: str,
    sentence_index: Dict[str, List[Tuple[str, str]]],
    max_sentences: int = 5,
) -> List[str]:
    """
    Uncached wrapper for backward compatibility.
    Prefer retrieve_sentences_cached in hot paths.
    """
    return list(retrieve_sentences_cached(term_a, term_b, _SENTENCE_INDEX_KEY, max_sentences))


# ──────────────────────────────────────────────
# LLM call via llama_cpp server
# ──────────────────────────────────────────────
def call_llama_cpp(prompt: str, base_url: str, retries: int = 3) -> str:
    """Call llama_cpp server for chat completion."""
    # Truncate prompt to leave room for KV cache and response
    if len(prompt) > 24000:
        prompt = prompt[:24000] + "\n\n[PROMPT TRUNCATED]"
        logging.warning("Prompt truncated to ~6000 tokens")
    for attempt in range(retries):
        try:
            data = {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
            }

            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )

            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()

        except Exception as exc:
            logging.warning(f"llama_cpp attempt {attempt+1} failed: {exc}")
            time.sleep(2 ** attempt)
    return "[]"


def parse_json_response(text: str) -> List[Dict]:
    """Robustly extract a JSON array from LLM output."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    text = re.sub(r'^.*?(\{|\[)', r'\1', text, flags=re.DOTALL).strip()

    # Phi-4 often returns bare objects instead of array — auto-wrap
    stripped = text.strip()
    if stripped.startswith('{'):
        text = '[' + re.sub(r'\}\s*\n\s*\{', '},{', stripped) + ']'

    # Try full JSON first
    try:
        data = json.loads(text)
        logging.debug(f"parse_json_response: Loaded {type(data)}")
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        elif isinstance(data, dict):
            return [data]
        return []
    except json.JSONDecodeError as e:
        err_str = str(e)
        # "Extra data" = LLM returned multiple JSON objects without array wrapper
        if "Extra data" in err_str:
            # Find all {...} blocks and try to parse each
            objects = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
            results = []
            for obj in objects[:10]:
                try:
                    parsed = json.loads(obj)
                    if isinstance(parsed, dict):
                        results.append(parsed)
                except Exception:
                    pass
            if results:
                logging.debug(f"parse_json_response: Parsed {len(results)} dicts from Extra data fallback")
                return results

        # Generic fallback: extract all {...} shaped objects
        logging.warning(f"JSON decode failed: {err_str}")
    objects = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    results = []
    for obj in objects[:10]:
        try:
            parsed = json.loads(obj)
            if isinstance(parsed, dict):
                results.append(parsed)
        except Exception:
            pass
    logging.debug(f"parse_json_response: Parsed {len(results)} dicts from generic fallback")
    return results


def extract_single_json_object(text: str) -> dict:
    """Robustly extract a single JSON object from LLM output, stripping markdown."""
    text = re.sub(r"```", "", text).strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def reject_vague_relations(edges: List[Dict]) -> List[Dict]:
    """Hard filter: reject 'associated_with' — too vague, always hallucinated."""
    return [e for e in edges if e.get("relation_type") != "associated_with"]


def evidence_matches_context(
    evidence: str,
    context_sentences: List[str],
    min_overlap: float = 0.4,
) -> bool:
    """Check that evidence words appear in the retrieved context."""
    if not context_sentences:
        return False
    evidence_words = set(evidence.lower().split())
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "of", "in",
        "and", "or", "to", "for", "with", "that", "this", "it",
        "by", "from", "on", "at", "as", "be", "been", "has", "have",
    }
    evidence_words -= stopwords
    if not evidence_words:
        return False
    combined_context = " ".join(context_sentences).lower()
    matches = sum(1 for w in evidence_words if w in combined_context)
    return (matches / len(evidence_words)) >= min_overlap


VERIFIER_PROMPT = """\
You are a strict scientific fact-checker for biomedical knowledge graphs.

══════════════════════════════════════════════
SOURCE TEXT:
══════════════════════════════════════════════
{CONTEXT}

══════════════════════════════════════════════
PROPOSED KNOWLEDGE GRAPH EDGE:
══════════════════════════════════════════════
  Source entity : {SOURCE}  ({SOURCE_TYPE})
  Relation      : {RELATION_TYPE}
  Target entity : {TARGET}  ({TARGET_TYPE})
  Direction     : {DIRECTION}
  Claimed evidence: "{EVIDENCE}"

══════════════════════════════════════════════
YOUR TASK:
══════════════════════════════════════════════
Answer these 4 questions about the proposed edge:

Q1. Does the claimed evidence sentence appear verbatim or near-verbatim \
    in the SOURCE TEXT above? (yes/no)
Q2. Does the SOURCE TEXT explicitly support the relation type \
    "{RELATION_TYPE}" between these two entities? (yes/no/partial)
Q3. Is this a directional fact (source acts on target) or \
    bidirectional? (source_to_target / target_to_source / undirected)
Q4. On a scale 0.0–1.0, how confident are you this edge is \
    scientifically valid based ONLY on the SOURCE TEXT?
    (0.9–1.0 = explicitly stated with data
     0.7–0.89 = strongly implied with experimental evidence
     0.5–0.69 = mentioned but without mechanistic detail
     <0.5 = inferred or speculative — reject this edge)

Q5. Is this finding described as replicated or consistent across studies?
    Look for: "consistent with", "confirmed by", "previously shown",
    "multiple studies", "well established", "replicates findings of"
    Answer: yes / no / unknown

Q6. Is this finding described as novel, preliminary, or needing validation?
    Look for: "to our knowledge", "first report", "preliminary",
    "warrants further study", "needs validation", "small sample"
    If yes → apply -0.15 confidence penalty.

Return ONLY this JSON:
{{
  "evidence_found_in_text": true | false,
  "relation_supported": "yes" | "partial" | "no",
  "corrected_direction": "source_to_target" | "target_to_source" | "undirected",
  "verified_confidence": <float 0.0–1.0>,
  "rejection_reason": "<if rejecting, brief reason; else null>",
  "replicated": "yes" | "no" | "unknown",
  "novelty_penalty_applied": true | false
}}
"""


def verify_edge(
    edge: Dict,
    context_sentences: List[str],
    base_url: str,
) -> Tuple[bool, float]:
    """
    Ask the LLM: is this relation explicitly supported by the provided context?
    Returns (is_valid, adjusted_confidence).
    """
    if not context_sentences:
        return False, 0.0

    context_text = "\n".join(context_sentences)
    prompt = VERIFIER_PROMPT.format(
        CONTEXT=context_text,
        SOURCE=edge.get("source", ""),
        SOURCE_TYPE=edge.get("entity_types", {}).get("source", "unknown"),
        RELATION_TYPE=edge.get("relation_type", ""),
        TARGET=edge.get("target", ""),
        TARGET_TYPE=edge.get("entity_types", {}).get("target", "unknown"),
        DIRECTION=edge.get("direction", "undirected"),
        EVIDENCE=edge.get("evidence", ""),
    )
    response = call_llama_cpp(prompt, base_url)
    try:
        data = extract_single_json_object(response)
        evidence_found = bool(data.get("evidence_found_in_text", False))
        rel_supported = data.get("relation_supported", "no")
        verified_conf = float(data.get("verified_confidence", 0.0))
        rejection = data.get("rejection_reason")

        # Reject if evidence not in text, relation not supported, or confidence < 0.5
        if not evidence_found or rel_supported == "no" or verified_conf < 0.5:
            return False, 0.0
        return True, verified_conf
    except Exception:
        return False, 0.0


CONTRADICTION_PROMPT = """\
You are checking whether a proposed biomedical relation is \
contradicted, disputed, or negated in the scientific literature.

══════════════════════════════════════════════
CONTEXT TEXT:
══════════════════════════════════════════════
{CONTEXT}

══════════════════════════════════════════════
PROPOSED RELATION:
══════════════════════════════════════════════
  {SOURCE} --[{RELATION_TYPE}]--> {TARGET}

══════════════════════════════════════════════
TASK:
══════════════════════════════════════════════
Scan the CONTEXT TEXT for any of these signals:

NEGATION signals:
- "did not", "was not", "were not", "no significant", "failed to",
  "contrary to", "in contrast", "unexpectedly", "no evidence of",
  "not detected", "absence of", "lacked", "neither...nor"

DISPUTE signals:
- "controversial", "disputed", "inconsistent with", "conflicting",
  "not replicated", "could not confirm", "debated"

LIMITATION signals:
- "correlation only", "causation not established", "requires validation",
  "preliminary", "small sample"

If ANY of these apply to the proposed relation:
- set "contradicted" to true
- quote the contradicting text exactly

Return ONLY this JSON:
{{
  "contradicted": true | false,
  "disputed": true | false,
  "is_correlation_only": true | false,
  "contradicting_quote": "<exact quote if contradicted, else null>",
  "confidence_penalty": <float 0.0–0.5 penalty to subtract from confidence>
}}
"""


def check_contradiction(
    edge: Dict,
    context_sentences: List[str],
    base_url: str,
) -> float:
    """
    Check if proposed relation is contradicted by the context.
    Returns confidence penalty (0.0–0.5) to subtract.
    """
    if not context_sentences:
        return 0.0

    context_text = "\n".join(context_sentences)
    prompt = CONTRADICTION_PROMPT.format(
        CONTEXT=context_text,
        SOURCE=edge.get("source", ""),
        RELATION_TYPE=edge.get("relation_type", ""),
        TARGET=edge.get("target", ""),
    )
    response = call_llama_cpp(prompt, base_url)
    try:
        data = extract_single_json_object(response)
        if data.get("contradicted") or data.get("disputed") or data.get("is_correlation_only"):
            return float(data.get("confidence_penalty", 0.3))
        return 0.0
    except Exception:
        return 0.0


def batch_verify_edges(
    edge_contexts: List[Tuple[Dict, List[str]]],
    base_url: str,
) -> List[Tuple[Dict, List[str], float]]:
    """
    Combined verification + contradiction check for multiple edges.
    Takes pre-paired (edge, context_sentences) tuples to avoid dict lookups.

    Returns list of (edge_copy, context_sentences, contra_penalty) tuples
    for edges that pass verification. Skips failed edges silently.
    """
    results = []
    for edge, context_for_pair in edge_contexts:
        if not context_for_pair:
            continue

        context_text = "\n".join(context_for_pair)
        combined_prompt = f"""\
CONTEXT TEXT:
{context_text}

PROPOSED RELATION:
{edge['source']} --[{edge['relation_type']}]--> {edge['target']}
Evidence claimed: "{edge.get('evidence', '')}"

Q5: Is this finding replicated across studies?
(yes/no/unknown — look for 'consistent with', 'previously shown',
'multiple studies', 'well established')
Q6: Is this finding novel or preliminary?
(set novelty_penalty_applied: true if 'to our knowledge',
'first report', 'preliminary', 'warrants further study' detected)

Answer JSON only:
{{
  "evidence_found_in_text": true | false,
  "relation_supported": "yes" | "partial" | "no",
  "verified_confidence": <float 0.0–1.0>,
  "contradicted": true | false,
  "disputed": true | false,
  "is_correlation_only": true | false,
  "confidence_penalty": <float 0.0–0.5>,
  "replicated": "yes" | "no" | "unknown",
  "novelty_penalty_applied": true | false
}}
"""
        response = call_llama_cpp(combined_prompt, base_url)
        try:
            data = extract_single_json_object(response)
            evidence_found = bool(data.get("evidence_found_in_text", False))
            rel_supported = data.get("relation_supported", "no")
            verified_conf = float(data.get("verified_confidence", 0.0))
            contra_penalty = float(data.get("confidence_penalty", 0.0))
            if data.get("novelty_penalty_applied"):
                verified_conf = max(0.0, verified_conf - 0.15)
            edge_copy = dict(edge)
            edge_copy["replicated"] = data.get("replicated", "unknown")

            if not evidence_found or rel_supported == "no" or verified_conf < 0.5:
                continue

            edge_copy["confidence"] = round((float(edge_copy.get("confidence", 0.7)) + verified_conf) / 2, 4)
            edge_copy["evidence_found_in_text"] = evidence_found

            results.append((edge_copy, context_for_pair, contra_penalty))
        except Exception as exc:
            logging.debug(f"batch_verify_edges: edge parse failed: {exc}")
            continue

    return results


ENTITY_DISAMBIGUATION_PROMPT = """\
You are a biomedical entity classifier for microbiome research.

Classify the entity type of the following term in the context \
of gut microbiome research:

Term: "{TERM}"

Context sentences where this term appears:
{CONTEXT_SENTENCES}

Choose EXACTLY ONE type from this list:
- organism          (bacteria, archaea, fungi, virus, parasite)
- gene              (gene, protein, enzyme, receptor)
- metabolite        (metabolic compound, short-chain fatty acid, bile acid)
- disease           (disease, disorder, syndrome, condition)
- pathway           (metabolic or signaling pathway)
- biomarker         (clinical measurement, lab value, index)
- body_site         (anatomical location, tissue, organ)
- cohort_type       (study population, participant group)
- clinical_assessment_tool  (scale, score, questionnaire)
- method            (sequencing method, technique, protocol)
- institution       (university, research institute, company)
- dietary_factor    (food, nutrient, supplement, diet)
- unknown           (cannot determine)

Rules:
- BSS/Bristol Stool Scale → clinical_assessment_tool
- Specific bacteria genera/species → organism
- "cohort", "population", "participants" → cohort_type
- Sequencing terms (16S, WGS, metagenomics) → method

Return ONLY this JSON:
{{
  "entity": "{TERM}",
  "entity_type": <one type from list above>,
  "confidence": <float 0.0–1.0>,
  "reasoning": "<one sentence>"
}}
"""


def disambiguate_entity_type(
    term: str,
    context_sentences: List[str],
    base_url: str,
) -> Tuple[str, float]:
    """
    Ask LLM to classify entity type using context sentences.
    Returns (entity_type, confidence).
    """
    if not context_sentences:
        return "unknown", 0.0

    context_text = "\n".join(f"- {s}" for s in context_sentences[:10])
    prompt = ENTITY_DISAMBIGUATION_PROMPT.format(
        TERM=term,
        CONTEXT_SENTENCES=context_text,
    )
    response = call_llama_cpp(prompt, base_url)
    try:
        data = extract_single_json_object(response)
        etype = data.get("entity_type", "unknown")
        conf = float(data.get("confidence", 0.0))
        return etype, conf
    except Exception:
        return "unknown", 0.0


RELATION_SCHEMA_PROMPT = """\
You are designing a biomedical knowledge graph edge schema.

Source entity: "{SOURCE}" (type: {SOURCE_TYPE})
Target entity: "{TARGET}" (type: {TARGET_TYPE})

From this master list of relation types, select ONLY the ones \
that are biologically plausible between these two entity types \
in microbiome research:

MASTER RELATION LIST:
  Causal/Mechanistic:
    produces, consumes, converts_to, metabolizes, synthesizes,
    activates, inhibits, upregulates, downregulates, degrades

  Ecological:
    colonizes, competes_with, inhibits_growth_of, promotes_growth_of,
    co-occurs_with, excludes

  Clinical:
    causes, ameliorates, protects_against, biomarker_for,
    risk_factor_for, therapeutic_target_for

  Structural:
    part_of, derived_from, encodes, binds_to, substrate_of

  Taxonomic:
    is_a, belongs_to, classifies_as

Return ONLY a JSON array of applicable relation type strings.
Be restrictive — 2 to 5 relations maximum.
If fewer than 2 are plausible → return []
Example: ["produces", "converts_to"]
"""


def get_relation_schema_for_pair(
    source: str,
    source_type: str,
    target: str,
    target_type: str,
    base_url: str,
) -> List[str]:
    """
    Ask LLM to suggest applicable relation types for an entity pair.
    Returns list of plausible relation types (2-5), or [] if none plausible.
    """
    prompt = RELATION_SCHEMA_PROMPT.format(
        SOURCE=source,
        SOURCE_TYPE=source_type,
        TARGET=target,
        TARGET_TYPE=target_type,
    )
    response = call_llama_cpp(prompt, base_url)
    try:
        data = json.loads(response)
        if isinstance(data, list):
            return [str(r) for r in data if isinstance(r, str)]
        return []
    except Exception:
        return []


CONFIDENCE_CALIBRATION_PROMPT = """\
You are calibrating confidence scores for a biomedical knowledge graph.
Your scores must match the real-world probability that a domain expert \
would agree this edge is scientifically valid.

══════════════════════════════════════════════
EDGE TO CALIBRATE:
══════════════════════════════════════════════
  {SOURCE} --[{RELATION_TYPE}]--> {TARGET}
  Current confidence: {CURRENT_CONFIDENCE}
  Evidence: "{EVIDENCE}"
  Verifier score: {VERIFIER_SCORE}
  Evidence found in text: {EVIDENCE_FOUND}
  Contradiction detected: {CONTRADICTION}
  Contradiction penalty: {CONTRADICTION_PENALTY}
  Study context: {STUDY_CONTEXT}

══════════════════════════════════════════════
CALIBRATION RUBRIC:
══════════════════════════════════════════════
  1.0  = Directly stated fact with quantitative data
         ("Bacteroides produces X at Y concentration")
  0.9  = Explicitly stated without quantitative detail
         ("B. fragilis produces butyrate")
  0.8  = Strongly implied by experimental results
  0.7  = Reported in methods/results without explicit causal claim
  0.6  = Mentioned in discussion as possible mechanism
  <0.6 = REJECT — do not include in knowledge graph

Consider:
- Is the evidence a direct statement or an inference?
- Is it from Results/Methods (higher weight) or Discussion/Abstract?
- Is there quantitative data (higher weight)?
- Does the relation_type match the actual language in evidence?

EVIDENCE HIERARCHY — apply BEFORE setting calibrated_confidence:
Tier 1 (max confidence 1.0): RCT with human subjects, meta-analysis
Tier 2 (max confidence 0.85): observational cohort in humans,
  in vivo animal study with mechanistic data
Tier 3 (max confidence 0.75): single in vitro experiment,
  case report / case series
Tier 4 (max confidence 0.65): computational prediction,
  expert opinion / review speculation
If study_context is "in_vitro" and relation_type is "causes" or
"protects_against" → apply additional -0.10 confidence penalty.

Return ONLY:
{{
  "calibrated_confidence": <float 0.6–1.0 or "REJECT">,
  "calibration_reason": "<one sentence>",
  "evidence_strength": "direct" | "implied" | "speculative"
}}
"""


def calibrate_confidence(
    edge: Dict,
    current_confidence: float,
    verifier_score: float,
    evidence_found: bool,
    contradiction_detected: bool,
    contradiction_penalty: float,
    base_url: str,
    study_context: str = "unknown",
) -> Tuple[float, str]:
    """
    Ask LLM to calibrate edge confidence using all available signals.
    Returns (calibrated_confidence, evidence_strength).
    """
    prompt = CONFIDENCE_CALIBRATION_PROMPT.format(
        SOURCE=edge.get("source", ""),
        RELATION_TYPE=edge.get("relation_type", ""),
        TARGET=edge.get("target", ""),
        CURRENT_CONFIDENCE=current_confidence,
        EVIDENCE=edge.get("evidence", ""),
        VERIFIER_SCORE=verifier_score,
        EVIDENCE_FOUND=str(evidence_found),
        CONTRADICTION=str(contradiction_detected),
        CONTRADICTION_PENALTY=contradiction_penalty,
        STUDY_CONTEXT=study_context,
    )
    response = call_llama_cpp(prompt, base_url)
    try:
        data = extract_single_json_object(response)
        calibrated = data.get("calibrated_confidence", "")
        if calibrated == "REJECT" or calibrated == "":
            return 0.0, "speculative"
        conf = float(calibrated)
        strength = data.get("evidence_strength", "implied")
        return conf, strength
    except Exception:
        return 0.0, "speculative"


RELATION_EVIDENCE_KEYWORDS = {
    "produces":         ["produc", "secret", "generat", "synthesiz"],
    "inhibits":         ["inhibit", "suppress", "reduc", "decreas"],
    "activates":        ["activ", "upregul", "induc", "promot"],
    "causes":           ["caus", "lead", "result", "contribut"],
    "protects_against": ["protect", "prevent", "reduc risk", "amelior"],
    "biomarker_for":    ["biomarker", "marker", "indicat", "diagnos"],
    "inhibits_growth_of":  ["inhibit", "suppress", "reduc", "outcompet"],
    "promotes_growth_of":  ["promot", "enhanc", "stimul", "facilit"],
    "risk_factor_for":     ["risk", "predispos", "associat", "increas risk"],
    "co-occurs_with":      ["co-occur", "found together", "correlat", "co-abund"],
    "ameliorates":         ["amelior", "alleviat", "improv", "reduc symptom"],
    "colonizes":           ["coloniz", "colonialis", "inhabit", "persist"],
}

CAUSAL_RELATION_TYPES: Set[str] = {
    "produces", "inhibits", "activates", "causes",
    "converts_to", "upregulates", "downregulates",
    "ameliorates", "protects_against"
}

# ──────────────────────────────────────────────
# FEATURE 3: Non-biological entity types filter
# ──────────────────────────────────────────────
NON_BIOLOGICAL_ENTITY_TYPES: Set[str] = {
    "study_design", "statistical_method", "sequencing_method",
    "geographic_location", "demographic_factor", "16s_rrna_gene",
    "sample_type", "institution", "method", "cohort_type",
    "clinical_assessment_tool",
}


def relation_keyword_check(edge: Dict) -> bool:
    keywords = RELATION_EVIDENCE_KEYWORDS.get(edge["relation_type"])
    if not keywords:
        return True  # no check for this type
    ev = edge.get("evidence", "").lower()
    return any(kw in ev for kw in keywords)


# ──────────────────────────────────────────────
# Relation extraction for one focal term
# ──────────────────────────────────────────────
def get_allowed_relations(src_type: str, tgt_type: str) -> List[str]:
    key = (src_type.lower(), tgt_type.lower())
    return TYPED_RELATIONS.get(key, GENERIC_RELATIONS)


def is_trivial_relation(source: str, target: str, rel_type: str) -> bool:
    """Check if relation is trivially true (encyclopedic, not scientific)."""
    src_lower = source.lower()
    tgt_lower = target.lower()

    # Same term
    if src_lower == tgt_lower:
        return True

    # Check explicit patterns
    key = (src_lower, tgt_lower, rel_type)
    if key in TRIVIAL_PATTERNS:
        return True

    # Self-referential
    if rel_type == "is_a" and src_lower == tgt_lower:
        return True

    # Obvious synonyms (stool = feces, bowel = intestine)
    if rel_type == "is_a" and src_lower in ["stool", "feces"] and tgt_lower in ["stool", "feces"]:
        return True
    if rel_type == "is_a" and src_lower == "bowel" and tgt_lower == "intestine":
        return True
    if rel_type == "part_of" and src_lower == "japan":
        return True

    return False


def extract_relations_for_term(
    term: str,
    etype: str,
    candidate_terms: List[str],
    candidate_types: List[str],
    base_url: str,
    sentence_index: Dict[str, List[Tuple[str, str]]],
    paper_metadata: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    # FEATURE 3: Skip non-biological entity types
    if etype in NON_BIOLOGICAL_ENTITY_TYPES:
        logging.debug(f"Skipping non-biological entity: '{term}' ({etype})")
        return []

    logging.info(f"extract_relations_for_term: term={term!r}, etype={etype!r}, cand={len(candidate_terms)}")
    # Get corrected entity type (fix misclassifications)
    etype = KNOWN_ENTITY_TYPES.get(etype.lower(), etype)

    all_edges: List[Dict] = []
    chunks = [candidate_terms[i:i+BATCH_SIZE] for i in range(0, len(candidate_terms), BATCH_SIZE)]
    ctype_chunks = [candidate_types[i:i+BATCH_SIZE] for i in range(0, len(candidate_types), BATCH_SIZE)]

    # Get context hint for this term
    context_hint = get_context_hint(term)
    final_edges: List[Dict] = []

    for chunk, ctypes in zip(chunks, ctype_chunks):
        # Filter candidates: only keep those with grounding sentences
        grounded_chunk = []
        grounded_ctypes = []
        grounding_info: Dict[str, List[str]] = {}

        for cand, ct in zip(chunk, ctypes):
            sentences = list(retrieve_sentences_cached(term, cand, _SENTENCE_INDEX_KEY, max_sentences=5))
            if sentences:
                grounded_chunk.append(cand)
                grounded_ctypes.append(ct)
                grounding_info[cand] = sentences

        # Skip entire batch if no candidates have grounding
        if not grounded_chunk:
            logging.debug(f"  No grounded candidates for batch with focus term: {term}")
            continue

        batch_rels = set(GENERIC_RELATIONS)
        for ct in grounded_ctypes:
            # Apply entity type corrections to candidates too
            corrected_ct = KNOWN_ENTITY_TYPES.get(ct.lower(), ct)
            allowed = set(get_allowed_relations(etype, corrected_ct))
            batch_rels = batch_rels | allowed
        batch_rels_str = ", ".join(sorted(batch_rels))

        term_list = "\n".join(f"- {t}  [type: {ct}]" for t, ct in zip(grounded_chunk, grounded_ctypes))
        logging.info(f"[{term}] candidate_terms={candidate_terms[:3]}, grounded={grounded_chunk[:3]}")

        # Build grounding context section
        grounding_context_parts = []
        for cand in grounded_chunk:
            sents = grounding_info.get(cand, [])
            if sents:
                grounding_context_parts.append(f"CANDIDATE: {cand}")
                for s in sents:
                    grounding_context_parts.append(f"  - {s}")
        grounding_context = "\n".join(grounding_context_parts) if grounding_context_parts else "No grounding sentences found for any candidate."

        prompt = USER_PROMPT_TEMPLATE.format(
            TERM=term,
            ETYPE=etype,
            TERM_LIST=term_list,
            RELATION_TYPES=batch_rels_str,
            CONTEXT_HINT=context_hint,
            RETRIEVED_CONTEXT=grounding_context,
        )

        response = call_llama_cpp(prompt, base_url)
        edges = parse_json_response(response)
        edges = reject_vague_relations(edges)
        edges = [e for e in edges if not e.get("negated", False)]

        if not edges:
            logging.debug(f"No edges extracted for {term}")
            continue

        edges = [e for e in edges if isinstance(e, dict)]
        logging.info(f"[{term}]: {len(edges)} valid dict edges extracted")

        # ── First pass: cheap validation, build context map ──
        validated_edges: List[Dict] = []
        edge_contexts: Dict[str, List[str]] = {}

        for edge in edges:
            if not all(k in edge for k in ("source", "target", "relation_type", "confidence")):
                continue
            if edge["target"] not in grounded_chunk:
                continue

            edge_source = edge.get("source", "").lower()
            edge_target = edge.get("target", "").lower()
            term_lower = term.lower()

            if edge_source != term_lower:
                if edge_target == term_lower:
                    edge["source"], edge["target"] = edge["target"], edge["source"]
                    edge["direction"] = "target_to_source" if edge.get("direction") == "source_to_target" else "source_to_target"
                else:
                    continue

            if is_trivial_relation(edge["source"], edge["target"], edge["relation_type"]):
                continue

            if float(edge.get("confidence", 0)) < MIN_CONFIDENCE:
                continue

            context_for_pair = retrieve_sentences_cached(
                term, edge["target"], _SENTENCE_INDEX_KEY, max_sentences=5
            )
            context_for_pair = list(context_for_pair)
            if not context_for_pair:
                continue
            if not evidence_matches_context(edge.get("evidence", ""), context_for_pair):
                continue

            edge_contexts[edge["target"]] = context_for_pair
            validated_edges.append(edge)

        if not validated_edges:
            continue

        # ── Second pass: batch LLM verification + contradiction (one call per edge) ──
        # Build list of (edge, context) tuples for batch_verify_edges
        edge_ctx_tuples: List[Tuple[Dict, List[str]]] = [
            (e, edge_contexts.get(e["target"], [])) for e in validated_edges
        ]
        verified_results = batch_verify_edges(edge_ctx_tuples, base_url)

        logging.info(f"Verified {len(verified_results)} edges for {term}")
        for i, (edge, ctxs, penalty) in enumerate(verified_results[:2]):
            logging.info(f"  Verified {i}: type={type(edge)}, keys={list(edge.keys()) if isinstance(edge, dict) else 'NOT DICT'}")

        # ── Third pass: final calibration and validation ──
        for edge_copy, context_for_pair, contra_penalty in verified_results:
            conf, strength = calibrate_confidence(
                edge_copy,
                current_confidence=edge_copy["confidence"],
                verifier_score=edge_copy["confidence"],
                evidence_found=edge_copy.get("evidence_found_in_text", False),
                contradiction_detected=contra_penalty > 0,
                contradiction_penalty=contra_penalty,
                base_url=base_url,
                study_context=edge_copy.get("study_context", "unknown"),
            )
            if conf < 0.6:
                continue
            edge_copy["confidence"] = round(conf, 4)
            edge_copy["evidence_strength"] = strength

            tgt_type_raw = edge_copy.get("entity_types", {}).get("target", "unknown")
            if isinstance(tgt_type_raw, list):
                tgt_type = str(tgt_type_raw[0]) if tgt_type_raw else "unknown"
            elif isinstance(tgt_type_raw, str):
                tgt_type = tgt_type_raw
            else:
                tgt_type = "unknown"
            tgt_type = KNOWN_ENTITY_TYPES.get(tgt_type.lower(), tgt_type)
            allowed = set(get_allowed_relations(etype, tgt_type)) | set(GENERIC_RELATIONS)
            if edge_copy["relation_type"] not in allowed:
                continue

            if (edge_copy.get("causal_or_correlative") == "correlative" and
                    edge_copy.get("relation_type") in CAUSAL_RELATION_TYPES):
                logging.debug(
                    f"Rejected: correlative finding with causal relation "
                    f"{edge_copy['relation_type']}: "
                    f"{edge_copy['source']} -> {edge_copy['target']}"
                )
                continue

            if edge_copy.get("negated"):
                with _NEGATED_EDGES_LOCK:
                    _NEGATED_EDGES.append(dict(edge_copy))
                continue

            if not relation_keyword_check(edge_copy):
                logging.debug(
                    f"Rejected: evidence keywords don't match relation type "
                    f"'{edge_copy['relation_type']}' for "
                    f"{edge_copy['source']} -> {edge_copy['target']}"
                )
                continue

            co_sents = retrieve_sentences_cached(
                edge_copy["source"], edge_copy["target"],
                _SENTENCE_INDEX_KEY, max_sentences=10
            )
            total_src = len(_SENTENCE_INDEX.get(edge_copy["source"].lower(), []))
            total_tgt = len(_SENTENCE_INDEX.get(edge_copy["target"].lower(), []))
            denom = min(total_src, total_tgt)
            edge_copy["cooccurrence_score"] = round(
                len(co_sents) / denom if denom > 0 else 0.0, 4
            )

            # FEATURE 1: Capture PMID + publication year
            evidence_text = edge_copy.get("evidence", "").lower()
            supporting_docs = []
            for doc_id, sent in _SENTENCE_INDEX.get(
                    edge_copy["source"].lower(), []):
                if evidence_text[:50] in sent.lower():
                    meta = (paper_metadata or {}).get(doc_id, {})
                    supporting_docs.append({
                        "doc_id": doc_id,
                        "pmid": meta.get("pmid"),
                        "year": meta.get("year"),
                    })
            edge_copy["source_pmids"] = ";".join(
                d["pmid"] for d in supporting_docs if d.get("pmid")
            )[:3]
            edge_copy["earliest_year"] = min(
                (d["year"] for d in supporting_docs if d.get("year")),
                default=None
            )

            # FEATURE 2: Normalize source and target entities
            src_norm = normalize_entity(
                edge_copy["source"],
                edge_copy.get("entity_types", {}).get("source", "unknown")
            )
            tgt_norm = normalize_entity(
                edge_copy["target"],
                edge_copy.get("entity_types", {}).get("target", "unknown")
            )
            edge_copy["source_normalized"] = (
                src_norm.get("canonical_name") or src_norm.get("chebi_id")
            )
            edge_copy["source_external_id"] = (
                src_norm.get("taxon_id") or src_norm.get("chebi_id")
            )
            edge_copy["target_normalized"] = (
                tgt_norm.get("canonical_name") or tgt_norm.get("chebi_id")
            )
            edge_copy["target_external_id"] = (
                tgt_norm.get("taxon_id") or tgt_norm.get("chebi_id")
            )

            final_edges.append(edge_copy)

    final_edges.sort(key=lambda e: float(e.get("confidence", 0)), reverse=True)
    return final_edges[:MAX_RELATIONS_PER_TERM]


# ──────────────────────────────────────────────
# Deduplication + confidence aggregation
# ──────────────────────────────────────────────
def canonical_edge_key(rel: Dict) -> str:
    """Canonical key that includes direction - so A→B != B→A."""
    direction = rel.get("direction", "undirected")
    source = rel.get("source", "")
    target = rel.get("target", "")

    # For undirected relations, sort to avoid duplicates
    # For directed, keep as-is so A→B is separate from B→A
    if direction == "undirected":
        a, b = sorted([source, target])
        return f"{a}|{rel.get('relation_type', '')}|{b}|undirected"
    else:
        return f"{source}|{rel.get('relation_type', '')}|{target}|{direction}"


def deduplicate_relations(relations: List[Dict]) -> List[Dict]:
    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for rel in relations:
        buckets[canonical_edge_key(rel)].append(rel)

    merged = []
    for key, group in buckets.items():
        best = max(group, key=lambda e: float(e.get("confidence", 0)))
        best = dict(best)
        if len(group) > 1:
            confs = [float(e.get("confidence", 0)) for e in group]
            best["confidence"] = round(float(np.mean(confs)), 4)
            best["occurrence_count"] = len(group)
        else:
            best["occurrence_count"] = 1
        merged.append(best)

    merged.sort(key=lambda e: float(e.get("confidence", 0)), reverse=True)
    return merged


# ──────────────────────────────────────────────
# FEATURE 2: Bidirectional contradiction detection
# ──────────────────────────────────────────────
CONTRADICTORY_PAIRS: List[Tuple[Dict, Dict]] = []

REVERSE_RELATION_MAP: Dict[str, str] = {
    "inhibits":            "activates",
    "activates":           "inhibits",
    "causes":              "ameliorates",
    "ameliorates":         "causes",
    "upregulates":         "downregulates",
    "downregulates":       "upregulates",
    "promotes_growth_of":  "inhibits_growth_of",
    "inhibits_growth_of":  "promotes_growth_of",
    "produces":            "consumes",
    "consumes":            "produces",
    "risk_factor_for":     "protects_against",
    "protects_against":    "risk_factor_for",
}

SYMMETRIC_RELS = {"co-occurs_with"}


def detect_bidirectional_contradictions(
    relations: List[Dict],
) -> Tuple[List[Tuple[Dict, Dict]], List[Dict]]:
    """
    Find pairs of edges that contradict each other (A--[R]-->B vs B--[R']-->A).
    Returns (contradictory_pairs, contradiction_report).
    """
    global CONTRADICTORY_PAIRS
    CONTRADICTORY_PAIRS = []

    edge_index: Dict[str, Dict] = {}
    for rel in relations:
        if rel.get("negated"):
            continue
        src = rel.get("source", "").lower()
        tgt = rel.get("target", "").lower()
        rel_type = rel.get("relation_type", "")
        direction = rel.get("direction", "forward")
        key = (src, tgt, rel_type, direction)
        edge_index[key] = rel

    seen_pairs: Set[Tuple[str, str]] = set()
    contradiction_report: List[Dict] = []

    for rel in relations:
        if rel.get("negated"):
            continue
        src = rel.get("source", "").lower()
        tgt = rel.get("target", "").lower()
        rel_type = rel.get("relation_type", "")

        if rel_type in SYMMETRIC_RELS:
            continue

        reverse_rel_type = REVERSE_RELATION_MAP.get(rel_type)
        if not reverse_rel_type:
            continue

        for direction in ("forward", "reverse"):
            reverse_key = (tgt, src, reverse_rel_type, direction)
            reverse_edge = edge_index.get(reverse_key)
            if not reverse_edge:
                continue

            pair_key = tuple(sorted([id(rel), id(reverse_edge)]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            CONTRADICTORY_PAIRS.append((rel, reverse_edge))
            contradiction_report.append({
                "edge_1": dict(rel),
                "edge_2": dict(reverse_edge),
                "edge_1_desc": f"{rel.get('source')} --[{rel_type}]--> {rel.get('target')}",
                "edge_2_desc": f"{reverse_edge.get('source')} --[{reverse_rel_type}]--> {reverse_edge.get('target')}",
                "contradiction_type": f"{rel_type} ↔ {reverse_rel_type}",
            })

    return CONTRADICTORY_PAIRS, contradiction_report


# ──────────────────────────────────────────────
# FEATURE 3: Summary report
# ──────────────────────────────────────────────
def write_summary_report(
    final_relations: List[Dict],
    contradiction_report: List[Dict],
    output_dir: str = OUTPUT_DIR,
) -> None:
    """Write a human-readable summary report to output_dir/summary_report.txt."""
    out_path = Path(output_dir) / "summary_report.txt"

    total_edges = len(final_relations)
    negated_count = len(_NEGATED_EDGES)
    contradicted_count = len(contradiction_report)

    # Edge type distribution
    rel_counts: Dict[str, int] = defaultdict(int)
    for r in final_relations:
        rel_counts[r.get("relation_type", "unknown")] += 1
    top_rel_types = sorted(rel_counts.items(), key=lambda x: -x[1])[:10]

    # Highest-confidence edges
    top_conf = sorted(final_relations, key=lambda e: float(e.get("confidence", 0)), reverse=True)[:10]

    # Confidence distribution buckets
    buckets = {"0.65-0.69": 0, "0.70-0.79": 0, "0.80-0.89": 0, "0.90+": 0}
    for r in final_relations:
        conf = float(r.get("confidence", 0))
        if conf >= 0.90:
            buckets["0.90+"] += 1
        elif conf >= 0.80:
            buckets["0.80-0.89"] += 1
        elif conf >= 0.70:
            buckets["0.70-0.79"] += 1
        else:
            buckets["0.65-0.69"] += 1

    # Most frequent source-target pairs
    st_counts: Dict[str, int] = defaultdict(int)
    for r in final_relations:
        st_counts[f"{r.get('source', '')} --> {r.get('target', '')}"] += 1
    top_st_pairs = sorted(st_counts.items(), key=lambda x: -x[1])[:10]

    lines = [
        "=" * 60,
        "KNOWLEDGE GRAPH SUMMARY REPORT",
        "=" * 60,
        f"Total unique edges:           {total_edges}",
        f"Negated edges removed:        {negated_count}",
        f"Contradictory pairs found:   {contradicted_count}",
        "",
        "EDGE TYPE DISTRIBUTION (Top 10):",
        "-" * 40,
    ]
    for rel_type, count in top_rel_types:
        lines.append(f"  {rel_type:<30} {count:>6}")

    lines.extend([
        "",
        "HIGHEST-CONFIDENCE EDGES (Top 10):",
        "-" * 40,
    ])
    for i, r in enumerate(top_conf, 1):
        lines.append(
            f"  {i:>2}. [{r.get('confidence', 0):.4f}] "
            f"{r.get('source', '')} --[{r.get('relation_type', '')}]--> {r.get('target', '')}"
        )

    lines.extend([
        "",
        "CONFIDENCE DISTRIBUTION:",
        "-" * 40,
    ])
    for bucket, count in buckets.items():
        lines.append(f"  {bucket:<12} {count:>6}")

    lines.extend([
        "",
        "MOST FREQUENT SOURCE-TARGET PAIRS (Top 10):",
        "-" * 40,
    ])
    for i, (pair, count) in enumerate(top_st_pairs, 1):
        lines.append(f"  {i:>2}. {pair} ({count})")

    lines.append("=" * 60)

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    logging.info(f"Summary report written to {out_path}")


# ──────────────────────────────────────────────
# FEATURE 4: Automated LLM-based precision estimation
# ──────────────────────────────────────────────
AUTO_JUDGE_PROMPT = """\
You are an independent biomedical expert reviewing a knowledge graph
edge extracted from scientific literature.

You were NOT involved in extracting this edge.
Your job: decide if this edge is scientifically valid.

═════════════════════════════════════════════
EDGE TO JUDGE:
═════════════════════════════════════════════
  Source      : {SOURCE} (type: {SOURCE_TYPE})
  Relation    : {RELATION_TYPE}
  Target      : {TARGET} (type: {TARGET_TYPE})
  Direction   : {DIRECTION}
  Study type  : {STUDY_CONTEXT}
  Evidence    : "{EVIDENCE}"

═════════════════════════════════════════════
ORIGINAL SOURCE TEXT:
═════════════════════════════════════════════
{CONTEXT}

═════════════════════════════════════════════
JUDGMENT CRITERIA:
═════════════════════════════════════════════
Answer YES only if ALL of the following are true:
1. The evidence quote appears in the source text above
2. The relation_type accurately describes what the evidence says
3. The direction is correct (source acts on target)
4. There is no negation signal in or around the evidence
5. This is a specific microbiome finding, not trivial biology

Answer NO if ANY criterion fails.
Answer UNCERTAIN if the evidence is ambiguous or partial.

Return ONLY this JSON:
{{
  "verdict": "yes" | "no" | "uncertain",
  "reason": "<one sentence>",
  "criterion_failed": <1-5 or null>
}}
"""

def auto_judge_edge(
    edge: Dict,
    context_sentences: List[str],
    base_url: str,
) -> str:
    """
    Use LLM as independent judge to validate a single edge.
    Returns 'yes', 'no', or 'uncertain'.
    """
    if not context_sentences:
        return "uncertain"
    context_text = "\n".join(context_sentences[:8])
    prompt = AUTO_JUDGE_PROMPT.format(
        SOURCE=edge.get("source", ""),
        SOURCE_TYPE=edge.get("entity_types", {}).get("source", "unknown"),
        RELATION_TYPE=edge.get("relation_type", ""),
        TARGET=edge.get("target", ""),
        TARGET_TYPE=edge.get("entity_types", {}).get("target", "unknown"),
        DIRECTION=edge.get("direction", "undirected"),
        STUDY_CONTEXT=edge.get("study_context", "unknown"),
        EVIDENCE=edge.get("evidence", ""),
        CONTEXT=context_text,
    )
    response = call_llama_cpp(prompt, base_url)
    try:
        data = extract_single_json_object(response)
        return str(data.get("verdict", "uncertain")).lower()
    except Exception:
        return "uncertain"

def run_automated_precision_evaluation(
    relations: List[Dict],
    base_url: str,
    output_dir: str,
    sample_size: int = 100,
    seed: int = 42,
) -> None:
    """
    Sample edges, run each through an independent LLM judge,
    compute estimated precision, and write full report.

    This is scientifically defensible as LLM-as-judge evaluation —
    cite: Zheng et al. 2023 (MT-Bench), Fu et al. 2023 (GPTScore).
    """
    import random
    random.seed(seed)

    if not relations:
        logging.warning("No relations to evaluate.")
        return

    # Stratified sample by relation_type
    from collections import Counter
    type_counts = Counter(r["relation_type"] for r in relations)
    sample: List[Dict] = []
    for rtype, count in type_counts.items():
        rtype_edges = [r for r in relations
                       if r["relation_type"] == rtype]
        n = max(1, round(sample_size * count / len(relations)))
        sample.extend(
            random.sample(rtype_edges, min(n, len(rtype_edges)))
        )
    if len(sample) < sample_size:
        remaining = [r for r in relations if r not in sample]
        if remaining:
            sample.extend(random.sample(
                remaining,
                min(sample_size - len(sample), len(remaining))
            ))
    sample = sample[:sample_size]

    logging.info(
        f"Running automated precision evaluation on "
        f"{len(sample)} sampled edges..."
    )

    verdicts: List[Dict] = []
    yes_count = no_count = uncertain_count = 0

    for i, edge in enumerate(sample):
        ctx = list(retrieve_sentences_cached(
            edge["source"], edge["target"],
            _SENTENCE_INDEX_KEY, max_sentences=8
        ))
        verdict = auto_judge_edge(edge, ctx, base_url)
        if verdict == "yes":
            yes_count += 1
        elif verdict == "no":
            no_count += 1
        else:
            uncertain_count += 1

        verdicts.append({
            **{k: edge.get(k, "") for k in [
                "source", "relation_type", "target",
                "confidence", "evidence", "study_context",
                "source_pmids", "earliest_year",
            ]},
            "auto_verdict": verdict,
        })

        if (i + 1) % 10 == 0:
            logging.info(
                f"  Judged {i+1}/{len(sample)}: "
                f"yes={yes_count} no={no_count} "
                f"uncertain={uncertain_count}"
            )

    total_judged = yes_count + no_count
    estimated_precision = (
        yes_count / total_judged if total_judged > 0 else 0.0
    )
    # Conservative precision (treating uncertain as wrong)
    conservative_precision = (
        yes_count / len(sample) if sample else 0.0
    )

    # Write verdict CSV
    verdict_path = os.path.join(output_dir, "auto_evaluation.csv")
    with open(verdict_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(verdicts[0].keys())
        )
        writer.writeheader()
        writer.writerows(verdicts)

    # Write evaluation report
    report_lines = [
        "=" * 60,
        "AUTOMATED PRECISION EVALUATION REPORT",
        "(LLM-as-Judge methodology — Zheng et al. 2023)",
        "=" * 60,
        f"Sample size:                {len(sample)} edges",
        f"Sampling strategy:          stratified by relation_type",
        f"Judge model:                {MODEL_NAME}",
        f"",
        f"Verdicts:",
        f"  YES (valid edge):         {yes_count}",
        f"  NO  (invalid edge):       {no_count}",
        f"  UNCERTAIN:                {uncertain_count}",
        f"",
        f"Estimated precision:        {estimated_precision:.3f}",
        f"Conservative precision:     {conservative_precision:.3f}",
        f"  (conservative = uncertain treated as incorrect)",
        f"",
        f"Precision by relation type:",
    ]

    from collections import defaultdict as _dd
    by_type: Dict = _dd(lambda: {"yes": 0, "no": 0, "uncertain": 0})
    for v in verdicts:
        by_type[v["relation_type"]][v["auto_verdict"]] += 1
    for rtype, counts in sorted(by_type.items()):
        t = counts["yes"] + counts["no"]
        p = counts["yes"] / t if t > 0 else 0.0
        report_lines.append(
            f"  {rtype:<40} {p:.3f}  (n={t})"
        )

    report_lines += [
        "",
        "Methodology note for thesis/paper:",
        "  Automated evaluation uses the same LLM as extractor.",
        "  To reduce self-evaluation bias, rerun auto_judge_edge()",
        "  with a different model (e.g. LLaMA-3, Mistral) for",
        "  cross-model validation. Full verdict log: auto_evaluation.csv",
        "=" * 60,
    ]

    report_text = "\n".join(report_lines)
    print(report_text)
    eval_report_path = os.path.join(output_dir, "auto_evaluation_report.txt")
    with open(eval_report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    logging.info(f"Evaluation report → {eval_report_path}")


# ──────────────────────────────────────────────
# FEATURE 4: NetworkX GraphML export
# ──────────────────────────────────────────────
def export_to_networkx(
    relations: List[Dict],
    output_dir: str = OUTPUT_DIR,
) -> None:
    """Export relations to a NetworkX DiGraph and save as GraphML."""
    G = nx.DiGraph()

    entity_type_map: Dict[str, str] = {}
    for r in relations:
        src = r.get("source", "")
        tgt = r.get("target", "")
        entity_type_map[src] = r.get("source_type", "unknown")
        entity_type_map[tgt] = r.get("target_type", "unknown")

    for r in relations:
        src = r.get("source", "")
        tgt = r.get("target", "")
        rel_type = r.get("relation_type", "")
        direction = r.get("direction", "forward")

        if src not in G:
            G.add_node(src, entity_type=entity_type_map.get(src, "unknown"))
        if tgt not in G:
            G.add_node(tgt, entity_type=entity_type_map.get(tgt, "unknown"))

        G.add_edge(src, tgt,
                   relation_type=rel_type,
                   confidence=float(r.get("confidence", 0.0)),
                   direction=direction,
                   evidence=r.get("evidence", ""),
                   negated=r.get("negated", False))

    out_path = Path(output_dir) / "knowledge_graph.graphml"
    nx.write_graphml(G, str(out_path))
    logging.info(f"NetworkX graph exported to {out_path} ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")


# ──────────────────────────────────────────────
# Checkpoint helpers
# ──────────────────────────────────────────────
def load_checkpoint() -> Dict:
    p = Path(CHECKPOINT_FILE)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {"processed_terms": [], "relations": []}


def save_checkpoint(checkpoint: Dict):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoint, f, indent=2)


# ──────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────
def print_graph_stats(relations: List[Dict]):
    nodes = set()
    for r in relations:
        nodes.add(r.get("source", ""))
        nodes.add(r.get("target", ""))
    rtype_counts: Dict[str, int] = defaultdict(int)
    for r in relations:
        rtype_counts[r.get("relation_type", "unknown")] += 1

    logging.info("─" * 50)
    logging.info(f"  Nodes (terms):  {len(nodes)}")
    logging.info(f"  Edges (unique): {len(relations)}")
    logging.info("  Relation type breakdown:")
    for rtype, cnt in sorted(rtype_counts.items(), key=lambda x: -x[1]):
        logging.info(f"    {rtype:<25} {cnt}")
    logging.info("─" * 50)


# ──────────────────────────────────────────────
# Evidence aggregation across papers
# ──────────────────────────────────────────────
def aggregate_duplicate_edges(relations: List[Dict]) -> List[Dict]:
    """
    Merge duplicate (source, relation_type, target) triples across papers.
    - Confidence = 1 - (1 - avg_conf)^N  (probability product rule)
    - Evidence strings are deduplicated and concatenated
    - replicated = "yes" if N >= 2 independent papers
    - study_contexts are collected across all occurrences
    """
    from collections import defaultdict
    grouped = defaultdict(list)
    for rel in relations:
        key = (rel["source"].lower(), rel["relation_type"], rel["target"].lower())
        grouped[key].append(rel)

    merged = []
    for key, group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        base = dict(max(group, key=lambda r: float(r.get("confidence", 0))))
        n = len(group)
        avg_conf = sum(r.get("confidence", 0.7) for r in group) / n
        base["confidence"] = round(1 - (1 - avg_conf) ** n, 4)
        seen_ev = set()
        all_evidence = []
        for r in group:
            ev = r.get("evidence", "")
            if ev and ev not in seen_ev:
                seen_ev.add(ev)
                all_evidence.append(ev)
        base["evidence"] = " | ".join(all_evidence)
        base["replicated"] = "yes" if n >= 2 else "no"
        contexts = list({r.get("study_context", "unknown") for r in group})
        base["study_contexts"] = contexts
        base["occurrence_count"] = n
        merged.append(base)
    return merged


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def build_knowledge_graph(
    entities_jsonl: str,
    llama_cpp_url: str,
    max_entities: Optional[int] = None,
    dry_run: bool = False,
):
    setup_logging()
    logging.info(f"LLM model: {MODEL_NAME}")
    logging.info(f"LLM URL: {llama_cpp_url}")
    logging.info(f"Embed model: BAAI/bge-small-en-v1.5 (sentence-transformers)")

    entities = load_entities(entities_jsonl)
    terms     = [e["entity"]      for e in entities]
    etypes    = [e["entity_type"] for e in entities]

    logging.info(f"Unique terms: {len(terms)}")

    # Build sentence-level index for grounding
    sentence_index = build_sentence_index(entities, PAPERS_DIR)

    # FEATURE 1: Load paper metadata
    paper_metadata = load_paper_metadata(PAPERS_DIR)

    # ── Disambiguate unknown entity types at startup (one-time cost) ──
    unknown_entities = [e for e in entities if e["entity_type"] == "unknown"]
    if unknown_entities:
        logging.info(f"Disambiguating {len(unknown_entities)} unknown entity types...")
        for ent in unknown_entities:
            ctx_sents = sentence_index.get(ent["entity"].lower(), [])
            ctx_texts = [s for _, s in ctx_sents[:10]]
            if not ctx_texts:
                continue
            etype, conf = disambiguate_entity_type(ent["entity"], ctx_texts, llama_cpp_url)
            if conf >= 0.7 and etype != "unknown":
                ent["entity_type"] = etype
                logging.info(f"  {ent['entity']} → {etype} (conf {conf:.2f})")

    # Build semantic embeddings via Ollama (still needed for embeddings)
    embeddings = build_embeddings(terms)
    term_index = {t: i for i, t in enumerate(terms)}

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # FEATURE 2: Load normalization cache from previous runs
    load_normalization_cache(OUTPUT_DIR)

    # Load checkpoint for resume support
    checkpoint = load_checkpoint()
    processed_terms: Set[str] = set(checkpoint.get("processed_terms", []))
    all_relations: List[Dict] = checkpoint.get("relations", [])
    checkpoint_lock = threading.Lock()

    def _process_term(term_etype_idx: Tuple) -> Tuple[str, List[Dict]]:
        term, etype, focal_idx = term_etype_idx
        neighbour_idxs = top_k_neighbours(focal_idx, embeddings, k=TOP_K_CANDIDATES)
        cand_terms = [terms[j] for j in neighbour_idxs]
        cand_types = [etypes[j] for j in neighbour_idxs]
        relations = extract_relations_for_term(
            term, etype, cand_terms, cand_types,
            llama_cpp_url, sentence_index,
            paper_metadata=paper_metadata,
        )
        for rel in relations:
            rel["focal_term"] = term
        return term, relations

    total = len(terms)
    todo = [
        (term, etype, term_index[term])
        for term, etype in zip(terms, etypes)
        if term.lower() not in processed_terms
    ]
    if max_entities is not None:
        todo = todo[:max_entities]
        logging.info(f"Limited to {max_entities} entities (dry-run/test mode)")

    # FEATURE 5: Dry-run mode - just print status and exit
    if dry_run:
        logging.info("=== DRY RUN MODE ===")
        logging.info(f"Would process {len(todo)} terms")
        logging.info(f"Already processed: {len(processed_terms)} terms")
        logging.info(f"Existing relations in checkpoint: {len(all_relations)}")
        return []

    logging.info(f"Processing {len(todo)} terms with 4 workers...")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_process_term, args): args[0]
            for args in todo
        }
        for future in as_completed(futures):
            try:
                term, relations = future.result()
                checkpoint_snapshot = None
                with checkpoint_lock:
                    all_relations.extend(relations)
                    processed_terms.add(term)
                    done = len(processed_terms)
                    if done % 10 == 0:
                        checkpoint_snapshot = {
                            "processed_terms": list(processed_terms),
                            "relations": all_relations
                        }
                if checkpoint_snapshot is not None:
                    save_checkpoint(checkpoint_snapshot)
                    logging.info(
                        f"  [{done}/{total}] Checkpoint saved "
                        f"({len(all_relations)} raw edges)"
                    )
            except Exception as exc:
                term = futures[future]
                logging.warning(f"Term '{term}' failed: {exc}")
                logging.warning(traceback.format_exc())

    # Post-processing
    logging.info("Deduplicating and aggregating relations …")
    final_relations = aggregate_duplicate_edges(all_relations)
    final_relations = deduplicate_relations(final_relations)

    # FEATURE 2: Bidirectional contradiction detection
    CONTRADICTORY_PAIRS, contradiction_report = detect_bidirectional_contradictions(final_relations)
    logging.info(f"Found {len(CONTRADICTORY_PAIRS)} contradictory edge pairs")

    # Write contradicted edges
    out_contradicted = Path(OUTPUT_DIR) / "contradicted_edges.jsonl"
    with open(out_contradicted, "w") as f:
        for pair in CONTRADICTORY_PAIRS:
            f.write(json.dumps(pair) + "\n")

    save_checkpoint({"processed_terms": list(processed_terms),
                     "relations": all_relations})

    # Write outputs
    out_raw   = Path(OUTPUT_DIR) / "relations_raw.jsonl"
    out_final = Path(OUTPUT_DIR) / "relations.jsonl"
    out_csv   = Path(OUTPUT_DIR) / "relations.csv"

    with open(out_raw, "w") as f:
        for r in all_relations:
            f.write(json.dumps(r) + "\n")

    with open(out_final, "w") as f:
        for r in final_relations:
            f.write(json.dumps(r) + "\n")

    # FEATURE 2: Save normalization cache for future runs
    save_normalization_cache(OUTPUT_DIR)

    for r in final_relations:
        stats = r.pop("statistical_support", None) or {}
        r["p_value_mentioned"]      = stats.get("p_value_mentioned", "")
        r["effect_size_mentioned"]  = stats.get("effect_size_mentioned", "")
        r["sample_size"]            = stats.get("sample_size", "")

    csv_keys = [
        "source", "target", "relation_type", "direction",
        "confidence", "cooccurrence_score", "occurrence_count", "evidence",
        "study_context", "species_specificity", "strain_level",
        "causal_or_correlative", "negated", "conditionality",
        "evidence_section", "replicated", "evidence_strength",
        "source_pmids", "earliest_year",
        "source_normalized", "source_external_id",
        "target_normalized", "target_external_id",
        "p_value_mentioned", "effect_size_mentioned", "sample_size"
    ]
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(final_relations)

    # FEATURE 1: Write negated edges audit file
    out_negated = Path(OUTPUT_DIR) / "negated_edges.jsonl"
    with open(out_negated, "w") as f:
        for r in _NEGATED_EDGES:
            f.write(json.dumps(r) + "\n")
    if _NEGATED_EDGES:
        logging.info(f"Negated edges audit: {len(_NEGATED_EDGES)} edges removed")

    print_graph_stats(final_relations)
    logging.info(f"Done. {len(final_relations)} unique edges → {OUTPUT_DIR}/")

    # FEATURE 4: Export to NetworkX
    export_to_networkx(final_relations)

    # FEATURE 3: Write summary report
    write_summary_report(final_relations, contradiction_report)

    # FEATURE 4: Run automated LLM-based precision evaluation
    run_automated_precision_evaluation(
        final_relations,
        llama_cpp_url,
        OUTPUT_DIR,
        sample_size=100,
    )

    return final_relations


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build a knowledge graph from microbiome entity relations."
    )
    parser.add_argument(
        "--entities",
        default="../../archive/legacy_kg_extraction/extraction/entities_raw.jsonl",
        help=(
            "Path to entities JSONL file "
            "(default: ../../archive/legacy_kg_extraction/extraction/entities_raw.jsonl)"
        ),
    )
    parser.add_argument(
        "--llama-url",
        default="http://127.0.0.1:8000/v1",
        help="llama_cpp server URL (default: http://127.0.0.1:8000/v1)",
    )
    parser.add_argument(
        "--max-entities",
        type=int,
        default=None,
        help="Limit number of entities to process (for testing/dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load checkpoint and print status without calling LLM",
    )

    args = parser.parse_args()

    os.chdir(Path(__file__).parent)
    build_knowledge_graph(
        entities_jsonl=args.entities,
        llama_cpp_url=args.llama_url,
        max_entities=args.max_entities,
        dry_run=args.dry_run,
    )
