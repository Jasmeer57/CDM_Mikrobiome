"""External NER benchmark: evaluate NER models on BC5CDR and BioRED test sets.

Computes entity-level precision, recall, F1 (exact span match and relaxed/overlap
match) per entity type and overall, for each model × dataset combination.

Uses the same model classes from :mod:`cdm_pipeline.ner.registry` as the
production pipeline — no duplicated model code.

Usage:
    python -m cdm_pipeline.ner.benchmark --models all --datasets bc5cdr biored
    python -m cdm_pipeline.ner.benchmark --models gliner gliner_biomed pubmedbert
"""
import sys
import io
import os
import json
import time
import argparse
import warnings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARK_DIR = REPO_ROOT / "paper" / "_multi_ner_runs" / "benchmarks"
BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

# ── BioRED data path (staged in repo for SLURM access) ──
BIORED_DIR = BENCHMARK_DIR / "biored_data"

# ── BC5CDR data path (cached via HuggingFace) ──
BC5CDR_DIR = Path(os.path.expanduser(
    "~/.cache/huggingface/hub/datasets--tner--bc5cdr/snapshots/"
    "f68cdc7db924369241e7868656f583072acd4e90/dataset"
))

# ── Type mappings from benchmark types to CDM types ──
BC5CDR_TYPE_MAP = {
    "Chemical": "CHEMICAL",
    "Disease": "DISEASE",
}

BIORED_TYPE_MAP = {
    "GeneOrGeneProduct": "PROTEIN",
    "DiseaseOrPhenotypicFeature": "DISEASE",
    "ChemicalEntity": "CHEMICAL",
    "OrganismTaxon": "ORGANISM",
    "CellLine": "CELL_TYPE",
    "SequenceVariant": "DNA_RNA",
}

# ── CDM types for GLiNER (zero-shot prompt labels) ──
CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]


# ═══════════════════════════════════════════════════════════════
#  Data loaders
# ═══════════════════════════════════════════════════════════════

def load_bc5cdr_test():
    """Load BC5CDR test set. Returns list of (doc_id, text, gold_entities).

    gold_entities: list of (start, end, cdm_type, surface_text)
    """
    import json as _json
    test_path = BC5CDR_DIR / "test.json"
    with open(test_path) as f:
        data = [_json.loads(line) for line in f]

    label_map = _json.load(open(BC5CDR_DIR / "label.json"))
    rev_labels = {v: k for k, v in label_map.items()}

    docs = []
    for idx, doc in enumerate(data):
        tokens = doc["tokens"]
        tags = doc["tags"]

        text_parts = []
        offsets = []
        pos = 0
        for tok in tokens:
            offsets.append((pos, pos + len(tok)))
            text_parts.append(tok)
            pos += len(tok) + 1
        text = " ".join(text_parts)

        gold = []
        i = 0
        while i < len(tags):
            tag = rev_labels[tags[i]]
            if tag.startswith("B-"):
                etype = tag[2:]
                start = offsets[i][0]
                end = offsets[i][1]
                j = i + 1
                while j < len(tags) and rev_labels[tags[j]].startswith("I-"):
                    etype_i = rev_labels[tags[j]][2:]
                    if etype_i == etype:
                        end = offsets[j][1]
                        j += 1
                    else:
                        break
                cdm_type = BC5CDR_TYPE_MAP.get(etype, etype.upper())
                gold.append((start, end, cdm_type, text[start:end]))
                i = j
            else:
                i += 1
        docs.append((str(idx), text, gold))
    return docs


def load_biored_test():
    """Load BioRED test set (PubTator format). Returns list of (doc_id, text, gold_entities)."""
    test_path = BIORED_DIR / "Test.PubTator"
    if not test_path.exists():
        raise FileNotFoundError(f"BioRED test file not found at {test_path}")

    docs = []
    current_id = None
    title = ""
    abstract = ""
    annotations = []

    with open(test_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                if current_id:
                    full_text = title + " " + abstract
                    docs.append((current_id, full_text, annotations))
                    current_id = None
                    title = ""
                    abstract = ""
                    annotations = []
                continue
            if "|t|" in stripped:
                parts = stripped.split("|t|", 1)
                current_id = parts[0]
                title = parts[1]
                annotations = []
            elif "|a|" in stripped:
                abstract = stripped.split("|a|", 1)[1]
            elif current_id and "\t" in stripped:
                parts = stripped.split("\t")
                if len(parts) >= 6:
                    start = int(parts[1])
                    end = int(parts[2])
                    mention = parts[3]
                    etype = parts[4]
                    cdm_type = BIORED_TYPE_MAP.get(etype, etype)
                    annotations.append((start, end, cdm_type, mention))

    if current_id:
        full_text = title + " " + abstract
        docs.append((current_id, full_text, annotations))

    return docs


# ═══════════════════════════════════════════════════════════════
#  Evaluation
# ═══════════════════════════════════════════════════════════════

def evaluate(gold_docs, pred_docs, eval_types=None):
    """Compute entity-level P/R/F1.

    Args:
        gold_docs: list of (doc_id, text, gold_entities)
        pred_docs: list of (doc_id, predictions)
        eval_types: set of CDM types to evaluate (None = all)

    Returns:
        dict with per-type and overall metrics (exact + relaxed match)
    """
    gold_map = defaultdict(list)
    pred_map = defaultdict(list)

    for doc_id, text, gold in gold_docs:
        for start, end, etype, mention in gold:
            if eval_types is None or etype in eval_types:
                gold_map[doc_id].append((start, end, etype, mention))

    for doc_id, preds in pred_docs:
        for p in preds:
            if eval_types is None or p["label"] in eval_types:
                pred_map[doc_id].append((p["start"], p["end"], p["label"], p["text"]))

    tp_exact = defaultdict(int)
    fp_exact = defaultdict(int)
    fn_exact = defaultdict(int)
    tp_relax = defaultdict(int)
    fp_relax = defaultdict(int)
    fn_relax = defaultdict(int)

    all_doc_ids = set(gold_map.keys()) | set(pred_map.keys())
    for doc_id in all_doc_ids:
        g = gold_map.get(doc_id, [])
        p = pred_map.get(doc_id, [])

        g_set = set((s, e, t) for s, e, t, m in g)
        p_set = set((s, e, t) for s, e, t, m in p)
        for item in g_set & p_set:
            tp_exact[item[2]] += 1
        for item in p_set - g_set:
            fp_exact[item[2]] += 1
        for item in g_set - p_set:
            fn_exact[item[2]] += 1

        matched_g = set()
        matched_p = set()
        for pi, (ps, pe, pt, pm) in enumerate(p):
            if pi in matched_p:
                continue
            for gi, (gs, ge, gt, gm) in enumerate(g):
                if gi in matched_g:
                    continue
                if pt == gt and ps < ge and pe > gs:
                    tp_relax[pt] += 1
                    matched_g.add(gi)
                    matched_p.add(pi)
                    break
        for pi, (ps, pe, pt, pm) in enumerate(p):
            if pi not in matched_p:
                fp_relax[pt] += 1
        for gi, (gs, ge, gt, gm) in enumerate(g):
            if gi not in matched_g:
                fn_relax[gt] += 1

    def prf(tp, fp, fn):
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        return p, r, f

    results = {"per_type": {}, "overall": {}}
    all_types = set(tp_exact.keys()) | set(fp_exact.keys()) | set(fn_exact.keys())

    total_tp_e, total_fp_e, total_fn_e = 0, 0, 0
    total_tp_r, total_fp_r, total_fn_r = 0, 0, 0

    for t in sorted(all_types):
        p_e, r_e, f_e = prf(tp_exact[t], fp_exact[t], fn_exact[t])
        p_r, r_r, f_r = prf(tp_relax[t], fp_relax[t], fn_relax[t])
        results["per_type"][t] = {
            "exact": {"P": p_e, "R": r_e, "F1": f_e,
                      "tp": tp_exact[t], "fp": fp_exact[t], "fn": fn_exact[t]},
            "relaxed": {"P": p_r, "R": r_r, "F1": f_r,
                        "tp": tp_relax[t], "fp": fp_relax[t], "fn": fn_relax[t]},
        }
        total_tp_e += tp_exact[t]; total_fp_e += fp_exact[t]; total_fn_e += fn_exact[t]
        total_tp_r += tp_relax[t]; total_fp_r += fp_relax[t]; total_fn_r += fn_relax[t]

    p_e, r_e, f_e = prf(total_tp_e, total_fp_e, total_fn_e)
    p_r, r_r, f_r = prf(total_tp_r, total_fp_r, total_fn_r)
    results["overall"]["exact"] = {"P": p_e, "R": r_e, "F1": f_e,
                                   "tp": total_tp_e, "fp": total_fp_e, "fn": total_fn_e}
    results["overall"]["relaxed"] = {"P": p_r, "R": r_r, "F1": f_r,
                                     "tp": total_tp_r, "fp": total_fp_r, "fn": total_fn_r}
    return results


# ═══════════════════════════════════════════════════════════════
#  Benchmark model configs
# ═══════════════════════════════════════════════════════════════
# Maps benchmark model keys to (registry_key, eval_types)
# eval_types: which CDM types this model can produce (used for evaluation filtering)

from .registry import MODEL_REGISTRY, get_model

BENCH_MODELS = {
    "gliner":           {"registry_key": "gliner",           "types": {"CHEMICAL", "DISEASE", "ORGANISM", "PROTEIN", "DNA_RNA", "CELL_TYPE"}},
    "gliner_biomed":    {"registry_key": "gliner_biomed",    "types": {"CHEMICAL", "DISEASE", "ORGANISM", "PROTEIN", "DNA_RNA", "CELL_TYPE"}},
    "pubmedbert":       {"registry_key": "pubmedbert",       "types": {"DISEASE"}},
    "scispacy_bc5cdr":  {"registry_key": "scispacy_bc5cdr",  "types": {"CHEMICAL", "DISEASE"}},
    "scispacy_craft":   {"registry_key": "scispacy_craft",   "types": {"PROTEIN", "DNA_RNA", "ORGANISM", "CHEMICAL", "CELL_TYPE"}},
    "scispacy_jnlpba":  {"registry_key": "scispacy_jnlpba",  "types": {"PROTEIN", "DNA_RNA", "CELL_TYPE"}},
    "scispacy_lg":      {"registry_key": "scispacy",         "types": None},
}

DATASET_REGISTRY = {
    "bc5cdr": {"loader": load_bc5cdr_test, "types": {"CHEMICAL", "DISEASE"}},
    "biored": {"loader": load_biored_test, "types": {"PROTEIN", "DISEASE", "CHEMICAL", "ORGANISM", "CELL_TYPE", "DNA_RNA"}},
}


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="External NER benchmark")
    parser.add_argument("--models", nargs="+", default=["all"],
                        choices=list(BENCH_MODELS.keys()) + ["all"])
    parser.add_argument("--datasets", nargs="+", default=["all"],
                        choices=list(DATASET_REGISTRY.keys()) + ["all"])
    parser.add_argument("--max_docs", type=int, default=0,
                        help="Max docs per dataset (0 = all)")
    parser.add_argument("--gliner_threshold", type=float, default=0.5)
    parser.add_argument("--output_dir", default=None,
                        help="Output directory for results JSON (default: %s). "
                             "Use a versioned dir like outputs/results/<job_id>/ for isolation."
                             % BENCHMARK_DIR)
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else BENCHMARK_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if "all" in args.models:
        args.models = list(BENCH_MODELS.keys())
    if "all" in args.datasets:
        args.datasets = list(DATASET_REGISTRY.keys())

    all_results = {}

    for ds_name in args.datasets:
        ds_info = DATASET_REGISTRY[ds_name]
        print(f"\n{'='*60}")
        print(f"Loading dataset: {ds_name}")
        print(f"{'='*60}")
        docs = ds_info["loader"]()
        if args.max_docs > 0:
            docs = docs[:args.max_docs]
        print(f"  Loaded {len(docs)} documents")

        type_counts = defaultdict(int)
        for doc_id, text, gold in docs:
            for s, e, t, m in gold:
                type_counts[t] += 1
        print(f"  Gold entities: {dict(type_counts)}")

        for model_name in args.models:
            model_info = BENCH_MODELS[model_name]
            eval_types = model_info["types"]

            if eval_types is not None:
                eval_types = eval_types & ds_info["types"]
                if not eval_types:
                    print(f"\n  [{model_name}] No overlapping types with {ds_name}, skipping")
                    continue

            print(f"\n  Running model: {model_name} (eval types: {eval_types})")

            # Instantiate model from registry
            override = {}
            if model_name.startswith("gliner"):
                override["threshold"] = args.gliner_threshold
            model = get_model(model_info["registry_key"], **override)

            # Use run_on_docs (shared benchmark method from BaseNERModel)
            preds, elapsed = model.run_on_docs(docs)

            metrics = evaluate(docs, preds, eval_types=eval_types)
            metrics["elapsed_seconds"] = elapsed
            metrics["n_docs"] = len(docs)
            metrics["eval_types"] = list(eval_types) if eval_types else "all"

            key = f"{ds_name}__{model_name}"
            all_results[key] = metrics

            o_e = metrics["overall"]["exact"]
            o_r = metrics["overall"]["relaxed"]
            print(f"\n  [{model_name} on {ds_name}]")
            print(f"    Exact:   P={o_e['P']:.4f}  R={o_e['R']:.4f}  F1={o_e['F1']:.4f}  (tp={o_e['tp']}, fp={o_e['fp']}, fn={o_e['fn']})")
            print(f"    Relaxed: P={o_r['P']:.4f}  R={o_r['R']:.4f}  F1={o_r['F1']:.4f}  (tp={o_r['tp']}, fp={o_r['fp']}, fn={o_r['fn']})")
            for t, tm in metrics["per_type"].items():
                print(f"    [{t}] Exact: F1={tm['exact']['F1']:.4f}  Relaxed: F1={tm['relaxed']['F1']:.4f}")

            del model

    # Save results
    output_path = output_dir / "ner_benchmark_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n{'='*60}")
    print(f"Results saved to {output_path}")
    print(f"{'='*60}")

    # Summary table
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Dataset':<10} {'Model':<20} {'Type':<12} {'Exact F1':>10} {'Relaxed F1':>12} {'P':>8} {'R':>8}")
    print("-" * 82)
    for key, m in sorted(all_results.items()):
        ds, model = key.split("__")
        o_e = m["overall"]["exact"]
        o_r = m["overall"]["relaxed"]
        print(f"{ds:<10} {model:<20} {'OVERALL':<12} {o_e['F1']:>10.4f} {o_r['F1']:>12.4f} {o_e['P']:>8.4f} {o_e['R']:>8.4f}")
        for t, tm in m["per_type"].items():
            print(f"{'':<10} {'':<20} {t:<12} {tm['exact']['F1']:>10.4f} {tm['relaxed']['F1']:>12.4f} {tm['exact']['P']:>8.4f} {tm['exact']['R']:>8.4f}")


if __name__ == "__main__":
    main()
