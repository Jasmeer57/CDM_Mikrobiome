#!/usr/bin/env python3
"""LLM extraction of data-catalogue fields over the human-microbiome corpus.

Runs a small Ollama model (default qwen3.5:4b, no-think, temperature 0,
seed 42) against each v1 corpus record's full text and extracts the
catalogue-template rows the deterministic record schema cannot reach:

  - datasets   (accession, repository, type, availability, evidence)
  - cohorts    (label, role, country, counts, criteria, setting)
  - samples    (body site, type, collection method, timepoint)
  - assays     (type, target region, platform, extraction, pipeline)
  - findings   (up to 10, verbatim-evidenced)

Design rules (mirror human_microbiome_corpus_builder.py):
  - Deterministic sampling (temperature 0, fixed seed) + per-paper checkpoints.
  - Resume-safe: existing <paper_id>_cat.json checkpoints are skipped; --force reprocesses.
  - Hallucination guard: every evidence_text quote must appear verbatim in the
    paper's normalized text. Unverifiable findings are DROPPED; unverifiable
    dataset entries without an accession are dropped too.
  - JSON repairs: control-char strip, inner-quote fix, truncated-tail repair
    (reused from human_microbiome_corpus_builder).

Usage:
    python3 catalogue_llm_extract.py \
        --records ../results/human_microbiome_corpus_v1 \
        --ollama-host http://127.0.0.1:11397 --model qwen3.5:4b
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from human_microbiome_corpus_builder import (  # noqa: E402
    _norm_ws,
    _parse_llm_json,
    atomic_json,
    now,
)

log = logging.getLogger("catalogue_llm")

VERSION = "1.0.0"

PROMPT = """You are an expert curator building a human-microbiome DATA CATALOGUE from ONE paper. \
Extract structured records using ONLY the supplied text. Never invent values: use null for \
scalars you cannot find and [] for arrays you cannot find. Numbers (participant_count, \
sample_count) may only be reported if the text states them.

Cautions:
- "datasets" has ONE entry per distinct dataset the paper mentions or uses \
(external repository data, supplementary deposited files, or the study's own data behind an \
accession). Include an entry even if only an accession or repository URL is mentioned. \
If the paper references no data at all, return [].
- Every evidence_text must be a SHORT VERBATIM quote copied EXACTLY from the text.
- Prioritize results-section findings (up to 10); separate authors' reported findings \
from background/hypothesis text.

Return ONLY compact JSON matching this shape:
{{
 "datasets": [{{
  "accession": "repository accession e.g. PRJNA123456/ERP12345/E-MTAB-1234/PRJDB1234 (string-or-null)",
  "repository": "GEO|SRA|ENA|ArrayExpress|DDBJ|dbGaP|EGA|Zenodo|Dryad|figshare|Supplementary|Other|UNKNOWN",
  "role": "primary_study_data|linked_data|reused_public_data|supplementary|UNKNOWN",
  "dataset_type": ["16S_amplicon|shotgun_metagenomics|metabolomics|host_genomics|other"],
  "title": "string-or-null",
  "description": "string-or-null",
  "availability_status": "PUBLIC|CONTROLLED|UPON_REQUEST|NOT_DEPOSITED|UNKNOWN",
  "access_conditions": "string-or-null",
  "original_or_reused": "ORIGINAL|REUSED|UNKNOWN",
  "evidence_text": "verbatim quote from the text about data availability"}}],
 "cohorts": [{{
  "cohort_label": "short label e.g. 'IBD patients'",
  "cohort_role": "cases|controls|cases_and_controls|single_group",
  "population_description": "string-or-null",
  "country_or_region": [],
  "setting": "hospital|community|clinic|laboratory|mixed|UNKNOWN",
  "recruitment_method": "string-or-null",
  "participant_count": "int-or-null",
  "sample_count": "int-or-null",
  "age_group": "neonates|children|adolescents|adults|mixed_ages|unclear",
  "age_summary": "string-or-null",
  "sex_or_gender_reporting": "string-or-null",
  "health_status": "string-or-null",
  "inclusion_criteria": [],
  "exclusion_criteria": [],
  "timepoints": [],
  "evidence_text": "verbatim quote about the cohort"}}],
 "samples": [{{
  "body_site": "string e.g. stool, saliva, rectal swab",
  "sample_type": "string-or-null",
  "collection_method": "string-or-null",
  "collection_timepoint": "string-or-null",
  "storage_condition": "string-or-null",
  "sample_count": "int-or-null",
  "evidence_text": "verbatim quote about sample collection"}}],
 "assays": [{{
  "assay_type": "16S_amplicon_sequencing|shotgun_metagenomics|metabolomics|qPCR|culturomics|flow_cytometry|other",
  "target_gene_or_region": "string-or-null",
  "sequencing_platform": "string-or-null",
  "library_preparation": "string-or-null",
  "dna_extraction_method": "string-or-null",
  "negative_controls": "string-or-null",
  "bioinformatics_pipeline": "string-or-null",
  "taxonomic_database": "string-or-null",
  "statistical_methods": [],
  "evidence_text": "verbatim quote about methods"}}],
 "findings": [{{
  "finding_text": "short statement of the reported result",
  "finding_domain": "microbiome_association|taxon_abundance|diversity|functional|clinical|other",
  "taxon_or_feature": "string-or-null",
  "taxonomic_rank": "phylum|class|order|family|genus|species|UNKNOWN",
  "comparison_or_exposure": "string-or-null",
  "outcome": "string-or-null",
  "direction": "increase|decrease|association|no_association|mixed|null",
  "effect_measure": "string-or-null",
  "effect_estimate": "string-or-null e.g. 'OR 1.4'",
  "confidence_interval": "string-or-null",
  "p_value": "string-or-null",
  "q_value": "string-or-null",
  "adjusted_covariates": [],
  "evidence_text": "verbatim quote supporting the finding",
  "evidence_location": "Results|Methods|Abstract|Discussion|Tables|Supplementary|other"}}]
}}

TITLE: {title}
DOI: {doi}
TEXT EXCERPT:
{excerpt}"""


def load_text(rec: dict) -> str:
    """Full clean text of the record with abstract fallback."""
    ft = rec.get("full_text") or {}
    tpath = ft.get("clean_text_path") or ""
    try:
        p = Path(tpath)
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    return (rec.get("publication") or {}).get("abstract") or ""


def make_prompt(rec: dict, context_chars: int) -> str:
    text = load_text(rec)
    pub = rec.get("publication") or {}
    budget = max(4000, context_chars)
    excerpt = text[:budget]
    if len(text) > budget * 2:
        excerpt += "\n[END EXCERPT]\n" + text[-min(4000, budget // 2):]
    return PROMPT.format(title=_norm_ws(pub.get("title") or ""),
                         doi=_norm_ws(pub.get("doi") or ""), excerpt=excerpt)


def quote_verified(quote: str, norm_text_lower: str, minlen: int = 15) -> bool:
    """A claim's evidence quote must appear verbatim (ws-normalized, lowercased)."""
    q = _norm_ws(quote or "").lower()
    if len(q) < minlen:
        return False
    return q[:200] in norm_text_lower


STR_FIELDS = {"title", "description", "access_conditions", "cohort_label", "cohort_role",
              "population_description", "setting", "recruitment_method", "age_group",
              "age_summary", "sex_or_gender_reporting", "health_status", "body_site",
              "sample_type", "collection_method", "collection_timepoint", "storage_condition",
              "assay_type", "target_gene_or_region", "sequencing_platform",
              "library_preparation", "dna_extraction_method", "negative_controls",
              "bioinformatics_pipeline", "taxonomic_database", "finding_text",
              "finding_domain", "taxon_or_feature", "taxonomic_rank",
              "comparison_or_exposure", "outcome", "direction", "effect_measure",
              "effect_estimate", "confidence_interval", "p_value", "q_value", "repository",
              "role", "availability_status", "original_or_reused", "evidence_location"}
INT_FIELDS = {"participant_count", "sample_count"}


def clean_item(item: dict) -> dict:
    """Coerce model output fields to catalogue types (str via _norm_ws, ints, list-fold)."""
    out = {}
    for k, v in item.items():
        if v is None:
            out[k] = None
        elif k in INT_FIELDS:
            try:
                out[k] = int(str(v).replace(",", "").strip())
            except (TypeError, ValueError):
                m = re.search(r"\d+", str(v))
                out[k] = int(m.group(0)) if m else None
        elif k in STR_FIELDS:
            out[k] = _norm_ws(str(v)) or None
        elif isinstance(v, list):
            out[k] = [_norm_ws(str(x)) for x in v
                     if x is not None and _norm_ws(str(x))]
        else:
            out[k] = _norm_ws(str(v)) or None
    return out


def postprocess(extracted: dict, norm_text_lower: str) -> dict:
    """Validate + clip the model output into a clean per-paper catalogue dict."""
    out = {"datasets": [], "cohorts": [], "samples": [], "assays": [], "findings": []}
    if not isinstance(extracted, dict):
        return out

    for ds in extracted.get("datasets") or []:
        if not isinstance(ds, dict):
            continue
        d = clean_item(ds)
        ev = _norm_ws(d.get("evidence_text") or "")
        d["evidence_verified"] = quote_verified(ev, norm_text_lower)
        d["evidence_text"] = ev or None
        if not d.get("accession") and not d["evidence_verified"]:
            continue  # no accession AND unverifiable -> likely hallucinated
        out["datasets"].append(d)

    for key in ("cohorts", "samples", "assays"):
        for item in extracted.get(key) or []:
            if not isinstance(item, dict):
                continue
            d = clean_item(item)
            ev = _norm_ws(d.get("evidence_text") or "")
            d["evidence_verified"] = quote_verified(ev, norm_text_lower)
            d["evidence_text"] = ev or None
            out[key].append(d)

    findings = extracted.get("findings")
    if isinstance(findings, list):
        for f in findings:
            if not isinstance(f, dict):
                continue
            d = clean_item(f)
            ev = _norm_ws(d.get("evidence_text") or "")
            if not quote_verified(ev, norm_text_lower, minlen=25):
                continue  # refuse unverifiable findings outright
            d["evidence_text"] = ev
            d["evidence_verified"] = True
            out["findings"].append(d)

    out["findings"] = out["findings"][:10]
    return out


def ollama_chat(host: str, model: str, prompt: str, max_tokens: int, timeout: int) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.0, "seed": 42, "num_predict": max_tokens,
            "num_ctx": 16384, "top_k": 20, "top_p": 0.8, "repeat_penalty": 1.05,
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
    content = (data.get("message") or {}).get("content", "")
    if not content.strip():
        raise RuntimeError("empty response from model")
    return content


def process_one(args_spec, rec_path: Path, out: Path, force: bool) -> dict:
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    pid = rec.get("paper_id") or rec_path.stem
    ckpt = out / f"{pid}_cat.json"
    if ckpt.is_file() and not force:
        return {"pid": pid, "status": "resumed"}
    if force and ckpt.is_file():
        ckpt.unlink()

    prompt = make_prompt(rec, args_spec.context_chars)
    norm_text_lower = _norm_ws(load_text(rec)).lower()
    content = ollama_chat(args_spec.ollama_host, args_spec.model, prompt,
                          args_spec.max_tokens, args_spec.timeout)
    extracted = _parse_llm_json(content)
    if not isinstance(extracted, dict):
        raise RuntimeError("unparseable JSON response")
    cat = postprocess(extracted, norm_text_lower)
    cat.update({
        "schema_version": VERSION,
        "paper_id": pid,
        "extracted_at": now(),
        "model": args_spec.model,
        "record_path": str(rec_path),
    })
    atomic_json(ckpt, cat)
    return {
        "pid": pid, "status": "ok",
        "n_datasets": len(cat["datasets"]), "n_cohorts": len(cat["cohorts"]),
        "n_samples": len(cat["samples"]), "n_assays": len(cat["assays"]),
        "n_findings": len(cat["findings"]),
    }


def write_csv_log(path: Path, rows: list) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    tmp = str(path) + f".tmp{int(time.time())}"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records", default=str(Path(__file__).resolve().parent.parent /
                                             "outputs/results/human_microbiome_corpus_v1"))
    ap.add_argument("--out", default=None, help="checkpoint dir (default: <records>/llm_catalogue)")
    ap.add_argument("--ollama-host", default="http://127.0.0.1:11397")
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--context-chars", type=int, default=20000)
    ap.add_argument("--max-tokens", type=int, default=4500)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--parallel", type=int, default=12)
    ap.add_argument("--force", action="store_true", help="re-extract even if checkpoint exists")
    ap.add_argument("--log-every", type=int, default=25)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    recdir = Path(args.records)
    out = Path(args.out) if args.out else recdir / "llm_catalogue"
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(recdir.glob("records/*/*.json"))
    if not paths:
        raise SystemExit("no records found under " + str(recdir))

    todo = []
    for p in paths:
        pid = json.loads(p.read_text(encoding="utf-8")).get("paper_id") or p.stem
        if args.force or not (out / f"{pid}_cat.json").is_file():
            todo.append(p)
    log.info("records: %d total, %d todo (checkpoints skipped)", len(paths), len(todo))
    if not todo:
        log.info("nothing to do — all checkpoints present")
        return

    rows: list = []
    done = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futs = {pool.submit(process_one, args, p, out, args.force): p for p in todo}
        for fut in as_completed(futs):
            rp = futs[fut]
            try:
                rows.append(fut.result())
            except Exception as e:
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

    write_csv_log(out / "llm_catalogue_log.csv", rows)
    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_err = sum(1 for r in rows if r.get("status") == "error")
    log.info("pass done: ok=%d error=%d | checkpoints on disk: %d",
             n_ok, n_err, len(list(out.glob("*_cat.json"))))
    if n_err:
        log.warning("%d papers failed — resubmit the same job to retry only these", n_err)


if __name__ == "__main__":
    main()
