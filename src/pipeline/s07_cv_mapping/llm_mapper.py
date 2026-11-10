"""LLM-enriched ontology mapping — verifies API candidates with qwen3:14b (no-think).

Two-phase pipeline:
  Phase 1: Re-run API mappers (OLS, UMLS, BioPortal, OMOP, NCBI Taxon) in parallel.
           Clean control chars from entity terms before mapping.
  Phase 2: LLM verification + enrichment with qwen3:14b (think=false).
           Batches of 30 entities per LLM call. For each entity the LLM:
             - Verifies the top candidate is semantically correct
             - Disambiguates between multiple candidates
             - Adds a biomedical definition
             - Adds microbiome-research context
             - Scores confidence (0-1)

Inspired by EFRE's normalization_fix.py grounding cascade, but uses LLM-based
semantic validation instead of Gilda + embeddings, and adds definitions/context
(which EFRE doesn't do for ontology mappings).

Reads:  paper/_multi_ner_runs/mapping/deduplicated_entities.json
Writes: paper/_multi_ner_runs/mapping/enriched_entities.json
        paper/_multi_ner_runs/mapping/llm_mapping_checkpoint.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

import requests

from pipeline.config import MAPPING_DIR, UMLS_API_KEY, BIOPORTAL_API_KEY, ENTREZ_API_KEY, CDM_TYPES
from pipeline.s07_cv_mapping.mappers import map_ols, map_umls, map_bioportal, map_omop, map_ncbi_taxon
from pipeline.s07_cv_mapping.confidence import resolve_canonical

# ── Paths ──
INPUT = MAPPING_DIR / "deduplicated_entities.json"
OUTPUT = MAPPING_DIR / "enriched_entities.json"
CHECKPOINT = MAPPING_DIR / "llm_mapping_checkpoint.json"

# ── Config ──
API_MAX_WORKERS = 8
BATCH_SIZE = 30
CHECKPOINT_EVERY = 500
LLM_TIMEOUT = 180
OLLAMA_MODEL = os.environ.get("LLM_MAPPER_MODEL", "qwen3:14b")

# Control char cleanup regex
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

PROMPT_VERSION = "mcdm-llm-mapper-v1"

# ── LLM system prompt (no-think for Qwen3) ──
SYSTEM_PROMPT = (
    "You are a biomedical ontology curator. Do not show your reasoning. "
    "Return ONLY the JSON array requested."
)


def _ensure_ollama_host() -> str:
    """Ensure OLLAMA_HOST has http:// prefix."""
    raw = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if raw and not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"http://{raw}"
        os.environ["OLLAMA_HOST"] = raw
    return raw


def clean_term(term: str) -> str:
    """Remove control chars, normalize Unicode ligatures, and strip whitespace."""
    term = _CTRL_RE.sub("", term)
    term = unicodedata.normalize("NFKD", term)
    term = term.strip()
    return term


# ── Phase 1: API candidate collection ──

def map_one_entity(entity: dict) -> dict:
    """Map a single entity to all available vocabularies (API phase)."""
    term = clean_term(entity["term"])
    cdm_type = entity["cdm_type"]

    if not term:
        return {
            "term": entity["term"],
            "clean_term": "",
            "norm": entity["norm"],
            "cdm_type": cdm_type,
            "sources": entity["sources"],
            "paper_count": entity["paper_count"],
            "mention_count": entity["mention_count"],
            "api_mapping": {
                "canonical": None,
                "all_mappings": [],
                "has_mapping": False,
            },
        }

    candidates: list[dict] = []
    for mapper_fn in (map_ols, map_umls, map_bioportal, map_omop, map_ncbi_taxon):
        try:
            candidates.extend(mapper_fn(term, cdm_type))
        except Exception as ex:
            if "DEBUG_API" in os.environ:
                mapper_name = getattr(mapper_fn, "__name__", str(mapper_fn))
                print(f"    [{mapper_name}] {term[:40]}: {ex}")

    canonical, others = resolve_canonical(candidates, cdm_type)

    return {
        "term": entity["term"],
        "clean_term": term,
        "norm": entity["norm"],
        "cdm_type": cdm_type,
        "sources": entity["sources"],
        "paper_count": entity["paper_count"],
        "mention_count": entity["mention_count"],
        "api_mapping": {
            "canonical": canonical,
            "all_mappings": candidates,
            "has_mapping": canonical is not None,
        },
    }


# ── Phase 2: LLM enrichment ──

def build_enrichment_prompt(entities: list[dict]) -> str:
    """Build the LLM prompt for a batch of entities."""
    items = []
    for i, e in enumerate(entities):
        api = e.get("api_mapping", {})
        canonical = api.get("canonical")
        all_maps = api.get("all_mappings", [])

        # Top 5 candidates (deduplicated by concept_id)
        seen_ids = set()
        cands = []
        for m in all_maps:
            cid = m.get("concept_id", "")
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            cands.append({
                "label": m.get("label", ""),
                "ontology": m.get("ontology_name", ""),
                "concept_id": cid,
                "source": m.get("source", ""),
                "confidence": round(m.get("confidence", 0), 3),
            })
            if len(cands) >= 5:
                break

        items.append({
            "index": i,
            "term": e.get("clean_term", e.get("term", "")),
            "cdm_type": e.get("cdm_type", ""),
            "candidates": cands,
        })

    entities_json = json.dumps(items, indent=2, ensure_ascii=False)

    return f"""You are verifying ontology mappings for microbiome research entities.

For each entity, evaluate its candidate mappings and return a JSON array with one object per entity.

## Evaluation criteria:
1. Is the top candidate semantically correct for this entity and its CDM type?
2. Is the entity a real biomedical concept (not a method artifact, product name, or noise)?
3. If no candidate is correct, set best_index to null.
4. If the entity itself is not biomedical (method artifact, kit name, statistical term), set verified=false and best_index=null.

## For each entity, return:
{{
  "index": <int>,
  "verified": <bool — true if the best candidate is a correct biomedical mapping>,
  "best_index": <int or null — 0-based index into candidates, or null if none is correct>,
  "definition": "<1-2 sentence biomedical definition of the entity, or empty if not biomedical>",
  "context": "<1 sentence: relevance to microbiome research, or empty>",
  "confidence": <0.0-1.0 — your confidence in the mapping>,
  "reason": "<brief reason for your choice>"
}}

## Entities to verify:
{entities_json}

Return ONLY a JSON array. No markdown, no explanation."""


def call_ollama(prompt: str) -> Optional[str]:
    """Call Ollama /api/chat with think=false for Qwen3 models."""
    host = _ensure_ollama_host()
    endpoint = f"{host.rstrip('/')}/api/chat"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_predict": 4096,
            "top_p": 0.9,
        },
    }

    try:
        r = requests.post(endpoint, json=payload, timeout=LLM_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "")
    except Exception as e:
        print(f"  [LLM ERROR] {e}")
        return None


def parse_llm_response(content: str, batch_size: int) -> list[dict]:
    """Parse the LLM JSON array response, handling markdown fences and truncation."""
    if not content:
        return []

    # Strip markdown fences if present
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
        text = text.strip()

    # Find the JSON array
    start = text.find("[")
    if start == -1:
        return []
    end = text.rfind("]")
    if end == -1:
        return []

    try:
        results = json.loads(text[start : end + 1])
        if isinstance(results, list):
            return results
    except json.JSONDecodeError:
        pass

    # Try incremental parse (handles truncated JSON)
    try:
        results = []
        decoder = json.JSONDecoder()
        idx = start
        while idx < end:
            obj, offset = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                results.append(obj)
            idx = offset
            while idx < len(text) and text[idx] not in "{":
                idx += 1
        return results
    except Exception:
        return []


def enrich_batch(batch: list[dict]) -> list[dict]:
    """Send a batch of entities to the LLM for verification + enrichment."""
    prompt = build_enrichment_prompt(batch)
    content = call_ollama(prompt)
    llm_results = parse_llm_response(content, len(batch))

    # Index results by "index" field
    by_index = {}
    for r in llm_results:
        idx = r.get("index")
        if idx is not None and isinstance(idx, int):
            by_index[idx] = r

    # Attach enrichment to each entity
    enriched = []
    for i, e in enumerate(batch):
        llm_data = by_index.get(i, {})
        api = e.get("api_mapping", {})
        all_maps = api.get("all_mappings", [])
        canonical = api.get("canonical")

        # If no API candidates, can't verify
        if not all_maps:
            e["llm_enrichment"] = {
                "verified": False,
                "best_candidate": None,
                "definition": llm_data.get("definition", ""),
                "context": llm_data.get("context", ""),
                "confidence": 0.0,
                "reason": "No API candidates to verify",
                "model": OLLAMA_MODEL,
                "prompt_version": PROMPT_VERSION,
            }
            enriched.append(e)
            continue

        # Resolve best candidate from LLM's best_index
        best_idx = llm_data.get("best_index")
        best_candidate = None
        if best_idx is not None and isinstance(best_idx, int) and 0 <= best_idx < len(all_maps):
            best_candidate = all_maps[best_idx]
        elif canonical and llm_data.get("verified", False):
            best_candidate = canonical

        e["llm_enrichment"] = {
            "verified": llm_data.get("verified", False),
            "best_candidate": best_candidate,
            "definition": llm_data.get("definition", ""),
            "context": llm_data.get("context", ""),
            "confidence": llm_data.get("confidence", 0.0),
            "reason": llm_data.get("reason", ""),
            "model": OLLAMA_MODEL,
            "prompt_version": PROMPT_VERSION,
        }
        enriched.append(e)

    return enriched


# ── Checkpoint ──

def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        with open(CHECKPOINT, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "results": [], "phase": "api"}


def save_checkpoint(cp: dict) -> None:
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False)


# ── Main ──

def main():
    t_start = time.time()

    retry_failed = "--retry-failed" in sys.argv

    # ── Load entities ──
    with open(INPUT, encoding="utf-8") as f:
        entities = json.load(f)
    print(f"Loaded {len(entities)} deduplicated entities from {INPUT.name}")

    # Filter: typed entities with paper_count >= 2 or sources >= 2
    typed = [
        e for e in entities
        if e["cdm_type"] != "ENTITY"
        and (e["paper_count"] >= 2 or len(e["sources"]) >= 2)
    ]
    print(f"  Typed (eligible for mapping): {len(typed)}")
    print(f"  ENTITY-only (skipped): {len(entities) - len(typed)}")

    if retry_failed:
        return _retry_failed(typed, t_start)

    # Normal full run (existing logic)
    _full_run(typed, t_start)


def _retry_failed(typed: list[dict], t_start: float):
    """Re-run API mapping + LLM enrichment for entities that got 0 candidates."""
    print(f"\n{'='*60}")
    print(f"RETRY-FAILED MODE: re-running API mapping for zero-candidate entities")
    print(f"{'='*60}")

    # Load existing results
    if not OUTPUT.exists():
        print(f"ERROR: {OUTPUT} not found. Run full mapping first.")
        return

    with open(OUTPUT, encoding="utf-8") as f:
        results = json.load(f)
    print(f"Loaded {len(results)} existing results")

    # Find entities with 0 API candidates
    by_norm = {r["norm"]: r for r in results}
    failed = [r for r in results if len(r["api_mapping"]["all_mappings"]) == 0]
    print(f"Zero-candidate entities: {len(failed)}")

    if not failed:
        print("Nothing to retry. All entities have candidates.")
        return

    # Re-run API mapping for failed entities (with Unicode normalization now in clean_term)
    print(f"\nRe-running API mapping with {API_MAX_WORKERS} workers...")
    api_t0 = time.time()
    re_mapped = 0
    newly_mapped = 0

    with ThreadPoolExecutor(max_workers=API_MAX_WORKERS) as pool:
        futures = {}
        for r in failed:
            entity = {
                "term": r["term"],
                "norm": r["norm"],
                "cdm_type": r["cdm_type"],
                "sources": r["sources"],
                "paper_count": r["paper_count"],
                "mention_count": r["mention_count"],
            }
            futures[pool.submit(map_one_entity, entity)] = r["norm"]

        for future in as_completed(futures):
            norm = futures[future]
            try:
                result = future.result()
                by_norm[norm] = result
                re_mapped += 1
                if result["api_mapping"]["has_mapping"]:
                    newly_mapped += 1
            except Exception as ex:
                print(f"  [ERROR] {norm}: {ex}")

            if re_mapped % 500 == 0:
                rate = re_mapped / (time.time() - api_t0)
                print(f"  API retry: {re_mapped}/{len(failed)} ({rate:.1f}/s) newly_mapped={newly_mapped}")

    api_elapsed = time.time() - api_t0
    print(f"\nAPI retry done: {re_mapped} re-mapped in {api_elapsed:.1f}s")
    print(f"  Newly mapped: {newly_mapped}")
    print(f"  Still unmapped: {re_mapped - newly_mapped}")

    # Rebuild results list in original order
    results = [by_norm[e["norm"]] for e in typed if e["norm"] in by_norm]

    # Now re-run LLM enrichment for entities that now have candidates but haven't been enriched
    needs_llm = [
        r for r in results
        if r["api_mapping"]["has_mapping"]
        and (
            not r.get("llm_enrichment")
            or r.get("llm_enrichment", {}).get("reason", "") == "No API candidates to verify"
            or (not r.get("llm_enrichment", {}).get("verified")
                and not r.get("llm_enrichment", {}).get("definition"))
        )
    ]
    print(f"\nEntities needing LLM enrichment: {len(needs_llm)}")

    if needs_llm:
        print(f"Batch size: {BATCH_SIZE}")
        est_batches = (len(needs_llm) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"Estimated batches: {est_batches}")

        llm_t0 = time.time()
        enriched_count = 0

        for batch_start in range(0, len(needs_llm), BATCH_SIZE):
            batch = needs_llm[batch_start : batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1

            try:
                enriched = enrich_batch(batch)
                for e in enriched:
                    by_norm[e["norm"]] = e
                    enriched_count += 1
            except Exception as ex:
                print(f"  [BATCH {batch_num} ERROR] {ex}")
                for e in batch:
                    e["llm_enrichment"] = {
                        "verified": False,
                        "best_candidate": None,
                        "definition": "",
                        "context": "",
                        "confidence": 0.0,
                        "reason": f"LLM error: {ex}",
                        "model": OLLAMA_MODEL,
                        "prompt_version": PROMPT_VERSION,
                    }
                    by_norm[e["norm"]] = e
                    enriched_count += 1

            if enriched_count % 300 < BATCH_SIZE:
                elapsed = time.time() - llm_t0
                rate = enriched_count / elapsed if elapsed > 0 else 0
                est_remaining = (len(needs_llm) - enriched_count) / rate / 3600 if rate > 0 else 0
                print(
                    f"  LLM: {enriched_count}/{len(needs_llm)} "
                    f"({rate:.1f}/s, ~{est_remaining:.1f}h left)"
                )

        llm_elapsed = time.time() - llm_t0
        print(f"\nPhase 2 done: {enriched_count} in {llm_elapsed:.1f}s ({llm_elapsed/60:.1f} min)")

    # Rebuild results list
    results = [by_norm[e["norm"]] for e in typed if e["norm"] in by_norm]

    # Write output + summary (shared with full run)
    _write_output_and_summary(results, t_start)


def _full_run(typed: list[dict], t_start: float):

    cp = load_checkpoint()
    done_norms = set(cp["done"].keys())
    results = cp.get("results", [])
    phase = cp.get("phase", "api")

    # ── Phase 1: API mapping ──
    if phase == "api":
        print(f"\n{'='*60}")
        print(f"Phase 1: API candidate collection (OLS, UMLS, BioPortal, OMOP, NCBI Taxon)")
        print(f"{'='*60}")

        todo = [e for e in typed if e["norm"] not in done_norms]
        print(f"Already mapped (checkpoint): {len(done_norms)}")
        print(f"Remaining: {len(todo)}")

        if todo:
            api_t0 = time.time()
            mapped = 0
            with ThreadPoolExecutor(max_workers=API_MAX_WORKERS) as pool:
                futures = {pool.submit(map_one_entity, e): e for e in todo}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        results.append(result)
                        cp["done"][result["norm"]] = True
                        mapped += 1
                    except Exception as ex:
                        e = futures[future]
                        cp["done"][e["norm"]] = False
                        results.append({
                            "term": e["term"],
                            "clean_term": clean_term(e["term"]),
                            "norm": e["norm"],
                            "cdm_type": e["cdm_type"],
                            "sources": e["sources"],
                            "paper_count": e["paper_count"],
                            "mention_count": e["mention_count"],
                            "api_mapping": {
                                "canonical": None,
                                "all_mappings": [],
                                "has_mapping": False,
                            },
                        })
                        mapped += 1

                    if mapped % 500 == 0:
                        save_checkpoint(cp)
                        rate = mapped / (time.time() - api_t0)
                        has = sum(1 for r in results if r["api_mapping"]["has_mapping"])
                        print(f"  API: {mapped}/{len(todo)} ({rate:.1f}/s) mapped={has}")

            save_checkpoint(cp)
            api_elapsed = time.time() - api_t0
            api_has = sum(1 for r in results if r["api_mapping"]["has_mapping"])
            print(f"\nPhase 1 done: {mapped} in {api_elapsed:.1f}s")
            print(f"  API-mapped: {api_has}/{len(results)} ({100*api_has/len(results):.1f}%)")
        else:
            print("Nothing to do (all already mapped via API).")

        # Move to phase 2
        phase = "llm"
        cp["phase"] = "llm"
        save_checkpoint(cp)

    # ── Phase 2: LLM enrichment ──
    if phase == "llm":
        print(f"\n{'='*60}")
        print(f"Phase 2: LLM enrichment with {OLLAMA_MODEL} (think=false)")
        print(f"{'='*60}")

        # Reset done set for LLM phase (we re-process all entities)
        llm_done = set(
            k for k, v in cp["done"].items()
            if isinstance(v, dict) and v.get("llm_done")
        )

        todo = [r for r in results if r["norm"] not in llm_done]
        print(f"LLM-enriched (checkpoint): {len(llm_done)}")
        print(f"Remaining: {len(todo)}")
        print(f"Batch size: {BATCH_SIZE}")
        est_batches = (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"Estimated batches: {est_batches}")

        if todo:
            llm_t0 = time.time()
            enriched_count = 0

            for batch_start in range(0, len(todo), BATCH_SIZE):
                batch = todo[batch_start : batch_start + BATCH_SIZE]
                batch_num = batch_start // BATCH_SIZE + 1

                try:
                    enriched = enrich_batch(batch)
                    for e in enriched:
                        # Update in results list
                        for i, r in enumerate(results):
                            if r["norm"] == e["norm"]:
                                results[i] = e
                                break
                        cp["done"][e["norm"]] = {"llm_done": True}
                    enriched_count += len(enriched)
                except Exception as ex:
                    print(f"  [BATCH {batch_num} ERROR] {ex}")
                    for e in batch:
                        e["llm_enrichment"] = {
                            "verified": False,
                            "best_candidate": None,
                            "definition": "",
                            "context": "",
                            "confidence": 0.0,
                            "reason": f"LLM error: {ex}",
                            "model": OLLAMA_MODEL,
                            "prompt_version": PROMPT_VERSION,
                        }
                        cp["done"][e["norm"]] = {"llm_done": True}

                if enriched_count % 300 < BATCH_SIZE:
                    save_checkpoint(cp)
                    elapsed = time.time() - llm_t0
                    rate = enriched_count / elapsed if elapsed > 0 else 0
                    est_remaining = (len(todo) - enriched_count) / rate / 3600 if rate > 0 else 0
                    verified = sum(
                        1 for r in results
                        if r.get("llm_enrichment", {}).get("verified")
                    )
                    print(
                        f"  LLM: {enriched_count}/{len(todo)} "
                        f"({rate:.1f}/s, ~{est_remaining:.1f}h left) "
                        f"verified={verified}"
                    )

            save_checkpoint(cp)
            llm_elapsed = time.time() - llm_t0
            print(f"\nPhase 2 done: {enriched_count} in {llm_elapsed:.1f}s "
                  f"({llm_elapsed/60:.1f} min)")

    # ── Write output + summary ──
    _write_output_and_summary(results, t_start)


def _write_output_and_summary(results: list[dict], t_start: float):
    """Write enriched_entities.json and llm_mapping_summary.json."""
    print(f"\n{'='*60}")
    print(f"Writing output to {OUTPUT}")
    print(f"{'='*60}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(results)} enriched entities")

    # ── Summary ──
    total = len(results)
    api_mapped = sum(1 for r in results if r["api_mapping"]["has_mapping"])
    llm_verified = sum(
        1 for r in results
        if r.get("llm_enrichment", {}).get("verified")
    )
    llm_with_def = sum(
        1 for r in results
        if r.get("llm_enrichment", {}).get("definition")
    )
    llm_with_ctx = sum(
        1 for r in results
        if r.get("llm_enrichment", {}).get("context")
    )

    by_type: dict[str, dict] = {}
    by_vocab: dict[str, int] = {}
    for r in results:
        t = r["cdm_type"]
        by_type.setdefault(t, {"total": 0, "api": 0, "llm": 0})
        by_type[t]["total"] += 1
        if r["api_mapping"]["has_mapping"]:
            by_type[t]["api"] += 1
        if r.get("llm_enrichment", {}).get("verified"):
            by_type[t]["llm"] += 1
            bc = r["llm_enrichment"].get("best_candidate") or r["api_mapping"].get("canonical")
            if bc:
                v = bc.get("ontology_name", "?")
                by_vocab[v] = by_vocab.get(v, 0) + 1

    print(f"\n{'='*60}")
    print(f"ENRICHED MAPPING SUMMARY")
    print(f"{'='*60}")
    print(f"Total entities:           {total}")
    print(f"API-mapped:                {api_mapped} ({100*api_mapped/total:.1f}%)")
    print(f"LLM-verified:              {llm_verified} ({100*llm_verified/total:.1f}%)")
    print(f"LLM with definition:       {llm_with_def}")
    print(f"LLM with context:          {llm_with_ctx}")
    print(f"\nBy CDM type:")
    for t in sorted(by_type, key=lambda x: -by_type[x]["total"]):
        d = by_type[t]
        print(
            f"  {t:20s}  API: {d['api']:5d}/{d['total']:<5d} "
            f"({100*d['api']/d['total']:.1f}%)  "
            f"LLM: {d['llm']:5d}/{d['total']:<5d} "
            f"({100*d['llm']/d['total']:.1f}%)"
        )
    print(f"\nTop verified vocabularies:")
    for v, c in sorted(by_vocab.items(), key=lambda x: -x[1])[:15]:
        print(f"  {v:20s} {c}")

    # Write summary JSON
    summary = {
        "total": total,
        "api_mapped": api_mapped,
        "api_rate": 100 * api_mapped / total,
        "llm_verified": llm_verified,
        "llm_rate": 100 * llm_verified / total,
        "llm_with_definition": llm_with_def,
        "llm_with_context": llm_with_ctx,
        "by_type": by_type,
        "by_vocab": by_vocab,
        "model": OLLAMA_MODEL,
        "prompt_version": PROMPT_VERSION,
        "api_keys_used": {
            "umls": bool(UMLS_API_KEY),
            "bioportal": bool(BIOPORTAL_API_KEY),
            "entrez": bool(ENTREZ_API_KEY),
        },
    }
    summary_path = MAPPING_DIR / "llm_mapping_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {summary_path}")

    elapsed_total = time.time() - t_start
    print(f"\nTotal elapsed: {elapsed_total:.1f}s ({elapsed_total/60:.1f} min)")


if __name__ == "__main__":
    main()
