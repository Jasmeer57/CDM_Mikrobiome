#!/usr/bin/env python3
"""
Runs the (fixed) BioMistralDeduplicator from core/biomedical_deduplicator.py
against the full unified entity corpus, within each entity_type group.

The class itself does an unfiltered O(n^2) LLM call per candidate pair, which
is infeasible at corpus scale (ORGANISM alone has ~2700 entities -> ~3.65M
pairs). This runner precomputes embeddings ONCE per unique entity string and
does the embedding pre-filter as a single vectorized cosine-similarity matrix
(fast, all local), then only calls BioMistralDeduplicator's per-pair LLM
scoring on the pairs that survive the filter.

Usage:
    python scripts/run_biomedical_dedup.py --corpus <unified_entity_corpus.json> --output <merged_corpus.json> [--dry_run]
"""
import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--embedding_prefilter", type=float, default=0.70,
                   help="Cosine similarity floor before an LLM call is spent on a pair. "
                        "Was 0.78 (picked by eye); threshold_sweep.py against a 120-pair "
                        "hand-labeled gold sample (scripts/build_gold_dedup_sample.py) showed "
                        "0.78 silently drops 10/48 true duplicates before they ever reach the "
                        "LLM (21%% recall loss at the gate, invisible downstream - the LLM/guard "
                        "never even sees these pairs). 0.70 recovers 42/48 (87.5%%). The gate's "
                        "job is recall, not precision - the LLM + organism_merge_is_safe guard "
                        "downstream is what actually decides, so a wider gate costs more LLM "
                        "calls but not more bad merges.")
    p.add_argument("--fuzzy_prefilter", type=float, default=0.85,
                   help="rapidfuzz character-ratio floor - ORed with embedding_prefilter, either "
                        "signal clearing its bar is enough to spend an LLM call on the pair. "
                        "Catches typo/near-identical variants embeddings sometimes score "
                        "inconsistently (e.g. OCR-mangled genus names).")
    p.add_argument("--fuzzy_fast_merge_threshold", type=float, default=0.95,
                   help="Above this fuzzy ratio, merge directly without an LLM call - reserved "
                        "for near-identical strings (case/whitespace/single-typo variants), not "
                        "genus/species-type near-matches which still need the LLM's judgment.")
    p.add_argument("--biomistral_threshold", type=float, default=0.75)
    p.add_argument("--dry_run", action="store_true",
                   help="Only report how many LLM calls each type group would need, don't call the LLM.")
    return p.parse_args()


def main():
    args = parse_args()

    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    from core.llm_client import LLMClient
    from core.biomedical_deduplicator import BioMistralDeduplicator

    with open(args.corpus, "r", encoding="utf-8") as f:
        data = json.load(f)
    entities = data["entities"]

    by_type = defaultdict(list)
    for e in entities:
        by_type[e["entity_type"]].append(e)

    logger.info("Loading embedding model once...")
    encoder = SentenceTransformer("all-MiniLM-L6-v2")

    llm_client = LLMClient(model="qwen3.5:9b")
    dedup = BioMistralDeduplicator.__new__(BioMistralDeduplicator)  # skip __init__'s own model load
    dedup.llm_client = llm_client
    dedup.biomistral_model = "qwen3.5:9b"
    dedup.semantic_encoder = encoder

    # Checkpointing: the background shell running this dies whenever the machine
    # sleeps/reboots (observed repeatedly - not a bug in this script, just how
    # unattended background processes behave), and every prior restart redid the
    # ENTIRE run from scratch (ORGANISM alone is ~3300 LLM calls, hours). Persist
    # every decided pair immediately so a restart resumes instead of repeating.
    checkpoint_path = Path(args.output).with_suffix(".checkpoint.json")
    if checkpoint_path.exists():
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)
        resumed_count = sum(len(v["done_pairs"]) for v in checkpoint.values())
        logger.info(f"Resuming from checkpoint: {checkpoint_path} ({resumed_count} pairs already decided)")
    else:
        checkpoint = {}

    def save_checkpoint():
        tmp = checkpoint_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f)
        tmp.replace(checkpoint_path)  # atomic on the same filesystem - no half-written checkpoint on a crash

    all_groups = []
    total_llm_calls = 0
    t0 = time.time()

    from rapidfuzz import process as rf_process, fuzz as rf_fuzz
    import re

    # ORGANISM-specific guard: the LLM prompt explicitly says "Bacteroides vs
    # Bacteroides fragilis are NOT the same" but does not reliably follow that
    # under real load - observed merging 'Salmonella enterica' -> 'Salmonella'
    # (species into genus) and 'Salmonella Typhimurium' -> 'Salmonella' (serovar
    # into genus) at bio_score=0.90, both wrong. Rather than trust the LLM's
    # judgment here, hard-block any merge where the two names don't reduce to
    # the same set of real taxonomic words after stripping known-safe
    # qualifiers (sp./spp./genus/species/etc.) and single-letter genus
    # abbreviations ("A. muciniphila" vs "muciniphila" IS safe - same species,
    # genus just abbreviated/dropped). A genuine species/strain epithet added
    # on one side changes the *count* of real words, which this catches
    # regardless of what score the LLM assigned.
    SAFE_TAXONOMY_QUALIFIERS = {"sp", "spp", "ssp", "genus", "species", "strain",
                                 "isolate", "group", "complex", "sample", "samples"}

    def organism_core_tokens(name):
        # Keep alphanumeric tokens WHOLE (strain codes like "W55"/"R0011"/"CUL60" are
        # real specificity, not noise) - only a token that is a single bare LETTER
        # (no digits) is treated as a droppable genus abbreviation ("E." -> "e").
        # The previous version extracted letters only (`[a-zA-Z]+`), which turned
        # "W55" into "w" and "R0011" into "r" - indistinguishable from a genuine
        # single-letter genus abbreviation, so those strain-code merges wrongly
        # passed the equal-length branch (both sides looked like 2 "real" words).
        tokens = re.findall(r"[a-zA-Z0-9]+", name.lower())
        core = []
        for t in tokens:
            if t in SAFE_TAXONOMY_QUALIFIERS:
                continue
            if len(t) == 1 and t.isalpha():
                continue  # bare single letter = genus abbreviation, droppable
            core.append(t)
        return core

    def _tokens_match(core1, core2, token_fuzzy_threshold=85):
        remaining = list(core2)
        for t1 in core1:
            best = None
            for t2 in remaining:
                r = rf_fuzz.ratio(t1, t2)
                if r >= token_fuzzy_threshold and (best is None or r > best[1]):
                    best = (t2, r)
            if best is None:
                return False
            remaining.remove(best[0])
        return True

    def organism_merge_is_safe(name1, name2, token_fuzzy_threshold=85):
        core1, core2 = organism_core_tokens(name1), organism_core_tokens(name2)
        if len(core1) == len(core2):
            return _tokens_match(core1, core2, token_fuzzy_threshold)
        # Length differs by exactly 1: only safe if it's a dropped/abbreviated GENUS
        # ("E. coli" -> filtered to just ['coli'] vs "Escherichia coli" -> ['escherichia',
        # 'coli']) - the shorter side's lone token must match the LONGER side's LAST
        # (species-position) token. If it instead matches the FIRST (genus-position)
        # token, that's the unsafe direction - a bare genus name being matched against
        # genus+species, i.e. exactly the "Salmonella" / "Salmonella enterica" bug.
        if abs(len(core1) - len(core2)) != 1:
            return False
        shorter, longer = (core1, core2) if len(core1) < len(core2) else (core2, core1)
        if len(shorter) != 1 or len(longer) < 2:
            return False
        return rf_fuzz.ratio(shorter[0], longer[-1]) >= token_fuzzy_threshold

    fast_path_merges = 0

    for etype, ents in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        names = [e["entity"] for e in ents]
        n = len(names)
        logger.info(f"[{etype}] {n} entities, embedding + fuzzy matrix...")
        embeddings = encoder.encode(names, show_progress_bar=False)
        sim_matrix = cosine_similarity(embeddings)
        # rapidfuzz.process.cdist is a C-optimized full pairwise matrix - orders of
        # magnitude faster than a Python double loop with SequenceMatcher per pair,
        # which is what the original biomedical_deduplicator.py did (fine per-paper,
        # infeasible at corpus scale for the same reason the embedding loop was).
        fuzzy_matrix = rf_process.cdist(names, names, scorer=rf_fuzz.ratio) / 100.0

        candidate_pairs = []
        fast_path_pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                fuzzy_score = float(fuzzy_matrix[i][j])
                emb_score = float(sim_matrix[i][j])
                if fuzzy_score >= args.fuzzy_fast_merge_threshold:
                    fast_path_pairs.append((i, j, fuzzy_score))
                elif emb_score >= args.embedding_prefilter or fuzzy_score >= args.fuzzy_prefilter:
                    candidate_pairs.append((i, j, emb_score, fuzzy_score))

        logger.info(f"[{etype}] {len(fast_path_pairs)} fast-path fuzzy merges (>={args.fuzzy_fast_merge_threshold}, "
                    f"no LLM needed), {len(candidate_pairs)} LLM candidate pairs "
                    f"(embedding>={args.embedding_prefilter} OR fuzzy>={args.fuzzy_prefilter}), "
                    f"out of {n*(n-1)//2} total pairs")
        total_llm_calls += len(candidate_pairs)
        fast_path_merges += len(fast_path_pairs)

        if args.dry_run:
            continue

        type_ckpt = checkpoint.setdefault(etype, {"done_pairs": [], "groups": []})
        already_done = set(tuple(p) for p in type_ckpt["done_pairs"])  # snapshot from a PRIOR run/session
        all_groups.extend(type_ckpt["groups"])  # re-adopt this type's already-decided merges

        for i, j, fuzzy_score in fast_path_pairs:
            if (i, j) in already_done:
                continue
            entity1, entity2 = ents[i], ents[j]
            if etype == "ORGANISM" and not organism_merge_is_safe(entity1["entity"], entity2["entity"]):
                logger.info(f"  BLOCKED (taxonomic guard): '{entity1['entity']}' vs '{entity2['entity']}'")
            else:
                canonical, dup = (entity1, entity2) if entity1["paper_count"] >= entity2["paper_count"] else (entity2, entity1)
                logger.info(f"  FAST-MERGE (fuzzy={fuzzy_score:.2f}): '{dup['entity']}' -> '{canonical['entity']}'")
                group = {"entity_type": etype, "canonical": canonical["entity"],
                         "duplicate": dup["entity"], "bio_score": 1.0, "emb_score": None, "fuzzy_score": fuzzy_score}
                all_groups.append(group)
                type_ckpt["groups"].append(group)
            type_ckpt["done_pairs"].append([i, j])

        save_checkpoint()  # fast_path is cheap (no LLM), checkpoint once after the whole batch

        for idx, (i, j, emb_score, fuzzy_score) in enumerate(candidate_pairs, 1):
            if (i, j) in already_done:
                continue
            entity1, entity2 = ents[i], ents[j]
            bio_score = dedup._get_bio_contextual_similarity(entity1["entity"], entity2["entity"], etype)
            if bio_score >= args.biomistral_threshold:
                if etype == "ORGANISM" and not organism_merge_is_safe(entity1["entity"], entity2["entity"]):
                    logger.info(f"  BLOCKED (taxonomic guard, LLM said bio_score={bio_score:.2f}): "
                                f"'{entity1['entity']}' vs '{entity2['entity']}'")
                else:
                    canonical, dup = (entity1, entity2) if entity1["paper_count"] >= entity2["paper_count"] else (entity2, entity1)
                    logger.info(f"  MERGE: '{dup['entity']}' -> '{canonical['entity']}' "
                                f"(bio_score={bio_score:.2f}, emb_score={emb_score:.2f}, fuzzy_score={fuzzy_score:.2f})")
                    group = {"entity_type": etype, "canonical": canonical["entity"],
                             "duplicate": dup["entity"], "bio_score": bio_score, "emb_score": emb_score,
                             "fuzzy_score": fuzzy_score}
                    all_groups.append(group)
                    type_ckpt["groups"].append(group)
            type_ckpt["done_pairs"].append([i, j])
            # Checkpoint every 20 LLM calls, not every single one - each save is a full
            # JSON rewrite, and at ~4s/call this keeps I/O overhead negligible while
            # bounding worst-case lost work on a crash to <20 calls (~80s).
            if idx % 20 == 0:
                save_checkpoint()

        save_checkpoint()

    elapsed = time.time() - t0
    logger.info(f"Total: {total_llm_calls} LLM candidate pairs (~{total_llm_calls * 2 / 60:.0f} min at ~2s/call), "
                f"{fast_path_merges} fast-path fuzzy merges (no LLM needed)")

    if args.dry_run:
        logger.info("Dry run - no LLM calls made, no output written.")
        return

    logger.info(f"Found {len(all_groups)} merge decisions in {elapsed/60:.1f} min.")

    # Apply merges: fold duplicate entities' stats into their canonical entity.
    dup_to_canonical = {}
    for g in all_groups:
        dup_to_canonical[(g["duplicate"].lower(), g["entity_type"])] = (g["canonical"], g["entity_type"])

    merged_by_key = {}
    for e in entities:
        key = (e["entity"].lower(), e["entity_type"])
        target_key = dup_to_canonical.get(key, key)
        if target_key not in merged_by_key:
            merged_by_key[target_key] = dict(e)
            merged_by_key[target_key]["merged_variants"] = []
        else:
            rec = merged_by_key[target_key]
            rec["paper_count"] = max(rec["paper_count"], e["paper_count"])
            rec["total_occurrences"] += e["total_occurrences"]
            rec["papers"] = sorted(set(rec.get("papers", [])) | set(e.get("papers", [])))
            rec["merged_variants"].append(e["entity"])

    merged_entities = list(merged_by_key.values())
    logger.info(f"Corpus: {len(entities)} -> {len(merged_entities)} entities after merge "
                f"({len(entities) - len(merged_entities)} folded in).")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"metadata": {**data.get("metadata", {}), "biomedical_dedup_merges": len(all_groups)},
                    "entities": merged_entities}, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote merged corpus: {args.output}")


if __name__ == "__main__":
    main()
