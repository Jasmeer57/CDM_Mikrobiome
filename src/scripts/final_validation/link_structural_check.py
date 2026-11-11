"""Structural check of catalogue link fields (cohort_id, assay_id, dataset_id) instead of an LLM judge (no model).

    python src/scripts/final_validation/link_structural_check.py

A passage cannot show an internal identifier, so the 2026-11-09 judges guessed (kappa 0.03-0.08 on these fields).
Each linked id (a field may hold several, separated by ';') is classified:
  BROKEN           the id does not exist in the target table
  CROSS_PAPER      the id exists but belongs to another paper
  VALID_ONLY_OPTION  same paper, and it is the paper's only record of the target type (link cannot be wrong)
  VALID_SAME_SECTION same paper, several candidates, and the target record's evidence is in the same section
  VALID_AMBIGUOUS  same paper, several candidates, evidence elsewhere (structurally valid; choice not verifiable)
Reads CDM 3.0.3 read-only (catalogue_v3_1 claims + all catalogue tables). Output:
outputs/results/benchmark/judge_v2_2026-11-10/link_structural_check.{json,csv}. Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "outputs/results/benchmark/judge_v2_2026-11-10"
TARGET = {"cohort_id": ("cohort", "cohort_id"), "assay_id": ("assay", "assay_id"), "dataset_id": ("dataset", "dataset_id")}
SOURCES = {"claim": "finding_id", "sample": "sample_group_id", "cohort": "cohort_id", "assay": "assay_id",
           "data_asset": "asset_id"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    target = {}
    per_paper = defaultdict(Counter)
    for f, (t, idc) in TARGET.items():
        sec = "section_id" in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        for r in c.execute(f"SELECT {idc}, paper_id{', section_id' if sec else ''} FROM {t}"):
            target[r[0]] = (r["paper_id"], r["section_id"] if sec else None)
            per_paper[f][r["paper_id"]] += 1
    res = defaultdict(Counter)
    rows = []
    for t, idc in SOURCES.items():
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        w = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
        for r in c.execute(f"SELECT * FROM {t}{w}"):
            for f in TARGET:
                if f not in cols or f == idc or not r[f]:
                    continue
                for x in [s.strip() for s in str(r[f]).split(";") if s.strip()]:
                    if x not in target:
                        k = "BROKEN"
                    elif target[x][0] != r["paper_id"]:
                        k = "CROSS_PAPER"
                    elif per_paper[f][r["paper_id"]] == 1:
                        k = "VALID_ONLY_OPTION"
                    elif "section_id" in cols and target[x][1] and target[x][1] == r["section_id"]:
                        k = "VALID_SAME_SECTION"
                    else:
                        k = "VALID_AMBIGUOUS"
                    res[f"{t}.{f}"][k] += 1
                    rows.append({"table": t, "record_id": r[idc], "field": f, "linked_id": x, "result": k})
    tot = Counter()
    for v in res.values():
        tot.update(v)
    out = {"what": "structural check of link fields (no model); replaces LLM judging of cohort_id / assay_id / dataset_id",
           "links": sum(tot.values()), "total": dict(tot), "by_field": {k: dict(v) for k, v in sorted(res.items())}}
    (OUT / "link_structural_check.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    with open(OUT / "link_structural_check.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
