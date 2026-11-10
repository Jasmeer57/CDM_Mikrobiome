#!/usr/bin/env python
"""Generate manuscript Table 9 — per-variant NER coverage on the 452-paper corpus.

Reads ONLY the summary JSONs that the 452-paper variant runs wrote, so every
number in the table traces to a single artifact. It deliberately does NOT
recompute Table 8's noise / clean-unique metrics: those came from
`per_model_quality.json`, which lived in the frozen v2.0 release and is absent
from this working tree. Table 8 stays attributed to the 444-paper build.

Usage:
    PYTHONPATH=src python src/scripts/gen_table9_variants.py [--markdown PATH]

Exit codes:
    0  table written
    1  a declared run directory or summary is missing (nothing written)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

REPO = str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents if (p / ".cdm_root").is_file()))
RESULTS = os.path.join(REPO, "outputs/results")

# (label, family, detail, run_dir, summary_glob, model_key, caveat)
# model_key is looked up inside summary["models"]; None = use whole summary.
VARIANTS = [
    # ── BERT family (outputs/results/<jobid>_ner_bert_variants) ──
    ("BioBERT-Disease", "PubMedBERT", "alvaroalon2/biobert_diseases_ner",
     "28643785_ner_bert_variants", "_bert_variants_summary.json", "biobert_diseases_wl", ""),
    ("BioBERT-Chemical", "PubMedBERT", "alvaroalon2/biobert_chemical_ner",
     "28643785_ner_bert_variants", "_bert_variants_summary.json", "biobert_chemical", ""),
    ("BioBERT-Genetic", "PubMedBERT", "alvaroalon2/biobert_genetic_ner",
     "28643785_ner_bert_variants", "_bert_variants_summary.json", "biobert_genetic", ""),
    ("SciBERT-JNLPBA", "PubMedBERT", "fran-martinez/scibert_scivocab_cased_ner_jnlpba",
     "28643785_ner_bert_variants", "_bert_variants_summary.json", "scibert_jnlpba",
     "label vocabulary not folded to CDM types"),
    # ── extra spaCy variant ──
    ("sciSpaCy-BIONLP13CG", "sciSpaCy", "en_ner_bionlp13cg_md",
     "28643869_ner_extra_variants", "_extra_variants_summary.json", "en_ner_bionlp13cg_md", ""),
    # HunFlair2 is reported from the span-trim re-run (job 28649224, approved
    # 2026-10-28).  The 28643869 summary is SUPERSEDED and must not be read: the
    # old runner's byte-exact slice check discarded 785 good spans, whose raw
    # flair token windows did not equal the sliced text, so it reported 106,011
    # rows where the trimmed run finds 106,413.  Family is `Flair`, not sciSpaCy:
    # hunflair2 is a flair-sequence-tagging ensemble.
    ("HunFlair2", "Flair", "hunflair/hunflair2-ner",
     "28649224_ner_hunflair2_trim", "_hunflair2_trim_summary.json", "hunflair2",
     "multi-corpus union label set; span-trimmed re-run"),
]

# ── newer GLiNER checkpoints: one summary for the whole run ──
GLINER_RUN = "28647499_ner_gliner_new"
GLINER_MODELS = [
    ("GLiNER2-base", "GLiNER2", "fastino/gliner2-base-v1", "gliner2_base", ""),
    ("GLiNER2-large", "GLiNER2", "fastino/gliner2-large-v1", "gliner2_large", ""),
    ("GLiNER-v2.5-medium", "GLiNER", "gliner-community/gliner_medium-v2.5", "gliner_v25_medium", ""),
    ("GLiNER-v2.5-biomed", "GLiNER", "Ihor/gliner-large-v2.5-biomed", "gliner_v25_biomed",
     "0 downloads, no license, no model card — exploratory only"),
]

# ── Java tools: run-tagged summary, newest completed run wins ──
JAVA_GLOB = os.path.join(RESULTS, "*_ner_java_tools", "_java_tools_summary_*.json")
# model_key must equal the summary's own `models` key, which is the CSV `model`
# string (title-cased tool name) — not a lowercase slug.
#
# tmChem joined the family on 2026-10-28: the tool was obtained from the
# ncbi.nlm.nih.gov mirror (not ftp.ncbi.nlm.nih.gov/pub/lu/) and wired into
# src/cdm_pipeline/ner/java_tools.py together with Ab3P-v1.5.  That also
# restored DNorm's abbreviation-driven lookup, so its former
# "Ab3P unavailable — degraded mode" caveat is retired.
JAVA_MODELS = [
    ("DNorm", "NCBI Java", "disease + MeSH normalization", "DNorm", ""),
    ("TaggerOne-Disease", "NCBI Java", "BC5CDR-Disease", "TaggerOne-Disease", ""),
    ("TaggerOne-Chemical", "NCBI Java", "BC5CDR-Chemical", "TaggerOne-Chemical", ""),
    ("tmChem", "NCBI Java", "BC5CDR-Chemical", "tmChem", ""),
    ("GNormPlus", "NCBI Java", "gene + normalization", "GNormPlus",
     "human Species 9606 rows dropped"),
]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_summary(run_dir, pattern):
    hits = sorted(glob.glob(os.path.join(RESULTS, run_dir, pattern)))
    return hits[-1] if hits else None


def fmt_int(n):
    return f"{n:,}" if isinstance(n, int) else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", default=None,
                    help="write the table here (default: stdout)")
    args = ap.parse_args()

    rows, missing = [], []

    # BERT + extra variants
    summary_cache = {}
    for label, family, detail, run_dir, pattern, key, caveat in VARIANTS:
        cache_key = (run_dir, pattern)
        if cache_key not in summary_cache:
            p = find_summary(run_dir, pattern)
            summary_cache[cache_key] = load_json(p) if p else None
        summ = summary_cache[cache_key]
        if not summ or key not in summ.get("models", {}):
            missing.append(f"{label} (outputs/results/{run_dir}/{pattern})")
            continue
        m = summ["models"][key]
        rows.append({
            "label": label, "family": family, "detail": detail,
            "rows": m.get("rows", 0),
            "papers": m.get("papers_with_entities"),
            "papers_total": m.get("papers_total") or summ.get("papers"),
            "labels": m.get("labels", {}),
            "seconds": m.get("elapsed_seconds"),
            "caveat": caveat,
        })

    # GLiNER new
    gp = find_summary(GLINER_RUN, "_gliner_new_summary.json")
    gsumm = load_json(gp) if gp else None
    for label, family, detail, key, caveat in GLINER_MODELS:
        if not gsumm or key not in gsumm.get("models", {}):
            missing.append(f"{label} (outputs/results/{GLINER_RUN}/_gliner_new_summary.json)")
            continue
        m = gsumm["models"][key]
        rows.append({
            "label": label, "family": family, "detail": detail,
            "rows": m.get("rows", 0),
            "papers": m.get("papers_with_entities"),
            "papers_total": m.get("papers_total") or gsumm.get("papers"),
            "labels": m.get("labels", {}),
            "seconds": m.get("elapsed_seconds"),
            "caveat": caveat,
        })

    # Java tools — newest summary that covers every declared tool wins.  Older
    # runs (e.g. 28647522) predate tmChem and are skipped, not merged: mixing
    # two runs in one table row set would silently attribute stale numbers.
    jhits = sorted(glob.glob(JAVA_GLOB), reverse=True)
    jsummary = None
    for hit in jhits:
        try:
            cand = load_json(hit)
        except (json.JSONDecodeError, OSError):
            continue
        if all(cand.get("models", {}).get(k, {}).get("status") == "OK"
               for _, _, _, k, _ in JAVA_MODELS):
            jsummary = cand
            break
    for label, family, detail, key, caveat in JAVA_MODELS:
        if not jsummary or key not in jsummary.get("models", {}):
            missing.append(f"{label} ({os.path.basename(jhits[0]) if jhits else JAVA_GLOB})")
            continue
        m = jsummary["models"][key]
        if m.get("status") != "OK":
            missing.append(f"{label} (status={m.get('status')})")
            continue
        rows.append({
            "label": label, "family": family, "detail": detail,
            "rows": m.get("rows", 0),
            "papers": m.get("papers_with_entities"),
            "papers_total": jsummary.get("papers"),
            "labels": m.get("labels", {}),
            "seconds": m.get("elapsed_seconds"),
            "caveat": caveat,
        })

    if missing:
        print("MISSING SOURCES — nothing written:", file=sys.stderr)
        for m in missing:
            print("  - " + m, file=sys.stderr)
        return 1

    lines = [
        "**Table 9. Per-variant NER coverage on the 452-paper segmented-section "
        "corpus.** All runs consume the same 2,815 section-body units "
        "(20,903,341 chars) and exclude `HMPAPER_000372`, the HTML redirect stub "
        "removed from the 452-paper analysis corpus. Generated by "
        "`src/scripts/gen_table9_variants.py` from the run summary JSONs; no number "
        "here is hand-entered.",
        "",
        "| Variant | Family | Checkpoint | Papers | Entities | Distinct labels | Seconds |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        pt = r["papers_total"] or "—"
        lines.append(
            f"| {r['label']} | {r['family']} | `{r['detail']}` | "
            f"{r['papers']}/{pt} | {fmt_int(r['rows'])} | "
            f"{len(r['labels'])} | {fmt_int(int(r['seconds'])) if r['seconds'] else '—'} |"
        )

    lines += [
        "",
        "*Papers* counts papers with at least one entity; the remainder are "
        "genuine zero-entity results, not failed runs (each variant's own "
        "summary records `papers_with_entities`). Times are wall-clock on the "
        "Slurm allocations described in the bundle's `04_ner/README.md` and are "
        "**not** comparable across families (different hardware, batching, and "
        "chunking).",
        "",
        "**Caveats.** " + " ".join(
            f"*{r['label']}*: {r['caveat']}." for r in rows if r.get("caveat")
        ) + " GLiNER2 and GLiNER v2.5 are different architectures — confidence "
        "scores are not comparable across them. Qwen's 452-paper body pass is "
        "reported separately (Table 8); it used vLLM `Qwen/Qwen3.5-4B` in place "
        "of the historical Ollama tag `qwen3.5:4b`.",
    ]

    out = "\n".join(lines) + "\n"
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"wrote {args.markdown} ({len(rows)} variants)")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
