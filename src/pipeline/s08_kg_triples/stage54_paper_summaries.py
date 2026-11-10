#!/usr/bin/env python3
"""Stage 54: LLM per-paper SUMMARY records, one per paper, generated from that
paper's Abstract + Results + Discussion sections (conclusion sections are
typed Discussion but matched by heading too, so they are always included).

Runs INSIDE the same A100 Slurm job as stage 53 (stage 53 must have started
the vLLM servers; stage 54 reuses them on ports VLLM_PORT / VLLM_PORT+1).
Like stage 53 it shards across the two GPUs via SHARD_COUNT/SHARD_INDEX over
a stable sha256(paper_id) split, writes per-shard checkpoints/outputs, then a
`--merge` pass (same job, CPU) reassembles and fails closed on gaps.

Contents are LLM paraphrase by design - they are GENERATED text, not verbatim
evidence. Every record states this explicitly (content_type
llm_generated_unverified, verification_status pending); nothing here feeds
quantitative claims. Numbers may be copied verbatim but are not verified.

Null vocabulary: not_reported / unavailable / pending (same as stage 53).

Outputs (final, after --merge)
  data/paper_summaries.jsonl          one record per paper (453 expected)
  validation/summaries_extraction_report.json
"""
import json
import os
import re
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C
import pipeline.llmio

STAGE = "stage54_paper_summaries"
PV = "2.1.0"
NR = "not_reported"
UNAVAIL = "unavailable"
UNRES = "unresolved"
PENDING = "pending"

SUMMARY_TYPES = ("Abstract", "Results", "Discussion")


SUMMARY_PROMPT = """You write a structured summary of ONE human-microbiome paper from its Abstract/Results/Discussion/Conclusion text only.
The summary is for a corpus build: it must be faithful, contain no invented numbers, and copy any statistic exactly as written or omit it.

Return STRICT JSON (no markdown, no commentary) with exactly these keys:
{{
  "paper_summary": "continuous prose, 100-180 words, covering study aim, population/body site, main findings incl. null findings, and reported effect direction",
  "key_findings": ["3 to 8 short statements, each under 30 words, one per distinct main finding incl. any null results; copy statistics verbatim or leave them out"],
  "main_conclusion": "the authors' stated conclusion or takeaway in under 60 words",
  "limitations_as_reported": "the limitations the authors state themselves, under 60 words, or not_reported if none are stated"
}}

Rules:
- Use ONLY the text provided; do not add prior knowledge.
- NEVER invent, estimate or round a number. Copy p-values, effect sizes and counts verbatim or omit them.
- Include null/negative findings in key_findings; do not present only positive results.
- If the text contains no results (e.g. methods-only), say so plainly in paper_summary and return an empty key_findings list.

Paper "{title}" (id {paper_id}):
{chunk}"""

MAX_PROMPT_CHARS = 40000        # ~10k tokens; fits comfortably in 32k ctx


def sanitize_summary(data):
    issues = []
    out = {}

    def txt(key, max_words, label):
        v = " ".join(str(data.get(key) or "").split())
        if not v or v.lower() == NR:
            v = NR
            issues.append(f"{label}_missing")
        n_words = len(v.split())
        if v != NR and n_words > max_words:
            issues.append(f"{label}_too_long_{n_words}w")
        return v

    out["paper_summary"] = txt("paper_summary", 260, "paper_summary")
    kf = data.get("key_findings")
    if not isinstance(kf, list):
        kf = []
        issues.append("key_findings_not_a_list")
    kf_clean = []
    for k in kf[:12]:                     # hard cap; extra drop is outrageous
        if isinstance(k, str) and k.strip() and len(k.strip().split()) <= 60:
            kf_clean.append(" ".join(k.split()))
    if len(kf) > len(kf_clean):
        issues.append("key_findings_truncated")
    if not kf_clean:
        issues.append("key_findings_missing")
    out["key_findings"] = kf_clean
    out["main_conclusion"] = txt("main_conclusion", 120, "main_conclusion")
    out["limitations_as_reported"] = txt(
        "limitations_as_reported", 120, "limitations_as_reported")
    out["_issues"] = issues
    return out


def enrich_paper(paper, sections, cfg, port):
    """Summarize one paper; return the paper-level record."""
    pid = paper["paper_id"]
    out = {
        "paper_id": pid,
        "llm_model": cfg["llm"]["model_label"],
        "llm_model_version": f"vllm:{cfg['llm']['runtime']}",
        "llm_prompt_version": cfg["llm"]["summaries_prompt_version"],
        "llm_status": "FAILED", "llm_error": None,
        "llm_chunks": 0, "llm_chunks_failed": 0, "llm_chunks_truncated": 0,
        "llm_split_retries": 0, "llm_input_chars": 0, "llm_degrees": [],
        "source_section_ids": [s["section_record_id"] for s in sections],
        "source_section_count": len(sections),
        "source_input_hash": C.sha256_text("\n\n".join(
            (s.get("section_text_original") or "")
            for s in sections)),
        "paper_summary_raw": [], "key_findings_raw": [],
        "main_conclusion_raw": [], "limitations_raw": [],
        "issues_raw": [],
    }
    text, _ = source_text_for_paper_prebuilt(sections)
    if not text:
        out["llm_status"] = "COMPLETE"   # vacuous: nothing summarizable
        out["no_source_sections"] = True
        return out
    chunks = C.chunk_text(text, MAX_PROMPT_CHARS)

    def build_prompt(chunk):
        return SUMMARY_PROMPT.format(
            title=paper.get("title") or "untitled",
            paper_id=pid, chunk=chunk)

    extract = llmio.make_extractor(cfg, port, out, build_prompt)

    statuses = []
    for ci, chunk in enumerate(chunks):
        out["llm_input_chars"] += len(chunk)
        try:
            data, status, err = extract(chunk, ci, 0)
            parsed = None
            if status != "FAILED" and isinstance(data, dict):
                parsed = data
            if status == "COMPLETE" and parsed is None:
                status, err = "FAILED", "no JSON object in response"
            if parsed is not None:
                s = sanitize_summary(parsed)
                if status == "COMPLETE":
                    out["paper_summary_raw"].append(s["paper_summary"])
                    out["key_findings_raw"].extend(s["key_findings"])
                    out["main_conclusion_raw"].append(s["main_conclusion"])
                    out["limitations_raw"].append(
                        s["limitations_as_reported"])
                    out["issues_raw"].extend(s["_issues"])
                else:
                    # keep PARTIAL chunk content visible but flagged
                    out["paper_summary_raw"].append(s["paper_summary"])
                    out["key_findings_raw"].extend(s["key_findings"])
                    out["issues_raw"].extend(s["_issues"] +
                                             [f"chunk{ci}_status_{status}"])
            statuses.append(status)
            if status != "COMPLETE":
                out["llm_error"] = ((out["llm_error"] + "; ")
                                    if out["llm_error"] else "") + \
                    f"chunk{ci}:{err}"
                if status == "PARTIAL":
                    out["llm_chunks_truncated"] += 1
                else:
                    out["llm_chunks_failed"] += 1
            out["llm_chunks"] += 1
        except Exception as e:  # noqa: BLE001
            statuses.append("FAILED")
            out["llm_chunks_failed"] += 1
            out["llm_chunks"] += 1
            out["llm_error"] = ((out["llm_error"] + "; ")
                                if out["llm_error"] else "") + \
                f"chunk{ci}:{e}"

    if all(s == "COMPLETE" for s in statuses):
        out["llm_status"] = "COMPLETE"
    elif any(s == "COMPLETE" for s in statuses):
        out["llm_status"] = "PARTIAL"
    else:
        out["llm_status"] = "FAILED"
    return out


def source_text_for_paper_prebuilt(sections):
    """Same logic as source_text_for_paper but over a pre_VERIFIED list of
    source sections (already filtered to eligible types) - returns (text, count)."""
    parts = []
    for s in sorted(sections, key=lambda x: x.get("section_order") or 0):
        label = s.get("section_name_original") or \
            s.get("section_type") or "section"
        parts.append(f"[{label}]\n{(s.get('section_text_original') or '').strip()}")
    return "\n\n".join(parts), len(parts)


def shard_of(pid):
    return int(C.sha256_text(pid)[:8], 16) % int(
        os.environ.get("SHARD_COUNT", "1"))


def select_source_sections(sections, papers_by_id):
    """For every paper: Abstract + Results + Discussion sections plus any
    conclusion-named section, excluding boilerplate/containers/context-empty."""
    by_paper = defaultdict(list)
    for s in sections:
        by_paper[s["paper_id"]].append(s)
    chosen, missing_sections = {}, {}
    for pid in papers_by_id:
        used = []
        for s in sorted(by_paper[pid],
                        key=lambda x: x.get("section_order") or 0):
            st = s.get("section_type")
            name = (s.get("section_name_original") or "").lower()
            if st not in SUMMARY_TYPES and "conclu" not in name:
                continue
            if (st in ("References", "Acknowledgements")
                    or s.get("is_container_section")):
                continue
            text = (s.get("section_text_original") or "").strip()
            if not text:
                continue
            used.append(s)
        chosen[pid] = used
        if not used:
            missing_sections[pid] = "no_abstract_results_discussion_text"
    return chosen, missing_sections


def merge_only(cfg):
    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    papers_by_id = {p["paper_id"]: p for p in papers}
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    chosen, missing_sections = select_source_sections(sections, papers_by_id)

    n_shards = int(os.environ.get("SHARD_COUNT", "1"))
    recs = []
    for i in range(n_shards):
        p = (C.CORPUS_DIR / "data" /
             ("paper_summaries.jsonl" if n_shards == 1
              else f"paper_summaries.shard{i}.jsonl"))
        if not p.exists():
            sys.exit(f"ERROR: missing shard output {p}")
        rs = C.read_jsonl(p)
        for r in rs:
            if shard_of(r["paper_id"]) != i:
                sys.exit(f"ERROR: paper {r['paper_id']} in shard {i} but "
                         f"belongs to shard {shard_of(r['paper_id'])}")
        recs.extend(rs)
    by_pid = {r["paper_id"]: r for r in recs}
    missing = [pid for pid in papers_by_id if pid not in by_pid]
    if missing:
        sys.exit(f"ERROR: {len(missing)} papers not covered, "
                 f"e.g. {missing[:5]}")

    records = []
    for p in papers:
        pid = p["paper_id"]
        r = by_pid[pid]
        src = chosen[pid]
        n_chunks = r.get("llm_chunks") or 0
        issues = list(r.get("issues_raw") or [])
        summary = " ".join(x for x in r.get("paper_summary_raw")
                           if x and x != NR)
        key_findings = [k for k in (r.get("key_findings_raw") or []) if k]
        # dedup key findings preserving order (multi-chunk splices)
        seen, kf_dedup = set(), []
        for k in key_findings:
            if k.lower() not in seen:
                seen.add(k.lower())
                kf_dedup.append(k)
        main_conclusion = " ".join(x for x in r.get("main_conclusion_raw")
                                   if x and x != NR)
        limitations = " ".join(x for x in r.get("limitations_raw")
                               if x and x != NR)
        if not src:
            summary = summary or "unavailable_no_eligible_source_sections"
            issues.append("no_eligible_source_sections")
        if r.get("llm_status") == "FAILED" and not summary:
            summary = "unavailable_generation_failed"
        rec = {
            # A. identification
            "summary_id": f"{pid}_SUMM_0001",
            "corpus_id": cfg["corpus"]["corpus_id"],
            "graph_id": cfg["corpus"]["corpus_id"],
            "graph_version": PV,
            "record_status": "active",
            "extraction_run_id": f"{STAGE}@{PV}",
            # B. subject (the paper itself)
            "paper_id": pid,
            "PMID": p.get("PMID") or NR,
            "PMCID": p.get("PMCID") or NR,
            "DOI": p.get("DOI") or NR,
            "paper_title": p.get("title") or "untitled",
            "publication_year": p.get("publication_year") or NR,
            # C. content (LLM paraphrase - flagged, never verbatim claims)
            "paper_summary": summary,
            "key_findings": kf_dedup,
            "main_conclusion": main_conclusion,
            "limitations_as_reported": limitations,
            "content_type": "llm_generated_unverified_paraphrase",
            "summary_word_count": len(summary.split()),
            "key_finding_count": len(kf_dedup),
            # D. input provenance
            "source_section_ids": [s["section_record_id"] for s in src],
            "source_section_types": [s.get("section_type") for s in src],
            "source_section_count": len(src),
            "source_input_hash": C.sha256_text("\n\n".join(
                (s.get("section_text_original") or "") for s in src)),
            "source_text_coverage_status": (
                "complete" if r.get("llm_status") == "COMPLETE"
                else ("partial" if r.get("llm_status") == "PARTIAL"
                      else "incomplete")),
            # E. extraction provenance
            "llm_model": r.get("llm_model"),
            "llm_model_version": r.get("llm_model_version"),
            "llm_prompt_version": r.get("llm_prompt_version"),
            "prompt_id": "HMCV2-SUMMARY-PROMPT",
            "prompt_version": cfg["llm"]["summaries_prompt_version"],
            "llm_status": r.get("llm_status"),
            "llm_chunks": n_chunks,
            "llm_chunks_failed": r.get("llm_chunks_failed"),
            "llm_chunks_truncated": r.get("llm_chunks_truncated"),
            "truncation_status": bool(r.get("llm_chunks_truncated")),
            "extraction_method": "automated",
            "extraction_model_name": r.get("llm_model"),
            "extraction_model_version": r.get("llm_model_version"),
            "extraction_timestamp": C.now_utc(),
            # F. validation/disposition
            "human_review_status": PENDING,
            "verification_status": PENDING,
            "automated_validation_status": (
                "checks_passed" if not issues else "flagged_needs_review"),
            "triple_quality_status": "not_applicable_summary_record",
            "inclusion_status": "included_v1",
            "exclusion_reason": None,
            "publication_readiness": "pending_human_review",
            "unresolved_issues": issues or None,
            "llm_error": r.get("llm_error"),
        }
        records.append(rec)

    C.write_jsonl(C.CORPUS_DIR / "data" / "paper_summaries.jsonl", records)

    missing_src_fields = {pid: v for pid, v in missing_sections.items()}
    report = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "shards": n_shards,
        "papers_total": len(papers),
        "papers_summarized": len(records),
        "papers_missing_from_output": missing,
        "papers_with_no_source_sections": missing_src_fields,
        "llm_status_counts": dict(Counter(
            r.get("llm_status") for r in recs)),
        "papers_with_flags": sum(1 for r in records
                                 if r.get("unresolved_issues")),
        "summary_word_count_median": sorted(
            r["summary_word_count"] for r in records)[len(records) // 2]
        if records else 0,
        "key_finding_avg": (sum(r["key_finding_count"]
                                for r in records) / len(records))
        if records else 0,
        "source_section_count_median": sorted(
            r["source_section_count"] for r in records)[len(records) // 2]
        if records else 0,
        "model": cfg["llm"]["model"], "model_label": cfg["llm"]["model_label"],
        "prompt_version": cfg["llm"]["summaries_prompt_version"],
        "thinking": cfg["llm"]["thinking"],
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "reconciliation": {
            "papers_all_present": not missing,
            "records_unique": len({r["summary_id"] for r in records})
            == len(records),
        },
    }
    C.atomic_write_json(
        C.CORPUS_DIR / "validation" / "summaries_extraction_report.json",
        report)
    return report


def main():
    C.require_slurm(STAGE)
    if "--merge" in sys.argv:
        cfg = C.load_config()
        report = merge_only(cfg)
        ev = C.Events(cfg["corpus"]["corpus_id"], f"{STAGE}-merge", PV)
        ev.record(pipeline_stage=f"{STAGE}-merge",
                  run_status="success" if report["reconciliation"][
                      "papers_all_present"] else "partial",
                  note=f"papers={report['papers_summarized']} "
                       f"flags={report['papers_with_flags']}")
        ev.close()
        print(json.dumps(report, indent=2))
        return

    cfg = C.load_config()
    if cfg["llm"].get("thinking") is not False:
        sys.exit("ERROR: llm.thinking must be false for this corpus build")
    port = int(os.environ.get("VLLM_PORT", "8000"))
    shard_n = int(os.environ.get("SHARD_COUNT", "1"))
    shard_i = int(os.environ.get("SHARD_INDEX", "0"))
    if not (0 <= shard_i < max(shard_n, 1)):
        sys.exit(f"ERROR: SHARD_INDEX {shard_i} out of range")

    os.environ["SHARD_COUNT"] = str(shard_n)   # shard_of reads it
    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    papers_by_id = {p["paper_id"]: p for p in papers}
    chosen, missing_sections = select_source_sections(sections, papers_by_id)

    mine = [p for p in papers if shard_of(p["paper_id"]) == shard_i]
    suffix = "" if shard_n == 1 else f".shard{shard_i}"
    ckpt = C.Checkpoint(
        C.CORPUS_DIR / "checkpoints" / f"{STAGE}{suffix}.jsonl",
        key="paper_id")

    def llm_fingerprint(p: dict) -> str:
        src = chosen[p["paper_id"]]
        return C.sha256_text("|".join([
            str(p.get("title")),
            C.sha256_text("\n\n".join(
                (s.get("section_text_original") or "") for s in src)),
            cfg["llm"]["model"],
            cfg["llm"]["summaries_prompt_version"],
            str(MAX_PROMPT_CHARS),
            str(cfg["llm"]["max_tokens"]),
        ]))

    fp_by_pid = {p["paper_id"]: llm_fingerprint(p) for p in papers}

    def usable(pid):
        if not ckpt.has(pid, fp_by_pid[pid]):
            return False
        return ckpt.done[pid].get("llm_status") == "COMPLETE"

    pending = [p for p in mine if not usable(p["paper_id"])]
    workers = int(os.environ.get(
        "WORKERS", str(cfg["llm"].get("workers_a100",
                                      cfg["llm"]["workers"]))))
    prog = C.Progress(STAGE, total=len(mine), unit="paper", desc="summaries")
    prog.count = len(mine) - len(pending)
    if prog.bar is not None:
        prog.bar.update(prog.count)
        prog.bar.refresh()
    prog.log(f"shard {shard_i}/{shard_n} papers={len(mine)} "
             f"resumed={prog.count} pending={len(pending)} "
             f"model={cfg['llm']['model']} workers={workers}")

    if not llmio.wait_for_server(port, prog):
        prog.close(summary="FAILED: server not ready")
        sys.exit(1)

    ev = C.Events(cfg["corpus"]["corpus_id"],
                  STAGE if shard_n == 1 else f"{STAGE}-s{shard_i}", PV)
    cur = C.CurationLog()
    lock = threading.Lock()
    started = C.now_utc()

    def work(paper):
        try:
            return enrich_paper(paper, chosen[paper["paper_id"]], cfg, port)
        except Exception as e:  # noqa: BLE001
            return {"paper_id": paper["paper_id"],
                    "llm_status": "FAILED", "llm_error": f"worker: {e!r}",
                    "llm_chunks": 0, "llm_chunks_failed": 1,
                    "llm_chunks_truncated": 0, "llm_input_chars": 0,
                    "llm_model": cfg["llm"]["model_label"],
                    "llm_model_version": "vllm",
                    "llm_prompt_version":
                        cfg["llm"]["summaries_prompt_version"]}

    if pending:
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(work, p): p for p in pending}
            for fut in as_completed(futs):
                r = fut.result()
                ckpt.add(r, fingerprint=fp_by_pid[r["paper_id"]])
                with lock:
                    prog.update(1, detail=(
                        f"{r['paper_id']} {r['llm_status']} "
                        f"chunks={r.get('llm_chunks')}"))
                    if r["llm_status"] != "COMPLETE":
                        cur.add(r["paper_id"], STAGE,
                                cfg["llm"]["model_label"], PV,
                                "paper summary", r["llm_status"],
                                problem=str(r.get("llm_error"))[:300],
                                resolution="paper kept with status; "
                                           "resumable via checkpoint")
    ckpt.close()

    results = [ckpt.done[p["paper_id"]] for p in mine
               if p["paper_id"] in ckpt.done]
    C.write_jsonl(C.CORPUS_DIR / "data" / f"paper_summaries{suffix}.jsonl",
                  results)
    n_com = sum(1 for r in results if r.get("llm_status") == "COMPLETE")
    n_par = sum(1 for r in results if r.get("llm_status") == "PARTIAL")
    n_fail = sum(1 for r in results if r.get("llm_status") == "FAILED")
    ev.record(pipeline_stage=STAGE,
              run_status="success" if not n_fail else "partial",
              model_name_version=cfg["llm"]["model_label"],
              prompt_version=cfg["llm"]["summaries_prompt_version"],
              started_at=started, completed_at=C.now_utc(),
              note=f"shard {shard_i}/{shard_n} papers={len(results)} "
                   f"complete={n_com} partial={n_par} failed={n_fail}")
    ev.close()
    prog.close(summary=f"shard{shard_i} papers={len(results)} "
                       f"complete={n_com} partial={n_par} failed={n_fail}")
    print(json.dumps({"shard": shard_i, "papers": len(results),
                      "complete": n_com, "partial": n_par, "failed": n_fail},
                     indent=2))


if __name__ == "__main__":
    main()
