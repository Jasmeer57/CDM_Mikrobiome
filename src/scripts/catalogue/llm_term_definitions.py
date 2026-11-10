#!/usr/bin/env python
"""Stage 3: LLM term correction + definition generation via Ollama (qwen3.5:4b, /no_think).

Reads:   data/catalogue/terminology_dedup.csv     (stage-2 output, sorted by priority)
Writes:  data/catalogue/catalogue_terms_llm.csv   (corrected term + definition + flags)
         data/catalogue/llm_terms_checkpoint.json  (resumable cache: term_norm -> record)

Batched prompts: N terms per call, LLM returns a strict JSON array of
{"term","corrected","definition","is_valid","cdm_type","is_taxon"} records.

Guard rails:
 - ORGANISM / taxon-looking terms are never rewritten (corrections ignored);
   definitions still requested.
 - On batch JSON parse failure, the batch falls back to per-term calls so a
   single malformed response loses nothing.
 - Priority: input rows are consumed in file order (stage 2 sorted by
   n_papers desc, then n_models desc) so a wall-clock kill still leaves the
   most valuable terms done. Checkpointed every --cache-every terms.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REPO_ROOT = PROJECT_ROOT
while not (REPO_ROOT / "data" / "catalogue").exists() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
PROJECT_ROOT = REPO_ROOT

IN_CSV = PROJECT_ROOT / "data" / "catalogue" / "terminology_dedup.csv"
OUT_CSV = PROJECT_ROOT / "data" / "catalogue" / "catalogue_terms_llm.csv"
CKPT = PROJECT_ROOT / "data" / "catalogue" / "llm_terms_checkpoint.json"
CKPT_LOCK = PROJECT_ROOT / "data" / "catalogue" / ".llm_terms_checkpoint.lock"


def load_checkpoint() -> dict:
    """Load checkpoint under lock; merge-and-save what a concurrent writer added."""
    if not CKPT.exists():
        return {}
    with CKPT_LOCK.open("w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            return json.loads(CKPT.read_text())
        except json.JSONDecodeError:
            return {}
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def save_checkpoint(cache: dict) -> None:
    """Atomic + locked checkpoint save (concurrent SLURM jobs on the same NFS)."""
    tmp = CKPT.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False))
    with CKPT_LOCK.open("w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            if CKPT.exists():
                try:
                    other = json.loads(CKPT.read_text())
                    if len(other) > len(cache):
                        merged = dict(cache)
                        merged.update(other)
                        tmp.write_text(json.dumps(merged, ensure_ascii=False))
                except json.JSONDecodeError:
                    pass
            os.replace(tmp, CKPT)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)

TAXON_HINT = re.compile(
    r"(bacter(?:ia|ium|a)|coccus|bacill|virus|monas|aceae|ales|mycet|spp?\.)", re.I
)

BATCH_TMPL = """You are curating a biomedical terminology for a human microbiome data catalogue.
For each term below, return STRICT JSON (a single JSON array, no markdown, one object per term, in order):

[{{"i": 1, "corrected": "...", "definition": "...", "is_valid": true, "cdm_type": "CHEMICAL", "is_taxon": false}}]

Rules:
- "i": the term number as given.
- "corrected": the term with fixed casing/hyphenation/spelling and extraction artifacts removed (glued words, stray punctuation). If already fine, repeat it unchanged. NEVER change a species/genus scientific name.
- "definition": 1-2 precise sentences (max 40 words) defining the term in a microbiome/biomedical context. For species/taxa: what the organism is and its relevance to the human microbiome.
- "is_valid": false only if the term is garbage (author list, table fragment, non-scientific text).
- "cdm_type": best type from ORGANISM, CHEMICAL, DISEASE, PROTEIN, DNA_RNA, CELL_TYPE, GENOMICS, PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, STUDY_DESIGN; keep the given label if correct.
- "is_taxon": true if the term is a biological taxon (species, genus, strain etc.)

Terms:
{items}

JSON array:"""

SINGLE_TMPL = """You are curating a biomedical terminology for a human microbiome data catalogue.
Given one extracted term labelled with a broad entity type, return STRICT JSON (no markdown, no extra text):

{{"corrected": "...", "definition": "...", "is_valid": true, "cdm_type": "{cdm_type}", "is_taxon": false}}

Rules:
- "corrected": fix casing/hyphenation/spelling/extraction artifacts; unchanged if fine. NEVER change a species/genus scientific name.
- "definition": 1-2 precise sentences (max 40 words) in a microbiome/biomedical context.
- "is_valid": false only if garbage (author list, table fragment, non-scientific text).
- "cdm_type": ORGANISM, CHEMICAL, DISEASE, PROTEIN, DNA_RNA, CELL_TYPE, GENOMICS, PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, or STUDY_DESIGN; keep "{cdm_type}" if correct.
- "is_taxon": true if a biological taxon.

Term: "{term}"
Label: {cdm_type}
JSON:"""


def ollama_chat(host: str, model: str, prompt: str, num_predict: int, timeout: int = 600) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt + " /no_think"}],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": num_predict},
    }).encode()
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["message"]["content"]


def strip_think(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    raw = re.sub(r"```[a-z]*\n?|```", "", raw).strip()
    return raw


def parse_batch(raw: str, want: int) -> list[dict] | None:
    """Parse a JSON array of per-term records; None if unrecoverable."""
    raw = strip_think(raw)
    m = re.search(r"\[.*\]", raw, flags=re.S)
    if not m:
        return None
    txt = m.group(0)
    try:
        arr = json.loads(txt)
    except json.JSONDecodeError:
        try:
            arr = json.loads(txt.replace("'", '"'))
        except json.JSONDecodeError:
            return None
    if not isinstance(arr, list) or len(arr) < want:
        return None
    return arr


def parse_single(raw: str) -> dict | None:
    raw = strip_think(raw)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        try:
            return json.loads(m.group(0).replace("'", '"'))
        except json.JSONDecodeError:
            return None


def guard_record(r: dict, parsed: dict) -> dict:
    term = r["term"]
    corrected = str(parsed.get("corrected") or term).strip() or term
    orig_taxon = bool(TAXON_HINT.search(term)) or r["cdm_type"] in ("ORGANISM", "CELL_TYPE")
    if orig_taxon and corrected.strip().lower() != term.strip().lower():
        corrected = term  # never rewrite taxa
    return {
        "corrected": corrected,
        "definition": str(parsed.get("definition") or "").strip(),
        "is_valid": bool(parsed.get("is_valid", True)),
        "llm_cdm_type": str(parsed.get("cdm_type") or r["cdm_type"]),
        "is_taxon": bool(parsed.get("is_taxon", False)),
        "correction_applied": corrected.strip().lower() != term.strip().lower(),
        "parse_failed": False,
    }


def fallback_record(r: dict) -> dict:
    return {
        "corrected": r["term"], "definition": "", "is_valid": True,
        "llm_cdm_type": r["cdm_type"], "is_taxon": False,
        "correction_applied": False, "parse_failed": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--types", default="")
    ap.add_argument("--min-papers", type=int, default=0, help="Only terms with n_papers >= this")
    ap.add_argument("--min-models", type=int, default=0, help="Only terms with n_models >= this")
    ap.add_argument("--cache-every", type=int, default=500)
    ap.add_argument("--skip-entity", action="store_true", help="Skip untyped ENTITY terms")
    args = ap.parse_args()

    if not IN_CSV.exists():
        print(f"ERROR: {IN_CSV} missing — run stage 2 first", file=sys.stderr)
        return 1

    try:
        urllib.request.urlopen(f"{args.host.rstrip('/')}/api/tags", timeout=10)
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: no Ollama at {args.host}: {e}", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(IN_CSV.open(encoding="utf-8")))
    if args.types:
        tf = {t.strip() for t in args.types.split(",")}
        rows = [r for r in rows if r["cdm_type"] in tf]
    if args.min_papers:
        rows = [r for r in rows if int(r["n_papers"] or 0) >= args.min_papers]
    if args.min_models:
        rows = [r for r in rows if int(r["n_models"] or 0) >= args.min_models]
    if args.skip_entity:
        rows = [r for r in rows if r["cdm_type"] != "ENTITY"]
    if args.limit:
        rows = rows[: args.limit]
    print(f"terms to process: {len(rows)} (batch={args.batch_size})", flush=True)

    cache: dict[str, dict] = load_checkpoint()
    print(f"checkpoint: {len(cache)} terms already done", flush=True)

    # process order = file order (priority-sorted by stage 2)
    todo = [r for r in rows if r["term_norm"] not in cache]
    fields = list(rows[0].keys()) + [
        "corrected_term", "definition", "is_valid", "llm_cdm_type",
        "is_taxon", "correction_applied", "llm_latency_s",
    ]
    # job-unique output (checkpoint is source of truth across concurrent jobs)
    jobid = os.environ.get("SLURM_JOB_ID", "local")
    out_path = OUT_CSV.with_name(f"{OUT_CSV.stem}_{jobid}.csv")
    out_f = out_path.open("w", newline="", encoding="utf-8")
    w = csv.DictWriter(out_f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()

    n_corr = n_invalid = n_fail = 0
    t0 = time.time()
    since_ckpt = 0
    bi = 0
    while bi < len(todo):
        batch = todo[bi: bi + args.batch_size]
        missing = [b for b in batch if b["term_norm"] not in cache]
        if not missing:
            bi += args.batch_size
            continue
        items = "\n".join(
            f'{k+1}. "{b["term"]}" [{b["cdm_type"]}]' for k, b in enumerate(missing))
        prompt = BATCH_TMPL.format(items=items)
        t1 = time.time()
        parsed_arr = None
        try:
            raw = ollama_chat(args.host, args.model, prompt,
                              num_predict=200 * len(missing) + 200)
            parsed_arr = parse_batch(raw, len(missing))
        except Exception as e:
            print(f"  batch call failed: {e}", flush=True)

        if parsed_arr is not None:
            for b, parsed in zip(missing, parsed_arr):
                if not isinstance(parsed, dict):
                    rec = fallback_record(b)
                    n_fail += 1
                else:
                    rec = guard_record(b, parsed)
                cache[b["term_norm"]] = rec
                since_ckpt += 1
        else:
            # fall back to per-term calls for this batch
            for b in missing:
                try:
                    raw = ollama_chat(
                        args.host, args.model,
                        SINGLE_TMPL.format(term=b["term"], cdm_type=b["cdm_type"]),
                        num_predict=320)
                    parsed = parse_single(raw)
                except Exception:
                    parsed = None
                if parsed is None:
                    rec = fallback_record(b)
                    n_fail += 1
                else:
                    rec = guard_record(b, parsed)
                cache[b["term_norm"]] = rec
                since_ckpt += 1
        bi += args.batch_size

        done = min(bi, len(todo))
        if done % 100 < args.batch_size:
            el = time.time() - t0
            rate = done / el if el else 0
            eta = (len(todo) - done) / rate if rate else 0
            out_f.flush()
            if since_ckpt >= args.cache_every:
                save_checkpoint(cache)
                since_ckpt = 0
            print(f"  {done}/{len(todo)} | corr={n_corr} inval={n_invalid} fail={n_fail} "
                  f"| {rate:.1f} t/s | ETA {eta/3600:.1f}h", flush=True)

    # final pass: write all rows (cache-hit or fresh) in input order
    n_done = n_skipped = 0
    for r in rows:
        rec = cache.get(r["term_norm"])
        if rec is None:
            rec = fallback_record(r)
            n_fail += 1
        else:
            n_skipped += 1
        row_out = dict(r)
        row_out.update({
            "corrected_term": rec["corrected"],
            "definition": rec["definition"],
            "is_valid": str(rec["is_valid"]).lower(),
            "llm_cdm_type": rec["llm_cdm_type"],
            "is_taxon": str(rec["is_taxon"]).lower(),
            "correction_applied": str(rec["correction_applied"]).lower(),
            "llm_latency_s": "",
        })
        w.writerow(row_out)
        n_done += 1
        if rec.get("correction_applied"):
            n_corr += 1
        if not rec["is_valid"]:
            n_invalid += 1

    out_f.flush()
    save_checkpoint(cache)
    out_f.close()
    print(f"done: {n_done} rows written ({n_skipped} from checkpoint cache) | "
          f"corrections: {n_corr} | invalid: {n_invalid} | failures: {n_fail}")
    print(f"output: {out_path}")
    print(f"elapsed: {(time.time()-t0)/3600:.2f}h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
