"""Shared machinery for the local-model stages (B terms, H definitions, I mappings): prompt files, sharded runs with
checkpoint/resume, and run provenance. A shard appends one JSON line per item to its own file; re-running skips
items already answered, so a job can be resubmitted after a timeout without repeating work.
"""
from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import HERE, now_iso, software_versions


def load_prompt(name: str) -> tuple[str, str, str]:
    path = HERE / "prompts" / name
    text = path.read_text(encoding="utf-8")
    system, user = text.split("USER:", 1)
    system = system.split("SYSTEM:", 1)[1].strip()
    return system, user.strip(), hashlib.sha256(text.encode()).hexdigest()


def fill(template: str, **kw) -> str:
    out = template
    for k, v in kw.items():
        out = out.replace("{" + k + "}", "" if v is None else str(v))
    return out


def shard_items(items: list[dict], shard: int, nshards: int) -> list[dict]:
    return [it for i, it in enumerate(items) if i % nshards == shard]


def done_ids(path: Path, key: str) -> set:
    if not path.exists():
        return set()
    out = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut by a kill; the item is simply redone
            if r.get("response") is not None:
                out.add(r[key])
    return out


def run_items(items: list[dict], key: str, render, llm, out_path: Path, parallel: int, meta: dict) -> dict:
    """render(item) -> (system, user). Writes {key, response, raw, usage, error, ...meta} per item."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    skip = done_ids(out_path, key)
    todo = [it for it in items if it[key] not in skip]
    print(f"{len(items)} items in shard, {len(skip)} already answered, {len(todo)} to run", flush=True)
    lock, n_ok, n_err = threading.Lock(), 0, 0
    with open(out_path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(llm.chat_json, *render(it)): it for it in todo}
        for i, f in enumerate(as_completed(futs), 1):
            it, res = futs[f], f.result()
            rec = {key: it[key], "response": res.get("parsed"), "raw": res.get("raw"), "error": res.get("error"),
                   "usage": res.get("usage"), "attempts": res.get("attempts"), "answered_at": now_iso(), **meta}
            with lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                n_ok += rec["response"] is not None
                n_err += rec["response"] is None
            if i % 500 == 0:
                print(f"  {i}/{len(todo)} done ({n_err} failed)", flush=True)
    return {"shard_items": len(items), "skipped_done": len(skip), "ran": len(todo), "ok": n_ok, "failed": n_err}


def provenance(cfg: dict, stage: str, prompt_sha: str, served_model: str, extra: dict) -> dict:
    return {"stage": stage, "model": cfg["local_llm"]["model"], "served_model": served_model,
            "prompt_sha256": prompt_sha, "temperature": cfg["local_llm"]["temperature"],
            "software": software_versions(), "started": now_iso(), **extra}
