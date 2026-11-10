"""Qwen3.5 LLM NER over segmented-sections markdown — Ollama port of notebook Cell 7c.

Semantics mirrored from src/notebooks/pipeline_standalone.ipynb Cell 7c:
* one SYSTEM_PROMPT, JSON response constrained to CDM_TYPES (via Ollama ``format``
  JSON-schema), temperature 0, thinking off (``think=False`` / Ollama chat field)
* 1500-char sentence/whitespace chunking (``llm_chunks``)
* LLM returns (text, type); offsets come from whole-word matches in the chunk
  (``llm_locate``); every occurrence becomes a row, later occurrences flagged
* section skip: backmatter tokens + introduction/background; ``(preamble)`` kept
* disk cache (v3-style key on chunk+prompt+settings), checkpoint/resume

Usage (expects a running Ollama with qwen3.5:4b pulled):
    PYTHONPATH=src python -m cdm_pipeline.ner.qwen_sections \
        --output_dir outputs/results/<dir> [--model qwen3.5:4b] [--host http://127.0.0.1:11434]
"""
import sys
import io
import os
import re
import csv
import json
import time
import hashlib
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from ..config import REPO_ROOT, CDM_TYPES
from .runner_sections import load_sections, SEG_DIR_DEFAULT

LLM_CHUNK_CHARS = 1500
LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0
LLM_PROMPT_VERSION = "cdm-ner-v1-ollama"
LLM_SKIP_TOKENS = ("introduction", "background")  # + backmatter, below
LLM_PARALLEL = 8

SYSTEM_PROMPT = """You extract named entities from microbiome research papers for a common data model.
Return every entity mention in the passage, copying the text EXACTLY as written (same spelling, case, spacing).
Use only these types:
ORGANISM: bacteria, archaea, fungi, viruses, named eukaryotic species and model organisms (not generic words like patients, participants, subjects)
CHEMICAL: small molecules, drugs, metabolites
DISEASE: human diseases and conditions
PROTEIN: proteins, enzymes, genes and gene products
DNA_RNA: DNA/RNA elements (e.g. 16S rRNA gene, primers, plasmids)
CELL_TYPE: cell types
GENOMICS: genomics concepts and sequencing approaches (e.g. shotgun metagenomics, 16S rRNA sequencing)
PATHWAY: biological pathways and processes
LAB_METHOD: laboratory techniques
DATA_ANALYSIS: statistical or computational methods and software
SAMPLE_METHOD: sample collection procedures
CLINICAL: clinical metrics and measurements
EXPERIMENTAL_METHOD: experimental design elements
STUDY_DESIGN: study structure (e.g. cohort study, randomized controlled trial)
Do not tag figure/table references, citations, author names, or licence text. If there are none, return an empty list."""

LLM_SCHEMA = {"type": "object", "properties": {"entities": {"type": "array", "items": {
    "type": "object", "properties": {"text": {"type": "string"},
                                     "type": {"type": "string",
                                              "enum": sorted(CDM_TYPES)}},
    "required": ["text", "type"]}}}, "required": ["entities"]}

CSV_FIELDS = ["term", "labels", "model", "paper", "section_id", "section_path",
              "char_start", "char_end", "llm_occurrence_expanded"]


def is_backmatter(path):
    """Cell 7c: backmatter tokens + introduction/background; (preamble) always kept."""
    from .runner_sections import BACKMATTER_TOKENS
    last = (path or "").split(">")[-1].strip().lower()
    if not last or last == "(preamble)":
        return False
    return any(tok in last for tok in BACKMATTER_TOKENS + LLM_SKIP_TOKENS)


def llm_chunks(text, limit=LLM_CHUNK_CHARS):
    """(start, end) windows, cut after sentence end / whitespace, never mid-word."""
    out, s, n = [], 0, len(text)
    while s < n:
        e = min(s + limit, n)
        if e < n:
            cut = max(text.rfind(". ", s, e), text.rfind("\n", s, e))
            if cut <= s:
                cut = text.rfind(" ", s, e)
            e = cut + 1 if cut > s else e
        if text[s:e].strip():
            out.append((s, e))
        s = e
    return out


def llm_locate(chunk, term):
    """Whole-word occurrences of term in chunk -> [(pos, expanded)]; expanded=0 for first match only."""
    if not term:
        return []
    hits = [m.start() for m in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", chunk)]
    return [(h, 0 if i == 0 else 1) for i, h in enumerate(hits)]


def cache_key(chunk, model):
    h = hashlib.sha256()
    for part in (chunk, SYSTEM_PROMPT, json.dumps(LLM_SCHEMA, sort_keys=True), model,
                 str(LLM_TEMPERATURE), str(LLM_MAX_TOKENS), LLM_PROMPT_VERSION):
        h.update(part.encode("utf-8") if isinstance(part, str) else part)
        h.update(b"\x1f")
    return h.hexdigest()


class OllamaClient:
    def __init__(self, host, model, timeout=600):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, chunk):
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": chunk}],
            "stream": False,
            "think": False,
            "options": {"temperature": LLM_TEMPERATURE, "num_predict": LLM_MAX_TOKENS},
            "format": LLM_SCHEMA,
        }).encode("utf-8")
        req = urllib.request.Request(self.host + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        msg = data.get("message", {}).get("content", "")
        ents = json.loads(msg).get("entities", [])
        return ents if isinstance(ents, list) else []

    def call_with_retry(self, chunk):
        """On truncated/invalid JSON retry once as two halves (notebook retry policy)."""
        try:
            return self.chat(chunk), None
        except Exception:
            pass
        cut = chunk.rfind(" ", 0, len(chunk) // 2)
        try:
            return self.chat(chunk[:cut]) + self.chat(chunk[cut:]), None
        except Exception as ex:
            return None, repr(ex)


def main():
    parser = argparse.ArgumentParser(description="Qwen3.5 section-level LLM NER (Ollama, Cell 7c port)")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--seg_dir", default=str(SEG_DIR_DEFAULT))
    parser.add_argument("--max_files", type=int, default=None)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--parallel", type=int, default=LLM_PARALLEL)
    parser.add_argument("--include_backmatter", action="store_true",
                        help="Also run on backmatter+intro sections (default: Cell 7c skip rule)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "_qwen_sections_cache.json"
    csv_path = output_dir / "qwen_sections_ner.csv"

    units, _ = load_sections(args.seg_dir, args.max_files,
                             body_only=not args.include_backmatter)
    if not args.include_backmatter:
        units = [u for u in units if not is_backmatter(u["path"])]
    total_chars = sum(len(u["text"]) for u in units)
    print("Papers: %d | sections (after Cell-7c skip): %d | chars: %d" % (
        len({u['cid'] for u in units}), len(units), total_chars))

    # 1) chunk the eligible sections
    jobs = []  # (cid, sid, path, chunk_start, chunk_end, key)
    for u in units:
        for s, e in llm_chunks(u["text"]):
            key = cache_key(u["text"][s:e], args.model)
            jobs.append((u["cid"], u["section_id"], u["path"], s, e, key))
    print("Chunks: %d" % len(jobs))

    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [j for j in jobs if j[5] not in cache]
    print("Cached hits: %d | to run: %d" % (len(jobs) - len(todo), len(todo)))

    client = OllamaClient(args.host, args.model)
    errors = []
    t0 = time.time()
    if todo:
        def _run(job):
            cid, sid, path, s, e, key = job
            try:
                ents, err = client.call_with_retry(jobs_text[(cid, sid)][s:e])
                return key, ents, err
            except Exception as ex:
                return key, None, repr(ex)

        jobs_text = {(u["cid"], u["section_id"]): u["text"] for u in units}
        done_ct = 0
        with ThreadPoolExecutor(args.parallel) as pool:
            for key, ents, err in pool.map(_run, todo):
                done_ct += 1
                if err:
                    errors.append(err)
                else:
                    cache[key] = {"entities": ents}
                if done_ct % 25 == 0 or done_ct == len(todo):
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                    el = time.time() - t0
                    rate = done_ct / el if el > 0 else 0
                    eta = (len(todo) - done_ct) / rate if rate > 0 else 0
                    print("  %d/%d chunks (%.0fs, ETA %.0fs, errors %d)" % (
                        done_ct, len(todo), el, eta, len(errors)), flush=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print("Run: %d chunks in %.0fs | errors: %d" % (len(todo), time.time() - t0, len(errors)))

    # 2) locate returned texts in their chunks -> rows
    stats = {"returned": 0, "not_in_text": 0, "bad_type": 0, "located_spans": 0,
             "malformed_entities": 0, "non_string_text_entities": 0,
             "first_match_rows": 0, "expanded_rows": 0, "expanded_by_type": {}}
    rows, seen = [], set()
    for cid, sid, path_name, s, e, key in jobs:
        entry = cache.get(key)
        if entry is None:
            continue
        chunk = None
        for u in units:
            if u["cid"] == cid and u["section_id"] == sid:
                chunk = u["text"][s:e]
                break
        if chunk is None:
            continue
        for ent in entry.get("entities", []):
            if not isinstance(ent, dict):
                stats["malformed_entities"] += 1
                stats["returned"] += 1
                continue
            if not isinstance(ent.get("text"), str):
                # Same guard as src/scripts/vllm_termpop/qwen_sections_vllm.py:
                # the model occasionally emits text as a number (e.g. citation
                # markers "[15]", statistics "-165", bare ints). Count and
                # skip — never silently dropped, always reported.
                stats["non_string_text_entities"] += 1
                stats["returned"] += 1
                continue
            term = ent.get("text").strip()
            typ = ent.get("type", "")
            stats["returned"] += 1
            if typ not in CDM_TYPES:
                stats["bad_type"] += 1
                continue
            hits = llm_locate(chunk, term)
            if not hits:
                stats["not_in_text"] += 1
                continue
            for h, expanded in hits:
                ts, te = s + h, s + h + len(term)
                if (cid, sid, ts, te) in seen:
                    continue
                seen.add((cid, sid, ts, te))
                rows.append({"term": term, "labels": typ, "model": args.model,
                             "paper": cid, "section_id": sid, "section_path": path_name,
                             "char_start": ts, "char_end": te,
                             "llm_occurrence_expanded": expanded})
                stats["located_spans"] += 1
                stats["expanded_rows" if expanded else "first_match_rows"] += 1
                if expanded:
                    stats["expanded_by_type"][typ] = stats["expanded_by_type"].get(typ, 0) + 1

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("Stats: %s" % json.dumps(stats))
    print("Saved %d rows -> %s" % (len(rows), csv_path))
    with open(output_dir / "_qwen_sections_summary.json", "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "sections": len(units), "chunks": len(jobs),
                   "run": len(todo), "errors": len(errors), "stats": stats,
                   "rows": len(rows)}, f, indent=2)


if __name__ == "__main__":
    main()
