#!/usr/bin/env python3
"""make_paper.py — Generate every number in the manuscript from checked-in sources.

This script is the single source of truth for all numeric claims in the
Microbiome-CDM manuscript. It:

1. Queries the v2.1.1-clean release DB for all database statistics.
2. Reads Claim B results from claim_B_novel_entity_recall/results/summary.json.
3. Reads Claim C (50-paper hybrid) from claim_C_hybrid_fusion/results_v2/.
4. Reads Claim D (speed/efficiency) from claim_D_speed_efficiency/results/timings.csv.
5. Reads Claim A results from the latest 5× rerun aggregate (if available).
6. Reads NER runner results from the latest 444-paper rerun (if available).
7. Reads external benchmark results from the latest rerun (if available).

All numbers are written to paper/manuscript/numbers.json with full
provenance (SQL, source file path, timestamp).

Usage:
    python src/scripts/make_paper.py
    python src/scripts/make_paper.py --db releases/v2.1.1-clean/microbiome_cdm.db
    python src/scripts/make_paper.py --check  # compare against manuscript.tex
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DEFAULT_DB = REPO_ROOT / "releases" / "v2.1.1-clean" / "microbiome_cdm.db"
MANUSCRIPT = REPO_ROOT / "paper" / "manuscript" / "manuscript.tex"
OUT_JSON = REPO_ROOT / "paper" / "manuscript" / "numbers.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def query_db(db_path: Path, sql: str, params: tuple = ()) -> Any:
    """Execute SQL and return result. For scalar queries, return single value."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    if len(rows) == 1 and len(rows[0].keys()) == 1:
        return rows[0][0]
    return [dict(r) for r in rows]


def pct(num: int, denom: int) -> float:
    return round(100 * num / denom, 1) if denom else 0.0


# ---------------------------------------------------------------------------
# Section 1: Database statistics from v2.1.1-clean
# ---------------------------------------------------------------------------
def collect_db_stats(db_path: Path) -> dict:
    """Query all database statistics from the release DB."""
    stats: dict[str, Any] = {
        "_source": str(db_path),
        "_sha256": sha256_file(db_path),
        "_queries": [],
    }

    def record(name: str, sql: str, value: Any):
        stats[name] = value
        stats["_queries"].append({"name": name, "sql": sql.strip(), "result": value})

    # Totals
    record("total_entities", "SELECT COUNT(*) FROM entities",
           query_db(db_path, "SELECT COUNT(*) FROM entities"))
    record("total_relationships", "SELECT COUNT(*) FROM relationships",
           query_db(db_path, "SELECT COUNT(*) FROM relationships"))
    record("total_controlled_vocab", "SELECT COUNT(*) FROM controlled_vocabularies",
           query_db(db_path, "SELECT COUNT(*) FROM controlled_vocabularies"))
    record("total_edge_evidence", "SELECT COUNT(*) FROM edge_evidence",
           query_db(db_path, "SELECT COUNT(*) FROM edge_evidence"))

    # UMLS / OLS / BioPortal mapping
    record("umls_mapped", "SELECT COUNT(*) FROM entities WHERE UMLS_ID IS NOT NULL AND UMLS_ID != ''",
           query_db(db_path, "SELECT COUNT(*) FROM entities WHERE UMLS_ID IS NOT NULL AND UMLS_ID != ''"))
    record("ols_mapped", "SELECT COUNT(*) FROM entities WHERE OLS IS NOT NULL AND OLS != ''",
           query_db(db_path, "SELECT COUNT(*) FROM entities WHERE OLS IS NOT NULL AND OLS != ''"))
    record("bioportal_mapped", "SELECT COUNT(*) FROM entities WHERE Bioportal IS NOT NULL AND Bioportal != ''",
           query_db(db_path, "SELECT COUNT(*) FROM entities WHERE Bioportal IS NOT NULL AND Bioportal != ''"))
    record("any_vocab_entities", "SELECT COUNT(DISTINCT entity_id) FROM controlled_vocabularies",
           query_db(db_path, "SELECT COUNT(DISTINCT entity_id) FROM controlled_vocabularies"))

    te = stats["total_entities"]
    stats["umls_pct"] = pct(stats["umls_mapped"], te)
    stats["ols_pct"] = pct(stats["ols_mapped"], te)
    stats["bioportal_pct"] = pct(stats["bioportal_mapped"], te)
    stats["any_vocab_pct"] = pct(stats["any_vocab_entities"], te)

    # Per-entity-type counts
    etype_rows = query_db(db_path, """
        SELECT entity_type,
               COUNT(*) AS total,
               SUM(CASE WHEN UMLS_ID IS NOT NULL AND UMLS_ID != '' THEN 1 ELSE 0 END) AS umls,
               SUM(CASE WHEN OLS IS NOT NULL AND OLS != '' THEN 1 ELSE 0 END) AS ols,
               SUM(CASE WHEN Bioportal IS NOT NULL AND Bioportal != '' THEN 1 ELSE 0 END) AS bio
        FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC
    """)
    stats["entities_by_type"] = {}
    for r in etype_rows:
        t = r["entity_type"]
        stats["entities_by_type"][t] = {
            "total": r["total"],
            "umls": r["umls"],
            "umls_pct": pct(r["umls"], r["total"]),
            "ols": r["ols"],
            "ols_pct": pct(r["ols"], r["total"]),
            "bioportal": r["bio"],
            "bioportal_pct": pct(r["bio"], r["total"]),
        }

    # Per-relationship-type counts
    rel_rows = query_db(db_path, """
        SELECT relationship_type, COUNT(*) AS cnt
        FROM relationships GROUP BY relationship_type ORDER BY cnt DESC
    """)
    stats["relationships_by_type"] = {r["relationship_type"]: r["cnt"] for r in rel_rows}

    # Relationship sources
    src_rows = query_db(db_path, """
        SELECT source_db, COUNT(*) AS cnt
        FROM relationships WHERE source_db IS NOT NULL
        GROUP BY source_db ORDER BY cnt DESC
    """)
    stats["relationships_by_source"] = {r["source_db"]: r["cnt"] for r in src_rows}

    # Relationship source_type breakdown
    stype_rows = query_db(db_path, """
        SELECT source_type, COUNT(*) AS cnt
        FROM relationships GROUP BY source_type ORDER BY cnt DESC
    """)
    stats["relationships_by_source_type"] = {r["source_type"]: r["cnt"] for r in stype_rows}

    # Vocabulary breakdown
    vocab_rows = query_db(db_path, """
        SELECT vocabulary_name, COUNT(*) AS cnt
        FROM controlled_vocabularies GROUP BY 1 ORDER BY 2 DESC
    """)
    stats["vocab_by_name"] = {r["vocabulary_name"]: r["cnt"] for r in vocab_rows}
    stats["n_distinct_vocabularies"] = len(vocab_rows)

    # Edge evidence coverage
    ee_rels = query_db(db_path, "SELECT COUNT(DISTINCT relationship_id) FROM edge_evidence")
    stats["edge_evidence_rels"] = ee_rels
    stats["edge_evidence_pct"] = pct(ee_rels, stats["total_relationships"])

    # Projects
    record("n_projects", "SELECT COUNT(*) FROM projects",
           query_db(db_path, "SELECT COUNT(*) FROM projects"))

    # Entity-project mentions
    record("n_entity_project_mentions", "SELECT COUNT(*) FROM entity_project_mentions",
           query_db(db_path, "SELECT COUNT(*) FROM entity_project_mentions"))

    return stats


# ---------------------------------------------------------------------------
# Section 2: Claim B (novel entity recall)
# ---------------------------------------------------------------------------
def collect_claim_b() -> dict:
    path = REPO_ROOT / "paper_claims" / "claim_B_novel_entity_recall" / "results" / "summary.json"
    if not path.exists():
        return {"_error": f"Claim B results not found: {path}", "_source": str(path)}
    with open(path) as f:
        data = json.load(f)
    return {
        "_source": str(path),
        "_sha256": sha256_file(path),
        "n_llm_unique": data["n_llm_unique"],
        "n_spacy_unique": data["n_spacy_unique"],
        "n_truly_novel": data["n_truly_novel"],
        "n_spacy_only_truly_novel": data["n_spacy_only_truly_novel"],
        "jaccard": data["jaccard_overlap"],
        "intersection_size": data["intersection_size"],
        "union_size": data["union_size"],
        "verdict": data["verdict"],
    }


# ---------------------------------------------------------------------------
# Section 3: Claim C (50-paper hybrid fusion)
# ---------------------------------------------------------------------------
def collect_claim_c() -> dict:
    base = REPO_ROOT / "paper_claims" / "claim_C_hybrid_fusion" / "results_v2"
    summary_path = base / "summary.json"
    leavek_path = base / "leave_k_out_results.json"
    if not summary_path.exists():
        return {"_error": f"Claim C results not found: {summary_path}"}

    with open(summary_path) as f:
        summary = json.load(f)

    result: dict[str, Any] = {
        "_source": str(summary_path),
        "_sha256": sha256_file(summary_path),
        "n_entities": summary["n_entities"],
        "n_relationships": summary["n_relationships"],
        "source_counts": summary["source_counts"],
        "headline_metrics": summary["headline_metrics"],
        "verdict": summary["verdict"],
    }

    # Jaccard
    # NOTE: In the hybrid build, LLM triples are ingested before spaCy, so the
    # `source` field (assigned on first insert) is "llm" for all shared entities.
    # Therefore:
    #   - llm_ents  (LLM-only n_entities)  INCLUDES the shared/cross-source entities
    #   - spacy_ents (spaCy-only n_entities) EXCLUDES them (already spaCy-unique)
    # So union = llm_ents + spacy_ents (no need to subtract cross again), and
    # spacy_unique = spacy_ents (already unique, don't subtract cross).
    llm_ents = summary["headline_metrics"]["LLM-only"]["n_entities"]
    spacy_ents = summary["headline_metrics"]["spaCy-only"]["n_entities"]
    cross = summary["headline_metrics"]["Hybrid (5-source)"]["cross_source_entities"]
    union = llm_ents + spacy_ents
    result["jaccard"] = round(cross / union, 4) if union else 0
    result["cross_source_entities"] = cross
    result["llm_unique"] = llm_ents - cross
    result["spacy_unique"] = spacy_ents
    result["hybrid_multiplier_vs_llm"] = round(summary["n_entities"] / llm_ents, 2) if llm_ents else 0
    true_spacy_ents = spacy_ents + cross
    result["hybrid_multiplier_vs_spacy"] = round(summary["n_entities"] / true_spacy_ents, 2) if true_spacy_ents else 0

    # Leave-K-out
    if leavek_path.exists():
        with open(leavek_path) as f:
            lk = json.load(f)
        result["leave_k_out"] = {}
        for k, v in lk.items():
            recalls = [s["recall_full"] for s in v["seed_recalls"]]
            entity_recalls = [s["recall_entity"] for s in v["seed_recalls"]]
            result["leave_k_out"][k] = {
                "mean_recall_full": round(v["mean_recall_full"], 4),
                "mean_recall_entity": round(v["mean_recall_entity"], 4),
                "n_held": v["seed_recalls"][0]["n_total"],
            }

    return result


# ---------------------------------------------------------------------------
# Section 4: Claim D (speed/efficiency)
# ---------------------------------------------------------------------------
def collect_claim_d() -> dict:
    path = REPO_ROOT / "paper_claims" / "claim_D_speed_efficiency" / "results" / "timings.csv"
    if not path.exists():
        return {"_error": f"Claim D results not found: {path}"}

    with open(path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    llm_time = sum(float(r["llm_wall_clock_s"]) for r in rows if r["llm_wall_clock_s"])
    llm_ents = sum(int(r["llm_n_entities"]) for r in rows if r["llm_n_entities"])
    llm_cost = sum(float(r["llm_cost_usd"]) for r in rows if r["llm_cost_usd"])
    llm_total_kb = sum(float(r["size_kb"]) for r in rows if r["size_kb"])
    n_papers = len(rows)

    # spaCy columns may be empty in this file
    spacy_time = sum(float(r["spacy_wall_clock_s"]) for r in rows if r.get("spacy_wall_clock_s"))
    spacy_ents = sum(int(r["spacy_n_entities"]) for r in rows if r.get("spacy_n_entities"))
    spacy_cost = sum(float(r["spacy_cost_usd"]) for r in rows if r.get("spacy_cost_usd"))

    return {
        "_source": str(path),
        "_sha256": sha256_file(path),
        "n_papers": n_papers,
        "llm_total_s": round(llm_time, 1),
        "llm_n_entities": llm_ents,
        "llm_throughput": round(llm_ents / llm_time, 2) if llm_time else 0,
        "llm_cost_usd": round(llm_cost, 4),
        "llm_s_per_kb": round(llm_time / llm_total_kb, 1) if llm_total_kb else 0,
        "spacy_total_s": round(spacy_time, 1) if spacy_time else None,
        "spacy_n_entities": spacy_ents if spacy_ents else None,
        "spacy_throughput": round(spacy_ents / spacy_time, 2) if spacy_time else None,
        "spacy_cost_usd": round(spacy_cost, 4) if spacy_cost else None,
    }


# ---------------------------------------------------------------------------
# Section 5: Claim A (context disambiguation) — from latest 5× rerun
# ---------------------------------------------------------------------------
def collect_claim_a() -> dict:
    """Find the latest Claim A 5× rerun results directory."""
    results_base = REPO_ROOT / "outputs/results"
    if not results_base.exists():
        return {"_error": "No outputs/results/ directory"}

    # Find directories matching *_claim_a_5x
    candidates = sorted(results_base.glob("*_claim_a_5x"), reverse=True)
    if not candidates:
        return {"_error": "No Claim A 5× rerun found. Run claim_a_5x_rerun.sbatch first."}

    run_dir = candidates[0]
    agg_path = run_dir / "aggregate.json"
    if not agg_path.exists():
        return {"_error": f"aggregate.json not found in {run_dir}. Job may still be running.",
                "_source": str(run_dir)}

    with open(agg_path) as f:
        agg = json.load(f)

    return {
        "_source": str(agg_path),
        "_sha256": sha256_file(agg_path),
        "n_runs": agg["n_runs"],
        "mean_acc": round(agg["mean_acc"], 4),
        "stdev": round(agg["stdev"], 4),
        "min_acc": round(agg["min_acc"], 4),
        "max_acc": round(agg["max_acc"], 4),
        "always_correct": agg["always_correct"],
        "always_wrong": agg["always_wrong"],
        "inconsistent": agg["inconsistent"],
        "runs": agg["runs"],
    }


# ---------------------------------------------------------------------------
# Section 6: NER runner (444-paper per-model counts) — from latest rerun
# ---------------------------------------------------------------------------
def collect_ner_runner() -> dict:
    """Find the latest NER 444-paper rerun results."""
    results_base = REPO_ROOT / "outputs/results"
    candidates = sorted(results_base.glob("*_ner_444"), reverse=True)
    if not candidates:
        return {"_error": "No NER 444-paper rerun found. Run ner_444_rerun.sbatch first."}

    run_dir = candidates[0]
    summary_path = run_dir / "_multi_ner_summary.json"
    if not summary_path.exists():
        return {"_error": f"Summary not found in {run_dir}. Job may still be running.",
                "_source": str(run_dir)}

    with open(summary_path) as f:
        summary = json.load(f)

    return {
        "_source": str(summary_path),
        "_sha256": sha256_file(summary_path),
        "models": summary.get("models", {}),
    }


# ---------------------------------------------------------------------------
# Section 7: External benchmark (BC5CDR + BioRED) — from latest rerun
# ---------------------------------------------------------------------------
def collect_external_benchmark() -> dict:
    """Find the latest external benchmark rerun results."""
    results_base = REPO_ROOT / "outputs/results"
    candidates = sorted(results_base.glob("*_ext_bench"), reverse=True)
    if not candidates:
        return {"_error": "No external benchmark rerun found. Run external_benchmark_rerun.sbatch first."}

    run_dir = candidates[0]
    results_path = run_dir / "ner_benchmark_results.json"
    if not results_path.exists():
        return {"_error": f"Results not found in {run_dir}. Job may still be running.",
                "_source": str(run_dir)}

    with open(results_path) as f:
        data = json.load(f)

    # Flatten: extract overall F1 per (dataset, model)
    flat = {}
    for key, val in data.items():
        if "__" not in key:
            continue
        ds, model = key.split("__", 1)
        if not isinstance(val, dict) or "error" in val:
            flat[key] = {"error": val.get("error", "unknown")}
            continue
        o_e = val.get("overall", {}).get("exact", {})
        o_r = val.get("overall", {}).get("relaxed", {})
        flat[key] = {
            "exact_f1": round(o_e.get("F1", 0), 4),
            "relaxed_f1": round(o_r.get("F1", 0), 4),
            "exact_p": round(o_e.get("P", 0), 4),
            "exact_r": round(o_e.get("R", 0), 4),
        }

    return {
        "_source": str(results_path),
        "_sha256": sha256_file(results_path),
        "results": flat,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--db", default=str(DEFAULT_DB), help="Path to release DB")
    p.add_argument("--out", default=str(OUT_JSON), help="Output JSON path")
    p.add_argument("--check", action="store_true", help="Compare numbers against manuscript.tex")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    print(f"Generating manuscript numbers from: {db_path}")
    print(f"SHA-256: {sha256_file(db_path)}")
    print()

    numbers: dict[str, Any] = {
        "_meta": {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "db_path": str(db_path),
            "db_sha256": sha256_file(db_path),
            "repo_root": str(REPO_ROOT),
        }
    }

    print("1. Database statistics (v2.1.1-clean)...")
    numbers["db"] = collect_db_stats(db_path)
    print(f"   {numbers['db']['total_entities']:,} entities, {numbers['db']['total_relationships']:,} relationships")
    print(f"   UMLS {numbers['db']['umls_mapped']:,} ({numbers['db']['umls_pct']}%), "
          f"OLS {numbers['db']['ols_mapped']:,} ({numbers['db']['ols_pct']}%), "
          f"BioPortal {numbers['db']['bioportal_mapped']:,} ({numbers['db']['bioportal_pct']}%)")

    print("2. Claim B (novel entity recall)...")
    numbers["claim_b"] = collect_claim_b()
    if "_error" in numbers["claim_b"]:
        print(f"   SKIP: {numbers['claim_b']['_error']}")
    else:
        print(f"   LLM novel: {numbers['claim_b']['n_truly_novel']:,}, "
              f"spaCy-only: {numbers['claim_b']['n_spacy_only_truly_novel']:,}, "
              f"Jaccard: {numbers['claim_b']['jaccard']}")

    print("3. Claim C (50-paper hybrid fusion)...")
    numbers["claim_c"] = collect_claim_c()
    if "_error" in numbers["claim_c"]:
        print(f"   SKIP: {numbers['claim_c']['_error']}")
    else:
        print(f"   {numbers['claim_c']['n_entities']:,} entities, "
              f"{numbers['claim_c']['n_relationships']:,} relationships, "
              f"Jaccard: {numbers['claim_c']['jaccard']}")

    print("4. Claim D (speed/efficiency)...")
    numbers["claim_d"] = collect_claim_d()
    if "_error" in numbers["claim_d"]:
        print(f"   SKIP: {numbers['claim_d']['_error']}")
    else:
        d = numbers["claim_d"]
        print(f"   LLM: {d['llm_total_s']}s, {d['llm_n_entities']} ents, "
              f"${d['llm_cost_usd']}, {d['llm_s_per_kb']} s/KB")

    print("5. Claim A (context disambiguation, 5× rerun)...")
    numbers["claim_a"] = collect_claim_a()
    if "_error" in numbers["claim_a"]:
        print(f"   SKIP: {numbers['claim_a']['_error']}")
    else:
        a = numbers["claim_a"]
        print(f"   {a['n_runs']} runs, mean: {a['mean_acc']:.1%}, "
              f"range: {a['min_acc']:.1%}-{a['max_acc']:.1%}")

    print("6. NER runner (444-paper per-model)...")
    numbers["ner_runner"] = collect_ner_runner()
    if "_error" in numbers["ner_runner"]:
        print(f"   SKIP: {numbers['ner_runner']['_error']}")
    else:
        print(f"   Models: {list(numbers['ner_runner']['models'].keys())}")

    print("7. External benchmark (BC5CDR + BioRED)...")
    numbers["external_benchmark"] = collect_external_benchmark()
    if "_error" in numbers["external_benchmark"]:
        print(f"   SKIP: {numbers['external_benchmark']['_error']}")
    else:
        print(f"   {len(numbers['external_benchmark']['results'])} (dataset, model) pairs")

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(numbers, f, indent=2)
    print(f"\nWrote: {out_path}")

    if args.check:
        print("\n--- CHECK MODE: Comparing against manuscript.tex ---")
        check_against_manuscript(numbers)

    return 0


def check_against_manuscript(numbers: dict) -> None:
    """Print warnings for numbers in manuscript.tex that don't match numbers.json."""
    if not MANUSCRIPT.exists():
        print(f"Manuscript not found: {MANUSCRIPT}")
        return

    text = MANUSCRIPT.read_text()

    # Key numbers to verify
    checks = [
        ("10,217", "db.total_entities", f"{numbers.get('db', {}).get('total_entities', '?'):,}"),
        ("8,210", "db.total_relationships", f"{numbers.get('db', {}).get('total_relationships', '?'):,}"),
        ("62.1", "db.umls_pct", str(numbers.get('db', {}).get('umls_pct', '?'))),
        ("6,345", "db.umls_mapped", f"{numbers.get('db', {}).get('umls_mapped', '?'):,}"),
        ("45,682", "db.total_controlled_vocab", f"{numbers.get('db', {}).get('total_controlled_vocab', '?'):,}"),
        ("8,668", "db.total_edge_evidence", f"{numbers.get('db', {}).get('total_edge_evidence', '?'):,}"),
    ]

    for old_str, label, new_val in checks:
        if old_str in text:
            if old_str != new_val:
                print(f"  MISMATCH: manuscript has '{old_str}' but {label} = {new_val}")
            else:
                print(f"  OK: '{old_str}' matches {label}")
        else:
            print(f"  NOT FOUND in manuscript: '{old_str}' ({label})")


if __name__ == "__main__":
    sys.exit(main())
