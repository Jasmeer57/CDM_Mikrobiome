"""LLM-as-judge client for the A40 pipeline — stdlib urllib, no OpenAI SDK.

Mirrors the transport style of src/scripts/vllm_termpop/qwen_sections_vllm.py:
  * urllib.request POST to http://<host>:<port>/v1/chat/completions
  * temperature 0, max_tokens 512, chat_template_kwargs {"enable_thinking": False}
  * response_format {"type": "json_object"} — NO guided/schema decoding
  * ThreadPoolExecutor(parallel) — server-side batching provides backpressure
  * client-side JSON parse + verdict-enum validation after the fact

Retry policy (per item, max 3 attempts):
  1. normal call
  2. verbatim retry on truncation / invalid JSON / bad verdict
  3. retry with an explicit "MUST return exactly one of: ..." reminder

No cache / checkpoint semantics: this is a one-shot evaluation.

Output JSONL, one record per item:
  {item_id, verdict, confidence, reasoning, model, retries, latency_ms}
For C2 (three independent type verdicts) the record additionally carries
  verdict_inventory_type, verdict_canonical_type, verdict_agreement
and `verdict` holds the primary (verdict_agreement).

Usage:
  python run_judge_client_a40.py \
      --input  outputs/logs/llm_judge/input_C1.jsonl \
      --output outputs/logs/llm_judge/results/C1_verdicts.jsonl \
      --model  google/gemma-4-E4B-it-qat-w4a16-ct \
      --port 8000 --parallel 32 \
      --prompt src/scripts/llm_judge_a40/prompts/judge_C1.txt
"""
import argparse
import ast
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── per-artifact verdict vocabularies (REVIEW_GUIDELINES.md) ─────────────────
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
# C2's headline verdict for the flat `verdict` field.
PRIMARY_FIELD = {"C1": "verdict", "C2": "verdict_agreement", "C3": "verdict", "C4": "verdict"}

TEMPERATURE = 0
MAX_TOKENS = 512
RETRY_LIMIT = 3  # total attempts per item

# Per-run sampling overrides, populated in main() from CLI args. Defaults keep
# the original Gemma-judge behaviour; multi-judge models override via flags:
#   DeepSeek-R1 distill: --temperature 0.6 --top_p 0.95 --max_tokens 4096
#     (temp 0 causes repetition loops in R1; think block needs the token room)
SAMPLING = {
    "temperature": TEMPERATURE,
    "max_tokens": MAX_TOKENS,
    "top_p": None,
    "chat_template_kwargs": {"enable_thinking": False},  # gemma-compatible
}
_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def render(template, item):
    """Substitute {{field}} placeholders from the input record."""
    def sub(m):
        key = m.group(1)
        val = item.get(key, "")
        if isinstance(val, (list, dict)):
            val = json.dumps(val, ensure_ascii=False)
        return "" if val is None else str(val)

    out = re.sub(r"\{\{(\w+)\}\}", sub, template)
    # An empty evidence field is meaningful (=> UNCERTAIN), make that explicit.
    return out


def _post(host, port, model, prompt_text, timeout=600):
    """One chat completion. Returns (content, finish_reason)."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": SAMPLING["temperature"],
        "max_tokens": SAMPLING["max_tokens"],
        "response_format": {"type": "json_object"},
    }
    if SAMPLING.get("top_p") is not None:
        payload["top_p"] = SAMPLING["top_p"]
    if SAMPLING.get("chat_template_kwargs"):
        payload["chat_template_kwargs"] = SAMPLING["chat_template_kwargs"]
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    choice = data["choices"][0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    if not content and msg.get("reasoning_content"):
        content = msg["reasoning_content"]
    finish = choice.get("finish_reason")
    return content, finish


def _bytes_to_unicode():
    """GPT-2 / Llama byte-level BPE byte<->unicode table (the canonical mapping)."""
    bs = (list(range(ord("!"), ord("~") + 1))
          + list(range(ord("\u00a1"), ord("\u00ac") + 1))
          + list(range(ord("\u00ae"), ord("\u00ff") + 1)))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


# Reverse table: marker char -> original byte (e.g. "Ġ" -> 0x20, "Ċ" -> 0x0a).
_BYTELEVEL_DECODE = {v: k for k, v in _bytes_to_unicode().items()}


def repair_bytelevel(text):
    """Undo leaked byte-level BPE markers in decoded completions.

    DeepSeek-R1-distill-llama-8b-awq ships a byte-level BPE tokenizer with NO
    tokenizer.model (sentencepiece) file, and some vLLM decode paths emit raw
    marker characters instead of applying the ByteLevel decoder: a perfectly
    valid JSON object arrives as '{ĠĠ"verdict":Ġ"SUPPORTED"}' (Ġ=space,
    Ċ=newline) and json.loads fails at line 1 column 2. Re-encode to bytes and
    UTF-8 decode to recover the real text. Falls back to targeted marker
    replacement if the text contains characters outside the 256-byte table.
    """
    if "Ġ" not in text and "Ċ" not in text:
        return text
    try:
        return bytes(_BYTELEVEL_DECODE[ch] for ch in text).decode("utf-8", "replace")
    except KeyError:
        return (text.replace("Ċ", "\n").replace("Ġ", " ")
                    .replace("ĉ", "\t").replace("č", "\r"))


def parse_and_validate(content, artifact):
    """Parse JSON and check every required verdict field against its allowed set.

    Returns (verdicts_dict, confidence, reasoning). Raises ValueError on any
    truncation / parse / validation failure so the caller can retry.
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("empty response content")
    # Undo leaked byte-level BPE markers BEFORE any structural parsing; without
    # this, valid JSON like '{ĠĠ"verdict":Ġ"SUPPORTED"}' is unparseable.
    text = repair_bytelevel(text).strip()
    # Reasoning models (DeepSeek-R1 distills) emit a <think ...>...</think->
    # block before the answer JSON; strip it so json.loads sees the object.
    # An unterminated <think (truncation) leaves no JSON behind -> ValueError
    # -> the caller retries with the explicit-format reminder.
    text = re.sub(r"<think[^>]*>.*?</think\s*>?", "", text,
                  flags=re.S | re.I).strip()
    # Tolerate an accidental code fence even though we asked for bare JSON.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as ex:
        # Some 4-bit judges (DeepSeek-R1 distill) emit Python-style dicts with
        # single quotes ({'verdict': 'SUPPORTED', ...}). ast.literal_eval
        # recovers them safely (literal containers only, no code execution);
        # every field is still validated against VERDICTS below.
        try:
            obj = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            obj = None
        if not isinstance(obj, dict):
            # Last resort: grab the outermost {...}
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
        val_u = val.strip().upper()
        if val_u not in allowed:
            raise ValueError(f"{field}={val!r} not in {allowed}")
        out[field] = val_u

    conf = obj.get("confidence")
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = None
    if conf is not None:
        conf = min(1.0, max(0.0, conf))
    reasoning = obj.get("reasoning")
    reasoning = reasoning if isinstance(reasoning, str) else ""
    return out, conf, reasoning[:400]


def judge_one(item, artifact, template, model, host, port, retry_limit=RETRY_LIMIT):
    item_id = item.get("item_id", "")
    prompt_text = render(template, item)
    spec = VERDICTS[artifact]
    reminder = (
        "\n\nYour previous answer was rejected. You MUST return ONLY a JSON object "
        "with these exact keys and values:\n"
        + "\n".join(f'  "{k}": one of {v}' for k, v in spec.items())
        + '\n  "confidence": number 0.0-1.0\n  "reasoning": string (<=200 chars)\n'
        "No prose, no code fence."
    )
    last_err = None
    last_content = None
    t0 = time.time()
    for attempt in range(retry_limit):
        # Attempt 0/1 are verbatim; attempt 2 appends the explicit reminder.
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
            last_content = None if isinstance(ex, (urllib.error.URLError, TimeoutError, OSError)) else locals().get("content")
            continue
    return {
        "item_id": item_id,
        "verdict": None,
        "confidence": None,
        "reasoning": "",
        "model": model,
        "retries": retry_limit,
        "latency_ms": int((time.time() - t0) * 1000),
        "error": last_err,
        "raw_response_head": (last_content[:500] if last_content else None),
    }


def main():
    ap = argparse.ArgumentParser(description="LLM-as-judge client (A40, urllib)")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--prompt", required=True, help="judge prompt template for the artifact")
    ap.add_argument("--artifact", default=None,
                    help="C1|C2|C3|C4 (default: inferred from --input name)")
    ap.add_argument("--model", default="google/gemma-4-E4B-it-qat-w4a16-ct")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--parallel", type=int, default=32)
    ap.add_argument("--retries", type=int, default=RETRY_LIMIT,
                    help="total attempts per item (default 3)")
    ap.add_argument("--limit", type=int, default=None, help="cap items (smoke test)")
    ap.add_argument("--temperature", type=float, default=SAMPLING["temperature"])
    ap.add_argument("--top_p", type=float, default=None)
    ap.add_argument("--max_tokens", type=int, default=SAMPLING["max_tokens"])
    ap.add_argument("--chat_template_kwargs", default=None,
                    help="JSON string; default keeps {'enable_thinking': False} "
                         "(gemma). Pass '{}' for non-gemma judge models.")
    args = ap.parse_args()

    SAMPLING["temperature"] = args.temperature
    SAMPLING["max_tokens"] = args.max_tokens
    SAMPLING["top_p"] = args.top_p
    if args.chat_template_kwargs is not None:
        SAMPLING["chat_template_kwargs"] = json.loads(args.chat_template_kwargs)

    artifact = args.artifact
    if not artifact:
        m = re.search(r"(C[1-4])", Path(args.input).name)
        if not m:
            sys.exit("FATAL: cannot infer artifact from --input; pass --artifact")
        artifact = m.group(1)
    if artifact not in VERDICTS:
        sys.exit(f"FATAL: unknown artifact {artifact}")

    template = Path(args.prompt).read_text(encoding="utf-8")
    items = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if args.limit:
        items = items[: args.limit]
    log(f"[{artifact}] {len(items)} items | model={args.model} | "
        f"parallel={args.parallel} | prompt={Path(args.prompt).name}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    done = ok = err = 0
    t0 = time.time()
    with open(args.output, "w", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futs = {
                pool.submit(judge_one, it, artifact, template, args.model,
                            args.host, args.port, args.retries): it
                for it in items
            }
            for fut in as_completed(futs):
                rec = fut.result()
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                done += 1
                if rec.get("verdict") is None:
                    err += 1
                else:
                    ok += 1
                if done % 25 == 0 or done == len(items):
                    el = time.time() - t0
                    rate = done / el if el > 0 else 0
                    eta = (len(items) - done) / rate if rate > 0 else 0
                    log(f"  {done}/{len(items)} ({el:.0f}s, {rate:.1f}/s, "
                        f"ETA {eta:.0f}s, ok={ok}, err={err})")

    log(f"[{artifact}] done: {ok} judged, {err} failed -> {args.output}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
