"""Evidence-grounded DeepSeek check of the CDM 3.0.3 triples (rules: evidence_schema.json, pre-registered).

For each triple with a CC BY / CC0 source sentence, DeepSeek is asked whether the sentence states the triple, for the
original relation and, where the cleaning changed it, for the cleaned relation. Resumable; answers in verdicts.jsonl.

    python evidence_check.py preregister
    python evidence_check.py judge         # API calls (login node: needs internet); resumable
    python evidence_check.py report
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import sqlite3
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/ner_llm_judge"))
import judge as J  # noqa: E402  (API client, config, JSON parsing)

SCHEMA = json.loads((HERE / "evidence_schema.json").read_text())
OUT = ROOT / "outputs/results/kg_2026-11-04/evidence_check"
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
CLEAN = ROOT / "outputs/results/cleaned_layer_deepseek/cleaned_triples.csv.gz"
BATCH = SCHEMA["judge"]["batch"]
SYSTEM_T = "You check relation triples against the sentence they were extracted from. Answer only in the requested JSON."
TASK = """Each item is [n, "sentence", "subject", "relation A", "object", B], where B is null or ["subject", "relation B", "object"].
Use ONLY the sentence. For each item answer [n, R, A, B, D]:
R: "Y" if the sentence states any relationship between subject and object, else "N".
A: for relation A as written (subject -> relation -> object): "Y" supported; "P" the entities are related in the sentence but the label is too generic or only partly right; "R" supported only with subject and object reversed; "N" not supported.
B: the same codes for B, or "-" if B is null.
D: "F" the sentence asserts it, "H" hedged or speculative, "G" negated (the sentence reports no association or no difference).
Return {"r": [[n, R, A, B, D], ...]} with exactly one entry per item, in order."""


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def items():
    ok = {r["paper_id"] for r in csv.DictReader(open(RIGHTS, encoding="utf-8")) if r["proposed_release_decision"] == "INCLUDE_TEXT"}
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    sent = {}
    for tid, pid, s in c.execute("SELECT canonical_triple_id, paper_id, source_sentence FROM relation_evidence WHERE relation_table = "
                                 "'relation' AND source_sentence IS NOT NULL AND source_sentence != '' ORDER BY triple_mention_id"):
        if pid in ok and tid not in sent:
            sent[tid] = (pid, s[:700])
    with gzip.open(CLEAN, "rt", encoding="utf-8") as fh:
        cl = {r["canonical_triple_id"]: r for r in csv.DictReader(fh)}
    out = []
    for tid, su, rel, ob in c.execute("SELECT canonical_triple_id, subject_display_label, relation_normalized, object_display_label FROM relation"):
        if tid not in sent:
            continue
        r = cl.get(tid, {})
        kept = r.get("kept") == "1"
        b = None
        if kept and (r["relation_cleaned"] != rel or r["direction_swapped"] == "1"):
            b = [ob, r["relation_cleaned"], su] if r["direction_swapped"] == "1" else [su, r["relation_cleaned"], ob]
        out.append({"id": tid, "paper": sent[tid][0], "sentence": sent[tid][1], "s": su, "rel": rel, "o": ob, "b": b, "kept": kept})
    return out


def cmd_preregister():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "PREREGISTRATION.sha256").write_text(f"{sha256(HERE / 'evidence_schema.json')}  evidence_schema.json\n")
    print((OUT / "PREREGISTRATION.sha256").read_text())


def check_prereg():
    h, f = (OUT / "PREREGISTRATION.sha256").read_text().split()
    if sha256(HERE / f) != h:
        sys.exit("evidence_schema.json changed after pre-registration")


class Client(J.Client):
    def chat(self, user):
        body = {"model": self.api["model"], "temperature": self.api.get("temperature", 0), "max_tokens": self.api.get("max_tokens", 6000),
                "messages": [{"role": "system", "content": SYSTEM_T}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}}
        body.update(self.api.get("extra_body") or {})
        r = self.request("/chat/completions", body)
        return r["choices"][0]["message"].get("content") or ""


def cmd_judge():
    check_prereg()
    cfg = J.load_cfg(str(ROOT / "src/scripts/ner_llm_judge/config.yml"))
    its = items()
    path = OUT / "verdicts.jsonl"
    done = {json.loads(l)["id"] for l in open(path, encoding="utf-8")} if path.exists() else set()
    todo = [i for i in its if i["id"] not in done]
    random.Random(1).shuffle(todo)
    batches = [todo[k:k + BATCH] for k in range(0, len(todo), BATCH)]
    print(f"{len(its):,} items; {len(done):,} done; {len(batches)} requests", flush=True)
    cl, lock, st = Client(cfg["api"]), threading.Lock(), Counter()
    codes = {"R": {"Y", "N"}, "A": {"Y", "P", "R", "N"}, "B": {"Y", "P", "R", "N", "-"}, "D": {"F", "H", "G"}}

    def run(b):
        rows = [[n, i["sentence"], i["s"], i["rel"], i["o"], i["b"]] for n, i in enumerate(b)]
        try:
            got = {}
            for r in (J.parse(cl.chat(TASK + "\n\nItems:\n" + json.dumps(rows, ensure_ascii=False))) or {}).get("r", []):
                if (isinstance(r, list) and len(r) == 5 and isinstance(r[0], int) and 0 <= r[0] < len(b)
                        and r[1] in codes["R"] and r[2] in codes["A"] and r[3] in codes["B"] and r[4] in codes["D"]):
                    got[r[0]] = r[1:]
        except Exception as e:  # noqa: BLE001
            print("batch error:", str(e)[:200], flush=True)
            got = {}
        with lock, open(path, "a", encoding="utf-8") as fh:
            for n, i in enumerate(b):
                if n in got:
                    R, A, B, D = got[n]
                    fh.write(json.dumps({"id": i["id"], "R": R, "A": A, "B": B if i["b"] else "-", "D": D}) + "\n")
                    st["ok"] += 1
                else:
                    st["missing"] += 1
            if (st["ok"] + st["missing"]) % 2000 < BATCH:
                print(dict(st), flush=True)

    with ThreadPoolExecutor(int(cfg["api"].get("max_concurrency", 24))) as ex:
        for f in as_completed([ex.submit(run, b) for b in batches]):
            f.result()
    print("finished:", dict(st), "- re-run to retry missing", flush=True)


def wilson(k, n, z=1.959964):
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return [round(c - h, 4), round(c + h, 4)]


def rate(xs, ok):
    n, k = len(xs), sum(1 for x in xs if ok(x))
    return {"n": n, "k": k, "rate": round(k / n, 4) if n else None, "wilson": wilson(k, n)}


def boot(xs, ok, rng, reps):
    by = defaultdict(list)
    for x in xs:
        by[x["paper"]].append(ok(x))
    ps = list(by)
    vals = []
    for _ in range(reps):
        s = [v for p in (rng.choice(ps) for _ in ps) for v in by[p]]
        vals.append(sum(s) / len(s))
    vals.sort()
    return [round(vals[int(0.025 * reps)], 4), round(vals[int(0.975 * reps) - 1], 4)]


def newcombe(a, b):
    p1, p2 = a["rate"], b["rate"]
    (l1, u1), (l2, u2) = a["wilson"], b["wilson"]
    d = p1 - p2
    return [round(d - ((p1 - l1) ** 2 + (u2 - p2) ** 2) ** 0.5, 4), round(d + ((u1 - p1) ** 2 + (p2 - l2) ** 2) ** 0.5, 4)]


def cmd_report():
    check_prereg()
    its = {i["id"]: i for i in items()}
    v = {}
    for l in open(OUT / "verdicts.jsonl", encoding="utf-8"):
        r = json.loads(l)
        v[r["id"]] = r
    xs = [{**its[k], **r} for k, r in v.items() if k in its]
    rng = random.Random(SCHEMA["uncertainty"]["bootstrap"]["seed"])
    reps = SCHEMA["uncertainty"]["bootstrap"]["replicates"]
    relab = [x for x in xs if x["b"]]
    kept, dropped = [x for x in xs if x["kept"]], [x for x in xs if not x["kept"]]
    assoc = {"ASSOCIATED_WITH", "INCREASED_IN", "DECREASED_IN", "CAUSES", "INCREASES_RISK_OF", "CONTRIBUTES_TO", "MORE_ABUNDANT_THAN",
             "LESS_ABUNDANT_THAN", "PROMOTES", "EXACERBATES"}
    s = {"items": len(its), "judged": len(xs),
         "R_stated": rate(xs, lambda x: x["R"] == "Y"), "R_bootstrap": boot(xs, lambda x: x["R"] == "Y", rng, reps),
         "A_supported": rate(xs, lambda x: x["A"] == "Y"), "A_bootstrap": boot(xs, lambda x: x["A"] == "Y", rng, reps),
         "A_supported_or_partial": rate(xs, lambda x: x["A"] in ("Y", "P")),
         "A_reversed": rate(xs, lambda x: x["A"] == "R"),
         "A_codes": dict(Counter(x["A"] for x in xs)), "D_codes": dict(Counter(x["D"] for x in xs)),
         "relabelled": {"n": len(relab), "A_supported": rate(relab, lambda x: x["A"] == "Y"), "B_supported": rate(relab, lambda x: x["B"] == "Y"),
                        "B_better": sum(1 for x in relab if x["B"] == "Y" and x["A"] != "Y"),
                        "A_better": sum(1 for x in relab if x["A"] == "Y" and x["B"] != "Y")},
         "kept": rate(kept, lambda x: x["A"] == "Y"), "dropped": rate(dropped, lambda x: x["A"] == "Y"),
         "kept_R": rate(kept, lambda x: x["R"] == "Y"), "dropped_R": rate(dropped, lambda x: x["R"] == "Y"),
         "negated_but_asserting": rate([x for x in xs if x["rel"] in assoc], lambda x: x["D"] == "G")}
    s["kept_minus_dropped"] = {"diff": round(s["kept"]["rate"] - s["dropped"]["rate"], 4), "newcombe": newcombe(s["kept"], s["dropped"])}
    with gzip.open(OUT / "evidence_verdicts.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["canonical_triple_id", "paper_id", "kept_by_cleaning", "relation", "relation_cleaned", "R", "A", "B", "D"])
        for x in xs:
            w.writerow([x["id"], x["paper"], int(x["kept"]), x["rel"], x["b"][1] if x["b"] else "", x["R"], x["A"], x["B"], x["D"]])
    (OUT / "summary.json").write_text(json.dumps(s, indent=1))
    pct = lambda d: f"{100 * d['rate']:.1f}% ({d['k']:,}/{d['n']:,}; {100 * d['wilson'][0]:.1f}–{100 * d['wilson'][1]:.1f})"
    L = ["# Evidence-grounded check of the triples (DeepSeek-V4-Flash)", "",
         "*Pre-registered in `src/scripts/kg/evidence_schema.json`. Each triple with a CC BY / CC0 source sentence was judged against "
         "that sentence. Model judgement, not human validation; the relabelling was done by the same model family.*", "",
         f"Triples judged: {len(xs):,} of {len(its):,}.", "",
         "| Measure | Value (95% Wilson) |", "|---|---:|",
         f"| Sentence states a relationship between subject and object | {pct(s['R_stated'])} |",
         f"| Original label supported as written | {pct(s['A_supported'])} |",
         f"| Original label supported or acceptable but generic | {pct(s['A_supported_or_partial'])} |",
         f"| Supported only with subject and object reversed | {pct(s['A_reversed'])} |",
         f"| Kept by cleaning: original label supported | {pct(s['kept'])} |",
         f"| Dropped by cleaning: original label supported | {pct(s['dropped'])} |",
         f"| Relabelled triples: original label supported | {pct(s['relabelled']['A_supported'])} |",
         f"| Relabelled triples: cleaned label supported | {pct(s['relabelled']['B_supported'])} |",
         f"| Association triples whose sentence is negated | {pct(s['negated_but_asserting'])} |", "",
         f"Paper bootstrap: stated {s['R_bootstrap']}, supported {s['A_bootstrap']}. Kept minus dropped: "
         f"{100 * s['kept_minus_dropped']['diff']:+.1f} points (95% CI {s['kept_minus_dropped']['newcombe']}). "
         f"Relabelled: cleaned better in {s['relabelled']['B_better']:,}, original better in {s['relabelled']['A_better']:,}.", "",
         f"Codes A: {s['A_codes']}; D: {s['D_codes']}."]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preregister", "judge", "report"])
    a = ap.parse_args()
    {"preregister": cmd_preregister, "judge": cmd_judge, "report": cmd_report}[a.cmd]()
