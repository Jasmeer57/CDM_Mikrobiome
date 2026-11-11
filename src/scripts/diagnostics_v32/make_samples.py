"""Fixed random sample of catalogue records for the judge run-variance check (diagnostics 2026-11-11, item 2).

Population: catalogue records judged in the frozen rubric-v2 TEST run (outputs/results/benchmark/judge_v2_2026-11-10/
test/) WITHOUT error by all three judges (Qwen3.5-9B, Llama-3.1-8B, Mistral-7B). Sample: random.Random(20261111).sample
of 500 (sorted keys first). Writes outputs/results/diagnostics_2026-11-11/run_variance/judge_sample.json.
Written with Claude Code (declare)."""
from __future__ import annotations

import glob
import json
import random
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
FROZEN = ROOT / "outputs/results/benchmark/judge_v2_2026-11-10/test"
OUT = ROOT / "outputs/results/diagnostics_2026-11-11/run_variance"
SEED, N = 20261111, 500


def ok_keys(model):
    k = set()
    for f in sorted(glob.glob(str(FROZEN / f"{model}.shard*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            j = json.loads(line)
            if "error" not in j:
                k.add((j["table"], j["record_id"]))
    return k


def main():
    per = {m: ok_keys(m) for m in ("qwen9", "llama", "mistral")}
    pop = sorted(per["qwen9"] & per["llama"] & per["mistral"])
    smp = sorted(random.Random(SEED).sample(pop, N))
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump({"seed": SEED, "n": N, "population": len(pop), "population_def": __doc__.split("\n\n")[1],
               "per_model_ok": {m: len(v) for m, v in per.items()}, "records": smp}, open(OUT / "judge_sample.json", "w"), indent=0)
    print(len(pop), {m: len(v) for m, v in per.items()})


if __name__ == "__main__":
    main()
