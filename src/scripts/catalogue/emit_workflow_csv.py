#!/usr/bin/env python
"""Stage 6: emit workflow.csv (curation provenance) reflecting actual pipeline state.

Rows follow src/template/data_catalogue/csv_templates/workflow.csv column set.
Status is derived from artifact existence (idempotent — rerun any time).
"""

from __future__ import annotations

import csv
from pathlib import Path

PROJECT_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OUT = PROJECT_ROOT / "data" / "catalogue" / "tables" / "workflow.csv"
DATA = PROJECT_ROOT / "data" / "catalogue"
TABLES = DATA / "tables"

FIELDS = ["stage", "action", "input", "output", "quality_check", "status", "owner", "notes"]


def done(path: Path) -> str:
    return "COMPLETED" if path.exists() else "NOT_STARTED"


def nrows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig") as fh:
        return sum(1 for _ in fh) - 1


STAGES = [
    ("01_Build_terminology",
     "Aggregate NER extractions into term registry with per-term stats",
     "multi-NER outputs over data/papers_txt/",
     "data/catalogue/terminology_raw.csv",
     "row count == observation count expected from NER runs",
     done(DATA / "terminology_raw.csv"),
     f"{nrows(DATA / 'terminology_raw.csv'):,} observations"),
    ("02_Deduplicate_terms",
     "Exact + fuzzy + semantic dedup (taxa protected from merging)",
     "terminology_raw.csv",
     "terminology_dedup.csv",
     "merge-direction spot checks; taxa untouched",
     done(DATA / "terminology_dedup.csv"),
     f"{nrows(DATA / 'terminology_dedup.csv'):,} terms survive"),
    ("03_LLM_term_correction",
     "qwen3.5:4b correction + definition of priority terms (n_papers>=2)",
     "terminology_dedup.csv",
     "catalogue_terms_llm.csv + checkpoint",
     "taxa guard; JSON parse fallback; checkpoint resume",
     "COMPLETED" if (DATA / "llm_terms_checkpoint.json").exists()
     and nrows(DATA / "catalogue_terms_llm_419617.csv") > 0 else "IN_PROGRESS"
     if (DATA / "llm_terms_checkpoint.json").exists() else "NOT_STARTED",
     "SLURM 419617 gpu-amd; batch=10, min-papers=2"),
    ("04_Seed_core_tables",
     "papers/datasets/dataassets from corpus records + BioProjects",
     "data/corpus/records/, corpus_tracking.csv",
     "tables/papers.csv, datasets.csv, dataassets.csv",
     "453 rows each; ID prefixes HMPAPER_/HMDATA_/HMASSET_",
     "COMPLETED" if nrows(TABLES / "papers.csv") == 453 else "NOT_STARTED",
     "AUTO_SEEDED; verification_status=UNVERIFIED"),
    ("05_Seed_study_tables",
     "cohorts/samples/findings from G_study_metadata + annotations",
     "records G_study_metadata; annotations/findings.csv",
     "tables/cohorts.csv, samples.csv, findings.csv",
     "foreign keys resolve to papers/datasets; findings carry annotation status",
     "COMPLETED" if nrows(TABLES / "cohorts.csv") == 453 else "NOT_STARTED",
     f"cohorts={nrows(TABLES / 'cohorts.csv')} samples={nrows(TABLES / 'samples.csv')} "
     f"findings={nrows(TABLES / 'findings.csv')}"),
    ("06_Extract_assays",
     "qwen3.5:4b assay metadata from methods sections",
     "data/segmented_sections_markdown/",
     "tables/assays.csv + assays_checkpoint.json",
     "chat gate; JSON-only schema; checkpoint resume",
     "COMPLETED" if nrows(TABLES / "assays.csv") > 400 else "IN_PROGRESS"
     if (DATA / "assays_checkpoint.json").exists() else "NOT_STARTED",
     "SLURM catalogue_assays.sbatch"),
    ("07_Controlled_vocabulary",
     "Assemble controlled vocabulary from LLM-corrected terms",
     "catalogue_terms_llm.csv",
     "controlled_vocabulary.csv (in bundle)",
     "vocab counts consistent with LLM output",
     "NOT_STARTED", "produced by assemble_and_validate.py"),
    ("08_Assemble_bundle",
     "Build JSON bundle (pipe-strings -> arrays) + validate Draft202012",
     "all tables + vocabulary",
     "human_microbiome_data_catalogue.json + validation_report.json",
     "schema validation must pass allOf checks",
     "IN_PROGRESS", "SLURM 419620 afterok:419617"),
    ("09_Manual_verification",
     "Human review of AUTO_SEEDED/UNVERIFIED rows",
     "all tables",
     "verified rows",
     "reviewer sign-off per table",
     "NOT_STARTED", "pending human review; authors/keywords/backfill gaps known"),
]


def main() -> int:
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for st, act, inp, out, qc, status, notes in STAGES:
            w.writerow({"stage": st, "action": act, "input": inp, "output": out,
                        "quality_check": qc, "status": status, "owner": "opencode+jkalra",
                        "notes": notes})
        print(f"wrote {len(STAGES)} rows -> {OUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
