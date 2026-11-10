"""Shared engine for the GPU gap stages (docs/gpu_gap_plan.md).

A stage is a pair of functions:
    build(ctx)          -> list of Request
    apply(ctx, results) -> writes the stage outputs (CPU, after all shards ran)

and this module supplies everything else:
  * vLLM OpenAI-compatible client tuned for throughput: many concurrent
    requests (continuous batching), JSON output, deterministic decoding,
    passage-first prompts so requests sharing a passage hit vLLM's prefix cache;
  * truncation handling: a multi-item request whose answer overflows max_tokens
    is retried as two halves, down to single items (a looping single item gets
    no answer instead of failing the run);
  * sharding by stable hash of the request key, so N array tasks split the
    work without coordination, and a resumable per-shard JSONL cache;
  * exact-quote anchoring: a model quote is accepted only if it can be located
    in the source; the STORED quote is then the exact source slice
    text[start:end] (template rule 5), never the model's paraphrase.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

RESULTS = REPO_ROOT / "outputs/results"
GAP_DIR = RESULTS / "gap_runs"

MODELS = {
    "qwen": "Qwen/Qwen3.5-4B",
    "gemma": "google/gemma-4-E4B-it-qat-w4a16-ct",
    "llama": "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4",
}


@dataclass
class Request:
    key: str                     # stable id of the unit of work
    system: str
    prefix: str                  # shared passage / context, sent FIRST (prefix cache)
    items: list                  # list of dicts; split in halves on truncation
    suffix: str                  # instructions after the items
    max_tokens: int = 2048
    meta: dict = field(default_factory=dict)

    def user(self, items=None):
        items = self.items if items is None else items
        return (self.prefix + "\n\nITEMS:\n" + json.dumps(items, ensure_ascii=False)
                + "\n\n" + self.suffix)


def shard_of(key, nshards):
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % nshards


def chat(host, model, system, user, max_tokens, timeout, qwen):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if qwen:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(host.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("finish_reason=length")
    content = (choice.get("message") or {}).get("content") or ""
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    return json.loads(content)


def run_requests(requests, out_path, host, model_key, parallel=96, timeout=900, log=print):
    """Run requests against the server; resumable JSONL cache at out_path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if out_path.exists():
        for line in open(out_path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "error" not in r:
                done[r["key"]] = r
    todo = [r for r in requests if r.key not in done]
    log(f"requests={len(requests)} cached={len(requests) - len(todo)} to_run={len(todo)}")
    model = MODELS[model_key]
    qwen = model_key in ("qwen", "gemma")  # both take chat_template_kwargs enable_thinking

    def ask(rq, items, depth=0):
        last = None
        for _ in range(2):
            try:
                return chat(host, model, rq.system, rq.user(items), rq.max_tokens, timeout, qwen), None
            except Exception as ex:  # noqa: BLE001
                last = repr(ex)
                if "finish_reason=length" in last:
                    break
        if "finish_reason=length" in (last or ""):
            if len(items) == 1:
                return {"_truncated_single": items[0].get("id")}, None
            if depth < 6:
                h = len(items) // 2
                a, ea = ask(rq, items[:h], depth + 1)
                if ea:
                    return None, ea
                b, eb = ask(rq, items[h:], depth + 1)
                if eb:
                    return None, eb
                return {"_parts": [a, b]}, None
        return None, last

    t0, n, errors = time.time(), 0, 0
    with open(out_path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(parallel) as pool:
        futs = {pool.submit(ask, rq, rq.items): rq for rq in todo}
        for fut in as_completed(futs):
            rq = futs[fut]
            ans, err = fut.result()
            rec = {"key": rq.key, "meta": rq.meta}
            if err:
                rec["error"] = err
                errors += 1
            else:
                rec["answer"] = ans
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if n % 200 == 0 or n == len(todo):
                fh.flush()
                el = time.time() - t0
                log(f"  {n}/{len(todo)} done, {errors} errors, {n / max(el, 1):.1f} req/s")
    return errors


def load_results(stage_dir):
    """All shard outputs of a stage -> {key: answer} (last successful wins)."""
    res, failed = {}, set()
    for p in sorted(Path(stage_dir).glob("responses.shard*.jsonl")):
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "error" in r:
                failed.add(r["key"])
            else:
                res[r["key"]] = r["answer"]
                failed.discard(r["key"])
    return res, failed


def flatten(answer, list_key):
    """Collect list_key entries from an answer, including split '_parts'."""
    out = []
    if not isinstance(answer, dict):
        return out
    if "_parts" in answer:
        for p in answer["_parts"]:
            out += flatten(p, list_key)
        return out
    v = answer.get(list_key)
    if isinstance(v, list):
        out += [x for x in v if isinstance(x, dict)]
    elif isinstance(v, dict):  # keyed by id
        out += [dict(x, id=k) for k, x in v.items() if isinstance(x, dict)]
    return out


# ── text and evidence ────────────────────────────────────────────────────────
_SECTIONS = None


def sections():
    """{(paper_id, section_id): (path, text)} from the segmented markdown."""
    global _SECTIONS
    if _SECTIONS is None:
        from cdm_pipeline.ner.runner_sections import load_sections, SEG_DIR_DEFAULT
        units, _ = load_sections(SEG_DIR_DEFAULT, None, body_only=False)
        _SECTIONS = {(u["cid"], u["section_id"]): (u["path"] or "", u["text"] or "") for u in units}
    return _SECTIONS


_BY_PAPER = None


def paper_sections(paper_id):
    global _BY_PAPER
    if _BY_PAPER is None:
        _BY_PAPER = {}
        for (pid, sid), (path, text) in sections().items():
            _BY_PAPER.setdefault(pid, []).append((sid, path, text))
    return _BY_PAPER.get(paper_id, [])


def anchor(quote, text, min_ratio=0.95):
    """Locate a model quote in text -> (start, end, exact_slice) or None.

    Exact substring first, then the normalised/fuzzy relocation from Phase A
    with a strict ratio. The returned slice is the source text itself, so the
    stored quote always satisfies text[start:end] == quote.
    """
    if not quote or not text:
        return None
    q = quote.strip()
    i = text.find(q)
    if i >= 0:
        return i, i + len(q), text[i:i + len(q)]
    import clean_catalogue as cc
    norm, idx = SECTION_NORM_CACHE.get(id(text)) or cc._norm_map(text)
    SECTION_NORM_CACHE[id(text)] = (norm, idx)
    hit = cc.relocate(q, norm, idx, min_ratio=min_ratio)
    if not hit:
        return None
    a, b, _ = hit
    return a, b, text[a:b]


SECTION_NORM_CACHE = {}


def chunk_text(text, limit=12000):
    """Sentence-aligned chunks covering the whole text exactly once."""
    if len(text) <= limit:
        return [(0, len(text))] if text.strip() else []
    out, s = [], 0
    while s < len(text):
        e = min(len(text), s + limit)
        if e < len(text):
            cut = max(text.rfind(". ", s, e), text.rfind("\n", s, e))
            if cut > s + limit // 2:
                e = cut + 1
        out.append((s, e))
        s = e
    return out


def load_records(cat_dir):
    with open(Path(cat_dir) / "catalogue_records.jsonl", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


ID_FIELD = {"datasets": "dataset_id", "data_assets": "asset_id", "cohorts": "cohort_id",
            "samples": "sample_group_id", "assays": "assay_id", "findings": "finding_id"}


def rec_id(r):
    return r["fields"][ID_FIELD[r["entity_type"]]]


def log_to(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg):
        line = time.strftime("[%H:%M:%S] ") + msg
        print(line, flush=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return log


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default
