"""Trace every number in the manuscript drafts to the claims register or a frozen validation/benchmark report.

Status per number: REGISTER (a stated value in MANUSCRIPT_CLAIMS_REGISTER.csv), REPORT (appears in a
final_validation report or the benchmark outputs), UNTRACED (neither; must be fixed or registered).
Small integers (<= 20), years and figure/section labels are skipped as non-claims.

    python manuscript_number_audit.py
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
PUB = ROOT / "paper/publication"
DRAFTS = sorted((PUB / "manuscript_draft").glob("0*.md"))
REPORTS = sorted((PUB / "final_validation").glob("*.md")) + [
    ROOT / "outputs/results/ner_fair_bench/FAIR_NER_BENCHMARK.md",
    ROOT / "outputs/results/ner_corpus_bench/CORPUS_NER_BENCHMARK.md",
    PUB / "rights/RIGHTS_ASSESSMENT.md",
    ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/REPORT.md",
    ROOT / "outputs/results/cleaned_layer_deepseek/CLEANING_REPORT.md",
    ROOT / "outputs/results/benchmark/bugsigdb_comparison_2026-11-03/REPORT.md",
    ROOT / "outputs/results/benchmark/triple_reference_check_2026-11-03/REPORT.md",
]
NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")
SKIP_CTX = re.compile(r"(Figure|Fig\.|Workstream|Q\d|B\d|claim|draft|Draft|v\d|3\.0\.|3\.1\.|1\.0\.|Gate|G\d)", re.I)


def norm(tok: str) -> str:
    t = tok.replace(",", "")
    return str(float(t)).rstrip("0").rstrip(".") if "." in t else t


def numbers(text: str):
    text = re.sub(r"`[^`]*`", " ", text)                    # code spans: paths, IDs
    text = re.sub(r"\[[A-Z]\d{2}[^\]]*\]", " ", text)       # claim-ID brackets
    text = re.sub(r"\[@[^\]]*\]", " ", text)                 # citation keys
    text = re.sub(r"\bdraft \d+(\.\d+)*", " ", text, flags=re.I)  # draft version labels
    text = re.sub(r"\b[A-Za-z]+[-_]?\d[\w.-]*", " ", text)   # model names like Qwen3.5-4B, V4
    for m in NUM.finditer(text):
        yield m.group(1), text[max(0, m.start() - 50):m.end() + 30].replace("\n", " ")


def main():
    reg = set()
    with open(PUB / "final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            for v in (r["stated"], r["recomputed"]):
                for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", v):
                    reg.add(norm(tok))
                try:
                    f = float(v)
                    reg.update({norm(str(round(100 * f, 1))), norm(str(round(f, 2)))} if f < 1 else set())
                except ValueError:
                    pass
    rep = set()
    for p in REPORTS:
        if p.exists():
            rep.update(norm(t) for t, _ in numbers(p.read_text(encoding="utf-8")))
    rows = []
    for d in DRAFTS:
        for tok, ctx in numbers(d.read_text(encoding="utf-8")):
            n = norm(tok)
            if ("." not in n and int(n) <= 20) or re.fullmatch(r"20[12]\d", n) or SKIP_CTX.search(ctx[40:60]):
                continue
            status = "REGISTER" if n in reg else ("REPORT" if n in rep else "UNTRACED")
            rows.append({"draft": d.name, "number": tok, "status": status, "context": ctx.strip()})
    out = PUB / "final_validation/MANUSCRIPT_NUMBER_AUDIT.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["draft", "number", "status", "context"])
        w.writeheader()
        w.writerows(rows)
    print(Counter(r["status"] for r in rows))
    for r in rows:
        if r["status"] == "UNTRACED":
            print(f'{r["draft"]}: {r["number"]}  …{r["context"]}…')


if __name__ == "__main__":
    main()
