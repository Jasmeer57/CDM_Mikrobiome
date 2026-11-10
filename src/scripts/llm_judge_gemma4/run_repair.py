"""P7 - second-pass judge on flagged items, using the FULL SECTION text.

Reads $OUTD/repair_queue.jsonl (from compute_judge_metrics.py), re-joins each
flagged item to its full section text, re-judges with prompts/repair_fullsection.txt,
and compares the second verdict to the first:

  agree    -> REPAIR_FAILED   (the flag survives a full-context look)
  disagree -> REPAIR_DISPUTED (full context overturns the flag)
  both     -> human queue (do NOT auto-fix anything)

Writes $OUTD/repair_second_pass.jsonl and $OUTD/REPAIR_REPORT.md.

Judge = Gemma 4 E4B (4-bit). This is LLM-as-judge, NOT a human gold standard.

Usage:
  python run_repair.py                       # needs VLLM_BASE_URL / server up
  python run_repair.py --dry-run             # render prompts, no server
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import asyncio
import json
import os
import sys

PIPE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PIPE)
from run_judge_client import (  # noqa: E402
    PROMPT_VERSION, load_template, parse_verdict_json, render,
)

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "llm_judge")
REL = os.path.join(ROOT, "pipelines/corpus_v2", "releases", "2.2.0", "data")
SECTIONS = os.path.join(REL, "sections.jsonl")
MENTIONS = os.path.join(REL, "triple_mentions.jsonl")

# keep the repair prompt within --max-model-len 8192 (~4 chars/token)
MAX_SECTION_CHARS = 12000

VOCAB = {
    "metric_faithfulness": "FAITHFUL | PARTIALLY_FAITHFUL | UNFAITHFUL | UNCERTAIN",
    "metric_factual_correctness": "CORRECT | INCORRECT | UNCERTAIN",
}

AGREE_VERDICT = {
    "metric_faithfulness": "UNFAITHFUL",
    "metric_factual_correctness": "INCORRECT",
}


def load_inputs():
    rows = {}
    for art in ("C1", "C2", "C3", "C4"):
        p = os.path.join(OUTD, "input_%s.jsonl" % art)
        if not os.path.exists(p):
            continue
        with open(p) as fh:
            for line in fh:
                d = json.loads(line)
                rows[d["item_id"]] = d
    return rows


def load_sections():
    bypair, byrec = {}, {}
    with open(SECTIONS) as fh:
        for line in fh:
            d = json.loads(line)
            t = d.get("section_text_original")
            bypair[(d["paper_id"], d["section_id_original"])] = t
            byrec[d["section_record_id"]] = t
    return bypair, byrec


def full_section(item, bypair, byrec):
    """Best-effort full section text for an item, else the context we have.

    Capped at MAX_SECTION_CHARS so the prompt fits --max-model-len 8192; when
    capped we keep a window around the evidence rather than the raw head.
    """
    text = ""
    if item.get("artifact") == "C1" and item.get("paper_id") and item.get("section_id"):
        text = bypair.get((item["paper_id"], item["section_id"])) or ""
    if not text:
        ctx = " ".join(x for x in (item.get("context_before"), item.get("evidence_text"),
                                   item.get("context_after")) if x)
        text = ctx.strip() or item.get("context_sentence") or item.get("definition_context") or ""
    if len(text) <= MAX_SECTION_CHARS:
        return text
    ev = item.get("evidence_text") or ""
    i = text.find(ev) if ev else -1
    if i < 0:
        return text[:MAX_SECTION_CHARS]
    half = MAX_SECTION_CHARS // 2
    return text[max(0, i - half):i - half + MAX_SECTION_CHARS]


def build_prompt(item, metric, first_verdict, section_text):
    tpl = load_template("repair_fullsection")
    return render(tpl, {
        "metric": metric,
        "claim_text": item.get("claim_text", ""),
        "evidence_text": item.get("evidence_text", ""),
        "section_text": section_text,
        "first_verdict": first_verdict,
        "verdict_vocabulary": VOCAB.get(metric, ""),
    })


async def call(client, model, prompt, retries, max_tokens):
    import random
    delay = 1.0
    last = None
    for attempt in range(retries + 1):
        try:
            r = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=max_tokens)
            return r.choices[0].message.content or ""
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
    client = AsyncOpenAI(base_url=base_url, api_key=os.environ.get("VLLM_API_KEY", "x"))
    model = args.model or os.environ.get("JUDGE_MODEL", "")
    if not model:
        ids = [m.id for m in (await client.models.list()).data]
        model = ids[0] if ids else None
    if not model:
        print("FATAL: no judge model", file=sys.stderr)
        sys.exit(2)

    qpath = os.path.join(args.outdir, "repair_queue.jsonl")
    if not os.path.exists(qpath):
        print("no repair_queue.jsonl; nothing to repair")
        return
    queue = [json.loads(l) for l in open(qpath) if l.strip()]
    if args.limit:
        queue = queue[:args.limit]
    items = load_inputs()
    bypair, byrec = load_sections()

    sem = asyncio.Semaphore(args.workers)
    out = []
    t0 = __import__("time").time()
    for i, q in enumerate(queue):
        item = items.get(q["item_id"], {})
        metric = q["metric"]
        first = q["verdict"]
        sec = full_section(item, bypair, byrec)
        prompt = build_prompt(item, metric, first, sec)
        async with sem:
            try:
                raw = await call(client, model, prompt, args.retries, args.max_tokens)
            except Exception as e:  # noqa: BLE001
                raw = ""
                print("  err %s: %s" % (q["item_id"][:40], e), file=sys.stderr)
        _, v2 = parse_verdict_json(raw)
        agrees = (v2 == first)
        out.append({
            "item_id": q["item_id"], "artifact": q["artifact"], "metric": metric,
            "first_verdict": first, "second_verdict": v2,
            "agrees": agrees,
            "disposition": "REPAIR_FAILED" if agrees else "REPAIR_DISPUTED",
            "suggested_action": q.get("suggested_action", "flag-for-human"),
            "raw_response": raw, "model": model, "prompt_version": PROMPT_VERSION,
        })
        if (i + 1) % 25 == 0:
            print("  repair %d/%d  %.0fs" % (i + 1, len(queue), __import__("time").time() - t0),
                  flush=True)

    with open(os.path.join(args.outdir, "repair_second_pass.jsonl"), "w") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_report(args.outdir, out, model)
    print("wrote repair_second_pass.jsonl + REPAIR_REPORT.md (%d items)" % len(out))


def write_report(outdir, out, model):
    failed = [r for r in out if r["disposition"] == "REPAIR_FAILED"]
    disputed = [r for r in out if r["disposition"] == "REPAIR_DISPUTED"]
    lines = [
        "# Repair report (second-pass LLM-as-judge)",
        "",
        "- Judge: Gemma 4 E4B (4-bit) — `%s`" % model,
        "- Pass 1 verdicts come from `JUDGE_METRICS.md`; this pass adds FULL SECTION "
        "text and re-judges only the flagged items.",
        "- **No item is auto-fixed.** Both outcomes go to the human queue.",
        "",
        "| disposition | meaning | count |",
        "|---|---|---:|",
        "| REPAIR_FAILED | full context still yields the flagged verdict | %d |" % len(failed),
        "| REPAIR_DISPUTED | full context overturns the flagged verdict | %d |" % len(disputed),
        "",
        "## Items",
        "",
        "| item_id | artifact | metric | pass1 | pass2 | disposition |",
        "|---|---|---|---|---|---|",
    ]
    for r in out:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            r["item_id"], r["artifact"], r["metric"],
            r["first_verdict"], r["second_verdict"], r["disposition"]))
    lines.append("")
    lines.append("Both `REPAIR_FAILED` and `REPAIR_DISPUTED` items require human review; "
                 "this is LLM-as-judge, NOT human validation.")
    lines.append("")
    with open(os.path.join(outdir, "REPAIR_REPORT.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def dry_run(args):
    items = load_inputs()
    bypair, byrec = load_sections()
    qpath = os.path.join(args.outdir, "repair_queue.jsonl")
    if not os.path.exists(qpath):
        print("no repair_queue.jsonl at", qpath)
        return
    queue = [json.loads(l) for l in open(qpath) if l.strip()][:args.limit or 3]
    for q in queue:
        item = items.get(q["item_id"], {})
        sec = full_section(item, bypair, byrec)
        p = build_prompt(item, q["metric"], q["verdict"], sec)
        print("--- %s (%s) first=%s section_chars=%d ---"
              % (q["item_id"][:50], q["metric"], q["verdict"], len(sec)))
        print(p)
    print("=== repair prompt rendered OK for %d item(s) ===" % len(queue))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTD)
    ap.add_argument("--model", default=os.environ.get("JUDGE_MODEL", ""))
    ap.add_argument("--base-url", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        dry_run(args)
        return
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
