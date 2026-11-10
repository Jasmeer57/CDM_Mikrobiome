"""[Constrained variant, 2026-11-09: exact code of the --constrained re-run; the frozen evidence_judge.py is
unchanged (FINAL_VALIDATION_MANIFEST.sha256). Writes only to a new --out folder.]

Model-based evidence assessment of every catalogue record (CDM 3.0.3), plus deterministic value checks.

For each record the judge sees ONLY: the source passage around the record's located quote (or the stored quote
when it could not be located), the separate quote of each gap-filled field, the field names with their
extraction rule, and the values. It never sees earlier model verdicts, confidence scores or pipeline flags.
Missing-data codes are not judged (a passage cannot show absence); they are covered by deterministic checks.

Verdicts per field: PASS (the passage states this value for this record), FAIL_NOT_SUPPORTED, FAIL_WRONG_FIELD,
FAIL_CONTRADICTED, UNCERTAIN; per record: PASS / FAIL / UNCERTAIN that it is a genuine record of its type
reported as the paper's own work. These are MODEL JUDGEMENTS, not accuracy.

    python evidence_judge.py judge --model llama --host http://127.0.0.1:8000 --shard 0 --nshards 3
    python evidence_judge.py deterministic
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/human_validation"))
sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))
from make_gate4_package import TABLES, MISSING, loads  # noqa: E402  (same field lists as the audit sample)
from fairbench import LLMS, NO_SYSTEM_ROLE  # noqa: E402

CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "paper/publication/final_validation/evidence_judge"
CTX = 500
LINKS = ("cohort_id", "assay_id", "dataset_id")
RULE = {"participant_count": "integer number of participants stated in the passage",
        "sample_count": "integer number of samples stated in the passage",
        "file_size_bytes": "integer file size stated in the passage",
        "direction": "INCREASE | DECREASE | NO_ASSOCIATION | MIXED | NOT_STATED; must be stated explicitly",
        "cohort_role": "cases_and_controls | single_group", "longitudinal": "YES | NO | UNCLEAR | NOT_APPLICABLE",
        "dataset_role": "primary_study_data | linked_data",
        "data_availability_status": "PUBLIC | CONTROLLED | EMBARGOED | UPON_REQUEST | NOT_DEPOSITED | LINK_ONLY | UNKNOWN",
        "access_status": "PUBLIC | CONTROLLED | EMBARGOED | UPON_REQUEST | NOT_DEPOSITED | LINK_ONLY | UNKNOWN",
        "original_or_reused": "ORIGINAL | REUSED | UNKNOWN"}
ENTITY = {"claim": "finding (a result reported by THIS study)", "assay": "assay / measurement method",
          "sample": "sample group (a set of biological samples)", "cohort": "cohort (a group of study participants or animals)",
          "dataset": "dataset (data generated or reused by the study)", "data_asset": "data asset (a file or deposited data object)"}
SYSTEM = """You check structured records extracted from scientific papers against the source text.
For each field decide, using ONLY the text given:
- PASS: the text explicitly states this value for this record and field.
- FAIL_NOT_SUPPORTED: the text does not state this value (it may be plausible, but it is not stated).
- FAIL_WRONG_FIELD: the value is in the text but belongs to a different field or a different record.
- FAIL_CONTRADICTED: the text states a different value.
- UNCERTAIN: you cannot decide from the text.
Also decide whether the record as a whole is a genuine record of the stated type reported as THIS paper's own work
(PASS), not one (FAIL: cited prior work, methods boilerplate, table/figure fragment, reagent, wrong type), or UNCERTAIN.
Do not use outside knowledge to fill gaps. Return ONLY JSON:
{"record": "PASS|FAIL|UNCERTAIN", "fields": {"<field>": "PASS|FAIL_NOT_SUPPORTED|FAIL_WRONG_FIELD|FAIL_CONTRADICTED|UNCERTAIN"}}"""


def records():
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    sec = {(r["paper_id"], r["section_id_original"]): r["section_text_original"]
           for r in c.execute("SELECT paper_id, section_id_original, section_text_original FROM section")}
    label = {}
    for t, (_, idc, lab, _) in TABLES.items():
        w = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
        for r in c.execute(f'SELECT "{idc}", "{lab}" FROM "{t}"{w}'):
            label[r[0]] = (r[1] or "")[:100]
    out = []
    for t, (ent, idc, lab, fields) in TABLES.items():
        w = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
        cols = set(r[1] for r in c.execute(f'PRAGMA table_info("{t}")'))
        for r in c.execute(f'SELECT * FROM "{t}"{w} ORDER BY rowid'):
            r = dict(r)
            txt = sec.get((r["paper_id"], r.get("section_id")))
            a, b = r.get("evidence_span_start"), r.get("evidence_span_end")
            if txt and a is not None:
                passage = txt[max(0, a - CTX):b + CTX]
            else:
                passage = "QUOTE ONLY (not located in the paper): " + str(r.get("evidence_text") or "")
            ge = loads(r.get("gap_evidence")) if "gap_evidence" in cols else {}
            ge = ge if isinstance(ge, dict) else {}
            fq = {}
            vals = {}
            for f in fields:
                v = r.get(f)
                if v in (None, "", "[]", "{}") or v in MISSING:
                    continue
                if f in LINKS:
                    v = "; ".join(f"{x.strip()} = {label.get(x.strip(), '?')}" for x in str(v).split(";"))
                vals[f] = str(v)[:400]
                e = ge.get(f)
                if isinstance(e, dict) and e.get("quote"):
                    t2 = sec.get((r["paper_id"], e.get("section_id")))
                    s0, s1 = e.get("char_start"), e.get("char_end")
                    fq[f] = (t2[max(0, s0 - 200):s1 + 200] if t2 and s0 is not None else e["quote"])[:900]
            fs = loads(r.get("field_sources")) or {}
            out.append({"table": t, "record_id": r[idc], "paper_id": r["paper_id"], "anchor": r.get("evidence_anchor_status"),
                        "passage": passage[:2400], "field_quotes": fq, "values": vals,
                        "gap_filled": sorted(k for k, s in (fs.items() if isinstance(fs, dict) else []) if str(s).startswith(("G1", "G3"))),
                        "missing_codes": {f: r.get(f) for f in fields if r.get(f) in MISSING}})
    return out


def prompt(rec):
    lines = [f"RECORD TYPE: {ENTITY[rec['table']]}", "", "SOURCE PASSAGE:", rec["passage"], ""]
    for f, q in rec["field_quotes"].items():
        lines += [f"ADDITIONAL SOURCE TEXT for field {f}:", q, ""]
    lines.append("FIELDS TO CHECK:")
    for f, v in rec["values"].items():
        rule = f" (rule: {RULE[f]})" if f in RULE else (" (the record is linked to these records)" if f in LINKS else "")
        lines.append(f"- {f}{rule}: {v}")
    return "\n".join(lines)


FIELD_VERDICTS = ["PASS", "FAIL_NOT_SUPPORTED", "FAIL_WRONG_FIELD", "FAIL_CONTRADICTED", "UNCERTAIN"]


def judge(a):
    global OUT
    if a.out:
        OUT = a.out
    if OUT == ROOT / "paper/publication/final_validation/evidence_judge" and a.constrained:
        raise SystemExit("constrained re-run must write to a new --out folder, not the frozen evidence_judge/")
    model = LLMS[a.model][0]
    recs = [r for i, r in enumerate(records()) if i % a.nshards == a.shard and r["values"]]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{a.model}.shard{a.shard}.jsonl"
    done = set()
    if path.exists():
        done = {(j["table"], j["record_id"]) for j in map(json.loads, open(path))}
    todo = [r for r in recs if (r["table"], r["record_id"]) not in done]
    print(f"{a.model} shard {a.shard}: {len(recs)} records, {len(todo)} to do", flush=True)

    def ask(rec):
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(rec)}]
        if a.model in NO_SYSTEM_ROLE:
            msgs = [{"role": "user", "content": SYSTEM + "\n\n" + prompt(rec)}]
        body = {"model": model, "messages": msgs, "temperature": 0, "seed": 0, "max_tokens": 900,
                "response_format": {"type": "json_object"}}
        if a.constrained:                                   # 2026-11-09: verdict tokens enforced by the server
            schema = {"type": "object", "additionalProperties": False, "required": ["record", "fields"],
                      "properties": {"record": {"type": "string", "enum": ["PASS", "FAIL", "UNCERTAIN"]},
                                     "fields": {"type": "object", "additionalProperties": False,
                                                "required": list(rec["values"]),
                                                "properties": {f: {"type": "string", "enum": FIELD_VERDICTS}
                                                               for f in rec["values"]}}}}
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "verdicts", "schema": schema, "strict": True}}
        err = None
        for _ in range(3):
            try:
                req = urllib.request.Request(a.host.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=900).read())
                txt = r["choices"][0]["message"].get("content") or ""
                m = re.search(r"\{.*\}", txt, re.S)
                j = json.loads(m.group(0)) if m else {}
                return {"table": rec["table"], "record_id": rec["record_id"], "record": j.get("record"),
                        "fields": {f: (j.get("fields") or {}).get(f) for f in rec["values"]},
                        "finish": r["choices"][0].get("finish_reason")}
            except Exception as ex:  # noqa: BLE001
                err = repr(ex)[:200]
        return {"table": rec["table"], "record_id": rec["record_id"], "error": err}

    t0 = time.time()
    with open(path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(a.parallel) as pool:
        for i, res in enumerate(pool.map(ask, todo)):
            fh.write(json.dumps(res) + "\n")
            if i % 1000 == 0:
                fh.flush()
                print(f"  {i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    print("done", time.time() - t0)


NUM = re.compile(r"\d[\d,]*")


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def deterministic(a):
    """Value-in-evidence checks for every populated field (no model)."""
    from collections import Counter, defaultdict
    res = defaultdict(Counter)
    rows = []
    for rec in records():
        ev = norm(rec["passage"])
        for f, v in rec["values"].items():
            if f in LINKS:
                continue
            evf = norm(rec["field_quotes"].get(f, "")) + " " + ev
            nv = norm(v)
            if f in ("participant_count", "sample_count", "file_size_bytes"):
                nums = {n.replace(",", "") for n in NUM.findall(evf.replace(" ", ""))} | set(re.findall(r"\d+", evf))
                ok = str(v).replace(",", "").strip() in nums
                kind = "count_in_evidence"
            elif f in RULE:
                ok, kind = None, "coded_value"
            else:
                toks = [t for t in nv.split() if len(t) > 2]
                share = sum(t in evf.split() for t in toks) / len(toks) if toks else 0
                ok = nv in evf or share >= 0.8
                kind = "text_in_evidence"
            k = "UNASSESSED" if ok is None else ("FOUND" if ok else "NOT_FOUND")
            res[(rec["table"], kind)][k] += 1
            rows.append({"table": rec["table"], "record_id": rec["record_id"], "field": f, "check": kind, "result": k,
                         "anchor": rec["anchor"], "gap_filled": f in rec["gap_filled"], "has_field_quote": f in rec["field_quotes"]})
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "deterministic_value_checks.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    s = {f"{t}|{k}": dict(v) for (t, k), v in sorted(res.items())}
    (OUT / "deterministic_summary.json").write_text(json.dumps(s, indent=1) + "\n")
    print(json.dumps(s, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["judge", "deterministic"])
    ap.add_argument("--model", default="llama")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--constrained", action="store_true", help="enforce verdict tokens with a JSON schema (2026-11-09)")
    ap.add_argument("--out", type=Path, default=None, help="output folder (required with --constrained)")
    ap.add_argument("--parallel", type=int, default=64)
    a = ap.parse_args(argv)
    return {"judge": judge, "deterministic": deterministic}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
