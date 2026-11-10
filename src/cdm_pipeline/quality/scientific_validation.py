"""Scientific validation pass — checks every entity for biomedical validity.

A strict LLM-based pass that re-evaluates ALL entities in the KG to ensure
they are genuine biomedical/scientific terms. Specifically targets:

  - Author names ("Braegger C", "Bossley C", "Oda K", "Quig D")
  - Geographic names ("Tokyo", "Japan", "China", "Netherlands")
  - Truncated words ("Hþ", "tion", "ated", "tive")
  - 2-letter fragments ("RH", "RR", "UF", "UH", "YW", "VL")
  - Journal/publisher names ("Nature", "Science", "Cell Press")
  - Company names ("Qiagen", "Illumina", "Sigma-Aldrich")
  - Non-biomedical English words
  - OCR artifacts and citation strings

Uses Qwen 3.5:9b via Ollama. Checkpoints every 50 batches for resume.
Deletes noise entities with full cascade (edge_evidence → relationships →
entity_project_mentions → entities).

Usage:
    python -m cdm_pipeline.quality.scientific_validation \
        --db microbiome_cdm.db --apply --delete \
        --checkpoint-dir checkpoints/
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ── Ollama defaults ──
DEFAULT_LLM_MODEL = os.environ.get("ENTITY_CLEANUP_MODEL", "qwen3.5:9b")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "8192"))
MAX_RETRIES = 3
TIMEOUT = 600
LLM_BATCH_SIZE = 30
CHECKPOINT_EVERY = 50

NO_THINKING = (
    "You are a biomedical knowledge-graph curation expert. "
    "Do not show your reasoning. Return ONLY the JSON array requested."
)


# ── Ollama helpers ──────────────────────────────────────────

def _ensure_ollama_host() -> str:
    raw = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if raw and not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"http://{raw}"
        os.environ["OLLAMA_HOST"] = raw
    return raw


def _call_llm(prompt: str, model: str = DEFAULT_LLM_MODEL) -> Optional[str]:
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


def _parse_json_array(raw: str) -> list:
    if not raw:
        return []
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = raw.strip().rstrip("`")
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

def _load_entities(conn: sqlite3.Connection) -> List[dict]:
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, term, entity_type, UMLS_ID, OLS, Bioportal, NCBITaxon, "
        "paper_count, confidence_score FROM entities ORDER BY id"
    ).fetchall()
    entities = []
    for r in rows:
        eid, term, etype, umls, ols, bio, ncbi, pcount, conf = r
        entities.append({
            "id": eid,
            "name": term,
            "type": etype or "UNKNOWN",
            "paper_count": pcount or 0,
            "confidence": conf or 0.0,
        })
    return entities


def _delete_noise_entities(conn: sqlite3.Connection, noise_ids: List[int]) -> dict:
    if not noise_ids:
        return {"entities": 0, "relationships": 0, "edge_evidence": 0, "entity_project_mentions": 0}

    placeholders = ",".join("?" * len(noise_ids))

    # 1. Find relationship IDs referencing noise entities
    rel_ids = [
        r[0] for r in conn.execute(
            f"SELECT id FROM relationships "
            f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
            noise_ids + noise_ids,
        ).fetchall()
    ]

    # 2. Delete edge_evidence
    ev_count = 0
    if rel_ids:
        ev_ph = ",".join("?" * len(rel_ids))
        ev_count = conn.execute(
            f"DELETE FROM edge_evidence WHERE relationship_id IN ({ev_ph})",
            rel_ids,
        ).rowcount

    # 3. Delete relationships
    rel_count = conn.execute(
        f"DELETE FROM relationships "
        f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
        noise_ids + noise_ids,
    ).rowcount

    # 4. Delete entity_project_mentions
    epm_count = conn.execute(
        f"DELETE FROM entity_project_mentions WHERE entity_id IN ({placeholders})",
        noise_ids,
    ).rowcount

    # 5. Delete entities
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


# ── Scientific validation prompt ────────────────────────────

def _llm_validate_batch(batch: List[Tuple[int, str, str, float]]) -> List[dict]:
    """Ask LLM to validate each entity as a genuine biomedical term."""
    lines = []
    for i, (eid, name, etype, conf) in enumerate(batch):
        lines.append(f'{i+1}. "{name}" (type: {etype}, conf: {conf:.2f})')
    entities_str = "\n".join(lines)

    prompt = (
        "You are a strict biomedical knowledge-graph curator.\n"
        "For each entity, decide if it is a GENUINE BIOMEDICAL/SCIENTIFIC term or FAKE/NOISE.\n\n"
        "GENUINE (is_scientific=true) means a specific, named entity used in biomedical research:\n"
        "  - Organisms: 'Bacteroides fragilis', 'E. coli', 'Lactobacillus', 'Firmicutes'\n"
        "  - Chemicals: 'butyrate', 'acetate', 'lipopolysaccharide', 'glucose', 'mucin'\n"
        "  - Diseases: 'inflammatory bowel disease', 'colitis', 'diabetes', 'obesity', 'sepsis'\n"
        "  - Proteins: 'IL-6', 'TNF-alpha', 'immunoglobulin A', 'defensin'\n"
        "  - DNA/RNA: '16S rRNA', 'V4 region', 'shRNA', 'crRNA'\n"
        "  - Cell types: 'T cell', 'macrophage', 'epithelial cell', 'dendritic cell'\n"
        "  - Genomics: 'alpha diversity', 'metagenomics', 'operational taxonomic unit'\n"
        "  - Pathways: 'NF-kB pathway', 'glycolysis', 'TCA cycle', 'bile acid metabolism'\n"
        "  - Lab methods: 'PCR', 'mass spectrometry', '16S sequencing', 'flow cytometry'\n"
        "  - Data analysis: 'PERMANOVA', 'ANOVA', 'principal component analysis', 'Shannon index'\n"
        "  - Sample methods: 'fecal swab', 'stool sample', 'biopsy'\n"
        "  - Clinical: 'remission', 'biomarker', 'placebo', 'constipation', 'insulin resistance'\n"
        "  - Experimental: 'randomized controlled trial', 'gavage', 'faecal microbiota transplant'\n"
        "  - Study design: 'cross-sectional study', 'longitudinal cohort', 'meta-analysis'\n"
        "  - Named tools/databases: 'KEGG', 'PICRUSt', 'USEARCH', 'RDP', 'QIIME', 'LEfSe'\n"
        "  - Named metrics: 'AUC', 'PERMANOVA', 'ANOSIM', 'Spearman correlation', 'PCoA'\n\n"
        "FAKE/NOISE (is_scientific=false) means ANY of these — mark for DELETION:\n"
        "  1. AUTHOR NAMES: 'Braegger C', 'Bossley C', 'Oda K', 'Quig D', 'Gordon JI',\n"
        "     'Holmes SP', 'Costello EK', 'Li K', 'Yu K', 'Pan Y', 'Cox F', 'Abe F'\n"
        "     Pattern: FirstName + LastInitial, e.g. 'Smith J', 'Wang X', 'Zhang L'\n"
        "  2. GEOGRAPHIC NAMES: 'Tokyo', 'Japan', 'China', 'Europe', 'Africa', 'America',\n"
        "     'Spain', 'India', 'Netherlands', 'Korea', 'France', 'Germany', 'Sweden'\n"
        "  3. TRUNCATED WORDS: 'tion', 'ated', 'tive', 'bio', 'se', 'li', 'ma', 'di',\n"
        "     'dig', 'Hþ', 'Cβ' — words cut off by PDF extraction or tokenization\n"
        "  4. 2-LETTER FRAGMENTS: 'RH', 'RR', 'UF', 'UH', 'YW', 'VL', 'NW', 'SN',\n"
        "     'JW', 'EK', 'KC', 'ML', 'GB', 'KB', 'GI', 'BP' — random letter pairs\n"
        "     EXCEPTION: real abbreviations like 'IL', 'TN', 'Ig', 'NO', 'DNA', 'RNA',\n"
        "     'PCR', 'LPS', 'ROS', 'ATP', 'GTP', 'NAD', 'FAD', 'AMP', 'SCFA', 'GABA'\n"
        "  5. JOURNAL/PUBLISHER NAMES: 'Nature', 'Science', 'Cell Press', 'PLOS ONE',\n"
        "     'BMC', 'Lancet', 'BMJ', 'Springer', 'Wiley'\n"
        "  6. COMPANY/SUPPLIER NAMES: 'Qiagen', 'Illumina', 'Sigma-Aldrich', 'Roche',\n"
        "     'Beckman', 'Agilent', 'Thermo Fisher'\n"
        "  7. CITATION STRINGS: 'BMC Bioinformatics 2017;18:247', '1997;10:33-38'\n"
        "  8. OCR ARTIFACTS: 'Demographi c', 'Bioinforma tics' (words split by PDF errors)\n"
        "  9. SPACED-OUT LETTERS: 'O R I G I N A L A R T I C L E', 'R T I C L E I N F O'\n"
        "  10. STATISTICAL NOTATION DUMPS: '***P < 0.001; **P < 0.01'\n"
        "  11. MEASUREMENT VALUES: '1004 kJ 6 g fat 20 g protein'\n"
        "  12. URLs/DOIs: 'https://doi.org/10.1093/...'\n"
        "  13. NON-BIOMEDICAL ENGLISH: 'blue', 'red', 'all', 'final', 'stable',\n"
        "      'measure', 'functional', 'structural', 'soluble'\n"
        "  14. GENERIC VAGUE WORDS that are not specific entities:\n"
        "      'the', 'and', 'for', 'with', 'this', 'that', 'were', 'been'\n"
        "  15. KOREAN/NON-ENGLISH TEXT: any non-Latin script characters\n\n"
        "CRITICAL RULES:\n"
        "  A. Author name pattern 'LastName Initial' (e.g. 'Smith J', 'Oda K') is ALWAYS noise.\n"
        "     Even if the name belongs to a researcher, it is NOT a biomedical entity.\n"
        "  B. Geographic names are ALWAYS noise — they are not biomedical entities.\n"
        "  C. 2-letter fragments that are NOT known abbreviations (DNA, RNA, PCR, etc.)\n"
        "     are noise from tokenization errors.\n"
        "  D. When uncertain about a specific term, check: is this a NAMED, SPECIFIC\n"
        "     biomedical entity? If it's a generic English word, mark is_scientific=false.\n"
        "  E. Real biomedical abbreviations ARE scientific: 'IL-6', 'TNF-α', 'SCFA',\n"
        "     'LPS', 'IgA', 'TLR4', 'NF-κB', 'AMP', 'GABA', 'FOS', 'GOS'\n"
        "  F. Named methods/tools ARE scientific: 'PERMANOVA', 'PICRUSt', 'QIIME',\n"
        "     'USEARCH', 'RDP', 'KEGG', 'LEfSe', 'MaAsLin', 'AUC'\n"
        "  G. Clinical terms ARE scientific: 'placebo', 'constipation', 'sepsis',\n"
        "     'insulin resistance', 'remission', 'biomarker', 'breast milk'\n\n"
        f"Entities to validate:\n{entities_str}\n\n"
        'Return a JSON array: [{"index": 1, "is_scientific": true, "reason": "..."}]\n'
        'where is_scientific=false means DELETE this entity (it is fake/noise).'
    )
    raw = _call_llm(prompt)
    if not raw:
        return []
    return _parse_json_array(raw)


# ── Main validation pass ───────────────────────────────────

def run_scientific_validation(
    db_path: Path,
    checkpoint_path: Optional[Path] = None,
    apply: bool = True,
    delete: bool = False,
    llm_model: str = DEFAULT_LLM_MODEL,
) -> dict:
    """Run scientific validation on ALL entities.

    Re-evaluates every entity with a strict biomedical-only lens.
    Deletes entities that are not genuine biomedical terms.
    """
    global DEFAULT_LLM_MODEL
    DEFAULT_LLM_MODEL = llm_model

    logger.info("=" * 60)
    logger.info("SCIENTIFIC VALIDATION PASS")
    logger.info("=" * 60)
    logger.info(f"  DB: {db_path}")
    logger.info(f"  Apply: {apply}")
    logger.info(f"  Delete: {delete}")
    logger.info(f"  LLM model: {llm_model}")

    conn = sqlite3.connect(str(db_path)) if apply else None
    if not conn:
        conn_ro = sqlite3.connect(str(db_path))
        entities = _load_entities(conn_ro)
        conn_ro.close()
    else:
        entities = _load_entities(conn)

    logger.info(f"  Total entities: {len(entities)}")

    # Load checkpoint
    checkpoint: Dict[str, dict] = {}
    if checkpoint_path and checkpoint_path.exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            checkpoint = json.load(f)
        logger.info(f"  Loaded checkpoint: {len(checkpoint)} already validated")

    # Skip already-validated entities
    processed_ids = set()
    for k in checkpoint.keys():
        try:
            processed_ids.add(int(k))
        except (ValueError, TypeError):
            pass

    to_eval = [
        (e["id"], e["name"], e["type"], e["confidence"])
        for e in entities
        if e["id"] not in processed_ids
    ]
    logger.info(f"  Entities to validate: {len(to_eval)}")
    logger.info(f"  Already validated: {len(processed_ids)}")

    # Process in batches
    total_batches = (len(to_eval) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
    for i in range(0, len(to_eval), LLM_BATCH_SIZE):
        batch = to_eval[i : i + LLM_BATCH_SIZE]
        batch_num = i // LLM_BATCH_SIZE + 1
        logger.info(f"  Validation batch {batch_num}/{total_batches}")

        results = _llm_validate_batch(batch)
        for r in results:
            if not isinstance(r, dict):
                continue
            try:
                idx = int(r.get("index", 0)) - 1
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(batch):
                eid, name, etype, conf = batch[idx]
                is_scientific = bool(r.get("is_scientific", True))
                checkpoint[str(eid)] = {
                    "name": name,
                    "type": etype,
                    "is_scientific": is_scientific,
                    "reason": r.get("reason", ""),
                }
        time.sleep(0.5)

        # Periodic checkpoint
        if checkpoint_path and batch_num % CHECKPOINT_EVERY == 0:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
            logger.info(
                f"  Checkpoint saved: {len(checkpoint)} validated "
                f"(batch {batch_num}/{total_batches})"
            )

    # Final checkpoint save
    if checkpoint_path:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        logger.info(f"  Final checkpoint saved: {checkpoint_path}")

    # Collect noise IDs (is_scientific=false)
    noise_ids = [
        int(eid) for eid, info in checkpoint.items()
        if isinstance(info, dict) and not info.get("is_scientific", True)
    ]
    scientific_ids = [
        int(eid) for eid, info in checkpoint.items()
        if isinstance(info, dict) and info.get("is_scientific", True)
    ]

    logger.info(f"  Total validated: {len(checkpoint)}")
    logger.info(f"  Scientific (keep): {len(scientific_ids)}")
    logger.info(f"  Noise (delete): {len(noise_ids)}")

    # Print sample of noise entities
    if noise_ids:
        logger.info("  Sample noise entities to delete:")
        noise_sample = noise_ids[:30]
        for eid in noise_sample:
            info = checkpoint.get(str(eid), {})
            logger.info(
                f"    id={eid} '{info.get('name', '?')}' "
                f"type={info.get('type', '?')} reason={info.get('reason', '')}"
            )

    # Delete noise entities
    if delete and conn and noise_ids:
        deleted = _delete_noise_entities(conn, noise_ids)
        logger.info(
            f"  DELETED: {deleted['entities']} entities, "
            f"{deleted['relationships']} relationships, "
            f"{deleted['edge_evidence']} edge_evidence, "
            f"{deleted['entity_project_mentions']} entity_project_mentions"
        )

    if conn:
        conn.close()

    return {
        "total_validated": len(checkpoint),
        "scientific": len(scientific_ids),
        "noise": len(noise_ids),
        "deleted": deleted if (delete and conn and noise_ids) else None,
    }


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Scientific validation — check all entities for biomedical validity"
    )
    parser.add_argument("--db", type=Path, required=True, help="Path to SQLite DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument("--delete", action="store_true", help="Physically delete noise entities")
    parser.add_argument(
        "--checkpoint-dir", type=Path, default=None, help="Directory for checkpoints"
    )
    parser.add_argument(
        "--llm-model", default=DEFAULT_LLM_MODEL, help=f"Ollama LLM model (default: {DEFAULT_LLM_MODEL})"
    )
    args = parser.parse_args()

    checkpoint_dir = args.checkpoint_dir or args.db.parent / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "scientific_validation.json"

    result = run_scientific_validation(
        db_path=args.db,
        checkpoint_path=checkpoint_path,
        apply=args.apply,
        delete=args.delete,
        llm_model=args.llm_model,
    )

    print("\n" + "=" * 60)
    print("Scientific Validation Summary")
    print("=" * 60)
    print(f"  Total validated: {result['total_validated']}")
    print(f"  Scientific (keep): {result['scientific']}")
    print(f"  Noise (delete): {result['noise']}")
    if result.get("deleted"):
        d = result["deleted"]
        print(f"  Deleted: {d['entities']} entities, {d['relationships']} relationships, "
              f"{d['edge_evidence']} evidence")


if __name__ == "__main__":
    main()
