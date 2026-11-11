"""Evaluation of the 3.2.0-candidate catalogue fields with the UNCHANGED catalogue judge rubric v2
(evidence_judge_v2.SYSTEM, build(), schema, temperature 0, same three local judges). Protocol fixed before running:

Records: assay records of the rubric-v2 TEST split (evidence_judge_v2.split_of) with a non-missing old OR new value
for dna_extraction_method or sequencing_platform. NOT_REPORTED / CITED_PROTOCOL are codes and are not judged (as in v2).
Three conditions, each one request per record, PART B = assay_type + the field(s) present:
  OLD     old 3.0.3 values, the original v2 inputs (record passage +-500 chars, original per-field gap quotes);
  OLDCTX  old values, but the field quotes for the two fields are the NEW evidence windows (where the new layer has one)
          -- shows whether old values are supported by the text where the method is actually stated;
  NEW     3.2.0-candidate values with their evidence windows as the field quotes (+-context around each evidence span,
          <= ~900 chars per field), record passage unchanged.
The only difference from the original v2 run is that PART B lists assay_type + these two fields instead of all assay
fields; OLD re-measures the old values under this reduced prompt, so OLD vs NEW is like-for-like.
Verdicts: judge_v2_analysis.stated_verdict (verified view: SUPPORTED needs a verified span). Majority reject = >= 2 of 3
judges FAIL (NOT_SUPPORTED / CONTRADICTED / WRONG_FIELD). Wilson 95% CIs; exact McNemar on paired records.

    python judge_fields.py inputs                      # CPU: write judge_inputs.jsonl
    python judge_fields.py judge --model qwen9 --host http://127.0.0.1:PORT --out DIR
    python judge_fields.py analyze --judge-dir DIR
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_judge_v2 as E  # noqa: E402
import gazetteer as G  # noqa: E402

OUT = G.OUT
FIELDS = ("dna_extraction_method", "sequencing_platform")
CODES = ("", "NOT_REPORTED", "CITED_PROTOCOL", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING", None)
QCAP = 900


def wilson(k, n, z=1.959964):
    if not n:
        return {"k": k, "n": n, "p": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": k, "n": n, "p": round(p, 4), "lo": round(c - h, 4), "hi": round(c + h, 4)}


def mcnemar(b, c):
    n = b + c
    if not n:
        return None
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return round(min(1.0, 2 * p), 6)


def quote(sec, keys):
    parts = []
    for k in keys:
        e = k["evidence"][0]
        txt = sec[e["section_id"]]
        ctx = max(80, (QCAP // max(1, len(keys)) - (e["end"] - e["start"])) // 2)
        parts.append(txt[max(0, e["start"] - ctx):e["end"] + ctx])
    return " ... ".join(parts)


def inputs():
    import sqlite3
    c = sqlite3.connect(f"file:{E.V1.CDM}?mode=ro", uri=True)
    secs = defaultdict(dict)
    for pid, sid, t in c.execute("SELECT paper_id, section_id_original, section_text_original FROM section"):
        secs[pid][sid] = t or ""
    new = {o["assay_id"]: o for o in map(json.loads, open(OUT / "records_v32.jsonl", encoding="utf-8"))}
    old = {r["record_id"]: r for r in E.V1.records() if r["table"] == "assay"}
    n = Counter()
    with open(OUT / "judge_inputs.jsonl", "w", encoding="utf-8") as fh:
        for rid, r in old.items():
            if E.split_of(rid) != "test":
                continue
            nr = new.get(rid, {})
            ov = {f: r["values"][f] for f in FIELDS if f in r["values"] and r["values"][f] not in CODES}
            nv = {f: nr[f] for f in FIELDS if nr.get(f) not in CODES}
            if not ov and not nv:
                continue
            nq = {f: quote(secs[r["paper_id"]], nr[f + "_keys"]) for f in FIELDS if nr.get(f + "_keys") and nr.get(f) not in CODES}
            base = {k: r[k] for k in ("table", "record_id", "paper_id", "passage")}
            at = {"assay_type": r["values"]["assay_type"]} if "assay_type" in r["values"] else {}
            conds = []
            if ov:
                conds.append(("OLD", {**at, **ov}, {f: q for f, q in r["field_quotes"].items() if f in ov}))
                conds.append(("OLDCTX", {**at, **ov}, {f: nq.get(f, r["field_quotes"].get(f)) for f in ov
                                                        if nq.get(f) or r["field_quotes"].get(f)}))
            if nv:
                conds.append(("NEW", {**at, **nv}, {f: nq[f] for f in nv if f in nq}))
            for cond, vals, fq in conds:
                fh.write(json.dumps({**base, "condition": cond, "values": vals, "field_quotes": fq, "missing_codes": {}},
                                    ensure_ascii=False) + "\n")
                n[cond] += 1
    print(dict(n))


def judge(a):
    recs = [json.loads(l) for l in open(OUT / "judge_inputs.jsonl", encoding="utf-8")]
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{a.model}.jsonl"
    done = set()
    if path.exists():
        done = {(j["condition"], j["record_id"]) for j in map(json.loads, open(path, encoding="utf-8")) if "error" not in j}
    todo = [r for r in recs if (r["condition"], r["record_id"]) not in done]
    print(f"{a.model}: {len(recs)} requests, {len(todo)} to do; rubric prompt {E.PROMPT_SHA256[:12]}", flush=True)

    def ask(rec):
        user, schema, cls, stated = E.build(rec)
        msgs = [{"role": "system", "content": E.SYSTEM}, {"role": "user", "content": user}]
        if a.model in E.NO_SYSTEM_ROLE:
            msgs = [{"role": "user", "content": E.SYSTEM + "\n\n" + user}]
        body = {"model": E.MODELS[a.model], "messages": msgs, "temperature": 0, "seed": 0, "max_tokens": 3000,
                "response_format": {"type": "json_schema", "json_schema": {"name": "v2", "schema": schema, "strict": True}}}
        if a.model in E.THINKING_OFF:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        err = None
        for _ in range(3):
            try:
                req = urllib.request.Request(a.host.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=900).read())
                j = json.loads(r["choices"][0]["message"].get("content") or "{}", strict=False)
                return {"condition": rec["condition"], "record_id": rec["record_id"], "paper_id": rec["paper_id"],
                        "record": j.get("record"), "stated": j.get("stated", {}), "finish": r["choices"][0].get("finish_reason"),
                        "model": E.MODELS[a.model], "prompt_sha256": E.PROMPT_SHA256}
            except Exception as ex:  # noqa: BLE001
                err = repr(ex)[:200]
        return {"condition": rec["condition"], "record_id": rec["record_id"], "error": err}

    t0 = time.time()
    with open(path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(a.parallel) as pool:
        for i, res in enumerate(pool.map(ask, todo)):
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            if i % 500 == 0:
                fh.flush()
                print(f"  {i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), flush=True)


def analyze(a):
    import judge_v2_analysis as A
    recs = {(r["condition"], r["record_id"]): r for r in map(json.loads, open(OUT / "judge_inputs.jsonl", encoding="utf-8"))}
    J = {}
    for m in E.MODELS:
        p = Path(a.judge_dir) / f"{m}.jsonl"
        if p.exists():
            J[m] = {(j["condition"], j["record_id"]): j for j in map(json.loads, open(p, encoding="utf-8")) if "error" not in j}
    ms = sorted(J)
    verd = defaultdict(dict)        # (cond, rid, field) -> {m: verdict}
    for m, out in J.items():
        for k, j in out.items():
            rec = recs[k]
            src = A.norm(rec["passage"] + " " + " ".join(rec["field_quotes"].values()))
            for f in FIELDS:
                it = (j.get("stated") or {}).get(f)
                if f in rec["values"] and it:
                    _, v = A.stated_verdict(it, rec["values"][f], src)
                    if v:
                        verd[(k[0], k[1], f)][m] = v
    maj = {}
    for k, d in verd.items():
        if all(m in d for m in ms):
            cnt = Counter(d.values())
            maj[k] = "FAIL" if cnt["FAIL"] >= 2 else ("PASS" if cnt["PASS"] >= 2 else ("UNC" if cnt["UNC"] >= 2 else "NO_MAJORITY"))
    new = {o["assay_id"]: o for o in map(json.loads, open(OUT / "records_v32.jsonl", encoding="utf-8"))}
    res = {"judges": ms, "rubric_prompt_sha256": E.PROMPT_SHA256, "requests": {m: len(J[m]) for m in ms},
           "errors_or_missing": {m: sum(1 for k in recs if k not in J[m]) for m in ms}, "by_field": {}}
    for f in FIELDS:
        blk = {}
        for cond in ("OLD", "OLDCTX", "NEW"):
            ks = [k for k in maj if k[0] == cond and k[2] == f]
            c = Counter(maj[k] for k in ks)
            blk[cond] = {"n_judged_all3": len(ks), "majority": dict(c), "majority_reject": wilson(c["FAIL"], len(ks)),
                         "majority_pass": wilson(c["PASS"], len(ks))}
        # coverage / abstention on records that had an old value
        old_ids = {k[1] for k in maj if k[0] == "OLD" and k[2] == f}
        st = Counter(new.get(r, {}).get(f, "NOT_IN_LAYER") if new.get(r, {}).get(f) in CODES or r not in new else "VALUE" for r in old_ids)
        blk["old_valued_records_new_status"] = dict(st)
        # paired: records judged under OLD and NEW
        pair = [r for r in old_ids if ("NEW", r, f) in maj]
        b = sum(maj[("OLD", r, f)] == "FAIL" and maj[("NEW", r, f)] != "FAIL" for r in pair)
        cc = sum(maj[("OLD", r, f)] != "FAIL" and maj[("NEW", r, f)] == "FAIL" for r in pair)
        blk["paired_old_vs_new"] = {"n": len(pair), "old_reject": wilson(sum(maj[("OLD", r, f)] == "FAIL" for r in pair), len(pair)),
                                    "new_reject": wilson(sum(maj[("NEW", r, f)] == "FAIL" for r in pair), len(pair)),
                                    "old_reject_new_not": b, "old_not_new_reject": cc, "mcnemar_exact_p": mcnemar(b, cc)}
        # strict view on old-valued records: new value accepted (majority PASS) vs rejected-or-abstained
        acc_new = sum(1 for r in old_ids if maj.get(("NEW", r, f)) == "PASS")
        acc_old = sum(1 for r in old_ids if maj.get(("OLD", r, f)) == "PASS")
        blk["old_valued_records_majority_pass"] = {"old": wilson(acc_old, len(old_ids)), "new": wilson(acc_new, len(old_ids))}
        # by confidence / source (NEW)
        for g in ("field_confidence", "field_source"):
            d = defaultdict(Counter)
            for k in maj:
                if k[0] == "NEW" and k[2] == f:
                    d[new[k[1]].get(f"{f}_{g}")][maj[k]] += 1
            blk[f"NEW_by_{g}"] = {x: {"n": sum(v.values()), "majority_reject": wilson(v["FAIL"], sum(v.values()))} for x, v in d.items()}
        res["by_field"][f] = blk
    out = Path(a.judge_dir) / "ANALYSIS.json"
    for p in (out, OUT / "judge_ANALYSIS.json"):
        p.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1)[:8000])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inputs", "judge", "analyze"])
    ap.add_argument("--model", choices=sorted(E.MODELS), default="qwen9")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--out", type=Path, default=OUT / "judge")
    ap.add_argument("--judge-dir", default=str(OUT / "judge"))
    ap.add_argument("--parallel", type=int, default=48)
    a = ap.parse_args(argv)
    return {"inputs": lambda: inputs(), "judge": lambda: judge(a), "analyze": lambda: analyze(a)}[a.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
