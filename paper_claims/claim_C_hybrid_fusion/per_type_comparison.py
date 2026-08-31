"""
Per-CDM-type comparison: scispaCy (4 models) vs LLM.

For each CDM entity type, compute:
- n entities produced by each method (per paper and total)
- n unique terms
- mean confidence (LLM only)
- method coverage (does ANY method produce this type?)

Outputs:
  - per_type_counts.csv          (type x method: n_entities, n_unique_terms)
  - per_type_per_paper.csv       (paper x type x method)
  - per_type_summary.json
  - per_type_report.txt          (human-readable)
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

# Map scispaCy fine-grained labels to CDM coarse types
LABEL_TO_CDM = {
    "CHEBI": "CHEMICAL", "CHEMICAL": "CHEMICAL", "DRUG": "CHEMICAL",
    "TAXON": "ORGANISM", "GGP": "PROTEIN", "SO": "DNA_RNA",
    "DNA": "DNA_RNA", "RNA": "DNA_RNA",
    "PROTEIN": "PROTEIN", "GENE": "GENE", "DISEASE": "DISEASE",
    "CELL_LINE": "CELL_TYPE", "CELL_TYPE": "CELL_TYPE",
    "ENTITY": "UNKNOWN",
    # bionlp13cg variants
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


def load_llm():
    """Return per-paper, per-type counts and per-type mean confidence."""
    per_paper_type = defaultdict(lambda: Counter())
    type_to_terms = defaultdict(set)
    type_conf = defaultdict(list)
    for j in sorted(LLM_DIR.glob("*.cdm_entities.json")):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper = j.stem.replace(".cdm_entities", "")
        inner = d.get("results", {}).get("cdm_entities", {}) or {}
        for etype, lst in inner.items():
            for e in (lst or []):
                term = e.get("entity") or e.get("term")
                if not term:
                    continue
                per_paper_type[paper][etype] += 1
                type_to_terms[etype].add(term.strip().lower())
                conf = e.get("confidence")
                if conf is not None:
                    type_conf[etype].append(float(conf))
    return per_paper_type, type_to_terms, type_conf


def load_spacy():
    """Return per-paper, per-model, per-coarse-type counts and per-type term sets."""
    per_paper_model_type = defaultdict(lambda: defaultdict(lambda: Counter()))
    type_to_terms_per_model = defaultdict(lambda: defaultdict(set))
    for j in sorted(SPACY_DIR.glob("*.spacy_ner.csv")):
        paper = j.stem.replace(".spacy_ner", "")
        try:
            with open(j, encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    term = (row.get("term") or "").strip()
                    label = (row.get("labels") or "").strip().upper()
                    model = row.get("model", "")
                    if not term or len(term) < 2 or label == "ENTITY":
                        continue
                    coarse = LABEL_TO_CDM.get(label, "UNKNOWN")
                    per_paper_model_type[paper][model][coarse] += 1
                    type_to_terms_per_model[model][coarse].add(term.lower())
        except Exception:
            continue
    return per_paper_model_type, type_to_terms_per_model


def main():
    print("Loading LLM JSONs ...")
    llm_per_paper, llm_terms, llm_conf = load_llm()
    print(f"  {len(llm_per_paper)} papers, {sum(sum(c.values()) for c in llm_per_paper.values())} LLM entity records")

    print("Loading spaCy CSVs ...")
    spc_per_paper, spc_terms = load_spacy()
    print(f"  {len(spc_per_paper)} papers, {sum(sum(sum(c.values()) for c in mm.values()) for mm in spc_per_paper.values())} spaCy entity rows")

    # ---- Per-type counts: LLM vs each spaCy model vs union
    rows = []
    summary = {}
    for t in CDM_TYPES:
        llm_n = sum(c.get(t, 0) for c in llm_per_paper.values())
        llm_u = len(llm_terms.get(t, set()))
        llm_c = round(sum(llm_conf.get(t, [])) / max(1, len(llm_conf.get(t, []))), 3) if llm_conf.get(t) else 0.0
        per_model = {}
        for m, tt in spc_terms.items():
            n = 0
            for paper, mm in spc_per_paper.items():
                model_data = mm.get(m, {})
                # Defensive: only sum if it's a Counter-like (dict)
                if hasattr(model_data, "get"):
                    n += model_data.get(t, 0)
            u = len(tt.get(t, set()))
            per_model[m] = {"n": n, "unique": u}
        rows.append({
            "cdm_type": t,
            "llm_n": llm_n, "llm_unique": llm_u, "llm_mean_conf": llm_c,
            **{f"{m}_n": v["n"] for m, v in per_model.items()},
            **{f"{m}_unique": v["unique"] for m, v in per_model.items()},
        })
        summary[t] = {"llm": {"n": llm_n, "unique": llm_u, "mean_conf": llm_c},
                      "spacy": per_model}

    # Write per_type_counts.csv
    out_csv = OUT_DIR / "per_type_counts.csv"
    if rows:
        keys = list(rows[0].keys())
    else:
        keys = ["cdm_type", "llm_n", "llm_unique", "llm_mean_conf"]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            # Ensure all keys present
            for k in keys:
                r.setdefault(k, 0)
            w.writerow(r)
    print(f"\nWrote: {out_csv}")

    # Write summary.json
    out_json = OUT_DIR / "per_type_summary.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote: {out_json}")

    # Per-paper per-type matrix
    per_paper_rows = []
    for paper in sorted(set(llm_per_paper) | set(spc_per_paper)):
        for t in CDM_TYPES:
            llm_n = llm_per_paper.get(paper, Counter()).get(t, 0)
            spc_per_model = {m: spc_per_paper.get(paper, {}).get(m, Counter()).get(t, 0)
                             for m in spc_terms}
            per_paper_rows.append({"paper": paper, "cdm_type": t, "llm": llm_n, **spc_per_model})
    out_pp = OUT_DIR / "per_type_per_paper.csv"
    with open(out_pp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_paper_rows[0].keys()))
        w.writeheader()
        w.writerows(per_paper_rows)
    print(f"Wrote: {out_pp}")

    # Human-readable report
    lines = []
    lines.append("=" * 75)
    lines.append("PER-CDM-TYPE COMPARISON: scispaCy (4 models) vs LLM (qwen3.5:9b)")
    lines.append("=" * 75)
    lines.append(f"  LLM papers: {len(llm_per_paper)} | spaCy papers: {len(spc_per_paper)}")
    lines.append("")
    spa_models = list(spc_terms.keys())
    header_cols = "  ".join(f"{m.split('_')[-1] if 'en_core_sci_lg' in m else m.replace('en_ner_','').replace('_md',''):>9s}" for m in spa_models)
    lines.append(f"{'CDM type':22s} {'LLM n':>7s} {'LLM u':>6s} {'conf':>5s} | {header_cols}")
    lines.append("-" * 95)
    for r in rows:
        spc_cols = "  ".join(f"{r.get(f'{m}_n', 0):>9d}" for m in spa_models)
        lines.append(
            f"{r['cdm_type']:22s} {r['llm_n']:>7d} {r['llm_unique']:>6d} {r['llm_mean_conf']:>5.2f} | {spc_cols}"
        )

    lines.append("")
    lines.append("=" * 75)
    lines.append("METHOD COVERAGE (does ANY method produce this type?)")
    lines.append("=" * 75)
    for r in rows:
        any_method = (r["llm_n"] > 0 or any(r.get(f"{m}_n", 0) > 0 for m in spa_models))
        marker = "✓" if any_method else "✗"
        llm_str = f"LLM={r['llm_n']:>5d}"
        spc_str = "  ".join(f"{m.split('_')[-1] if 'en_core_sci_lg' in m else m.replace('en_ner_','').replace('_md','')}={r.get(f'{m}_n', 0):>5d}" for m in spa_models)
        lines.append(f"  {marker} {r['cdm_type']:22s}  {llm_str}  {spc_str}")

    out_txt = OUT_DIR / "per_type_report.txt"
    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {out_txt}")

    # Print a short summary to stdout
    print()
    if len(lines) > 4:
        print(lines[3])
        print(lines[4])
        for r in rows[:8]:
            spc_cols = "  ".join(f"{r.get(f'{m}_n', 0):>9d}" for m in spa_models)
            print(
                f"  {r['cdm_type']:22s} {r['llm_n']:>7d} {r['llm_unique']:>6d} {r['llm_mean_conf']:>5.2f} | {spc_cols}"
            )


if __name__ == "__main__":
    main()
