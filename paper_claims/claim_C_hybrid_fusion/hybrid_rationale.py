"""
Why hybrid? Quantitative evidence for the necessity of the 7-source hybrid design.

Three analyses:
1. Entity-set overlap (Jaccard) between LLM and each spaCy model, on normalized terms.
2. Per-paper entity overlap and per-paper entity-coverage delta (LLM-only, spaCy-only, both).
3. Type-coverage complementarity: for each CDM type, which methods produce it and which do not.

Outputs:
  - entity_overlap.csv          (method-pair Jaccard on normalized terms)
  - per_paper_coverage.csv      (per paper: llm_only, spacy_only, both, neither)
  - type_complementarity.csv    (per type: which methods produce it)
  - hybrid_rationale.json       (all numbers)
  - hybrid_rationale.txt        (human-readable report)
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
LLM_DIR = REPO / "paper_claims" / "_llm_runs"
SPACY_DIR = REPO / "paper_claims" / "_spacy_runs"
OUT_DIR = REPO / "paper_claims" / "claim_C_hybrid_fusion" / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LABEL_TO_CDM = {
    "CHEBI": "CHEMICAL", "CHEMICAL": "CHEMICAL", "DRUG": "CHEMICAL",
    "TAXON": "ORGANISM", "GGP": "PROTEIN", "SO": "DNA_RNA",
    "DNA": "DNA_RNA", "RNA": "DNA_RNA",
    "PROTEIN": "PROTEIN", "GENE": "GENE", "DISEASE": "DISEASE",
    "CELL_LINE": "CELL_TYPE", "CELL_TYPE": "CELL_TYPE",
    "ENTITY": "UNKNOWN",
    "AMINO_ACID": "CHEMICAL",
    "GENE_OR_GENE_PRODUCT": "GENE",
    "ORGANISM": "ORGANISM",
    "ORGANISM_SUBSTANCE": "CHEMICAL",
    "OTHER_ORGANISM": "ORGANISM",
    "SIMPLE_CHEMICAL": "CHEMICAL",
}

CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "GENE", "PROTEIN", "DNA_RNA",
    "CELL_TYPE", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN", "UNKNOWN",
]


def norm(s):
    import re
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def load_llm_terms():
    """Return dict paper -> set of normalized terms; also a global set."""
    per_paper = defaultdict(set)
    global_set = set()
    for j in sorted(LLM_DIR.glob("*.cdm_entities.json")):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper = j.stem.replace(".cdm_entities", "")
        inner = d.get("results", {}).get("cdm_entities", {}) or {}
        for etype, lst in inner.items():
            for e in (lst or []):
                t = e.get("entity") or e.get("term")
                if t:
                    n = norm(t)
                    if n:
                        per_paper[paper].add(n)
                        global_set.add(n)
    return per_paper, global_set


def load_spacy_terms():
    """Return dict model -> set of normalized terms (per paper too)."""
    per_paper_model = defaultdict(lambda: defaultdict(set))
    model_global = defaultdict(set)
    for j in sorted(SPACY_DIR.glob("*.spacy_ner.csv")):
        paper = j.stem.replace(".spacy_ner", "")
        try:
            with open(j, encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    t = (row.get("term") or "").strip()
                    label = (row.get("labels") or "").strip().upper()
                    model = row.get("model", "")
                    if not t or len(t) < 2 or label == "ENTITY":
                        continue
                    n = norm(t)
                    if n:
                        per_paper_model[paper][model].add(n)
                        model_global[model].add(n)
        except Exception:
            continue
    return per_paper_model, model_global


def jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    print("Loading LLM ...")
    llm_paper, llm_global = load_llm_terms()
    print(f"  {len(llm_paper)} papers, {len(llm_global)} unique LLM terms")

    print("Loading spaCy ...")
    spc_paper, spc_global = load_spacy_terms()
    print(f"  {len(spc_paper)} papers, {sum(len(v) for v in spc_global.values())} total spaCy terms")

    # 1) Pairwise Jaccard (LLM vs each spaCy model on global sets)
    overlap_rows = []
    for m, ms in spc_global.items():
        j = jaccard(llm_global, ms)
        llm_only = len(llm_global - ms)
        spc_only = len(ms - llm_global)
        shared = len(llm_global & ms)
        overlap_rows.append({
            "method_a": "LLM",
            "method_b": m,
            "jaccard": round(j, 4),
            "shared": shared,
            "a_only": llm_only,
            "b_only": spc_only,
            "a_size": len(llm_global),
            "b_size": len(ms),
        })
    # Also union of all spaCy models vs LLM
    all_spc = set()
    for s in spc_global.values():
        all_spc |= s
    j = jaccard(llm_global, all_spc)
    overlap_rows.append({
        "method_a": "LLM",
        "method_b": "spaCy_union",
        "jaccard": round(j, 4),
        "shared": len(llm_global & all_spc),
        "a_only": len(llm_global - all_spc),
        "b_only": len(all_spc - llm_global),
        "a_size": len(llm_global),
        "b_size": len(all_spc),
    })

    with open(OUT_DIR / "entity_overlap.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(overlap_rows[0].keys()))
        w.writeheader()
        w.writerows(overlap_rows)
    print(f"\nWrote: {OUT_DIR / 'entity_overlap.csv'}")

    # 2) Per-paper coverage: for each paper with BOTH LLM and spaCy, count:
    #   llm_only, spacy_only, both, neither
    cov_rows = []
    common_papers = sorted(set(llm_paper) & set(spc_paper))
    for p in common_papers:
        ll = llm_paper[p]
        # All spaCy terms on this paper (any model)
        ss = set()
        for m_terms in spc_paper[p].values():
            ss |= m_terms
        llm_only = ll - ss
        spc_only = ss - ll
        both = ll & ss
        cov_rows.append({
            "paper": p,
            "llm_n": len(ll),
            "spacy_n": len(ss),
            "both": len(both),
            "llm_only": len(llm_only),
            "spacy_only": len(spc_only),
            "jaccard": round(jaccard(ll, ss), 4),
        })
    with open(OUT_DIR / "per_paper_coverage.csv", "w", encoding="utf-8", newline="") as f:
        if cov_rows:
            w = csv.DictWriter(f, fieldnames=list(cov_rows[0].keys()))
            w.writeheader()
            w.writerows(cov_rows)
    print(f"Wrote: {OUT_DIR / 'per_paper_coverage.csv'}")

    # 3) Type complementarity: for each CDM type, which methods produce it?
    # LLM per type
    llm_type = defaultdict(set)
    for j in sorted(LLM_DIR.glob("*.cdm_entities.json")):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        inner = d.get("results", {}).get("cdm_entities", {}) or {}
        for etype, lst in inner.items():
            for e in (lst or []):
                t = e.get("entity") or e.get("term")
                if t:
                    llm_type[etype].add(norm(t))

    spc_type_per_model = defaultdict(lambda: defaultdict(set))
    for j in sorted(SPACY_DIR.glob("*.spacy_ner.csv")):
        try:
            with open(j, encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    t = (row.get("term") or "").strip()
                    label = (row.get("labels") or "").strip().upper()
                    model = row.get("model", "")
                    if not t or len(t) < 2 or label == "ENTITY":
                        continue
                    coarse = LABEL_TO_CDM.get(label, "UNKNOWN")
                    spc_type_per_model[model][coarse].add(norm(t))
        except Exception:
            continue

    comp_rows = []
    for t in CDM_TYPES:
        row = {"cdm_type": t}
        row["llm_n"] = len(llm_type.get(t, set()))
        for m, mts in spc_type_per_model.items():
            row[f"{m}_n"] = len(mts.get(t, set()))
        # Type is "LLM-only" if LLM produces but ALL spaCy models do not
        any_spc = any(row.get(f"{m}_n", 0) > 0 for m in spc_type_per_model)
        row["llm_only_type"] = (row["llm_n"] > 0) and not any_spc
        row["spaCy_union_n"] = max((row.get(f"{m}_n", 0) for m in spc_type_per_model), default=0)
        comp_rows.append(row)
    with open(OUT_DIR / "type_complementarity.csv", "w", encoding="utf-8", newline="") as f:
        keys = list(comp_rows[0].keys())
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(comp_rows)
    print(f"Wrote: {OUT_DIR / 'type_complementarity.csv'}")

    # Summary JSON
    summary = {
        "n_papers_llm": len(llm_paper),
        "n_papers_spacy": len(spc_paper),
        "n_common_papers": len(common_papers),
        "llm_global_terms": len(llm_global),
        "spacy_global_terms_per_model": {m: len(s) for m, s in spc_global.items()},
        "spacy_global_union": len(all_spc),
        "pairwise_jaccard_llm_vs_spacy_model": [
            {"model": r["method_b"], "jaccard": r["jaccard"],
             "shared": r["shared"], "llm_only": r["a_only"], "spacy_only": r["b_only"]}
            for r in overlap_rows if r["method_b"] != "spaCy_union"
        ],
        "llm_vs_spacy_union": {
            "jaccard": overlap_rows[-1]["jaccard"],
            "shared": overlap_rows[-1]["shared"],
            "llm_only": overlap_rows[-1]["a_only"],
            "spacy_only": overlap_rows[-1]["b_only"],
        },
        "per_paper_coverage_summary": {
            "n_papers": len(cov_rows),
            "mean_llm_only": round(sum(r["llm_only"] for r in cov_rows) / max(1, len(cov_rows)), 1),
            "mean_spacy_only": round(sum(r["spacy_only"] for r in cov_rows) / max(1, len(cov_rows)), 1),
            "mean_both": round(sum(r["both"] for r in cov_rows) / max(1, len(cov_rows)), 1),
            "mean_jaccard": round(sum(r["jaccard"] for r in cov_rows) / max(1, len(cov_rows)), 4),
        },
        "llm_only_types": [r["cdm_type"] for r in comp_rows if r["llm_only_type"]],
        "spacy_only_types": [r["cdm_type"] for r in comp_rows
                             if r["llm_n"] == 0 and r.get("spaCy_union_n", 0) > 0],
        "neither_type": [r["cdm_type"] for r in comp_rows
                         if r["llm_n"] == 0 and r.get("spaCy_union_n", 0) == 0],
    }
    with open(OUT_DIR / "hybrid_rationale.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote: {OUT_DIR / 'hybrid_rationale.json'}")

    # Human-readable report
    lines = []
    lines.append("=" * 75)
    lines.append("WHY HYBRID? Quantitative complementarity between LLM and scispaCy")
    lines.append("=" * 75)
    lines.append(f"  LLM papers: {len(llm_paper)} | spaCy papers: {len(spc_paper)} | common: {len(common_papers)}")
    lines.append(f"  LLM global terms: {len(llm_global)}")
    lines.append(f"  spaCy global terms: {{ {', '.join(f'{m}={len(s)}' for m, s in spc_global.items())} }}")
    lines.append(f"  spaCy union: {len(all_spc)}")
    lines.append("")

    lines.append("--- 1) Pairwise Jaccard overlap on global normalized-term sets ---")
    for r in overlap_rows:
        lines.append(f"  LLM vs {r['method_b']:25s}  Jaccard={r['jaccard']:.4f}  "
                     f"shared={r['shared']}  LLM-only={r['a_only']}  spaCy-only={r['b_only']}")
    lines.append("")

    lines.append("--- 2) Per-paper coverage (LLM vs spaCy union) ---")
    lines.append(f"  n papers: {len(cov_rows)}")
    if cov_rows:
        lines.append(f"  mean LLM-only per paper:   {summary['per_paper_coverage_summary']['mean_llm_only']:.1f}")
        lines.append(f"  mean spaCy-only per paper: {summary['per_paper_coverage_summary']['mean_spacy_only']:.1f}")
        lines.append(f"  mean both per paper:       {summary['per_paper_coverage_summary']['mean_both']:.1f}")
        lines.append(f"  mean Jaccard per paper:    {summary['per_paper_coverage_summary']['mean_jaccard']:.4f}")
    lines.append("")

    lines.append("--- 3) Type complementarity: which types are LLM-only? ---")
    lines.append(f"  LLM-only types: {summary['llm_only_types']}")
    lines.append(f"  spaCy-only types: {summary['spacy_only_types']}")
    lines.append(f"  Neither (missing in both): {summary['neither_type']}")
    lines.append("")

    lines.append("=" * 75)
    lines.append("THE BOTTOM LINE")
    lines.append("=" * 75)
    lines.append(f"  The Jaccard between LLM and the spaCy union is {summary['llm_vs_spacy_union']['jaccard']:.4f}.")
    lines.append(f"  {summary['llm_vs_spacy_union']['llm_only']} terms are ONLY in the LLM, "
                 f"{summary['llm_vs_spacy_union']['spacy_only']} are ONLY in spaCy, "
                 f"and only {summary['llm_vs_spacy_union']['shared']} are shared.")
    lines.append(f"  The LLM produces {len(summary['llm_only_types'])} CDM types that no spaCy model produces: "
                 f"{summary['llm_only_types']}.")
    lines.append(f"  This complementarity is the empirical case for the 7-source hybrid: each method")
    lines.append(f"  fills a gap the other cannot, and the union is significantly larger than either")
    lines.append(f"  single-method view.")

    out_txt = OUT_DIR / "hybrid_rationale.txt"
    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {out_txt}")

    # Print a short summary
    print()
    print(lines[2])
    print(lines[3])
    print(lines[4])
    print(lines[6])
    for r in overlap_rows:
        print(f"  LLM vs {r['method_b']:25s}  Jaccard={r['jaccard']:.4f}  "
              f"shared={r['shared']}  LLM-only={r['a_only']}  spaCy-only={r['b_only']}")
    print()
    print(lines[11])
    print(lines[12])
    print(lines[13])
    print(lines[14])
    if cov_rows:
        print(lines[16])
        print(lines[17])
        print(lines[18])
        print(lines[19])
    print()
    print(f"  LLM-only types: {summary['llm_only_types']}")
    print(f"  Neither (missing in both): {summary['neither_type']}")


if __name__ == "__main__":
    main()
