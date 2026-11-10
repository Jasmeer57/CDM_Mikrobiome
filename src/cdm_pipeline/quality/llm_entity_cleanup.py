"""LLM-based entity cleanup — type correction, semantic dedup, noise detection.

Three-pass entity quality pipeline using Ollama LLM + bge-m3 embeddings:

  Pass 1: Type correction (LLM) — fixes mis-typed entities using Qwen3 generative LLM.
          Targets entities where the ontology-ID prefix doesn't match the assigned type,
          or the entity name looks suspicious for its current type.
  Pass 2: Semantic deduplication (bge-m3) — merges semantic duplicate entities within
          the same CDM type using bge-m3 embedding cosine similarity (threshold 0.90).
  Pass 3: Noise detection (LLM) — flags extraction artifacts (non-biomedical terms,
          truncated words, coding artifacts) for removal or confidence downgrade.

All operations read from and write to the SQLite DB directly. Uses JSON checkpoints
for resume after timeout (important for large entity sets on GPU nodes).

Usage:
    from cdm_pipeline.quality.llm_entity_cleanup import run_entity_cleanup
    result = run_entity_cleanup(db_path=Path("microbiome_cdm.db"), apply=True)

    # Or via CLI:
    # python -m cdm_pipeline.quality.llm_entity_cleanup --db microbiome_cdm.db --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

logger = logging.getLogger(__name__)

# ── Ollama defaults ──
DEFAULT_LLM_MODEL = os.environ.get("ENTITY_CLEANUP_MODEL", "qwen3.5:9b")
DEFAULT_EMBED_MODEL = os.environ.get("ECO_EMBED_MODEL", "bge-m3:latest")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "8192"))
MAX_RETRIES = 3
TIMEOUT = 600

# ── Thresholds ──
DEDUP_THRESHOLD = 0.90
LLM_BATCH_SIZE = 30
EMBED_BATCH_SIZE = 64
EMBED_WORKERS = 8

# ── CDM entity types (14) ──
CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]

# ── Type→ontology prefix map (for mismatch detection) ──
TYPE_PREFIX_MAP: Dict[str, set] = {
    "ORGANISM": {"NCBITAXON", "GTDB"},
    "CHEMICAL": {"CHEBI", "MESH", "RXNORM", "DRUGBANK"},
    "DISEASE": {"MONDO", "DOID", "EFO", "MESH", "HP", "ORPHANET", "OMIM"},
    "PROTEIN": {"PR", "HGNC", "GO", "UNIPROT"},
    "DNA_RNA": {"SO", "SEQUENCE", "GENEPIO"},
    "CELL_TYPE": {"CL", "CLO"},
    "GENOMICS": {"OBI", "SO", "NCIT"},
    "PATHWAY": {"GO", "WIKIPATHWAYS", "REACTOME", "KEGG"},
    "LAB_METHOD": {"OBI", "ERO", "NCIT"},
    "DATA_ANALYSIS": {"STATO", "OBI", "EDAM", "NCIT"},
    "SAMPLE_METHOD": {"OBI", "NCIT"},
    "CLINICAL": {"SNOMEDCT", "NCIT", "LOINC", "MESH"},
    "EXPERIMENTAL_METHOD": {"OBI", "ERO", "NCIT"},
    "STUDY_DESIGN": {"OBI", "SNOMEDCT", "NCIT"},
}

# ── Type prototypes for embedding-based classification ──
TYPE_PROTOTYPES: Dict[str, str] = {
    "ORGANISM": "living individual microbial or host species bacteria virus fungus archaeon microbe pathogen taxon strain genus",
    "CHEMICAL": "small molecule compound drug metabolite lipid amino acid short chain fatty acid nutrient vitamin mineral",
    "DISEASE": "medical condition disorder illness syndrome pathology inflammatory bowel disease crohn's colitis cancer diabetes",
    "PROTEIN": "gene product polypeptide enzyme receptor transcription factor antibody cytokine signaling molecule",
    "DNA_RNA": "genetic sequence DNA RNA gene locus coding region transcript genome metagenome amplicon 16S rRNA",
    "CELL_TYPE": "specific cell kind immune cell T cell B cell macrophage epithelial cell Paneth cell goblet cell",
    "GENOMICS": "genomic analysis taxonomic profiling alpha diversity beta diversity gene cluster operon metagenomics",
    "PATHWAY": "biological process signaling cascade metabolic route NF-kB MAPK Wnt beta-catenin mTOR autophagy",
    "LAB_METHOD": "laboratory technique assay procedure chromatography mass spectrometry PCR sequencing culturing",
    "DATA_ANALYSIS": "statistical analysis bioinformatics method PERMANOVA ANOVA regression machine learning diversity index",
    "SAMPLE_METHOD": "sampling collection method stool sample biopsy fecal swab environmental sample collection protocol",
    "CLINICAL": "clinical outcome patient group biomarker measurement disease activity score remission relapse cohort",
    "EXPERIMENTAL_METHOD": "experimental design study procedure intervention protocol treatment arms control group",
    "STUDY_DESIGN": "study type randomized controlled trial cohort case-control cross-sectional longitudinal meta-analysis",
}

# ── Noise prototypes ──
NOISE_PROTOTYPE = (
    "non-biomedical term extraction artifact truncated word coding artifact "
    "random string generic word with no specific meaning common English word "
    "lab reagent buffer vehicle negative control placeholder abbreviation"
)

NO_THINKING = (
    "You are a biomedical entity quality curator. "
    "Do not show your reasoning. Return ONLY the JSON array requested."
)


# ── Ollama helpers ──────────────────────────────────────────

def _ensure_ollama_host() -> str:
    """Ensure OLLAMA_HOST has http:// prefix."""
    raw = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if raw and not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"http://{raw}"
        os.environ["OLLAMA_HOST"] = raw
    return raw


def _call_llm(prompt: str, model: str = DEFAULT_LLM_MODEL) -> Optional[str]:
    """Call Ollama /api/chat with think=false for Qwen3 compatibility."""
    host = _ensure_ollama_host()
    endpoint = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": NO_THINKING},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "format": None,
        "options": {
            "temperature": 0,
            "seed": 42,
            "top_p": 0.9,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(endpoint, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                raw = msg.get("content", "").strip()
                if raw:
                    return raw
                logger.warning(f"Empty LLM response (attempt {attempt})")
                time.sleep(5 * attempt)
            else:
                logger.error(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
                time.sleep(10 * attempt)
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(10)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error (attempt {attempt}/{MAX_RETRIES}): {e}")
            time.sleep(10 * attempt)
    return None


def _embed_batch(texts: List[str], model: str = DEFAULT_EMBED_MODEL) -> np.ndarray:
    """Embed a batch of texts via Ollama /api/embed."""
    host = _ensure_ollama_host()
    resp = requests.post(
        f"{host}/api/embed",
        json={"model": model, "input": texts},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return np.array(data["embeddings"], dtype=np.float32)


def _embed_single(text: str, model: str = DEFAULT_EMBED_MODEL) -> Optional[np.ndarray]:
    """Embed a single text via Ollama /api/embed."""
    try:
        result = _embed_batch([text], model)
        return result[0] if len(result) > 0 else None
    except Exception as e:
        logger.warning(f"Embed failed for '{text[:50]}': {e}")
        return None


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1D arrays."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _parse_json_array(raw: str) -> list:
    """Parse a JSON array from LLM response, handling markdown fences and noise."""
    if not raw:
        return []
    # Strip markdown code fences
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = raw.strip().rstrip("`")
    # Find JSON array
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return []


# ── DB helpers ──────────────────────────────────────────────

def _get_entity_ontology_prefix(entity_row: tuple) -> str:
    """Extract ontology prefix from the first non-empty ontology field."""
    # Fields: UMLS_ID, OLS, Bioportal, NCBITaxon
    for val in entity_row:
        if val and isinstance(val, str) and ":" in val:
            return val.split(":")[0].upper()
    return ""


def _load_entities(conn: sqlite3.Connection) -> List[dict]:
    """Load all entities from DB into dicts."""
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, term, entity_type, UMLS_ID, OLS, Bioportal, NCBITaxon, "
        "paper_count, frequency FROM entities ORDER BY id"
    ).fetchall()
    entities = []
    for r in rows:
        eid, term, etype, umls, ols, bio, ncbi, pcount, freq = r
        # Determine ontology prefix
        prefix = ""
        for val in (umls, ols, bio, ncbi):
            if val and isinstance(val, str) and ":" in val:
                prefix = val.split(":")[0].upper()
                break
        entities.append({
            "id": eid,
            "name": term,
            "type": etype or "UNKNOWN",
            "ontology_id": umls or ols or bio or ncbi or "",
            "ontology_prefix": prefix,
            "paper_count": pcount or 0,
            "frequency": freq or 0,
            "umls": umls or "",
            "ols": ols or "",
            "bioportal": bio or "",
            "ncbitaxon": ncbi or "",
        })
    return entities


# ── Pass 1: Type Correction (LLM) ──────────────────────────

def _find_type_correction_candidates(entities: List[dict]) -> List[dict]:
    """Find entities whose type may be wrong.

    Criteria:
    - Ontology-ID prefix doesn't match the assigned type's expected prefixes
    - Entity name looks suspicious for its type (e.g., 'taxonomic' as DISEASE)
    - Entity type is not in the 14 CDM types
    """
    candidates = []
    for e in entities:
        # Type not in CDM types
        if e["type"] not in CDM_TYPES:
            candidates.append(e)
            continue
        # Prefix mismatch
        if e["ontology_prefix"]:
            expected = TYPE_PREFIX_MAP.get(e["type"], set())
            if expected and e["ontology_prefix"] not in expected:
                # Some prefixes are valid across types (MESH, UMLS, NCIT)
                if e["ontology_prefix"] not in {"MESH", "UMLS", "NCIT"}:
                    candidates.append(e)
                    continue
    return candidates


def _llm_classify_batch(batch: List[dict]) -> List[dict]:
    """Ask LLM to classify entities into CDM types."""
    lines = []
    for i, e in enumerate(batch):
        lines.append(
            f'{i+1}. Name: "{e["name"]}", Current type: {e["type"]}, '
            f'Ontology ID: {e.get("ontology_id", "")}, '
            f'Ontology prefix: {e.get("ontology_prefix", "")}'
        )
    entities_str = "\n".join(lines)
    types_str = ", ".join(CDM_TYPES)

    prompt = (
        f"Classify each entity into exactly one type from this list: {types_str}\n\n"
        f"Use the ontology ID prefix as a strong signal:\n"
        f"  NCBITaxon → ORGANISM, CHEBI → CHEMICAL, MONDO/DOID → DISEASE, "
        f"GO → PATHWAY, HP → DISEASE, CL → CELL_TYPE, HGNC → PROTEIN, "
        f"SO → DNA_RNA, OBI → LAB_METHOD/SAMPLE_METHOD/EXPERIMENTAL_METHOD, "
        f"STATO → DATA_ANALYSIS, EFO → CLINICAL/DISEASE, SNOMEDCT → CLINICAL/DISEASE\n\n"
        f"Common errors to fix:\n"
        f"- Generic words ('taxa', 'species', 'reads', 'negative') are usually noise or wrong type\n"
        f"- 'taxonomic' is not a DISEASE — it should be GENOMICS or DATA_ANALYSIS\n"
        f"- 'sequencing' should be LAB_METHOD or DATA_ANALYSIS\n"
        f"- 'treatment' should be CLINICAL\n"
        f"- Patient groups typed as ORGANISM should be CLINICAL\n\n"
        f"Entities:\n{entities_str}\n\n"
        f'Return a JSON array: [{{"index": 1, "type": "...", "confidence": 0.0-1.0}}]'
    )
    raw = _call_llm(prompt)
    if not raw:
        return []
    return _parse_json_array(raw)


def pass1_type_correction(
    entities: List[dict],
    checkpoint_path: Optional[Path] = None,
    apply: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[List[dict], dict]:
    """Pass 1: LLM-based type correction for mis-typed entities.

    Returns (entities, corrections_dict) where corrections_dict maps
    entity_id → {"old_type": ..., "new_type": ..., "confidence": ...}
    """
    logger.info("=" * 60)
    logger.info("PASS 1: Type Correction (LLM)")
    logger.info("=" * 60)

    # Load checkpoint
    checkpoint = {}
    if checkpoint_path and checkpoint_path.exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            checkpoint = json.load(f)
        logger.info(f"  Loaded checkpoint: {len(checkpoint)} corrections")

    # Find candidates (always, so we can resume from partial checkpoint)
    all_candidates = _find_type_correction_candidates(entities)
    # Skip candidates already in checkpoint
    candidates = [e for e in all_candidates if str(e["id"]) not in checkpoint]
    logger.info(f"  Type correction candidates: {len(candidates)} ({len(all_candidates) - len(candidates)} already in checkpoint)")

    if candidates:
        for i in range(0, len(candidates), LLM_BATCH_SIZE):
            batch = candidates[i : i + LLM_BATCH_SIZE]
            batch_num = i // LLM_BATCH_SIZE + 1
            total_batches = (len(candidates) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
            logger.info(f"  Type correction batch {batch_num}/{total_batches}")
            results = _llm_classify_batch(batch)
            for r in results:
                if not isinstance(r, dict):
                    continue
                try:
                    idx = int(r.get("index", 0)) - 1
                except (ValueError, TypeError):
                    continue
                if 0 <= idx < len(batch):
                    e = batch[idx]
                    new_type = str(r.get("type", "")).upper().strip()
                    if new_type in CDM_TYPES and new_type != e["type"]:
                        checkpoint[e["id"]] = {
                            "old_type": e["type"],
                            "new_type": new_type,
                            "confidence": float(r.get("confidence", 0.0)),
                            "name": e["name"],
                        }
            time.sleep(0.5)

            # Periodic checkpoint every 50 batches
            if checkpoint_path and batch_num % 50 == 0:
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                with open(checkpoint_path, "w", encoding="utf-8") as f:
                    json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                logger.info(f"  Periodic checkpoint saved: {len(checkpoint)} corrections (batch {batch_num}/{total_batches})")

        if checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
            logger.info(f"  Checkpoint saved: {checkpoint_path}")

    # Apply corrections (handle int/string key mismatch from JSON checkpoints)
    # When checkpoint is built in-memory, keys are ints; when loaded from JSON, keys are strings.
    # Normalize all keys to strings for consistent lookup.
    checkpoint = {str(k): v for k, v in checkpoint.items()}
    corrections_applied = 0
    for e in entities:
        eid_key = str(e["id"])
        if eid_key in checkpoint:
            c = checkpoint[eid_key]
            old_type = e["type"]
            e["type"] = c["new_type"]
            corrections_applied += 1
            if apply and conn:
                conn.execute(
                    "UPDATE entities SET entity_type = ? WHERE id = ?",
                    (c["new_type"], e["id"]),
                )
    if apply and conn:
        conn.commit()

    logger.info(f"  Corrections applied: {corrections_applied}")
    return entities, checkpoint


# ── Pass 2: Semantic Deduplication (bge-m3) ────────────────

def pass2_semantic_dedup(
    entities: List[dict],
    checkpoint_path: Optional[Path] = None,
    apply: bool = True,
    conn: Optional[sqlite3.Connection] = None,
    threshold: float = DEDUP_THRESHOLD,
) -> Tuple[List[dict], dict]:
    """Pass 2: Semantic deduplication using bge-m3 embeddings.

    Merges entities with cosine similarity >= threshold within the same CDM type.
    The canonical (kept) entity is the one with ontology grounding or higher paper_count.
    Returns (entities, remap_dict) where remap maps duplicate_id → canonical_id.
    """
    logger.info("=" * 60)
    logger.info("PASS 2: Semantic Deduplication (bge-m3)")
    logger.info("=" * 60)

    if checkpoint_path and checkpoint_path.exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            checkpoint = json.load(f)
        raw_remap = checkpoint.get("remap", {})
        # Convert string keys/values to int (JSON serializes to strings)
        remap: Dict[int, int] = {}
        for k, v in raw_remap.items():
            try:
                remap[int(k)] = int(v)
            except (ValueError, TypeError):
                continue
        completed_types = set(checkpoint.get("completed_types", []))
        logger.info(f"  Loaded checkpoint: {len(remap)} remappings, {len(completed_types)} types done")
    else:
        remap: Dict[int, int] = {}  # duplicate_id → canonical_id
        completed_types: set = set()

    # Group by type
    by_type: Dict[str, List[dict]] = defaultdict(list)
    for e in entities:
        by_type[e["type"]].append(e)

    # Embed and compare within each type (skip completed types)
    for etype, type_entities in by_type.items():
        if len(type_entities) < 2 or etype in completed_types:
            continue
        logger.info(f"  {etype}: {len(type_entities)} entities")

        # Batch embed all names
        names = [e["name"] for e in type_entities]
        embeddings: Dict[str, np.ndarray] = {}
        for i in range(0, len(names), EMBED_BATCH_SIZE):
            batch_names = names[i : i + EMBED_BATCH_SIZE]
            try:
                embs = _embed_batch(batch_names)
                for j, name in enumerate(batch_names):
                    embeddings[name] = embs[j]
            except Exception as ex:
                logger.warning(f"  Embed batch failed: {ex}")
                continue
            time.sleep(0.1)
        logger.info(f"    Embedded {len(embeddings)} names")

        # Pairwise comparison
        merge_pairs = 0
        for i in range(len(type_entities)):
            ei = type_entities[i]
            ei_emb = embeddings.get(ei["name"])
            if ei_emb is None:
                continue
            for j in range(i + 1, len(type_entities)):
                ej = type_entities[j]
                ej_emb = embeddings.get(ej["name"])
                if ej_emb is None:
                    continue
                score = _cosine_sim(ei_emb, ej_emb)
                if score >= threshold:
                    # Pick canonical: prefer grounded, then higher paper_count
                    ei_grounded = bool(ei["ontology_id"])
                    ej_grounded = bool(ej["ontology_id"])
                    if ei_grounded and not ej_grounded:
                        canonical, duplicate = ei, ej
                    elif ej_grounded and not ei_grounded:
                        canonical, duplicate = ej, ei
                    elif ei["paper_count"] >= ej["paper_count"]:
                        canonical, duplicate = ei, ej
                    else:
                        canonical, duplicate = ej, ei

                    # Chain remapping
                    old_canon = remap.get(canonical["id"], canonical["id"])
                    remap[duplicate["id"]] = old_canon
                    merge_pairs += 1

        if merge_pairs > 0:
            logger.info(f"    Merge pairs: {merge_pairs}")

        # Checkpoint after each type
        completed_types.add(etype)
        if checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_data = {
                "remap": {str(k): str(v) for k, v in remap.items()},
                "completed_types": sorted(completed_types),
            }
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
            logger.info(f"  Checkpoint saved: {checkpoint_path}")

    # Resolve remapping chains
    def resolve(eid: int) -> int:
        seen = set()
        while eid in remap and eid not in seen:
            seen.add(eid)
            eid = remap[eid]
        return eid

    final_remap = {eid: resolve(eid) for eid in remap}

    # Apply: update relationships to point to canonical entities
    merged_count = 0
    if apply and conn and final_remap:
        for dup_id, canon_id in final_remap.items():
            # Update relationships: source_id and target_id
            conn.execute(
                "UPDATE relationships SET source_id = ? WHERE source_id = ?",
                (canon_id, dup_id),
            )
            conn.execute(
                "UPDATE relationships SET target_id = ? WHERE target_id = ?",
                (canon_id, dup_id),
            )
            # Merge paper_count and frequency into canonical
            conn.execute(
                "UPDATE entities SET paper_count = paper_count + "
                "(SELECT paper_count FROM entities WHERE id = ?), "
                "frequency = frequency + "
                "(SELECT frequency FROM entities WHERE id = ?) WHERE id = ?",
                (dup_id, dup_id, canon_id),
            )
            # Delete duplicate entity
            conn.execute("DELETE FROM entities WHERE id = ?", (dup_id,))
            merged_count += 1
        conn.commit()

    logger.info(f"  Merged: {merged_count} duplicates")

    # Remove merged entities from the list
    merged_ids = set(final_remap.keys())
    entities = [e for e in entities if e["id"] not in merged_ids]

    return entities, {str(k): str(v) for k, v in final_remap.items()}


# ── Pass 3: Noise Detection (LLM) ───────────────────────────

def _is_likely_noise(name: str) -> bool:
    """Quick heuristic pre-filter for obvious noise."""
    if not name or len(name) < 2:
        return True
    # Single short lowercase word
    if re.match(r"^[a-z]{1,4}$", name):
        return True
    # Snake_case or kebab-case artifacts
    if re.match(r"^[a-z0-9_-]+$", name) and "-" in name and len(name) <= 12:
        return True
    # Generic non-biomedical words
    generic = {
        "taxa", "species", "reads", "negative", "research", "treatment",
        "sample", "samples", "data", "analysis", "method", "methods",
        "study", "studies", "results", "control", "group", "groups",
        "patient", "patients", "subject", "subjects", "positive", "normal",
    }
    if name.lower().strip() in generic:
        return True
    return False


def _llm_noise_batch(batch: List[tuple]) -> List[dict]:
    """Ask LLM to detect extraction noise — ALL entities, no pre-filter."""
    lines = []
    for i, (eid, name, etype) in enumerate(batch):
        lines.append(f'{i+1}. "{name}" (type: {etype})')
    entities_str = "\n".join(lines)
    prompt = (
        "You are a biomedical knowledge-graph curation expert.\n"
        "For each entity, decide if it is a REAL biomedical term or NOISE.\n\n"
        "REAL biomedical terms are specific, named entities that belong to one of these categories:\n"
        "  ORGANISM (e.g. 'Bacteroides fragilis', 'E. coli', 'Lactobacillus')\n"
        "  CHEMICAL (e.g. 'butyrate', 'acetate', 'lipopolysaccharide', 'glucose')\n"
        "  DISEASE (e.g. 'inflammatory bowel disease', 'colitis', 'diabetes')\n"
        "  PROTEIN (e.g. 'IL-6', 'TNF-alpha', 'immunoglobulin A')\n"
        "  DNA_RNA (e.g. '16S rRNA', 'V4 region', 'shRNA')\n"
        "  CELL_TYPE (e.g. 'T cell', 'macrophage', 'epithelial cell')\n"
        "  GENOMICS (e.g. 'alpha diversity', 'metagenomics', 'operational taxonomic unit')\n"
        "  PATHWAY (e.g. 'NF-kB pathway', 'glycolysis', 'TCA cycle')\n"
        "  LAB_METHOD (e.g. 'PCR', 'mass spectrometry', '16S sequencing')\n"
        "  DATA_ANALYSIS (e.g. 'PERMANOVA', 'ANOVA', 'principal component analysis')\n"
        "  SAMPLE_METHOD (e.g. 'fecal swab', 'stool sample', 'biopsy')\n"
        "  CLINICAL (e.g. 'remission', 'biomarker', 'written informed consent')\n"
        "  EXPERIMENTAL_METHOD (e.g. 'randomized controlled trial', 'gavage')\n"
        "  STUDY_DESIGN (e.g. 'cross-sectional study', 'longitudinal cohort')\n\n"
        "NOISE (is_noise=true) means GARBAGE/ARTIFACTS that should be DELETED:\n"
        "  1. Publication metadata: 'ARTICLE', 'ORIGINAL ARTICLE', 'ARTICLE INFO', 'SUPPLEMENTARY', 'research article'\n"
        "  2. Citation strings: 'BMC Bioinformatics 2017;18:247', '1997;10:33-38'\n"
        "  3. Sentence fragments: 'Demographi c and clinical character istics of individu als with'\n"
        "  4. Spaced-out letter sequences: 'O R I G I N A L A R T I C L E', 'R T I C L E I N F O'\n"
        "  5. OCR breakage: 'Bioinforma tics', 'Demographi c' (words split by PDF extraction errors)\n"
        "  6. Statistical notation dumps: '***P < 0.001; **P < 0.01; *P < 0.05'\n"
        "  7. Dietary/measurement values: '1004 kJ 6 g fat 20 g protein'\n"
        "  8. URLs/DOIs: 'https://doi.org/10.1093/...'\n"
        "  9. Truncated words: 'tion', 'ated', 'tive', 'bio', 'se', 'li', 'ma'\n"
        "  10. Author/person names: 'Gordon JI', 'Holmes SP', 'DeSantis'\n"
        "  11. Journal/publisher names: 'Nature', 'Science', 'Cell Press'\n"
        "  12. Company/supplier names: 'Qiagen', 'Illumina', 'Sigma-Aldrich'\n"
        "  13. Geographic locations: 'China', 'Europe', 'Africa'\n"
        "  14. Lab reagents/buffers used as entity names: 'PBS', 'DMSO' (when typed as a method)\n"
        "  15. Non-biomedical English words: 'blue', 'red', 'all', 'final'\n\n"
        "GENERIC (is_real_term=false, is_noise=false) means a vague/abstract word that is NOT garbage but too\n"
        "  unspecific to be a useful knowledge-graph node. Example: 'microbiome', 'diversity', 'bacteria',\n"
        "  'composition', 'Gut', 'age', 'cell', 'intestinal', 'taxa'. These are kept but de-prioritized.\n\n"
        "CRITICAL RULES:\n"
        "  A. Type mismatch is NOT noise. If a term IS a valid biomedical entity but has the wrong CDM type\n"
        "     (e.g. 'Erysipelotrichaceae' typed DNA_RNA instead of ORGANISM), mark is_real_term=true,\n"
        "     is_noise=false. Type correction is handled in a separate pass.\n"
        "  B. Named tools, databases, and metrics ARE real terms. Keep these as is_real_term=true:\n"
        "     'KEGG', 'PICRUSt', 'USEARCH', 'RDP', 'Shannon index', 'AUC', 'PERMANOVA', 'ANOSIM',\n"
        "     'Spearman correlation', 'PCoA', 'NMDS', 'LEfSe', 'MaAsLin', 'QIIME'.\n"
        "  C. Clinical terms ARE real. Keep these as is_real_term=true:\n"
        "     'placebo', 'constipation', 'sepsis', 'insulin resistance', 'gut dysbiosis', 'remission',\n"
        "     'confounders', 'biomarker', 'breast milk', 'prebiotics', 'probiotics'.\n"
        "  D. Common proteins/chemicals ARE real: 'mucin', 'lactic acid', 'butyrate', 'acetate'.\n"
        "  E. When uncertain, lean towards is_real_term=true, is_noise=false.\n\n"
        "Most entities in this list ARE real biomedical terms — only flag garbage/artifacts as is_noise=true.\n\n"
        f"Entities:\n{entities_str}\n\n"
        'Return a JSON array: [{"index": 1, "is_real_term": true, "is_noise": false, "reason": "..."}]'
    )
    raw = _call_llm(prompt)
    if not raw:
        return []
    return _parse_json_array(raw)


def _delete_noise_entities(conn: sqlite3.Connection, noise_ids: List[int]) -> dict:
    """Physically delete noise entities and all dependent rows from the DB.

    Cascade: edge_evidence → relationships → entity_project_mentions → entities.
    Returns counts of deleted rows per table.
    """
    if not noise_ids:
        return {"entities": 0, "relationships": 0, "edge_evidence": 0, "entity_project_mentions": 0}

    placeholders = ",".join("?" * len(noise_ids))

    # 1. Find relationship IDs that reference noise entities
    rel_ids = [
        r[0] for r in conn.execute(
            f"SELECT id FROM relationships "
            f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
            noise_ids + noise_ids,
        ).fetchall()
    ]

    # 2. Delete edge_evidence for those relationships
    ev_count = 0
    if rel_ids:
        ev_placeholders = ",".join("?" * len(rel_ids))
        ev_count = conn.execute(
            f"DELETE FROM edge_evidence WHERE relationship_id IN ({ev_placeholders})",
            rel_ids,
        ).rowcount

    # 3. Delete relationships referencing noise entities
    rel_count = conn.execute(
        f"DELETE FROM relationships "
        f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
        noise_ids + noise_ids,
    ).rowcount

    # 4. Delete entity_project_mentions for noise entities
    epm_count = conn.execute(
        f"DELETE FROM entity_project_mentions WHERE entity_id IN ({placeholders})",
        noise_ids,
    ).rowcount

    # 5. Delete noise entities
    ent_count = conn.execute(
        f"DELETE FROM entities WHERE id IN ({placeholders})",
        noise_ids,
    ).rowcount

    conn.commit()
    return {
        "entities": ent_count,
        "relationships": rel_count,
        "edge_evidence": ev_count,
        "entity_project_mentions": epm_count,
    }


def pass3_noise_detection(
    entities: List[dict],
    checkpoint_path: Optional[Path] = None,
    apply: bool = True,
    conn: Optional[sqlite3.Connection] = None,
    delete: bool = False,
) -> Tuple[List[dict], dict]:
    """Pass 3: LLM-based noise detection — evaluates ALL entities.

    Sends every entity to the LLM for noise review (no heuristic pre-filter).
    Stores ALL verdicts in checkpoint (real + noise) for resume support.
    Flagged entities get confidence_score set to 0.0.
    If delete=True, noise entities are physically removed from the DB
    (entities, relationships, edge_evidence, entity_project_mentions).

    Returns (entities, noise_dict) where noise_dict maps entity_id → noise info.
    """
    logger.info("=" * 60)
    logger.info("PASS 3: Noise Detection (LLM) — ALL entities")
    logger.info("=" * 60)

    if checkpoint_path and checkpoint_path.exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            checkpoint = json.load(f)
        logger.info(f"  Loaded checkpoint: {len(checkpoint)} entities evaluated")
    else:
        checkpoint = {}

    # Skip entities already in checkpoint (resume support)
    processed_ids = set()
    for k in checkpoint.keys():
        try:
            processed_ids.add(int(k))
        except (ValueError, TypeError):
            pass

    all_to_eval = [
        (e["id"], e["name"], e["type"])
        for e in entities
        if e["id"] not in processed_ids
    ]
    logger.info(f"  Entities to evaluate: {len(all_to_eval)} ({len(processed_ids)} already processed)")

    for i in range(0, len(all_to_eval), LLM_BATCH_SIZE):
        batch = all_to_eval[i : i + LLM_BATCH_SIZE]
        batch_num = i // LLM_BATCH_SIZE + 1
        total_batches = (len(all_to_eval) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
        logger.info(f"  Noise detection batch {batch_num}/{total_batches}")
        results = _llm_noise_batch(batch)
        for r in results:
            if not isinstance(r, dict):
                continue
            try:
                idx = int(r.get("index", 0)) - 1
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(batch):
                eid, name, etype = batch[idx]
                is_noise = bool(r.get("is_noise", False))
                is_real = bool(r.get("is_real_term", True))
                # Store ALL verdicts (not just noise) for resume support
                checkpoint[eid] = {
                    "name": name,
                    "type": etype,
                    "is_noise": is_noise,
                    "is_real_term": is_real,
                    "reason": r.get("reason", ""),
                }
        time.sleep(0.5)

        # Periodic checkpoint every 50 batches
        if checkpoint_path and batch_num % 50 == 0:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
            logger.info(f"  Periodic checkpoint saved: {len(checkpoint)} evaluated (batch {batch_num}/{total_batches})")

    if checkpoint_path:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        logger.info(f"  Checkpoint saved: {checkpoint_path}")

    # Entities to DELETE: only those explicitly flagged is_noise=true (garbage/artifacts)
    noise_ids = [
        int(eid) for eid, info in checkpoint.items()
        if isinstance(info, dict) and info.get("is_noise")
    ]
    # Entities to DE-PRIORITIZE: is_real_term=false but NOT garbage (generic words)
    generic_ids = [
        int(eid) for eid, info in checkpoint.items()
        if isinstance(info, dict)
        and not info.get("is_real_term", True)
        and not info.get("is_noise")
    ]
    logger.info(f"  Total evaluated: {len(checkpoint)}")
    logger.info(f"  Noise (to delete): {len(noise_ids)}")
    logger.info(f"  Generic (confidence→0, kept): {len(generic_ids)}")

    # Apply: zero out confidence for BOTH noise and generic entities
    zero_ids = noise_ids + generic_ids
    noise_applied = 0
    if apply and conn:
        for eid in zero_ids:
            conn.execute(
                "UPDATE entities SET confidence_score = 0.0 WHERE id = ?",
                (eid,),
            )
            noise_applied += 1
        conn.commit()
    logger.info(f"  Confidence zeroed: {noise_applied}")

    # Delete: physically remove ONLY is_noise entities from DB (not generic words)
    if delete and conn and noise_ids:
        deleted = _delete_noise_entities(conn, noise_ids)
        logger.info(f"  Deleted: {deleted['entities']} entities, "
                     f"{deleted['relationships']} relationships, "
                     f"{deleted['edge_evidence']} edge_evidence, "
                     f"{deleted['entity_project_mentions']} entity_project_mentions")

    return entities, checkpoint


# ── Main orchestrator ───────────────────────────────────────

def run_entity_cleanup(
    db_path: Path,
    apply: bool = True,
    checkpoint_dir: Optional[Path] = None,
    llm_model: str = DEFAULT_LLM_MODEL,
    embed_model: str = DEFAULT_EMBED_MODEL,
    passes: str = "1,2,3",
    delete: bool = False,
) -> dict:
    """Run the 3-pass LLM entity cleanup pipeline.

    Args:
        db_path: Path to the SQLite DB.
        apply: If True, write changes to DB. If False, dry run.
        checkpoint_dir: Directory for JSON checkpoints (enables resume).
        llm_model: Ollama LLM model name for type correction + noise detection.
        embed_model: Ollama embedding model name for semantic dedup.
        passes: Comma-separated pass numbers to run (e.g. "1,3" for type+noise only).
        delete: If True, physically delete noise entities from DB (pass3 only).

    Returns:
        Dict with summary statistics for each pass.
    """
    global DEFAULT_LLM_MODEL, DEFAULT_EMBED_MODEL
    DEFAULT_LLM_MODEL = llm_model
    DEFAULT_EMBED_MODEL = embed_model

    pass_set = set(int(p.strip()) for p in passes.split(",") if p.strip())

    if checkpoint_dir is None:
        checkpoint_dir = db_path.parent / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"DB: {db_path}")
    logger.info(f"Apply: {apply}")
    logger.info(f"Passes: {sorted(pass_set)}")
    logger.info(f"LLM model: {llm_model}")
    logger.info(f"Embed model: {embed_model}")
    logger.info(f"Checkpoint dir: {checkpoint_dir}")

    conn = sqlite3.connect(str(db_path)) if apply else None

    # Load entities
    if conn:
        entities = _load_entities(conn)
    else:
        conn_ro = sqlite3.connect(str(db_path))
        entities = _load_entities(conn_ro)
        conn_ro.close()

    logger.info(f"Total entities loaded: {len(entities)}")
    type_dist = Counter(e["type"] for e in entities)
    for t, c in type_dist.most_common():
        logger.info(f"  {t:25s} {c:6d}")

    result = {"n_entities": len(entities), "type_distribution": dict(type_dist)}

    # Pass 1: Type correction
    if 1 in pass_set:
        ckpt = checkpoint_dir / "pass1_type_correction.json"
        entities, corrections = pass1_type_correction(entities, ckpt, apply, conn)
        result["pass1"] = {
            "n_candidates": len(corrections),
            "n_corrected": sum(1 for v in corrections.values() if v.get("new_type") != v.get("old_type")),
            "corrections": corrections,
        }

    # Pass 2: Semantic dedup
    if 2 in pass_set:
        ckpt = checkpoint_dir / "pass2_dedup.json"
        entities, remap = pass2_semantic_dedup(entities, ckpt, apply, conn)
        result["pass2"] = {
            "n_merged": len(remap),
            "remap": remap,
        }

    # Pass 3: Noise detection (ALL entities — no heuristic pre-filter)
    if 3 in pass_set:
        ckpt = checkpoint_dir / "pass3_noise_full.json"
        entities, noise = pass3_noise_detection(entities, ckpt, apply, conn, delete=delete)
        noise_count = sum(
            1 for v in noise.values()
            if isinstance(v, dict) and v.get("is_noise")
        )
        generic_count = sum(
            1 for v in noise.values()
            if isinstance(v, dict)
            and not v.get("is_real_term", True)
            and not v.get("is_noise")
        )
        result["pass3"] = {
            "n_evaluated": len(noise),
            "n_noise": noise_count,
            "n_generic": generic_count,
            "noise": noise,
        }

    if conn:
        conn.close()

    # Final stats
    logger.info(f"\nEntity cleanup complete. Final entity count: {len(entities)}")
    return result


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = argparse.ArgumentParser(description="LLM-based entity cleanup (type correction + dedup + noise)")
    parser.add_argument("--db", type=Path, required=True, help="Path to SQLite DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB (default: dry run)")
    parser.add_argument("--checkpoint-dir", type=Path, default=None, help="Directory for checkpoints")
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help=f"Ollama LLM model (default: {DEFAULT_LLM_MODEL})")
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL, help=f"Ollama embedding model (default: {DEFAULT_EMBED_MODEL})")
    parser.add_argument("--passes", default="1,2,3", help="Comma-separated pass numbers (default: 1,2,3)")
    parser.add_argument("--delete", action="store_true", help="Physically delete noise entities from DB (pass3 only)")
    args = parser.parse_args()

    result = run_entity_cleanup(
        db_path=args.db,
        apply=args.apply,
        checkpoint_dir=args.checkpoint_dir,
        llm_model=args.llm_model,
        embed_model=args.embed_model,
        passes=args.passes,
        delete=args.delete,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("Entity Cleanup Summary")
    print("=" * 60)
    print(f"  Total entities: {result['n_entities']}")
    if "pass1" in result:
        print(f"  Pass 1 (type correction): {result['pass1']['n_corrected']} corrected")
    if "pass2" in result:
        print(f"  Pass 2 (semantic dedup): {result['pass2']['n_merged']} merged")
    if "pass3" in result:
        print(f"  Pass 3 (noise detection): {result['pass3']['n_noise']} flagged / {result['pass3']['n_evaluated']} evaluated")
        if args.delete:
            print(f"    (noise entities physically deleted from DB)")


if __name__ == "__main__":
    main()
