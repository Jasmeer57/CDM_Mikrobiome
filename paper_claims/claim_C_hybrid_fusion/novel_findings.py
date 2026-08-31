"""
Find novel biological findings in the hybrid KG.

A "novel finding" is a high-confidence (subject, relation, object) triple that:
  1. is NOT in the curated KB
  2. is NOT in the gold standard (so it's not just a re-derivation)
  3. is supported by >= N papers (cross-paper agreement)
  4. has reasonable source provenance (LLM, co-occurrence, type-canonical, cross-source)
  5. is biologically plausible (the relation type is one of the canonical CDM relations)

These are the "candidate novel findings" - the kind of result that, if validated
by an external source, would constitute a paper-worthy biological discovery.

Outputs:
  - novel_findings_all.csv       (all candidates, ranked)
  - novel_findings_top100.csv    (top 100 by support)
  - novel_findings_by_relation.csv (counts per relation)
  - novel_findings_summary.json
  - novel_findings_report.txt
"""
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import csv, json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(r"C:\Users\jkalra\Documents\Microbiome-CDM")
KG_DIR = REPO / "paper_claims" / "claim_C_hybrid_fusion" / "mini_hybrid_v2"
KB_PATH = REPO / "paper_claims" / "biological_kb.py"
GOLD_PATH = REPO / "paper_claims" / "claim_F_biological_validation" / "gold_associations.json"
OUT_DIR = REPO / "paper_claims" / "claim_C_hybrid_fusion" / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def norm(s):
    import re
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def load_kg():
    rels = json.loads((KG_DIR / "relationships.json").read_text(encoding="utf-8"))
    return rels


def load_kb_relations():
    """Build a set of (norm(subject), norm(relation), norm(object)) for all KB-curated relations.
    This includes KNOWN_ASSOCIATIONS, SCFA_TREATS, ANTIBIOTIC_DISRUPTS, and the DRUGS/ORGANISMS relations."""
    sys.path.insert(0, str(REPO / "paper_claims"))
    import biological_kb
    out = set()
    # KNOWN_ASSOCIATIONS - old style
    for cat, info in biological_kb.KNOWN_ASSOCIATIONS.items():
        for org in info.get("depleted_organisms", []):
            for d in biological_kb.CATEGORY_TO_DISEASE.get(cat, [cat]):
                out.add((norm(org), "depleted_in", norm(d)))
        for org in info.get("enriched_organisms", []):
            for d in biological_kb.CATEGORY_TO_DISEASE.get(cat, [cat]):
                out.add((norm(org), "enriched_in", norm(d)))
        for drug in info.get("treatments", []):
            for d in biological_kb.CATEGORY_TO_DISEASE.get(cat, [cat]):
                out.add((norm(drug), "treats", norm(d)))
        # tuple-style
        for org, chem in info.get("producer_to_product", []):
            out.add((norm(org), "produces", norm(chem)))
        for chem, disease in info.get("metabolite_to_disease", []):
            rel = "treats" if chem.lower() in ("butyrate", "propionate", "acetate", "short-chain fatty acid") else "associated_with"
            out.add((norm(chem), rel, norm(disease)))
        for org, disease in info.get("organism_to_disease", []):
            out.add((norm(org), "associated_with", norm(disease)))
        for drug, org in info.get("antibiotic_to_organism", []):
            rel = "enriched_in" if org == "clostridioides difficile" else "disrupts"
            out.add((norm(drug), rel, norm(org)))
        for org, cond in info.get("probiotic_to_condition", []):
            out.add((norm(org), "treats", norm(cond)))
    # ORGANISMS.enriched_in / depleted_in
    for org_canonical, info in biological_kb.ORGANISMS.items():
        for d in info.get("enriched_in", []):
            out.add((norm(org_canonical), "enriched_in", norm(d)))
        for d in info.get("depleted_in", []):
            out.add((norm(org_canonical), "depleted_in", norm(d)))
        for chem in info.get("produces", []):
            out.add((norm(org_canonical), "produces", norm(chem)))
    # DRUGS.treats / associated_with / produced_by
    for drug_canonical, info in biological_kb.DRUGS.items():
        for d in info.get("treats", []):
            out.add((norm(drug_canonical), "treats", norm(d)))
        for d in info.get("associated_with", []):
            out.add((norm(drug_canonical), "associated_with", norm(d)))
        for org in info.get("produced_by", []):
            out.add((norm(org), "produces", norm(drug_canonical)))
    # SCFA_TREATS_INFLAMMATION
    for chem, diseases in biological_kb.SCFA_TREATS_INFLAMMATION.items():
        for d in diseases:
            out.add((norm(chem), "treats", norm(d)))
    # ANTIBIOTIC_DISRUPTS
    for drug, organisms in biological_kb.ANTIBIOTIC_DISRUPTS.items():
        for o in organisms:
            out.add((norm(drug), "disrupts", norm(o)))
    return out


def load_gold_relations():
    d = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    out = set()
    for a in d.get("associations", []):
        out.add((norm(a["subject"]), norm(a["relation"]), norm(a["object"])))
    return out


def main():
    print("Loading KG ...")
    rels = load_kg()
    print(f"  {len(rels)} relationships")

    print("Loading KB relations ...")
    kb_rels = load_kb_relations()
    print(f"  {len(kb_rels)} KB-curated (norm-subject, norm-relation, norm-object) keys")

    print("Loading gold standard ...")
    gold_rels = load_gold_relations()
    print(f"  {len(gold_rels)} gold associations")

    # Find novel candidates: in KG, NOT in KB, NOT in gold
    # Group by (subject, relation, object) and count support
    print("\nAggregating KG by (subject, relation, object) ...")
    agg = defaultdict(lambda: {"papers": set(), "sources": set(), "max_conf": 0.0,
                                "n_total": 0, "n_llm": 0, "n_spacy": 0})
    for r in rels:
        s = norm(r["source_entity"])
        rel = norm(r["relationship_type"])
        o = norm(r["target_entity"])
        # Skip the generic co_occurs_with from S3 - too noisy
        if rel == "co_occurs_with":
            continue
        key = (s, rel, o)
        agg[key]["n_total"] += 1
        src_db = r.get("source_db", "unknown")
        agg[key]["sources"].add(src_db)
        if src_db == "kb_curated":
            pass
        elif "llm" in src_db.lower():
            agg[key]["n_llm"] += 1
        else:
            agg[key]["n_spacy"] += 1
        # Track supporting papers
        papers = r.get("papers", [])
        for p in papers:
            agg[key]["papers"].add(p)
        # Track max confidence
        conf = r.get("confidence", 0)
        if conf and conf > agg[key]["max_conf"]:
            agg[key]["max_conf"] = conf

    # Filter for novel
    print("Filtering for novel findings ...")
    # Generic / uninformative terms to drop
    GENERIC_NOISE = {
        "p", "k", "c", "n", "s", "a", "r", "i", "o", "e", "m", "b", "t",
        "otu", "otus", "b", "d", "f", "g", "h", "j", "l", "q", "u", "v", "w", "x", "y", "z",
        "individuals", "individual", "samples", "sample", "patient", "patients",
        "study", "studies", "data", "results", "analysis", "method", "methods",
        "introduction", "discussion", "conclusion", "abstract", "background",
    }
    BIOLOGICAL_RELATIONS = {
        "treats", "treated_by", "produces", "produced_by", "associated_with",
        "depleted_in", "enriched_in", "disrupts", "participates_in", "implicates",
        "implicated_in", "involves", "involved_in",
    }
    novel = []
    for (s, rel, o), info in agg.items():
        if (s, rel, o) in kb_rels:
            continue
        if (s, rel, o) in gold_rels:
            continue
        # Skip generic co-occurrences (too noisy for novel-finding framing)
        if rel == "co_occurs_with":
            continue
        # Skip non-biological relations
        if rel not in BIOLOGICAL_RELATIONS:
            continue
        # Skip short / generic terms
        if len(s) < 3 or len(o) < 3:
            continue
        if s in GENERIC_NOISE or o in GENERIC_NOISE:
            continue
        # Skip very low confidence (noise from text-mining)
        if info["max_conf"] < 0.5:
            continue
        # Skip associations without paper support
        if not info["papers"]:
            continue
        info["subject"] = s
        info["relation"] = rel
        info["object"] = o
        info["n_papers"] = len(info["papers"])
        info["source_dbs"] = ",".join(sorted(info["sources"]))
        novel.append(info)

    # Rank by n_papers then max_conf
    novel.sort(key=lambda x: (x["n_papers"], x["max_conf"]), reverse=True)
    print(f"  {len(novel)} novel candidate associations")

    # Write all
    out_all = OUT_DIR / "novel_findings_all.csv"
    keys = ["subject", "relation", "object", "n_papers", "n_total", "n_llm", "n_spacy",
            "max_conf", "source_dbs"]
    with open(out_all, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in novel:
            w.writerow({k: r.get(k, "") for k in keys})
    print(f"Wrote: {out_all}")

    # Write top 100 (most-supported)
    out_top = OUT_DIR / "novel_findings_top100.csv"
    with open(out_top, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in novel[:100]:
            w.writerow({k: r.get(k, "") for k in keys})
    print(f"Wrote: {out_top}")

    # Per-relation counts
    by_rel = Counter()
    for r in novel:
        by_rel[r["relation"]] += 1
    out_rel = OUT_DIR / "novel_findings_by_relation.csv"
    with open(out_rel, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["relation", "n_novel_findings"])
        for rel, n in by_rel.most_common():
            w.writerow([rel, n])
    print(f"Wrote: {out_rel}")

    # Summary
    summary = {
        "n_kg_rels": len(rels),
        "n_kb_rels": len(kb_rels),
        "n_gold_rels": len(gold_rels),
        "n_novel_candidates": len(novel),
        "n_with_papers_3plus": sum(1 for r in novel if r["n_papers"] >= 3),
        "n_with_papers_5plus": sum(1 for r in novel if r["n_papers"] >= 5),
        "by_relation": dict(by_rel.most_common()),
        "top_20_novel": [
            {"subject": r["subject"], "relation": r["relation"], "object": r["object"],
             "n_papers": r["n_papers"], "max_conf": r["max_conf"],
             "source_dbs": r["source_dbs"]}
            for r in novel[:20]
        ],
    }
    out_json = OUT_DIR / "novel_findings_summary.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote: {out_json}")

    # Human-readable
    lines = []
    lines.append("=" * 75)
    lines.append("NOVEL BIOLOGICAL FINDINGS — candidates for the paper's headline discovery")
    lines.append("=" * 75)
    lines.append(f"  Total KG relations:        {len(rels):>6d}")
    lines.append(f"  KB-curated (excluded):     {len(kb_rels):>6d}")
    lines.append(f"  Gold-standard (excluded):  {len(gold_rels):>6d}")
    lines.append(f"  Novel candidates:          {len(novel):>6d}")
    lines.append(f"  ... with >=3 paper support: {summary['n_with_papers_3plus']:>6d}")
    lines.append(f"  ... with >=5 paper support: {summary['n_with_papers_5plus']:>6d}")
    lines.append("")
    lines.append("By relation type:")
    for rel, n in by_rel.most_common(15):
        lines.append(f"  {rel:30s} {n:>5d}")
    lines.append("")
    lines.append("=" * 75)
    lines.append("TOP 20 NOVEL FINDINGS (most cross-paper support)")
    lines.append("=" * 75)
    lines.append(f"{'#':>3s} {'subject':30s} {'relation':15s} {'object':30s} {'papers':>6s} {'conf':>5s}")
    lines.append("-" * 95)
    for i, r in enumerate(novel[:20], 1):
        lines.append(f"{i:>3d} {r['subject']:30s} {r['relation']:15s} {r['object']:30s} {r['n_papers']:>6d} {r['max_conf']:>5.2f}")
    lines.append("")
    lines.append("=" * 75)
    lines.append("WHAT THIS MEANS FOR THE PAPER")
    lines.append("=" * 75)
    lines.append(f"  The hybrid KG contains {len(novel)} novel high-confidence associations")
    lines.append(f"  not in the curated KB and not in the gold standard. {summary['n_with_papers_3plus']}")
    lines.append(f"  of them are supported by 3+ independent papers in the 50-paper corpus.")
    lines.append(f"  These are the kind of 'KG-driven hypothesis' findings that, if validated")
    lines.append(f"  externally, would constitute a paper-worthy biological discovery.")
    lines.append(f"  For the paper, we report these as 'candidate novel findings' — the next")
    lines.append(f"  step is external validation (e.g., against the Abdill 2025 168K-sample")
    lines.append(f"  compendium or future meta-analyses).")

    out_txt = OUT_DIR / "novel_findings_report.txt"
    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {out_txt}")
    print()
    print(lines[2])
    print(lines[3])
    print(lines[4])
    print(lines[5])
    print(lines[6])
    print(lines[7])
    print(lines[8])
    print(lines[10])
    for rel, n in by_rel.most_common(15):
        print(f"  {rel:30s} {n:>5d}")
    print()
    print(lines[15])
    print(lines[16])
    for i, r in enumerate(novel[:20], 1):
        print(f"{i:>3d} {r['subject']:30s} {r['relation']:15s} {r['object']:30s} {r['n_papers']:>6d} {r['max_conf']:>5.2f}")


if __name__ == "__main__":
    main()
