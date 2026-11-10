"""Intra-NLP comparison — pairwise metrics across all 5 NER models.

Compares GLiNER, PubMedBERT (BioBERT), PubTator3, sciSpaCy (4 models combined),
and Qwen3.5:9b (LLM) on entity overlap, unique contribution, type coverage,
and per-paper statistics.

Reads:  paper/_multi_ner_runs/{gliner,pubmedbert,pubtator3,scispacy,qwen3.5}_ner.csv
Writes: paper/_multi_ner_runs/intra_nlp_comparison.json
        paper/_multi_ner_runs/intra_nlp_comparison_summary.txt
"""
import sys
import io
import csv
import json
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from ..config import NER_OUTPUT_DIR, REPO_ROOT
from ..utils import norm

SPACY_RUNS_DIR = REPO_ROOT / "paper" / "_spacy_runs"

MODEL_DISPLAY = {
    "gliner": "GLiNER",
    "pubmedbert": "PubMedBERT",
    "pubtator": "PubTator3",
    "scispacy": "sciSpaCy",
    "qwen": "Qwen3.5:9b",
}


def _load_csv(path):
    """Load a NER CSV, return list of dicts."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read().replace("\x00", "")
    return list(csv.DictReader(io.StringIO(content)))


def _load_scispacy():
    """Load all per-paper sciSpaCy CSVs and merge into one list."""
    rows = []
    if not SPACY_RUNS_DIR.exists():
        return rows
    for csv_path in sorted(SPACY_RUNS_DIR.glob("*.spacy_ner.csv")):
        rows.extend(_load_csv(csv_path))
    return rows


def _model_key(model_field):
    """Map the 'model' CSV column value to a canonical model group key."""
    m = (model_field or "").lower()
    if "gliner" in m:
        return "gliner"
    if "biobert" in m or "pubmedbert" in m:
        return "pubmedbert"
    if "pubtator" in m:
        return "pubtator"
    if "qwen" in m:
        return "qwen"
    if m.startswith("en_"):
        return "scispacy"
    return m


def build_model_data():
    """Load all NER CSVs and group by canonical model key.

    Returns dict: model_key -> {
        "rows": [...],           # raw CSV rows
        "entities": set,         # normalized entity strings (lowercased)
        "entities_typed": dict,  # norm_entity -> set of CDM types
        "by_type": Counter,      # CDM type -> count
        "by_paper": Counter,     # paper filename -> entity count
        "papers": set,           # set of paper filenames
    }
    """
    sources = {
        "gliner": NER_OUTPUT_DIR / "gliner_ner.csv",
        "pubmedbert": NER_OUTPUT_DIR / "pubmedbert_ner.csv",
        "pubtator": NER_OUTPUT_DIR / "pubtator3_ner.csv",
        "scispacy": NER_OUTPUT_DIR / "scispacy_ner.csv",
        "qwen": NER_OUTPUT_DIR / "qwen3.5_ner.csv",
    }

    raw_rows = {}
    for key, path in sources.items():
        raw_rows[key] = _load_csv(path)
        print("  Loaded %d rows for %s" % (len(raw_rows[key]), MODEL_DISPLAY.get(key, key)))

    models = {}
    for key, rows in raw_rows.items():
        entities = set()
        entities_typed = defaultdict(set)
        by_type = Counter()
        by_paper = Counter()
        papers = set()

        for r in rows:
            term = r.get("term", "").strip()
            if not term:
                continue
            ne = norm(term)
            if not ne or len(ne) < 2:
                continue
            label = r.get("labels", "ENTITY").strip().upper()
            paper = r.get("paper", "").strip()

            entities.add(ne)
            entities_typed[ne].add(label)
            by_type[label] += 1
            if paper:
                by_paper[paper] += 1
                papers.add(paper)

        models[key] = {
            "rows": rows,
            "entities": entities,
            "entities_typed": dict(entities_typed),
            "by_type": by_type,
            "by_paper": by_paper,
            "papers": papers,
        }

    return models


def jaccard(set_a, set_b):
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def compute_pairwise(models):
    """Compute pairwise overlap metrics between all models."""
    keys = sorted(models.keys())
    results = {}

    for a, b in combinations(keys, 2):
        ea = models[a]["entities"]
        eb = models[b]["entities"]
        overlap = ea & eb
        union = ea | eb

        # Per-type overlap
        type_overlap = {}
        all_types = set(models[a]["by_type"].keys()) | set(models[b]["by_type"].keys())
        for t in sorted(all_types):
            ea_t = {e for e, types in models[a]["entities_typed"].items() if t in types}
            eb_t = {e for e, types in models[b]["entities_typed"].items() if t in types}
            if ea_t or eb_t:
                type_overlap[t] = {
                    "a": len(ea_t),
                    "b": len(eb_t),
                    "overlap": len(ea_t & eb_t),
                    "jaccard": round(jaccard(ea_t, eb_t), 4),
                }

        # Paper overlap
        pa = models[a]["papers"]
        pb = models[b]["papers"]

        results["%s__%s" % (a, b)] = {
            "a_entities": len(ea),
            "b_entities": len(eb),
            "overlap": len(overlap),
            "union": len(union),
            "jaccard": round(jaccard(ea, eb), 4),
            "a_only": len(ea - eb),
            "b_only": len(eb - ea),
            "a_papers": len(pa),
            "b_papers": len(pb),
            "paper_overlap": len(pa & pb),
            "type_overlap": type_overlap,
        }

    return results


def compute_unique_contribution(models):
    """For each model, count entities found ONLY by that model (not in any other)."""
    keys = sorted(models.keys())
    all_others = {}
    for k in keys:
        all_others[k] = set()
        for k2 in keys:
            if k2 != k:
                all_others[k].update(models[k2]["entities"])

    results = {}
    for k in keys:
        own = models[k]["entities"]
        unique = own - all_others[k]
        results[k] = {
            "total_unique": len(unique),
            "pct_of_own": round(100 * len(unique) / max(len(own), 1), 1),
            "pct_of_all_unique": None,  # filled later
        }

    total_all_unique = sum(r["total_unique"] for r in results.values())
    for k in keys:
        results[k]["pct_of_all_unique"] = round(
            100 * results[k]["total_unique"] / max(total_all_unique, 1), 1
        )

    return results, total_all_unique


def compute_type_coverage(models):
    """Build a matrix of model x CDM type coverage."""
    keys = sorted(models.keys())
    all_types = sorted(set().union(*(m["by_type"].keys() for m in models.values())))

    matrix = {}
    for k in keys:
        matrix[k] = {t: models[k]["by_type"].get(t, 0) for t in all_types}

    return matrix, all_types


def compute_per_paper_stats(models):
    """Per-paper entity counts and co-occurrence across models."""
    all_papers = set()
    for m in models.values():
        all_papers.update(m["papers"])

    keys = sorted(models.keys())
    per_paper = {}
    for paper in sorted(all_papers):
        counts = {}
        for k in keys:
            counts[k] = models[k]["by_paper"].get(paper, 0)
        per_paper[paper] = counts

    # Summary stats
    summary = {}
    for k in keys:
        vals = [models[k]["by_paper"].get(p, 0) for p in all_papers]
        nonzero = [v for v in vals if v > 0]
        summary[k] = {
            "papers_with_entities": len(nonzero),
            "total_papers": len(all_papers),
            "coverage_pct": round(100 * len(nonzero) / max(len(all_papers), 1), 1),
            "mean_per_paper": round(sum(vals) / max(len(all_papers), 1), 1),
            "median_per_paper": sorted(vals)[len(vals) // 2] if vals else 0,
            "max_per_paper": max(vals) if vals else 0,
        }

    return per_paper, summary


def compute_ensemble_stats(models):
    """Union and intersection of all models."""
    keys = sorted(models.keys())
    entity_sets = [models[k]["entities"] for k in keys]

    union_all = set().union(*entity_sets)
    intersection_all = set(entity_sets[0])  # copy to avoid mutating input
    for s in entity_sets[1:]:
        intersection_all &= s

    # Progressive union (how much does each model add?)
    progressive = []
    accumulated = set()
    for k in keys:
        added = models[k]["entities"] - accumulated
        accumulated.update(models[k]["entities"])
        progressive.append({
            "model": k,
            "new_entities": len(added),
            "cumulative_union": len(accumulated),
        })

    return {
        "union_all": len(union_all),
        "intersection_all": len(intersection_all),
        "progressive_union": progressive,
    }


def format_summary_text(results):
    """Format a human-readable summary."""
    lines = []
    lines.append("=" * 80)
    lines.append("INTRA-NLP COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")

    # Per-model stats
    lines.append("1. PER-MODEL STATISTICS")
    lines.append("-" * 60)
    model_stats = results["model_stats"]
    lines.append("%-12s %8s %8s %8s %8s" % (
        "Model", "Entities", "Unique", "Papers", "Types"
    ))
    for k in sorted(model_stats.keys()):
        s = model_stats[k]
        lines.append("%-12s %8d %8d %8d %8d" % (
            MODEL_DISPLAY.get(k, k),
            s["total_entities"],
            s["unique_entities"],
            s["papers_covered"],
            s["types_covered"],
        ))
    lines.append("")

    # Pairwise Jaccard
    lines.append("2. PAIRWISE ENTITY OVERLAP (Jaccard)")
    lines.append("-" * 60)
    pw = results["pairwise"]
    pairs = sorted(pw.keys())
    lines.append("%-20s %8s %8s %8s %8s %8s" % (
        "Pair", "A_only", "B_only", "Overlap", "Union", "Jaccard"
    ))
    for pair in pairs:
        d = pw[pair]
        a, b = pair.split("__")
        label = "%s vs %s" % (MODEL_DISPLAY.get(a, a), MODEL_DISPLAY.get(b, b))
        lines.append("%-20s %8d %8d %8d %8d %8.4f" % (
            label, d["a_only"], d["b_only"], d["overlap"], d["union"], d["jaccard"]
        ))
    lines.append("")

    # Unique contribution
    lines.append("3. UNIQUE ENTITY CONTRIBUTION (found by ONLY one model)")
    lines.append("-" * 60)
    uc = results["unique_contribution"]
    lines.append("%-12s %8s %8s %8s" % (
        "Model", "Unique", "% of own", "% of all"
    ))
    for k in sorted(uc.keys()):
        d = uc[k]
        lines.append("%-12s %8d %8.1f%% %8.1f%%" % (
            MODEL_DISPLAY.get(k, k),
            d["total_unique"],
            d["pct_of_own"],
            d["pct_of_all_unique"],
        ))
    lines.append("  Total unique across all models: %d" % results["total_unique_all"])
    lines.append("")

    # Type coverage
    lines.append("4. TYPE COVERAGE MATRIX")
    lines.append("-" * 60)
    tc = results["type_coverage"]
    types = results["all_types"]
    header = "%-12s" % "Model"
    for t in types:
        header += " %8s" % t[:8]
    lines.append(header)
    for k in sorted(tc.keys()):
        row = "%-12s" % MODEL_DISPLAY.get(k, k)
        for t in types:
            row += " %8d" % tc[k].get(t, 0)
        lines.append(row)
    lines.append("")

    # Ensemble stats
    lines.append("5. ENSEMBLE STATISTICS")
    lines.append("-" * 60)
    es = results["ensemble"]
    lines.append("  Union of all models:     %d entities" % es["union_all"])
    lines.append("  Intersection of all:      %d entities" % es["intersection_all"])
    lines.append("  Progressive union:")
    for p in es["progressive_union"]:
        lines.append("    + %-12s -> %6d new (cumulative: %d)" % (
            MODEL_DISPLAY.get(p["model"], p["model"]),
            p["new_entities"],
            p["cumulative_union"],
        ))
    lines.append("")

    # Per-paper coverage
    lines.append("6. PER-PAPER COVERAGE")
    lines.append("-" * 60)
    pp = results["per_paper_summary"]
    lines.append("%-12s %8s %8s %8s %8s %8s" % (
        "Model", "Papers", "Cover%", "Mean", "Median", "Max"
    ))
    for k in sorted(pp.keys()):
        s = pp[k]
        lines.append("%-12s %8d %8.1f%% %8.1f %8d %8d" % (
            MODEL_DISPLAY.get(k, k),
            s["papers_with_entities"],
            s["coverage_pct"],
            s["mean_per_paper"],
            s["median_per_paper"],
            s["max_per_paper"],
        ))
    lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    print("Loading NER outputs for all 5 models ...")
    models = build_model_data()

    keys = sorted(models.keys())
    print("\nModels loaded: %s" % [MODEL_DISPLAY.get(k, k) for k in keys])

    # 1. Per-model stats
    model_stats = {}
    for k in keys:
        m = models[k]
        model_stats[k] = {
            "total_entities": len(m["rows"]),
            "unique_entities": len(m["entities"]),
            "papers_covered": len(m["papers"]),
            "types_covered": len(m["by_type"]),
        }

    # 2. Pairwise
    print("Computing pairwise overlaps ...")
    pairwise = compute_pairwise(models)

    # 3. Unique contribution
    print("Computing unique entity contributions ...")
    unique_contrib, total_unique_all = compute_unique_contribution(models)

    # 4. Type coverage
    print("Computing type coverage matrix ...")
    type_coverage, all_types = compute_type_coverage(models)

    # 5. Ensemble
    print("Computing ensemble statistics ...")
    ensemble = compute_ensemble_stats(models)

    # 6. Per-paper
    print("Computing per-paper statistics ...")
    per_paper, per_paper_summary = compute_per_paper_stats(models)

    results = {
        "model_stats": model_stats,
        "pairwise": pairwise,
        "unique_contribution": unique_contrib,
        "total_unique_all": total_unique_all,
        "type_coverage": type_coverage,
        "all_types": all_types,
        "ensemble": ensemble,
        "per_paper": per_paper,
        "per_paper_summary": per_paper_summary,
        "model_display": MODEL_DISPLAY,
    }

    # Save JSON
    out_json = NER_OUTPUT_DIR / "intra_nlp_comparison.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print("\nResults saved to %s" % out_json)

    # Save summary text
    summary_text = format_summary_text(results)
    out_txt = NER_OUTPUT_DIR / "intra_nlp_comparison_summary.txt"
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(summary_text)
    print("Summary saved to %s" % out_txt)

    # Print to console
    print()
    print(summary_text)


if __name__ == "__main__":
    main()
