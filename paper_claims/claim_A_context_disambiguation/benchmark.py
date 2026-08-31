#!/usr/bin/env python3
"""
Claim A benchmark — context-dependent entity type disambiguation.

This script runs the LLM pipeline and the spaCy pipeline on a curated set of
ambiguous terms, compares their type classifications against ground truth, and
emits a results table.

Usage (from this folder):
    python benchmark.py
    python benchmark.py --output results/
    python benchmark.py --llm-only         # skip spaCy
    python benchmark.py --spacy-only       # skip LLM

Outputs:
    - results/per_term_accuracy.csv
    - results/confusion_matrix_llm.txt
    - results/confusion_matrix_spacy_<model>.txt
    - prints a LaTeX-ready table fragment to stdout

Optional deps (script degrades gracefully if missing):
    - llm_terms (LLM pipeline)         -> run with --llm-only=False to skip
    - spacy + scispacy models          -> run with --spacy-only=False to skip
    - ollama running locally (qwen3:8b) -> required for LLM

The test set lives in ambiguous_terms.json (35 terms, 14 CDM types).
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
TEST_SET = HERE / "ambiguous_terms.json"


# ---------------------------------------------------------------------------
# Pipeline loaders — guarded so the script can run in pieces.
# ---------------------------------------------------------------------------
def _try_load_llm_pipeline():
    """Load the LLM pipeline from llm_terms/. Returns (run_fn, label) or (None, None)."""
    try:
        llm_root = REPO_ROOT / "llm_terms"
        sys.path.insert(0, str(llm_root))
        from core.pipeline import CDMEntityPipeline  # noqa: F401
        from config.cdm_config import PipelineConfig  # noqa: F401

        pipeline = CDMEntityPipeline(
            model="qwen3:8b",
            config=PipelineConfig(default_model="qwen3:8b"),
        )

        def run(text):
            return pipeline.extract_entities(text)

        return run, "LLM-Qwen3-8B"
    except Exception as exc:
        print(f"  [warn] LLM pipeline not available: {type(exc).__name__}: {str(exc)[:120]}")
        return None, None


def _try_load_spacy_pipeline():
    """Load the spaCy pipeline. Returns list of (run_fn, model_label)."""
    results = []
    try:
        spacy_root = REPO_ROOT / "spacy_terms"
        sys.path.insert(0, str(spacy_root))
        from src.config.settings import get_config
        from src.modules.terms_extractor import create_terms_extractor

        # Try the 4 sciSpaCy models in priority order. Skip ones not installed.
        config = get_config()
        candidate_models = [
            "en_core_sci_lg",
            "en_ner_craft_md",
            "en_ner_bc5cdr_md",
            "en_ner_jnlpba_md",
        ]
        for model_name in candidate_models:
            try:
                cfg = get_config()
                cfg.scispacy.preferred_models = [model_name]
                cfg.scispacy.auto_detect_models = True
                extractor = create_terms_extractor(cfg)
                # Inspect: did it actually load the model?
                available = getattr(extractor, "available_models", None) or []
                if available and model_name in available:
                    def run(text, _ex=extractor):
                        return _ex.extract_from_text(text)
                    results.append((run, f"spaCy-{model_name}"))
                    print(f"  [ok] loaded {model_name}")
            except Exception as exc:
                print(f"  [skip] {model_name}: {type(exc).__name__}: {str(exc)[:80]}")
    except Exception as exc:
        print(f"  [warn] spaCy pipeline not available: {type(exc).__name__}: {str(exc)[:120]}")
    return results


# ---------------------------------------------------------------------------
# Mapping helper: spaCy NER labels are short entity codes (ENTITY, ORGANISM,
# CHEMICAL, DISEASE, ...). LLM returns CDM type strings. We normalize to the
# 14 CDM types and flag unknown labels as UNKNOWN.
# ---------------------------------------------------------------------------
VALID_TYPES = {
    "ORGANISM", "PROTEIN", "CHEMICAL", "DISEASE", "DNA_RNA", "CELL_TYPE",
    "SAMPLE_METHOD", "LAB_METHOD", "DATA_ANALYSIS", "PATHWAY",
    "EXPERIMENTAL_METHOD", "STUDY_DESIGN", "GENOMICS", "CLINICAL", "UNKNOWN",
}

# spaCy NER labels commonly produced. Only the ones likely to fire for our test
# set are listed; everything else is mapped to UNKNOWN.
SPACY_LABEL_MAP = {
    "ORGANISM": "ORGANISM",
    "ORG": "ORGANISM",
    "GPE": "ORGANISM",          # geo-political (in some NERs) — wrong but plausibly mis-fires
    "PERSON": "UNKNOWN",
    "CHEMICAL": "CHEMICAL",
    "DRUG": "CHEMICAL",
    "DISEASE": "DISEASE",
    "GENE": "GENE",             # CDM has GENE; treat as UNKNOWN since the LLM rejects GENE
    "PROTEIN": "PROTEIN",
    "DNA": "DNA_RNA",
    "RNA": "DNA_RNA",
    "CELL": "CELL_TYPE",
    "CELL_TYPE": "CELL_TYPE",
    "METHOD": "DATA_ANALYSIS",
    "TOOL": "DATA_ANALYSIS",
    "ENTITY": "UNKNOWN",        # generic fallback — spaCy 'en_core_sci_lg' uses ENTITY
    "PROCESS": "PATHWAY",
    "PATHWAY": "PATHWAY",
}


def _extract_type_from_entities(entities, term):
    """Given a list of entity dicts from a pipeline, return the type of the
    entity that matches `term` (case-insensitive substring). Returns UNKNOWN if
    no match or no type info."""
    if not entities:
        return "UNKNOWN"
    needle = term.lower()
    # Prefer exact match, then prefix, then substring.
    candidates = []
    for ent in entities:
        text = (ent.get("entity") or ent.get("term") or "").strip()
        etype = (
            ent.get("entity_type")
            or ent.get("categories")
            or ent.get("type")
            or "UNKNOWN"
        )
        etype = etype.upper().strip()
        if not text:
            continue
        t_low = text.lower()
        if t_low == needle:
            candidates.append((0, etype))
        elif t_low.startswith(needle) or needle.startswith(t_low):
            candidates.append((1, etype))
        elif needle in t_low or t_low in needle:
            candidates.append((2, etype))
    if not candidates:
        return "UNKNOWN"
    candidates.sort()
    return candidates[0][1]


def _spacy_to_cdm(entities, term):
    """spaCy entities use NER labels; map them to CDM types."""
    spacy_label = _extract_type_from_entities(entities, term)
    return SPACY_LABEL_MAP.get(spacy_label, spacy_label)


# ---------------------------------------------------------------------------
# Main benchmark loop.
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm-only", action="store_true")
    parser.add_argument("--spacy-only", action="store_true")
    parser.add_argument("--output", default=str(HERE / "results"))
    parser.add_argument("--limit", type=int, default=None, help="run on first N terms only (for quick smoke test)")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(TEST_SET, "r", encoding="utf-8") as f:
        data = json.load(f)
    terms = data["terms"]
    if args.limit:
        terms = terms[: args.limit]

    print(f"Loaded {len(terms)} test terms (of {len(data['terms'])} total)")
    print(f"Output dir: {out_dir}\n")

    # Load pipelines.
    llm_run, llm_label = (None, None) if args.spacy_only else _try_load_llm_pipeline()
    spacy_runs = [] if args.llm_only else _try_load_spacy_pipeline()

    if llm_run:
        print(f"LLM pipeline: {llm_label}")
    else:
        print("LLM pipeline: NOT AVAILABLE (--spacy-only or import failed)")
    if spacy_runs:
        print(f"spaCy pipelines: {[lbl for _, lbl in spacy_runs]}")
    else:
        print("spaCy pipelines: NOT AVAILABLE (--llm-only or import failed)")
    print()

    # Per-term results.
    rows = []
    for entry in terms:
        tid = entry["id"]
        term = entry["term"]
        expected = entry["expected_type"]
        context = entry["example_context"]
        ambiguous = entry.get("ambiguous", False)

        row = {
            "id": tid, "term": term, "expected": expected, "ambiguous": ambiguous,
        }

        if llm_run:
            t0 = time.time()
            try:
                ents = llm_run(context)
                pred = _extract_type_from_entities(ents, term)
                row["llm_type"] = pred
                row["llm_time_s"] = round(time.time() - t0, 2)
                row["llm_correct"] = (pred == expected)
            except Exception as exc:
                row["llm_type"] = f"ERR:{type(exc).__name__}"
                row["llm_time_s"] = round(time.time() - t0, 2)
                row["llm_correct"] = False
        else:
            row["llm_type"] = "N/A"
            row["llm_time_s"] = 0
            row["llm_correct"] = False

        for run_fn, sp_label in spacy_runs:
            col = f"spacy_{sp_label.split('-', 1)[1]}"  # e.g. "spacy_en_core_sci_lg"
            t0 = time.time()
            try:
                ents = run_fn(context)
                pred = _spacy_to_cdm(ents, term)
                row[f"{col}_type"] = pred
                row[f"{col}_time_s"] = round(time.time() - t0, 2)
                row[f"{col}_correct"] = (pred == expected)
            except Exception as exc:
                row[f"{col}_type"] = f"ERR:{type(exc).__name__}"
                row[f"{col}_time_s"] = round(time.time() - t0, 2)
                row[f"{col}_correct"] = False

        rows.append(row)

    # Per-pipeline accuracy.
    pipelines = []
    if llm_run:
        pipelines.append(("LLM", "llm_correct", "llm_type"))
    for _, sp_label in spacy_runs:
        col = f"spacy_{sp_label.split('-', 1)[1]}"
        pipelines.append((sp_label, f"{col}_correct", f"{col}_type"))

    print("=" * 70)
    print("OVERALL ACCURACY (correct type / total terms)")
    print("=" * 70)
    for label, correct_col, _ in pipelines:
        ok = sum(1 for r in rows if r.get(correct_col, False))
        print(f"  {label:30s}: {ok:3d}/{len(rows):3d}  =  {ok/len(rows)*100:5.1f}%")

    print()
    print("=" * 70)
    print("ACCURACY ON AMBIGUOUS SUBSET (the harder cases)")
    print("=" * 70)
    amb_rows = [r for r in rows if r.get("ambiguous")]
    if amb_rows:
        for label, correct_col, _ in pipelines:
            ok = sum(1 for r in amb_rows if r.get(correct_col, False))
            print(f"  {label:30s}: {ok:3d}/{len(amb_rows):3d}  =  {ok/len(amb_rows)*100:5.1f}%")
    else:
        print("  (no ambiguous-marked terms in current set)")

    # Per-type accuracy.
    print()
    print("=" * 70)
    print("PER-EXPECTED-TYPE ACCURACY")
    print("=" * 70)
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["expected"]].append(r)
    for etype in sorted(by_type):
        subset = by_type[etype]
        print(f"  [{etype}]")
        for label, correct_col, _ in pipelines:
            ok = sum(1 for r in subset if r.get(correct_col, False))
            print(f"    {label:28s}: {ok}/{len(subset)} = {ok/len(subset)*100:5.1f}%")

    # Confusion matrices.
    for label, correct_col, type_col in pipelines:
        confusion = Counter()
        for r in rows:
            if r.get(correct_col) is None or not r.get(correct_col):
                confusion[("expected=" + r["expected"], "pred=" + str(r.get(type_col, "?")))] += 1
        path = out_dir / f"confusion_{label.replace(' ', '_').replace('/', '_')}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Confusion matrix for {label}\n")
            f.write("(rows: expected, cols: predicted; counts include both correct and incorrect)\n\n")
            for (e, p), c in sorted(confusion.items()):
                f.write(f"  {e:30s} {p:30s} {c:5d}\n")
        print(f"\nWrote confusion matrix: {path}")

    # CSV.
    csv_path = out_dir / "per_term_accuracy.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        import csv as _csv
        writer = _csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"Wrote per-term CSV: {csv_path}")

    # LaTeX table fragment.
    print()
    print("=" * 70)
    print("LATEX TABLE FRAGMENT (paste into paper)")
    print("=" * 70)
    spacy_cols = [lbl for lbl, _, _ in pipelines if lbl != "LLM"]
    cols = " & ".join(["term", "expected"] + [lbl.replace(" ", "\\_") for lbl, _, _ in pipelines])
    print(f"\\begin{{tabular}}{{l{'l' * (2 + len(pipelines))}}}")
    print(f"\\toprule")
    print(f"{cols} \\\\")
    print(f"\\midrule")
    for r in rows:
        cells = [r["term"], r["expected"]]
        for label, correct_col, type_col in pipelines:
            mark = "\\cmark" if r.get(correct_col) else "\\xmark"
            cells.append(f"{r.get(type_col, '?')} {mark}")
        print(" & ".join(cells) + " \\\\")
    print(f"\\bottomrule")
    print(f"\\end{{tabular}}")

    # Verdict.
    print()
    print("=" * 70)
    print("VERDICT (informational; you decide the threshold)")
    print("=" * 70)
    if llm_run and spacy_runs:
        llm_acc = sum(1 for r in rows if r.get("llm_correct")) / len(rows)
        sp_accs = [
            sum(1 for r in rows if r.get(f"spacy_{lbl.split('-', 1)[1]}_correct")) / len(rows)
            for _, lbl in spacy_runs
        ]
        best_sp = max(sp_accs) if sp_accs else 0
        delta = (llm_acc - best_sp) * 100
        print(f"  LLM overall accuracy:                {llm_acc*100:5.1f}%")
        print(f"  Best spaCy model overall accuracy:   {best_sp*100:5.1f}%")
        print(f"  Δ (LLM − best spaCy):                {delta:+5.1f} pp")
        if delta >= 15:
            print("  → Claim A is strongly supported (Δ ≥ 15 percentage points).")
        elif delta >= 5:
            print("  → Claim A is weakly supported (Δ 5-15 pp). Consider scoping claim.")
        else:
            print("  → Claim A is NOT supported (Δ < 5 pp). Rephrase or drop.")

        if amb_rows:
            llm_amb = sum(1 for r in amb_rows if r.get("llm_correct")) / len(amb_rows)
            sp_amb = max(
                sum(1 for r in amb_rows if r.get(f"spacy_{lbl.split('-', 1)[1]}_correct")) / len(amb_rows)
                for _, lbl in spacy_runs
            ) if spacy_runs else 0
            print(f"\n  On ambiguous subset only:")
            print(f"  LLM accuracy:                       {llm_amb*100:5.1f}%")
            print(f"  Best spaCy accuracy:                {sp_amb*100:5.1f}%")
            print(f"  Δ:                                  {(llm_amb-sp_amb)*100:+5.1f} pp")
    else:
        print("  (need both LLM and spaCy pipelines available to compute verdict)")


if __name__ == "__main__":
    main()
