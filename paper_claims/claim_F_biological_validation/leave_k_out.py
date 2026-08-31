"""
Leave-K-out validation of the hybrid KG.

This is the proper validation for a KG with a KB layer: hold out a fraction of
the KB's KNOWN_ASSOCIATIONS, rebuild the KG without that subset, then measure
recall on the held-out portion. If the held-out recall is high, the KB is
not just "answering with itself" — the text-mining layers are recovering
canonical biology from the literature.

We do this for K=10%, 20%, 30% of the KB.

For each K:
  1. Sample K% of KNOWN_ASSOCIATIONS
  2. Create a "masked KB" without those associations
  3. Build a v2 KG using the masked KB
  4. Measure full-triple recall on the held-out subset
  5. Repeat 3 times with different random seeds for stability

Outputs:
  - leave_k_out_results.json
  - leave_k_out_report.txt
"""
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import json
import random
from pathlib import Path
from copy import deepcopy
import importlib

REPO = Path(r"C:\Users\jkalra\Documents\Microbiome-CDM")
sys.path.insert(0, str(REPO / "paper_claims"))


def collect_holdout_associations(kb_module, fraction=0.2, seed=0):
    """Sample a fraction of the KB-curated associations to hold out.
    Returns a list of (subject, relation, object) tuples (normalized) and the
    modified KNOWN_ASSOCIATIONS dict.
    """
    random.seed(seed)
    held_out = []

    # KNOWN_ASSOCIATIONS: sample from each subcategory
    for cat, info in kb_module.KNOWN_ASSOCIATIONS.items():
        # Sample some depleted_organisms
        n = max(1, int(len(info.get("depleted_organisms", [])) * fraction))
        for org in random.sample(info.get("depleted_organisms", []), min(n, len(info.get("depleted_organisms", [])))):
            for d in kb_module.CATEGORY_TO_DISEASE.get(cat, [cat]):
                held_out.append((org, "depleted_in", d))
        # Sample some enriched_organisms
        n = max(1, int(len(info.get("enriched_organisms", [])) * fraction))
        for org in random.sample(info.get("enriched_organisms", []), min(n, len(info.get("enriched_organisms", [])))):
            for d in kb_module.CATEGORY_TO_DISEASE.get(cat, [cat]):
                held_out.append((org, "enriched_in", d))
        # Sample some treatments
        n = max(1, int(len(info.get("treatments", [])) * fraction))
        for drug in random.sample(info.get("treatments", []), min(n, len(info.get("treatments", [])))):
            for d in kb_module.CATEGORY_TO_DISEASE.get(cat, [cat]):
                held_out.append((drug, "treats", d))
        # Sample some producer_to_product
        n = max(1, int(len(info.get("producer_to_product", [])) * fraction))
        for tup in random.sample(info.get("producer_to_product", []), min(n, len(info.get("producer_to_product", [])))):
            held_out.append((tup[0], "produces", tup[1]))

    # Also sample some from SCFA_TREATS_INFLAMMATION
    scfa_items = [(c, d) for c, ds in kb_module.SCFA_TREATS_INFLAMMATION.items() for d in ds]
    n = max(1, int(len(scfa_items) * fraction))
    for c, d in random.sample(scfa_items, min(n, len(scfa_items))):
        held_out.append((c, "treats", d))

    # Also sample some from ANTIBIOTIC_DISRUPTS
    antibio_items = [(a, o) for a, os_ in kb_module.ANTIBIOTIC_DISRUPTS.items() for o in os_]
    n = max(1, int(len(antibio_items) * fraction))
    for a, o in random.sample(antibio_items, min(n, len(antibio_items))):
        held_out.append((a, "disrupts", o))

    return held_out


def norm(s):
    import re
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def main():
    import biological_kb
    import claim_F_biological_validation.benchmark as benchmark_module
    # Reimport to ensure latest
    importlib.reload(biological_kb)
    importlib.reload(benchmark_module)

    fractions = [0.1, 0.2, 0.3]
    n_seeds = 3
    results = {}

    # Save the original KG to restore
    full_kg = benchmark_module.REPO_ROOT / "paper_claims" / "claim_C_hybrid_fusion" / "mini_hybrid_v2"

    for fraction in fractions:
        seed_recalls = []
        for seed in range(n_seeds):
            # Build masked KB
            masked_kb = deepcopy(biological_kb.KNOWN_ASSOCIATIONS)
            random.seed(seed)
            for cat, info in masked_kb.items():
                if "depleted_organisms" in info:
                    n = max(1, int(len(info["depleted_organisms"]) * fraction))
                    info["depleted_organisms"] = random.sample(info["depleted_organisms"],
                                                              max(0, len(info["depleted_organisms"]) - n))
                if "enriched_organisms" in info:
                    n = max(1, int(len(info["enriched_organisms"]) * fraction))
                    info["enriched_organisms"] = random.sample(info["enriched_organisms"],
                                                              max(0, len(info["enriched_organisms"]) - n))
                if "treatments" in info:
                    n = max(1, int(len(info["treatments"]) * fraction))
                    info["treatments"] = random.sample(info["treatments"],
                                                       max(0, len(info["treatments"]) - n))
                if "producer_to_product" in info:
                    n = max(1, int(len(info["producer_to_product"]) * fraction))
                    info["producer_to_product"] = random.sample(info["producer_to_product"],
                                                                max(0, len(info["producer_to_product"]) - n))
            # Mask the SCFA and antibiotic
            masked_scfa = {}
            n = max(1, int(sum(len(v) for v in biological_kb.SCFA_TREATS_INFLAMMATION.values()) * fraction))
            n_per = max(1, n // len(biological_kb.SCFA_TREATS_INFLAMMATION))
            for k, v in biological_kb.SCFA_TREATS_INFLAMMATION.items():
                if len(v) > n_per:
                    masked_scfa[k] = v[:-n_per]
                else:
                    masked_scfa[k] = []
            masked_antibio = {}
            n = max(1, int(sum(len(v) for v in biological_kb.ANTIBIOTIC_DISRUPTS.values()) * fraction))
            n_per = max(1, n // len(biological_kb.ANTIBIOTIC_DISRUPTS))
            for k, v in biological_kb.ANTIBIOTIC_DISRUPTS.items():
                if len(v) > n_per:
                    masked_antibio[k] = v[:-n_per]
                else:
                    masked_antibio[k] = []

            # Save the held-out triples
            held_out = []
            for cat, info in biological_kb.KNOWN_ASSOCIATIONS.items():
                # Compute full list of triples
                for org in info.get("depleted_organisms", []):
                    if org not in masked_kb[cat].get("depleted_organisms", []):
                        for d in biological_kb.CATEGORY_TO_DISEASE.get(cat, [cat]):
                            held_out.append((norm(org), "depleted_in", norm(d)))
                for org in info.get("enriched_organisms", []):
                    if org not in masked_kb[cat].get("enriched_organisms", []):
                        for d in biological_kb.CATEGORY_TO_DISEASE.get(cat, [cat]):
                            held_out.append((norm(org), "enriched_in", norm(d)))
                for drug in info.get("treatments", []):
                    if drug not in masked_kb[cat].get("treatments", []):
                        for d in biological_kb.CATEGORY_TO_DISEASE.get(cat, [cat]):
                            held_out.append((norm(drug), "treats", norm(d)))
                for tup in info.get("producer_to_product", []):
                    if tup not in masked_kb[cat].get("producer_to_product", []):
                        held_out.append((norm(tup[0]), "produces", norm(tup[1])))

            # Now build a v2 KG with the masked KB by monkey-patching
            from paper_claims.claim_C_hybrid_fusion import build_mini_hybrid_v2 as build_module
            build_module.KNOWN_ASSOCIATIONS = masked_kb
            build_module.SCFA_TREATS_INFLAMMATION = masked_scfa
            build_module.ANTIBIOTIC_DISRUPTS = masked_antibio

            # Build to a different output dir
            masked_dir = REPO / "paper_claims" / "claim_C_hybrid_fusion" / "mini_hybrid_v2_masked"
            build_module.DEFAULT_OUT = masked_dir

            # Rebuild
            print(f"\n=== Fraction {fraction:.0%}, seed {seed}: {len(held_out)} held-out associations ===")
            try:
                build_module.main()
            except Exception as e:
                print(f"  Build failed: {e}")
                continue

            # Now measure recall on the held-out set
            ents, rels = benchmark_module.load_hybrid(masked_dir)
            kb_relations = benchmark_module.build_kb_relations_set(rels)
            kb_entities = benchmark_module.build_entity_set_full(ents, rels)

            n_total = len(held_out)
            n_recovered = 0
            for (s, rel, o) in held_out:
                if (s, rel, o) in kb_relations:
                    n_recovered += 1
            n_entities_recovered = 0
            for (s, rel, o) in held_out:
                if s in kb_entities and o in kb_entities:
                    n_entities_recovered += 1
            recall_full = n_recovered / n_total if n_total else 0
            recall_entity = n_entities_recovered / n_total if n_total else 0
            print(f"  Held-out: {n_total}, recovered (full): {n_recovered} ({100*recall_full:.1f}%)")
            print(f"  Held-out entity coverage: {100*recall_entity:.1f}%")
            seed_recalls.append({"n_total": n_total, "n_recovered": n_recovered,
                                 "recall_full": recall_full,
                                 "recall_entity": recall_entity})

        results[fraction] = {
            "seed_recalls": seed_recalls,
            "mean_recall_full": sum(s["recall_full"] for s in seed_recalls) / max(1, len(seed_recalls)),
            "mean_recall_entity": sum(s["recall_entity"] for s in seed_recalls) / max(1, len(seed_recalls)),
        }

    # Restore the original KB
    build_module.KNOWN_ASSOCIATIONS = biological_kb.KNOWN_ASSOCIATIONS
    build_module.SCFA_TREATS_INFLAMMATION = biological_kb.SCFA_TREATS_INFLAMMATION
    build_module.ANTIBIOTIC_DISRUPTS = biological_kb.ANTIBIOTIC_DISRUPTS

    # Output
    out_json = REPO / "paper_claims" / "claim_F_biological_validation" / "results" / "leave_k_out_results.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_json}")

    # Report
    lines = []
    lines.append("=" * 75)
    lines.append("LEAVE-K-OUT VALIDATION — held-out KB associations recovered by text-mining")
    lines.append("=" * 75)
    lines.append(f"  For each K% of KB associations held out, we rebuild the KG with the")
    lines.append(f"  remaining {(1-fractions[0])*100:.0f}% and measure recall on the held-out portion.")
    lines.append(f"  If the held-out recall is high, the text-mining layers are recovering")
    lines.append(f"  canonical biology from the literature — the KG is not just 'answering with itself'.")
    lines.append("")
    lines.append(f"{'K':>5s}  {'n_seeds':>7s}  {'mean recall (full)':>20s}  {'mean recall (entity)':>22s}")
    lines.append("-" * 60)
    for f, r in results.items():
        lines.append(f"{f:>5.0%}  {len(r['seed_recalls']):>7d}  {100*r['mean_recall_full']:>19.1f}%  {100*r['mean_recall_entity']:>21.1f}%")
    lines.append("")
    lines.append("Per-seed detail:")
    for f, r in results.items():
        lines.append(f"  K={f:.0%}:")
        for i, s in enumerate(r["seed_recalls"]):
            lines.append(f"    seed {i}: {s['n_recovered']}/{s['n_total']} = {100*s['recall_full']:.1f}% full, {100*s['recall_entity']:.1f}% entity")

    out_txt = REPO / "paper_claims" / "claim_F_biological_validation" / "results" / "leave_k_out_report.txt"
    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {out_txt}")
    print()
    for ln in lines:
        print(ln)


if __name__ == "__main__":
    main()
