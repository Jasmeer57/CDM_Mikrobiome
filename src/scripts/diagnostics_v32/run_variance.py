"""Run-to-run variance (diagnostics 2026-11-11, item 2): label flip rates between repeated runs of the triple re-typing
step (retype-v2.5, Qwen3.5-9B) and of the catalogue judges (rubric v2), and agreement with the frozen outputs.

Runs (diag.sbatch): rep1, rep2, rep3 at temperature 0 (the scripts' own setting), t07 at temperature 0.7 (seed
20261111), all in one vLLM server session per model. Samples: retype = the script's own --sample 500
(random.Random(20261110)); judges = 500 catalogue records, random.Random(20261111) (make_samples.py).
Units: retype = triple (final relation, specific_verified, direction); judges = every judged slot of a record (record
verdict, each classify field, each stated-value verdict, each label verdict).
Reads only; writes outputs/results/diagnostics_2026-11-11/run_variance/{SUMMARY.json, REPORT.md}.

    python src/scripts/diagnostics_v32/run_variance.py
Written with Claude Code (declare)."""
from __future__ import annotations

import glob
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/diagnostics_v32"))
from stats_util import kappa_with_ci, prop  # noqa: E402

D = ROOT / "outputs/results/diagnostics_2026-11-11/run_variance"
FROZEN_RT = ROOT / "outputs/results/triple_retype_v2_2026-11-10/all_v25"
FROZEN_J = ROOT / "outputs/results/benchmark/judge_v2_2026-11-10/test"
RUNS = ["rep1", "rep2", "rep3", "t07"]
EXITS = {"ASSOCIATION_UNSIGNED", "NULL_FINDING", "NOT_SUPPORTED", "UNPARSED"}


def jl(paths):
    return [json.loads(l) for p in paths for l in open(p, encoding="utf-8") if l.strip()]


def pair_stats(a, b, keys):
    x, y = [a[k] for k in keys], [b[k] for k in keys]
    agree = sum(u == v for u, v in zip(x, y))
    return {"agreement": prop(agree, len(keys)), "flip": prop(len(keys) - agree, len(keys)), "kappa": kappa_with_ci(x, y, reps=1000)}


def compare_runs(runs, frozen, label):
    """runs: name -> {key: value}; frozen: {key: value}."""
    have = [r for r in RUNS if r in runs]
    keys = sorted(set(frozen).intersection(*[set(runs[r]) for r in have])) if have else []
    out = {"n_units": len(keys), "runs_present": have, "label": label}
    if not keys:
        return out
    t0 = [r for r in have if r.startswith("rep")]
    out["vs_frozen"] = {r: pair_stats(runs[r], frozen, keys) for r in have}
    out["between_t0_reps"] = {f"{a}-{b}": pair_stats(runs[a], runs[b], keys) for a, b in itertools.combinations(t0, 2)}
    if len(t0) >= 2:
        anyflip = sum(len({runs[r][k] for r in t0}) > 1 for k in keys)
        out["any_flip_across_t0_reps"] = prop(anyflip, len(keys))
        anyflip_f = sum(len({runs[r][k] for r in t0} | {frozen[k]}) > 1 for k in keys)
        out["any_flip_t0_reps_or_frozen"] = prop(anyflip_f, len(keys))
    if "t07" in have and t0:
        out["t07_vs_rep1"] = pair_stats(runs["t07"], runs[t0[0]], keys)
    out["distribution"] = {name: dict(Counter(v[k] for k in keys).most_common(8)) for name, v in [("frozen", frozen)] + [(r, runs[r]) for r in have]}
    return out


def retype():
    fro = {r["canonical_triple_id"]: r for r in jl(sorted(glob.glob(str(FROZEN_RT / "*.jsonl"))))}
    runs = {}
    for r in RUNS:
        p = D / "retype" / r / "triples_retyped_v2.jsonl"
        if p.exists():
            rows = {x["canonical_triple_id"]: x for x in jl([p])}
            runs[r] = rows
    if not runs:
        return None
    res = {"frozen": str(FROZEN_RT.relative_to(ROOT)), "n_per_run": {r: len(v) for r, v in runs.items()},
           "unparsed_per_run": {r: sum(x["relation"] == "UNPARSED" for x in v.values()) for r, v in runs.items()}}
    f = {
        "relation": lambda x: x["relation"],
        "specific_verified": lambda x: bool(x["specific_verified"]),
        "relation_and_direction": lambda x: (x["relation"], x["direction"]),
        "coarse_outcome": lambda x: "SPECIFIC" if x["specific_verified"] else x["relation"] if x["relation"] in EXITS else "SPECIFIC_UNVERIFIED",
    }
    for name, fn in f.items():
        res[name] = compare_runs({r: {k: fn(x) for k, x in v.items()} for r, v in runs.items()},
                                 {k: fn(x) for k, x in fro.items()}, name)
    keys = res["relation"].get("n_units")
    res["specific_verified_rate"] = {name: prop(sum(bool(x["specific_verified"]) for k, x in src.items() if k in runs.get("rep1", src)), len(runs.get("rep1", src)))
                                     for name, src in [("frozen", {k: fro[k] for k in runs.get("rep1", {}) if k in fro})] + list(runs.items())}
    return res


def judge_slots(row):
    s = {("record",): row.get("record")}
    for f, v in (row.get("classify") or {}).items():
        s[("classify", f)] = v
    for f, v in (row.get("stated") or {}).items():
        s[("stated", f)] = v.get("v") if isinstance(v, dict) else v
    for f, v in (row.get("label") or {}).items():
        s[("label", f)] = v
    return s


def judges():
    sample = json.load(open(D / "judge_sample.json"))
    keep = {tuple(x) for x in sample["records"]}
    out = {"sample": {k: sample[k] for k in ("seed", "n", "population")}}
    for m in ("qwen9", "llama", "mistral"):
        fro = {}
        for row in jl(sorted(glob.glob(str(FROZEN_J / f"{m}.shard*.jsonl")))):
            k = (row["table"], row["record_id"])
            if k in keep and "error" not in row:
                fro[k] = row
        runs = {}
        for r in RUNS:
            p = D / "judge" / r / "all" / f"{m}.shard0.jsonl"
            if p.exists():
                runs[r] = {(x["table"], x["record_id"]): x for x in jl([p]) if "error" not in x}
        if not runs:
            continue
        def flat(rows):
            return {(k, *s): v for k, row in rows.items() for s, v in judge_slots(row).items()}
        F = flat(fro)
        R = {r: flat(v) for r, v in runs.items()}
        mres = {"n_records": {r: len(v) for r, v in runs.items()}, "errors": {}, "all_slots": compare_runs(R, F, "all slots")}
        for r in RUNS:
            p = D / "judge" / r / "all" / f"{m}.shard0.jsonl"
            if p.exists():
                mres["errors"][r] = sum("error" in x for x in jl([p]))
        for part in ("record", "classify", "stated", "label"):
            sel = lambda d: {k: v for k, v in d.items() if k[2] == part}
            mres[part] = compare_runs({r: sel(v) for r, v in R.items()}, sel(F), part)
        # aggregate rate stability: share SUPPORTED among stated slots, share PASS among records
        rate = {}
        for name, d in [("frozen", F)] + list(R.items()):
            st = [v for k, v in d.items() if k[2] == "stated"]
            rc = [v for k, v in d.items() if k[2] == "record"]
            rate[name] = {"stated_SUPPORTED": prop(sum(v == "SUPPORTED" for v in st), len(st)),
                          "record_PASS": prop(sum(v == "PASS" for v in rc), len(rc))}
        mres["aggregate_rates"] = rate
        out[m] = mres
    return out


def main():
    s = {"date": "2026-11-11", "method": __doc__.split("\n\n")[1].strip(), "retype": retype(), "judges": judges(),
         "status": "diagnostic; model outputs, not accuracy; PENDING lead approval"}
    (D / "SUMMARY.json").write_text(json.dumps(s, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(s, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
