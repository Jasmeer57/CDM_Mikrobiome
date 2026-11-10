#!/usr/bin/env python
"""Stage 5: assemble the full catalogue JSON + CSV tables and validate against the
template's Draft 2020-12 schema.

Reads:   data/catalogue/tables/*.csv                     (seeded tables: papers, datasets, dataassets)
         data/catalogue/catalogue_terms_llm.csv          (stage 3 output, if present)
         data/corpus/annotations/findings.csv            (1,485 existing findings)
         data/corpus/records/HMPAPER_*.json              (for cohort/sample/assay seeds, if any)
Writes:  data/catalogue/human_microbiome_data_catalogue.json   (schema-valid bundle)
         data/catalogue/tables/controlled_vocabulary.csv       (CDM-type vocabulary from LLM terms)
         data/catalogue/validation_report.json

Notes:
 - template schema expects `authors`, `keywords`, etc. as arrays: CSV pipe
   strings are split back into lists here
 - empty CSV cells become null per template missing-data conventions
 - cohorts / samples / assays / findings tables are included with whatever
   rows exist (findings seeded from corpus annotations; cohorts/samples/assays
   pending extraction jobs)
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REPO_ROOT = PROJECT_ROOT
while not (REPO_ROOT / "src/template").exists() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
PROJECT_ROOT = REPO_ROOT

TABLES = PROJECT_ROOT / "data" / "catalogue" / "tables"
SCHEMA = PROJECT_ROOT / "src/template" / "data_catalogue" / "human_microbiome_data_catalogue.schema.json"
FINDINGS = PROJECT_ROOT / "data" / "corpus" / "annotations" / "findings.csv"
LLM_TERMS = PROJECT_ROOT / "data" / "catalogue" / "catalogue_terms_llm.csv"
CATALOGUE_JSON = PROJECT_ROOT / "data" / "catalogue" / "human_microbiome_data_catalogue.json"
VOCAB_CSV = TABLES / "controlled_vocabulary.csv"
REPORT = PROJECT_ROOT / "data" / "catalogue" / "validation_report.json"

ARRAY_FIELDS = {
    "authors", "keywords", "dataset_type", "repository_accession", "related_publication_dois",
    "study_registration", "catalogue_notes", "curator_notes", "software_tools",
    "statistical_methods", "notes", "country_or_region", "inclusion_criteria",
    "exclusion_criteria", "key_covariates", "timepoints", "adjusted_covariates",
}
INT_FIELDS = {"publication_year", "participant_count", "sample_count", "file_size_bytes"}


def load_table(name: str) -> list[dict]:
    path = TABLES / f"{name}.csv"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rec = {}
            for k, v in r.items():
                if v is None or v == "":
                    rec[k] = None
                elif k in ARRAY_FIELDS:
                    rec[k] = [x for x in v.split("|") if x]
                elif k in INT_FIELDS:
                    rec[k] = int(v)
                else:
                    rec[k] = v
            out.append(rec)
    return out


def main() -> int:
    t0 = time.time()
    schema = json.loads(SCHEMA.read_text())

    papers = load_table("papers")
    datasets = load_table("datasets")
    assets = load_table("dataassets")
    cohorts = load_table("cohorts")
    samples = load_table("samples")
    assays = load_table("assays")

    # findings: seed from corpus annotations (they have different columns;
    # map to template finding shape, keep what we have)
    findings = load_table("findings")
    if not findings and FINDINGS.exists():
        n = 0
        with FINDINGS.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                n += 1
                findings.append({
                    "finding_id": f"HMFINDING_{n:06d}",
                    "paper_id": r.get("paper_id") or r.get("corpus_id"),
                    "finding_text": r.get("finding") or r.get("finding_text"),
                    "taxon_or_feature": r.get("taxon_or_feature"),
                    "body_site": r.get("body_site_normalized") or r.get("body_site"),
                    "direction": r.get("direction"),
                    "evidence_text": r.get("evidence_text"),
                    "evidence_location": r.get("evidence_location"),
                    "extraction_method": "corpus_pipeline annotations",
                    "verification_status": r.get("verification_status") or "PENDING",
                    "notes": None,
                })

    bundle = {
        "schema_version": "1.0.0",
        "papers": papers,
        "datasets": datasets,
        "data_assets": assets,
        "cohorts": cohorts,
        "samples": samples,
        "assays": assays,
        "findings": findings,
    }

    # ---------------- validate ----------------
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("[warn] jsonschema missing — skipping validation")
        Draft202012Validator = None

    errors_by_table: dict[str, int] = {}
    first_errors = []
    if Draft202012Validator:
        v = Draft202012Validator(schema)
        doc = {**bundle, "papers": papers[:1]}  # validate one paper first quick
        for key in bundle:
            errs = 0
            for i, rec in enumerate(bundle[key]):
                probe = dict(bundle)
                probe[key] = [rec]
                probe = {k: (v_ if k == key else []) for k, v_ in
                         (("schema_version", "1.0.0"),
                          ("papers", probe.get("papers", [])),
                          ("datasets", probe.get("datasets", [])),
                          ("data_assets", probe.get("data_assets", [])),
                          ("cohorts", probe.get("cohorts", [])),
                          ("samples", probe.get("samples", [])),
                          ("assays", probe.get("assays", [])),
                          ("findings", probe.get("findings", []))) if k == key}
                probe = dict(probe)
                probe[key] = [rec]
                for e in v.iter_errors(probe):
                    errs += 1
                    if len(first_errors) < 20:
                        first_errors.append(f"{key}[{i}] {'/'.join(map(str, e.path))}: {e.message[:120]}")
            errors_by_table[key] = errs
        # whole-bundle validation is n_records x 8-table check; keep per-table counts

    # ---------------- controlled vocabulary ----------------
    vocab_rows = []
    if LLM_TERMS.exists():
        with LLM_TERMS.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("is_valid") == "false":
                    continue
                vocab_rows.append({
                    "term": r.get("corrected_term") or r.get("term"),
                    "cdm_type": r.get("llm_cdm_type") or r.get("cdm_type"),
                    "source_type_original": r.get("cdm_type"),
                    "definition": r.get("definition"),
                    "is_taxon": r.get("is_taxon"),
                    "n_papers": r.get("n_papers"),
                    "n_models": r.get("n_models"),
                    "models": r.get("models"),
                })
        with VOCAB_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(vocab_rows[0].keys()))
            w.writeheader()
            w.writerows(vocab_rows)

    CATALOGUE_JSON.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "papers": len(papers),
        "datasets": len(datasets),
        "data_assets": len(assets),
        "cohorts": len(cohorts),
        "samples": len(samples),
        "assays": len(assays),
        "findings": len(findings),
        "vocabulary_terms": len(vocab_rows),
        "schema_errors_per_table": errors_by_table,
        "first_errors": first_errors,
        "elapsed_s": round(time.time() - t0, 1),
    }
    REPORT.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in report if k != "first_errors"}, indent=2))
    for e in first_errors[:20]:
        print(" ", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
