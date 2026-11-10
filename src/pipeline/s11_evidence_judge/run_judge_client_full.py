"""F2 — full-scale LLM-as-judge client with resume cache.

Copy of run_judge_client_a40.py plus cross-resubmission resume:

  * Cache file ($CACHE, JSON) keyed by
        cache_key = sha1(item_id + "|" + prompt_version)[:16]
    where prompt_version is derived from the prompt template's own hash. Editing a
    prompt therefore invalidates the cache instead of contaminating a re-run with
    stale verdicts.
  * Cache value: {item_id, verdict, confidence, reasoning, retries, timestamp,
    artifact}. For C2 the three type verdicts are stored too.
  * Cache is rewritten atomically (tmp + os.replace) every --cache-every items.
  * Output JSONL is opened in APPEND mode; item_ids already present are skipped,
    so a resubmission never duplicates rows.
  * Cache hits are re-emitted into the output (cheap) so the output file is
    complete even if it was truncated.

Transport is unchanged from the A40 client: stdlib urllib, temperature 0,
max_tokens 512, chat_template_kwargs enable_thinking False, response_format
json_object, no guided decoding, client-side verdict validation, 3 attempts.

Usage:
  python run_judge_client_full.py \
      --input  outputs/logs/llm_judge/input_full_C2.jsonl \
      --output outputs/logs/llm_judge/results/C2_full_verdicts.jsonl \
      --cache  outputs/logs/llm_judge/_judge_full_cache.json \
      --model  google/gemma-4-E4B-it-qat-w4a16-ct \
      --port 8000 --parallel 32 \
      --prompt src/scripts/llm_judge_a40/prompts/judge_C2.txt \
      --progress-every 500
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

VERDICTS = {
    "C1": {"verdict": ["SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "UNCERTAIN"]},
    "C2": {
        "verdict_inventory_type": ["CORRECT", "INCORRECT", "UNCERTAIN"],
        "verdict_canonical_type": ["CORRECT", "INCORRECT", "UNCERTAIN"],
        "verdict_agreement": ["AGREE", "DISAGREE", "UNCERTAIN"],
    },
    "C3": {"verdict": ["VALID", "INVALID", "TOO_BROAD", "TOO_NARROW", "UNCERTAIN"]},
    "C4": {"verdict": ["SENSIBLE", "PLAUSIBLE_BUT_WEAK", "NONSENSE", "UNCERTAIN"]},
}
PRIMARY_FIELD = {"C1": "verdict", "C2": "verdict_agreement", "C3": "verdict", "C4": "verdict"}

TEMPERATURE = 0
MAX_TOKENS = 512
RETRY_LIMIT = 3
_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def render(template, item):
    def sub(m):
        key = m.group(1)
        val = item.get(key, "")
        if isinstance(val, (list, dict)):
            val = json.dumps(val, ensure_ascii=False)
        return "" if val is None else str(val)
    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def cache_key(item_id, prompt_version):
    return hashlib.sha1(("%s|%s" % (item_id, prompt_version)).encode()).hexdigest()[:16]


def _post(host, port, model, prompt_text, timeout=600):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    choice = data["choices"][0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    if not content and msg.get("reasoning_content"):
        content = msg["reasoning_content"]
    return content, choice.get("finish_reason")


def parse_and_validate(content, artifact):
    text = (content or "").strip()
    if not text:
        raise ValueError("empty response content")
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as ex:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"invalid JSON: {ex}") from ex
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError as ex2:
            raise ValueError(f"invalid JSON: {ex2}") from ex2
    if not isinstance(obj, dict):
        raise ValueError("response JSON is not an object")

    spec = VERDICTS[artifact]
    out = {}
    for field, allowed in spec.items():
        val = obj.get(field)
        if not isinstance(val, str):
            raise ValueError(f"missing/non-string field {field}")
        v = val.strip().upper()
        if v not in allowed:
            raise ValueError(f"{field}={val!r} not in {allowed}")
        out[field] = v
    conf = obj.get("confidence")
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = None
    if conf is not None:
        conf = min(1.0, max(0.0, conf))
    reasoning = obj.get("reasoning")
    return out, conf, (reasoning if isinstance(reasoning, str) else "")[:400]


def judge_one(item, artifact, template, model, host, port):
    item_id = item.get("item_id", "")
    prompt_text = render(template, item)
    spec = VERDICTS[artifact]
    reminder = (
        "\n\nYour previous answer was rejected. You MUST return ONLY a JSON object "
        "with these exact keys and values:\n"
        + "\n".join(f'  "{k}": one of {v}' for k, v in spec.items())
        + '\n  "confidence": number 0.0-1.0\n  "reasoning": string (<=200 chars)\n'
        "No prose, no code fence.")
    last_err = None
    t0 = time.time()
    for attempt in range(RETRY_LIMIT):
        text = prompt_text if attempt < 2 else prompt_text + reminder
        try:
            content, finish = _post(host, port, model, text)
            if finish == "length":
                raise ValueError("response truncated by max_tokens (finish_reason=length)")
            verdicts, conf, reasoning = parse_and_validate(content, artifact)
            rec = {
                "item_id": item_id,
                "verdict": verdicts[PRIMARY_FIELD[artifact]],
                "confidence": conf,
                "reasoning": reasoning,
                "model": model,
                "retries": attempt,
                "latency_ms": int((time.time() - t0) * 1000),
            }
            if artifact == "C2":
                rec.update(verdicts)
            return rec
        except (ValueError, json.JSONDecodeError, KeyError, urllib.error.URLError,
                TimeoutError, OSError) as ex:
            last_err = repr(ex)
    return {
        "item_id": item_id, "verdict": None, "confidence": None, "reasoning": "",
        "model": model, "retries": RETRY_LIMIT,
        "latency_ms": int((time.time() - t0) * 1000), "error": last_err,
    }


def load_cache(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        log(f"WARNING: cache {path} unreadable; starting empty")
        return {}


def save_cache_atomic(path, cache):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)
    os.replace(tmp, path)


def load_done_ids(path):
    done = set()
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line).get("item_id"))
            except json.JSONDecodeError:
                continue
    return done


def main():
    ap = argparse.ArgumentParser(description="Full-scale LLM-as-judge client (resume cache)")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--artifact", default=None)
    ap.add_argument("--model", default="google/gemma-4-E4B-it-qat-w4a16-ct")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--parallel", type=int, default=32)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--progress-every", type=int, default=500)
    ap.add_argument("--cache-every", type=int, default=100)
    args = ap.parse_args()

    artifact = args.artifact
    if not artifact:
        m = re.search(r"(C[1-4])", Path(args.input).name)
        if not m:
            sys.exit("FATAL: cannot infer artifact from --input; pass --artifact")
        artifact = m.group(1)
    if artifact not in VERDICTS:
        sys.exit(f"FATAL: unknown artifact {artifact}")

    template = Path(args.prompt).read_text(encoding="utf-8")
    prompt_version = hashlib.sha256(template.encode()).hexdigest()[:12]

    items = []
    with open(args.input, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if args.limit:
        items = items[: args.limit]

    cache = load_cache(args.cache)
    done = load_done_ids(args.output)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    log(f"[{artifact}] {len(items)} items | model={args.model} | parallel={args.parallel}")
    log(f"[{artifact}] cache={args.cache} (entries={len(cache)})")
    log(f"[{artifact}] cache_key = sha1(item_id + '|' + prompt_version)[:16], "
        f"prompt_version={prompt_version}")
    log(f"[{artifact}] output={args.output} (existing rows={len(done)})")

    # Partition: already in output -> skip; in cache -> re-emit; else -> run.
    todo, cached_hits, skipped = [], 0, 0
    for it in items:
        iid = it.get("item_id", "")
        if iid in done:
            skipped += 1
            continue
        if cache_key(iid, prompt_version) in cache:
            cached_hits += 1
        else:
            todo.append(it)
    log(f"[{artifact}] skip_existing={skipped} cache_hits={cached_hits} to_run={len(todo)}")

    t0 = time.time()
    written = 0
    ok = err = 0

    with open(args.output, "a", encoding="utf-8") as out:
        # 1) Re-emit cache hits so the output is complete even after a truncation.
        for it in items:
            iid = it.get("item_id", "")
            if iid in done:
                continue
            ck = cache_key(iid, prompt_version)
            entry = cache.get(ck)
            if not entry:
                continue
            rec = {k: entry.get(k) for k in
                   ("item_id", "verdict", "confidence", "reasoning", "model",
                    "retries", "latency_ms")}
            if artifact == "C2":
                for f in VERDICTS["C2"]:
                    rec[f] = entry.get(f)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
            if rec.get("verdict") is None:
                err += 1
            else:
                ok += 1
        out.flush()

        # 2) Run the missing items.
        since_save = 0
        if todo:
            with ThreadPoolExecutor(max_workers=args.parallel) as pool:
                futs = {pool.submit(judge_one, it, artifact, template, args.model,
                                    args.host, args.port): it for it in todo}
                for fut in as_completed(futs):
                    rec = fut.result()
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    written += 1
                    since_save += 1
                    if rec.get("verdict") is None:
                        err += 1
                    else:
                        ok += 1
                        entry = dict(rec)
                        entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                        entry["artifact"] = artifact
                        cache[cache_key(rec["item_id"], prompt_version)] = entry
                    if since_save >= args.cache_every:
                        out.flush()
                        save_cache_atomic(args.cache, cache)
                        since_save = 0
                    if written % args.progress_every == 0:
                        el = time.time() - t0
                        rate = written / el if el > 0 else 0
                        eta = (len(todo) - (written - (ok + err - (written - len(todo))))) / rate if rate else 0
                        log(f"  {written}/{len(items)} written "
                            f"({el:.0f}s, {rate:.1f}/s, ok={ok}, err={err})")
        out.flush()

    save_cache_atomic(args.cache, cache)
    el = time.time() - t0
    log(f"[{artifact}] done: {ok} judged, {err} failed, {written} written in {el:.0f}s "
        f"({written/el if el else 0:.1f}/s) -> {args.output}")
    log(f"[{artifact}] cache now has {len(cache)} entries")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
