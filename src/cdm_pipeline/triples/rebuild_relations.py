"""Rebuild DB relationships from LLM-extracted triples.

Replaces the heuristic type-pair dispatch (lines 803-832 of cdm/database.py)
with LLM-extracted relation types. Co-occurrence edges that have no LLM triple
are relabeled as CO_OCCURS_WITH (honest labeling, not falsely labeled as
ASSOCIATED_WITH/PRODUCES/EXPRESSES etc.).

Workflow:
1. Load all triples from cdm_output/triples/*.triples.json
2. Match triple subject/object to entities in the DB (exact → substring → fuzzy)
3. Reset ALL heuristic-assigned relation types to CO_OCCURS_WITH
4. For matched LLM triples: update relationship_type + evidence
5. Unmatched co-occurrence pairs stay as CO_OCCURS_WITH
6. Report match statistics
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import difflib
import re

import numpy as np

from cdm_pipeline.quality.predicate_synonyms import normalize_predicate, is_correlational_evidence
from cdm_pipeline.quality.type_constraints import validate_and_fix
from cdm_pipeline.quality.corroboration_merge import merge_triples

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRIPLES_DIR = REPO_ROOT / "paper" / "_multi_ner_runs" / "cdm_output" / "triples"
DB_PATH = REPO_ROOT / "paper" / "_multi_ner_runs" / "cdm_output" / "microbiome_cdm.db"

# These are the relation types assigned by the heuristic type-pair dispatch
# (lines 803-832 of cdm/database.py). All others (PARENT_OF, PROTECTS_AGAINST,
# EXACERBATES) come from the KB and should NOT be reset.
HEURISTIC_REL_TYPES = {
    "ASSOCIATED_WITH", "CO_OCCURS_WITH", "PRODUCES", "EXPRESSES",
    "ENCODES", "PART_OF_PATHWAY", "TREATS", "DISRUPTS",
}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower().strip())


def load_triples(triples_dir: Path = TRIPLES_DIR, validated: bool = False) -> list:
    """Load all triples from per-paper JSON files.

    Args:
        triples_dir: Directory containing per-paper JSON files.
        validated: If True, load from validated output (Phase 2) with
                   *.validated.json pattern and 'validated_triples' key.
                   If False, load from Phase 1 output with *.triples.json
                   pattern and 'triples' key.
    """
    all_triples = []
    if validated:
        files = sorted(triples_dir.glob("*.validated.json"))
        print(f"Loading validated triples from {len(files)} papers...")
        # Also load original triples to recover evidence/paper_id/sentence fields
        # that were stripped during validation
        orig_dir = triples_dir.parent  # e.g. .../triples/ (parent of .../triples/validated/)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)

            # Load matching original triples file for evidence/paper_id fields
            acc = f.stem.replace(".validated", "")
            orig_file = orig_dir / f"{acc}.triples.json"
            orig_by_key = {}
            if orig_file.exists():
                with open(orig_file, encoding="utf-8") as fh2:
                    orig_data = json.load(fh2)
                for ot in orig_data.get("triples", []):
                    key = (ot.get("subject", ""), ot.get("predicate", ""), ot.get("object", ""))
                    orig_by_key[key] = ot

            for t in data.get("validated_triples", []):
                # Skip rejected triples
                if t.get("action") == "reject":
                    continue
                # Fix key naming bug: validator sometimes outputs "order_type" instead of "object_type"
                if "order_type" in t and "object_type" not in t:
                    t["object_type"] = t.pop("order_type")
                # Merge in fields from original triples that were stripped
                key = (t.get("subject", ""), t.get("predicate", ""), t.get("object", ""))
                orig = orig_by_key.get(key, {})
                merged = {**orig, **t}  # validated fields override, but keep evidence etc.
                # Ensure paper_id is set
                if not merged.get("paper_id"):
                    merged["paper_id"] = acc
                all_triples.append(merged)
        print(f"  Loaded {len(all_triples)} validated triples (rejects filtered)")
    else:
        files = sorted(triples_dir.glob("*.triples.json"))
        print(f"Loading triples from {len(files)} papers...")
        for f in files:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            for t in data.get("triples", []):
                all_triples.append(t)
    print(f"  Loaded {len(all_triples)} triples total")
    return all_triples


def build_entity_lookup(db_path: Path) -> dict:
    """Build (norm(term), entity_type) -> entity_id lookup from DB."""
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
    print(f"  Entity lookup: {len(lookup)} (norm, type) pairs")
    return lookup, by_type


def match_entity_tiers_1_3(
    text: str,
    entity_type: str,
    lookup: dict,
    by_type: dict,
) -> int | None:
    """Match triple subject/object text to a DB entity (Tiers 1-3 only).

    Tier 1: Exact norm match with type constraint
    Tier 2: Exact norm match without type (any type)
    Tier 3: Substring match (text is substring of entity term or vice versa, same type)
    """
    n = norm(text)
    if not n or len(n) < 2:
        return None

    # Tier 1: exact match with type
    if (n, entity_type) in lookup:
        return lookup[(n, entity_type)]

    # Tier 2: exact match without type
    for etype, eid in [(k[1], v) for k, v in lookup.items() if k[0] == n]:
        return eid

    # Tier 3: substring match (same type)
    candidates = by_type.get(entity_type, [])
    for cn, eid, cterm in candidates:
        if n in cn or cn in n:
            if len(n) > 3 and len(cn) > 3:
                return eid

    return None


def match_entity_difflib(
    text: str,
    entity_type: str,
    by_type: dict,
    threshold: float = 0.90,
) -> int | None:
    """Tier 4 (legacy): difflib SequenceMatcher fuzzy match."""
    n = norm(text)
    candidates = by_type.get(entity_type, [])
    best_ratio = 0.0
    best_eid = None
    for cn, eid, cterm in candidates:
        ratio = difflib.SequenceMatcher(None, n, cn).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_eid = eid
    if best_ratio >= threshold and best_eid:
        return best_eid
    return None


def match_entity_biolord(
    text: str,
    entity_type: str,
    embeddings_cache: dict,
    q_emb: np.ndarray,
    threshold: float = 0.85,
) -> tuple[int | None, float]:
    """Tier 4 (BioLORD-2023): semantic embedding match."""
    if entity_type not in embeddings_cache:
        return None, 0.0
    embs, ids, terms = embeddings_cache[entity_type]
    if len(ids) == 0:
        return None, 0.0
    sims = embs @ q_emb
    best_idx = int(np.argmax(sims))
    best_sim = float(sims[best_idx])
    if best_sim >= threshold:
        return ids[best_idx], best_sim
    return None, best_sim


def rebuild(db_path: Path = DB_PATH, triples_dir: Path = TRIPLES_DIR, dry_run: bool = False, validated: bool = False, eco_mapping: bool = False, use_biolord: bool = False, biolord_threshold: float = 0.85, quality_gates: bool = False, bio_audit: bool = False, rescore: bool = False, entity_cleanup: bool = False):
    """Rebuild relationships from LLM triples.

    Args:
        validated: If True, load from validated output (Phase 2).
        eco_mapping: If True, tag each relationship with ECO evidence codes
                     via embedding similarity (requires Ollama bge-m3 running).
        use_biolord: If True, use BioLORD-2023 embeddings for Tier 4 matching
                     instead of difflib SequenceMatcher.
        biolord_threshold: Cosine similarity threshold for BioLORD-2023 matching.
        quality_gates: If True, apply quality gates:
                      1. Predicate synonym normalization
                      2. Type-pair constraint validation (demote/swap/reject)
                      3. Corroboration merge across papers
                      4. Direction-demotion for correlational evidence
        bio_audit: If True, run biological plausibility audit (Gate 5) after rebuild.
        rescore: If True, recompute confidence scores with 8-component formula (Gate 6).
        entity_cleanup: If True, run LLM entity cleanup (Gate 4.5: type correction +
                       bge-m3 dedup + noise detection). Requires Ollama running.
    """
    print("=" * 60)
    print("Rebuilding DB relationships from LLM triples")
    print("=" * 60)
    print(f"DB:            {db_path}")
    print(f"Triples:       {triples_dir}")
    print(f"Validated:     {validated}")
    print(f"ECO map:       {eco_mapping}")
    print(f"Quality gates: {quality_gates}")
    print(f"Bio audit:     {bio_audit}")
    print(f"Rescore:       {rescore}")
    print(f"Entity cleanup:{entity_cleanup}")
    print(f"Tier 4:        {'BioLORD-2023 ≥%.2f' % biolord_threshold if use_biolord else 'difflib ≥0.90'}")
    print(f"Dry run:       {dry_run}")
    print()

    # Load triples
    triples = load_triples(triples_dir, validated=validated)
    if not triples:
        print("ERROR: No triples found. Run triple extraction first.")
        return

    # ── Quality Gate 1: Predicate synonym normalization ──
    if quality_gates:
        print("Quality Gate 1: Normalizing predicates...")
        pred_before = Counter(t.get("predicate", "").lower() for t in triples)
        for t in triples:
            raw_pred = t.get("predicate", "")
            canonical = normalize_predicate(raw_pred)
            if canonical != raw_pred.lower():
                t["original_predicate_raw"] = raw_pred
            t["predicate"] = canonical
        pred_after = Counter(t.get("predicate", "").lower() for t in triples)
        n_changed = sum(1 for t in triples if t.get("original_predicate_raw"))
        n_canonical = len(set(t.get("predicate", "").lower() for t in triples))
        print(f"  Normalized {n_changed} predicates to canonical forms")
        print(f"  Unique predicates: {len(pred_before)} → {n_canonical}")
        print()

    # Optionally init ECO mapper
    eco_mapper = None
    if eco_mapping:
        try:
            from cdm_pipeline.triples.eco_mapper import ECOMapper
            print("Initializing ECO mapper (bge-m3 embeddings)...")
            eco_mapper = ECOMapper()
            print(f"  ECO mapper ready: {len(eco_mapper.ids)} classes")
        except Exception as e:
            print(f"  WARNING: ECO mapper init failed: {e}")
            print(f"  Continuing without ECO mapping.")
            eco_mapper = None

    # Build entity lookup
    print("Building entity lookup...")
    lookup, by_type = build_entity_lookup(db_path)

    # Optionally load BioLORD-2023 embeddings cache
    biolord_cache = None
    if use_biolord:
        try:
            from cdm_pipeline.triples.biolord_matcher import encode_entities, encode_queries
            print("Loading BioLORD-2023 entity embeddings...")
            biolord_cache = encode_entities(db_path)
            total_ents = sum(len(ids) for _, ids, _ in biolord_cache.values())
            print(f"  Loaded {total_ents} entity embeddings across {len(biolord_cache)} types")
        except Exception as e:
            print(f"  WARNING: BioLORD-2023 init failed ({e}), falling back to difflib")
            biolord_cache = None

    # Phase 1: Run Tiers 1-3 (string matching) on all triple entities
    print("Matching triples to entities (Tiers 1-3)...")
    matched = []
    unmatched_subject = 0
    unmatched_object = 0
    unmatched_both = 0

    # Track which entities need Tier 4 (BioLORD/difflib)
    tier4_needed = {}  # (text, entity_type) -> list of (triple_idx, role)

    for idx, t in enumerate(triples):
        s_type = t.get("subject_type") or t.get("order_type", "")
        o_type = t.get("object_type") or t.get("order_type", "")
        s_text = t.get("subject", "")
        o_text = t.get("object", "")

        s_id = match_entity_tiers_1_3(s_text, s_type, lookup, by_type)
        o_id = match_entity_tiers_1_3(o_text, o_type, lookup, by_type)

        # Queue unmatched for Tier 4
        if not s_id:
            key = (s_text, s_type)
            tier4_needed.setdefault(key, []).append((idx, "subject"))
        if not o_id:
            key = (o_text, o_type)
            tier4_needed.setdefault(key, []).append((idx, "object"))

    # Phase 2: Tier 4 matching (batch BioLORD-2023 or difflib)
    tier4_results = {}  # (text, entity_type) -> entity_id
    if tier4_needed:
        print(f"  {len(tier4_needed)} unique entities need Tier 4 matching...")

        if biolord_cache:
            # Batch encode all unmatched entities with BioLORD-2023
            texts = [k[0] for k in tier4_needed]
            types = [k[1] for k in tier4_needed]
            print(f"  Encoding {len(texts)} entities with BioLORD-2023...")
            q_embs = encode_queries(texts)
            t4_matched = 0
            for i, (text, etype) in enumerate(zip(texts, types)):
                if etype not in biolord_cache:
                    continue
                embs, ids, terms = biolord_cache[etype]
                if len(ids) == 0:
                    continue
                sims = embs @ q_embs[i]
                best_idx = int(np.argmax(sims))
                best_sim = float(sims[best_idx])
                if best_sim >= biolord_threshold:
                    tier4_results[(text, etype)] = ids[best_idx]
                    t4_matched += 1
            print(f"  Tier 4 (BioLORD-2023 ≥{biolord_threshold}): matched {t4_matched}/{len(tier4_needed)}")
        else:
            # Fallback: difflib
            t4_matched = 0
            for (text, etype) in tier4_needed:
                eid = match_entity_difflib(text, etype, by_type)
                if eid:
                    tier4_results[(text, etype)] = eid
                    t4_matched += 1
            print(f"  Tier 4 (difflib ≥0.90): matched {t4_matched}/{len(tier4_needed)}")

    # Now resolve all triple entity IDs
    print("Resolving entity IDs...")
    for idx, t in enumerate(triples):
        s_type = t.get("subject_type") or t.get("order_type", "")
        o_type = t.get("object_type") or t.get("order_type", "")
        s_text = t.get("subject", "")
        o_text = t.get("object", "")

        s_id = match_entity_tiers_1_3(s_text, s_type, lookup, by_type)
        o_id = match_entity_tiers_1_3(o_text, o_type, lookup, by_type)

        # Try Tier 4 for unmatched
        if not s_id:
            s_id = tier4_results.get((s_text, s_type))
        if not o_id:
            o_id = tier4_results.get((o_text, o_type))

        if s_id and o_id:
            matched.append({
                "source_id": s_id,
                "target_id": o_id,
                "relationship_type": t["predicate"].upper(),
                "confidence": t.get("confidence", 0.5),
                "evidence": t.get("evidence", ""),
                "rationale": t.get("rationale", ""),
                "paper_id": t.get("paper_id", ""),
                "sentence_id": t.get("sentence_id"),
                "evidence_start": t.get("evidence_start_offset"),
                "evidence_end": t.get("evidence_end_offset"),
            })
        elif not s_id and not o_id:
            unmatched_both += 1
        elif not s_id:
            unmatched_subject += 1
        else:
            unmatched_object += 1

    print(f"  Matched: {len(matched)} triples (both subject and object found)")
    print(f"  Unmatched: subject={unmatched_subject}, object={unmatched_object}, both={unmatched_both}")
    total_triples = len(triples)
    match_rate = len(matched) / total_triples * 100 if total_triples > 0 else 0
    print(f"  Match rate: {match_rate:.1f}%")
    print()

    # ── Quality Gate 2: Type-pair constraint validation ──
    if quality_gates:
        print("Quality Gate 2: Type-pair constraint validation...")
        # We need entity types for validation — load from DB
        conn_t = sqlite3.connect(str(db_path))
        type_lookup = {}
        for row in conn_t.execute("SELECT id, entity_type FROM entities"):
            type_lookup[row[0]] = row[1]
        conn_t.close()

        validated_matched = []
        n_demoted = 0
        n_swapped = 0
        n_flagged = 0
        n_rejected = 0
        for m in matched:
            s_type = type_lookup.get(m["source_id"], "")
            o_type = type_lookup.get(m["target_id"], "")
            pred = m["relationship_type"].lower()
            result = validate_and_fix(
                "", s_type, pred, "", o_type, m.get("evidence", ""),
            )
            if result["fix_action"] == "swapped":
                m["source_id"], m["target_id"] = m["target_id"], m["source_id"]
                m["original_predicate"] = pred.upper()
                m["demotion_reason"] = result["fix_reason"]
                n_swapped += 1
            elif result["fix_action"] == "demoted":
                m["original_predicate"] = pred.upper()
                m["demotion_reason"] = result["fix_reason"]
                m["direction_demoted_to"] = "associated_with"
                m["relationship_type"] = "ASSOCIATED_WITH"
                n_demoted += 1
            elif result["fix_action"] == "flagged":
                m["flagged"] = result["fix_reason"]
                n_flagged += 1
            elif result["fix_action"] == "rejected":
                n_rejected += 1
                continue

            # Quality Gate 2b: Direction-demotion for correlational evidence
            pred_lower = m["relationship_type"].lower()
            if pred_lower in ("treats", "treated_by", "produces", "produced_by",
                              "disrupts", "depleted_in", "enriched_in",
                              "encodes", "expresses", "implicated_in"):
                ev = m.get("evidence", "")
                if is_correlational_evidence(ev):
                    m["original_predicate"] = m["relationship_type"]
                    m["demotion_reason"] = "correlational_evidence_for_directional_predicate"
                    m["direction_demoted_to"] = "associated_with"
                    m["relationship_type"] = "ASSOCIATED_WITH"
                    n_demoted += 1

            validated_matched.append(m)

        print(f"  Type-pair: swapped={n_swapped}, demoted={n_demoted}, flagged={n_flagged}, rejected={n_rejected}")
        matched = validated_matched
        print(f"  Validated triples remaining: {len(matched)}")
        print()

    # Group matched triples by entity pair (for deduplication)
    pair_triples = defaultdict(list)
    for m in matched:
        key = (m["source_id"], m["target_id"])
        pair_triples[key].append(m)

    # Also collect reverse pairs (LLM might have A→B and B→A for same pair)
    pair_triples_merged = defaultdict(list)
    for (s, t), tris in pair_triples.items():
        reverse_key = (t, s)
        if reverse_key in pair_triples_merged:
            # Merge into existing (keep direction with more triples)
            existing = pair_triples_merged[reverse_key]
            if len(existing) < len(tris):
                pair_triples_merged[reverse_key] = tris + existing
            else:
                pair_triples_merged[reverse_key] = existing + tris
        elif (s, t) not in pair_triples_merged:
            pair_triples_merged[(s, t)] = tris
        else:
            pair_triples_merged[(s, t)].extend(tris)

    # For each pair, pick the most common relation type (majority vote)
    # ── Quality Gate 3: Corroboration merge (if enabled) ──
    pair_relations = {}
    if quality_gates:
        print("Quality Gate 3: Corroboration merge...")
        n_corroborated = 0
        for (s_id, t_id), tris in pair_triples_merged.items():
            merged_list = merge_triples(tris)
            for m in merged_list:
                rel_type = m.get("relationship_type", "ASSOCIATED_WITH")
                if not rel_type.endswith(("WITH", "BY", "IN", "PATHWAY")):
                    rel_type = rel_type.upper()
                pair_relations[(s_id, t_id)] = {
                    "relationship_type": rel_type,
                    "confidence": m.get("confidence", 0.5),
                    "evidence": m.get("evidence", ""),
                    "n_triples": m.get("corroboration_count", 1),
                    "n_papers": m.get("corroboration_count", 1),
                    "paper_ids": m.get("source_papers", []),
                    "original_predicate": m.get("original_predicate"),
                    "demotion_reason": m.get("demotion_reason"),
                    "direction_demoted_to": m.get("direction_demoted_to"),
                }
                if m.get("corroboration_count", 1) > 1:
                    n_corroborated += 1
        print(f"  Corroborated pairs (≥2 sources): {n_corroborated}")
        print()
    else:
        for (s_id, t_id), tris in pair_triples_merged.items():
            rel_counts = Counter(t["relationship_type"] for t in tris)
            best_rel = rel_counts.most_common(1)[0][0]
            # Average confidence
            avg_conf = sum(t["confidence"] for t in tris) / len(tris)
            # Collect all evidence
            evidence_list = [t["evidence"] for t in tris[:5]]  # top 5 evidence quotes
            pair_relations[(s_id, t_id)] = {
                "relationship_type": best_rel,
                "confidence": round(avg_conf, 4),
                "evidence": " | ".join(evidence_list),
                "n_triples": len(tris),
                "n_papers": len(set(t["paper_id"] for t in tris)),
                "paper_ids": list(set(t["paper_id"] for t in tris)),
            }

    print(f"  Unique entity pairs with LLM relations: {len(pair_relations)}")
    print()

    # ECO evidence code mapping
    if eco_mapper:
        print("Mapping ECO evidence codes via embeddings (bge-m3)...")
        evidence_texts = [info["evidence"][:500] for info in pair_relations.values()]
        try:
            eco_results = eco_mapper.map_evidence_batch(evidence_texts, top_k=1)
            eco_codes = {}
            for (pair_key, _), results in zip(pair_relations.items(), eco_results):
                if results:
                    eco_codes[pair_key] = f"{results[0].eco_id}:{results[0].label}"
                else:
                    eco_codes[pair_key] = None
            n_mapped = sum(1 for v in eco_codes.values() if v)
            print(f"  ECO codes assigned: {n_mapped}/{len(pair_relations)} ({n_mapped/len(pair_relations)*100:.1f}%)")
            # Show sample
            for pair_key, eco in list(eco_codes.items())[:5]:
                if eco:
                    print(f"    {eco}")
        except Exception as e:
            print(f"  WARNING: ECO mapping failed ({e}), continuing without ECO codes")
            eco_codes = {pk: None for pk in pair_relations}
        print()

    # Now rebuild DB
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Get current relationship stats
    c.execute("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC")
    before = dict(c.fetchall())
    print(f"Before rebuild: {before}")
    print(f"  Total: {sum(before.values())} relationships")
    print()

    if dry_run:
        print("[DRY RUN] No changes made to DB.")
        print(f"  Would update {len(pair_relations)} pairs with LLM relation types")
        print(f"  Would reset {sum(v for k, v in before.items() if k in HEURISTIC_REL_TYPES)} heuristic relationships to CO_OCCURS_WITH")
        conn.close()
        return

    # Step 1: Reset ALL heuristic-assigned relation types to CO_OCCURS_WITH
    print("Step 1: Resetting heuristic-assigned relation types to CO_OCCURS_WITH...")
    placeholders = ",".join("?" * len(HEURISTIC_REL_TYPES))
    c.execute(
        f"UPDATE relationships SET relationship_type = 'CO_OCCURS_WITH' "
        f"WHERE relationship_type IN ({placeholders})",
        list(HEURISTIC_REL_TYPES),
    )
    reset_count = c.rowcount
    print(f"  Reset {reset_count} relationships to CO_OCCURS_WITH")

    # Step 2: Update relationships with LLM-extracted relation types
    print("Step 2: Updating relationships with LLM-extracted relation types...")
    updated = 0
    created = 0
    for (s_id, t_id), info in pair_relations.items():
        rel_type = info["relationship_type"]
        conf = info["confidence"]
        evidence = info["evidence"]
        eco_code = eco_codes.get((s_id, t_id)) if eco_mapper else None
        orig_pred = info.get("original_predicate")
        dem_reason = info.get("demotion_reason")
        dem_to = info.get("direction_demoted_to")

        # Check if a relationship already exists for this pair (either direction)
        c.execute(
            "SELECT id FROM relationships WHERE (source_id=? AND target_id=?) OR (source_id=? AND target_id=?)",
            (s_id, t_id, t_id, s_id),
        )
        existing = c.fetchone()

        if existing:
            rel_id = existing[0]
            if quality_gates and orig_pred:
                c.execute(
                    "UPDATE relationships SET relationship_type=?, confidence=?, evidence=?, "
                    "source_type='llm_triple', evidence_type='sentence_level', eco_code=?, "
                    "original_predicate=?, demotion_reason=?, direction_demoted_to=? WHERE id=?",
                    (rel_type, conf, evidence[:500], eco_code, orig_pred, dem_reason, dem_to, rel_id),
                )
            else:
                c.execute(
                    "UPDATE relationships SET relationship_type=?, confidence=?, evidence=?, "
                    "source_type='llm_triple', evidence_type='sentence_level', eco_code=? WHERE id=?",
                    (rel_type, conf, evidence[:500], eco_code, rel_id),
                )
            updated += 1
        else:
            if quality_gates and orig_pred:
                c.execute(
                    "INSERT INTO relationships (source_id, target_id, relationship_type, "
                    "source_db, confidence, evidence, evidence_type, source_type, validation_status, eco_code, "
                    "original_predicate, demotion_reason, direction_demoted_to) "
                    "VALUES (?, ?, ?, 'llm_triple', ?, ?, 'sentence_level', 'llm_extracted', 'llm_verified', ?, ?, ?, ?)",
                    (s_id, t_id, rel_type, conf, evidence[:500], eco_code, orig_pred, dem_reason, dem_to),
                )
            else:
                c.execute(
                    "INSERT INTO relationships (source_id, target_id, relationship_type, "
                    "source_db, confidence, evidence, evidence_type, source_type, validation_status, eco_code) "
                    "VALUES (?, ?, ?, 'llm_triple', ?, ?, 'sentence_level', 'llm_extracted', 'llm_verified', ?)",
                    (s_id, t_id, rel_type, conf, evidence[:500], eco_code),
                )
            rel_id = c.lastrowid
            created += 1

        # Add edge evidence for each paper
        for paper_id in info["paper_ids"]:
            c.execute(
                "INSERT OR IGNORE INTO edge_evidence (relationship_id, paper_id, source_model, eco_code) "
                "VALUES (?, ?, 'qwen3.5:9b', ?)",
                (rel_id, paper_id, eco_code),
            )

    print(f"  Updated {updated} existing relationships with LLM relation types")
    print(f"  Created {created} new relationships from LLM triples")

    conn.commit()

    # Get final stats
    c.execute("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC")
    after = dict(c.fetchall())
    print(f"\nAfter rebuild: {after}")
    print(f"  Total: {sum(after.values())} relationships")

    # Print relation type distribution
    print("\nRelation type distribution:")
    for rel_type, count in sorted(after.items(), key=lambda x: -x[1]):
        pct = count / sum(after.values()) * 100
        print(f"  {rel_type:25s}: {count:6d} ({pct:5.1f}%)")

    conn.close()
    print(f"\nDone. DB updated: {db_path}")

    # ── Quality Gate 4.5: LLM entity cleanup (type correction + dedup + noise) ──
    if entity_cleanup and not dry_run:
        print("\n" + "=" * 60)
        print("Quality Gate 4.5: LLM Entity Cleanup (GPU/Ollama)")
        print("=" * 60)
        try:
            from cdm_pipeline.quality.llm_entity_cleanup import run_entity_cleanup
            cleanup_result = run_entity_cleanup(
                db_path=db_path,
                apply=True,
                passes="1,2,3",
            )
            if "pass1" in cleanup_result:
                print(f"  Pass 1 (type correction): {cleanup_result['pass1']['n_corrected']} corrected")
            if "pass2" in cleanup_result:
                print(f"  Pass 2 (semantic dedup):  {cleanup_result['pass2']['n_merged']} merged")
            if "pass3" in cleanup_result:
                print(f"  Pass 3 (noise detection): {cleanup_result['pass3']['n_noise']} flagged")
        except Exception as e:
            print(f"  WARNING: Entity cleanup failed ({e})")

    # ── Quality Gate 5: Biological plausibility audit ──
    if bio_audit and not dry_run:
        print("\n" + "=" * 60)
        print("Quality Gate 5: Biological plausibility audit")
        print("=" * 60)
        from cdm_pipeline.quality.bio_audit import audit_relations
        audit_result = audit_relations(db_path=db_path, apply=True, dry_run=False)
        print(f"  Audited:       {audit_result['n_audited']:,} relations")
        print(f"  Flagged:       {audit_result['n_flagged']} flags on {audit_result['n_unique_flagged']} unique relations")
        for flag, count in sorted(audit_result["flag_counts"].items(), key=lambda x: -x[1]):
            print(f"    {flag:30s}: {count:6d}")
        print(f"  Actions:       {audit_result['action_counts']}")

    # ── Quality Gate 5.5: Study type annotation (before rescoring) ──
    if rescore and not dry_run:
        print("\n" + "=" * 60)
        print("Quality Gate 5.5: Study type annotation")
        print("=" * 60)
        try:
            from cdm_pipeline.quality.study_type_annotator import annotate_study_types
            st_result = annotate_study_types(db_path=db_path)
            print(f"  Annotated:     {st_result['n_relationships']:,} relations")
            print(f"  With type:     {st_result['n_with_study_type']:,}")
            print(f"  Unknown:       {st_result['n_unknown']:,}")
            print(f"  Distribution:  {st_result['relationship_type_distribution']}")
        except Exception as e:
            print(f"  WARNING: Study type annotation failed ({e})")

    # ── Quality Gate 6: Scientific confidence rescoring ──
    if rescore and not dry_run:
        print("\n" + "=" * 60)
        print("Quality Gate 6: Scientific confidence rescoring")
        print("=" * 60)
        from cdm_pipeline.quality.confidence_scoring import rescore_relations
        score_result = rescore_relations(db_path=db_path, dry_run=False)
        print(f"  Scored:        {score_result['n_scored']:,} relations")
        print(f"  Mean old:      {score_result['mean_old_score']:.4f}")
        print(f"  Mean new:      {score_result['mean_new_score']:.4f}")
        print(f"  Increased:     {score_result['n_increased']:,}")
        print(f"  Decreased:     {score_result['n_decreased']:,}")
        dirs = score_result.get("direction_recovered", {})
        if dirs:
            print(f"  Direction:     {dirs}")


def main():
    parser = argparse.ArgumentParser(description="Rebuild DB relationships from LLM triples")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to the SQLite DB")
    parser.add_argument("--triples-dir", type=Path, default=None, help="Directory with triple JSON files (default: auto)")
    parser.add_argument("--validated", action="store_true", help="Load from validated output (Phase 2) instead of Phase 1")
    parser.add_argument("--dry-run", action="store_true", help="Don't modify DB, just print stats")
    parser.add_argument("--eco-mapping", action="store_true", help="Tag relationships with ECO evidence codes via bge-m3 embeddings")
    parser.add_argument("--biolord", action="store_true", help="Use BioLORD-2023 embeddings for Tier 4 matching (replaces difflib)")
    parser.add_argument("--biolord-threshold", type=float, default=0.85, help="Cosine similarity threshold for BioLORD-2023 matching (default: 0.85)")
    parser.add_argument("--quality-gates", action="store_true", help="Apply quality gates: predicate normalization, type-pair constraints, corroboration merge, direction-demotion")
    parser.add_argument("--bio-audit", action="store_true", help="Run biological plausibility audit (14 microbiome-specific flags) after rebuild")
    parser.add_argument("--rescore", action="store_true", help="Recompute confidence scores with 8-component scientific quality formula")
    parser.add_argument("--entity-cleanup", action="store_true", help="Run LLM entity cleanup (Gate 4.5: type correction + bge-m3 dedup + noise detection). Requires Ollama.")
    args = parser.parse_args()

    if args.triples_dir is None:
        args.triples_dir = TRIPLES_DIR / "validated" if args.validated else TRIPLES_DIR

    rebuild(
        db_path=args.db,
        triples_dir=args.triples_dir,
        dry_run=args.dry_run,
        validated=args.validated,
        eco_mapping=args.eco_mapping,
        use_biolord=args.biolord,
        biolord_threshold=args.biolord_threshold,
        quality_gates=args.quality_gates,
        bio_audit=args.bio_audit,
        rescore=args.rescore,
        entity_cleanup=args.entity_cleanup,
    )


if __name__ == "__main__":
    main()
