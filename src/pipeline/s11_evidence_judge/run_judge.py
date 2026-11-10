"""P5 - async vLLM judge runner (LLM-as-judge, NOT a human gold standard).

Extractor under audit: Qwen 3.5:9b. Judge: an independent, cross-family model
served by vLLM (default: google/gemma-4-E4B-it-qat-w4a16-ct). The judge model ID
is read from the vLLM server or --model; no secrets are read.

Reads a JSONL input (see build_inputs.py / sample_stratified.py), renders a
prompt template per item, calls the OpenAI-compatible endpoint, and writes JSONL
results with: item_id, verdict, confidence, reasoning, model, prompt_version,
timestamp.

Usage:
  python run_judge.py --input .../sample_input.jsonl --output .../out.jsonl \
      --prompt c1_record --artifact records --model <judge-id>
  python run_judge.py --prompt c1_record --dry-run
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

# prompt template -> artifact slice it consumes (None = accepts any / all rows)
PROMPT_ARTIFACT = {
    "c1_record": "records",
    "c2_type": "types",
    "c3_mapping": "mappings",
    "c4_triple": "triples",
}
PROMPT_VERSION = "judge-v1"

# verdict field(s) per prompt
PROMPT_VERDICTS = {
    "c1_record": ["verdict"],
    "c2_type": ["verdict_inventory_type", "verdict_canonical_type", "verdict_agreement"],
    "c3_mapping": ["verdict"],
    "c4_triple": ["verdict"],
}


class _Blank(defaultdict):
    def __missing__(self, key):
        return ""


def load_template(name):
    path = os.path.join(PROMPTS, name + ".txt")
    with open(path) as fh:
        return fh.read()


def render(template, row):
    return template.format_map(_Blank(str, {k: ("" if v is None else v) for k, v in row.items()}))


def parse_verdicts(text, prompt):
    """Extract a JSON object from the model output and pull the verdict fields."""
    obj = None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(t[start:end + 1])
        except Exception:
            obj = None
    out = {"confidence": None, "reasoning": ""}
    if isinstance(obj, dict):
        out["confidence"] = obj.get("confidence")
        out["reasoning"] = str(obj.get("reasoning", ""))[:200]
        for v in PROMPT_VERDICTS[prompt]:
            out[v] = obj.get(v)
    for v in PROMPT_VERDICTS[prompt]:
        out.setdefault(v, None)
    return out


async def call_one(client, model, prompt_text, max_retries, sem):
    async with sem:
        delay = 1.0
        for attempt in range(max_retries + 1):
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt_text}],
                    temperature=0.0,
                    max_tokens=512,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(delay + random.random() * 0.5)
                delay *= 2
    return ""


async def run(args):
    from openai import AsyncOpenAI

    base_url = args.base_url or os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
    api_key = os.environ.get("VLLM_API_KEY", "x")
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    model = args.model
    if not model:
        try:
            ids = [m.id for m in (await client.models.list()).data]
            model = ids[0] if ids else None
        except Exception as e:
            print("FATAL: could not list models from vLLM (%s)" % e, file=sys.stderr)
            sys.exit(2)
    if not model:
        print("FATAL: no judge model available", file=sys.stderr)
        sys.exit(2)

    template = load_template(args.prompt)
    want_artifact = PROMPT_ARTIFACT.get(args.prompt)
    rows = []
    with open(args.input) as fh:
        for line in fh:
            d = json.loads(line)
            if args.artifact and d.get("artifact") != args.artifact:
                continue
            if not args.artifact and want_artifact and d.get("artifact") not in (None, want_artifact):
                continue
            rows.append(d)

    if args.limit:
        rows = rows[:args.limit]
    print("judge model: %s | prompt: %s | items: %d" % (model, args.prompt, len(rows)))

    sem = asyncio.Semaphore(args.workers)
    results = []
    failures = 0
    t0 = time.time()
    # process in batches for progress reporting / backpressure
    for i in range(0, len(rows), args.batch_size):
        chunk = rows[i:i + args.batch_size]
        tasks = [call_one(client, model, render(template, r), args.retries, sem) for r in chunk]
        outs = await asyncio.gather(*tasks, return_exceptions=True)
        for r, o in zip(chunk, outs):
            if isinstance(o, Exception):
                failures += 1
                rec = {"item_id": r["item_id"], "error": str(o)}
            else:
                pv = parse_verdicts(o, args.prompt)
                rec = {"item_id": r["item_id"]}
                rec.update(pv)
            rec["model"] = model
            rec["prompt_version"] = PROMPT_VERSION
            rec["timestamp"] = datetime.now(timezone.utc).isoformat()
            results.append(rec)
        done = min(i + args.batch_size, len(rows))
        if done % 100 < args.batch_size or done == len(rows):
            print("  progress %d/%d  failures=%d  %.1fs" % (done, len(rows), failures, time.time() - t0), flush=True)

    with open(args.output, "w") as fh:
        for rec in results:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    rate = failures / max(1, len(rows))
    print("wrote %s | items=%d failures=%d (%.2f%%)" % (args.output, len(rows), failures, 100 * rate))
    if rate > 0.01:
        print("FAIL: failure rate > 1%%", file=sys.stderr)
        sys.exit(1)


def dry_run(args):
    template = load_template(args.prompt)
    print("=== DRY RUN: prompt=%s template=%s ===" % (args.prompt, args.prompt + ".txt"))
    # render against synthetic rows for every prompt to prove templates are valid
    samples = {
        "c1_record": {"claim_text": "sample_type: stool | body_site: gut",
                      "evidence_text": "Stool samples were collected from the gut.",
                      "context_before": "Methods. ", "context_after": " DNA was extracted."},
        "c2_type": {"inventory_term": "Prevotella", "inventory_types": "organism_taxa",
                    "canonical_term_norm": "prevotella", "canonical_cdm_type": "ORGANISM",
                    "canonical_alternative_types": "", "context_sentence": "Prevotella was enriched."},
        "c3_mapping": {"term": "Prevotella", "cdm_type": "ORGANISM", "ontology_name": "MESH",
                       "concept_id": "MESH:D001", "concept_label": "Prevotella",
                       "term_definition": "genus of bacteria"},
        "c4_triple": {"subject_surface": "Prevotella", "subject_type": "organism",
                      "relation": "INCREASED_IN", "object_surface": "gut",
                      "object_type": "body_site", "evidence_text": "Prevotella increased in the gut.",
                      "context_sentence": "Prevotella increased in the gut."},
    }
    if args.input and os.path.exists(args.input):
        with open(args.input) as fh:
            for line in fh:
                d = json.loads(line)
                if not args.artifact or d.get("artifact") == args.artifact:
                    samples[args.prompt] = d
                    break
    rendered = render(template, samples[args.prompt])
    print(rendered)
    print("=== template rendered OK (%d chars) ===" % len(rendered))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--model", default=os.environ.get("JUDGE_MODEL", ""))
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--artifact", default="")
    ap.add_argument("--prompt", required=True,
                    choices=["c1_record", "c2_type", "c3_mapping", "c4_triple"])
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
