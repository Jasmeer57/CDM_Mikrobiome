#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claim F benchmark — Biological validation of the mini-hybrid KG.

Loads a curated gold set of well-established human-gut microbiome associations
(60 triples sourced from HMDAD, DisGeNET, gutMGBrain, KEGG, and major
meta-analyses) and asks: what fraction of these does the mini-hybrid KG
recover? This validates the claim that the KG is biologically sound.

The gold set is intentionally *external* to the KG construction — the
hybrid-builder doesn't see it during build time. So a high recall on the
gold set is a real validation of the KG's biological content.

Outputs:
  - results/recall_per_category.csv
  - results/recall_per_relation.csv
  - results/missed_associations.csv
  - results/spurious_associations.csv  (associations in KG not in gold — useful for novel-finding triage)
  - results/summary.json
  - results/verdict.txt
"""
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from paper_claims.biological_kb import norm


def load_hybrid(hybrid_dir: Path):
    ents = json.loads((hybrid_dir / "entities.json").read_text(encoding="utf-8"))
    rels = json.loads((hybrid_dir / "relationships.json").read_text(encoding="utf-8"))
    return ents, rels


def build_entity_set_full(ents, rels):
    """Set of (norm(entity)) including BOTH seed-only entities and
    entities that appear in relationships. This catches KB-seed-only
    entities that the gold set references but the build script didn't
    yet wire up a relation for."""
    s = set()
    for e in ents:
        t = e.get("term", "") or e.get("entity", "")
        if t:
            s.add(norm(t))
    for r in rels:
        s.add(norm(r.get("source_entity", "")))
        s.add(norm(r.get("target_entity", "")))
    return s


def load_gold(gold_path: Path):
    d = json.loads(gold_path.read_text(encoding="utf-8"))
    return d.get("associations", []), d.get("categories", [])


def build_kb_relations_set(rels):
    """Build a set of (norm(subject), norm(relation), norm(object)) for fast lookup."""
    s = set()
    for r in rels:
        s.add((norm(r["source_entity"]), norm(r["relationship_type"]), norm(r["target_entity"])))
    return s


def build_kb_entity_set(rels):
    """Set of (norm(entity), norm(entity)) in the KG."""
    s = set()
    for r in rels:
        s.add(norm(r["source_entity"]))
        s.add(norm(r["target_entity"]))
    return s


def compute_metrics(gold, kb_relations, kb_entities):
    """For each gold association, check if (subject, relation, object) is in the KG.

    Also accept partial matches where the type is implied by the relation name
    (e.g., 'depleted_in' implies the subject is an organism)."""
    n_total = len(gold)
    n_full_match = 0
    n_entity_match = 0
    n_partial_match = 0
    per_category = defaultdict(lambda: {"total": 0, "full": 0, "partial": 0, "entity_only": 0})
    per_relation = defaultdict(lambda: {"total": 0, "full": 0, "partial": 0, "entity_only": 0})
    missed = []

    for assoc in gold:
        s_n = norm(assoc["subject"])
        r_n = norm(assoc["relation"])
        o_n = norm(assoc["object"])
        cat = assoc.get("category", "unknown")

        full_key = (s_n, r_n, o_n)
        full = full_key in kb_relations

        s_in = s_n in kb_entities
        o_in = o_n in kb_entities

        # Partial match: subject entity present, object entity present,
        # and the relation type exists in the KG between an entity of the right type
        # (here, we just check that the subject-entity is present + object-entity is present
        # and some relation connects them)
        partial = False
        if s_in and o_in and not full:
            # find any relation in KB between these two
            for r in kb_relations:
                if r[0] == s_n and r[2] == o_n:
                    partial = True
                    break
        elif s_in and o_in and full:
            partial = True  # full is also partial

        entity_only = s_in and o_in and not full and not partial

        if full:
            n_full_match += 1
        if s_in and o_in:
            n_entity_match += 1
        if partial:
            n_partial_match += 1

        per_category[cat]["total"] += 1
        per_relation[r_n]["total"] += 1
        if full:
            per_category[cat]["full"] += 1
            per_relation[r_n]["full"] += 1
        if partial:
            per_category[cat]["partial"] += 1
            per_relation[r_n]["partial"] += 1
        if entity_only:
            per_category[cat]["entity_only"] += 1
            per_relation[r_n]["entity_only"] += 1

        if not full:
            missed.append({
                "subject": assoc["subject"],
                "relation": assoc["relation"],
                "object": assoc["object"],
                "category": cat,
                "subject_in_kg": s_in,
                "object_in_kg": o_in,
                "evidence": assoc.get("evidence", ""),
            })

    return {
        "n_total": n_total,
        "n_full_match": n_full_match,
        "n_entity_match": n_entity_match,
        "n_partial_match": n_partial_match,
        "n_missed": len(missed),
        "recall_full": round(n_full_match / n_total, 4),
        "recall_entity": round(n_entity_match / n_total, 4),
        "recall_partial": round(n_partial_match / n_total, 4),
        "per_category": dict(per_category),
        "per_relation": dict(per_relation),
        "missed": missed,
    }


def find_spurious_associations(rels, gold, kb_relations):
    """Associations in the KG that are NOT in the gold set.

    These are 'spurious' relative to the gold set, but they may be valid novel
    findings. Useful for manual triage / future work."""
    gold_keys = {(norm(a["subject"]), norm(a["relation"]), norm(a["object"])) for a in gold}
    spurious = []
    for r in rels:
        key = (norm(r["source_entity"]), norm(r["relationship_type"]), norm(r["target_entity"]))
        if key in gold_keys:
            continue
        # Only consider curated (kb_curated) and high-confidence LLM edges
        if r.get("source_db") == "kb_curated":
            # These are KB-seeded — should have been in gold but wasn't. Not a true spurious.
            continue
        if r.get("confidence", 0) >= 0.85 and r.get("source_db") in ("kb_curated",):
            continue
        spurious.append({
            "source": r["source_entity"],
            "relation": r["relationship_type"],
            "target": r["target_entity"],
            "source_db": r.get("source_db", ""),
            "confidence": r.get("confidence", 0),
        })
    return spurious


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hybrid-dir", default=str(REPO_ROOT / "paper_claims" / "claim_C_hybrid_fusion" / "mini_hybrid_v2"))
    ap.add_argument("--gold-file", default=str(HERE / "gold_associations.json"))
    ap.add_argument("--output", default=str(HERE / "results"))
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Loading hybrid:  {args.hybrid_dir}")
    print(f"Loading gold:    {args.gold_file}")
    ents, rels = load_hybrid(Path(args.hybrid_dir))
    gold, categories = load_gold(Path(args.gold_file))
    print(f"Hybrid: {len(ents)} entities, {len(rels)} relationships")
    print(f"Gold:   {len(gold)} associations in {len(categories)} categories\n")

    kb_relations = build_kb_relations_set(rels)
    kb_entities = build_entity_set_full(ents, rels)
    print(f"KG relation triples: {len(kb_relations)}")
    print(f"KG entities:          {len(kb_entities)}\n")

    metrics = compute_metrics(gold, kb_relations, kb_entities)

    # Per-category recall
    cat_csv = out / "recall_per_category.csv"
    with open(cat_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["category", "n_total", "n_full_match", "recall_full", "n_entity_match", "recall_entity", "n_partial_match"])
        w.writeheader()
        for cat in sorted(metrics["per_category"]):
            d = metrics["per_category"][cat]
            w.writerow({
                "category": cat, "n_total": d["total"], "n_full_match": d["full"],
                "recall_full": round(d["full"] / d["total"], 4) if d["total"] else 0,
                "n_entity_match": d["partial"] + d["entity_only"],
                "recall_entity": round((d["partial"] + d["entity_only"]) / d["total"], 4) if d["total"] else 0,
                "n_partial_match": d["partial"],
            })
    print(f"Wrote: {cat_csv}")

    # Per-relation recall
    rel_csv = out / "recall_per_relation.csv"
    with open(rel_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["relation", "n_total", "n_full_match", "recall_full", "n_partial_match"])
        w.writeheader()
        for rel in sorted(metrics["per_relation"]):
            d = metrics["per_relation"][rel]
            w.writerow({
                "relation": rel, "n_total": d["total"], "n_full_match": d["full"],
                "recall_full": round(d["full"] / d["total"], 4) if d["total"] else 0,
                "n_partial_match": d["partial"],
            })
    print(f"Wrote: {rel_csv}")

    # Missed associations
    miss_csv = out / "missed_associations.csv"
    with open(miss_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["subject", "relation", "object", "category", "subject_in_kg", "object_in_kg", "evidence"])
        w.writeheader()
        for m in metrics["missed"]:
            w.writerow(m)
    print(f"Wrote: {miss_csv}")

    # Spurious associations
    spurious = find_spurious_associations(rels, gold, kb_relations)
    spur_csv = out / "spurious_associations.csv"
    with open(spur_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source", "relation", "target", "source_db", "confidence"])
        w.writeheader()
        for s in spurious:
            w.writerow(s)
    print(f"Wrote: {spur_csv}")

    # Headline
    print()
    print("=" * 70)
    print("CLAIM F — BIOLOGICAL VALIDATION")
    print("=" * 70)
    print(f"  Gold associations:        {metrics['n_total']}")
    print(f"  Full-triple match:        {metrics['n_full_match']}  ({100*metrics['recall_full']:.1f}%)")
    print(f"  Both-entities match:      {metrics['n_entity_match']}  ({100*metrics['recall_entity']:.1f}%)")
    print(f"  Any-relation partial:     {metrics['n_partial_match']}  ({100*metrics['recall_partial']:.1f}%)")
    print(f"  Missed:                   {metrics['n_missed']}")
    print()
    print("  Per-category recall (full triple):")
    for cat in sorted(metrics["per_category"]):
        d = metrics["per_category"][cat]
        if d["total"] == 0: continue
        cov = d["full"] / d["total"] * 100
        print(f"    {cat:30s}  {d['full']:2d}/{d['total']:2d}  ({cov:5.1f}%)")
    print()
    print("  Per-relation recall (full triple):")
    for rel in sorted(metrics["per_relation"]):
        d = metrics["per_relation"][rel]
        if d["total"] == 0: continue
        cov = d["full"] / d["total"] * 100
        print(f"    {rel:30s}  {d['full']:2d}/{d['total']:2d}  ({cov:5.1f}%)")

    # Summary JSON
    summary = {
        "n_gold": metrics["n_total"],
        "recall_full": metrics["recall_full"],
        "recall_entity": metrics["recall_entity"],
        "recall_partial": metrics["recall_partial"],
        "n_missed": metrics["n_missed"],
        "n_spurious": len(spurious),
        "per_category": {k: v for k, v in metrics["per_category"].items()},
        "per_relation": {k: v for k, v in metrics["per_relation"].items()},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote: {out / 'summary.json'}")

    # Verdict
    print()
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    rf = metrics["recall_full"]
    re_ = metrics["recall_entity"]
    if rf >= 0.80:
        verdict = f"STRONGLY supported: full-triple recall {100*rf:.1f}%"
    elif rf >= 0.60:
        verdict = f"supported: full-triple recall {100*rf:.1f}%, entity-coverage {100*re_:.1f}%"
    elif re_ >= 0.80:
        verdict = f"PARTIALLY supported: entities present ({100*re_:.1f}%) but relations not yet aligned ({100*rf:.1f}%)"
    elif re_ >= 0.60:
        verdict = f"WEAK: entity coverage {100*re_:.1f}%, full triple {100*rf:.1f}%"
    else:
        verdict = f"NOT supported: entity coverage {100*re_:.1f}%, full triple {100*rf:.1f}%"
    print(f"  {verdict}")
    (out / "verdict.txt").write_text(verdict + "\n", encoding="utf-8")
    print(f"\nWrote: {out / 'verdict.txt'}")


if __name__ == "__main__":
    main()
