"""Segmented-corpus NER: run the multi-NER ensemble over segmented-sections markdown.

Mirrors src/notebooks/pipeline_standalone.ipynb section semantics:

* Sections come from repo-root ``data/segmented_sections_markdown/HMPAPER_*.md`` parsed
  with the notebook's exact ``parse_sections`` / SECTION_PATH conventions.
* BODY_ONLY=True — backmatter sections (references, acknowledg, funding, ...) are
  excluded, exactly like the notebook's ``is_backmatter``; ``(preamble)`` is body.
* Each model runs per (paper, section) unit; CSV rows carry ``section_id`` and
  ``section_path`` and offsets are relative to the section body, validated via
  ``body[start:end] == term`` before emitting (the notebook's slice rule).

Usage:
    python -m cdm_pipeline.ner.runner_sections --models all --output_dir outputs/results/<dir>
    python -m cdm_pipeline.ner.runner_sections --models gliner scispacy_bc5cdr
"""
import sys
import io
import os
import re
import csv
import json
import gc
import time
import argparse
import warnings
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from pipeline.config import REPO_ROOT, CDM_TYPES
from pipeline.s04_ner.registry import MODEL_REGISTRY, DEFAULT_MODELS, SCISPACY_ALL, BERT_VARIANTS, EXTRA_MODELS, GLINER_NEW, get_model

SEG_DIR_DEFAULT = REPO_ROOT / "data/segmented_sections_markdown"

# Notebook Cell 1/8: BODY_ONLY=True, user-approved token list.
BACKMATTER_TOKENS = ("references", "acknowledg", "funding", "author contribution",
                     "data availability", "conflict", "associated data", "footnote",
                     "supplementary", "orcid", "corresponding author",
                     "institutional", "informed consent", "competing interest")

MARKER_LINE = re.compile(
    r"^\s*<!-- (SECTION_PATH: .*?|SEGMENT: \S+|SECTION_ID: \S+|END_SEGMENT: \S+) -->\s*$")
ORDINAL_LINE = re.compile(r"^\s*<!-- SEGMENT_ORDINAL_WITHIN_SECTION: \d+ -->\s*$")
SEGMENT_RE = re.compile(
    r"<!-- SEGMENT: (\S+) -->\n<!-- SECTION_ID: (\S+) -->\n(.*?)\n<!-- END_SEGMENT: \1 -->",
    re.S)
PATH_RE = re.compile(r"<!-- SECTION_PATH: (.*?) -->")


def is_backmatter(path):
    """Notebook Cell 2 verbatim: last SECTION_PATH token vs BACKMATTER_TOKENS; (preamble) is body."""
    last = (path or "").split(">")[-1].strip().lower()
    if not last or last == "(preamble)":
        return False
    return any(tok in last for tok in BACKMATTER_TOKENS)


def parse_markdown(md_text):
    """Parse one segmented markdown file -> list of section dicts.

    Follows the notebook's parse_sections (segment joins wiped from output;
    the SEGMENT_ORDINAL marker is extra body noise, removed here since
    every section is a single segment in this corpus).
    """
    txt = md_text
    if txt.startswith("---"):
        txt = re.sub(r"\A---\n.*?\n---\n", "", txt, flags=re.S)
    secs, paths = [], {}
    for m in SEGMENT_RE.finditer(txt):
        seg_id, sec_id, body = m.group(1), m.group(2), m.group(3)
        pm = PATH_RE.search(body)  # read path from the RAW body before marker filtering
        lines = [ln for ln in body.split("\n") if not MARKER_LINE.match(ln)]
        body = "\n".join(lines).strip()
        body_clean = "\n".join(ln for ln in body.split("\n") if not ORDINAL_LINE.match(ln)).strip()
        secs.append({"section_id": sec_id, "body": body_clean})
        paths[sec_id] = pm.group(1) if pm else ""
    return secs, paths


def load_sections(seg_dir, max_files=None, body_only=True):
    """Load all papers -> (units, per-paper stats).

    units: list of {cid, section_id, path, text}
    """
    seg_dir = Path(seg_dir)
    files = sorted(seg_dir.glob("HMPAPER_*.md"))
    if max_files:
        files = files[:max_files]
    units, stats = [], {}
    for f in files:
        cid = f.stem
        secs, paths = parse_markdown(f.read_text(encoding="utf-8"))
        kept = skipped = chars = 0
        for s in secs:
            path = paths.get(s["section_id"], "")
            if body_only and is_backmatter(path):
                skipped += 1
                continue
            units.append({"cid": cid, "section_id": s["section_id"], "path": path, "text": s["body"]})
            kept += 1
            chars += len(s["body"])
        stats[cid] = {"kept": kept, "skipped": skipped, "chars": chars}
    return units, stats


CSV_FIELDS = ["term", "labels", "model", "paper", "section_id", "section_path",
              "char_start", "char_end"]


def run_model_on_units(model, units, output_path, report_every=200):
    """Run one model over section units; write CSV. Returns (n_rows, elapsed)."""
    t0 = time.time()
    rows = []
    for idx, u in enumerate(units):
        text = u["text"]
        if not text.strip():
            continue
        try:
            preds = model.predict_text(text)
        except Exception as ex:
            print("  [%s] %s/%s predict failed: %r" % (model.name, u["cid"], u["section_id"], ex))
            continue
        for p in preds:
            term = p["text"].strip()
            if not term:
                continue
            s, e = p["start"], p["end"]
            if not (0 <= s < e <= len(text)) or text[s:e] != p["text"]:
                # slice-validation failed (notebook rule): clamp to what matches
                continue
            rows.append({
                "term": term,
                "labels": p["label"],
                "model": model.name,
                "paper": u["cid"],
                "section_id": u["section_id"],
                "section_path": u["path"],
                "char_start": s,
                "char_end": e,
            })
        if (idx + 1) % report_every == 0 or idx == len(units) - 1:
            el = time.time() - t0
            rate = (idx + 1) / el if el > 0 else 0
            eta = (len(units) - idx - 1) / rate if rate > 0 else 0
            print("  [%s] %d/%d sections (%d ents, %.0fs, ETA %.0fs)" % (
                model.name, idx + 1, len(units), len(rows), el, eta))
            sys.stdout.flush()
    elapsed = time.time() - t0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("[%s] Saved %d rows -> %s (%.0fs)" % (model.name, len(rows), output_path, elapsed))
    return rows, elapsed


def main():
    available = sorted(MODEL_REGISTRY.keys()) + ["all", "scispacy_all", "bert_variants",
                                                 "extra", "gliner_new"]
    parser = argparse.ArgumentParser(description="Section-level multi-NER on segmented markdown corpus")
    parser.add_argument("--models", nargs="+", default=["all"], choices=available)
    parser.add_argument("--max_files", type=int, default=None, help="Max papers (HMPAPER_*.md files)")
    parser.add_argument("--exclude_papers", nargs="+", default=[],
                        help="Paper ids to exclude. The 452-paper analysis universe is "
                             "segmented_sections_markdown (453 papers) minus HMPAPER_000372, "
                             "an HTML 'Auto Article Locator' redirect stub (908 body chars, "
                             "zero catalogue records).")
    parser.add_argument("--seg_dir", default=str(SEG_DIR_DEFAULT))
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--entity_types", nargs="+", default=None)
    parser.add_argument("--api_key", default=os.environ.get("ENTREZ_API_KEY", ""))
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--include_backmatter", action="store_true",
                        help="Also run on backmatter sections (default: body only, notebook rule)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    models = list(args.models)
    if "all" in models:
        models = list(DEFAULT_MODELS)
    elif "scispacy_all" in models:
        models = [m for m in models if m != "scispacy_all"] + SCISPACY_ALL
    elif "bert_variants" in models:
        models = [m for m in models if m != "bert_variants"] + BERT_VARIANTS
    elif "extra" in models:
        models = [m for m in models if m != "extra"] + EXTRA_MODELS
    elif "gliner_new" in models:
        models = [m for m in models if m != "gliner_new"] + GLINER_NEW
    # PubTator is API/PMID-based, not section-text based: excluded here.
    models = [m for m in models if m != "pubtator"]
    if not models:
        print("Nothing to run (pubtator excluded from section mode).")
        return

    seg_dir = Path(args.seg_dir)
    units, stats = load_sections(seg_dir, args.max_files, body_only=not args.include_backmatter)
    if args.exclude_papers:
        ex = set(args.exclude_papers)
        units = [u for u in units if u["cid"] not in ex]
        stats = {k: v for k, v in stats.items() if k not in ex}
        print("Excluded %d paper(s): %s" % (len(ex), sorted(ex)))
    print("Papers: %d | section units: %d | body chars: %d" % (
        len(stats), len(units), sum(s["chars"] for s in stats.values())))
    print("Models:", models)

    entity_types = args.entity_types or CDM_TYPES
    summary = {"papers": len(stats), "units": len(units),
               "body_chars": sum(s["chars"] for s in stats.values()),
               "models": {}}

    for model_key in models:
        print("\n" + "=" * 60)
        print("Running: %s" % model_key)
        print("=" * 60)
        override = {"threshold": args.threshold}
        if model_key.startswith("gliner"):
            override["entity_types"] = list(entity_types)
        t_load = time.time()
        model = get_model(model_key, **override)
        model._ensure_loaded()
        load_seconds = round(time.time() - t_load, 1)
        rows, elapsed = run_model_on_units(
            model, units, output_dir / model.output_file)
        papers_seen = sorted(set(r["paper"] for r in rows))
        labels = {}
        for r in rows:
            labels[r["labels"]] = labels.get(r["labels"], 0) + 1
        summary["models"][model.name] = {
            "registry_key": model_key,
            "checkpoint": getattr(model, "model_name", None) or getattr(model, "spacy_model", None),
            "rows": len(rows),
            "elapsed_seconds": round(elapsed, 1),
            "load_seconds": load_seconds,
            "papers_with_entities": len(papers_seen),
            "papers_total": len(stats),
            "sections_with_entities": len(set((r["paper"], r["section_id"]) for r in rows)),
            "labels": dict(sorted(labels.items())),
        }
        del model
        gc.collect()

    # Combined CSV
    combined = []
    for model_key in models:
        entry = MODEL_REGISTRY[model_key]
        p = output_dir / entry["kwargs"].get("output_file", "")
        if p.exists():
            with open(p, encoding="utf-8", errors="replace") as f:
                content = f.read().replace("\x00", "")
                combined.extend(csv.DictReader(io.StringIO(content)))
    with open(output_dir / "all_ner_sections_combined.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(combined)
    summary["combined_rows"] = len(combined)
    with open(output_dir / "_sections_ner_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("\nCombined rows: %d -> %s" % (len(combined), output_dir / "all_ner_sections_combined.csv"))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
