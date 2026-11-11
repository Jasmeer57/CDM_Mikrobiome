"""Relation evaluation of layer 3.2.0-candidate on the competitor gold sets: the task `rel` of
src/scripts/competitors/competitor_llm_runner.py with ONLY two changes: (1) the v3.2 typer (retype_triples_v32.py:
v3.1 prompt + corpus-derived labels + open cue, same cue check / direction rules / verifier) and (2) the frozen Fix B
syntactic filter (bench_parse.jsonl from bench_parse.py): items that fail -> CO_OCCURRENCE_ONLY, no model call.
Items (rel_items), context, entity types ("OTHER_RELATION" predicate, "UNKNOWN" hints), batching and output fields are the
original runner's. Gold labels are not shown to the model.

    python src/scripts/fixes_v32/bench_llm_v32.py --port P --outdir DIR [--shard i --nshards n]

Output DIR/rel/rel.shardN.jsonl (resumable). Run inside v32.sbatch (TASK=bench). Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src/scripts/competitors"))
import competitor_llm_runner as CR  # noqa: E402
import retype_triples_v32 as R  # noqa: E402

PARSE = ROOT / "outputs/results/fixes_v32_2026-11-11/parse/bench_parse.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--model", default="cyankiwi/Qwen3.5-9B-AWQ-4bit")
    ap.add_argument("--db303", type=Path, default=CR.DB303)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--outdir", type=Path, required=True)
    a = ap.parse_args()
    c303 = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
    labels, prompt = R.labels_and_prompt(c303)
    schema = R.V3.make_schema(labels)
    syn = {j["id"]: j for j in (json.loads(l) for l in open(PARSE, encoding="utf-8"))}
    items = CR.rel_items()
    assert all(t["id"] in syn for t in items), "bench_parse.jsonl incomplete"
    items = [t for i, t in enumerate(items) if i % a.nshards == a.shard]
    out = a.outdir / "rel"
    out.mkdir(parents=True, exist_ok=True)
    res = out / f"rel.shard{a.shard}.jsonl"
    done = {r["id"] for r in CR.read_jsonl(res) if r["relation"] != "UNPARSED"}
    todo = [t for t in items if t["id"] not in done]
    print(f"rel v3.2: {len(items):,} items in shard; {len(todo):,} to run; {len(labels)} labels; model {a.model}", flush=True)
    lock = threading.Lock()
    keys = ("id", "ds", "split", "doc", "sent", "subject", "stype", "object", "otype", "gold")

    def run(batch):
        recs, typed = [], []
        for t in batch:
            s = syn[t["id"]]
            base = {**{k: t[k] for k in keys}, "syntax_status": s["status"], "syntax_connected": s["connected"],
                    "model": a.model, "prompt_version": R.PV, "labels_sha256": R.LABELS_SHA}
            if s["connected"] is False:
                recs.append({**base, "relation": "CO_OCCURRENCE_ONLY", "model_relation": None, "direction": "SAME",
                             "direction_model": "", "direction_word_order": None, "cue": "", "cue_found": False,
                             "specific_verified": False, "open_cue_verified": False, "verify": None})
            else:
                typed.append((t, base))
        if typed:
            its = [[n, t["subject"], t["stype"], "OTHER_RELATION", t["object"], t["otype"], "UNKNOWN", [t["ctx"]]]
                   for n, (t, _) in enumerate(typed)]
            fins = R.type_batch(a.port, a.model, prompt, schema, its, [(t["subject"], t["object"]) for t, _ in typed],
                                [[t["ctx"]] for t, _ in typed])
            recs += [{**base, **fins[n]} for n, (_, base) in enumerate(typed)]
        with lock, open(res, "a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + R.BATCH]) for i in range(0, len(todo), R.BATCH)]
        for k, fu in enumerate(as_completed(futs)):
            fu.result()
            if k % 100 == 0:
                print(f"  {k * R.BATCH:,}/{len(todo):,} {time.time() - t0:.0f}s", flush=True)
    print("rel v3.2 done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
