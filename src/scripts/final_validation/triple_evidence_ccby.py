"""Triple-vs-sentence LLM screen of 2026-11-07, restricted to sentences from CC BY / CC0 papers, plus rights accounting.

The 2026-11-07 run (outputs/results/evidence_judge_all_2026-11-07/, DeepSeek-V4.1-Flash via the Fraunhofer Genie
gateway) sent the anchor sentence of every triple, without a licence filter. This script
  1. counts the sentences sent by the licence of their source paper (rights/PAPER_RIGHTS_MATRIX.csv), for the change
     record and the external-processing inventory (B24);
  2. reports the screen only on sentences from CC BY / CC0 papers (the basis of the 2026-11-03 check, Q03-Q06);
  3. reconciles it with Q04 (original label supported 22.0%) by predicate kind and by cross-tabulation on the triples
     both runs judged.
It reads frozen outputs and writes only to a new dated directory. Model judgements, not accuracy.

    python src/scripts/final_validation/triple_evidence_ccby.py [--out DIR]
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
RUN = ROOT / "outputs/results/evidence_judge_all_2026-11-07"
MERGED = RUN / "merged_triples.csv.gz"
VERD = RUN / "verdicts.jsonl"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
OLD = ROOT / "outputs/results/kg_2026-11-04/evidence_check/verdicts.jsonl"
OPEN = {"cc by", "cc0"}
GENERIC = {"OTHER_RELATION"}
LABELS = ["SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "CONFLICTS"]


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson": wilson(k, n)}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/results/benchmark/triple_evidence_ccby_2026-11-07")
    a = ap.parse_args()
    rights = {r["paper_id"]: r for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))}
    sent = {}                                           # triple id -> paper of the sentence actually sent
    for line in open(VERD, encoding="utf-8"):
        v = json.loads(line)
        if v.get("quote_paper_id"):
            sent[v["id"]] = v["quote_paper_id"]
    rows = list(csv.DictReader(gzip.open(MERGED, "rt", encoding="utf-8")))
    old = {json.loads(x)["id"]: json.loads(x) for x in open(OLD, encoding="utf-8")}

    # 1 rights accounting: one sentence per judged request item (verdicts.jsonl holds the sent paper id)
    by_lic = collections.Counter()
    by_dec = collections.Counter()
    for tid, pid in sent.items():
        r = rights.get(pid)
        lic = (r["licence"].lower() if r else "paper not in rights matrix")
        by_lic[lic] += 1
        by_dec[r["proposed_release_decision"] if r else "UNKNOWN"] += 1
    n_open = sum(v for k, v in by_lic.items() if k in OPEN)

    # 2 screen on CC BY / CC0 sentences
    sub = [r for r in rows if r["ev_support"] in LABELS and rights.get(r["ev_quote_paper"], {}).get("licence", "").lower() in OPEN]
    n = len(sub)
    dist = {l: rate(sum(r["ev_support"] == l for r in sub), n) for l in LABELS}
    kinds = {}
    for name, test in (("specific_predicate", lambda r: r["predicate"] not in GENERIC),
                       ("generic_predicate", lambda r: r["predicate"] in GENERIC)):
        s = [r for r in sub if test(r)]
        kinds[name] = {"n": len(s), **{l: rate(sum(r["ev_support"] == l for r in s), len(s)) for l in LABELS}}
    conf_neg = None                                     # negation share needs reading notes; left to the report
    # 3 cross-tab with the 2026-11-03 run (old A: Y supported, P partial/generic, N not, R reversed)
    xt = collections.Counter()
    for r in sub:
        o = old.get(r["triple_id"])
        if o:
            xt[(o["A"], r["ev_support"])] += 1
    overlap = sum(xt.values())
    xtab = {oa: {l: xt[(oa, l)] for l in LABELS} for oa in ("Y", "P", "N", "R")}

    out = {"generated": "2026-11-07", "model": "deepseek-ai/DeepSeek-V4.1-Flash (Fraunhofer Genie gateway)",
           "what": "LLM judgement of whether each triple's anchor sentence states it; not accuracy, not human validation",
           "rights_sent_sentences": {"total": len(sent), "cc_by_or_cc0": n_open, "other": len(sent) - n_open,
                                     "by_licence": dict(by_lic.most_common()),
                                     "by_proposed_release_decision": dict(by_dec.most_common())},
           "ccby_subset": {"triples_judged": n, "distribution": dist, "by_predicate_kind": kinds},
           "reconciliation_with_2026_11_03": {
               "overlap_triples": overlap,
               "old_A_codes": "Y original label supported; P partial or only generic; N not supported; R reversed",
               "crosstab_old_A_rows_new_support_columns": xtab,
               "note": "the 2026-11-03 rubric (Q04) scored the original label: a generic OTHER_RELATION triple could at "
                       "best be P. The 2026-11-07 rubric scores whether the sentence states the claim, so a generic "
                       "triple whose sentence states some relation between the two entities can be SUPPORTED."},
           "inputs": {str(p.relative_to(ROOT)): sha(p) for p in (MERGED, VERD, RIGHTS, OLD)}}
    a.out.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out / "summary.json", "w"), indent=1)

    pct = lambda d: f"{100 * d['rate']:.1f}%" if d["rate"] is not None else "n/a"  # noqa: E731
    L = ["# Triple-vs-sentence screen, CC BY / CC0 sentences only (2026-11-07)", "",
         "LLM judgement (DeepSeek-V4.1-Flash), not accuracy. Generated by "
         "`src/scripts/final_validation/triple_evidence_ccby.py`.", "",
         "## Rights accounting of the run", "",
         f"- Sentences sent to the Genie gateway: {len(sent):,}; from CC BY / CC0 papers {n_open:,}; other "
         f"{len(sent) - n_open:,}.", "", "| Licence of source paper | Sentences |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in by_lic.most_common()]
    L += ["", "| Proposed release decision | Sentences |", "|---|---:|"] + [f"| {k} | {v:,} |" for k, v in by_dec.most_common()]
    L += ["", f"## Screen on {n:,} triples with a CC BY / CC0 sentence", "", "| Verdict | n | % [95% Wilson] |", "|---|---:|---|"]
    L += [f"| {l} | {d['k']:,} | {pct(d)} [{100 * d['wilson'][0]:.1f}–{100 * d['wilson'][1]:.1f}] |" for l, d in dist.items()]
    L += ["", "| Predicate kind | n | SUPPORTED | PARTIAL | NOT_SUPPORTED | CONFLICTS |", "|---|---:|---:|---:|---:|---:|"]
    L += [f"| {k} | {v['n']:,} | " + " | ".join(pct(v[l]) for l in LABELS) + " |" for k, v in kinds.items()]
    L += ["", f"## Reconciliation with the 2026-11-03 check (Q03–Q06), {overlap:,} triples judged by both", "",
          "Rows: 2026-11-03 code for the original label (Y supported, P partial or generic, N not, R reversed). "
          "Columns: 2026-11-07 verdict.", "", "| old A \\ new | " + " | ".join(LABELS) + " |", "|---|" + "---:|" * 4]
    L += [f"| {oa} | " + " | ".join(f"{xtab[oa][l]:,}" for l in LABELS) + " |" for oa in xtab]
    L += ["", out["reconciliation_with_2026_11_03"]["note"], ""]
    (a.out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"sent": len(sent), "open": n_open, "subset": n,
                      "dist": {l: d["k"] for l, d in dist.items()}, "overlap": overlap}, indent=0))


if __name__ == "__main__":
    main()
