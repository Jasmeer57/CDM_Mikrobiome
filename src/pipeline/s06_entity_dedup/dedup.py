"""Stage 2: Deduplication — merge all NER CSVs into a unified entity registry.

Reads:  paper/_multi_ner_runs/{gliner,pubmedbert,pubtator3,scispacy,qwen3.5}_ner.csv
        plus, when ``include_variants=True``, the fifteen section-level variant runs
        in ``outputs/results/28643785_*``, ``outputs/results/28643869_*``, ``outputs/results/28647499_*``,
        ``outputs/results/28649224_*`` and ``outputs/results/28649661_*`` (see
        :data:`VARIANT_CSV_FILES`).
Writes: paper/_multi_ner_runs/deduplicated_entities.json

Dedup key is the normalized term (lowercase + collapsed whitespace).  When the
same term is found by multiple models with different CDM types, the type is
resolved by model priority:

    GLiNER  >  Qwen/PubTator3  >  PubMedBERT  >  sciSpaCy (specific)  >  sciSpaCy (ENTITY)

"ENTITY" (generic label from en_core_sci_lg) is kept as a last-resort type only
when no other model assigns a specific CDM type to the same term.

Terms longer than 100 characters are rejected (PubMedBERT garbage filter:
38.8% of PubMedBERT terms exceed 100 chars — author lists tagged as DISEASE).

Registration contract (do not skip)
-----------------------------------
The priority lookup is ``MODEL_PRIORITY.get(model, 9)``.  An *unregistered* model
therefore gets priority 9, which is worse than every tier above — including
``en_core_sci_lg``'s generic ``ENTITY`` at tier 4.  A new model whose strings are
not added here still has its rows counted, but it can never win a type conflict,
so its specificity is silently discarded.  Every ``model`` value that appears in a
consumed CSV must be present in both :data:`MODEL_PRIORITY` and
:data:`SOURCE_NAME`.

Tiers are tiers of *type-resolution trust*, not of extraction quality, and several
models deliberately share a tier (all GLiNER checkpoints; both BERT families; the
Java normalizers).  Within a tier the first-observed label wins, so a run's type
assignment for an ambiguous surface can depend on CSV order — the registry is
source-agnostic by design (same convention as
``src/scripts/catalogue/build_terminology_registry.py``), and per-model spans are
kept in the per-variant CSVs, not here.
"""
import argparse
import sys
import io
import csv
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pipeline.config import NER_OUTPUT_DIR, CDM_TYPES, NER_CSVS, EXCLUDE_PAPERS
from pipeline.utils import is_junk, norm, load_csv_safe

CSV_FILES = [
    "gliner_ner.csv",
    "pubmedbert_ner.csv",
    "pubtator3_ner.csv",
    "scispacy_ner.csv",
    "qwen3.5_ner.csv",
]

# --- section-level variant runs (2026-10-27/28) -------------------------------
# These live in outputs/results/<job>_*/ rather than NER_OUTPUT_DIR, because those run
# directories are frozen artifacts of a specific Slurm job (three are read-only:
# dr-xr-xr-x).  They are therefore listed as (relative dir, filename) pairs and
# consumed only when the caller opts in, so the historical `main()` output for the
# five baseline CSVs stays byte-reproducible.
#
# The filename set is NOT glob-derived on purpose: it is inconsistent in the tree
# (`scispacy_ner_bionlp13cg.csv` has no `_ner` infix before the model, and the
# GLiNER job writes `_gliner_new_summary.json`).  Globbing `*_ner.csv` silently
# under-counts; the explicit list is the completeness contract, and a missing file
# is reported as MISSING rather than skipped quietly.
VARIANT_CSV_FILES = [
    ("28643785_ner_bert_variants", "bert_disease_ner.csv"),      # alvaroalon2 biobert_diseases
    ("28643785_ner_bert_variants", "bert_chemical_ner.csv"),     # biobert_chemical
    ("28643785_ner_bert_variants", "bert_genetic_ner.csv"),      # biobert_genetic
    ("28643785_ner_bert_variants", "scibert_jnlpba_ner.csv"),    # scibert_jnlpba
    ("28643869_ner_extra_variants", "scispacy_ner_bionlp13cg.csv"),
    # HunFlair2 replaced by the span-trim re-run (job 28649224, approved
    # 2026-10-28, notebook Cell 19).  The 28643869 CSV is superseded and must
    # not be read: it carried 34,378 junk rows and silently dropped 785 good
    # spans whose raw token window failed the old byte-exact slice check.
    ("28649224_ner_hunflair2_trim", "hunflair2_ner.csv"),
    ("28647499_ner_gliner_new", "gliner2_base_ner.csv"),
    ("28647499_ner_gliner_new", "gliner2_large_ner.csv"),
    ("28647499_ner_gliner_new", "gliner_v25_medium_ner.csv"),
    ("28647499_ner_gliner_new", "gliner_v25_biomed_ner.csv"),
    # Java family, superseded by job 28649661 (2026-10-28): that run added tmChem
    # and restored Ab3P, which is why DNorm rises 34,703 -> 48,203 rows.  The
    # 28647522 CSVs must not be read -- mixing the two runs in one merge would
    # attribute DNorm's pre-Ab3P output to the current tool set.
    ("28649661_ner_java_tools", "dnorm_ner.csv"),
    ("28649661_ner_java_tools", "taggerone_disease_ner.csv"),
    ("28649661_ner_java_tools", "taggerone_chemical_ner.csv"),
    ("28649661_ner_java_tools", "tmchem_ner.csv"),
    ("28649661_ner_java_tools", "gnormplus_ner.csv"),
]

OUTPUT = NER_OUTPUT_DIR / "deduplicated_entities.json"

# Tier = type-resolution trust.  Shared tiers are intentional.
MODEL_PRIORITY = {
    # --- baseline five (unchanged; do not renumber, tests assert this order) ---
    "gliner_medium": 0,
    # gliner_biomed ships in the section-level ensemble and is the same GLiNER
    # *family* as gliner_medium, but with a biomedical checkpoint.  It was left
    # out of this table until the 452 build, where it would have fallen to
    # priority 9 and lost every type conflict to en_core_sci_lg's generic
    # ENTITY (tier 4) — a 297,115-row file silently outranked by a tagger that
    # emits no types at all.
    "gliner_biomed": 0,
    "qwen3.5:9b": 1,
    # The 452 build consumes two Qwen artifacts whose `model` column is written
    # by the runners rather than by MODEL_REGISTRY: the vLLM body run tags rows
    # with the HF repo id, the historical Ollama run with the Ollama tag.  Both
    # are the same Qwen tier as qwen3.5:9b.
    "Qwen/Qwen3.5-4B": 1,
    "qwen3.5:4b": 1,
    "pubtator3": 1,
    "biobert_diseases": 2,
    "en_ner_bc5cdr_md": 3,
    "en_ner_craft_md": 3,
    "en_ner_jnlpba_md": 3,
    "en_core_sci_lg": 4,
    # --- GLiNER family, all four new checkpoints: tier 0 with gliner_medium ---
    # Two architectures ship here (fastino gliner2 base/large, and gliner-community/
    # Ihor v2.5 medium/biomed).  They are the same *extraction* family for
    # type-resolution purposes, but their confidence scores are NOT comparable, so
    # nothing downstream may rank them by score — only by registration tier.
    "gliner2_base": 0,
    "gliner2_large": 0,
    "gliner_v25_medium": 0,
    "gliner_v25_biomed": 0,
    # --- BERT family + HunFlair2: tier 2, the PubMedBERT tier ---
    # biobert_chemical/genetic are sibling heads of the same BioBERT lineage;
    # scibert_jnlpba is a different encoder but the same JMLE-style BIO task;
    # hunflair2 is a flair-sequence-tagging ensemble.  None of them outranks the
    # specialised baseline models, and all of them outrank the generic tiers.
    "biobert_diseases_wl": 2,
    "biobert_chemical": 2,
    "biobert_genetic": 2,
    "scibert_jnlpba": 2,
    "hunflair2": 2,
    # --- sciSpaCy biomed NER: tier 3, with the other scispaCy specific models ---
    "en_ner_bionlp13cg_md": 3,
    # --- Java tools: tier 2 ---
    # These are the only runs with a real ontology normalizer behind them
    # (DNorm -> OMIM/CUI, TaggerOne -> MeSH, tmChem -> MeSH/CHEBI, GNormPlus ->
    # NCBI Taxonomy/Gene), so they carry more type authority than an unnormalized
    # tagger.  They tie with PubMedBERT rather than outranking GLiNER: model
    # priority is about the *label* vocabulary, and the normalizer's output is
    # retained separately in the tool CSV's norm/cdm_type columns (which this
    # merge does not consume).
    "DNorm": 2,
    "TaggerOne-Disease": 2,
    "TaggerOne-Chemical": 2,
    "tmChem": 2,
    "GNormPlus": 2,
}

SOURCE_NAME = {
    "gliner_medium": "GLiNER",
    "gliner_biomed": "GLiNER-Biomed",
    "qwen3.5:9b": "Qwen",
    "Qwen/Qwen3.5-4B": "Qwen-vLLM",
    "qwen3.5:4b": "Qwen-Ollama",
    "pubtator3": "PubTator3",
    "biobert_diseases": "PubMedBERT",
    "en_core_sci_lg": "sciSpaCy",
    "en_ner_bc5cdr_md": "sciSpaCy",
    "en_ner_craft_md": "sciSpaCy",
    "en_ner_jnlpba_md": "sciSpaCy",
    # variants: kept as distinct source labels so the registry records *which*
    # checkpoint saw a term.  Folding them into "GLiNER"/sciSpaCy would make the
    # four checkpoints indistinguishable after the merge.
    "gliner2_base": "GLiNER2-base",
    "gliner2_large": "GLiNER2-large",
    "gliner_v25_medium": "GLiNER-v2.5-medium",
    "gliner_v25_biomed": "GLiNER-v2.5-biomed",
    "biobert_diseases_wl": "BioBERT-Disease-WL",
    "biobert_chemical": "BioBERT-Chemical",
    "biobert_genetic": "BioBERT-Genetic",
    "scibert_jnlpba": "SciBERT-JNLPBA",
    "hunflair2": "HunFlair2",
    "en_ner_bionlp13cg_md": "sciSpaCy-BIONLP13CG",
    "DNorm": "DNorm",
    "TaggerOne-Disease": "TaggerOne-Disease",
    "TaggerOne-Chemical": "TaggerOne-Chemical",
    "tmChem": "tmChem",
    "GNormPlus": "GNormPlus",
}

MAX_TERM_LENGTH = 100

LABEL_FIX = {
    "ENTITY": "ENTITY",
    "GO": "PATHWAY",
    # --- approved 2026-10-28 (proposals in src/notebooks/pipeline_standalone.ipynb Cell 19;
    #     sign-off recorded there). common.LABEL_TO_CDM stays UNWIRED: DNA/RNA/CELL_LINE/
    #     GENE/TAXON keep dropping until that separate decision is taken. ---------------
    # Java tools (DNorm / TaggerOne / tmChem / GNormPlus): title-case CDM names are
    # pure case-folds; the NCBI-Taxonomy categories map conventionally to ORGANISM.
    "Disease": "DISEASE",
    "Chemical": "CHEMICAL",
    "CellLine": "CELL_TYPE",          # the CDM type is CELL_TYPE (common.LABEL_TO_CDM agrees:
                                      # its CELL_LINE entry also targets CELL_TYPE)
    "Species": "ORGANISM",
    "Genus": "ORGANISM",
    "Strain": "ORGANISM",
    # biobert_genetic's coarse label (job 28643785): GENOMICS chosen over DNA_RNA/PROTEIN —
    # the label space is too coarse for one CDM type; GENETIC is absent from LABEL_TO_CDM.
    "GENETIC": "GENOMICS",
}

VALID_TYPES = set(CDM_TYPES) | {"ENTITY"}


def fix_label(label):
    return LABEL_FIX.get(label, label)


def classify_row(row):
    """Apply the Stage-2 row filter to one CSV row.

    Returns ``(reason, None)`` when the row must be dropped, or
    ``(None, (norm_key, label))`` when it survives.  ``reason`` is one of
    ``junk_or_short``, ``over_max_length``, ``empty_norm``,
    ``label_not_in_vocabulary``.

    Factored out of :func:`main` so the survival report cannot drift from the
    filter it claims to measure — both callers go through this function, so a
    change to the thresholds changes the reported survival too.
    """
    term = (row.get("term") or "").strip()
    if len(term) < 2 or is_junk(term):
        return "junk_or_short", None
    if len(term) > MAX_TERM_LENGTH:
        return "over_max_length", None
    k = norm(term)
    if not k:
        return "empty_norm", None
    label = fix_label(row.get("labels") or row.get("label") or "")
    if label not in VALID_TYPES:
        return "label_not_in_vocabulary", None
    return None, (k, label)


def _variant_dir_path(rel_dir, filename):
    """Resolve a variant CSV under ``<repo>/results/<rel_dir>/<filename>``."""
    from pipeline.config import REPO_ROOT

    return REPO_ROOT / "outputs/results" / rel_dir / filename


def resolve_inputs(include_variants=False, baseline_dir=None, csv_paths=None):
    """Return ``[(label, path), ...]`` for the CSVs this stage should read.

    ``label`` is used only for the coverage report; ``check_registration``
    reads the actual ``model`` column, so the label need not match it.

    Three ways to select inputs, in priority order:

    1. ``csv_paths`` — an explicit list of CSV paths (a re-scoped build such as
       the 452 one, whose filenames differ from the historical five).  The label
       is the filename stem, which is what the CDM corpus records as the model.
    2. ``baseline_dir`` + ``include_variants`` — the historical layout: five
       baseline CSVs plus, if opted in, the declare-complete variant list.
    3. Neither — the five baselines under :data:`NER_OUTPUT_DIR`.

    Baseline files are optional (a missing one is a WARNING, matching historical
    behaviour — not every checkout ships all five).  Variant files are declared
    complete, so a missing one is reported as MISSING.
    """
    if csv_paths:
        return [(Path(p).stem, Path(p)) for p in csv_paths]
    base = Path(baseline_dir) if baseline_dir else NER_OUTPUT_DIR
    inputs = [(name, base / name) for name in CSV_FILES]
    if include_variants:
        for rel_dir, filename in VARIANT_CSV_FILES:
            inputs.append((f"{rel_dir}/{filename}", _variant_dir_path(rel_dir, filename)))
    return inputs


def check_registration(csv_paths):
    """Audit that every ``model`` value in the given CSVs is registered.

    Returns a list of problems; empty means every model has a tier and a source
    label.  An unregistered model is not fatal (it merges with priority 9) but it
    can never win a type conflict, so the caller is expected to surface this.
    """
    problems = []
    for label, path in csv_paths:
        if not path.exists():
            continue
        seen = set()
        for r in load_csv_safe(path):
            seen.add((r.get("model") or "").strip())
        for model in sorted(seen):
            if not model:
                problems.append(f"{label}: empty model string")
                continue
            if model not in MODEL_PRIORITY:
                problems.append(f"{label}: model {model!r} not in MODEL_PRIORITY (falls to 9)")
            if model not in SOURCE_NAME:
                problems.append(f"{label}: model {model!r} not in SOURCE_NAME")
    return problems


def main(include_variants=False, output=None, baseline_dir=None, csv_paths=None,
         exclude_papers=None):
    t0 = time.time()
    print("=" * 60)
    print("Stage 2: Deduplication")
    if include_variants:
        print(f"  variant runs: {len(VARIANT_CSV_FILES)} CSVs (opt-in)")
    print("=" * 60)

    output_path = output or OUTPUT
    if csv_paths:
        print(f"  explicit inputs: {len(csv_paths)} CSVs (CSV_FILES bypassed)")
    inputs = resolve_inputs(include_variants, baseline_dir=baseline_dir,
                            csv_paths=csv_paths)

    # Paper-scope filter.  Rows for an excluded paper are dropped before they can
    # contribute a paper to ``paper_count``; this is how the 452-paper analysed
    # scope is expressed without rewriting the read-only per-variant CSVs.
    excluded = {exclude_papers} if isinstance(exclude_papers, str) else set(exclude_papers or ())
    excluded_rows = 0

    # A declared input that is absent would silently shrink the merge, so it is
    # called out loudly; baseline CSVs keep the historical soft warning.
    variant_labels = {f"{d}/{f}" for d, f in VARIANT_CSV_FILES}
    missing_variants = []
    for label, path in inputs:
        if not path.exists() and (csv_paths or label in variant_labels):
            missing_variants.append(label)
            print(f"  MISSING declared CSV: {label}")
    for problem in check_registration(inputs):
        print(f"  REGISTRATION: {problem}")

    # An explicit input list is a completeness contract: every file was named on
    # purpose, so an absent one must abort rather than quietly produce a smaller
    # registry (the failure mode that once published a wrong combined total).
    if csv_paths and missing_variants:
        raise SystemExit(
            f"dedup: {len(missing_variants)} explicitly named CSV(s) do not exist: "
            f"{', '.join(missing_variants)}"
        )

    if csv_paths:
        base_dir = None
        print(f"  paper scope: {len(excluded)} excluded "
              f"({', '.join(sorted(excluded)) or 'none'})")
    else:
        base_dir = (Path(baseline_dir) if baseline_dir else NER_OUTPUT_DIR)
        baseline_present = [n for n in CSV_FILES if (base_dir / n).exists()]
        print(f"  baseline dir: {base_dir}")
        if not baseline_present:
            print("  " + "!" * 58)
            print("  WARNING: no baseline CSV found in the baseline dir.")
            print("           The merge will contain VARIANT rows only.")
            print(f"           Pass --baseline_dir if the five CSVs live elsewhere")
            print(f"           (the shipped copies are in paper/_multi_ner_runs).")
            print("  " + "!" * 58)
        elif len(baseline_present) < len(CSV_FILES):
            absent = [n for n in CSV_FILES if n not in baseline_present]
            print(f"  baseline CSVs present: {len(baseline_present)}/{len(CSV_FILES)} "
                  f"(absent: {', '.join(absent)})")

    entities = {}

    # Drop accounting: the filter is three independent reasons, and conflating them
    # hides which one dominates (label-vocabulary vs junk/short/over-100-chars).
    drop_reasons = Counter()
    drop_labels = Counter()
    rows_by_input = {}

    for csv_label, csv_path in inputs:
        if not csv_path.exists():
            if csv_label not in variant_labels:
                print(f"  WARNING: {csv_label} not found, skipping")
            continue

        rows = load_csv_safe(csv_path)
        kept = 0
        for r in rows:
            if excluded and (r.get("paper") or "").strip() in excluded:
                excluded_rows += 1
                continue
            reason, parsed = classify_row(r)
            if reason is not None:
                drop_reasons[reason] += 1
                if reason == "label_not_in_vocabulary":
                    drop_labels[r.get("labels") or r.get("label") or ""] += 1
                continue
            k, label = parsed

            model = (r.get("model") or "").strip()
            source = SOURCE_NAME.get(model, model)
            priority = MODEL_PRIORITY.get(model, 9)

            if k not in entities:
                entities[k] = {
                    "term": (r.get("term") or "").strip(),
                    "norm": k,
                    "cdm_type": label,
                    "cdm_type_priority": priority,
                    "sources": set(),
                    "papers": set(),
                    "mention_count": 0,
                }

            e = entities[k]
            e["sources"].add(source)
            e["papers"].add(r.get("paper") or "")
            e["mention_count"] += 1

            if priority < e["cdm_type_priority"]:
                e["cdm_type"] = label
                e["cdm_type_priority"] = priority
            elif priority == e["cdm_type_priority"] and label != "ENTITY" and e["cdm_type"] == "ENTITY":
                e["cdm_type"] = label

            kept += 1

        rows_by_input[csv_label] = dict(rows=len(rows), kept=kept)
        print(f"  {csv_label}: {len(rows)} rows, {kept} kept")

    results = []
    for k in sorted(entities):
        e = entities[k]
        results.append({
            "term": e["term"],
            "norm": e["norm"],
            "cdm_type": e["cdm_type"],
            "sources": sorted(e["sources"]),
            "paper_count": len(e["papers"]),
            "mention_count": e["mention_count"],
        })

    if not rows_by_input:
        raise SystemExit(
            "dedup: no input CSVs found — refusing to overwrite the registry with an empty result.\n"
            f"  looked for baselines in: {base_dir or NER_OUTPUT_DIR}\n"
            "  pass --baseline_dir, --csv_paths or --include_variants"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\n  {len(results)} unique entities in {elapsed:.1f}s")
    print(f"  Saved to {output_path}")

    by_type = Counter(e["cdm_type"] for e in results)
    by_source = Counter(tuple(e["sources"]) for e in results)

    print(f"\n  By CDM type:")
    for t, c in by_type.most_common():
        print(f"    {t:25s} {c:6d}")
    print(f"\n  Top source combos:")
    for combo, c in by_source.most_common(10):
        print(f"    {combo}: {c}")

    total_rows = sum(v["rows"] for v in rows_by_input.values())
    total_kept = sum(v["kept"] for v in rows_by_input.values())
    dropped = sum(drop_reasons.values())
    print(f"\n  Rows: {total_rows} read, {total_kept} kept, {dropped} dropped")
    if excluded:
        print(f"    scope-filtered (excluded papers): {excluded_rows} rows")
    if total_rows:
        print(f"    kept {100.0 * total_kept / total_rows:.2f}%")
    for reason, count in drop_reasons.most_common():
        print(f"    drop[{reason:26s}] {count:8d} ({100.0 * count / max(total_rows, 1):5.2f}%)")
    if drop_labels:
        print("    dropped label values (raw -> fix_label -> not a CDM type):")
        for raw, count in drop_labels.most_common():
            print(f"      {raw!r:32s} -> {fix_label(raw)!r:22s} {count:8d}")

    entity_only = sum(1 for e in results if e["cdm_type"] == "ENTITY")
    typed = len(results) - entity_only
    print(f"\n  Typed entities: {typed}")
    print(f"  ENTITY-only (untyped): {entity_only}")

    return dict(entities=results, rows_by_input=rows_by_input,
                drop_reasons=dict(drop_reasons), drop_labels=dict(drop_labels),
                missing_variants=missing_variants, output=str(output_path),
                excluded_papers=sorted(excluded), excluded_rows=excluded_rows)


def cli(argv=None):
    ap = argparse.ArgumentParser(description="Stage 2: NER deduplication into an entity registry.")
    ap.add_argument("--include_variants", "--include-variants", dest="include_variants",
                    action="store_true",
                    help="also consume the fifteen section-level variant CSVs under outputs/results/")
    ap.add_argument("--output", default=None,
                    help="write the registry here instead of the default deduplicated_entities.json")
    ap.add_argument("--baseline_dir", "--baseline-dir", dest="baseline_dir", default=None,
                    help="directory holding the five baseline CSVs "
                         "(default: NER_OUTPUT_DIR; the shipped copies are one level up)")
    ap.add_argument("--csv_paths", "--csv-paths", dest="csv_paths", default=None,
                    nargs="+", metavar="CSV",
                    help="explicit input CSVs, bypassing CSV_FILES/VARIANT_CSV_FILES "
                         "(used by re-scoped builds whose filenames differ)")
    ap.add_argument("--exclude_papers", "--exclude-papers", dest="exclude_papers",
                    default=None, nargs="+", metavar="PAPER",
                    help="paper IDs to drop at read time (default: CDM_EXCLUDE_PAPERS)")
    args = ap.parse_args(argv)
    main(include_variants=args.include_variants, output=args.output,
         baseline_dir=args.baseline_dir,
         csv_paths=args.csv_paths or (NER_CSVS or None),
         exclude_papers=args.exclude_papers or (EXCLUDE_PAPERS or None))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
