#!/usr/bin/env python3
"""LLM title-correction pass over the v1 corpus (qwen3.5:4b, no-think).

For each record: send the first ~3000 chars of the paper text (title region) plus
the record's current title, ask the model for the exact article title as printed
near the top of the first page. Verification is deterministic: the returned title
must appear verbatim (whitespace-normalized) in the head of the text ->
verified_inline=true; otherwise it is kept but flagged verified_inline=false so
merges can decide precedence (never overwrite a good title with an unverified one).

Resume-safe: one checkpoint per paper (<pid>_title.json). Re-run skips existing
checkpoints unless --force.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from human_microbiome_corpus_builder import _norm_ws, atomic_json, now  # noqa: E402

log = logging.getLogger("title_llm")

VERSION = "1.0.0"

PROMPT = """You extract the exact article title of ONE scientific paper from its first-page text.

Rules:
- Return ONLY the full title as printed near the top of the first page, on one line, no quotes.
- Do NOT return author names, affiliations, journal names, running heads, volume/issue info, \
received/accepted dates, "Original Research"/"Research Article" labels, or page headers \
like "Page 3 of 17".
- If the text contains no recognizable article title, return exactly: NO_TITLE_FOUND

CURRENT TITLE FIELD (may be wrong or junk): {current_title}

FIRST-PAGE TEXT:
{head}"""


def load_text_head(rec: dict, head_chars: int) -> str:
    ft = rec.get("full_text") or {}
    tpath = ft.get("clean_text_path") or ""
    try:
        p = Path(tpath)
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore")[:head_chars]
    except Exception:
        pass
    return ((rec.get("publication") or {}).get("abstract") or "")[:head_chars]


def ollama_chat(host: str, model: str, prompt: str, timeout: int) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.0, "seed": 42, "num_predict": 120,
            "num_ctx": 4096, "top_k": 20, "top_p": 0.8, "repeat_penalty": 1.05,
        },
    }
    req = urllib.request.Request(
        host.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(data["error"])
    content = ((data.get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("empty response from model")
    return content


def looks_like_title(s: str) -> bool:
    """Cheap sanity gate on the model's output."""
    t = _norm_ws(s or "")
    if len(t) < 10 or len(t) > 350:
        return False
    if s.upper() == s or s.isdigit():
        return False
    # author-list pattern: multiple comma+digit superscripts or 'F. Lastname,' runs
    # author-string tell: >=2 'Firstname Lastname,' or 'F. Lastname,' runs
    n_name_commas = len(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z]\.)*\s+[A-Z][a-z]+\s*,", s))
    if n_name_commas >= 2 and not t.endswith((".", "!", "?")):
        return False
    if re.search(r"\b[A-Z]\. ?[A-Z]\.? [A-Z][a-z]+,", s) and s.count(",") >= 2:
        return False
    if re.search(r"\d[,/]", s) and len(t) < 80:
        return False
    bad_markers = ("et al", "page ", "received", "accepted", "http", "@",
                   "correspond", ":?:", "university", "institute", "department",
                   "original research", "research article", "advance online")
    lower = t[:120].lower()
    n_bad = sum(1 for m in bad_markers if m in lower)
    return n_bad <= (1 if len(t) > 60 else 0)


def process_one(args_spec, rec_path: Path, out: Path, force: bool) -> dict:
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    pid = rec.get("paper_id") or rec_path.stem
    ckpt = out / f"{pid}_title.json"
    if ckpt.is_file() and not force:
        return {"pid": pid, "status": "resumed"}
    if force and ckpt.is_file():
        ckpt.unlink()

    pub = rec.get("publication") or {}
    current = _norm_ws(pub.get("title") or "")
    head = load_text_head(rec, args_spec.head_chars)
    prompt = PROMPT.format(current_title=current or "(empty)", head=head)

    content = ollama_chat(args_spec.ollama_host, args_spec.model, prompt, args_spec.timeout)
    title = _norm_ws(content.splitlines()[0]) if content else ""
    title = title.strip('"').strip()

    if title.upper().startswith("NO_TITLE_FOUND") or not looks_like_title(title):
        result = {"paper_id": pid, "llm_title": None, "verified_inline": False,
                  "reason": "no_title_found_or_junk", "current_title": current}
    else:
        norm_head = _norm_ws(head).lower()
        verified = title.lower() in norm_head
        result = {"paper_id": pid, "llm_title": title, "verified_inline": verified,
                  "reason": "verified" if verified else "not_in_head", "current_title": current}
    result.update({"schema_version": VERSION, "extracted_at": now(),
                   "model": args_spec.model, "record_path": str(rec_path)})
    atomic_json(ckpt, result)
    return {"pid": pid, "status": "ok", **{k: result[k] for k in
            ("llm_title", "verified_inline", "reason")}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records", default=str(Path(__file__).resolve().parent.parent /
                                             "outputs/results/human_microbiome_corpus_v1"))
    ap.add_argument("--out", default=None, help="checkpoint dir (default: <records>/llm_titles)")
    ap.add_argument("--ollama-host", default="http://127.0.0.1:11397")
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--head-chars", type=int, default=3000)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--parallel", type=int, default=12)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default=None,
                    help="comma-separated paper_ids to (re)process regardless of checkpoints")
    ap.add_argument("--log-every", type=int, default=25)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    recdir = Path(args.records)
    out = Path(args.out) if args.out else recdir / "llm_titles"
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(recdir.glob("records/*/*.json"))
    if not paths:
        raise SystemExit("no records found under " + str(recdir))

    only = set(args.only.split(",")) if args.only else None
    todo = []
    for p in paths:
        pid = json.loads(p.read_text(encoding="utf-8")).get("paper_id") or p.stem
        if only and pid not in only:
            continue
        if args.force or only or not (out / f"{pid}_title.json").is_file():
            todo.append(p)
    log.info("records: %d total, %d todo (checkpoints skipped)", len(paths), len(todo))
    if not todo:
        log.info("nothing to do")
        return

    rows = []
    done = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futs = {pool.submit(process_one, args, p, out, args.force or bool(only)): p for p in todo}
        for fut in as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception as e:
                rp = futs[fut]
                try:
                    pid = json.loads(rp.read_text(encoding="utf-8")).get("paper_id") or rp.stem
                except Exception:
                    pid = rp.stem
                rows.append({"pid": pid, "status": "error", "error": str(e)[:300]})
                log.warning("FAILED %s: %s", rp, e)
            done += 1
            if done % args.log_every == 0 or done == len(todo):
                rate = done / max(time.monotonic() - start, 0.001)
                log.info("%d/%d (%.2f papers/s, ETA %.1f min)", done, len(todo), rate,
                         (len(todo) - done) / rate / 60)

    log_path = out / "llm_titles_log.csv"
    keys: list = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    tmp = str(log_path) + f".tmp{int(time.time())}"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, log_path)

    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_err = sum(1 for r in rows if r.get("status") == "error")
    n_ver = sum(1 for r in rows if r.get("verified_inline"))
    log.info("pass done: ok=%d error=%d verified_inline=%d | log: %s",
             n_ok, n_err, n_ver, log_path)
    if n_err:
        log.warning("%d papers failed — resubmit to retry only these", n_err)


if __name__ == "__main__":
    main()
