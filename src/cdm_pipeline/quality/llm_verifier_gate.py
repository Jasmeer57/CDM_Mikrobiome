"""LLM verifier gate for the Microbiome-CDM pipeline.

Ported from EFRE's llm_verifier_gate.py, adapted for:
  - 14 CDM entity types (vs EFRE's 10)
  - 14 CDM canonical predicates (vs EFRE's ~30)
  - phi4-mini:3.8b model (vs EFRE's qwen3.5:9b) — shorter prompt, simpler instructions
  - SQLite DB data model (vs EFRE's JSONL)
  - Microbiome scope (not IBD-diet-specific)

6-verdict taxonomy:
  supported        → keep
  over_interpreted → demote (predicate → associated_with, keep in KG)
  contradicted     → flag (send to review)
  not_in_scope     → drop (quarantine)
  not_in_evidence  → flag (send to review)
  nonsensical      → drop (quarantine)

Direction-demotion: if the LLM says "over_interpreted", the directional
predicate is demoted to "associated_with" and the original is preserved
in the `original_predicate` column.

Usage (standalone):
  python -m cdm_pipeline.quality.llm_verifier_gate \
      --db path/to/microbiome_cdm.db \
      --output path/to/verifier_results.json \
      --workers 8 --batch-size 5

Usage (imported from rebuild_relations.py):
  from cdm_pipeline.quality.llm_verifier_gate import verify_relations
  results = verify_relations(relations, workers=8)
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# ── Config ──
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "phi4-mini:3.8b")
DEFAULT_BATCH_SIZE = 5
DEFAULT_WORKERS = 8

# ── Directional predicates that may be over-interpreted from correlational evidence ──
from .predicate_synonyms import DIRECTIONAL_PREDICATES

# ── System prompt (kept short for phi4-mini's smaller context) ──
_SYSTEM_PROMPT = (
    "You are a strict biomedical knowledge-graph quality auditor. "
    "Evaluate whether each triple is correct, well-formed, and supported by the evidence. "
    "Be conservative: if the evidence does not CLEARLY support the claim, mark it accordingly. "
    "Respond ONLY with a JSON array. No explanation outside the JSON."
)

# ── Prompt template (microbiome-scoped, not IBD-diet-specific) ──
_PROMPT_TEMPLATE = """Evaluate each knowledge-graph triple extracted from microbiome literature.

For each triple, assess:
1. SUPPORTED: Does the evidence directly support this specific claim (subject + predicate + object)?
2. DIRECTION: If the predicate is directional (treats, produces, disrupts, depletes, enriches, encodes, expresses, implicated_in), does the evidence support that specific causal/directional claim — or is it merely correlational ("associated with", "linked to", "correlated")?
3. SEMANTIC: Is the triple well-formed? (e.g., "X produces produces Y" is nonsensical; "X treats Y" where Y is a method is wrong)

Verdict options:
  "supported"        — evidence clearly supports the exact claim
  "over_interpreted" — evidence is correlational but claim is directional; demote to "associated with"
  "contradicted"     — evidence contradicts the claim
  "not_in_scope"     — claim is not about microbiome/biology
  "not_in_evidence"  — evidence does not mention this relationship at all
  "nonsensical"      — triple is semantically malformed

Return a JSON array with one object per triple:
[
  {"verdict": "supported", "confidence": 0.9, "reason": "brief explanation"},
  ...
]

Triples to evaluate:

"""


def _build_triple_text(rel: dict) -> str:
    subj = rel.get("subject", "")
    pred = rel.get("relationship_type", "")
    obj = rel.get("object", "")
    evidence = (rel.get("evidence") or "").strip()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    if len(evidence) > 600:
        evidence = evidence[:600] + "..."
    return (
        f"Subject: {subj} ({subj_type})\n"
        f"Predicate: {pred}\n"
        f"Object: {obj} ({obj_type})\n"
        f"Evidence: {evidence}"
    )


def _build_batch_prompt(rels: list[dict]) -> str:
    prompt = _PROMPT_TEMPLATE
    for i, rel in enumerate(rels):
        prompt += f"--- Triple {i + 1} ---\n{_build_triple_text(rel)}\n\n"
    return prompt


def _normalize_verdict(raw: str) -> str:
    """Normalize LLM verdict to one of the canonical labels."""
    if not isinstance(raw, str):
        return "not_in_evidence"
    v = raw.strip().lower().replace("-", "_").replace(" ", "_")
    canonical = {
        "supported", "over_interpreted", "contradicted",
        "not_in_scope", "not_in_evidence", "nonsensical",
    }
    if v in canonical:
        return v
    variants = {
        "associated_with": "over_interpreted",
        "association": "over_interpreted",
        "associational": "over_interpreted",
        "correlational": "over_interpreted",
        "correlation": "over_interpreted",
        "overinterpreted": "over_interpreted",
        "over_interpretation": "over_interpreted",
        "over_interprets": "over_interpreted",
        "out_of_scope": "not_in_scope",
        "not_relevant": "not_in_scope",
        "irrelevant": "not_in_scope",
        "off_topic": "not_in_scope",
        "not_supported": "not_in_evidence",
        "no_evidence": "not_in_evidence",
        "unsupported": "not_in_evidence",
        "nonsense": "nonsensical",
        "malformed": "nonsensical",
        "ill_formed": "nonsensical",
        "contradiction": "contradicted",
        "contradicts": "contradicted",
        "contradictory": "contradicted",
        "support": "supported",
        "supports": "supported",
        "clearly_supported": "supported",
        "well_supported": "supported",
    }
    return variants.get(v, "not_in_evidence")


def _verdict_to_action(verdict: str) -> str:
    v = _normalize_verdict(verdict)
    return {
        "supported": "keep",
        "over_interpreted": "demote",
        "contradicted": "flag",
        "not_in_scope": "drop",
        "not_in_evidence": "flag",
        "nonsensical": "drop",
    }.get(v, "flag")


def _call_llm(prompt: str, model: str, timeout: int = 120) -> list[dict]:
    """Call Ollama and parse JSON array response."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "system": _SYSTEM_PROMPT,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42, "num_predict": 512},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    text = data.get("response", "").strip()

    # phi4-mini may wrap in ```json ... ``` or return bare JSON
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "results" in result:
            return result["results"]
    except json.JSONDecodeError:
        pass

    # Try line-by-line JSONL fallback
    results = []
    for line in text.split("\n"):
        line = line.strip().strip(",").strip("[]")
        if line:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results


def _verify_batch(
    batch_idx: int,
    batch: list[dict],
    model: str,
):
    """Verify a single batch. Returns (batch_idx, results, elapsed, error)."""
    prompt = _build_batch_prompt(batch)
    t0 = time.time()
    try:
        llm_results = _call_llm(prompt, model)
    except Exception as e:
        return batch_idx, [], time.time() - t0, str(e)

    elapsed = time.time() - t0
    out = []
    for i, rel in enumerate(batch):
        if i < len(llm_results) and isinstance(llm_results[i], dict):
            raw_verdict = llm_results[i].get("verdict", "not_in_evidence")
            try:
                confidence = float(llm_results[i].get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            reason = llm_results[i].get("reason", "")
        else:
            raw_verdict = "not_in_evidence"
            confidence = 0.0
            reason = "LLM returned no verdict for this triple"

        verdict = _normalize_verdict(raw_verdict)
        action = _verdict_to_action(verdict)

        rel["llm_verdict"] = verdict
        rel["llm_verdict_raw"] = raw_verdict if isinstance(raw_verdict, str) else ""
        rel["llm_confidence"] = round(confidence, 4)
        rel["llm_reason"] = reason
        rel["llm_verdict_action"] = action

        if verdict == "over_interpreted":
            pred = rel.get("relationship_type", "")
            rel["original_predicate"] = pred
            rel["relationship_type"] = "associated_with"
            rel["direction_demoted_to"] = "associated_with"
            rel["demotion_reason"] = "llm_over_interpreted"

        out.append(rel)

    return batch_idx, out, elapsed, None


def verify_relations(
    relations: list[dict],
    model: str = DEFAULT_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
    workers: int = DEFAULT_WORKERS,
) -> list[dict]:
    """Run LLM verification on all relations.

    Each relation dict should have:
      subject, subject_type, relationship_type, object, object_type, evidence
    Returns the same list with added fields:
      llm_verdict, llm_confidence, llm_reason, llm_verdict_action
      (and for over_interpreted: original_predicate, direction_demoted_to, demotion_reason)
    """
    if not relations:
        return relations

    n_batches = (len(relations) + batch_size - 1) // batch_size
    print(
        f"Verifying {len(relations)} relations in {n_batches} batches of {batch_size} "
        f"({workers} workers, model={model})..."
    )

    batches = []
    for batch_idx in range(n_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(relations))
        batches.append((batch_idx, relations[start:end]))

    results_by_idx: dict[int, list[dict]] = {}
    done_count = 0
    t_start = time.time()

    if workers <= 1:
        for batch_idx, batch in batches:
            try:
                idx, out, elapsed, err = _verify_batch(batch_idx, batch, model)
            except Exception as e:
                print(f"  [batch {batch_idx}] CRASHED: {e}")
                results_by_idx[batch_idx] = batch
                done_count += len(batch)
                continue
            if err:
                print(f"  [batch {batch_idx}] LLM call failed: {err}")
            results_by_idx[idx] = out
            done_count += len(out)
            if (batch_idx + 1) % 10 == 0 or batch_idx == n_batches - 1:
                print(f"  [batch {batch_idx + 1}/{n_batches}] {elapsed:.1f}s — {done_count}/{len(relations)} done")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_verify_batch, batch_idx, batch, model): batch_idx
                for batch_idx, batch in batches
            }
            for future in as_completed(futures):
                try:
                    idx, out, elapsed, err = future.result()
                except Exception as e:
                    idx = futures[future]
                    print(f"  [batch {idx}] CRASHED: {e}")
                    results_by_idx[idx] = batches[idx][1]
                    done_count += len(batches[idx][1])
                    continue
                if err:
                    print(f"  [batch {idx}] LLM call failed: {err}")
                results_by_idx[idx] = out
                done_count += len(out)
                if done_count % (batch_size * 50) < batch_size or done_count == len(relations):
                    pct = done_count / len(relations) * 100
                    elapsed_total = time.time() - t_start
                    rate = done_count / elapsed_total if elapsed_total > 0 else 0
                    eta = (len(relations) - done_count) / rate if rate > 0 else 0
                    print(f"  [{done_count}/{len(relations)}] {pct:.1f}% — {elapsed_total:.0f}s elapsed, ETA {eta:.0f}s")

    results = []
    for i in range(n_batches):
        results.extend(results_by_idx.get(i, []))
    return results


def load_relations_from_db(db_path: Path, where_clause: str = "") -> list[dict]:
    """Load relations from the DB with joined entity names and types."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    query = """
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.confidence, r.evidence, r.source_type,
               s.term as subject, s.entity_type as subject_type,
               t.term as object, t.entity_type as object_type
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
    """
    if where_clause:
        query += f" WHERE {where_clause}"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def apply_verifier_results(db_path: Path, results: list[dict], dry_run: bool = False) -> dict:
    """Apply verifier results to the DB.

    - keep: no change
    - demote: update relationship_type to associated_with, set original_predicate, demotion_reason
    - flag: set validation_status to 'llm_flagged'
    - drop: delete from DB
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    stats = Counter()

    for r in results:
        action = r.get("llm_verdict_action", "keep")
        stats[action] += 1
        if action == "demote":
            if not dry_run:
                conn.execute(
                    "UPDATE relationships SET relationship_type = ?, "
                    "original_predicate = ?, demotion_reason = ?, "
                    "direction_demoted_to = ?, validation_status = 'llm_demoted' "
                    "WHERE id = ?",
                    (
                        r.get("direction_demoted_to", "ASSOCIATED_WITH"),
                        r.get("original_predicate", r.get("relationship_type")),
                        r.get("demotion_reason", "llm_over_interpreted"),
                        r.get("direction_demoted_to", "ASSOCIATED_WITH"),
                        r["id"],
                    ),
                )
        elif action == "keep":
            if not dry_run:
                conn.execute(
                    "UPDATE relationships SET validation_status = 'llm_supported' WHERE id = ?",
                    (r["id"],),
                )
        elif action == "flag":
            if not dry_run:
                conn.execute(
                    "UPDATE relationships SET validation_status = 'llm_flagged' WHERE id = ?",
                    (r["id"],),
                )
        elif action == "drop":
            if not dry_run:
                conn.execute("DELETE FROM relationships WHERE id = ?", (r["id"],))

    if not dry_run:
        conn.commit()
    conn.close()
    return dict(stats)


def main():
    ap = argparse.ArgumentParser(description="LLM verifier gate for MCDM pipeline")
    ap.add_argument("--db", required=True, help="Path to microbiome_cdm.db")
    ap.add_argument("--output", required=True, help="Output JSON path for verifier results")
    ap.add_argument("--report", help="JSON report path")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--where", default="", help="SQL WHERE clause to filter relations")
    ap.add_argument("--limit", type=int, default=None, help="Process only first N relations")
    ap.add_argument("--apply", action="store_true", help="Apply results to DB (otherwise just write JSON)")
    ap.add_argument("--dry-run", action="store_true", help="Don't actually modify DB")
    args = ap.parse_args()

    db_path = Path(args.db)
    relations = load_relations_from_db(db_path, args.where)
    print(f"Loaded {len(relations)} relations from {db_path}")

    if args.limit:
        relations = relations[: args.limit]
        print(f"Limited to first {args.limit} relations")

    verified = verify_relations(
        relations,
        model=args.model,
        batch_size=args.batch_size,
        workers=args.workers,
    )

    # Write output
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(verified, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(verified)} verified relations to {out_path}")

    # Stats
    verdict_counts = Counter(r.get("llm_verdict", "missing") for r in verified)
    action_counts = Counter(r.get("llm_verdict_action", "missing") for r in verified)
    print("\n=== LLM VERIFIER GATE RESULTS ===")
    for v, c in verdict_counts.most_common():
        pct = c / len(verified) * 100
        print(f"  {v:20s}: {c:6d} ({pct:.1f}%)")
    print("\n  Actions:")
    for a, c in action_counts.most_common():
        pct = c / len(verified) * 100
        print(f"  {a:20s}: {c:6d} ({pct:.1f}%)")

    # Apply to DB
    if args.apply:
        stats = apply_verifier_results(db_path, verified, dry_run=args.dry_run)
        mode = "DRY RUN" if args.dry_run else "APPLIED"
        print(f"\n=== DB UPDATES ({mode}) ===")
        for action, count in stats.items():
            print(f"  {action}: {count}")

    # Write report
    if args.report:
        report = {
            "gate": "llm_verifier",
            "model": args.model,
            "n_input": len(relations),
            "verdict_distribution": dict(verdict_counts),
            "action_distribution": dict(action_counts),
        }
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()
