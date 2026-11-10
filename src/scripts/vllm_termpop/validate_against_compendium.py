"""Score catalogue-NER output against the Human Microbiome Compendium's
curated project metadata (data/168000-samples-paper/projects.csv).

The compendium is an independent, human-curated annotation of 482 BioProjects:
`sample_type`, `condition`, `subjects`, `amplicon`, `kit`. Those columns overlap
directly with the catalogue fields the LLM is extracting, so they give a real
external check instead of eyeballing rows.

Comparisons (NER field -> compendium column):
    samples.sample_type              -> sample_type
    cohorts.health_status            -> condition
    assays.target_gene_or_region     -> amplicon
    assays.dna_extraction_method     -> kit

Matching is deliberately lenient (token containment in either direction, plus
V-region normalisation) because the two sources use different granularity: the
compendium writes "v3-v4", the paper writes "hypervariable V3-V4 region of 16S
rRNA". A miss therefore means "not corroborated", not "wrong".

Usage:
    PYTHONPATH=src python src/scripts/vllm_termpop/validate_against_compendium.py \
        --run_dir outputs/results/catalogue_ner_full \
        [--out outputs/results/catalogue_ner_full/compendium_validation]

Outputs:
    <out>.csv        per-paper verdicts for each compared field
    <out>_summary.json  agreement rates + coverage
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
PROJECTS = REPO_ROOT / "data/168000-samples-paper" / "projects.csv"
DATASETS = REPO_ROOT / "data" / "catalogue" / "tables" / "datasets.csv"

COMPARISONS = [
    ("samples", "sample_type", "sample_type"),
    ("cohorts", "health_status", "condition"),
    ("assays", "target_gene_or_region", "amplicon"),
    ("assays", "dna_extraction_method", "kit"),
]

STOP = {"the", "of", "a", "an", "and", "in", "from", "for", "with", "by", "to",
        "was", "were", "is", "are", "using", "used", "sample", "samples",
        "study", "data", "gene", "rrna", "region", "extraction", "dna"}


def norm(text):
    """Lowercase word set, dropping punctuation and generic microbiome words."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOP}


def v_region(text):
    """Normalise amplicon mentions: 'V3-V4', 'v3v4', 'V3–V4' -> 'v3-v4'."""
    t = (text or "").lower().replace("–", "-").replace("—", "-")
    hits = re.findall(r"v\s*([3-9])\s*[-–_ ]?\s*([3-9])", t)
    out = set()
    for a, b in hits:
        out.add("v%s-%s" % (a, b))
        out.add("v%s-v%s" % (a, b))
    for a in re.findall(r"\bv([3-9])\b", t):
        out.add("v%s" % a)
    return out


def related(ner_value, gold_value):
    """True if the NER value corroborates the curated value (lenient)."""
    if not gold_value or not ner_value:
        return None  # nothing to compare
    if v_region(gold_value) & v_region(ner_value) and v_region(gold_value):
        return True
    g, n = norm(gold_value), norm(ner_value)
    if not g or not n:
        return None
    if g <= n or n <= g:
        return True
    return len(g & n) / len(g) >= 0.6


def load_csv(path, enc="utf-8"):
    with open(path, newline="", encoding=enc) as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--out", default=None,
                    help="output prefix (default: <run_dir>/compendium_validation)")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    out_prefix = Path(args.out) if args.out else run_dir / "compendium_validation"

    records = [json.loads(line) for line in
               (run_dir / "catalogue_records.jsonl").open(encoding="utf-8")]
    gold = {r["project"]: r for r in load_csv(PROJECTS, "utf-8-sig")}
    paper_acc = {r["paper_id"]: (r.get("repository_accession") or "").strip()
                 for r in load_csv(DATASETS)}

    by_paper_field = {}
    for rec in records:
        paper = rec["paper_id"]
        for entity, field, gold_col in COMPARISONS:
            if rec["entity_type"] != entity:
                continue
            val = rec["fields"].get(field)
            if val:
                by_paper_field.setdefault((paper, gold_col), []).append(str(val))

    papers = sorted({r["paper_id"] for r in records})
    rows = []
    for paper in papers:
        acc = paper_acc.get(paper, "")
        g = gold.get(acc, {})
        for _entity, _field, gold_col in COMPARISONS:
            gold_val = (g.get(gold_col) or "").strip()
            ner_vals = by_paper_field.get((paper, gold_col), [])
            verdicts = [related(v, gold_val) for v in ner_vals]
            verdicts = [v for v in verdicts if v is not None]
            if not gold_val:
                status = "NO_GOLD"
            elif not ner_vals:
                status = "NER_MISSING"
            elif any(verdicts):
                status = "CORROBORATED"
            else:
                status = "NOT_CORROBORATED"
            rows.append({
                "paper_id": paper, "bioproject": acc, "field": gold_col,
                "compendium_value": gold_val,
                "ner_values": " | ".join(ner_vals[:6]),
                "status": status,
            })

    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out_prefix) + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["paper_id", "bioproject", "field", "compendium_value",
                            "ner_values", "status"])
        w.writeheader()
        w.writerows(rows)

    summary = {"run_dir": str(run_dir), "papers_with_records": len(papers),
               "compendium_projects": len(gold), "fields": {}}
    for _e, _f, gold_col in COMPARISONS:
        sub = [r for r in rows if r["field"] == gold_col]
        comparable = [r for r in sub if r["status"] not in ("NO_GOLD", "NER_MISSING")]
        ok = sum(1 for r in comparable if r["status"] == "CORROBORATED")
        summary["fields"][gold_col] = {
            "papers_with_gold": sum(1 for r in sub if r["status"] != "NO_GOLD"),
            "comparable": len(comparable),
            "corroborated": ok,
            "agreement_pct": round(100.0 * ok / len(comparable), 2) if comparable else None,
            "ner_missing": sum(1 for r in sub if r["status"] == "NER_MISSING"),
        }
    with open(str(out_prefix) + "_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary["fields"], indent=2))
    print("wrote", str(out_prefix) + ".csv")


if __name__ == "__main__":
    main()
