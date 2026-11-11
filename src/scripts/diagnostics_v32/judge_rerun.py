"""Run-to-run variance of the catalogue judges (diagnostics 2026-11-11, item 2): evidence_judge_v2.py unchanged
(rubric v2, same PROMPT_SHA256), restricted to a fixed sample of catalogue records (judge_sample.json written by
make_samples.py). Temperature from tempctl (DIAG_TEMPERATURE), default 0 as in the script.

    [DIAG_TEMPERATURE=0.7 DIAG_SEED=20261111] python src/scripts/diagnostics_v32/judge_rerun.py --sample FILE \
        --model qwen9 --host http://127.0.0.1:P --out DIR
Output DIR/all/<model>.shard0.jsonl. Written with Claude Code (declare)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/diagnostics_v32"))
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
import tempctl  # noqa: E402,F401
import evidence_judge_v2 as J  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    keep = {(t, r) for t, r in json.load(open(a.sample))["records"]}
    orig = J.V1.records
    J.V1.records = lambda: [r for r in orig() if (r["table"], r["record_id"]) in keep]
    return J.main(["judge", "--model", a.model, "--host", a.host, "--split", "all", "--out", str(a.out), "--parallel", "48"])


if __name__ == "__main__":
    raise SystemExit(main())
