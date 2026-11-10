#!/usr/bin/env python
"""
Merge ALL metadata for all 482 BioProject accessions into one comprehensive file.

Sources merged:
  1. projects.csv (482) — DOI, amplicon, kit, condition, sample_type, subjects
  2. sample_metadata.tsv (482) — SRS, SRR, instrument, geo_loc, pubdate, total_bases
  3. bioproject_data_export.json (422) — title, study_title
  4. pubmed_metadata.json (412) — PMID, MeSH (w/ qualifiers), chemicals, authors,
     ORCIDs, references, grants, COI, journal, abstract, pub dates, keywords, etc.
  5. missing_papers_metadata.json (39) — NCBI BioProject, ENA, PubMed title search
  6. biosample_metadata.json (482) — per-sample demographics: age, sex, BMI,
     geography, body_site, disease, diet, race, host, lifestyle attributes

MeSH descriptors are categorized into: age_groups, sex, study_design, population,
sample_material, methods, analysis, diseases, geography.

Output:
  paper/_multi_ner_runs/cdm_output/all_studies_metadata.json
  paper/_multi_ner_runs/cdm_output/all_studies_metadata.tsv
"""

import csv
import json
from collections import Counter
from pathlib import Path

from cdm_pipeline import paths as _paths
from cdm_pipeline.entrez.mesh_categorizer import categorize_mesh_headings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAMPLES_PAPER = _paths.samples_paper_dir()
PROJECTS_CSV = _SAMPLES_PAPER / "projects.csv"
SAMPLE_METADATA = _SAMPLES_PAPER / "sample_metadata.tsv"
BIOPROJECT_EXPORT = _paths.bioproject_export()
PAPERS_DIR = _paths.papers_txt()
OUTPUT_DIR = PROJECT_ROOT / "paper" / "_multi_ner_runs" / "cdm_output"
PUBMED_JSON = OUTPUT_DIR / "pubmed_metadata.json"
MISSING_JSON = OUTPUT_DIR / "missing_papers_metadata.json"
BIOSAMPLE_JSON = OUTPUT_DIR / "biosample_metadata.json"


def load_projects_csv() -> dict:
    with open(PROJECTS_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return {row["project"].strip(): row for row in reader}


def load_sample_metadata() -> dict:
    per_project = {}
    with open(SAMPLE_METADATA, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            acc = row.get("project", "").strip()
            if not acc:
                continue
            if acc not in per_project:
                per_project[acc] = {
                    "n_samples": 0,
                    "instruments": set(),
                    "geo_locs": set(),
                    "library_strategies": set(),
                    "library_sources": set(),
                    "pubdates": set(),
                    "total_bases": 0,
                    "n_runs": 0,
                    "srrs": set(),
                    "srss": set(),
                }
            p = per_project[acc]
            p["n_samples"] += 1
            p["n_runs"] += 1
            if row.get("instrument"):
                p["instruments"].add(row["instrument"])
            if row.get("geo_loc_name"):
                p["geo_locs"].add(row["geo_loc_name"])
            if row.get("library_strategy"):
                p["library_strategies"].add(row["library_strategy"])
            if row.get("library_source"):
                p["library_sources"].add(row["library_source"])
            if row.get("pubdate"):
                p["pubdates"].add(row["pubdate"])
            if row.get("srr"):
                p["srrs"].add(row["srr"])
            if row.get("srs"):
                p["srss"].add(row["srs"])
            try:
                p["total_bases"] += int(row.get("total_bases", 0))
            except ValueError:
                pass
    for acc, p in per_project.items():
        for k in ("instruments", "geo_locs", "library_strategies", "library_sources", "pubdates", "srrs", "srss"):
            p[k] = sorted(p[k])
    return per_project


def load_bioproject_export() -> dict:
    if not BIOPROJECT_EXPORT.exists():
        return {}
    with open(BIOPROJECT_EXPORT) as f:
        data = json.load(f)
    return {bp["bioproject_id"]: bp for bp in data.get("bioprojects", [])}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def get_all_accessions() -> set:
    accs = set()
    accs.update(load_projects_csv().keys())
    accs.update(load_sample_metadata().keys())
    return accs


def _join_list(val) -> str:
    if isinstance(val, list):
        return "; ".join(str(v) for v in val)
    return str(val) if val else ""


def _join_dict(val) -> str:
    if isinstance(val, dict):
        return "; ".join(f"{k}={v}" for k, v in val.items())
    return str(val) if val else ""


def run():
    print("Loading all sources...")
    projects = load_projects_csv()
    print(f"  projects.csv: {len(projects)}")

    sample_meta = load_sample_metadata()
    print(f"  sample_metadata.tsv: {len(sample_meta)} projects")

    bp_export = load_bioproject_export()
    print(f"  bioproject_data_export.json: {len(bp_export)}")

    pubmed = load_json(PUBMED_JSON)
    print(f"  pubmed_metadata.json: {len(pubmed)}")

    missing = load_json(MISSING_JSON)
    print(f"  missing_papers_metadata.json: {len(missing)}")

    biosample = load_json(BIOSAMPLE_JSON)
    print(f"  biosample_metadata.json: {len(biosample)}")

    papers_txt = {f.stem for f in PAPERS_DIR.glob("*.txt")}
    print(f"  data/papers_txt/: {len(papers_txt)}")

    all_accs = sorted(set(projects.keys()) | set(sample_meta.keys()))
    print(f"\nTotal unique BioProject accessions: {len(all_accs)}")
    print()

    merged = {}
    for acc in all_accs:
        record = {"bioproject_id": acc}

        # 1. projects.csv
        pcsv = projects.get(acc, {})
        record["doi"] = pcsv.get("link", "").strip().replace("https://doi.org/", "").replace("http://doi.org/", "")
        record["amplicon"] = pcsv.get("amplicon", "").strip()
        record["avg_read_length"] = pcsv.get("avg_length", "").strip()
        record["bead_beating"] = pcsv.get("bead_beating", "").strip()
        record["extraction_kit"] = pcsv.get("kit", "").strip()
        record["sample_type"] = pcsv.get("sample_type", "").strip()
        record["condition"] = pcsv.get("condition", "").strip()
        record["subjects"] = pcsv.get("subjects", "").strip()
        record["notes"] = pcsv.get("notes", "").strip()

        # 2. sample_metadata.tsv
        sm = sample_meta.get(acc, {})
        record["n_samples"] = sm.get("n_samples", 0)
        record["n_runs"] = sm.get("n_runs", 0)
        record["instruments"] = sm.get("instruments", [])
        record["geo_locations"] = sm.get("geo_locs", [])
        record["library_strategies"] = sm.get("library_strategies", [])
        record["library_sources"] = sm.get("library_sources", [])
        record["pubdates"] = sm.get("pubdates", [])
        record["total_bases"] = sm.get("total_bases", 0)
        record["srr_count"] = len(sm.get("srrs", []))
        record["srs_count"] = len(sm.get("srss", []))

        # 3. bioproject_data_export.json
        bp = bp_export.get(acc, {})
        record["bioproject_title"] = bp.get("title", "")
        record["bioproject_study_title"] = bp.get("study_title", "")

        # 4. PubMed metadata (enriched v2)
        pm = pubmed.get(acc, {})
        if pm and pm.get("pmid"):
            record["pmid"] = pm.get("pmid", "")
            record["pub_title"] = pm.get("title", "")
            record["abstract"] = pm.get("abstract", "")
            record["abstract_structured"] = pm.get("abstract_structured", [])
            record["journal"] = pm.get("journal", "")
            record["journal_iso_abbrev"] = pm.get("journal_iso_abbrev", "")
            record["journal_nlm_id"] = pm.get("journal_nlm_id", "")
            record["journal_country"] = pm.get("journal_country", "")
            record["pub_year"] = pm.get("pub_year", "")
            record["pub_month"] = pm.get("pub_month", "")
            record["pub_day"] = pm.get("pub_day", "")
            record["volume"] = pm.get("volume", "")
            record["issue"] = pm.get("issue", "")
            record["pages"] = pm.get("pages", "")
            record["language"] = pm.get("language", "")
            record["publication_types"] = pm.get("publication_types", [])
            record["publication_status"] = pm.get("publication_status", "")

            # Authors (full detail)
            record["authors"] = pm.get("authors", [])
            record["n_authors"] = pm.get("n_authors", 0)
            record["author_names"] = pm.get("author_names", [])
            record["author_orcids"] = pm.get("author_orcids", [])
            record["n_orcids"] = len(record["author_orcids"])
            record["author_affiliations"] = pm.get("author_affiliations", [])

            # MeSH headings (full detail with qualifiers)
            record["mesh_headings"] = pm.get("mesh_headings", [])
            record["mesh_terms"] = pm.get("mesh_terms", [])
            record["n_mesh"] = pm.get("n_mesh", 0)
            record["mesh_major_topics"] = pm.get("mesh_major_topics", [])
            record["mesh_qualifiers"] = pm.get("mesh_qualifiers", [])

            # MeSH categories
            mesh_cats = categorize_mesh_headings(pm.get("mesh_headings", []))
            record["mesh_age_groups"] = [h["descriptor"] for h in mesh_cats["age_groups"]]
            record["mesh_sex"] = [h["descriptor"] for h in mesh_cats["sex"]]
            record["mesh_study_design"] = [h["descriptor"] for h in mesh_cats["study_design"]]
            record["mesh_population"] = [h["descriptor"] for h in mesh_cats["population"]]
            record["mesh_sample_material"] = [h["descriptor"] for h in mesh_cats["sample_material"]]
            record["mesh_methods"] = [h["descriptor"] for h in mesh_cats["methods"]]
            record["mesh_analysis"] = [h["descriptor"] for h in mesh_cats["analysis"]]
            record["mesh_diseases"] = [h["descriptor"] for h in mesh_cats["diseases"]]
            record["mesh_geography"] = [h["descriptor"] for h in mesh_cats["geography"]]
            record["mesh_other"] = [h["descriptor"] for h in mesh_cats["other"]]

            # Chemicals
            record["chemicals"] = pm.get("chemicals", [])
            record["chemical_names"] = pm.get("chemical_names", [])

            # Keywords
            record["keywords"] = pm.get("keywords", [])
            record["keyword_details"] = pm.get("keyword_details", [])

            # Grants
            record["grants"] = pm.get("grants", [])
            record["grant_ids"] = pm.get("grant_ids", [])

            # IDs
            record["pmc_id"] = pm.get("pmc_id", "")
            record["pii"] = pm.get("pii", "")
            record["issn_print"] = pm.get("issn_print", "")
            record["issn_electronic"] = pm.get("issn_electronic", "")
            record["issn_linking"] = pm.get("issn_linking", "")

            # Dates
            record["date_received"] = pm.get("date_received", {})
            record["date_accepted"] = pm.get("date_accepted", {})
            record["date_epublish"] = pm.get("date_epublish", {})
            record["date_ppublish"] = pm.get("date_ppublish", {})
            record["history_dates"] = pm.get("history_dates", {})

            # References
            record["references"] = pm.get("references", [])
            record["n_references"] = pm.get("n_references", 0)
            record["reference_pmids"] = pm.get("reference_pmids", [])

            # Other
            record["coi_statement"] = pm.get("coi_statement", "")
            record["copyright"] = pm.get("copyright", "")
            record["data_banks"] = pm.get("data_banks", [])
            record["citation_subsets"] = pm.get("citation_subsets", [])
        else:
            # Empty defaults for all PubMed fields
            for k in ["pmid", "pub_title", "abstract", "journal", "journal_iso_abbrev",
                      "journal_nlm_id", "journal_country", "pub_year", "pub_month",
                      "pub_day", "volume", "issue", "pages", "language",
                      "publication_status", "pmc_id", "pii", "issn_print",
                      "issn_electronic", "issn_linking", "coi_statement", "copyright"]:
                record[k] = ""
            for k in ["authors", "author_names", "author_orcids", "author_affiliations",
                      "mesh_headings", "mesh_terms", "mesh_major_topics", "mesh_qualifiers",
                      "chemicals", "chemical_names", "keywords", "keyword_details",
                      "grants", "grant_ids", "references", "reference_pmids",
                      "data_banks", "citation_subsets", "publication_types",
                      "abstract_structured", "history_dates", "date_received",
                      "date_accepted", "date_epublish", "date_ppublish"]:
                record[k] = []
            for k in ["n_authors", "n_orcids", "n_mesh", "n_references"]:
                record[k] = 0
            for k in ["mesh_age_groups", "mesh_sex", "mesh_study_design",
                      "mesh_population", "mesh_sample_material", "mesh_methods",
                      "mesh_analysis", "mesh_diseases", "mesh_geography", "mesh_other"]:
                record[k] = []

        # 5. Missing papers metadata (for 39 without text)
        miss = missing.get(acc, {})
        if miss:
            ncbi = miss.get("ncbi_bioproject", {})
            ena = miss.get("ena") or {}
            miss_pubmed = miss.get("pubmed") or {}

            # Fill title if empty
            if not record["pub_title"]:
                record["pub_title"] = ncbi.get("title", "") or ena.get("title", "")
            if not record["bioproject_title"]:
                record["bioproject_title"] = ncbi.get("title", "") or ena.get("title", "")
            record["ncbi_description"] = ncbi.get("description", "") or ena.get("description", "")
            record["ncbi_organism"] = ncbi.get("organism", "") or ena.get("organism", "")
            record["ncbi_datatype"] = ncbi.get("datatype", "")
            record["submitting_center"] = ncbi.get("submitting_center", "") or ena.get("name", "")
            record["ena_n_runs"] = ena.get("n_runs", 0)
            record["ena_total_reads"] = ena.get("total_reads", 0)
            record["ena_total_bases"] = ena.get("total_bases", 0)
            record["ena_library_strategy"] = ena.get("library_strategy", "")
            record["ena_library_source"] = ena.get("library_source", "")
            record["ena_instrument_model"] = ena.get("instrument_model", "")

            # PubMed from title search
            if miss_pubmed and miss_pubmed.get("pmid"):
                record["pmid"] = miss_pubmed.get("pmid", "")
                if not record["abstract"]:
                    record["abstract"] = miss_pubmed.get("abstract", "")
                if not record["journal"]:
                    record["journal"] = miss_pubmed.get("journal", "")
                if not record["pub_year"]:
                    record["pub_year"] = miss_pubmed.get("pub_year", "")
                record["authors"] = miss_pubmed.get("authors", [])
                record["n_authors"] = miss_pubmed.get("n_authors", 0)
                record["mesh_terms"] = miss_pubmed.get("mesh_terms", [])
                record["n_mesh"] = miss_pubmed.get("n_mesh", 0)
                record["keywords"] = miss_pubmed.get("keywords", [])
                record["publication_types"] = miss_pubmed.get("publication_types", [])
        else:
            record["ncbi_description"] = ""
            record["ncbi_organism"] = ""
            record["ncbi_datatype"] = ""
            record["submitting_center"] = ""
            record["ena_n_runs"] = 0
            record["ena_total_reads"] = 0
            record["ena_total_bases"] = 0
            record["ena_library_strategy"] = ""
            record["ena_library_source"] = ""
            record["ena_instrument_model"] = ""

        # 6. BioSample demographics
        bs = biosample.get(acc, {})
        record["biosample_n_checked"] = bs.get("n_samples_checked", 0)
        record["biosample_n_found"] = bs.get("n_samples_found", 0)
        record["biosample_age_min"] = bs.get("age_min", "")
        record["biosample_age_max"] = bs.get("age_max", "")
        record["biosample_age_mean"] = bs.get("age_mean", "")
        record["biosample_sex_dist"] = bs.get("sex_distribution", {})
        record["biosample_n_male"] = bs.get("n_male", 0)
        record["biosample_n_female"] = bs.get("n_female", 0)
        record["biosample_bmi_mean"] = bs.get("bmi_mean", "")
        record["biosample_geo"] = bs.get("geo_locations", [])
        record["biosample_body_sites"] = bs.get("body_sites", [])
        record["biosample_host"] = bs.get("host_organisms", [])
        record["biosample_diseases"] = bs.get("diseases", [])
        record["biosample_disease_flags"] = bs.get("disease_flags", {})
        record["biosample_races"] = bs.get("races", [])
        record["biosample_nationalities"] = bs.get("nationalities", [])
        record["biosample_interventions"] = bs.get("intervention_groups", [])
        record["biosample_diet_types"] = bs.get("diet_types", [])
        record["biosample_antibiotics"] = bs.get("antibiotic_history", [])
        record["biosample_probiotics"] = bs.get("probiotic_use", [])
        record["biosample_smoking"] = bs.get("smoking_status", [])
        record["biosample_lifestyle"] = bs.get("lifestyle", {})
        record["biosample_all_attr_keys"] = bs.get("all_attribute_keys", [])

        # Flags
        record["has_full_text"] = acc in papers_txt
        record["has_pmid"] = bool(record.get("pmid"))
        record["has_mesh"] = record.get("n_mesh", 0) > 0
        record["has_doi"] = bool(record.get("doi"))
        record["has_biosample"] = record.get("biosample_n_found", 0) > 0
        record["has_age_data"] = bool(record.get("biosample_age_min"))
        record["has_sex_data"] = bool(record.get("biosample_sex_dist"))
        record["has_bmi_data"] = bool(record.get("biosample_bmi_mean"))

        merged[acc] = record

    # Save JSON
    json_path = OUTPUT_DIR / "all_studies_metadata.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"JSON: {json_path} ({len(merged)} records)")

    # Save TSV
    tsv_path = OUTPUT_DIR / "all_studies_metadata.tsv"
    tsv_fields = [
        "bioproject_id", "has_full_text", "has_pmid", "has_mesh", "has_doi",
        "has_biosample", "has_age_data", "has_sex_data", "has_bmi_data",
        "doi", "pmid", "pmc_id", "pii",
        "bioproject_title", "pub_title", "ncbi_description", "abstract",
        "journal", "journal_iso_abbrev", "journal_country",
        "pub_year", "pub_month", "volume", "issue", "pages",
        "language", "publication_status", "publication_types",
        "n_authors", "n_orcids", "author_names", "author_orcids",
        "n_mesh", "mesh_terms",
        "mesh_age_groups", "mesh_sex", "mesh_study_design", "mesh_population",
        "mesh_sample_material", "mesh_methods", "mesh_analysis",
        "mesh_diseases", "mesh_geography", "mesh_other",
        "chemical_names",
        "keywords", "n_references", "reference_pmids",
        "grants", "grant_ids",
        "coi_statement", "copyright",
        "ncbi_organism", "ncbi_datatype", "submitting_center",
        "condition", "sample_type", "subjects", "notes",
        "amplicon", "avg_read_length", "bead_beating", "extraction_kit",
        "n_samples", "n_runs", "instruments", "geo_locations",
        "library_strategies", "library_sources", "pubdates", "total_bases",
        "srr_count", "srs_count",
        "biosample_n_checked", "biosample_n_found",
        "biosample_age_min", "biosample_age_max", "biosample_age_mean",
        "biosample_sex_dist", "biosample_n_male", "biosample_n_female",
        "biosample_bmi_mean",
        "biosample_geo", "biosample_body_sites", "biosample_host",
        "biosample_diseases", "biosample_disease_flags",
        "biosample_races", "biosample_nationalities",
        "biosample_interventions", "biosample_diet_types",
        "biosample_antibiotics", "biosample_probiotics", "biosample_smoking",
        "biosample_lifestyle", "biosample_all_attr_keys",
        "ena_n_runs", "ena_total_reads", "ena_total_bases",
        "ena_library_strategy", "ena_library_source", "ena_instrument_model",
    ]
    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=tsv_fields, extrasaction="ignore")
        writer.writeheader()
        for acc in sorted(merged):
            row = dict(merged[acc])
            # Join lists for TSV
            for k in ["authors", "author_names", "author_orcids", "mesh_terms",
                      "mesh_age_groups", "mesh_sex", "mesh_study_design", "mesh_population",
                      "mesh_sample_material", "mesh_methods", "mesh_analysis",
                      "mesh_diseases", "mesh_geography", "mesh_other",
                      "chemical_names", "keywords", "reference_pmids",
                      "grants", "publication_types",
                      "instruments", "geo_locations", "library_strategies",
                      "library_sources", "pubdates",
                      "biosample_geo", "biosample_body_sites", "biosample_host",
                      "biosample_diseases", "biosample_races", "biosample_nationalities",
                      "biosample_interventions", "biosample_diet_types",
                      "biosample_antibiotics", "biosample_probiotics",
                      "biosample_smoking", "biosample_all_attr_keys"]:
                if isinstance(row.get(k), list):
                    row[k] = "; ".join(str(v) for v in row[k])
            for k in ["biosample_sex_dist", "biosample_disease_flags", "biosample_lifestyle"]:
                if isinstance(row.get(k), dict):
                    row[k] = "; ".join(f"{kk}={vv}" for kk, vv in row[k].items())
            writer.writerow(row)
    print(f"TSV:  {tsv_path}")

    # Summary
    n = len(merged)
    print()
    print("=" * 70)
    print("All Studies Metadata Summary (v2 — Enriched)")
    print("=" * 70)
    print(f"Total BioProject accessions: {n}")
    print(f"  with full text:          {sum(1 for r in merged.values() if r['has_full_text'])}")
    print(f"  with PMID:               {sum(1 for r in merged.values() if r['has_pmid'])}")
    print(f"  with MeSH:               {sum(1 for r in merged.values() if r['has_mesh'])}")
    print(f"  with DOI:                {sum(1 for r in merged.values() if r['has_doi'])}")
    print(f"  with BioSamples:         {sum(1 for r in merged.values() if r['has_biosample'])}")
    print(f"  with age data:           {sum(1 for r in merged.values() if r['has_age_data'])}")
    print(f"  with sex data:           {sum(1 for r in merged.values() if r['has_sex_data'])}")
    print(f"  with BMI data:           {sum(1 for r in merged.values() if r['has_bmi_data'])}")
    print(f"  with description:        {sum(1 for r in merged.values() if r.get('ncbi_description') or r.get('abstract'))}")
    print(f"  with title:              {sum(1 for r in merged.values() if r.get('pub_title') or r.get('bioproject_title'))}")
    print(f"  with journal:            {sum(1 for r in merged.values() if r.get('journal'))}")
    print(f"  with COI statement:      {sum(1 for r in merged.values() if r.get('coi_statement'))}")
    print(f"  with ORCID authors:      {sum(1 for r in merged.values() if r.get('n_orcids', 0) > 0)}")
    print(f"  with references:         {sum(1 for r in merged.values() if r.get('n_references', 0) > 0)}")
    print(f"  with chemicals:          {sum(1 for r in merged.values() if r.get('chemical_names'))}")
    print(f"  total MeSH terms:         {sum(r.get('n_mesh', 0) for r in merged.values())}")
    print(f"  total authors:           {sum(r.get('n_authors', 0) for r in merged.values())}")
    print(f"  total ORCIDs:            {sum(r.get('n_orcids', 0) for r in merged.values())}")
    print(f"  total references:        {sum(r.get('n_references', 0) for r in merged.values())}")
    print(f"  total samples:            {sum(r.get('n_samples', 0) for r in merged.values()):,}")
    print(f"  total bases:              {sum(r.get('total_bases', 0) for r in merged.values()):,}")

    # MeSH category coverage
    print()
    print("MeSH category coverage:")
    for cat in ["mesh_age_groups", "mesh_sex", "mesh_study_design", "mesh_population",
                "mesh_sample_material", "mesh_methods", "mesh_analysis",
                "mesh_diseases", "mesh_geography"]:
        n_with = sum(1 for r in merged.values() if r.get(cat))
        print(f"  {cat:25s}: {n_with}/{n} ({n_with/n*100:.1f}%)")

    # BioSample coverage
    print()
    print("BioSample demographic coverage:")
    for label, key in [("geography", "biosample_geo"), ("body_site", "biosample_body_sites"),
                       ("host", "biosample_host"), ("disease", "biosample_diseases"),
                       ("race", "biosample_races"), ("nationality", "biosample_nationalities"),
                       ("intervention", "biosample_interventions"), ("diet", "biosample_diet_types"),
                       ("antibiotics", "biosample_antibiotics"), ("smoking", "biosample_smoking")]:
        n_with = sum(1 for r in merged.values() if r.get(key))
        print(f"  {label:25s}: {n_with}/{n} ({n_with/n*100:.1f}%)")

    # Source coverage matrix
    print()
    print("Source coverage per study:")
    for source in ["has_full_text", "has_doi", "has_pmid", "has_mesh", "has_biosample"]:
        n_with = sum(1 for r in merged.values() if r.get(source))
        print(f"  {source:20s}: {n_with}/{n} ({n_with/n*100:.1f}%)")

    # Top journals
    journals = Counter(r.get("journal", "") for r in merged.values() if r.get("journal"))
    print()
    print("Top 15 journals:")
    for j, c in journals.most_common(15):
        print(f"  {c:3d}  {j}")

    # Top MeSH terms
    all_mesh = []
    for r in merged.values():
        all_mesh.extend(r.get("mesh_terms", []))
    mesh_counter = Counter(all_mesh)
    print()
    print(f"Top 20 MeSH terms (of {len(all_mesh)} total):")
    for m, c in mesh_counter.most_common(20):
        print(f"  {c:4d}  {m}")

    # Top conditions
    conditions = Counter(r.get("condition", "") for r in merged.values() if r.get("condition"))
    print()
    print(f"Top 15 conditions (from projects.csv):")
    for cond, c in conditions.most_common(15):
        print(f"  {c:3d}  {cond}")


if __name__ == "__main__":
    run()
