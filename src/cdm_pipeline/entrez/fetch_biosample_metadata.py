#!/usr/bin/env python
"""
Fetch per-sample demographic metadata from NCBI BioSample for all 482 BioProjects.

Queries BioSample via SRS accessions from sample_metadata.tsv.  For each project
we fetch a handful of samples (default 5) and aggregate ALL harmonized attributes
into a project-level summary — age ranges, sex distribution, body_site, host,
geo_loc, diet, disease, BMI, etc.

Output:
  paper/_multi_ner_runs/cdm_output/biosample_metadata.json
  paper/_multi_ner_runs/cdm_output/biosample_metadata.tsv

Usage:
  python -m cdm_pipeline.entrez.fetch_biosample_metadata [--samples-per-project 5] [--delay 0.35]
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Dataset path (supports CDM_SAMPLES_PAPER override). Imported via the repo root
# so this stays runnable as a standalone script, not only as `python -m`.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from cdm_pipeline import paths as _paths  # noqa: E402

SAMPLE_METADATA = _paths.samples_paper_dir() / "sample_metadata.tsv"
OUTPUT_DIR = PROJECT_ROOT / "paper" / "_multi_ner_runs" / "cdm_output"

ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "jkalra@uni-potsdam.de")
ENTREZ_API_KEY = os.environ.get("ENTREZ_API_KEY", "")


def _params(extra: dict) -> dict:
    p = {"email": ENTREZ_EMAIL, "tool": "microbiome-cdm"}
    if ENTREZ_API_KEY:
        p["api_key"] = ENTREZ_API_KEY
    p.update(extra)
    return p


def load_srs_per_project(n_per_project: int = 5) -> Dict[str, List[str]]:
    """Load SRS accessions from sample_metadata.tsv, sample n_per_project per project."""
    proj_srs: Dict[str, List[str]] = defaultdict(list)
    with open(SAMPLE_METADATA, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            proj = (row.get("project") or "").strip()
            srs = (row.get("srs") or "").strip()
            if proj and srs:
                if len(proj_srs[proj]) < n_per_project:
                    proj_srs[proj].append(srs)
    return dict(proj_srs)


def esearch_biosample(srs: str) -> Optional[str]:
    """Look up BioSample ID by SRS accession."""
    try:
        r = requests.get(f"{EUTILS}/esearch.fcgi", params=_params({
            "db": "biosample", "term": srs, "retmax": 1,
        }), timeout=30)
        root = ET.fromstring(r.text)
        id_elem = root.find(".//Id")
        return id_elem.text if id_elem is not None else None
    except Exception:
        return None


def efetch_biosample(bs_id: str) -> Optional[dict]:
    """Fetch and parse a BioSample record."""
    try:
        r = requests.get(f"{EUTILS}/efetch.fcgi", params=_params({
            "db": "biosample", "id": bs_id, "rettype": "xml",
        }), timeout=30)
        root = ET.fromstring(r.text)
    except Exception:
        return None

    for sample in root.iter("BioSample"):
        acc = sample.attrib.get("accession", "")
        attrs = {}
        for attr in sample.iter("Attribute"):
            name = attr.attrib.get("harmonized_name", "") or attr.attrib.get("attribute_name", "")
            val = (attr.text or "").strip()
            if val and val.lower() not in ("missing", "not applicable", "not collected", "unknown"):
                attrs[name] = val
        return {"accession": acc, "attributes": attrs}
    return None


# ---------------------------------------------------------------------------
# Attribute aggregation
# ---------------------------------------------------------------------------

# Interesting demographic / clinical / lifestyle attributes
DEMOGRAPHIC_ATTRS = [
    "age", "host_age", "age years", "age cat", "birth year",
    "host_age_units", "age_units",
    "sex", "host_sex", "gender",
    "host", "host_common_name", "host_taxid",
    "host_body_mass_index", "body_mass_index", "host weight", "weight kg",
    "height cm",
    "host_life_stage",
    "race", "race2", "hispanic_latino",
    "nationality", "country of birth", "country_residence",
    "geo_loc_name", "latitude", "longitude", "lat_lon",
    "env_medium", "body_site", "host_body_habitat", "host_tissue_sampled",
    "host_body_product", "sample_type",
    "collection_date", "collection_timestamp", "time", "timepoint",
    "disease", "disease_activity", "condition", "clinical condition",
    "host_disease", "host_phenotype",
    "intervention_group", "experimental group",
    "ibd", "ibd_diagnosis_refined", "ibs",
    "diabetes", "diabetes type",
    "cancer", "cancer treatment",
    "mental_illness", "depression",
    "cardiovascular_disease", "kidney_disease", "liver_disease",
    "thyroid", "autoimmune",
    "pregnant",
    "diet type", "specialized_diet",
    "antibiotic_history",
    "probiotic_frequency",
    "smoking_frequency",
    "alcohol_frequency", "alcohol consumption",
    "exercise_frequency",
    "sleep_duration",
    "bowel_movement_frequency",
    "csection",
    "breastmilk_formula_ensure",
    "pets",
    "dog", "cat",
    "livingwith",
    "level_of_education",
    "nail_biter",
    "flossing_frequency", "teethbrushing_frequency",
    "deodorant_use",
    "cosmetics_frequency",
]

# Map to canonical categories
ATTR_CATEGORY = {
    "age": "age", "host_age": "age", "age years": "age", "age cat": "age",
    "birth year": "age", "host_age_units": "age_units", "age_units": "age_units",
    "sex": "sex", "host_sex": "sex", "gender": "sex",
    "host": "host", "host_common_name": "host", "host_taxid": "host",
    "host_body_mass_index": "bmi", "body_mass_index": "bmi",
    "host weight": "weight", "weight kg": "weight", "height cm": "height",
    "host_life_stage": "life_stage",
    "race": "race", "race2": "race", "hispanic_latino": "ethnicity",
    "nationality": "nationality", "country of birth": "nationality",
    "country_residence": "nationality",
    "geo_loc_name": "geography", "latitude": "geography", "longitude": "geography",
    "lat_lon": "geography",
    "env_medium": "body_site", "body_site": "body_site",
    "host_body_habitat": "body_site", "host_tissue_sampled": "body_site",
    "host_body_product": "body_site", "sample_type": "sample_type",
    "collection_date": "collection_date", "collection_timestamp": "collection_date",
    "time": "timepoint", "timepoint": "timepoint",
    "disease": "disease", "disease_activity": "disease",
    "condition": "condition", "clinical condition": "condition",
    "host_disease": "disease", "host_phenotype": "phenotype",
    "intervention_group": "intervention", "experimental group": "intervention",
    "ibd": "disease_flag", "ibd_diagnosis_refined": "disease_flag",
    "ibs": "disease_flag",
    "diabetes": "disease_flag", "diabetes type": "disease_flag",
    "cancer": "disease_flag", "cancer treatment": "treatment",
    "mental_illness": "disease_flag",
    "cardiovascular_disease": "disease_flag",
    "kidney_disease": "disease_flag",
    "liver_disease": "disease_flag",
    "thyroid": "disease_flag",
    "autoimmune": "disease_flag",
    "pregnant": "pregnancy",
    "diet type": "diet", "specialized_diet": "diet",
    "antibiotic_history": "antibiotics",
    "probiotic_frequency": "probiotics",
    "smoking_frequency": "smoking",
    "alcohol_frequency": "alcohol", "alcohol consumption": "alcohol",
    "exercise_frequency": "exercise",
    "sleep_duration": "sleep",
    "bowel_movement_frequency": "lifestyle",
    "csection": "birth_mode",
    "breastmilk_formula_ensure": "infant_feeding",
    "dog": "pets", "cat": "pets",
    "level_of_education": "education",
}


def aggregate_samples(samples: List[dict]) -> dict:
    """Aggregate BioSample records into a project-level summary."""
    if not samples:
        return {}

    # Collect all attribute values across samples
    attr_values = defaultdict(list)
    all_attr_keys = set()
    for s in samples:
        for k, v in s["attributes"].items():
            attr_values[k].append(v)
            all_attr_keys.add(k)

    summary = {
        "n_samples_checked": len(samples),
        "n_samples_found": sum(1 for s in samples if s),
        "all_attribute_keys": sorted(all_attr_keys),
    }

    # Extract structured demographic info
    # Age
    ages = []
    for key in ["age", "host_age", "age years", "birth year"]:
        for v in attr_values.get(key, []):
            try:
                if "-" in v:
                    parts = v.split("-")
                    for p in parts:
                        try:
                            ages.append(float(p.strip()))
                        except ValueError:
                            pass
                else:
                    ages.append(float(v))
            except ValueError:
                pass
    if ages:
        summary["age_values"] = sorted(ages)
        summary["age_min"] = min(ages)
        summary["age_max"] = max(ages)
        summary["age_mean"] = round(sum(ages) / len(ages), 1)

    # Sex / gender
    sex_counts = Counter()
    for key in ["sex", "host_sex", "gender"]:
        for v in attr_values.get(key, []):
            vl = v.lower().strip()
            if vl in ("male", "m"):
                sex_counts["male"] += 1
            elif vl in ("female", "f"):
                sex_counts["female"] += 1
            elif vl and vl not in ("not provided", "unspecified"):
                sex_counts[vl] += 1
    if sex_counts:
        summary["sex_distribution"] = dict(sex_counts)
        summary["n_male"] = sex_counts.get("male", 0)
        summary["n_female"] = sex_counts.get("female", 0)

    # BMI
    bmis = []
    for key in ["host_body_mass_index", "body_mass_index"]:
        for v in attr_values.get(key, []):
            try:
                bmis.append(float(v))
            except ValueError:
                pass
    if bmis:
        summary["bmi_values"] = sorted(bmis)
        summary["bmi_mean"] = round(sum(bmis) / len(bmis), 1)

    # Geography
    geos = set()
    for key in ["geo_loc_name"]:
        for v in attr_values.get(key, []):
            geos.add(v)
    if geos:
        summary["geo_locations"] = sorted(geos)

    # Body site
    body_sites = set()
    for key in ["env_medium", "body_site", "host_body_habitat", "host_tissue_sampled", "host_body_product"]:
        for v in attr_values.get(key, []):
            body_sites.add(v)
    if body_sites:
        summary["body_sites"] = sorted(body_sites)

    # Host
    hosts = set()
    for key in ["host", "host_common_name"]:
        for v in attr_values.get(key, []):
            hosts.add(v)
    if hosts:
        summary["host_organisms"] = sorted(hosts)

    # Race / ethnicity
    races = set()
    for key in ["race", "race2"]:
        for v in attr_values.get(key, []):
            races.add(v)
    if races:
        summary["races"] = sorted(races)

    # Nationality
    nats = set()
    for key in ["nationality", "country of birth", "country_residence"]:
        for v in attr_values.get(key, []):
            nats.add(v)
    if nats:
        summary["nationalities"] = sorted(nats)

    # Disease / condition
    diseases = set()
    for key in ["disease", "disease_activity", "host_disease", "condition", "clinical condition"]:
        for v in attr_values.get(key, []):
            diseases.add(v)
    if diseases:
        summary["diseases"] = sorted(diseases)

    # Disease flags
    disease_flags = {}
    for key in ["ibd", "ibs", "diabetes", "cancer", "mental_illness",
                "cardiovascular_disease", "kidney_disease", "liver_disease",
                "thyroid", "autoimmune"]:
        for v in attr_values.get(key, []):
            disease_flags[key] = v
    if disease_flags:
        summary["disease_flags"] = disease_flags

    # Intervention
    interventions = set()
    for key in ["intervention_group", "experimental group"]:
        for v in attr_values.get(key, []):
            interventions.add(v)
    if interventions:
        summary["intervention_groups"] = sorted(interventions)

    # Diet
    diets = set()
    for key in ["diet type", "specialized_diet"]:
        for v in attr_values.get(key, []):
            diets.add(v)
    if diets:
        summary["diet_types"] = sorted(diets)

    # Antibiotics
    abx = set()
    for v in attr_values.get("antibiotic_history", []):
        abx.add(v)
    if abx:
        summary["antibiotic_history"] = sorted(abx)

    # Probiotics
    probs = set()
    for v in attr_values.get("probiotic_frequency", []):
        probs.add(v)
    if probs:
        summary["probiotic_use"] = sorted(probs)

    # Smoking
    smokes = set()
    for v in attr_values.get("smoking_frequency", []):
        smokes.add(v)
    if smokes:
        summary["smoking_status"] = sorted(smokes)

    # Lifestyle attributes present
    lifestyle = {}
    for key in ["alcohol_frequency", "exercise_frequency", "sleep_duration",
                "bowel_movement_frequency", "pregnant", "csection",
                "breastmilk_formula_ensure", "level_of_education"]:
        vals = attr_values.get(key, [])
        if vals:
            lifestyle[key] = sorted(set(vals))
    if lifestyle:
        summary["lifestyle"] = lifestyle

    # Store ALL raw attributes for maximum flexibility
    summary["all_attributes_sample"] = samples[0].get("attributes", {}) if samples else {}

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(samples_per_project: int = 5, delay: float = 0.35, resume: bool = True):
    proj_srs = load_srs_per_project(samples_per_project)
    print(f"Projects to query: {len(proj_srs)}")
    print(f"Samples per project: {samples_per_project}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "biosample_metadata.json"
    tsv_path = OUTPUT_DIR / "biosample_metadata.tsv"

    existing = {}
    if resume and json_path.exists():
        with open(json_path) as f:
            existing = json.load(f)
        print(f"Resuming: {len(existing)} projects already fetched")

    results = dict(existing)
    to_process = [(p, srs_list) for p, srs_list in proj_srs.items() if p not in results]

    print(f"To process: {len(to_process)}")
    print()

    n_found = 0
    n_not_found = 0

    for i, (proj, srs_list) in enumerate(to_process):
        samples = []
        for srs in srs_list:
            bs_id = esearch_biosample(srs)
            time.sleep(delay)
            if not bs_id:
                continue
            rec = efetch_biosample(bs_id)
            time.sleep(delay)
            if rec:
                samples.append(rec)

        if samples:
            agg = aggregate_samples(samples)
            agg["bioproject_id"] = proj
            results[proj] = agg
            n_found += 1
            n_keys = len(agg.get("all_attribute_keys", []))
            if (i + 1) % 25 == 0 or i < 5:
                print(f"  [{i+1}/{len(to_process)}] {proj}: {len(samples)} samples, "
                      f"{n_keys} attrs, age={agg.get('age_min','')}-{agg.get('age_max','')}, "
                      f"sex={agg.get('sex_distribution','')}, "
                      f"site={agg.get('body_sites','')}, geo={agg.get('geo_locations','')}")
        else:
            results[proj] = {"bioproject_id": proj, "n_samples_found": 0}
            n_not_found += 1
            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(to_process)}] {proj}: no BioSamples found")

        if (i + 1) % 50 == 0:
            with open(json_path, "w") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"    Checkpoint saved ({len(results)} projects)")

    # Final save
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # TSV
    tsv_fields = [
        "bioproject_id", "n_samples_checked", "n_samples_found",
        "age_min", "age_max", "age_mean",
        "n_male", "n_female", "sex_distribution",
        "bmi_mean",
        "geo_locations", "body_sites", "host_organisms",
        "races", "nationalities", "diseases", "disease_flags",
        "intervention_groups", "diet_types",
        "antibiotic_history", "probiotic_use", "smoking_status",
    ]
    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=tsv_fields, extrasaction="ignore")
        writer.writeheader()
        for proj in sorted(results):
            row = dict(results[proj])
            for k in ("geo_locations", "body_sites", "host_organisms", "races",
                      "nationalities", "diseases", "intervention_groups", "diet_types",
                      "antibiotic_history", "probiotic_use", "smoking_status"):
                if isinstance(row.get(k), list):
                    row[k] = "; ".join(str(v) for v in row[k])
            if isinstance(row.get("sex_distribution"), dict):
                row["sex_distribution"] = "; ".join(f"{k}={v}" for k, v in row["sex_distribution"].items())
            if isinstance(row.get("disease_flags"), dict):
                row["disease_flags"] = "; ".join(f"{k}={v}" for k, v in row["disease_flags"].items())
            writer.writerow(row)

    # Summary
    total = len(results)
    n_with_age = sum(1 for r in results.values() if "age_min" in r)
    n_with_sex = sum(1 for r in results.values() if "sex_distribution" in r)
    n_with_bmi = sum(1 for r in results.values() if "bmi_mean" in r)
    n_with_geo = sum(1 for r in results.values() if "geo_locations" in r)
    n_with_body = sum(1 for r in results.values() if "body_sites" in r)
    n_with_disease = sum(1 for r in results.values() if "diseases" in r)
    n_with_race = sum(1 for r in results.values() if "races" in r)
    n_with_diet = sum(1 for r in results.values() if "diet_types" in r)
    n_with_samples = sum(1 for r in results.values() if r.get("n_samples_found", 0) > 0)

    print()
    print("=" * 70)
    print("BioSample Metadata Fetch Summary")
    print("=" * 70)
    print(f"Total projects:              {total}")
    print(f"  with BioSamples found:     {n_with_samples} ({n_with_samples/total*100:.1f}%)")
    print(f"  with age data:             {n_with_age} ({n_with_age/total*100:.1f}%)")
    print(f"  with sex data:             {n_with_sex} ({n_with_sex/total*100:.1f}%)")
    print(f"  with BMI data:             {n_with_bmi} ({n_with_bmi/total*100:.1f}%)")
    print(f"  with geography:            {n_with_geo} ({n_with_geo/total*100:.1f}%)")
    print(f"  with body site:            {n_with_body} ({n_with_body/total*100:.1f}%)")
    print(f"  with disease info:         {n_with_disease} ({n_with_disease/total*100:.1f}%)")
    print(f"  with race data:            {n_with_race} ({n_with_race/total*100:.1f}%)")
    print(f"  with diet info:            {n_with_diet} ({n_with_diet/total*100:.1f}%)")
    print(f"JSON: {json_path}")
    print(f"TSV:  {tsv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch BioSample demographic metadata")
    parser.add_argument("--samples-per-project", type=int, default=5,
                        help="SRS accessions to query per project")
    parser.add_argument("--delay", type=float, default=0.35, help="Delay between API calls")
    parser.add_argument("--no-resume", action="store_true", help="Don't resume")
    args = parser.parse_args()
    run(samples_per_project=args.samples_per_project, delay=args.delay,
        resume=not args.no_resume)
