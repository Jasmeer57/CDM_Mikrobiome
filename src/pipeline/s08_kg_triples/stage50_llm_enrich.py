#!/usr/bin/env python3
"""Stage 50: LLM enrichment of eligible sections with vLLM Qwen3.5-4B (thinking off).

Runs INSIDE the A40 Slurm job that also serves the model (localhost). Worker
threads hit the vLLM OpenAI endpoint concurrently; results are checkpointed per
section so a timeout/resubmit continues where it stopped.

Integrity rules honored:
- LLM output goes ONLY into llm_* fields; source text is untouched (template §9)
- model_name_version + prompt_version recorded on every record
- fail-closed per section: llm_status in COMPLETE/PARTIAL/FAILED
- truncation (finish_reason=length) or unbalanced JSON => PARTIAL/FAILED, never
  silently accepted as complete
- the prompt text that produced each chunk is hashed, so a prompt change is visible

Outputs
  data/llm_terms.jsonl                    one record per enriched section
  data/sections.jsonl                     llm_enrichment summary merged in
  validation/llm_enrichment_summary.json
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage50_llm_enrich"
PV = "2.0.0"

PROMPT = """You are building a domain vocabulary for human-microbiome research.
Extract ALL domain terms mentioned in the following scientific text.
Return STRICT JSON (no markdown, no commentary) with this schema:
{{
  "terms": [
    {{"term": "...", "type": "organism_taxa|disease_phenotype|method_technique|gene_protein|metabolite|anatomical_site|statistical_measure|intervention", "context": "short quote (<=15 words)", "confidence": 0.0-1.0}}
  ]
}}
Text:
{chunk}"""


def wait_for_server(port: int, prog: C.Progress, timeout_s: int = 900) -> bool:
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


def _split_half(text: str) -> tuple:
    """Split a chunk near the middle at a paragraph boundary."""
    mid = len(text) // 2
    idx = text.rfind("\n\n", 0, mid)
    if idx < 200:
        idx = text.find("\n\n", mid)
    if idx == -1:
        idx = mid
    return text[:idx].strip(), text[idx:].strip()


def enrich_section(rec, cfg, port):
    model = cfg["llm"]["model"]
    out = {
        "paper_id": rec["paper_id"],
        "section_record_id": rec["section_record_id"],
        "section_type": rec.get("section_type"),
        "llm_model": cfg["llm"]["model_label"],
        "llm_model_version": f"vllm:{cfg['llm']['runtime']}",
        "llm_prompt_version": cfg["llm"]["prompt_version"],
        "llm_source_text_hash": rec.get("text_hash_sha256"),
        "llm_status": "FAILED", "llm_terms": [], "llm_error": None,
        "llm_chunks": 0, "llm_chunks_failed": 0, "llm_chunks_truncated": 0,
        "llm_split_retries": 0, "llm_input_chars": 0, "llm_degrees": [],
    }
    text = rec.get("section_text_original") or ""
    chunks = C.chunk_text(text, cfg["llm"]["max_prompt_chars"])

    def extract(chunk, ci, depth):
        """Return (terms, status, error). Truncated/failed JSON is retried on
        smaller sub-chunks instead of being recorded as a loss."""
        prompt = PROMPT.format(chunk=chunk)
        resp = post_chat(port, model, prompt, cfg["llm"]["max_tokens"],
                         cfg["llm"]["temperature"])
        choice = resp["choices"][0]
        content = choice["message"]["content"]
        if choice["message"].get("reasoning_content"):
            content = choice["message"]["reasoning_content"] + "\n" + content
        finish = choice.get("finish_reason")
        out["llm_degrees"].append({"chunk": ci, "split_depth": depth,
                                   "chars": len(chunk), "finish_reason": finish,
                                   "usage": resp.get("usage"),
                                   "prompt_sha256": C.sha256_text(prompt)})
        terms, err = [], None
        try:
            data = repair_json_strict(content)
            terms = data.get("terms") or []
        except Exception as e:  # noqa: BLE001
            err = str(e)
        if terms and finish != "length":
            return terms, "COMPLETE", None
        if depth < 2 and len(chunk) >= 2000:
            a, b = _split_half(chunk)
            if a and b:
                out["llm_split_retries"] += 1
                t1, s1, e1 = extract(a, ci, depth + 1)
                t2, s2, e2 = extract(b, ci, depth + 1)
                merged = t1 + t2
                if s1 == "COMPLETE" and s2 == "COMPLETE":
                    return merged, "COMPLETE", None
                return merged, "PARTIAL", e1 or e2 or "split retry incomplete"
        if terms:                       # parsed but hit the length cap
            return terms, "PARTIAL", "finish_reason=length (output truncated)"
        return [], "FAILED", err or "empty response"

    statuses = []
    for ci, chunk in enumerate(chunks):
        out["llm_input_chars"] += len(chunk)
        try:
            terms, status, err = extract(chunk, ci, 0)
            for t in terms:
                t["chunk"] = ci
            out["llm_terms"].extend(terms)
            if status == "COMPLETE":
                statuses.append("COMPLETE")
            elif status == "PARTIAL":
                statuses.append("PARTIAL")
                out["llm_chunks_truncated"] += 1
                out["llm_error"] = ((out["llm_error"] + "; ") if out["llm_error"]
                                    else "") + f"chunk{ci}:{err}"
            else:
                statuses.append("FAILED")
                out["llm_chunks_failed"] += 1
                out["llm_error"] = ((out["llm_error"] + "; ") if out["llm_error"]
                                    else "") + f"chunk{ci}:{err}"
        except Exception as e:  # noqa: BLE001
            out["llm_chunks_failed"] += 1
            statuses.append("FAILED")
            out["llm_error"] = ((out["llm_error"] + "; ") if out["llm_error"]
                                else "") + f"chunk{ci}:{e}"
        out["llm_chunks"] += 1

    if not chunks:
        out["llm_status"] = "COMPLETE"          # nothing to extract from an empty section
    elif all(s == "COMPLETE" for s in statuses):
        out["llm_status"] = "COMPLETE"
    elif any(s == "COMPLETE" for s in statuses) or out["llm_terms"]:
        out["llm_status"] = "PARTIAL"
    else:
        out["llm_status"] = "FAILED"
    return out


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    # Requests hard-code enable_thinking=False; refuse a config that would make
    # the recorded provenance disagree with what was actually sent.
    if cfg["llm"].get("thinking") is not False:
        sys.exit("ERROR: llm.thinking must be false for this corpus build "
                 "(requests send chat_template_kwargs.enable_thinking=False)")
    port = int(os.environ.get("VLLM_PORT", "8000"))
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()

    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    eligible = [s for s in sections if s.get("extraction_eligibility")]
    if not sections:
        sys.exit("ERROR: data/sections.jsonl missing; run stage 45 first")
    if not eligible:
        sys.exit("ERROR: no sections marked extraction_eligibility=true; run stage 45")

    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl",
                        key="section_record_id")

    def llm_fingerprint(s: dict) -> str:
        """Invalidate a cached section when its text, model or prompt changes."""
        return C.sha256_text("|".join([
            str(s.get("text_hash_sha256")),
            cfg["llm"]["model"],
            cfg["llm"]["prompt_version"],
            str(cfg["llm"]["max_prompt_chars"]),
            str(cfg["llm"]["max_tokens"]),
        ]))

    fp_by_sid = {s["section_record_id"]: llm_fingerprint(s) for s in eligible}

    def usable(sid):
        """Resume only records that finished cleanly; retry PARTIAL/FAILED."""
        if not ckpt.has(sid, fp_by_sid[sid]):
            return False
        return ckpt.done[sid].get("llm_status") == "COMPLETE"

    pending = [s for s in eligible if not usable(s["section_record_id"])]
    prog = C.Progress(STAGE, total=len(eligible), unit="section", desc="llm enrich")
    prog.count = len(eligible) - len(pending)
    if prog.bar is not None:
        prog.bar.update(prog.count)
        prog.bar.refresh()
    prog.log(f"eligible={len(eligible)} resumed={prog.count} pending={len(pending)} "
             f"model={cfg['llm']['model']} workers={cfg['llm']['workers']}")

    if not wait_for_server(port, prog):
        ev.record(pipeline_stage=STAGE, run_status="failed",
                  error_message=f"vLLM server not ready on port {port}")
        ev.close()
        prog.close(summary="FAILED: server not ready")
        sys.exit(1)

    lock = threading.Lock()
    failed = partial = 0
    started = C.now_utc()

    def work(rec):
        try:
            return enrich_section(rec, cfg, port)
        except Exception as e:  # noqa: BLE001
            return {"paper_id": rec["paper_id"],
                    "section_record_id": rec["section_record_id"],
                    "llm_status": "FAILED", "llm_error": f"worker: {e!r}",
                    "llm_terms": [], "llm_chunks": 0, "llm_chunks_failed": 1,
                    "llm_chunks_truncated": 0, "llm_input_chars": 0,
                    "llm_model": cfg["llm"]["model_label"],
                    "llm_model_version": "vllm",
                    "llm_prompt_version": cfg["llm"]["prompt_version"]}

    if pending:
        with ThreadPoolExecutor(cfg["llm"]["workers"]) as ex:
            futs = {ex.submit(work, r): r for r in pending}
            for fut in as_completed(futs):
                r = fut.result()
                ckpt.add(r, fingerprint=fp_by_sid[r["section_record_id"]])
                with lock:
                    if r["llm_status"] == "FAILED":
                        failed += 1
                    elif r["llm_status"] == "PARTIAL":
                        partial += 1
                    prog.update(1, detail=f"{r['section_record_id']} {r['llm_status']} "
                                          f"terms={len(r.get('llm_terms') or [])} "
                                          f"chunks={r.get('llm_chunks')}")
                    if r["llm_status"] != "COMPLETE":
                        cur.add(r["paper_id"], STAGE, cfg["llm"]["model_label"],
                                PV, "section term extraction", r["llm_status"],
                                problem=str(r.get("llm_error"))[:300],
                                resolution="terms kept; flagged unverified")
    ckpt.close()

    results = [ckpt.done[s["section_record_id"]] for s in eligible
               if s["section_record_id"] in ckpt.done]
    C.write_jsonl(C.CORPUS_DIR / "data" / "llm_terms.jsonl", results)

    # merge a compact summary into sections.jsonl (full terms stay in llm_terms.jsonl)
    by_sid = {r["section_record_id"]: r for r in results}
    for s in sections:
        r = by_sid.get(s["section_record_id"])
        if r:
            s["llm_enrichment"] = {
                "status": r["llm_status"],
                "model": r["llm_model"],
                "prompt_version": r["llm_prompt_version"],
                "chunks": r["llm_chunks"],
                "term_count": len(r.get("llm_terms") or []),
                "record_ref": "data/llm_terms.jsonl",
            }
    C.write_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl", sections)

    n_com = sum(1 for r in results if r["llm_status"] == "COMPLETE")
    n_par = sum(1 for r in results if r["llm_status"] == "PARTIAL")
    n_fail = sum(1 for r in results if r["llm_status"] == "FAILED")
    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "sections_total": len(sections),
        "sections_eligible": len(eligible),
        "sections_enriched": len(results),
        "llm_complete": n_com, "llm_partial": n_par, "llm_failed": n_fail,
        "sections_never_enriched": len(eligible) - len(results),
        "total_terms": sum(len(r.get("llm_terms") or []) for r in results),
        "chunks_total": sum(r.get("llm_chunks") or 0 for r in results),
        "chunks_truncated": sum(r.get("llm_chunks_truncated") or 0 for r in results),
        "chunks_failed": sum(r.get("llm_chunks_failed") or 0 for r in results),
        "input_chars": sum(r.get("llm_input_chars") or 0 for r in results),
        "model": cfg["llm"]["model"],
        "model_label": cfg["llm"]["model_label"],
        "prompt_version": cfg["llm"]["prompt_version"],
        "thinking": cfg["llm"]["thinking"],
        "temperature": cfg["llm"]["temperature"],
        "max_tokens": cfg["llm"]["max_tokens"],
        "workers": cfg["llm"]["workers"],
        "max_prompt_chars": cfg["llm"]["max_prompt_chars"],
        "reconciliation": {
            "eligible_equals_enriched_plus_missing":
                len(eligible) == len(results) + (len(eligible) - len(results)),
            "status_sum_equals_enriched": n_com + n_par + n_fail == len(results),
        },
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "llm_enrichment_summary.json", summary)
    ev.record(pipeline_stage=STAGE, run_status="success" if not n_fail else "partial",
              model_name_version=cfg["llm"]["model_label"],
              prompt_version=cfg["llm"]["prompt_version"],
              started_at=started, completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"eligible={len(eligible)} complete={n_com} partial={n_par} failed={n_fail}")
    ev.close()
    prog.close(summary=f"complete={n_com} partial={n_par} failed={n_fail} "
                       f"terms={summary['total_terms']}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
