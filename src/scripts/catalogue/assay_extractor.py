#!/usr/bin/env python
"""Stage 4c: extract assay metadata per paper via qwen3.5:4b over methods-like sections.

Reads:   data/segmented_sections_markdown/HMPAPER_*.md   (SECTION_PATH-segmented)
         data/catalogue/tables/datasets.csv          (dataset_id per paper)
Writes:  data/catalogue/tables/assays.csv            (template column set)
         data/catalogue/assays_checkpoint.json       (resume across jobs)

One Ollama chat call per paper: methods-like sections (SECTION_PATH matching
method/material/protocol), falling back to the whole document minus references
when no methods section exists. Checkpointed + flock-protected like
llm_term_definitions.py (concurrent SLURM jobs safe).
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
while not (REPO_ROOT / "data" / "corpus").exists() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
PROJECT_ROOT = REPO_ROOT

SECTIONS = PROJECT_ROOT / "data/segmented_sections_markdown"
TABLES = PROJECT_ROOT / "data" / "catalogue" / "tables"
DATASETS_CSV = TABLES / "datasets.csv"
OUT_CSV = TABLES / "assays.csv"
CKPT = PROJECT_ROOT / "data" / "catalogue" / "assays_checkpoint.json"
CKPT_LOCK = PROJECT_ROOT / "data" / "catalogue" / ".assays_checkpoint.lock"

METHODS_RE = re.compile(r"^(?:[0-9.]*\s*)*(method|material|experimental|protocol)", re.I)
EXCLUDE_RE = re.compile(r"references|supplementary|acknowledg|funding|author_contrib", re.I)
MAX_CHARS = 26000  # ~6-7k tokens of prompt context for the 4b model

PROMPT = """You extract sequencing-assay metadata from a microbiome paper's methods text.
Return STRICT JSON (one object, no markdown, no extra text):

{{
 "assay_type": "16S rRNA amplicon sequencing | shotgun metagenomic sequencing | metatranscriptomics | other (name it)",
 "target_gene_or_region": "e.g. V3-V4, V4, whole genome — empty string if not stated",
 "sequencing_platform": "e.g. Illumina MiSeq, Ion Torrent PGM — empty string if not stated",
 "library_preparation": "kit or protocol named — empty string if not stated",
 "dna_extraction_method": "e.g. Qiagen DNeasy PowerSoil, bead-beating protocol — empty string if not stated",
 "primer_or_probe": "primer names/sequences, e.g. 515F/806R — empty string if not stated",
 "negative_controls": "e.g. blank extraction controls, none — empty string if not stated",
 "positive_controls": "e.g. mock community — empty string if not stated",
 "contamination_handling": "e.g. decontam, prevalence filtering — empty string if not stated",
 "quality_control": "QC steps: Chimera removal (name tool), quality filtering thresholds, rarefaction depth — empty string if not stated",
 "bioinformatics_pipeline": "named workflow, e.g. QIIME2, DADA2 — empty string if not stated",
 "software_tools": "pipe-separated tool list with versions where stated",
 "taxonomic_database": "e.g. SILVA 132, Greengenes — empty string if not stated",
 "functional_database": "e.g. KEGG, eggNOG — empty string if not stated",
 "normalization_method": "e.g. rarefaction, CSS, compositional — empty string if not stated",
 "statistical_methods": "pipe-separated tests, e.g. ANCOM|LEfSe|PERMANOVA"
}}

Only include what the text supports. Text:

"""

TEXT = """

Return the JSON object now. /no_think"""


def s(v) -> str:
    if isinstance(v, list):
        return "|".join(str(x) for x in v if x)
    return str(v or "").strip()


ASSAY_COLS = [
    "assay_type", "target_gene_or_region", "sequencing_platform",
    "library_preparation", "dna_extraction_method", "primer_or_probe",
    "negative_controls", "positive_controls", "contamination_handling",
    "quality_control", "bioinformatics_pipeline", "software_tools",
    "taxonomic_database", "functional_database", "normalization_method",
    "statistical_methods",
]


def load_checkpoint() -> dict:
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


def extract_methods_text(md_text: str) -> str:
    """Concatenate methods-like SECTION segments; exclude container sections."""
    seg_re = re.compile(
        r"<!-- SECTION_PATH: ([^>]+?) -->\n(.*?)(?=\n?<!-- (?:SEGMENT|SECTION_PATH|END_SEGMENT):)",
        re.S,
    )
    pieces = []
    for path, body in seg_re.findall(md_text):
        if EXCLUDE_RE.search(path):
            continue
        if METHODS_RE.match(path.strip()):
            pieces.append(f"[SECTION: {path.strip()}]\n{body.strip()}")
    if pieces:
        return "\n\n".join(pieces)[:MAX_CHARS]
    # fallback: whole doc minus container sections
    keep = []
    for path, body in seg_re.findall(md_text):
        if EXCLUDE_RE.search(path):
            continue
        keep.append(body.strip())
    return "\n\n".join(keep)[:MAX_CHARS]


def chat(host: str, model: str, prompt: str, timeout: int = 300) -> str:
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False, "options": {"temperature": 0.1, "num_predict": 512},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"]


def parse_json_obj(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(raw[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11444"))
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cache-every", type=int, default=20)
    args = ap.parse_args()

    ds_of = {}
    with DATASETS_CSV.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ds_of.setdefault(r["paper_id"], r["dataset_id"])

    files = sorted(SECTIONS.glob("HMPAPER_*.md"))
    if args.limit:
        files = files[: args.limit]

    cache = load_checkpoint()
    todo = [f for f in files if f.stem not in cache]
    print(f"papers: {len(files)} | checkpoint covers {len(cache)} | todo {len(todo)}", flush=True)

    t0 = time.time()
    n_fail = 0
    for n, f in enumerate(todo, 1):
        md = f.read_text(encoding="utf-8")
        pid = f.stem
        prompt = PROMPT + extract_methods_text(md) + TEXT
        rec = None
        for attempt in (1, 2):
            try:
                rec = parse_json_obj(chat(args.host, args.model, prompt))
                if rec:
                    break
            except (urllib.error.URLError, TimeoutError, KeyError) as e:
                print(f"  {pid}: attempt {attempt} failed: {e}", flush=True)
                time.sleep(3 * attempt)
        if rec is None:
            n_fail += 1
            rec = {c: "" for c in ASSAY_COLS}
            rec["_failed"] = True
        else:
            rec = {c: s(rec.get(c)) for c in ASSAY_COLS}
        rec["_failed"] = rec.get("_failed", False)
        cache[pid] = rec
        if n % args.cache_every == 0:
            save_checkpoint(cache)
            el = time.time() - t0
            rate = n / el
            eta = (len(todo) - n) / rate if rate else 0
            print(f"  {n}/{len(todo)} | fail={n_fail} | {rate*60:.1f} papers/min | "
                  f"ETA {eta/3600:.2f}h", flush=True)

    save_checkpoint(cache)

    # write final CSV from checkpoint (all papers)
    fields = ["assay_id", "paper_id", "dataset_id"] + ASSAY_COLS + ["evidence_location", "notes"]
    jobid = os.environ.get("SLURM_JOB_ID", "local")
    out_path = OUT_CSV
    rows = []
    for i in range(1, 454):
        pid = f"HMPAPER_{i:06d}"
        rec = cache.get(pid)
        if rec is None:
            continue
        row = {"assay_id": f"HMASSAY_{i:06d}", "paper_id": pid,
               "dataset_id": ds_of.get(pid, ""), "evidence_location": "methods sections",
               "notes": "LLM extracted (qwen3.5:4b); AUTO_SEEDED" }
        row.update({c: rec.get(c, "") for c in ASSAY_COLS})
        if rec.get("_failed"):
            row["notes"] = "LLM extraction failed; needs manual review"
        rows.append(row)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out_path.relative_to(PROJECT_ROOT)} "
          f"({n_fail} extraction failures)", flush=True)
    print(f"elapsed: {(time.time()-t0)/3600:.2f}h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
