"""LLM-as-judge pass over the v3 validation sample (Phase E, model evaluation).

The validation sheet (make_validation_sample.py) is scored here by an LLM judge
(Claude Opus 5.5, working interactively) instead of human curators. This is
reported as model evaluation, never as human validation.

  show    print a compact batch for the judge: extracted values, links resolved
          to the linked records' labels, and the source text around the
          evidence span (from data/segmented_sections_markdown)
  record  append the judge's verdicts for a batch (JSON list) to
          llm_judge/verdicts_<pass>.jsonl; a later verdict for the same
          sample_no replaces an earlier one
  export  write validation_sample_llm_judge.csv: pass A -> reviewer_A_*,
          pass B (independent re-judgement of a subset) -> reviewer_B_*;
          score it with make_validation_sample.py score

Usage:
    python src/scripts/vllm_termpop/llm_judge_validation.py show --start 1 --n 20
    python src/scripts/vllm_termpop/llm_judge_validation.py record --pass A --json '[...]'
    python src/scripts/vllm_termpop/llm_judge_validation.py export
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))
VAL = REPO_ROOT / "outputs/results/catalogue_v3_validation"
CAT = REPO_ROOT / "outputs/results/catalogue_v3_vocab"
JUDGE = "Claude Opus 5.5 (claude-opus-5-5), LLM-as-judge"
RECORD_V = {"CORRECT", "PARTIAL", "WRONG", "UNSURE"}
LINK_V = {"CORRECT", "WRONG", "NO_LINK_NEEDED", "MISSING_LINK", "UNSURE"}
WINDOW = 220


def load_sheet():
    with open(VAL / "validation_sample.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def labels():
    """id -> short label for linked datasets/cohorts/assays."""
    out = {}
    keys = {"datasets": ("dataset_id", "dataset_title", "repository_accession"),
            "cohorts": ("cohort_id", "cohort_label", "population_description"),
            "assays": ("assay_id", "assay_type", "target_gene_or_region")}
    for e, (idf, *fields) in keys.items():
        with open(CAT / f"catalogue_{e}.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[r[idf]] = " | ".join(str(r.get(f, ""))[:60] for f in fields if str(r.get(f, "")).strip())
    return out


def section_texts(paper_ids):
    from cdm_pipeline.ner.runner_sections import parse_markdown
    out = {}
    for pid in paper_ids:
        f = REPO_ROOT / "data/segmented_sections_markdown" / f"{pid}.md"
        if f.exists():
            secs, _ = parse_markdown(f.read_text(encoding="utf-8"))
            for s in secs:
                out[(pid, s["section_id"])] = s["body"]
    return out


def context(texts, row):
    m = re.search(r"\[(\S+?)\](?: chars (\d+)-(\d+))?", row["evidence_location"])
    if not m:
        return "(no location)"
    body = texts.get((row["paper_id"], m.group(1)))
    if body is None:
        return "(section text not found)"
    if m.group(2):
        a, b = int(m.group(2)), int(m.group(3))
        lo, hi = max(0, a - WINDOW), min(len(body), b + WINDOW)
        return ("…" if lo else "") + " ".join(body[lo:a].split()) + " ⟦" + " ".join(body[a:b].split()) \
            + "⟧ " + " ".join(body[b:hi].split()) + ("…" if hi < len(body) else "")
    return "(span not located) " + " ".join(body[:2 * WINDOW].split()) + "…"


def show(args):
    rows = [r for r in load_sheet() if args.start <= int(r["sample_no"]) < args.start + args.n]
    lab = labels()
    texts = section_texts({r["paper_id"] for r in rows})
    for r in rows:
        links = json.loads(r["links"] or "{}")
        res = {k: [f"{i}={lab.get(i.strip(), '?')}" for i in v.split(";")] for k, v in links.items()}
        print(f"### #{r['sample_no']} {r['entity']} {r['record_id']} ({r['paper_id']}, {r['evidence_location'].split(' chars')[0]})")
        print("VALUES:", json.dumps({k: str(v)[:120] for k, v in json.loads(r["extracted_values"]).items()}, ensure_ascii=False))
        print("LINKS:", json.dumps(res, ensure_ascii=False) if res else "(none)")
        src = context(texts, r)
        if "⟦" not in src:  # quote not re-found: show it separately
            print("QUOTE:", " ".join(r["evidence_text"].split())[:300])
        print("SOURCE:", src)
        print()


def record(args):
    items = json.loads(Path(args.json[1:]).read_text() if args.json.startswith("@") else args.json)
    path = VAL / "llm_judge" / f"verdicts_{args.pass_}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    for it in items:
        if it["record"] not in RECORD_V or it["links"] not in LINK_V:
            sys.exit(f"bad verdict in {it}")
    with open(path, "a", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(dict(it, judge=JUDGE, pass_=args.pass_), ensure_ascii=False) + "\n")
    done = {json.loads(line)["sample_no"] for line in open(path, encoding="utf-8")}
    print(f"pass {args.pass_}: {len(items)} recorded, {len(done)} distinct samples judged")


def load_pass(p):
    path = VAL / "llm_judge" / f"verdicts_{p}.jsonl"
    out = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            v = json.loads(line)
            out[int(v["sample_no"])] = v
    return out


def export(args):
    rows = load_sheet()
    a, b = load_pass("A"), load_pass("B")
    for r in rows:
        n = int(r["sample_no"])
        for col, src in (("A", a), ("B", b)):
            v = src.get(n)
            r[f"reviewer_{col}_record"] = v["record"] if v else ""
            r[f"reviewer_{col}_links"] = v["links"] if v else ""
            r[f"reviewer_{col}_notes"] = (f"[{JUDGE}, pass {col}] " + v.get("note", "")) if v else ""
    out = VAL / "validation_sample_llm_judge.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}: pass A {len(a)}/{len(rows)}, pass B {len(b)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="LLM-as-judge pass over the validation sample")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--start", type=int, required=True)
    s.add_argument("--n", type=int, default=20)
    r = sub.add_parser("record")
    r.add_argument("--pass", dest="pass_", choices=["A", "B"], required=True)
    r.add_argument("--json", required=True, help="JSON list, or @file")
    sub.add_parser("export")
    args = ap.parse_args(argv)
    return {"show": show, "record": record, "export": export}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
