"""P2 - async vLLM judge client (LLM-as-judge, NOT a human gold standard).

Sends each input item to a Gemma 4 E4B vLLM server (OpenAI-compatible API) using
one metric prompt template, and writes one result record per item.

The extractor under audit is Qwen 3.5:9b; the judge is Gemma 4 E4B — a different
model family. This is an LLM-as-judge evaluation, NOT human validation and NOT a
gold standard.

Result JSONL schema (one object per line):
  item_id, artifact, metric, verdict_json, raw_response, model,
  prompt_version, latency_ms, error

Usage:
  python run_judge_client.py --input  $OUTD/input_C1.jsonl \
      --output $OUTD/results/C1_metric_faithfulness.jsonl \
      --prompt metric_faithfulness --artifact C1 --model <judge-id>
  python run_judge_client.py --prompt metric_faithfulness --dry-run
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

PIPE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(PIPE, "prompts")
PROMPT_VERSION = "judge-gemma4-v1"

# metric template -> artifact slices it applies to (from the P0-P9 spec)
METRIC_ARTIFACTS = {
    "metric_faithfulness": ["C1", "C4"],
    "metric_context_precision": ["C1", "C4"],
    "metric_context_recall": ["C1"],
    "metric_factual_correctness": ["C2", "C3"],
    "metric_instruction_following": ["C1", "C2", "C3", "C4"],
    "metric_completeness": ["C1", "C4"],
    "metric_relevance": ["C2", "C3"],
}
METRICS = list(METRIC_ARTIFACTS)


class _Blank(defaultdict):
    def __missing__(self, key):
        return ""


def load_template(name):
    with open(os.path.join(PROMPTS, name + ".txt")) as fh:
        return fh.read()


def render(template, row):
    return template.format_map(
        _Blank(str, {k: ("" if v is None else v) for k, v in row.items()})
    )


def parse_verdict_json(text):
    """Pull the first JSON object from the model output. Returns (obj, verdict)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    obj = None
    if start >= 0 and end > start:
        try:
            obj = json.loads(t[start:end + 1])
        except Exception:
            obj = None
    verdict = None
    if isinstance(obj, dict):
        verdict = obj.get("verdict")
    return obj, verdict


async def call_one(client, model, prompt_text, retries, sem, max_tokens):
    async with sem:
        delay = 1.0
        last = None
        for attempt in range(retries + 1):
            try:
                t0 = time.time()
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt_text}],
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
                return (resp.choices[0].message.content or "", int((time.time() - t0) * 1000))
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt >= retries:
                    break
                await asyncio.sleep(delay + random.random() * 0.5)
                delay *= 2
        raise last


async def run(args):
    from openai import AsyncOpenAI

    base_url = args.base_url or os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
    api_key = os.environ.get("VLLM_API_KEY", "x")
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    model = args.model or os.environ.get("JUDGE_MODEL", "")
    if not model:
        try:
            ids = [m.id for m in (await client.models.list()).data]
            model = ids[0] if ids else None
        except Exception as e:  # noqa: BLE001
            print("FATAL: could not list models from vLLM (%s)" % e, file=sys.stderr)
            sys.exit(2)
    if not model:
        print("FATAL: no judge model available", file=sys.stderr)
        sys.exit(2)

    template = load_template(args.prompt)
    rows = []
    with open(args.input) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if args.artifact and d.get("artifact") != args.artifact:
                continue
            rows.append(d)
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        print("FATAL: no rows for artifact=%s in %s" % (args.artifact, args.input), file=sys.stderr)
        sys.exit(2)

    print("judge model: %s | metric: %s | artifact: %s | items: %d"
          % (model, args.prompt, args.artifact, len(rows)), flush=True)

    sem = asyncio.Semaphore(args.workers)
    results = []
    failures = 0
    t0 = time.time()
    for i in range(0, len(rows), args.batch_size):
        chunk = rows[i:i + args.batch_size]
        tasks = [call_one(client, model, render(template, r), args.retries, sem, args.max_tokens)
                 for r in chunk]
        outs = await asyncio.gather(*tasks, return_exceptions=True)
        for r, o in zip(chunk, outs):
            rec = {
                "item_id": r.get("item_id"),
                "artifact": r.get("artifact", args.artifact),
                "metric": args.prompt,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if isinstance(o, Exception):
                failures += 1
                rec.update({"verdict_json": None, "raw_response": "", "latency_ms": None,
                            "error": str(o)})
            else:
                raw, ms = o
                obj, verdict = parse_verdict_json(raw)
                rec.update({
                    "verdict_json": obj if isinstance(obj, dict) else {"verdict": verdict},
                    "raw_response": raw,
                    "latency_ms": ms,
                    "error": None,
                })
            results.append(rec)
        done = min(i + args.batch_size, len(rows))
        if done % 200 < args.batch_size or done == len(rows):
            print("  progress %d/%d  failures=%d  %.1fs"
                  % (done, len(rows), failures, time.time() - t0), flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as fh:
        for rec in results:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    rate = failures / max(1, len(rows))
    print("wrote %s | items=%d failures=%d (%.2f%%)"
          % (args.output, len(rows), failures, 100 * rate))
    if rate > 0.01:
        print("FAIL: failure rate > 1%%", file=sys.stderr)
        sys.exit(1)


SAMPLES = {
    "C1": {"item_id": "C1|sample", "artifact": "C1", "entity_type": "samples",
           "claim_text": "sample_type: stool | body_site: gut",
           "evidence_text": "Stool samples were collected from the gut.",
           "context_text": "Methods. Stool samples were collected from the gut. DNA was extracted."},
    "C2": {"item_id": "C2|sample", "artifact": "C2", "inventory_term": "Prevotella",
           "inventory_types": "organism_taxa", "canonical_term_norm": "prevotella",
           "canonical_cdm_type": "ORGANISM",
           "claim_text": "term 'Prevotella' typed as ORGANISM",
           "evidence_text": "Prevotella was enriched in the gut.",
           "context_text": "Prevotella was enriched in the gut."},
    "C3": {"item_id": "C3|sample", "artifact": "C3", "term": "Prevotella",
           "cdm_type": "ORGANISM", "ontology_name": "MESH", "concept_id": "MESH:D001",
           "concept_label": "Prevotella", "definition_context": "genus of bacteria",
           "claim_text": "term 'Prevotella' mapped to MESH:D001 (Prevotella)",
           "evidence_text": "genus of bacteria", "context_text": "genus of bacteria"},
    "C4": {"item_id": "C4|sample", "artifact": "C4", "subject_surface": "Prevotella",
           "subject_type": "organism", "relation": "INCREASED_IN", "object_surface": "gut",
           "object_type": "body_site",
           "claim_text": "Prevotella --INCREASED_IN--> gut",
           "evidence_text": "Prevotella increased in the gut.",
           "context_text": "Prevotella increased in the gut."},
}


def dry_run(args):
    template = load_template(args.prompt)
    print("=== DRY RUN: metric=%s template=%s.txt ===" % (args.prompt, args.prompt))
    arts = [args.artifact] if args.artifact else METRIC_ARTIFACTS[args.prompt]
    for a in arts:
        rendered = render(template, SAMPLES[a])
        print("--- artifact %s (%d chars) ---" % (a, len(rendered)))
        print(rendered)
    print("=== template rendered OK for %s ===" % ",".join(arts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--prompt", required=True, choices=METRICS)
    ap.add_argument("--artifact", default="", choices=["", "C1", "C2", "C3", "C4"])
    ap.add_argument("--model", default=os.environ.get("JUDGE_MODEL", ""))
    ap.add_argument("--base-url", default="")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        dry_run(args)
        return
    if not args.input or not args.output:
        print("FATAL: --input and --output required (or use --dry-run)", file=sys.stderr)
        sys.exit(2)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
