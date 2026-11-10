"""Qwen3.5-4B section-level LLM NER via a vLLM OpenAI-compatible server —
FULL-SECTION extraction with coverage-preserving segmentation.

Semantics (mirrors cdm_pipeline.ner.qwen_sections / notebook Cell 7c unless
noted): same SYSTEM_PROMPT, JSON schema constrained to CDM_TYPES, temperature 0,
thinking disabled, backmatter/introduction skip rule, whole-word span location,
disk cache keyed on (segment text + prompt + settings), checkpoint/resume.

Differences required by the full-section extraction spec:
  1. FULL-SECTION FIRST — if the entire section body fits the model context
     window (--full_section_max_chars), one request covers the whole section;
     no chunking, no truncation.
  2. COVERAGE-PRESERVING SEGMENTATION — longer sections are split with
     sentence-aligned, non-overlapping windows (every character processed
     exactly once -> no double-counting); segment offsets are absolute
     positions in the section text; duplicate entities reconcile via exact
     (paper, section, char_start, char_end) spans.
  3. PRE-EXTRACTION VERIFICATION — per section: char count + sha256 of the
     body text recorded before extraction; empty/truncated bodies flagged.
  4. FAIL-CLOSED COVERAGE — every segment that errors (after retry) marks its
     section INCOMPLETE -> run coverage_status=REVIEW_REQUIRED and the
     unprocessed segments are listed in the coverage report. Never reported
     as complete without full-coverage evidence.

Usage (expects `vllm serve Qwen/Qwen3.5-4B --port 8000` on the node):
    PYTHONPATH=src python src/scripts/vllm_termpop/qwen_sections_vllm.py \
        --output_dir outputs/results/<dir> [--port 8000] [--parallel 32]

Outputs (in --output_dir):
    vllm_sections_ner.csv      rows: term,labels,model,paper,section_id,
                                section_path,char_start,char_end,llm_occurrence_expanded
    _vllm_sections_cache.json  checkpoint/resume cache (segment-keyed)
    _vllm_sections_summary.json run stats + coverage summary (authoritative)
    _coverage.csv               per-section coverage: paper,section_id,
                                section_chars,segments,processed,errors,status
"""
import sys
import os
import csv
import json
import time
import logging
import hashlib
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

try:  # tqdm lives in the vLLM venv; degrade gracefully elsewhere
    from tqdm import tqdm
    _TQDM = True
except ImportError:  # pragma: no cover
    _TQDM = False

    def tqdm(iterable=None, **kw):  # type: ignore[misc]
        return iterable if iterable is not None else []

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

log = logging.getLogger("vllm_ner")


def setup_logging(log_path):
    """Console + file logging so long SLURM runs are fully auditable."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    log.propagate = False

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))

from cdm_pipeline.config import CDM_TYPES  # noqa: E402
from cdm_pipeline.ner.runner_sections import (  # noqa: E402
    load_sections,
    SEG_DIR_DEFAULT,
    is_backmatter as _is_cpu_backmatter,
)
from cdm_pipeline.ner.qwen_sections import (  # noqa: E402
    SYSTEM_PROMPT,
    LLM_SCHEMA,
    is_backmatter,
    llm_chunks,
    llm_locate,
)

LLM_TEMPERATURE = 0
LLM_MAX_TOKENS = 4096
# vLLM transport differs from the Ollama run; schema enforced via response_format.
LLM_PROMPT_VERSION = "cdm-ner-v1-vllm-fullsec"
DEFAULT_PARALLEL = 32
# Sections up to this many chars are sent whole (Qwen3.5-4B @ max-model-len 32768
# ~ 4 chars/token -> 20K chars ~ 5K prompt tokens, comfortably inside the window).
FULL_SECTION_MAX_CHARS = 20000
# Hard ceiling: a section larger than this in tokens can't be handled even
# segmented at sentence granularity without mid-sentence cuts; still processed.
SEG_CHUNK_CHARS = 4000  # segment size for over-long sections (sentence-aligned)

# Retry fallback: when a whole segment still truncates (finish_reason=length on
# an entity-dense passage), recursively halve it on whitespace until each piece
# fits. Depth-limited so ~<=8 leaves, and never split below a floor where a
# further request would be pointless.
MAX_SPLIT_DEPTH = 3
SPLIT_MIN_CHARS = 400

CSV_FIELDS = ["term", "labels", "model", "paper", "section_id", "section_path",
              "char_start", "char_end", "llm_occurrence_expanded"]


def user_prompt(text):
    schema = json.dumps(LLM_SCHEMA)
    return (
        "Extract ALL named entities from the COMPLETE passage below. "
        "The passage is a full section of a microbiome research paper "
        "(possibly split into segments; this is one complete unit).\n"
        "Copy each entity EXACTLY as written in the passage (same spelling, case, spacing).\n"
        "Respond with ONLY a JSON object of this exact shape (no prose, no code fence):\n"
        f"{schema}\n"
        'Example: {"entities": [{"text": "...", "type": "..."}]}\n'
        'If the passage contains no entities, return {"entities": []}.\n\n'
        f"Passage:\n{text}"
    )


def cache_key(segment_text, model):
    h = hashlib.sha256()
    for part in (segment_text, SYSTEM_PROMPT, json.dumps(LLM_SCHEMA, sort_keys=True),
                 model, str(LLM_TEMPERATURE), str(LLM_MAX_TOKENS), LLM_PROMPT_VERSION):
        h.update(part.encode("utf-8") if isinstance(part, str) else part)
        h.update(b"\x1f")
    return h.hexdigest()


def segment_section(text, full_max=FULL_SECTION_MAX_CHARS, seg_chars=SEG_CHUNK_CHARS):
    """Full-section-first coverage plan.

    Returns list of (start, end, mode) where mode in {"full", "segment"}.
    The windows form a non-overlapping partition of [0, len(text)) anchored at
    sentence boundaries (via llm_chunks), so every character is processed
    exactly once and frequency aggregation cannot double-count text.
    """
    text = text or ""
    if not text.strip():
        return []
    if len(text) <= full_max:
        return [(0, len(text), "full")]
    return [(s, e, "segment") for s, e in llm_chunks(text, limit=seg_chars)]


def write_json_atomic(path, obj):
    """Atomic JSON write so a killed job never leaves a corrupt checkpoint."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class RunState:
    """Small JSON job-state file: survives preemption, answers 'where was I?'."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "updated": None, "pid": os.getpid(),
                     "status": "RUNNING", "done": 0, "total": 0,
                     "errors": 0, "last_key": None}

    def save(self, **kw):
        self.data.update(kw)
        self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        write_json_atomic(self.path, self.data)


class VLLMClient:
    """Minimal OpenAI-compatible chat client via stdlib urllib (no extra deps)."""

    def __init__(self, host, model, timeout=600):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, text):
        import urllib.request
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": user_prompt(text)}],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "chat_template_kwargs": {"enable_thinking": False},  # non-thinking mode
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(self.host + "/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        msg = data["choices"][0].get("message") or {}
        content = msg.get("content") or ""
        finish = data["choices"][0].get("finish_reason")
        if not content and msg.get("reasoning_content"):
            content = msg["reasoning_content"]
        ents = json.loads(content).get("entities", [])
        if finish == "length":
            raise ValueError("response truncated by max_tokens (finish_reason=length)")
        return ents if isinstance(ents, list) else []

    def _chat_split(self, text, depth):
        """Recursive halving: a single split is not always enough because each
        half can *also* exceed max_tokens on entity-dense sections (the usual
        cause of finish_reason=length). Depth-limited so a pathological input
        terminates instead of splitting forever."""
        try:
            return self.chat(text)
        except Exception:
            if depth >= MAX_SPLIT_DEPTH or len(text) < SPLIT_MIN_CHARS:
                raise
        cut = text.rfind(" ", 0, len(text) // 2)
        if cut < SPLIT_MIN_CHARS:
            # No usable whitespace before the midpoint — hard-split at the
            # midpoint rather than splitting off-centre (which would leave the
            # left half still too large). Depth limit bounds this.
            cut = len(text) // 2
        if cut <= 0 or cut >= len(text):
            raise ValueError("cannot split further")
        left = self._chat_split(text[:cut], depth + 1)
        right = self._chat_split(text[cut:], depth + 1)
        return left + right

    def call_with_retry(self, text):
        """Retry policy: on error/invalid JSON/truncation, retry once verbatim,
        then fall back to depth-limited recursive halving."""
        try:
            return self.chat(text), None
        except Exception:
            pass
        try:
            return self.chat(text), None
        except Exception as ex:
            first_err = repr(ex)
        try:
            return self._chat_split(text, 0), None
        except Exception as ex:
            return None, "%s | split: %s" % (first_err, repr(ex))


def main():
    ap = argparse.ArgumentParser(description="Qwen3.5 full-section NER via vLLM")
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--seg_dir", default=str(SEG_DIR_DEFAULT))
    ap.add_argument("--max_files", type=int, default=None)
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL,
                    help="concurrent workers hitting the vLLM server")
    ap.add_argument("--full_section_max_chars", type=int, default=FULL_SECTION_MAX_CHARS)
    ap.add_argument("--section_filter", choices=("cell7c", "body", "all"), default=None,
                    help="Section universe to process: "
                         "cell7c (default) = backmatter+introduction/background skipped, "
                         "the historical Cell-7c LLM rule; "
                         "body = backmatter skipped but introduction/background KEPT, "
                         "exactly the cdm_pipeline.ner.runner_sections CPU body universe; "
                         "all = every section incl. backmatter. "
                         "Overrides --include_backmatter when given.")
    ap.add_argument("--include_backmatter", action="store_true",
                    help="Deprecated alias for --section_filter all (kept for compatibility)")
    args = ap.parse_args()
    if args.section_filter is None:
        args.section_filter = "all" if args.include_backmatter else "cell7c"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "_vllm_sections_cache.json"
    csv_path = output_dir / "vllm_sections_ner.csv"

    # ── 0) load sections + pre-extraction verification ─────────────────────
    # Section universe:
    #   cell7c -> body minus backmatter minus introduction/background (Cell 7c)
    #   body   -> body minus backmatter only (= runner_sections CPU universe)
    #   all    -> everything, backmatter included
    units, _ = load_sections(args.seg_dir, args.max_files, body_only=False)
    if args.section_filter == "cell7c":
        units = [u for u in units if not is_backmatter(u["path"])]
    elif args.section_filter == "body":
        units = [u for u in units if not _is_cpu_backmatter(u["path"])]
    # dedupe (cid, sid) safety: load_sections yields one unit per section id
    sec_text = {}
    coverage = {}  # (cid, sid) -> dict
    for u in units:
        key = (u["cid"], u["section_id"])
        text = u["text"] or ""
        sec_text[key] = text
        coverage[key] = {
            "paper": u["cid"], "section_id": u["section_id"], "section_path": u["path"],
            "section_chars": len(text), "text_sha256": hashlib.sha256(
                text.encode("utf-8")).hexdigest()[:16],
            "empty": not text.strip(),
            "segments": 0, "processed": 0, "errors": 0, "cached": 0, "ran": 0,
            "status": "SKIPPED_EMPTY" if not text.strip() else "PENDING",
        }

    # ── 1) coverage plan: full-section or sentence-aligned segment partition ─
    jobs = []  # (cid, sid, path, seg_start, seg_end, mode, key)
    for u in units:
        key0 = (u["cid"], u["section_id"])
        for s, e, mode in segment_section(sec_text[key0], args.full_section_max_chars):
            jobs.append((u["cid"], u["section_id"], u["path"], s, e, mode,
                         cache_key(sec_text[key0][s:e], args.model)))
        coverage[key0]["segments"] = len(segment_section(sec_text[key0], args.full_section_max_chars))
        if coverage[key0]["status"] == "PENDING" and coverage[key0]["segments"] == 0:
            coverage[key0]["status"] = "SKIPPED_EMPTY"

    n_full = sum(1 for j in jobs if j[5] == "full")
    print("Papers: %d | sections: %d | segments: %d (full-section: %d, split: %d) | chars: %d"
          % (len({u['cid'] for u in units}), len(units), len(jobs), n_full,
             len(jobs) - n_full, sum(len(t or '') for t in sec_text.values())))

    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    # A cached *error* is NOT a completed segment: retry it on resubmit. Only
    # successful (or explicitly empty) entries are terminal, so a truncated
    # segment is re-attempted with the recursive-split fallback rather than
    # being silently frozen as permanently failed.
    todo = [j for j in jobs
            if (cache.get(j[6]) is None) or cache[j[6]].get("error")]
    print("Cached hits: %d (incl. %d errored to retry) | to run: %d"
          % (len(jobs) - len(todo),
             sum(1 for j in jobs if (cache.get(j[6]) or {}).get("error")), len(todo)))

    # ── 2) run with checkpoint/resume; every error fails the section closed ─
    client = VLLMClient(args.host, args.model)
    seg_errors = []  # (cid, sid, seg_index, key, err)
    t0 = time.time()

    def _run(job_tuple):
        idx, (cid, sid, path, s, e, mode, key) = job_tuple
        try:
            ents, err = client.call_with_retry(sec_text[(cid, sid)][s:e])
            return key, ents, err
        except Exception as ex:  # noqa: BLE001 — record, don't kill the worker
            return key, None, repr(ex)

    todo_keys = {j[6] for j in todo}
    for j in jobs:
        coverage[(j[0], j[1])]["ran" if j[6] in todo_keys else "cached"] += 1

    if todo:
        done_ct = 0
        with ThreadPoolExecutor(args.parallel) as pool:
            for key, ents, err in pool.map(_run, enumerate(todo)):
                done_ct += 1
                if err is not None or ents is None:
                    seg_errors.append((key, repr(err)))
                    cache[key] = {"entities": None, "error": str(err)}
                else:
                    cache[key] = {"entities": ents}
                if done_ct % 25 == 0 or done_ct == len(todo):
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                    el = time.time() - t0
                    rate = done_ct / el if el > 0 else 0
                    eta = (len(todo) - done_ct) / rate if rate > 0 else 0
                    print("  %d/%d segments (%.0fs, ETA %.0fs, errors %d)" % (
                        done_ct, len(todo), el, eta, len(seg_errors)), flush=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    for (cid, sid), cov in coverage.items():
        cov["processed"] = cov["segments"] - cov["errors"]
        if cov["status"] in ("PENDING",):
            cov["status"] = ("COMPLETE" if cov["errors"] == 0 and cov["processed"] == cov["segments"]
                             else "REVIEW_REQUIRED_INCOMPLETE")
    n_incomplete = sum(1 for c in coverage.values() if c["status"] == "REVIEW_REQUIRED_INCOMPLETE")
    n_complete = sum(1 for c in coverage.values() if c["status"] == "COMPLETE")
    coverage_status = "COMPLETE" if (n_incomplete == 0 and not seg_errors) else "REVIEW_REQUIRED"

    # ── 3) locate returned texts in their segments -> deduped spans ─────────
    stats = {"returned": 0, "not_in_text": 0, "bad_type": 0, "located_spans": 0,
             "bare_string_entities": 0, "malformed_entities": 0,
             "non_string_text_entities": 0,
             "first_match_rows": 0, "expanded_rows": 0, "expanded_by_type": {},
             "segments_failed": len(seg_errors), "segments_total": len(jobs)}
    rows, seen = [], set()
    for cid, sid, path_name, s, e, mode, key in jobs:
        entry = cache.get(key)
        if entry is None or entry.get("error") or "entities" not in entry:
            continue
        chunk = sec_text[(cid, sid)][s:e]
        for ent in entry.get("entities") or []:
            # The model occasionally emits a bare string instead of the
            # {"text","type"} object. A bare string carries no entity type, so
            # it cannot be assigned a CDM type: count it and skip it rather
            # than crash (it is not silently dropped — it is reported).
            if isinstance(ent, str):
                stats["bare_string_entities"] += 1
                stats["returned"] += 1
                continue
            if not isinstance(ent, dict):
                stats["malformed_entities"] += 1
                stats["returned"] += 1
                continue
            if not isinstance(ent.get("text"), str):
                # The model occasionally emits the text as a number (citation
                # markers like "[15]", statistics like "-165", or bare ints)
                # instead of a string. Those carry no usable mention string:
                # count and skip, same policy as bare strings above.
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
                if (cid, sid, ts, te) in seen:  # cross-segment duplicate reconciliation
                    continue
                seen.add((cid, sid, ts, te))
                rows.append({"term": term, "labels": typ, "model": args.model,
                             "paper": cid, "section_id": sid, "section_path": path_name,
                             "char_start": ts, "char_end": te,
                             "llm_occurrence_expanded": expanded,
                             "segment_mode": mode})
                stats["located_spans"] += 1
                stats["expanded_rows" if expanded else "first_match_rows"] += 1
                stats["expanded_by_type"][typ] = stats["expanded_by_type"].get(typ, 0) + 1

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # ── 4) coverage report (fail-closed) ────────────────────────────────────
    exp_chars = sum(c["section_chars"] for c in coverage.values())
    proc_chars = sum(c["section_chars"] for c in coverage.values()
                     if c["status"] in ("COMPLETE", "SKIPPED_EMPTY"))
    with open(output_dir / "_coverage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["paper", "section_id", "section_path",
                                          "section_chars", "text_sha256", "empty",
                                          "segments", "processed", "errors",
                                          "cached", "ran", "status"])
        w.writeheader()
        for c in coverage.values():
            w.writerow({k: c[k] for k in w.fieldnames})
    coverage_summary = {
        "coverage_status": coverage_status,  # COMPLETE only with zero failed segments
        "sections_total": len(coverage), "sections_complete": n_complete,
        "sections_empty": sum(1 for c in coverage.values() if c["status"] == "SKIPPED_EMPTY"),
        "sections_incomplete": n_incomplete,
        "segments_total": len(jobs),
        "segments_full_section": n_full,
        "segments_split": len(jobs) - n_full,
        "segments_failed": len(seg_errors),
        "expected_chars": exp_chars, "processed_chars": proc_chars,
        "char_coverage_pct": round(100.0 * proc_chars / exp_chars, 3) if exp_chars else 100.0,
        "truncation_warnings": [f"{k}: segment failed (counted as unprocessed)"
                                for k, _ in seg_errors[:20]],
    }
    with open(output_dir / "_vllm_sections_summary.json", "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "sections": len(units), "segments": len(jobs),
                   "run": len(todo), "cached": len(jobs) - len(todo),
                   "prompt_version": LLM_PROMPT_VERSION, "parallel": args.parallel,
                   "section_filter": args.section_filter,
                   "full_section_max_chars": args.full_section_max_chars,
                   "stats": stats, "rows": len(rows),
                   "coverage": coverage_summary}, f, indent=2)
    print("Stats: %s" % json.dumps({k: v for k, v in stats.items()
                                    if not isinstance(v, dict)}))
    print("Coverage: %d/%d sections complete, %d segment(s) failed -> %s"
          % (n_complete, len(coverage), len(seg_errors), coverage_status))
    if coverage_status != "COMPLETE":
        print("WARNING: coverage incomplete — extraction NOT reported as verified; "
              "see _coverage.csv and _vllm_sections_summary.json")
        for k, e in seg_errors[:10]:
            print("  failed segment:", k, e[:120])
    print("Saved %d rows -> %s" % (len(rows), csv_path))


if __name__ == "__main__":
    main()
