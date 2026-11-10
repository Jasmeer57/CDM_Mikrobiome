"""BioLORD-2023 embedding-based entity matching for KG and ontology.

Replaces the difflib SequenceMatcher fuzzy tier (Tier 4) in rebuild_relations.py
with semantic similarity via BioLORD-2023 sentence embeddings.

Uses:
  - BioLORD-2023 (FremyCompany/BioLORD-2023) for biomedical entity encoding
  - Cosine similarity for semantic matching
  - Per-type embedding caches to avoid recomputation

The model is loaded from HuggingFace cache (~/.cache/huggingface/hub/).
Falls back gracefully if sentence-transformers is not installed.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

import numpy as np

from ..config import REPO_ROOT, CDM_OUTPUT_DIR

logger = logging.getLogger(__name__)

DB_PATH = CDM_OUTPUT_DIR / "microbiome_cdm.db"
CACHE_DIR = CDM_OUTPUT_DIR / "embeddings"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MODEL_NAME = "FremyCompany/BioLORD-2023"
DEFAULT_THRESHOLD = 0.85
BATCH_SIZE = 512

_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer

    _AVAILABLE = True
except ImportError:
    logger.warning("sentence-transformers not installed; BioLORD matching unavailable")


def _model():
    """Lazy-load the BioLORD-2023 model (singleton)."""
    if not _AVAILABLE:
        raise ImportError("sentence-transformers required for BioLORD matching")
    return SentenceTransformer(MODEL_NAME)


def encode_entities(db_path: Path = DB_PATH, force: bool = False) -> dict:
    """Encode all DB entities with BioLORD-2023, per entity_type.

    Returns:
        dict: entity_type -> (embeddings np.ndarray [N, D], entity_ids list[int], terms list[str])

    Caches to CACHE_DIR/{entity_type}.npz so re-runs are instant.
    """
    if not _AVAILABLE:
        raise ImportError("sentence-transformers required")

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("SELECT id, term, entity_type FROM entities ORDER BY id")
    rows = c.fetchall()
    conn.close()

    from collections import defaultdict

    by_type = defaultdict(list)
    for eid, term, etype in rows:
        by_type[etype].append((eid, term))

    model = _model()
    results = {}

    for etype, items in sorted(by_type.items()):
        cache_file = CACHE_DIR / f"biolord_{etype}.npz"
        if cache_file.exists() and not force:
            data = np.load(cache_file, allow_pickle=True)
            if len(data["ids"]) == len(items):
                results[etype] = (data["embeddings"], list(data["ids"]), list(data["terms"]))
                logger.info(f"  {etype}: {len(items)} entities (cached)")
                continue

        terms = [t for _, t in items]
        ids = [eid for eid, _ in items]

        t0 = time.time()
        embs = model.encode(
            terms,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        elapsed = time.time() - t0
        logger.info(f"  {etype}: {len(terms)} entities encoded in {elapsed:.1f}s")

        np.savez(cache_file, embeddings=embs, ids=np.array(ids), terms=np.array(terms, dtype=object))
        results[etype] = (embs, ids, terms)

    return results


def encode_query(text: str) -> np.ndarray:
    """Encode a single query entity text with BioLORD-2023."""
    model = _model()
    emb = model.encode([text], convert_to_numpy=True, normalize_embeddings=True)
    return emb[0]


def encode_queries(texts: list[str]) -> np.ndarray:
    """Encode a batch of query entity texts."""
    model = _model()
    return model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )


def match_entity_biolord(
    text: str,
    entity_type: str,
    embeddings_cache: dict,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[int | None, float]:
    """Match a single entity text against DB entities of the same type.

    Returns:
        (entity_id, similarity_score) or (None, 0.0) if no match above threshold.
    """
    if entity_type not in embeddings_cache:
        return None, 0.0

    embs, ids, terms = embeddings_cache[entity_type]
    if len(ids) == 0:
        return None, 0.0

    q = encode_query(text)
    sims = embs @ q

    best_idx = int(np.argmax(sims))
    best_sim = float(sims[best_idx])

    if best_sim >= threshold:
        return ids[best_idx], best_sim
    return None, best_sim


def match_entities_biolord(
    queries: list[tuple[str, str]],
    embeddings_cache: dict,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[tuple[int | None, float]]:
    """Match a batch of (text, entity_type) queries against DB entities.

    More efficient than single calls because queries are encoded in one batch.

    Returns:
        List of (entity_id, similarity_score) per query.
    """
    texts = [q[0] for q in queries]
    types = [q[1] for q in queries]

    q_embs = encode_queries(texts)

    results = []
    for i, (text, etype) in enumerate(queries):
        if etype not in embeddings_cache:
            results.append((None, 0.0))
            continue

        embs, ids, terms = embeddings_cache[etype]
        if len(ids) == 0:
            results.append((None, 0.0))
            continue

        sims_row = embs @ q_embs[i]
        best_idx = int(np.argmax(sims_row))
        best_sim = float(sims_row[best_idx])

        if best_sim >= threshold:
            results.append((ids[best_idx], best_sim))
        else:
            results.append((None, best_sim))

    return results


def benchmark_matching(
    triples_csv: Path | None = None,
    db_path: Path = DB_PATH,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Run a full benchmark: compare difflib Tier 4 vs BioLORD-2023 on unmatched entities.

    Takes all validated triples, runs Tiers 1-3 (exact, exact-no-type, substring),
    then for entities still unmatched, compares:
      - Tier 4a: difflib SequenceMatcher ratio >= 0.90 (current approach)
      - Tier 4b: BioLORD-2023 cosine similarity >= threshold (new approach)

    Returns a dict with all stats.
    """
    import csv
    import difflib
    import re
    from collections import defaultdict

    def norm(t: str) -> str:
        return re.sub(r"\s+", " ", t.lower().strip())

    # Load DB entities
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("SELECT id, term, entity_type FROM entities")
    lookup = {}
    by_type = defaultdict(list)
    for eid, term, etype in c.fetchall():
        n = norm(term)
        lookup[(n, etype)] = eid
        by_type[etype].append((n, eid, term))
    conn.close()

    # Load triples
    if triples_csv is None:
        triples_csv = CDM_OUTPUT_DIR / "triples" / "validated" / "all_validated_triples.csv"

    with open(triples_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        triples = list(reader)

    # Collect all entity mentions
    mentions = []
    for t in triples:
        mentions.append((t["subject"], t["subject_type"]))
        mentions.append((t["object"], t["object_type"]))

    total = len(mentions)
    t1 = t2 = t3 = 0
    t4_difflib = 0
    t4_biolord = 0
    unmatched_after_t3 = []

    for text, etype in mentions:
        n = norm(text)
        if not n or len(n) < 2:
            continue

        if (n, etype) in lookup:
            t1 += 1
            continue

        found = False
        for k in lookup:
            if k[0] == n:
                t2 += 1
                found = True
                break
        if found:
            continue

        candidates = by_type.get(etype, [])
        found = False
        for cn, eid, cterm in candidates:
            if n in cn or cn in n:
                if len(n) > 3 and len(cn) > 3:
                    t3 += 1
                    found = True
                    break
        if found:
            continue

        unmatched_after_t3.append((text, etype, n))

    # Tier 4a: difflib
    for text, etype, n in unmatched_after_t3:
        candidates = by_type.get(etype, [])
        best_ratio = 0.0
        for cn, eid, cterm in candidates:
            ratio = difflib.SequenceMatcher(None, n, cn).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
        if best_ratio >= 0.90:
            t4_difflib += 1

    # Tier 4b: BioLORD-2023
    print(f"Encoding {len(unmatched_after_t3)} unmatched entities with BioLORD-2023...")
    embeddings_cache = encode_entities(db_path)

    # Batch encode all unmatched queries
    query_texts = [text for text, _, _ in unmatched_after_t3]
    query_types = [etype for _, etype, _ in unmatched_after_t3]

    if query_texts:
        q_embs = encode_queries(query_texts)
        for i, (text, etype, n) in enumerate(unmatched_after_t3):
            if etype not in embeddings_cache:
                continue
            embs, ids, terms = embeddings_cache[etype]
            if len(ids) == 0:
                continue
            sims = embs @ q_embs[i]
            best_sim = float(np.max(sims))
            if best_sim >= threshold:
                t4_biolord += 1

    matched_t3 = t1 + t2 + t3
    matched_difflib = matched_t3 + t4_difflib
    matched_biolord = matched_t3 + t4_biolord

    stats = {
        "total_mentions": total,
        "tier1_exact_type": t1,
        "tier2_exact_no_type": t2,
        "tier3_substring": t3,
        "tier4_difflib": t4_difflib,
        "tier4_biolord": t4_biolord,
        "matched_tiers_1_3": matched_t3,
        "matched_with_difflib": matched_difflib,
        "matched_with_biolord": matched_biolord,
        "match_rate_difflib": matched_difflib / total * 100,
        "match_rate_biolord": matched_biolord / total * 100,
        "unmatched_after_t3": len(unmatched_after_t3),
        "threshold_biolord": threshold,
    }

    print("\n" + "=" * 60)
    print("BioLORD-2023 vs difflib Benchmark")
    print("=" * 60)
    print(f"Total entity mentions:     {total}")
    print(f"Tier 1 (exact+type):       {t1:5d} ({t1/total*100:.2f}%)")
    print(f"Tier 2 (exact no-type):    {t2:5d} ({t2/total*100:.2f}%)")
    print(f"Tier 3 (substring):        {t3:5d} ({t3/total*100:.2f}%)")
    print(f"  Matched (Tiers 1-3):     {matched_t3:5d} ({matched_t3/total*100:.2f}%)")
    print(f"  Unmatched after T3:      {len(unmatched_after_t3):5d}")
    print(f"Tier 4a difflib ≥0.90:     {t4_difflib:5d}")
    print(f"Tier 4b BioLORD ≥{threshold}:  {t4_biolord:5d}")
    print(f"  Total matched (difflib): {matched_difflib:5d} ({stats['match_rate_difflib']:.2f}%)")
    print(f"  Total matched (BioLORD):  {matched_biolord:5d} ({stats['match_rate_biolord']:.2f}%)")
    print(f"  Δ BioLORD vs difflib:     {matched_biolord - matched_difflib:+d}")

    return stats


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="BioLORD-2023 entity matching benchmark")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Cosine similarity threshold")
    parser.add_argument("--encode-only", action="store_true", help="Just encode DB entities and cache")
    parser.add_argument("--force", action="store_true", help="Force re-encode even if cache exists")
    args = parser.parse_args()

    if args.encode_only:
        print("Encoding all DB entities with BioLORD-2023...")
        cache = encode_entities(force=args.force)
        total = sum(len(ids) for _, ids, _ in cache.values())
        print(f"Done. {total} entities encoded across {len(cache)} types.")
    else:
        stats = benchmark_matching(threshold=args.threshold)
        print(f"\nStats: {json.dumps(stats, indent=2)}")
