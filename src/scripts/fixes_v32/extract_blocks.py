"""Catalogue findings from TABLE / TABLE_CAPTION / FIGURE_CAPTION blocks (catalogue 3.2.0-candidate).

Reuses the catalogue_v3_1 extractor contract verbatim (src/scripts/vllm_termpop/catalogue_ner.py: system prompt,
findings field list, user-prompt builder, placeholder cleaning) so the records are comparable with the prose
catalogue. Two additions only: a one-line PASSAGE TYPE note in front of the passage, and JSON-schema constrained
decoding (vLLM structured outputs) of the findings object. Thinking disabled, temperature 0, local model only.

    python src/scripts/fixes_v32/extract_blocks.py prepare          # login node: blocks.jsonl -> units.jsonl
    python src/scripts/fixes_v32/extract_blocks.py run --port P --model M --out DIR [--limit N]   # inside SLURM
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "src/scripts/vllm_termpop")]
import catalogue_ner as CN  # noqa: E402  (prompt + contract of the catalogue_v3_1 extractor, imported read-only)

OUT = ROOT / "outputs/results/catalogue_tables_captions_v32_2026-11-11"
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
FIELDS = CN.ENTITY_SPECS["findings"][3]
PROMPT_VERSION = CN.LLM_PROMPT_VERSION + "+blocks-v1"
MAX_UNIT_CHARS = 6000
TYPE_NOTE = {
    "TABLE": ("a TABLE from the paper, flattened from PDF: the table caption first, then the table cells in reading "
              "order (often one cell per line). Read rows and column headers together; a finding needs the taxon or "
              "feature, the groups compared and, if shown, the direction."),
    "FIGURE_CAPTION": "a FIGURE CAPTION (legend) from the paper. Extract only findings the caption text itself states.",
    "TABLE_CAPTION": "a TABLE CAPTION from the paper (the table body is not available). Extract only findings the caption states.",
}
DIRECTIONS = ["INCREASE", "DECREASE", "NO_ASSOCIATION", "MIXED", "NOT_STATED"]
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["findings"],
    "properties": {"findings": {"type": "array", "maxItems": 60, "items": {
        "type": "object", "additionalProperties": False, "required": ["evidence_text", "direction"],
        "properties": {f: ({"type": "string", "enum": DIRECTIONS} if f == "direction" else {"type": "string"})
                       for f in FIELDS}}}}}


def user_prompt(text, block_type):
    return "PASSAGE TYPE: " + TYPE_NOTE[block_type] + "\n\n" + CN.build_user_prompt(text, ["findings"])


# ------------------------------------------------------------------ prepare (login node, CPU)
def split_lines(text, start, limit):
    """Line-aligned windows of <= limit chars -> [(abs_start, abs_end)] partitioning [start, start+len(text))."""
    out, s, pos = [], 0, 0
    for ln in text.split("\n"):
        e = pos + len(ln) + 1
        if e - s > limit and pos > s:
            out.append((start + s, start + pos))
            s = pos
        pos = e
    out.append((start + s, start + len(text)))
    return out


def cmd_prepare(a):
    blocks = [json.loads(l) for l in open(OUT / "blocks.jsonl", encoding="utf-8")]
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    texts = {}
    for pid, sid in {(b["paper_id"], b["section_id"]) for b in blocks}:
        texts[(pid, sid)] = c.execute("SELECT section_text_original FROM section WHERE paper_id=? AND section_id_original=?",
                                      (pid, sid)).fetchone()[0]
    caption_of_table = {(b["paper_id"], b["section_id"], b["caption_char_start"]) for b in blocks if b["block_type"] == "TABLE"}
    units = []
    for b in blocks:
        key = (b["paper_id"], b["section_id"])
        t = texts[key]
        if b["block_type"] == "TABLE_CAPTION" and (b["paper_id"], b["section_id"], b["char_start"]) in caption_of_table:
            continue  # extracted together with its table body
        if b["block_type"] == "TABLE":
            cap_s = b["caption_char_start"]
            cap = next(x for x in blocks if x["paper_id"] == b["paper_id"] and x["section_id"] == b["section_id"]
                       and x["block_type"] == "TABLE_CAPTION" and x["char_start"] == cap_s)
            wins = split_lines(t[b["char_start"]:b["char_end"]], b["char_start"], MAX_UNIT_CHARS)
            for k, (s, e) in enumerate(wins):
                units.append({"unit_id": f"{b['block_id']}#{k}", "block_id": b["block_id"], "paper_id": b["paper_id"],
                              "section_id": b["section_id"], "block_type": "TABLE", "label": b["label"],
                              "supplementary": b["supplementary"],
                              "spans": [[cap["char_start"], cap["char_end"], "TABLE_CAPTION"], [s, e, "TABLE"]],
                              "text": t[cap["char_start"]:cap["char_end"]] + "\n" + t[s:e]})
        else:
            for k, (s, e) in enumerate(split_lines(b["text"], b["char_start"], MAX_UNIT_CHARS)):
                units.append({"unit_id": f"{b['block_id']}#{k}", "block_id": b["block_id"], "paper_id": b["paper_id"],
                              "section_id": b["section_id"], "block_type": b["block_type"], "label": b["label"],
                              "supplementary": b["supplementary"], "spans": [[s, e, b["block_type"]]], "text": t[s:e]})
    with open(OUT / "units.jsonl", "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units))
    print(len(units), "units", dict(Counter(u["block_type"] for u in units)),
          "max chars", max(len(u["text"]) for u in units))


# ------------------------------------------------------------------ run (SLURM, vLLM)
def chat(port, model, text, block_type, timeout=900):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": CN.CATALOGUE_SYSTEM_PROMPT},
                     {"role": "user", "content": user_prompt(text, block_type)}],
        "temperature": CN.LLM_TEMPERATURE, "max_tokens": CN.LLM_MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"name": "catalogue_findings", "schema": SCHEMA, "strict": True}},
    }).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    ch = data["choices"][0]
    if ch.get("finish_reason") == "length":
        raise ValueError("finish_reason=length")
    return json.loads(ch["message"]["content"])["findings"], data.get("usage", {})


def run_unit(port, model, u):
    """Whole unit first; on failure halve it at a line boundary (table body only), depth <= 2. Fail-closed."""
    def go(text, depth):
        try:
            return chat(port, model, text, u["block_type"])[0], None
        except Exception as ex:  # noqa: BLE001
            err = repr(ex)
        if depth >= 2 or len(text) < 1500:
            return None, err
        cut = text.rfind("\n", 0, len(text) // 2)
        cut = cut if cut > 0 else CN.best_cut(text)
        if cut <= 0:
            return None, err
        head = text[:text.find("\n") + 1] if u["block_type"] == "TABLE" else ""  # keep the caption as context
        parts = [text[:cut], (head + text[cut:]) if head and not text[cut:].startswith(head) else text[cut:]]
        out = []
        for p in parts:
            r, e = go(p, depth + 1)
            if e:
                return None, e
            out += r
        return out, None
    t0 = time.time()
    recs, err = go(u["text"], 0)
    return {"unit_id": u["unit_id"], "status": "OK" if err is None else "FAILED", "error": err,
            "records": [CN.normalise_record("findings", r, set(FIELDS)) for r in (recs or []) if isinstance(r, dict)],
            "seconds": round(time.time() - t0, 2)}


def cmd_run(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    units = [json.loads(l) for l in open(OUT / "units.jsonl", encoding="utf-8")]
    if a.limit:
        units = units[: a.limit]
    with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/v1/models", timeout=30) as r:
        served = [m["id"] for m in json.loads(r.read())["data"]]
    if a.model not in served:
        sys.exit(f"server serves {served}, not {a.model}")
    part = out / f"raw_{os.environ.get('SLURM_JOB_ID', 'local')}.jsonl"
    done, res, t0 = 0, [], time.time()
    with ThreadPoolExecutor(a.parallel) as ex:
        futs = {ex.submit(run_unit, a.port, a.model, u): u for u in units}
        for f in as_completed(futs):
            r = f.result()
            r.update(model=a.model, prompt_version=PROMPT_VERSION,
                     system_prompt_sha256=hashlib.sha256(CN.CATALOGUE_SYSTEM_PROMPT.encode()).hexdigest())
            res.append(r)
            done += 1
            if done % 200 == 0 or done == len(units):
                tmp = part.with_suffix(".tmp")
                tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in res), encoding="utf-8")
                os.replace(tmp, part)
                print(f"{done}/{len(units)} units, {sum(len(x['records']) for x in res)} records, "
                      f"{sum(x['status'] != 'OK' for x in res)} failed, {time.time() - t0:.0f}s", flush=True)
    st = Counter(x["status"] for x in res)
    (out / f"run_{os.environ.get('SLURM_JOB_ID', 'local')}.json").write_text(json.dumps({
        "units": len(units), "status": dict(st), "records": sum(len(x["records"]) for x in res),
        "model": a.model, "prompt_version": PROMPT_VERSION, "schema": SCHEMA, "seconds": round(time.time() - t0, 1)},
        indent=2))
    print("done", dict(st))
    if st.get("FAILED"):
        print("WARNING: failed units are reported as FAILED (fail-closed), not silently dropped")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    r = sub.add_parser("run")
    r.add_argument("--port", type=int, required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--out", default=str(OUT))
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--parallel", type=int, default=48)
    a = ap.parse_args()
    {"prepare": cmd_prepare, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
