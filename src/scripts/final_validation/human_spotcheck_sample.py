"""Draw a blinded random sample of 100 triples for a two-person manual check, and write the annotation sheets.

    ~/venvs/parquet_export/bin/python src/scripts/final_validation/human_spotcheck_sample.py

Population: the 16,032 triples judged by DeepSeek-V4.1-Flash on 2026-11-07 against a sentence from a CC BY / CC0
paper (= W02). Simple random sample, n = 100, fixed seed. Writes to
outputs/results/benchmark/human_spotcheck_triples_2026-11-09/:
  ANNOTATION_SHEET_A.xlsx, ANNOTATION_SHEET_B.xlsx  identical, blinded (no model verdict), with dropdowns
  sample.csv                                         the 100 items as shown to annotators
  KEY_deepseek_verdicts.csv                          model verdicts -- do not open before both sheets are done
  PREREGISTRATION.sha256                             hashes of protocol, sample, sheets and key, made before annotation
Refuses to overwrite an existing sample (the draw must happen once).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
RUN = ROOT / "outputs/results/evidence_judge_all_2026-11-07"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
OUT = ROOT / "outputs/results/benchmark/human_spotcheck_triples_2026-11-09"
SEED, N = 20261109, 100
OPEN = {"cc by", "cc0"}
LABELS = ["SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "CONFLICTS"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    if (OUT / "sample.csv").exists():
        raise SystemExit("sample already drawn; the draw must happen once (delete the folder only if nobody annotated)")
    rights = {r["paper_id"]: r for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))}
    items = {json.loads(l)["id"]: json.loads(l) for l in open(RUN / "items.jsonl", encoding="utf-8")}
    merged = {r["triple_id"]: r for r in csv.DictReader(gzip.open(RUN / "merged_triples.csv.gz", "rt", encoding="utf-8"))}
    pop = sorted(t for t, r in merged.items()
                 if r["ev_support"] in LABELS
                 and rights.get(r["ev_quote_paper"], {}).get("licence", "").lower() in OPEN
                 and t in items and items[t].get("quote"))
    assert len(pop) == 16032, f"population {len(pop)} != W02 16,032"
    rnd = random.Random(SEED)
    pick = sorted(rnd.sample(pop, N))
    rnd.shuffle(pick)                                   # presentation order independent of id order

    OUT.mkdir(parents=True, exist_ok=False)
    rows, key = [], []
    for k, t in enumerate(pick, 1):
        it, m = items[t], merged[t]
        r = rights.get(it.get("paper_id") or m["ev_quote_paper"], {})
        rows.append({"item": k, "triple_id": t, "paper_id": it.get("paper_id"), "doi": r.get("doi", ""),
                     "licence": r.get("licence", ""), "subject": it["subject"], "relation": it["relation"],
                     "object": it["object"], "subject_type": it.get("st", ""), "object_type": it.get("ot", ""),
                     "sentence": it["quote"]})
        key.append({"item": k, "triple_id": t, "ds_support": m["ev_support"], "ds_polarity": m["ev_polarity"],
                    "ds_justified": m["ev_justified"], "ds_quote_match": m["ev_quote_match"],
                    "ds_notes": m["ev_notes"], "predicate_family": m["family"],
                    "generic": m["predicate"] == "OTHER_RELATION"})
    with open(OUT / "sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with open(OUT / "KEY_deepseek_verdicts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0])); w.writeheader(); w.writerows(key)

    shown = ["item", "subject", "relation", "object", "subject_type", "object_type", "sentence", "doi"]
    fill = ["SUPPORT", "POLARITY", "RELATION_JUSTIFIED", "NOTES"]
    for who in ("A", "B"):
        wb = Workbook(); ws = wb.active; ws.title = "annotate"
        ws.append(shown + fill)
        for c in ws[1]:
            c.font = Font(bold=True)
        for c in ws[1][len(shown):]:
            c.fill = PatternFill("solid", fgColor="FFF2CC")
        for r in rows:
            ws.append([r[c] for c in shown] + ["", "", "", ""])
        widths = {"A": 6, "B": 28, "C": 18, "D": 28, "E": 14, "F": 14, "G": 80, "H": 24, "I": 16, "J": 11, "K": 12, "L": 40}
        for col, wdt in widths.items():
            ws.column_dimensions[col].width = wdt
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        for col, opts in (("I", LABELS), ("J", ["Y", "N", "U"]), ("K", ["Y", "N"])):
            dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
            ws.add_data_validation(dv); dv.add(f"{col}2:{col}{N + 1}")
        ws.freeze_panes = "B2"
        g = wb.create_sheet("guide")
        for line in (open(ROOT / "src/scripts/final_validation/human_spotcheck_guide.txt",
                          encoding="utf-8").read().splitlines()):
            g.append([line])
        g.column_dimensions["A"].width = 120
        wb.save(OUT / f"ANNOTATION_SHEET_{who}.xlsx")
    for name in ("human_spotcheck_protocol.md", "human_spotcheck_guide.txt"):
        (OUT / name.replace("human_spotcheck_", "").upper().replace(".TXT", ".txt").replace(".MD", ".md")).write_bytes(
            (ROOT / "src/scripts/final_validation" / name).read_bytes())
    files = sorted(p for p in OUT.iterdir() if p.is_file())
    (OUT / "PREREGISTRATION.sha256").write_text("".join(f"{sha(p)}  {p.name}\n" for p in files), encoding="utf-8")
    print(f"population {len(pop)}; sample {N}; seed {SEED}; wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
