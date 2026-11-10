"""Component I correction — recompute the public NER benchmark from the 54 shipped prediction files.

Imports the benchmark protocol itself (src/scripts/ner_fair_bench/fairbench.py) so that the matching
rules are not re-implemented. Adds one metric the shipped run does not compute: a supported-schema F1
(micro over only the types a configuration can actually emit), which separates schema coverage from
span-finding skill.

Read-only. Writes NER_RECOMPUTATION_CHECK.csv and ner_recompute_summary.json beside the audit.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]          # paper/publication/component_quality_audit
ROOT = next(p for p in AUDIT.parents if (p / ".cdm_root").is_file())
BENCH = ROOT / "outputs/results/benchmark/ner_fair_bench"

sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))
import fairbench as fb  # noqa: E402

fb.PRED = BENCH / "preds"
fb.OUT = BENCH
fb.RAW = ROOT / "data/benchmarks_ner/raw"

TOL = 1e-12
rows_out = []
summary = {"datasets": {}, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
reported = json.loads((BENCH / "fair_ner_metrics.json").read_text())


def add(ds, model, metric, rep, rec, note=""):
    if rec is None:
        rows_out.append([ds, model, metric, "" if rep is None else rep, "", "", "N/A", note])
        return
    rep_f = None if rep is None else float(rep)
    ok = rep_f is not None and abs(rep_f - rec) <= TOL
    rows_out.append([ds, model, metric,
                     "" if rep_f is None else f"{rep_f:.15g}",
                     f"{rec:.15g}",
                     "" if rep_f is None else f"{abs(rep_f - rec):.3g}",
                     "MATCH" if ok else ("MISSING_IN_JSON" if rep_f is None else "MISMATCH"),
                     note])


for ds in ("bc5cdr", "biored"):
    t_ds = time.time()
    docs = fb.load(ds)
    span_docs = [(p, t, [(s, e, "SPAN", m) for s, e, _, m in g]) for p, t, g in docs]
    types = fb.TYPES[ds]
    rec_rows, names = {}, []
    for path in sorted(fb.PRED.glob(f"{ds}__*.jsonl")):
        name = path.stem.split("__", 1)[1]
        names.append(name)
        meta, raw = fb.read_preds(path)
        raw = [(p, raw.get(p, [])) for p, _, _ in docs]
        pred = fb.project(raw, name, ds)
        sup = fb.supported(name, ds)
        full = fb.micro(docs, pred, types, per_doc=True)
        spans = [(p, sorted({(int(x["start"]), int(x["end"]), "SPAN") for x in ps
                             if name == "scispacy_lg" or fb.project([(p, [x])], name, ds)[0][1]}))
                 for p, ps in raw]
        rec = {
            "full": fb.agg(full, types),
            "full_ci": fb.boot(full, types),
            "span_only": fb.micro(span_docs, spans, ["SPAN"]),
            "per_type": {t: fb.agg(full, [t]) for t in sup},
            "per_type_ci": {t: fb.boot(full, [t], n=1000) for t in sup},
            "supported": sup,
        }
        # audit-only metric: every emitted span, regardless of whether its label maps into the schema
        spans_all = [(p, sorted({(int(x["start"]), int(x["end"]), "SPAN") for x in ps})) for p, ps in raw]
        rec["span_all"] = fb.micro(span_docs, spans_all, ["SPAN"])
        common = [t for t in types if "Chemical" in t or "Disease" in t]
        rec["chem_dis"] = (fb.agg(full, common) if all(t in sup for t in common) else None) if common else None
        rec["supported_schema"] = fb.agg(full, sup) if sup else None
        rec["supported_schema_ci"] = fb.boot(full, sup) if sup else None
        rec["rows"] = full
        rec_rows[name] = rec

    # best-on-dataset, recomputed exactly as score() does (typed models only)
    typed = [n for n in names if n != "scispacy_lg"]
    best = max(typed, key=lambda n: rec_rows[n]["full"]["exact"]["F1"]) if typed else None

    for name in names:
        r = reported[f"{ds}__{name}"]
        c = rec_rows[name]
        fe, fr = c["full"]["exact"], c["full"]["relaxed"]
        re_, rr = r["full_schema"]["exact"], r["full_schema"]["relaxed"]
        for k, rep, rec in (("exact_F1", re_["F1"], fe["F1"]), ("exact_P", re_["P"], fe["P"]),
                            ("exact_R", re_["R"], fe["R"]), ("relaxed_F1", rr["F1"], fr["F1"]),
                            ("exact_tp", re_["tp"], fe["tp"]), ("exact_fp", re_["fp"], fe["fp"]),
                            ("exact_fn", re_["fn"], fe["fn"])):
            add(ds, name, f"full_schema_{k}", rep, float(rec))
        add(ds, name, "full_schema_ci_low", r["full_schema_ci"][0], c["full_ci"][0])
        add(ds, name, "full_schema_ci_high", r["full_schema_ci"][1], c["full_ci"][1])
        add(ds, name, "span_only_exact_F1", r["span_only"]["exact"]["F1"], c["span_only"]["exact"]["F1"])
        add(ds, name, "span_only_relaxed_F1", r["span_only"]["relaxed"]["F1"], c["span_only"]["relaxed"]["F1"])
        rows_out.append([ds, name, "span_all_exact_F1", "", f"{c['span_all']['exact']['F1']:.15g}", "",
                         "NEW", "type-agnostic F1 over EVERY emitted span, including labels outside the "
                                "dataset schema (the shipped span_only keeps only spans whose label maps)"])
        if "chem_dis" in r:
            add(ds, name, "chem_dis_exact_F1", r["chem_dis"]["exact"]["F1"], c["chem_dis"]["exact"]["F1"])
        else:
            add(ds, name, "chem_dis_exact_F1", None, None, "model cannot emit all Chemical/Disease types")
        for t in types:
            rep = r["per_type"].get(t)
            rec_t = c["per_type"].get(t)
            if rep is None and rec_t is None:
                add(ds, name, f"per_type_F1[{t}]", None, None, "unsupported type -> N/A")
            elif rep is None:
                add(ds, name, f"per_type_F1[{t}]", None, rec_t["exact"]["F1"], "computable but absent from JSON")
            else:
                add(ds, name, f"per_type_F1[{t}]", rep["exact"]["F1"], rec_t["exact"]["F1"])
                add(ds, name, f"per_type_ci_low[{t}]", rep["ci"][0], c["per_type_ci"][t][0])
                add(ds, name, f"per_type_ci_high[{t}]", rep["ci"][1], c["per_type_ci"][t][1])
        add(ds, name, "best_on_dataset", 1 if r.get("best_on_dataset") == best else 0,
            1 if best == r.get("best_on_dataset") else 0)
        # new metric, not present in the shipped JSON
        ss = c["supported_schema"]
        rows_out.append([ds, name, "supported_schema_exact_F1", "", "" if ss is None else f"{ss['exact']['F1']:.15g}",
                         "", "NEW" if ss is not None else "N/A",
                         f"micro over {len(c['supported'])} supported type(s): {','.join(c['supported']) or 'none'}"])
        if ss is not None:
            rows_out.append([ds, name, "supported_schema_ci", "",
                             f"[{c['supported_schema_ci'][0]:.6f},{c['supported_schema_ci'][1]:.6f}]", "",
                             "NEW", "2000-resample document bootstrap, seed 0"])

    summary["datasets"][ds] = {
        "docs": len(docs),
        "gold_entities": sum(len(g) for _, _, g in docs),
        "gold_by_type": {t: sum(1 for _, _, g in docs for _, _, ty, _ in g if ty == t) for t in types},
        "models": len(names),
        "best_on_dataset_recomputed": best,
        "seconds": round(time.time() - t_ds, 1),
    }

out_csv = AUDIT / "NER_RECOMPUTATION_CHECK.csv"
out_csv.parent.mkdir(parents=True, exist_ok=True)
with open(out_csv, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["dataset", "model", "metric", "reported", "recomputed", "abs_diff", "verdict", "note"])
    w.writerows(rows_out)

counts = {}
for r in rows_out:
    counts[r[6]] = counts.get(r[6], 0) + 1
summary["verdict_counts"] = counts
summary["rows"] = len(rows_out)
summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")

# per-model supported-schema table for the matrix / corrections doc
best_supported = {}
for ds in ("bc5cdr", "biored"):
    d = {}
    for r in rows_out:
        if r[0] == ds and r[2] == "supported_schema_exact_F1" and r[4]:
            d[r[1]] = float(r[4])
    best_supported[ds] = dict(sorted(d.items(), key=lambda kv: -kv[1]))
summary["supported_schema_exact_F1"] = best_supported

(AUDIT / "diagnostics/results/ner_recompute_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
print(json.dumps({k: summary[k] for k in ("verdict_counts", "rows", "datasets")}, indent=1))
print("csv rows:", len(rows_out))
