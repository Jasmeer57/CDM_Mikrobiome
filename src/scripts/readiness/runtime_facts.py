"""Runtime / cost fact sheet for the BiB manuscript (facts only; the authors write the text).

Three separate blocks, never summed into a whole-build figure:
  A. Benchmark timings (seconds per document) from the frozen benchmark outputs.
  B. Corpus-scale NER timings: each benchmarked program run once over the full 453-paper corpus text.
  C. Production runs of CDM 3.0.3: per registered run, SLURM accounting (sacct) for the job IDs recorded in the CDM's
     extraction_run table. Runs without recorded job IDs are UNKNOWN. The whole-build wall-clock and GPU-hours are
     UNKNOWN until every run's job provenance is confirmed; no estimate is made.
Plain .log/.out files deleted on 2026-10-30 are not used.

    python src/scripts/readiness/runtime_facts.py [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
FAIR = ROOT / "outputs/results/ner_fair_bench/fair_ner_metrics.json"
S1000 = ROOT / "outputs/results/benchmark/ner_species_s1000/species_metrics.json"
CORPUS = ROOT / "outputs/results/ner_corpus_bench/corpus_metrics.json"
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"


def nr(v):
    return "not recorded" if v is None else (f"{v:,}" if isinstance(v, int) else v)


def sacct(job_ids):
    """Allocation-level rows (one per array task) for the given job IDs."""
    if not job_ids:
        return []
    out = subprocess.run(["sacct", "-j", ",".join(job_ids), "-X", "-P", "-n", "-o",
                          "JobIDRaw,JobID,JobName,State,ElapsedRaw,AllocTRES,Start,End"],
                         capture_output=True, text=True, check=False).stdout
    rows = []
    for line in out.splitlines():
        raw, jid, name, state, el, tres, start, end = line.split("|")
        gpu = re.search(r"gres/gpu=(\d+)", tres)
        gtype = re.search(r"gres/gpu:([a-z0-9]+)=", tres)
        rows.append({"job": jid, "name": name, "state": state.split()[0], "elapsed_s": int(el or 0),
                     "gpus": int(gpu.group(1)) if gpu else 0, "gpu_type": gtype.group(1) if gtype else None,
                     "start": start, "end": end})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=ROOT / f"outputs/results/benchmark/runtime_facts_{date.today().isoformat()}")
    a = ap.parse_args()
    fair, s1000, corpus = json.load(open(FAIR)), json.load(open(S1000)), json.load(open(CORPUS))["models"]

    bench = [{"dataset": k.split("__")[0], "program": k.split("__")[1], "kind": v["meta"]["kind"],
              "device": v["meta"].get("device", "not recorded"), "docs": v["meta"].get("docs"), "seconds": v["meta"].get("seconds"),
              "sec_per_doc": v["meta"].get("sec_per_doc")} for k, v in fair.items()]
    bench += [{"dataset": "s1000", "program": k, "kind": v["meta"]["kind"], "device": v["meta"].get("device", "not recorded"),
               "docs": v["meta"].get("docs"), "seconds": v["meta"].get("seconds"), "sec_per_doc": v["meta"].get("sec_per_doc")}
              for k, v in s1000.items()]
    corp = [{"program": k, "kind": v["meta"]["kind"], "device": v["meta"].get("device", "not recorded"), "seconds": v["meta"].get("seconds"),
             "chunks": v["meta"].get("chunks"), "chars": v["meta"].get("chars")} for k, v in corpus.items()]

    con = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    runs, allocs = [], {}
    for rid, stage, model, jobs_txt, verification in con.execute(
            "select extraction_run_id, stage, model, job_ids, verification from extraction_run"):
        ids = re.findall(r"\b(2\d{7})\b", f"{jobs_txt or ''} {rid if re.fullmatch(r'2[0-9]{7}', rid) else ''}")
        ids = sorted(set(ids))
        alloc = sacct(ids)
        r = {"run": rid, "stage": stage, "model": model, "verification": verification, "job_ids": ids,
             "sacct_tasks": len(alloc)}
        allocs[rid] = alloc
        if not ids:
            r["status"] = "UNKNOWN: no job ID recorded"
        elif not alloc:
            r["status"] = "UNKNOWN: job IDs not in SLURM accounting"
        else:
            states = sorted({x["state"] for x in alloc})
            r |= {"states": states, "task_seconds": sum(x["elapsed_s"] for x in alloc),
                  "gpu_hours": round(sum(x["elapsed_s"] * x["gpus"] for x in alloc) / 3600, 2),
                  "gpu_types": sorted({x["gpu_type"] for x in alloc if x["gpu_type"]}),
                  "first_start": min(x["start"] for x in alloc), "last_end": max(x["end"] for x in alloc),
                  "status": "RECORDED" if states == ["COMPLETED"] else
                  "RECORDED, NOT ALL COMPLETED: the run may have continued in jobs not recorded"}
        runs.append(r)
    known = [r for r in runs if r["status"] == "RECORDED"]
    unknown = [r for r in runs if not r["status"].startswith("RECORDED")]
    partial = [r for r in runs if r["status"].startswith("RECORDED, NOT")]
    # several registry rows name the same jobs (e.g. a stage row and its "apply" row): count each task once
    owner, uniq = {}, {}
    for r in known:
        for x in allocs[r["run"]]:
            owner.setdefault(x["job"], []).append(r["run"])
            uniq[x["job"]] = x
    for r in known:
        shared = sorted({o for x in allocs[r["run"]] for o in owner[x["job"]]} - {r["run"]})
        if shared:
            r["shares_jobs_with"] = shared
    uniq_s = sum(x["elapsed_s"] for x in uniq.values())
    uniq_gpu_h = round(sum(x["elapsed_s"] * x["gpus"] for x in uniq.values()) / 3600, 2)

    a.out.mkdir(parents=True, exist_ok=True)
    json.dump({"generated": date.today().isoformat(), "benchmark": bench, "corpus_scale_ner": corp,
               "production_runs": runs,
               "distinct_task_sum_recorded_runs_only": {"tasks": len(uniq), "task_seconds": uniq_s,
                                                        "gpu_hours": uniq_gpu_h}, "whole_build": "UNKNOWN (job provenance incomplete; no estimate made)",
               "inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (FAIR, S1000, CORPUS, CDM)}}, open(a.out / "summary.json", "w"), indent=1)

    L = [f"# Runtime and cost facts, {date.today().isoformat()}", "",
         "Facts only, for the authors. Generated by `src/scripts/readiness/runtime_facts.py`; data in `summary.json`. "
         "Blocks A–C are separate and must not be added together.", "",
         "## Whole-build wall-clock and GPU-hours: **UNKNOWN**", "",
         f"- {len(runs)} runs are registered in CDM 3.0.3 (`extraction_run`). SLURM accounting covers "
         f"{len(known)} fully; {len(partial)} only partly (a recorded job did not complete); {len(unknown)} not at all.",
         "- No estimate is made from other SLURM jobs. The total stays unknown until every run's job provenance is "
         "confirmed.", "",
         "Runs without SLURM accounting:", ""]
    L += [f"- `{r['run']}` ({r['stage']}): {r['status']}" for r in unknown]
    L += ["", "Runs whose recorded job did not complete:", ""]
    L += [f"- `{r['run']}` ({r['stage']}): job(s) {', '.join(r['job_ids'])} state {', '.join(r['states'])}, "
          f"{r['task_seconds']} s; the registry still marks it {r['verification']}" for r in partial]
    L += ["", "## C. Production runs with complete SLURM accounting", "",
          "Task-seconds = sum of elapsed time over array tasks (parallel tasks overlap in wall time). GPU-hours = "
          "sum of elapsed × allocated GPUs.", "",
          "| Run | Stage | Tasks | Task-seconds | GPU-hours | GPU | First start → last end |", "|---|---|---|---|---|---|---|"]
    for r in known:
        L.append(f"| `{r['run']}`{' †' if r.get('shares_jobs_with') else ''} | {r['stage']} | {r['sacct_tasks']} | {r['task_seconds']:,} | {r['gpu_hours']} | "
                 f"{', '.join(r['gpu_types']) or 'CPU'} | {r['first_start']} → {r['last_end']} |")
    L.append(f"| **sum over distinct job tasks of these runs only** | | {len(uniq)} | {uniq_s:,} | {uniq_gpu_h} | | |")
    L += ["", "Rows marked † share jobs with another row; the sum counts each job task once. It covers only the runs "
          "listed and is **not** the cost of the build.", "",
          "## B. Corpus-scale NER (benchmark run of each program over the full corpus text)", "",
          "One pass per program over the same chunks of the 453-paper corpus (not the production extraction).", "",
          "| Program | Kind | Device | Seconds | Chunks | Characters |", "|---|---|---|---|---|---|"]
    for c in sorted(corp, key=lambda c: c["seconds"] or 0):
        L.append(f"| {c['program']} | {c['kind']} | {c['device']} | {nr(c['seconds'])} | {c['chunks']} | {nr(c['chars'])} |")
    L += ["", "## A. Benchmark timings (seconds per document)", "",
          "| Dataset | Program | Kind | Device | Docs | Seconds | s/doc |", "|---|---|---|---|---|---|---|"]
    for b in sorted(bench, key=lambda b: (b["dataset"], b["sec_per_doc"] is None, b["sec_per_doc"] or 0)):
        L.append(f"| {b['dataset']} | {b['program']} | {b['kind']} | {b['device']} | {nr(b['docs'])} | {nr(b['seconds'])} | "
                 f"{nr(b['sec_per_doc'])} |")
    L += ["", "**Before use:** register any number that enters the manuscript (claims register), then re-run "
          "`claims_register.py` and `manuscript_number_audit.py`."]
    (a.out / "RUNTIME_FACTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written:", a.out, f"runs {len(runs)}: recorded {len(known)}, partial {len(partial)}, unknown {len(unknown)}")


if __name__ == "__main__":
    main()
