#!/usr/bin/env python3
"""Stage 52: LLM extraction of finding records (template §4) from eligible
Abstract/Results/Discussion sections.

Runs INSIDE the A40 Slurm job that also serves the model (localhost). Worker
threads hit the vLLM OpenAI endpoint concurrently via scripts/llmio.py; results
are checkpointed per section so a timeout/resubmit continues where it stopped.

Integrity rules honored:
- a paper may have ZERO findings (e.g. Methods-heavy text); an empty list is a
  valid COMPLETE result, never a failure
- verbatim evidence_text with a short quoted span (<= ~60 words); the LLM must
  never invent statistics - any numeric field it cannot copy from the text
  stays not_reported
- null results and contradictions are findings too - the prompt explicitly
  asks for them so they are not silently dropped
- strict JSON or split-retry; truncation is PARTIAL, never silently accepted
- finding IDs are assigned deterministically per paper AFTER collection,
  ordered by (section_order, appearance in the LLM output)

Outputs
  data/findings.jsonl      one record per finding (findings_raw subset nested
                           per section record for provenance)
  validation/findings_extraction_report.json
"""
import json
import os
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C
import llmio

STAGE = "stage52_findings_extract"
PV = "2.1.0"
NOT_REPORTED = "not_reported"

CLAIM_TYPES = {"result", "null_result", "author_interpretation", "other"}
DIRECTIONS = {"increased", "decreased", "no_association_reported", "mixed", "unclear"}
RANKS = {"strain", "species", "genus", "family", "order", "class",
         "phylum", "domain", "clade", "unknown"}
ELIGIBLE_TYPES = ("Abstract", "Results", "Discussion")

FINDINGS_PROMPT = """You extract scientific FINDINGS from one section of a human-microbiome paper for a corpus build.
Extract EVERY distinct result, null result, or author interpretation stated in the text. Include null/negative results and contradictory or mixed findings - do NOT include only positive associations.
If the section states no findings, return an empty list.

For each finding return STRICT JSON (no markdown, no commentary) with exactly these keys:
{{
  "findings": [
    {{
      "claim_type": "result | null_result | author_interpretation | other",
      "body_site_original": "body site as worded in the text",
      "population_subgroup": "population/subgroup the finding applies to",
      "exposure_or_comparison": "exposure, condition or comparison studied",
      "outcome": "outcome measured",
      "taxon_original": "taxon as worded in the text, or not_reported",
      "taxonomic_rank": "strain|species|genus|family|order|class|phylum|domain|clade|unknown",
      "microbial_function_pathway": "function/pathway, or not_reported",
      "direction": "increased | decreased | no_association_reported | mixed | unclear",
      "direction_refers_to": "what the direction refers to (e.g. abundance of X in Y vs Z)",
      "effect_measure": "measure as stated (odds ratio, log2foldchange...), or not_reported",
      "effect_estimate": "numeric value as stated verbatim, or not_reported",
      "p_value": "verbatim, or not_reported",
      "q_value": "adjusted p / q value verbatim, or not_reported",
      "confidence_interval": "verbatim, or not_reported",
      "adjusted_covariates": "covariates adjusted for, or not_reported",
      "sample_size": "n as stated for this analysis, or not_reported",
      "evidence_text": "short VERBATIM quote from the text supporting this finding (at most 60 words, exact wording, no paraphrase)"
    }}
  ]
}}

Rules:
- evidence_text MUST be copied word-for-word from the text; the corpus verifies it against the source and drops nothing silently.
- NEVER invent or compute a statistic. If the text does not give effect_estimate, p_value, q_value, confidence_interval or sample_size, put not_reported.
- One finding per distinct scientific statement, not one per paper.
- Only use the text provided.

Section "{section_name}" ({section_type}) of "{title}":
{chunk}"""


def sanitize(fd, rec_meta):
    """Coerce one LLM finding dict into the corpus vocabulary; unknown enums
    are kept verbatim but flagged via claim_type=other / direction=unclear,
    never silently dropped."""
    out = {}
    for k, default in (("claim_type", "other"), ("direction", "unclear"),
                       ("taxonomic_rank", "unknown")):
        v = str(fd.get(k) or "").strip()
        out[k] = v if v in {"claim_type": CLAIM_TYPES, "direction": DIRECTIONS,
                            "taxonomic_rank": RANKS}[k] else default
    for k in ("body_site_original", "population_subgroup", "exposure_or_comparison",
              "outcome", "taxon_original", "microbial_function_pathway",
              "direction_refers_to", "effect_measure", "effect_estimate",
              "p_value", "q_value", "confidence_interval", "adjusted_covariates",
              "sample_size"):
        v = " ".join(str(fd.get(k) or "").split())
        out[k] = v if v else NOT_REPORTED
    ev = " ".join(str(fd.get("evidence_text") or "").split())
    out["evidence_text"] = ev
    out["_invalid_evidence_text"] = not ev or ev.lower() == NOT_REPORTED
    return out


def enrich_section(sec, cfg, port):
    """Extract findings from one eligible section; return the section-level
    record (like stage-50) with a find list."""
    model = cfg["llm"]["model"]
    out = {
        "paper_id": sec["paper_id"],
        "section_record_id": sec["section_record_id"],
        "section_type": sec.get("section_type"),
        "section_order": sec.get("section_order"),
        "llm_model": cfg["llm"]["model_label"],
        "llm_model_version": f"vllm:{cfg['llm']['runtime']}",
        "llm_prompt_version": cfg["llm"]["findings_prompt_version"],
        "llm_source_text_hash": sec.get("text_hash_sha256"),
        "llm_status": "FAILED", "findings_raw": [], "llm_error": None,
        "llm_chunks": 0, "llm_chunks_failed": 0, "llm_chunks_truncated": 0,
        "llm_split_retries": 0, "llm_input_chars": 0, "llm_degrees": [],
    }
    text = sec.get("section_text_original") or ""
    if not text.strip():
        out["llm_status"] = "COMPLETE"  # empty section: vacuously no findings
        return out
    chunks = C.chunk_text(text, cfg["llm"]["max_prompt_chars"])
    out_meta = out  # degree counters accumulate directly on the record

    def build_prompt(chunk):
        return FINDINGS_PROMPT.format(
            section_name=sec.get("section_name_original") or "section",
            section_type=sec.get("section_type") or "",
            title=sec.get("paper_title") or "untitled",
            chunk=chunk)

    extract = llmio.make_extractor(cfg, port, out_meta, build_prompt)

    statuses, all_finds = [], []
    for ci, chunk in enumerate(chunks):
        out["llm_input_chars"] += len(chunk)
        try:
            data, status, err = extract(chunk, ci, 0)
            finds = None
            if status != "FAILED" and isinstance(data, dict):
                raw = data.get("findings")
                finds = raw if isinstance(raw, list) else []
                if "findings" not in data:
                    finds = []          # valid JSON with no findings key: none stated
            if status == "COMPLETE" and finds is None:
                status, err = "FAILED", "findings key missing from response"
            if finds is not None:
                src_offset = sum(len(c) for c in chunks[:ci])
                for fd in finds:
                    if isinstance(fd, dict):
                        f = sanitize(fd, out)
                        f["chunk"] = ci
                        f["chunk_char_offset"] = src_offset
                        all_finds.append(f)
            statuses.append(status)
            if status != "COMPLETE":
                out["llm_error"] = ((out["llm_error"] + "; ") if out["llm_error"]
                                    else "") + f"chunk{ci}:{err}"
                if status == "PARTIAL":
                    out["llm_chunks_truncated"] += 1
                else:
                    out["llm_chunks_failed"] += 1
            out["llm_chunks"] += 1
        except Exception as e:  # noqa: BLE001
            statuses.append("FAILED")
            out["llm_chunks_failed"] += 1
            out["llm_chunks"] += 1
            out["llm_error"] = ((out["llm_error"] + "; ") if out["llm_error"]
                                else "") + f"chunk{ci}:{e}"

    if all(s == "COMPLETE" for s in statuses):
        out["llm_status"] = "COMPLETE"
    elif any(s == "COMPLETE" for s in statuses) or all_finds:
        out["llm_status"] = "PARTIAL"
    else:
        out["llm_status"] = "FAILED"
    out["findings_raw"] = all_finds
    return out


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    if cfg["llm"].get("thinking") is not False:
        sys.exit("ERROR: llm.thinking must be false for this corpus build "
                 "(requests send chat_template_kwargs.enable_thinking=False)")
    port = int(os.environ.get("VLLM_PORT", "8000"))
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()

    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    if not sections:
        sys.exit("ERROR: data/sections.jsonl missing; run stage 45 first")
    titles = {p["paper_id"]: p.get("title") for p in
              C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")}
    eligible = [s for s in sections
                if s.get("extraction_eligibility")
                and s.get("section_type") in ELIGIBLE_TYPES]
    if not eligible:
        sys.exit("ERROR: no eligible Abstract/Results/Discussion sections")

    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl",
                        key="section_record_id")

    def llm_fingerprint(s: dict) -> str:
        return C.sha256_text("|".join([
            str(s.get("text_hash_sha256")),
            cfg["llm"]["model"],
            cfg["llm"]["findings_prompt_version"],
            str(cfg["llm"]["max_prompt_chars"]),
            str(cfg["llm"]["max_tokens"]),
        ]))

    fp_by_sid = {s["section_record_id"]: llm_fingerprint(s) for s in eligible}

    def usable(sid):
        if not ckpt.has(sid, fp_by_sid[sid]):
            return False
        return ckpt.done[sid].get("llm_status") == "COMPLETE"

    pending = [s for s in eligible if not usable(s["section_record_id"])]
    prog = C.Progress(STAGE, total=len(eligible), unit="section", desc="findings")
    prog.count = len(eligible) - len(pending)
    if prog.bar is not None:
        prog.bar.update(prog.count)
        prog.bar.refresh()
    prog.log(f"eligible={len(eligible)} resumed={prog.count} pending={len(pending)} "
             f"model={cfg['llm']['model']} workers={cfg['llm']['workers']}")

    if not llmio.wait_for_server(port, prog):
        ev.record(pipeline_stage=STAGE, run_status="failed",
                  error_message=f"vLLM server not ready on port {port}")
        ev.close()
        prog.close(summary="FAILED: server not ready")
        sys.exit(1)

    lock = threading.Lock()
    n_com = n_par = n_fail = 0
    started = C.now_utc()

    def work(sec):
        sec = dict(sec)
        sec["paper_title"] = titles.get(sec["paper_id"])
        try:
            return enrich_section(sec, cfg, port)
        except Exception as e:  # noqa: BLE001
            return {"paper_id": sec["paper_id"],
                    "section_record_id": sec["section_record_id"],
                    "llm_status": "FAILED", "llm_error": f"worker: {e!r}",
                    "findings_raw": [], "llm_chunks": 0, "llm_chunks_failed": 1,
                    "llm_chunks_truncated": 0, "llm_input_chars": 0,
                    "llm_model": cfg["llm"]["model_label"],
                    "llm_model_version": "vllm",
                    "llm_prompt_version": cfg["llm"]["findings_prompt_version"]}

    if pending:
        with ThreadPoolExecutor(cfg["llm"]["workers"]) as ex:
            futs = {ex.submit(work, s): s for s in pending}
            for fut in as_completed(futs):
                r = fut.result()
                ckpt.add(r, fingerprint=fp_by_sid[r["section_record_id"]])
                with lock:
                    prog.update(1, detail=f"{r['section_record_id']} {r['llm_status']} "
                                          f"finds={len(r.get('findings_raw') or [])}")
                    if r["llm_status"] == "FAILED":
                        n_fail += 1
                        cur.add(r["paper_id"], STAGE, cfg["llm"]["model_label"],
                                PV, "finding extraction", r["llm_status"],
                                problem=str(r.get("llm_error"))[:300],
                                resolution="section skipped; no findings kept")
                    elif r["llm_status"] == "PARTIAL":
                        n_par += 1
                        cur.add(r["paper_id"], STAGE, cfg["llm"]["model_label"],
                                PV, "finding extraction", r["llm_status"],
                                problem=str(r.get("llm_error"))[:300],
                                resolution="findings kept; flagged unverified")
    ckpt.close()

    results = [ckpt.done[s["section_record_id"]] for s in eligible
               if s["section_record_id"] in ckpt.done]
    n_com = sum(1 for r in results if r.get("llm_status") == "COMPLETE")
    n_par = sum(1 for r in results if r.get("llm_status") == "PARTIAL")
    n_fail = sum(1 for r in results if r.get("llm_status") == "FAILED")
    C.write_jsonl(C.CORPUS_DIR / "data" / "findings_sections.jsonl", results)

    # ---- assign finding IDs per paper, ordered by (section_order, appearance) ----
    results_sorted = sorted(results, key=lambda r: (r["paper_id"],
                                                    r.get("section_order") or 0))
    # re-sort sections within a paper by section_order; chunk offset keeps
    # appearance order within a section
    findings_out = []
    per_paper = defaultdict(int)
    for r in results_sorted:
        for fd in r.get("findings_raw") or []:
            pid = r["paper_id"]
            per_paper[pid] += 1
            rec = {k: v for k, v in fd.items() if not k.startswith("_")}
            rec.update({
                "finding_id": f"{pid}_FIND_{per_paper[pid]:04d}",
                "corpus_id": pid,
                "study_id": f"{pid}_STUDY_001",
                "paper_id": pid,
                "evidence_section_id": r["section_record_id"],
                "evidence_locator_type": "section",
                "evidence_locator": None,        # filled by stage 55
                "text_version_id": r.get("llm_source_text_hash"),
                "extraction_method": "automated",
                "extractor_model_and_version": f"{r['llm_model']} ({r['llm_model_version']})",
                "extractor_prompt_version": r["llm_prompt_version"],
                "verification_status": "pending",   # human review is the gate
                "evidence_locator_status": None,      # filled by stage 55
                "reviewer": None,
                "review_date": None,
                "notes": ("evidence_text missing from LLM output"
                          if fd.get("_invalid_evidence_text") else None),
                "extraction_status_section": r["llm_status"],
                "llm_source_section_status": r["llm_status"],
            })
            findings_out.append(rec)
    C.write_jsonl(C.CORPUS_DIR / "data" / "findings.jsonl", findings_out)

    n_findings = len(findings_out)
    by_type = Counter(f["claim_type"] for f in findings_out)
    by_dir = Counter(f["direction"] for f in findings_out)
    by_sec_type = Counter(r.get("section_type") for r in results)
    no_evidence = sum(1 for f in findings_out
                      if not (f.get("evidence_text") or "").strip())
    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "sections_total": len(sections),
        "sections_eligible_for_findings": len(eligible),
        "sections_processed": len(results),
        "sections_complete": n_com, "sections_partial": n_par,
        "sections_failed": n_fail,
        "findings_total": n_findings,
        "findings_per_section_dist": dict(Counter(
            len(r.get("findings_raw") or []) for r in results)),
        "papers_with_findings": len({f["paper_id"] for f in findings_out}),
        "claim_type_counts": dict(by_type),
        "direction_counts": dict(by_dir),
        "findings_by_section_type": dict(by_sec_type),
        "findings_missing_evidence_text": no_evidence,
        "model": cfg["llm"]["model"],
        "model_label": cfg["llm"]["model_label"],
        "prompt_version": cfg["llm"]["findings_prompt_version"],
        "thinking": cfg["llm"]["thinking"],
        "temperature": cfg["llm"]["temperature"],
        "max_tokens": cfg["llm"]["max_tokens"],
        "workers": cfg["llm"]["workers"],
        "max_prompt_chars": cfg["llm"]["max_prompt_chars"],
        "reconciliation": {
            "eligible_equals_processed_plus_missing":
                len(eligible) == len(results) + (len(eligible) - len(results)),
            "status_sum_equals_processed": n_com + n_par + n_fail == len(results),
        },
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "findings_extraction_report.json",
                         summary)
    ev.record(pipeline_stage=STAGE,
              run_status="success" if not n_fail else "partial",
              model_name_version=cfg["llm"]["model_label"],
              prompt_version=cfg["llm"]["findings_prompt_version"],
              started_at=started, completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"findings={n_findings} sections={len(results)} complete={n_com} "
                   f"partial={n_par} failed={n_fail}")
    ev.close()
    prog.close(summary=f"findings={n_findings} complete={n_com} partial={n_par} "
                       f"failed={n_fail}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
