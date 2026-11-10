#!/usr/bin/env python
"""Stage 1: terminology ingest + deduplication for the Human Microbiome Data Catalogue.

Inputs:
  releases/zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv   (LLM extraction, 14 CDM types)
  releases/zenodo_v1/ner_453_sections/*.csv                    (6 NER models over 453 sections)

Outputs (in data/catalogue/):
  terminology_raw.csv          every surviving (term, type, model) observation, normalized
  terminology_exact_dedup.csv   registry after exact normalization dedup

Dedup rules:
  - normalize case + whitespace (existing cdm_pipeline.utils.norm)
  - junk filter (cdm_pipeline.utils.is_junk)
  - terms > 100 chars rejected (PubMedBERT garbage filter)
  - same normalized term + same type from multiple models -> merged with
    model priority GLiNER > Qwen > PubMedBERT > sciSpaCy-specific > sciSpaCy-lg

Results counts and per-type totals are written to terminology_stats.json.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT
while not (REPO_ROOT / "releases/zenodo_v1").exists() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
PROJECT_ROOT = REPO_ROOT
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pipeline.utils import is_junk, load_csv_safe  # noqa: E402
from pipeline.s06_entity_dedup.dedup import MODEL_PRIORITY, SOURCE_NAME, fix_label  # noqa: E402

ZENODO = PROJECT_ROOT / "releases/zenodo_v1"
QWEN_CSV = ZENODO / "qwen_sections_ner" / "qwen_sections_ner.csv"
NER_DIR = ZENODO / "ner_453_sections"
OUT_DIR = PROJECT_ROOT / "data" / "catalogue"

CSV_FILES = [
    "gliner_ner.csv",
    "gliner_biomed_ner.csv",
    "pubmedbert_ner.csv",
    "pubtator3_ner.csv",
    "scispacy_ner.csv",
    "qwen_sections_ner.csv",
]
MAX_TERM_LENGTH = 100


def main() -> int:
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    csvs = [QWEN_CSV] + sorted(NER_DIR.glob("*.csv"))
    csvs = [c for c in csvs if c.name != "all_ner_sections_combined.csv"]

    def norm(t: str) -> str:
        return re.sub(r"\s+", " ", t.lower().strip())

    # ---- pass 1: raw observations ----
    rows_written = 0
    n_obs = Counter()
    n_reject = Counter()
    raw_path = OUT_DIR / "terminology_raw.csv"
    # term_norm -> type -> {models, papers, term_canonical}
    registry: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))

    with raw_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["term", "term_norm", "labels", "model", "paper",
                    "section_id", "section_path", "char_start", "char_end", "source_file"])
        for csv_path in csvs:
            if not csv_path.exists():
                print(f"[warn] missing {csv_path}", file=sys.stderr)
                continue
            for r in load_csv_safe(csv_path):
                term = (r.get("term") or "").strip()
                label = fix_label(r.get("labels") or r.get("label") or "")
                model = (r.get("model") or "").strip()
                if not term or not label or not model:
                    continue
                if len(term) > MAX_TERM_LENGTH:
                    n_reject["too_long"] += 1
                    continue
                if is_junk(term):
                    n_reject["junk"] += 1
                    continue
                if "\\n" in term or "\u00a0" in term:
                    n_reject["newline"] += 1
                    continue
                tn = norm(term)
                w.writerow([term, tn, label, model, r.get("paper", ""),
                            r.get("section_id", ""), r.get("section_path", ""),
                            r.get("char_start", ""), r.get("char_end", ""),
                            csv_path.name])
                rows_written += 1
                n_obs[model] += 1
                slot = registry[tn].setdefault(label, {"models": Counter(), "papers": set(), "canonical": term})
                slot["models"][model] += 1
                slot["papers"].add(r.get("paper", ""))

    print(f"raw observations: {rows_written} (models: {dict(n_obs)})")
    print(f"rejected: {dict(n_reject)}")

    # ---- pass 2: exact dedup + type resolution ----
    exact_path = OUT_DIR / "terminology_exact_dedup.csv"
    out_rows = []
    for tn, by_type in registry.items():
        # resolve conflicting types by model priority
        def best_type_rank(lbl):
            return min((MODEL_PRIORITY.get(m, 99) for m in by_type[lbl]["models"]), default=99)

        types = sorted(by_type, key=best_type_rank)
        chosen = types[0]
        slot = by_type[chosen]
        all_models = sorted({m for s in by_type.values() for m in s["models"]},
                            key=lambda m: MODEL_PRIORITY.get(m, 99))
        all_types = sorted(by_type)
        out_rows.append({
            "term": slot["canonical"],
            "term_norm": tn,
            "cdm_type": chosen,
            "all_types": "|".join(all_types),
            "models": "|".join(all_models),
            "source_names": "|".join(sorted({SOURCE_NAME.get(m, m) for m in all_models})),
            "n_models": len(all_models),
            "n_observations": sum(s["models"].total() for s in by_type.values()),
            "n_papers": len(set().union(*(s["papers"] for s in by_type.values()))),
        })
    out_rows.sort(key=lambda r: (-r["n_models"], -r["n_observations"], r["term_norm"]))

    with exact_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    stats = {
        "raw_observations": rows_written,
        "rejected": dict(n_reject),
        "unique_terms_after_exact_dedup": len(out_rows),
        "per_type": dict(Counter(r["cdm_type"] for r in out_rows)),
        "per_model_observations": dict(n_obs),
        "elapsed_s": round(time.time() - t0, 1),
    }
    (OUT_DIR / "terminology_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"unique terms (exact dedup): {len(out_rows)}")
    print(f"per type: {dict(stats['per_type'])}")
    print(f"elapsed: {stats['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
