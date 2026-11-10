"""Score the two-person manual check of 100 triples (analysis fixed in PROTOCOL.md before annotation).

    ~/venvs/parquet_export/bin/python src/scripts/final_validation/human_spotcheck_score.py [--dir DIR]

Reads ANNOTATION_SHEET_A.xlsx (with the AGREED column added after adjudication), ANNOTATION_SHEET_B.xlsx and
KEY_deepseek_verdicts.csv; checks the pre-registered files are unchanged (key, sample, protocol, guide); writes
results.json and RESULTS.md into the same folder. A small two-person spot check of one LLM screen; not accuracy of
the CDM.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

from openpyxl import load_workbook

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
LABELS = ["SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "CONFLICTS"]


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def kappa(a, b):
    n = len(a)
    if not n:
        return None, None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    pe = sum(ca[l] * cb[l] for l in set(a) | set(b)) / (n * n)
    return round(po, 3), (round((po - pe) / (1 - pe), 3) if pe < 1 else None)


def read_sheet(p, agreed=False):
    ws = load_workbook(p, data_only=True)["annotate"]
    head = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(head)}
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[col["item"]] is None:
            continue
        v = (row[col["AGREED"]] if agreed else row[col["SUPPORT"]]) if (not agreed or "AGREED" in col) else None
        out[int(row[col["item"]])] = (str(v).strip().upper() if v else "")
    return out


def dist(labels):
    n = len(labels); c = collections.Counter(labels)
    d = {l: {"k": c[l], "pct": round(100 * c[l] / n, 1) if n else None, "wilson95": wilson(c[l], n)} for l in LABELS}
    sp = c["SUPPORTED"] + c["PARTIAL"]
    d["SUPPORTED_or_PARTIAL"] = {"k": sp, "pct": round(100 * sp / n, 1) if n else None, "wilson95": wilson(sp, n)}
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=ROOT / "outputs/results/benchmark/human_spotcheck_triples_2026-11-09")
    d = ap.parse_args().dir
    pre = dict(reversed(l.split("  ", 1)) for l in (d / "PREREGISTRATION.sha256").read_text().split("\n") if l)
    changed = [f for f in ("KEY_deepseek_verdicts.csv", "sample.csv", "PROTOCOL.md", "GUIDE.txt")
               if hashlib.sha256((d / f).read_bytes()).hexdigest() != pre.get(f)]
    if changed:
        raise SystemExit(f"pre-registered files changed: {changed}")
    A, B = read_sheet(d / "ANNOTATION_SHEET_A.xlsx"), read_sheet(d / "ANNOTATION_SHEET_B.xlsx")
    AG = read_sheet(d / "ANNOTATION_SHEET_A.xlsx", agreed=True)
    key = {int(r["item"]): r for r in csv.DictReader(open(d / "KEY_deepseek_verdicts.csv", encoding="utf-8"))}
    items = sorted(key)
    bad = {w: [i for i in items if s.get(i) not in LABELS] for w, s in (("A", A), ("B", B))}
    if bad["A"] or bad["B"]:
        raise SystemExit(f"items without a valid SUPPORT label: A {bad['A'][:10]} B {bad['B'][:10]}")
    agreed_ok = all(AG.get(i) in LABELS for i in items)
    a = [A[i] for i in items]; b = [B[i] for i in items]
    two = lambda xs: ["S" if x == "SUPPORTED" else "not" for x in xs]  # noqa: E731
    res = {"n": len(items), "annotator_A": dist(a), "annotator_B": dist(b),
           "A_vs_B": {"4_labels": dict(zip(("observed", "kappa"), kappa(a, b))),
                      "supported_vs_not": dict(zip(("observed", "kappa"), kappa(two(a), two(b))))},
           "deepseek_on_sample": dist([key[i]["ds_support"] for i in items])}
    if agreed_ok:
        g = [AG[i] for i in items]; m = [key[i]["ds_support"] for i in items]
        res["agreed"] = dist(g)
        res["deepseek_vs_agreed"] = {"4_labels": dict(zip(("observed", "kappa"), kappa(g, m))),
                                     "supported_vs_not": dict(zip(("observed", "kappa"), kappa(two(g), two(m)))),
                                     "confusion_rows_agreed_cols_deepseek":
                                         {x: {y: sum(1 for i in items if AG[i] == x and key[i]["ds_support"] == y)
                                              for y in LABELS} for x in LABELS}}
    else:
        res["agreed"] = "AGREED column missing or incomplete in sheet A; adjudicate first"
    json.dump(res, open(d / "results.json", "w"), indent=1)
    L = ["# Manual check of 100 triples: results", "", "Two-person spot check of the DeepSeek-V4.1-Flash triple screen "
         "(CC BY / CC0 subset). Not accuracy of the CDM.", "",
         "| Label | A | B | Agreed | DeepSeek (same items) |", "|---|---|---|---|---|"]
    for l in LABELS + ["SUPPORTED_or_PARTIAL"]:
        f = lambda r: f"{r[l]['pct']}% [{r[l]['wilson95'][0]}–{r[l]['wilson95'][1]}]" if isinstance(r, dict) else "–"  # noqa: E731
        L.append(f"| {l} | {f(res['annotator_A'])} | {f(res['annotator_B'])} | {f(res['agreed'])} | "
                 f"{f(res['deepseek_on_sample'])} |")
    L += ["", f"A vs B: {res['A_vs_B']}", ""]
    if agreed_ok:
        L += [f"DeepSeek vs agreed: {res['deepseek_vs_agreed']['4_labels']} (4 labels), "
              f"{res['deepseek_vs_agreed']['supported_vs_not']} (supported vs not)", ""]
    (d / "RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
