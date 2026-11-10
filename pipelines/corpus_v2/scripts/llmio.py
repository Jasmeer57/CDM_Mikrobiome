"""Shared vLLM client helpers for corpus_v2 LLM stages (51: studies, 52: findings).

Factored from the proven stage-50 implementation so the new stages reuse the
same, tested behaviour: in-job localhost vLLM OpenAI endpoint, thinking
disabled per request, documented-JSON repairs only, and split-retry on
truncated/unparseable output. Stage 50 itself is intentionally left untouched.
"""
import json
import re
import time
import urllib.request


def wait_for_server(port: int, prog, timeout_s: int = 900) -> bool:
    """Poll /v1/models until the in-job vLLM server answers."""
    deadline = time.time() + timeout_s
    url = f"http://127.0.0.1:{port}/v1/models"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5):
                prog.log(f"vLLM ready on port {port}")
                return True
        except Exception:  # noqa: BLE001
            time.sleep(5)
    prog.log(f"vLLM NOT ready after {timeout_s}s on port {port}", level="ERROR")
    return False


def post_chat(port, model, content, max_tokens, temperature):
    """POST one chat completion with enable_thinking=False (template §9 rule:
    the extraction must be reproducible; thinking mode is off for this build)."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    last = None
    for attempt in range(3):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                return json.load(resp)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise last


def repair_json_strict(s: str):
    """Documented repairs only: strip code fences, cut to last balanced brace."""
    s = (s or "").strip()
    s = re.sub(r"^```(json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    start = s.find("{")
    if start == -1:
        raise ValueError("no JSON object in response")
    depth, last_close = 0, -1
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                last_close = i
                break
    if last_close == -1:
        raise ValueError("truncated JSON (unbalanced braces)")
    return json.loads(s[start:last_close + 1])


def split_half(text: str) -> tuple:
    """Split a chunk near the middle at a paragraph boundary."""
    mid = len(text) // 2
    idx = text.rfind("\n\n", 0, mid)
    if idx < 200:
        idx = text.find("\n\n", mid)
    if idx == -1:
        idx = mid
    return text[:idx].strip(), text[idx:].strip()


def make_extractor(cfg, port, out, build_prompt):
    """Return extract(chunk, ci) -> (data, status, error).

    Implements the stage-50 semantics: precise JSON or retry on two half-size
    sub-chunks (depth<2, chunk>=2000 chars); truncation and empty responses
    are PARTIAL/FAILED, never silently accepted as complete. `out` is the
    record dict to which degree/split counters are added.
    """
    model = cfg["llm"]["model"]

    def extract(chunk, ci, depth):
        prompt = build_prompt(chunk)
        resp = post_chat(port, model, prompt, cfg["llm"]["max_tokens"],
                         cfg["llm"]["temperature"])
        choice = resp["choices"][0]
        content = choice["message"]["content"]
        if choice["message"].get("reasoning_content"):
            content = choice["message"]["reasoning_content"] + "\n" + content
        finish = choice.get("finish_reason")
        out["llm_degrees"].append({
            "chunk": ci, "split_depth": depth, "chars": len(chunk),
            "finish_reason": finish, "usage": resp.get("usage"),
            "prompt_sha256": _sha(prompt),
        })
        data, err = None, None
        try:
            data = repair_json_strict(content)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        if data is not None and finish != "length":
            return data, "COMPLETE", None
        if depth < 2 and len(chunk) >= 2000:
            a, b = split_half(chunk)
            if a and b:
                out["llm_split_retries"] += 1
                d1, s1, e1 = extract(a, ci, depth + 1)
                d2, s2, e2 = extract(b, ci, depth + 1)
                merged = merge_data(d1, d2)
                if s1 == "COMPLETE" and s2 == "COMPLETE":
                    return merged, "COMPLETE", None
                return merged, "PARTIAL", e1 or e2 or "split retry incomplete"
        if data is not None:
            return data, "PARTIAL", "finish_reason=length (output truncated)"
        return None, "FAILED", err or "empty response"

    return extract


def _sha(t: str) -> str:
    import hashlib
    return hashlib.sha256((t or "").encode("utf-8", "replace")).hexdigest()


def merge_data(a, b):
    """Merge two parsed JSON objects; lists under shared keys are concatenated,
    scalars keep the first non-null value."""
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            if k not in out or out[k] in (None, "", [], {}):
                out[k] = v
            elif isinstance(out[k], list) and isinstance(v, list):
                out[k] = out[k] + [x for x in v if x not in out[k]]
        return out
    return a
