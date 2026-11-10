#!/usr/bin/env python
"""Stage 4b: seed cohorts, samples, findings tables from corpus records + annotations.

Reads:   data/corpus/records/HMPAPER_*.json          (G_study_metadata)
         data/corpus/annotations/findings.csv        (1,485 findings, 31 papers)
         data/catalogue/tables/datasets.csv          (dataset_id per paper_id, from stage 4)
Writes:  data/catalogue/tables/cohorts.csv           (1 cohort row per paper-study)
         data/catalogue/tables/samples.csv           (1 sample-group row per paper body-site x specimen-type)
         data/catalogue/tables/findings.csv          (annotation rows in template column set)

All rows AUTO_SEEDED / verification_status carries the annotation status.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

PROJECT_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REPO_ROOT = PROJECT_ROOT
while not (REPO_ROOT / "data" / "corpus").exists() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
PROJECT_ROOT = REPO_ROOT

RECORDS = PROJECT_ROOT / "data" / "corpus" / "records"
ANNOT = PROJECT_ROOT / "data" / "corpus" / "annotations" / "findings.csv"
TABLES = PROJECT_ROOT / "data" / "catalogue" / "tables"
DATASETS_CSV = TABLES / "datasets.csv"

COHORT_FIELDS = [
    "cohort_id", "paper_id", "dataset_id", "cohort_label", "cohort_role",
    "population_description", "country_or_region", "setting", "recruitment_method",
    "participant_count", "sample_count", "age_group", "age_summary",
    "sex_or_gender_reporting", "health_status", "inclusion_criteria",
    "exclusion_criteria", "key_covariates", "longitudinal", "timepoints",
    "evidence_location", "notes",
]
SAMPLE_FIELDS = [
    "sample_group_id", "paper_id", "dataset_id", "cohort_id", "body_site",
    "body_site_original", "sample_type", "collection_method",
    "collection_timepoint", "storage_condition", "preservation_method",
    "sample_count", "sample_processing", "notes",
]
FINDING_FIELDS = [
    "finding_id", "paper_id", "dataset_id", "cohort_id", "assay_id",
    "finding_domain", "taxon_or_feature", "taxonomic_rank",
    "comparison_or_exposure", "outcome", "direction", "effect_measure",
    "effect_estimate", "confidence_interval", "p_value", "q_value",
    "adjusted_covariates", "author_interpretation", "evidence_text",
    "evidence_location", "extraction_method", "verification_status", "notes",
]


def s(v) -> str:
    if isinstance(v, list):
        return "|".join(str(x) for x in v if x)
    return str(v or "").strip()


def main() -> int:
    # paper_id -> dataset_id map from stage-4 output
    ds_of = {}
    with DATASETS_CSV.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ds_of.setdefault(r["paper_id"], r["dataset_id"])

    cohorts, samples, findings = [], [], []
    cohort_of = {}  # paper_id -> cohort_id (single study per record, verified)
    sg_n = 0

    for i in range(1, 454):
        cid = f"HMPAPER_{i:06d}"
        rec = json.loads((RECORDS / f"{cid}.json").read_text())
        g = (rec.get("G_study_metadata") or [{}])
        st = g[0] if g else {}
        did = ds_of.get(cid, "")
        mb = st.get("microbiome") or {}

        copid = f"HMCOHORT_{i:06d}"
        cohort_of[cid] = copid

        # longitudinal inferred from reported timepoints > 1
        tp = st.get("number_of_time_points_reported")
        try:
            tp_n = int(str(tp)) if tp not in (None, "") else None
        except ValueError:
            tp_n = None
        longitudinal = "yes" if (tp_n or 0) > 1 else ("no" if tp_n == 1 else "")

        cohorts.append({
            "cohort_id": copid,
            "paper_id": cid,
            "dataset_id": did,
            "cohort_label": s(st.get("study_id")) or f"study 1 of {cid}",
            "cohort_role": "primary",
            "population_description": s(st.get("population_description")),
            "country_or_region": s(st.get("country_or_region")),
            "setting": s(st.get("recruitment_setting")),
            "recruitment_method": "",
            "participant_count": s(st.get("number_of_participants_reported")),
            "sample_count": s(st.get("number_of_biological_samples_reported")),
            "age_group": "",
            "age_summary": s(st.get("age_information")),
            "sex_or_gender_reporting": s(st.get("sex_gender_information_as_reported")),
            "health_status": s(st.get("health_conditions")),
            "inclusion_criteria": s(st.get("eligibility_criteria")),
            "exclusion_criteria": "",
            "key_covariates": s(st.get("confounders_reported")),
            "longitudinal": longitudinal,
            "timepoints": s(tp),
            "evidence_location": "G_study_metadata",
            "notes": s(st.get("source_row_notes")),
        })

        # sample-group rows: one per (body_site, specimen_type) pair when present
        sites = [s(x) for x in (mb.get("body_sites") or []) if s(x)]
        specs = [s(x) for x in (mb.get("specimen_types") or []) if s(x)]
        if sites or specs:
            pairs = [(a, b) for a in sites for b in specs] or \
                    [(a, "") for a in sites] or [("", b) for b in specs]
            for site, spec in pairs:
                sg_n += 1
                samples.append({
                    "sample_group_id": f"HMSAMPLE_{sg_n:06d}",
                    "paper_id": cid,
                    "dataset_id": did,
                    "cohort_id": copid,
                    "body_site": site,
                    "body_site_original": site,
                    "sample_type": spec,
                    "collection_method": "",
                    "collection_timepoint": "",
                    "storage_condition": "",
                    "preservation_method": "",
                    "sample_count": "",
                    "sample_processing": s(mb.get("sample_processing")),
                    "notes": "AUTO_SEEDED from G_study_metadata.microbiome",
                })

    # findings from annotations
    with ANNOT.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            pid = r["corpus_id"]
            assoc = s(r.get("association"))
            # direction from association wording
            d = {"positive_association": "increase",
                 "negative_association": "decrease",
                 "null_finding": "no_change",
                 "enriched": "increase",
                 "depleted": "decrease"}.get(assoc, "")
            findings.append({
                "finding_id": s(r.get("finding_id")),
                "paper_id": pid,
                "dataset_id": ds_of.get(pid, ""),
                "cohort_id": cohort_of.get(pid, ""),
                "assay_id": "",
                "finding_domain": s(r.get("claim_type")),
                "taxon_or_feature": s(r.get("taxon")),
                "taxonomic_rank": s(r.get("taxonomic_rank")),
                "comparison_or_exposure": s(r.get("condition_or_exposure")),
                "outcome": s(r.get("outcome")),
                "direction": d,
                "effect_measure": s(r.get("effect_measure")),
                "effect_estimate": s(r.get("effect_estimate")),
                "confidence_interval": s(r.get("confidence_interval")),
                "p_value": s(r.get("p_value")),
                "q_value": s(r.get("q_value")),
                "adjusted_covariates": "",
                "author_interpretation": "",
                "evidence_text": s(r.get("evidence_text")),
                "evidence_location": s(r.get("evidence_locator")),
                "extraction_method": "corpus_annotation",
                "verification_status": s(r.get("verification_status")) or "PENDING",
                "notes": s(r.get("body_site")),
            })

    for path, fields, rows in (
        (TABLES / "cohorts.csv", COHORT_FIELDS, cohorts),
        (TABLES / "samples.csv", SAMPLE_FIELDS, samples),
        (TABLES / "findings.csv", FINDING_FIELDS, findings),
    ):
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows):4d} rows -> {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
