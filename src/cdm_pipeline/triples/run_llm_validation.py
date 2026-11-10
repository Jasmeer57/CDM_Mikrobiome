"""Run LLM validation on borderline typed relations using parallel requests."""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

PREDICATE_VERBS = {
    "ASSOCIATED_WITH": "is associated with", "TREATS": "treats", "TREATED_BY": "is treated by",
    "PRODUCES": "produces", "PRODUCED_BY": "is produced by", "DISRUPTS": "disrupts",
    "DEPLETED_IN": "is depleted in", "ENRICHED_IN": "is enriched in",
    "CO_OCCURS_WITH": "co-occurs with", "ENCODES": "encodes", "EXPRESSES": "expresses",
    "PART_OF_PATHWAY": "is part of pathway", "PARTICIPATES_IN": "participates in",
    "IMPLICATED_IN": "is implicated in",
}

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = "phi4-mini:3.8b"
MAX_WORKERS = 8

RESULTS_PATH = str(_CDM_ROOT / "paper/_multi_ner_runs/cdm_output/validation/db_validation_results.json")
LLM_OUT_PATH = str(_CDM_ROOT / "paper/_multi_ner_runs/cdm_output/validation/db_validation_llm_responses.json")


def validate_one(rel):
    verb = PREDICATE_VERBS.get(rel["relationship_type"], rel["relationship_type"])
    prompt = (
        f"Does the evidence support this relationship?\n\n"
        f"Relationship: {rel['subject']} ({rel['subject_type']}) {verb} {rel['object']} ({rel['object_type']})\n"
        f"Evidence: {rel['evidence'][:400]}\n\n"
        f"Answer with: KEEP, FIX (suggest correct predicate), or REJECT. Then explain (1 sentence)."
    )
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": 150},
    }).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
            text = data.get("response", "").strip()
        verdict = "keep"
        tl = text.lower()[:20]
        if "reject" in tl:
            verdict = "reject"
        elif "fix" in tl:
            verdict = "fix"
        return {**rel, "llm_verdict": verdict, "llm_response": text}
    except Exception as e:
        return {**rel, "llm_verdict": "error", "llm_response": str(e)}


def main():
    with open(RESULTS_PATH) as f:
        scored = json.load(f)

    borderline = [r for r in scored if r["tier1_verdict"] == "borderline" and r["score_type"] == "evidence_match"]
    print(f"Borderline typed relations: {len(borderline)}")
    print(f"Using {MAX_WORKERS} parallel workers, model={MODEL}")

    t0 = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(validate_one, rel): rel for rel in borderline}
        done = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            if done % 100 == 0:
                elapsed = time.time() - t0
                rate = done / elapsed
                eta = (len(borderline) - done) / rate
                print(f"  {done}/{len(borderline)} ({rate:.1f}/s, ETA {eta:.0f}s)")

    elapsed = time.time() - t0
    keep = sum(1 for r in results if r["llm_verdict"] == "keep")
    fix = sum(1 for r in results if r["llm_verdict"] == "fix")
    reject = sum(1 for r in results if r["llm_verdict"] == "reject")
    error = sum(1 for r in results if r["llm_verdict"] == "error")
    print(f"\nDone in {elapsed:.1f}s ({len(results)/elapsed:.1f}/s)")
    print(f"LLM verdicts: keep={keep}, fix={fix}, reject={reject}, error={error}")

    # Save LLM responses
    with open(LLM_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Update scored results
    llm_map = {r["id"]: r for r in results}
    for r in scored:
        if r["id"] in llm_map:
            r["llm_verdict"] = llm_map[r["id"]]["llm_verdict"]
            r["llm_response"] = llm_map[r["id"]]["llm_response"]
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(scored, f, indent=2, ensure_ascii=False)

    # Show rejects and fixes
    if reject:
        print(f"\n=== REJECT samples ({reject}) ===")
        for r in [r for r in results if r["llm_verdict"] == "reject"][:10]:
            print(f"  score={r['biolord_score']:.3f}  [{r['subject']}] --{r['relationship_type']}--> [{r['object']}]")
            print(f"  LLM: {r['llm_response'][:150]}")
    if fix:
        print(f"\n=== FIX samples ({fix}) ===")
        for r in [r for r in results if r["llm_verdict"] == "fix"][:10]:
            print(f"  score={r['biolord_score']:.3f}  [{r['subject']}] --{r['relationship_type']}--> [{r['object']}]")
            print(f"  LLM: {r['llm_response'][:150]}")


if __name__ == "__main__":
    main()
