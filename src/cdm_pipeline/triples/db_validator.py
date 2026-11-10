"""Two-tier DB relationship validation.

Tier 1 (BioLORD-2023, no LLM): Embed each relationship as a natural-language
   statement ("X is associated with Y") and compare to evidence text via cosine
   similarity. Auto-accept high similarity, auto-reject very low.
   For CO_OCCURS_WITH (evidence is just "Co-occur in N papers"), compare subject
   vs object embeddings instead — flag truly absurd pairings.

Tier 2 (small LLM, borderline only): Send borderline cases to a small Ollama
   model (phi4-mini:3.8b) for final judgment: KEEP / FIX / REJECT.

Usage:
    python -m cdm_pipeline.triples.db_validator --model phi4-mini:3.8b
    python -m cdm_pipeline.triples.db_validator --dry-run   # just score, no LLM
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import numpy as np

from ..config import CDM_OUTPUT_DIR

logger = logging.getLogger(__name__)

DB_PATH = CDM_OUTPUT_DIR / "microbiome_cdm.db"
OUTPUT_DIR = CDM_OUTPUT_DIR / "validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREDICATE_VERBS = {
    "ASSOCIATED_WITH": "is associated with",
    "TREATS": "treats",
    "TREATED_BY": "is treated by",
    "PRODUCES": "produces",
    "PRODUCED_BY": "is produced by",
    "DISRUPTS": "disrupts",
    "DEPLETED_IN": "is depleted in",
    "ENRICHED_IN": "is enriched in",
    "CO_OCCURS_WITH": "co-occurs with",
    "ENCODES": "encodes",
    "EXPRESSES": "expresses",
    "PART_OF_PATHWAY": "is part of pathway",
    "PARTICIPATES_IN": "participates in",
    "IMPLICATED_IN": "is implicated in",
}

AUTO_KEEP = 0.60
AUTO_REJECT = 0.25
CO_OCCUR_THRESHOLD = 0.15
BATCH_SIZE = 512


def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("FremyCompany/BioLORD-2023")


def load_relationships(db_path: Path = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("""
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.evidence, r.confidence,
               e1.term, e1.entity_type,
               e2.term, e2.entity_type
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
        ORDER BY r.id
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "source_id": r[1],
            "target_id": r[2],
            "relationship_type": r[3],
            "evidence": r[4] or "",
            "confidence": r[5],
            "subject": r[6],
            "subject_type": r[7],
            "object": r[8],
            "object_type": r[9],
        }
        for r in rows
    ]


def make_statement(rel: dict) -> str:
    verb = PREDICATE_VERBS.get(rel["relationship_type"], rel["relationship_type"].lower().replace("_", " "))
    return f"{rel['subject']} {verb} {rel['object']}"


def score_tier1(rels: list[dict], model) -> list[dict]:
    """Score all relationships with BioLORD-2023 embedding similarity."""
    statements = [make_statement(r) for r in rels]

    is_cooc = [r["relationship_type"] == "CO_OCCURS_WITH" for r in rels]

    # For typed relations: embed statement vs evidence
    # For CO_OCCURS_WITH: embed subject vs object (check semantic relatedness)
    typed_indices = [i for i, c in enumerate(is_cooc) if not c]
    cooc_indices = [i for i, c in enumerate(is_cooc) if c]

    # Encode all statements
    print(f"  Encoding {len(statements)} statements with BioLORD-2023...")
    t0 = time.time()
    stmt_embs = model.encode(
        statements,
        batch_size=BATCH_SIZE,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    print(f"  Done in {time.time() - t0:.1f}s")

    # Typed: encode evidence, compute stmt vs evidence similarity
    if typed_indices:
        evidence_texts = [rels[i]["evidence"] if rels[i]["evidence"] else "no evidence" for i in typed_indices]
        print(f"  Encoding {len(typed_indices)} evidence texts...")
        t0 = time.time()
        ev_embs = model.encode(
            evidence_texts,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        print(f"  Done in {time.time() - t0:.1f}s")

    # CO_OCCURS_WITH: encode subject and object separately
    if cooc_indices:
        subj_texts = [rels[i]["subject"] for i in cooc_indices]
        obj_texts = [rels[i]["object"] for i in cooc_indices]
        print(f"  Encoding {len(cooc_indices)} CO_OCCURS_WITH entity pairs...")
        t0 = time.time()
        subj_embs = model.encode(
            subj_texts,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        obj_embs = model.encode(
            obj_texts,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        print(f"  Done in {time.time() - t0:.1f}s")

    # Compute scores
    results = []
    ev_offset = 0
    cooc_offset = 0
    for i, rel in enumerate(rels):
        if not is_cooc[i]:
            ev_idx = ev_offset
            ev_offset += 1
            sim = float(stmt_embs[i] @ ev_embs[ev_idx])
            score_type = "evidence_match"
        else:
            cooc_idx = cooc_offset
            cooc_offset += 1
            sim = float(subj_embs[cooc_idx] @ obj_embs[cooc_idx])
            score_type = "entity_relatedness"

        if score_type == "evidence_match":
            if sim >= AUTO_KEEP:
                verdict = "auto_keep"
            elif sim < AUTO_REJECT:
                verdict = "auto_reject"
            else:
                verdict = "borderline"
        else:
            if sim >= CO_OCCUR_THRESHOLD:
                verdict = "auto_keep"
            else:
                verdict = "borderline"

        results.append({
            **rel,
            "biolord_score": round(sim, 4),
            "score_type": score_type,
            "statement": statements[i],
            "tier1_verdict": verdict,
        })

    return results


def llm_validate(rels: list[dict], model_name: str = "phi4-mini:3.8b") -> list[dict]:
    """Send borderline relationships to a small LLM for judgment."""
    import urllib.request

    print(f"  Sending {len(rels)} borderline cases to {model_name}...")

    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    results = []
    t0 = time.time()

    for idx, rel in enumerate(rels):
        if rel["relationship_type"] == "CO_OCCURS_WITH":
            prompt = (
                f"Two entities co-occur in {rel['evidence'] or 'scientific papers'}. "
                f"Is this a meaningful co-occurrence worth keeping in a knowledge graph?\n\n"
                f"Entity 1: {rel['subject']} ({rel['subject_type']})\n"
                f"Entity 2: {rel['object']} ({rel['object_type']})\n\n"
                f"Answer with one word: KEEP or REJECT. Then briefly explain why (1 sentence)."
            )
        else:
            verb = PREDICATE_VERBS.get(rel["relationship_type"], rel["relationship_type"])
            prompt = (
                f"Does the evidence support this relationship?\n\n"
                f"Relationship: {rel['subject']} ({rel['subject_type']}) {verb} {rel['object']} ({rel['object_type']})\n"
                f"Evidence: {rel['evidence'][:400]}\n\n"
                f"Answer with: KEEP, FIX (suggest correct predicate), or REJECT. "
                f"Then briefly explain why (1 sentence)."
            )

        payload = json.dumps({
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "seed": 42, "num_predict": 150},
        }).encode()

        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                text = data.get("response", "").strip()

            verdict = "keep"
            text_lower = text.lower()
            if "reject" in text_lower[:20]:
                verdict = "reject"
            elif "fix" in text_lower[:20]:
                verdict = "fix"

            results.append({
                **rel,
                "llm_verdict": verdict,
                "llm_response": text,
            })
        except Exception as e:
            results.append({
                **rel,
                "llm_verdict": "error",
                "llm_response": str(e),
            })

        if (idx + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            eta = (len(rels) - idx - 1) / rate
            print(f"    {idx + 1}/{len(rels)} ({rate:.1f}/s, ETA {eta:.0f}s)")

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s ({len(rels) / elapsed:.1f}/s)")
    return results


def validate(
    db_path: Path = DB_PATH,
    model_name: str = "phi4-mini:3.8b",
    dry_run: bool = False,
    apply: bool = False,
):
    """Full two-tier validation of all DB relationships."""
    print("=" * 60)
    print("DB Relationship Validation (BioLORD + LLM)")
    print("=" * 60)
    print(f"DB:          {db_path}")
    print(f"LLM model:   {model_name}")
    print(f"Dry run:     {dry_run}")
    print(f"Apply to DB: {apply}")
    print()

    rels = load_relationships(db_path)
    print(f"Loaded {len(rels)} relationships")

    # Tier 1: BioLORD scoring
    print("\n--- Tier 1: BioLORD-2023 embedding similarity ---")
    model = _get_model()
    scored = score_tier1(rels, model)

    # Summary
    auto_keep = sum(1 for r in scored if r["tier1_verdict"] == "auto_keep")
    auto_reject = sum(1 for r in scored if r["tier1_verdict"] == "auto_reject")
    borderline = sum(1 for r in scored if r["tier1_verdict"] == "borderline")

    print(f"\n  Auto-keep:    {auto_keep:6d} ({auto_keep / len(scored) * 100:.1f}%)")
    print(f"  Auto-reject:  {auto_reject:6d} ({auto_reject / len(scored) * 100:.1f}%)")
    print(f"  Borderline:   {borderline:6d} ({borderline / len(scored) * 100:.1f}%)")

    # Break down by type
    typed = [r for r in scored if r["score_type"] == "evidence_match"]
    cooc = [r for r in scored if r["score_type"] == "entity_relatedness"]
    print(f"\n  Typed relations ({len(typed)}):")
    tk = sum(1 for r in typed if r["tier1_verdict"] == "auto_keep")
    tr = sum(1 for r in typed if r["tier1_verdict"] == "auto_reject")
    tb = sum(1 for r in typed if r["tier1_verdict"] == "borderline")
    print(f"    auto-keep={tk}, auto-reject={tr}, borderline={tb}")
    if typed:
        scores = sorted([r["biolord_score"] for r in typed])
        print(f"    score: min={scores[0]:.3f}, median={scores[len(scores)//2]:.3f}, max={scores[-1]:.3f}")

    print(f"\n  CO_OCCURS_WITH ({len(cooc)}):")
    ck = sum(1 for r in cooc if r["tier1_verdict"] == "auto_keep")
    cb = sum(1 for r in cooc if r["tier1_verdict"] == "borderline")
    print(f"    auto-keep={ck}, borderline={cb}")
    if cooc:
        scores = sorted([r["biolord_score"] for r in cooc])
        print(f"    score: min={scores[0]:.3f}, median={scores[len(scores)//2]:.3f}, max={scores[-1]:.3f}")

    # Show auto-reject samples
    rejects = [r for r in scored if r["tier1_verdict"] == "auto_reject"]
    if rejects:
        print(f"\n  Auto-reject samples ({len(rejects)} total):")
        for r in rejects[:10]:
            print(f"    score={r['biolord_score']:.3f}  [{r['subject_type']}] {r['subject']} --{r['relationship_type']}--> [{r['object_type']}] {r['object']}")
            if r["evidence"]:
                print(f"      ev: {r['evidence'][:80]}")

    # Tier 2: LLM validation for borderline typed relations only
    # CO_OCCURS_WITH are honestly labeled co-occurrence — no need for LLM judgment
    borderline_rels = [r for r in scored if r["tier1_verdict"] == "borderline" and r["score_type"] == "evidence_match"]
    borderline_cooc = [r for r in scored if r["tier1_verdict"] == "borderline" and r["score_type"] == "entity_relatedness"]
    print(f"\n  Borderline breakdown: {len(borderline_rels)} typed, {len(borderline_cooc)} CO_OCCURS_WITH (skipped)")
    if borderline_rels and not dry_run:
        print(f"\n--- Tier 2: LLM validation ({model_name}) ---")
        llm_results = llm_validate(borderline_rels, model_name)

        keep = sum(1 for r in llm_results if r["llm_verdict"] == "keep")
        fix = sum(1 for r in llm_results if r["llm_verdict"] == "fix")
        reject = sum(1 for r in llm_results if r["llm_verdict"] == "reject")
        error = sum(1 for r in llm_results if r["llm_verdict"] == "error")

        print(f"\n  LLM verdicts: keep={keep}, fix={fix}, reject={reject}, error={error}")

        # Merge results
        llm_map = {r["id"]: r for r in llm_results}
        for r in scored:
            if r["id"] in llm_map:
                r["final_verdict"] = llm_map[r["id"]]["llm_verdict"]
                r["llm_response"] = llm_map[r["id"]]["llm_response"]
            else:
                r["final_verdict"] = r["tier1_verdict"].replace("auto_", "")
                r["llm_response"] = ""
    else:
        for r in scored:
            r["final_verdict"] = r["tier1_verdict"].replace("auto_", "")
            r["llm_response"] = ""
        if borderline_rels and dry_run:
            print(f"\n  [DRY RUN] {len(borderline_rels)} borderline cases would be sent to LLM")

    # Final summary
    final_keep = sum(1 for r in scored if r["final_verdict"] in ("keep", "auto_keep"))
    final_reject = sum(1 for r in scored if r["final_verdict"] in ("reject", "auto_reject"))
    final_fix = sum(1 for r in scored if r["final_verdict"] == "fix")

    print(f"\n{'=' * 60}")
    print(f"Final: keep={final_keep}, reject={final_reject}, fix={final_fix}")
    print(f"  of {len(scored)} total relationships")
    print(f"{'=' * 60}")

    # Save results
    output_file = OUTPUT_DIR / "db_validation_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(scored, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {output_file}")

    # Save borderline LLM responses for review
    if borderline_rels and not dry_run:
        llm_file = OUTPUT_DIR / "db_validation_llm_responses.json"
        with open(llm_file, "w", encoding="utf-8") as f:
            json.dump(llm_results, f, indent=2, ensure_ascii=False)
        print(f"LLM responses saved to {llm_file}")

    # Apply to DB
    if apply and not dry_run:
        to_reject = [r["id"] for r in scored if r["final_verdict"] in ("reject", "auto_reject")]
        if to_reject:
            print(f"\nDeleting {len(to_reject)} rejected relationships from DB...")
            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()
            placeholders = ",".join("?" * len(to_reject))
            c.execute(f"DELETE FROM relationships WHERE id IN ({placeholders})", to_reject)
            conn.commit()
            conn.close()
            print(f"  Deleted {c.rowcount} relationships")

    return scored


def main():
    parser = argparse.ArgumentParser(description="Two-tier DB relationship validation")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to the SQLite DB")
    parser.add_argument("--model", type=str, default="phi4-mini:3.8b", help="Ollama model for Tier 2")
    parser.add_argument("--dry-run", action="store_true", help="Only Tier 1 (BioLORD), skip LLM")
    parser.add_argument("--apply", action="store_true", help="Delete rejected relationships from DB")
    args = parser.parse_args()

    validate(db_path=args.db, model_name=args.model, dry_run=args.dry_run, apply=args.apply)


if __name__ == "__main__":
    main()
