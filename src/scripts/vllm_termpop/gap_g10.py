"""G10 — full-census LLM-judge evaluation of the v3.1 catalogue (Gemma, C1 rubric).

Reuses the existing judge: src/scripts/llm_judge_a40/build_inputs_full.py (C1 builder, pointed at the
v3.1 records) and run_judge_client_full.py + prompts/judge_C1.txt, so v3.1 rates are comparable with
the v2 full-census numbers in releases/frozen_output/05_evidence.

    python gap_g10.py inputs --nparts 8        # CPU: input_full_C1.part{k}.jsonl
    python gap_g10.py merge                    # CPU: merge parts + metrics
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import gaplib as G

PIPE = G.REPO_ROOT / "src/scripts/llm_judge_a40"
OUT = G.GAP_DIR / "G10"
CAT = G.RESULTS / "catalogue_v3_1"


def inputs(nparts):
    sys.path.insert(0, str(PIPE))
    import build_inputs_full as B
    B.RECORDS = str(CAT / "catalogue_records.jsonl")
    OUT.mkdir(parents=True, exist_ok=True)
    full = OUT / "input_full_C1.jsonl"
    w = B.Writer(str(full)) if hasattr(B, "Writer") else None
    if w is None:  # the builder's writer class name
        cls = next(v for k, v in vars(B).items() if isinstance(v, type) and hasattr(v, "write") and hasattr(v, "close"))
        w = cls(str(full))
    stats = B.build_c1(w, 0.005)
    w.close()
    rows = open(full, encoding="utf-8").read().splitlines()
    for k in range(nparts):
        (OUT / f"input_full_C1.part{k}.jsonl").write_text("\n".join(rows[k::nparts]) + "\n", encoding="utf-8")
    print(json.dumps({**stats, "parts": nparts}, indent=1))


def merge():
    res = OUT / "results"
    res.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(OUT.glob("C1_part*_verdicts.jsonl")):
        rows += [l for l in open(p, encoding="utf-8") if l.strip()]
    (res / "C1_full_verdicts.jsonl").write_text("".join(rows), encoding="utf-8")
    print(f"merged {len(rows)} verdicts")
    subprocess.run([sys.executable, str(PIPE / "compute_judge_metrics_a40.py"), "--results", str(res),
                    "--out", str(OUT / "JUDGE_METRICS_V3_1.md")], check=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inputs", "merge"])
    ap.add_argument("--nparts", type=int, default=8)
    a = ap.parse_args()
    inputs(a.nparts) if a.cmd == "inputs" else merge()
