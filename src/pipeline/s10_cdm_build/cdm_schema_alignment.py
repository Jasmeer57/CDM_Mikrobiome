#!/usr/bin/env python3
"""CDM Schema Alignment: populate sample-level data and build OMOP vocabulary infrastructure.

Transforms the Microbiome-CDM from a literature-derived knowledge graph into a proper
Common Data Model by:
  Phase 1: Populating 168,464 samples + 3.5M sample tags + project metadata from the
          168k-samples compendium (NMDC/MIxS-aligned sample-centric data).
  Phase 2: Building 8 OMOP-style vocabulary infrastructure tables (CONCEPT, DOMAIN,
          VOCABULARY, CONCEPT_RELATIONSHIP, CONCEPT_ANCESTOR, CONCEPT_SYNONYM,
          SOURCE_TO_CONCEPT_MAP, CDM_SOURCE).
  Phase 3: Linking samples to entities (connecting the KG to sample-level data).

Usage:
    python -m cdm_pipeline.cdm_schema_alignment --phase 1   # samples + tags + projects
    python -m cdm_pipeline.cdm_schema_alignment --phase 2   # OMOP vocabulary tables
    python -m cdm_pipeline.cdm_schema_alignment --phase 3   # sample-entity linkage
    python -m cdm_pipeline.cdm_schema_alignment --all       # all phases
"""
import argparse
import csv
import gzip
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Dataset paths (support CDM_SAMPLES_PAPER / CDM_PAPERS_TXT overrides). Imported
# via the repo root so this stays runnable as a standalone script.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from cdm_pipeline import paths as _paths  # noqa: E402

SRC_DB = PROJECT_ROOT / "releases" / "v2.1.1-clean" / "microbiome_cdm.db"
DST_DIR = PROJECT_ROOT / "releases" / "v3.0-cdm"
DST_DB = DST_DIR / "microbiome_cdm.db"

_SAMPLES_PAPER = _paths.samples_paper_dir()
SAMPLES_TSV = _SAMPLES_PAPER / "sample_metadata.tsv"
TAGS_TSV_GZ = _SAMPLES_PAPER / "tags.tsv.gz"
PROJECTS_CSV = _SAMPLES_PAPER / "projects.csv"
BIOSAMPLE_JSON = (
    PROJECT_ROOT / "paper" / "_multi_ner_runs" / "cdm_output" / "biosample_metadata.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Country names that should be grouped as "Unknown"
_UNKNOWN_COUNTRY_NAMES = {
    None, "", "missing", "not applicable", "not available", "not collected",
    "unknown", "na", "n/a", "none",
}


def _clean_country(name):
    """Normalize a geo_loc_name value: group missing/unknown entries, extract country."""
    if name is None:
        return "Unknown"
    name = name.strip()
    key = name.lower()
    if key in _UNKNOWN_COUNTRY_NAMES:
        return "Unknown"
    # geo_loc_name format is often "country: region" or "country:city" — extract country
    if ":" in name:
        country = name.split(":")[0].strip()
        return country
    return name


def _clean_country_distribution(dist):
    """Given a {name: count} dict, merge unknown variants into 'Unknown'."""
    cleaned = {}
    unknown_total = 0
    for name, count in dist.items():
        country = _clean_country(name)
        if country == "Unknown":
            unknown_total += count
        else:
            cleaned[country] = cleaned.get(country, 0) + count
    if unknown_total:
        cleaned["Unknown"] = unknown_total
    return dict(sorted(cleaned.items(), key=lambda x: (-x[1], x[0])))


def _clean_age_values(raw_values):
    """Clean raw age values from BioSample records.

    Fixes three known issues:
    1. Birth-year tags (e.g. 'birth year: 1994') misinterpreted as ages.
       Detection: value in [1890, current_year] → it's a birth year, not an age → drop.
    2. Ages recorded in days (e.g. host_age=221, 437, 685).
       Detection: all values > 120 and < 36500 → divide by 365.25 to get years.
    3. Implausible outliers (> 120 years after day conversion) → drop.

    Returns a cleaned list of age values in years.
    """
    if not raw_values:
        return []
    import datetime as _dt
    current_year = _dt.datetime.now().year

    cleaned = []
    for v in raw_values:
        try:
            val = float(v)
        except (ValueError, TypeError):
            continue
        if val <= 0:
            continue
        # Birth year detection: value looks like a year, not an age
        if 1890 <= val <= current_year:
            continue  # skip birth years
        # If all remaining values in a project are > 120 and < 36500, they're days
    # Check if this project's values are likely in days
    plausible = [v for v in cleaned]  # placeholder
    # Re-process: check if all values are > 120 (likely days)
    vals_after_birthyear = []
    for v in raw_values:
        try:
            val = float(v)
        except (ValueError, TypeError):
            continue
        if val <= 0:
            continue
        if 1890 <= val <= current_year:
            continue  # birth year, skip
        vals_after_birthyear.append(val)

    if not vals_after_birthyear:
        return []

    # If all values > 120, likely in days → convert
    if all(v > 120 for v in vals_after_birthyear) and all(v < 36500 for v in vals_after_birthyear):
        vals_after_birthyear = [round(v / 365.25, 1) for v in vals_after_birthyear]

    # Filter out anything still implausible (> 120 years)
    return [v for v in vals_after_birthyear if 0 < v <= 120]


def clean_age_data(db_path):
    """Fix age columns in projects table: recompute from biosample_age_values with cleaning."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("SELECT id, biosample_age_values FROM projects WHERE biosample_age_values IS NOT NULL AND biosample_age_values != ''")
    rows = cur.fetchall()

    n_fixed = 0
    for proj_id, raw in rows:
        try:
            raw_values = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            continue
        cleaned = _clean_age_values(raw_values)
        if not cleaned:
            # All values were implausible — set to NULL
            cur.execute("UPDATE projects SET age_min=NULL, age_max=NULL, age_mean=NULL WHERE id=?",
                         (proj_id,))
            n_fixed += 1
            continue
        new_min = round(min(cleaned), 1)
        new_max = round(max(cleaned), 1)
        new_mean = round(sum(cleaned) / len(cleaned), 1)
        # Only update if values actually changed
        cur.execute("SELECT age_min, age_max, age_mean FROM projects WHERE id=?", (proj_id,))
        old = cur.fetchone()
        if old and (old[0] != new_min or old[1] != new_max or old[2] != new_mean):
            cur.execute("UPDATE projects SET age_min=?, age_max=?, age_mean=? WHERE id=?",
                         (new_min, new_max, new_mean, proj_id))
            n_fixed += 1

    conn.commit()
    conn.close()
    print(f"  Age data cleaned: {n_fixed} projects updated (birth-year + day-scale fixes)")
    return n_fixed


# ---------------------------------------------------------------------------
# Phase 1: Sample-level data + project metadata
# ---------------------------------------------------------------------------

def copy_db():
    """Copy v2.1.1-clean DB to v3.0-cdm."""
    DST_DIR.mkdir(parents=True, exist_ok=True)
    if DST_DB.exists():
        DST_DB.unlink()
    shutil.copy2(SRC_DB, DST_DB)
    print(f"Copied {SRC_DB} -> {DST_DB} ({DST_DB.stat().st_size / 1024 / 1024:.1f} MB)")
    return DST_DB


def populate_samples(db_path):
    """Load 168,464 samples from sample_metadata.tsv into the samples table."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("DELETE FROM samples")

    batch = []
    n = 0
    with open(SAMPLES_TSV, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            batch.append((
                row["srs"].strip(),
                row["project"].strip(),
                row["srr"].strip() or None,
                row["library_strategy"].strip() or None,
                row["library_source"].strip() or None,
                row["pubdate"].strip() or None,
                int(row["total_bases"]) if row["total_bases"].strip() else None,
                row["instrument"].strip() or None,
                row["geo_loc_name"].strip() or None,
                row["iso"].strip() or None,
                row["region"].strip() or None,
            ))
            n += 1
            if len(batch) >= 10000:
                cur.executemany(
                    "INSERT INTO samples (srs, project_id, srr, library_strategy, "
                    "library_source, pubdate, total_bases, instrument, geo_loc_name, "
                    "iso, region) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                batch.clear()
                if n % 50000 == 0:
                    print(f"  samples: {n:,}")
                    conn.commit()

    if batch:
        cur.executemany(
            "INSERT INTO samples (srs, project_id, srr, library_strategy, "
            "library_source, pubdate, total_bases, instrument, geo_loc_name, "
            "iso, region) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            batch,
        )

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM samples")
    total = cur.fetchone()[0]
    print(f"  samples: {total:,} rows loaded")
    conn.close()
    return total


def populate_sample_tags(db_path):
    """Load ~3.5M sample tags from tags.tsv.gz into the sample_tags table."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Build SRS -> sample_id lookup
    cur.execute("SELECT srs, id FROM samples")
    srs_to_id = {row[0]: row[1] for row in cur.fetchall()}
    print(f"  sample_tags: {len(srs_to_id):,} samples in lookup")

    cur.execute("DELETE FROM sample_tags")

    batch = []
    n = 0
    skipped = 0
    with gzip.open(TAGS_TSV_GZ, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            srs = row["srs"].strip()
            sample_id = srs_to_id.get(srs)
            if sample_id is None:
                skipped += 1
                continue
            batch.append((
                sample_id,
                row["tag"].strip(),
                row["value"].strip() or None,
            ))
            n += 1
            if len(batch) >= 10000:
                cur.executemany(
                    "INSERT INTO sample_tags (sample_id, tag, value) VALUES (?,?,?)",
                    batch,
                )
                batch.clear()
                if n % 500000 == 0:
                    print(f"  sample_tags: {n:,} (skipped {skipped:,})")
                    conn.commit()

    if batch:
        cur.executemany(
            "INSERT INTO sample_tags (sample_id, tag, value) VALUES (?,?,?)",
            batch,
        )

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM sample_tags")
    total = cur.fetchone()[0]
    print(f"  sample_tags: {total:,} rows loaded (skipped {skipped:,} unmatched SRS)")
    conn.close()
    return total


def update_projects_metadata(db_path):
    """Update projects table with metadata from projects.csv and BioSample demographics."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    n_updated = 0
    with open(PROJECTS_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            project_id = row["project"].strip()
            cur.execute(
                "UPDATE projects SET link=?, amplicon=?, avg_length=?, bead_beating=?, "
                "kit=?, sample_type=?, condition=?, subjects=?, notes=? "
                "WHERE project_id=?",
                (
                    row["link"].strip() or None,
                    row["amplicon"].strip() or None,
                    float(row["avg_length"]) if row["avg_length"].strip() else None,
                    bool(row["bead_beating"].strip() == "TRUE")
                    if row["bead_beating"].strip()
                    else None,
                    row["kit"].strip() or None,
                    row["sample_type"].strip() or None,
                    row["condition"].strip() or None,
                    row["subjects"].strip() or None,
                    row["notes"].strip() or None,
                    project_id,
                ),
            )
            if cur.rowcount > 0:
                n_updated += 1

    conn.commit()
    print(f"  projects: {n_updated} rows updated from projects.csv")

    if BIOSAMPLE_JSON.exists():
        with open(BIOSAMPLE_JSON) as f:
            bs_data = json.load(f)

        # Add clinical metadata columns to projects table
        clinical_cols = [
            ("age_min", "REAL"),
            ("age_max", "REAL"),
            ("age_mean", "REAL"),
            ("bmi_mean", "REAL"),
            ("n_male", "INTEGER"),
            ("n_female", "INTEGER"),
            ("sex_distribution", "TEXT"),
            ("body_site", "TEXT"),
            ("diseases", "TEXT"),
            ("disease_flags", "TEXT"),
            ("geo_locations", "TEXT"),
            ("nationalities", "TEXT"),
            ("races", "TEXT"),
            ("diet_types", "TEXT"),
            ("smoking_status", "TEXT"),
            ("antibiotic_history", "TEXT"),
            ("probiotic_use", "TEXT"),
            ("intervention_groups", "TEXT"),
            ("lifestyle", "TEXT"),
            ("biosample_age_values", "TEXT"),
            ("biosample_bmi_values", "TEXT"),
            ("biosample_n_samples_checked", "INTEGER"),
            ("biosample_n_samples_found", "INTEGER"),
            ("biosample_all_attribute_keys", "TEXT"),
        ]
        existing_cols = {c[1] for c in cur.execute("PRAGMA table_info(projects)").fetchall()}
        for col_name, col_type in clinical_cols:
            if col_name not in existing_cols:
                cur.execute(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}")
        conn.commit()
        print(f"  projects: added {len(clinical_cols)} clinical metadata columns")

        n_bs = 0
        for proj_id, bs in bs_data.items():
            host = "; ".join(bs.get("host_organisms", [])) if bs.get("host_organisms") else None
            updates = []

            def _join_list(key):
                val = bs.get(key)
                if isinstance(val, list):
                    return "; ".join(str(v) for v in val) if val else None
                return str(val) if val else None

            set_clauses = []
            set_values = []

            field_map = {
                "age_min": bs.get("age_min"),
                "age_max": bs.get("age_max"),
                "age_mean": bs.get("age_mean"),
                "bmi_mean": bs.get("bmi_mean"),
                "n_male": bs.get("n_male"),
                "n_female": bs.get("n_female"),
                "sex_distribution": _join_list("sex_distribution"),
                "body_site": _join_list("body_sites"),
                "diseases": _join_list("diseases"),
                "disease_flags": _join_list("disease_flags"),
                "geo_locations": _join_list("geo_locations"),
                "nationalities": _join_list("nationalities"),
                "races": _join_list("races"),
                "diet_types": _join_list("diet_types"),
                "smoking_status": _join_list("smoking_status"),
                "antibiotic_history": _join_list("antibiotic_history"),
                "probiotic_use": _join_list("probiotic_use"),
                "intervention_groups": _join_list("intervention_groups"),
                "lifestyle": _join_list("lifestyle"),
                "biosample_age_values": _join_list("age_values"),
                "biosample_bmi_values": _join_list("bmi_values"),
                "biosample_n_samples_checked": bs.get("n_samples_checked"),
                "biosample_n_samples_found": bs.get("n_samples_found"),
                "biosample_all_attribute_keys": _join_list("all_attribute_keys"),
            }
            if host:
                field_map["host_organism"] = host

            for col, val in field_map.items():
                if val is not None:
                    set_clauses.append(f"{col}=?")
                    set_values.append(val)

            if set_clauses:
                set_values.append(proj_id)
                cur.execute(
                    f"UPDATE projects SET {', '.join(set_clauses)} WHERE project_id=?",
                    set_values,
                )
                if cur.rowcount > 0:
                    n_bs += 1

        conn.commit()
        print(f"  projects: {n_bs} rows updated with clinical metadata from BioSample data")

    conn.close()
    return n_updated


def phase1():
    """Phase 1: Populate samples, sample_tags, and update projects metadata."""
    print("=" * 60)
    print("Phase 1: Sample-level data + project metadata")
    print("=" * 60)

    db_path = copy_db()
    n_samples = populate_samples(db_path)
    n_tags = populate_sample_tags(db_path)
    n_projects = update_projects_metadata(db_path)

    print()
    print(f"Phase 1 complete: {n_samples:,} samples, {n_tags:,} tags, {n_projects} projects updated")
    print(f"DB: {db_path}")
    return db_path


# ---------------------------------------------------------------------------
# Phase 2: OMOP-style vocabulary infrastructure
# ---------------------------------------------------------------------------

def build_vocabulary_tables(db_path):
    """Build 8 OMOP-style vocabulary infrastructure tables."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Drop any partial tables from previous runs (idempotent)
    for tbl in [
        "concept_ancestor", "source_to_concept_map", "concept_synonym",
        "concept_relationship", "concept", "domain", "vocabulary",
        "cdm_source", "sample_entity_links",
    ]:
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.commit()

    # --- VOCABULARY ---
    cur.execute("""CREATE TABLE IF NOT EXISTS vocabulary (
        vocabulary_id TEXT PRIMARY KEY,
        vocabulary_name TEXT NOT NULL,
        vocabulary_reference TEXT,
        vocabulary_version TEXT,
        vocabulary_concept_id INTEGER
    )""")

    vocab_rows = [
        ("UMLS", "Unified Medical Language System", "https://www.nlm.nih.gov/research/umls/", "2024AA", None),
        ("MESH", "Medical Subject Headings", "https://meshb.nlm.nih.gov/", "2024", None),
        ("SNOMEDCT", "SNOMED Clinical Terms", "https://www.snomed.org/", "2024-09", None),
        ("NCIT", "NCI Thesaurus", "https://cbiitsapi.nci.nih.gov/", "24.09e", None),
        ("NCBITAXON", "NCBI Taxonomy", "https://www.ncbi.nlm.nih.gov/taxonomy", "2024-08", None),
        ("CHEBI", "Chemical Entities of Biological Interest", "https://www.ebi.ac.uk/chebi/", "219", None),
        ("OMIM", "Online Mendelian Inheritance in Man", "https://omim.org/", "2024", None),
        ("MONDO", "Mondo Disease Ontology", "http://purl.obolibrary.org/obo/mondo", "2024-08", None),
        ("HP", "Human Phenotype Ontology", "https://hpo.jax.org/", "2024-08", None),
        ("RXNORM", "RxNorm", "https://www.nlm.nih.gov/research/umls/rxnorm/", "2024-09", None),
        ("GO", "Gene Ontology", "http://purl.obolibrary.org/obo/go", "2024-09", None),
        ("LOINC", "Logical Observation Identifiers Names and Codes", "https://loinc.org/", "2.78", None),
        ("DOID", "Human Disease Ontology", "http://purl.obolibrary.org/obo/doid", "2024-08", None),
        ("PR", "Protein Ontology", "http://purl.obolibrary.org/obo/pr", "2024-08", None),
        ("HGNC", "HUGO Gene Nomenclature Committee", "https://www.genenames.org/", "2024-07", None),
        ("OBI", "Ontology for Biomedical Investigations", "http://purl.obolibrary.org/obo/obi", "2024-07", None),
        ("STATO", "Statistics Ontology", "http://purl.obolibrary.org/obo/stato", "1.4", None),
        ("GENEPIO", "Genomic Epidemiology Ontology", "http://purl.obolibrary.org/obo/genepio", "2024-07", None),
        ("CL", "Cell Ontology", "http://purl.obolibrary.org/obo/cl", "2024-08", None),
        ("EDAM", "EDAM Ontology", "http://edamontology.org/", "1.25", None),
        ("SO", "Sequence Ontology", "http://purl.obolibrary.org/obo/so", "2024-08", None),
        ("WIKIPATHWAYS", "WikiPathways", "https://www.wikipathways.org/", "2024-09", None),
        ("ICD9CM", "ICD-9-CM", "https://www.cdc.gov/nchs/icd/icd9cm.htm", "2014", None),
        ("ICD10", "ICD-10", "https://icd.who.int/browse10", "2024", None),
        ("CLO", "Cell Line Ontology", "http://purl.obolibrary.org/obo/clo", "2024-08", None),
        ("ERO", "Eagle-i Resource Ontology", "http://purl.obolibrary.org/obo/ero", "1.5", None),
    ]
    cur.executemany("INSERT INTO vocabulary VALUES (?,?,?,?,?)", vocab_rows)
    print(f"  vocabulary: {len(vocab_rows)} rows")

    # --- DOMAIN ---
    cur.execute("""CREATE TABLE IF NOT EXISTS domain (
        domain_id TEXT PRIMARY KEY,
        domain_name TEXT NOT NULL,
        domain_concept_id INTEGER,
        vocabulary_id TEXT
    )""")

    cur.execute("SELECT type_name, description FROM entity_types")
    vocab_map = {
        "ORGANISM": "NCBITAXON",
        "DISEASE": "MONDO",
        "CHEMICAL": "CHEBI",
        "PROTEIN": "PR",
        "PATHWAY": "WIKIPATHWAYS",
        "DNA_RNA": "SO",
        "CELL_TYPE": "CL",
        "GENOMICS": "SO",
        "CLINICAL": "SNOMEDCT",
        "DATA_ANALYSIS": "EDAM",
        "EXPERIMENTAL_METHOD": "OBI",
        "LAB_METHOD": "OBI",
        "SAMPLE_METHOD": "OBI",
        "STUDY_DESIGN": "STATO",
    }
    for type_name, desc in cur.fetchall():
        cur.execute(
            "INSERT INTO domain VALUES (?,?,?,?)",
            (type_name, desc or type_name, None, vocab_map.get(type_name)),
        )
    print(f"  domain: 14 rows")

    # --- CONCEPT ---
    cur.execute("""CREATE TABLE IF NOT EXISTS concept (
        concept_id INTEGER PRIMARY KEY,
        concept_name TEXT NOT NULL,
        domain_id TEXT,
        vocabulary_id TEXT,
        concept_class_id TEXT,
        standard_concept TEXT,
        concept_code TEXT,
        valid_start_date DATE,
        valid_end_date DATE,
        invalid_reason TEXT
    )""")

    # Build a lookup of best vocabulary mapping per entity
    cur.execute("""
        SELECT entity_id, vocabulary_name, vocabulary_id, mapping_tier, mapping_confidence
        FROM controlled_vocabularies
        ORDER BY entity_id, mapping_tier ASC NULLS LAST, mapping_confidence DESC
    """)
    best_vocab = {}
    best_code = {}
    for eid, vname, vid, tier, conf in cur.fetchall():
        if eid not in best_vocab:
            best_vocab[eid] = vname
            best_code[eid] = vid

    # Insert concepts
    cur.execute("SELECT id, term, entity_type, umls_mapped FROM entities")
    batch = []
    for eid, term, etype, umls_mapped in cur.fetchall():
        batch.append((
            eid,
            term,
            etype,
            best_vocab.get(eid),
            etype,  # concept_class_id
            "S" if umls_mapped else None,  # standard_concept
            best_code.get(eid),  # concept_code
            "2026-09-25",
            "2099-12-31",
            None,
        ))
    cur.executemany(
        "INSERT INTO concept VALUES (?,?,?,?,?,?,?,?,?,?)",
        batch,
    )
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM concept")
    print(f"  concept: {cur.fetchone()[0]:,} rows")

    # --- CONCEPT_RELATIONSHIP ---
    cur.execute("""CREATE TABLE IF NOT EXISTS concept_relationship (
        concept_id_1 INTEGER NOT NULL,
        concept_id_2 INTEGER NOT NULL,
        relationship_id TEXT NOT NULL,
        valid_start_date DATE,
        valid_end_date DATE,
        invalid_reason TEXT,
        PRIMARY KEY (concept_id_1, concept_id_2, relationship_id)
    )""")

    cur.execute("""
        INSERT OR IGNORE INTO concept_relationship (concept_id_1, concept_id_2, relationship_id, valid_start_date, valid_end_date)
        SELECT source_id, target_id, relationship_type, '2026-09-25', '2099-12-31'
        FROM relationships
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM concept_relationship")
    print(f"  concept_relationship: {cur.fetchone()[0]:,} rows")

    # --- CONCEPT_SYNONYM ---
    cur.execute("""CREATE TABLE IF NOT EXISTS concept_synonym (
        concept_id INTEGER NOT NULL,
        concept_synonym_name TEXT NOT NULL,
        language_concept_id INTEGER
    )""")

    cur.execute("""
        INSERT OR IGNORE INTO concept_synonym (concept_id, concept_synonym_name, language_concept_id)
        SELECT entity_id, vocabulary_label, 4180186
        FROM controlled_vocabularies
        WHERE vocabulary_label IS NOT NULL AND vocabulary_label != ''
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM concept_synonym")
    print(f"  concept_synonym: {cur.fetchone()[0]:,} rows")

    # --- SOURCE_TO_CONCEPT_MAP ---
    cur.execute("""CREATE TABLE IF NOT EXISTS source_to_concept_map (
        source_code TEXT NOT NULL,
        source_concept_id INTEGER,
        source_vocabulary_id TEXT NOT NULL,
        source_code_description TEXT,
        target_concept_id INTEGER NOT NULL,
        target_vocabulary_id TEXT NOT NULL,
        valid_start_date DATE,
        valid_end_date DATE,
        invalid_reason TEXT,
        PRIMARY KEY (source_code, source_vocabulary_id, target_concept_id)
    )""")

    cur.execute("""
        INSERT OR IGNORE INTO source_to_concept_map (source_code, source_concept_id, source_vocabulary_id,
            source_code_description, target_concept_id, target_vocabulary_id,
            valid_start_date, valid_end_date)
        SELECT vocabulary_id, entity_id, vocabulary_name, vocabulary_label,
               entity_id, vocabulary_name, '2026-09-25', '2099-12-31'
        FROM controlled_vocabularies
        WHERE vocabulary_id IS NOT NULL AND vocabulary_id != ''
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM source_to_concept_map")
    print(f"  source_to_concept_map: {cur.fetchone()[0]:,} rows")

    # --- CONCEPT_ANCESTOR ---
    cur.execute("""CREATE TABLE IF NOT EXISTS concept_ancestor (
        ancestor_concept_id INTEGER NOT NULL,
        descendant_concept_id INTEGER NOT NULL,
        min_levels_of_separation INTEGER,
        max_levels_of_separation INTEGER,
        PRIMARY KEY (ancestor_concept_id, descendant_concept_id)
    )""")

    # Self-ancestors (0 levels) for all entities
    cur.execute("""
        INSERT OR IGNORE INTO concept_ancestor (ancestor_concept_id, descendant_concept_id, min_levels_of_separation, max_levels_of_separation)
        SELECT id, id, 0, 0 FROM entities
    """)
    conn.commit()

    # Domain → entity ancestor relationships (1 level)
    # Use negative IDs for domain-level concepts to distinguish from entity IDs
    cur.execute("SELECT id, type_name FROM entity_types")
    type_ids = {t[1]: t[0] for t in cur.fetchall()}

    batch = []
    cur.execute("SELECT id, entity_type FROM entities")
    for eid, etype in cur.fetchall():
        tid = type_ids.get(etype)
        if tid is not None:
            batch.append((-tid, eid, 1, 1))
    cur.executemany(
        "INSERT OR IGNORE INTO concept_ancestor VALUES (?,?,?,?)",
        batch,
    )
    conn.commit()
    print(f"  concept_ancestor: domain+self ancestors loaded")

    # NCBITaxon hierarchy: entities sharing the same NCBITaxon ID are ancestors of each other
    cur.execute("""
        SELECT entity_id, vocabulary_id FROM controlled_vocabularies
        WHERE vocabulary_name = 'NCBITAXON' AND vocabulary_id IS NOT NULL AND vocabulary_id != ''
    """)
    ncbi_by_id = {}
    for eid, vid in cur.fetchall():
        ncbi_by_id.setdefault(vid, []).append(eid)

    n_pairs = 0
    for vid, eids in ncbi_by_id.items():
        if len(eids) > 1:
            for i in range(len(eids)):
                for j in range(len(eids)):
                    if i != j:
                        cur.execute(
                            "INSERT OR IGNORE INTO concept_ancestor VALUES (?,?,0,0)",
                            (eids[i], eids[j]),
                        )
                        n_pairs += 1
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM concept_ancestor")
    print(f"  concept_ancestor: {cur.fetchone()[0]:,} rows (including {n_pairs:,} NCBITaxon cross-refs)")

    # --- CDM_SOURCE ---
    cur.execute("""CREATE TABLE IF NOT EXISTS cdm_source (
        cdm_source_name TEXT NOT NULL,
        cdm_source_abbreviation TEXT,
        cdm_holder TEXT,
        source_description TEXT,
        source_documentation_reference TEXT,
        cdm_version TEXT,
        vocabulary_version TEXT,
        cdm_release_date DATE
    )""")

    cur.execute("""INSERT INTO cdm_source VALUES (
        'Microbiome Common Data Model',
        'MCDM',
        'University of Potsdam, Microbiome AI Lab',
        'A literature-derived biomedical knowledge graph integrated with 168,464 microbiome samples from 482 BioProjects, aligned to OMOP CDM vocabulary infrastructure and NMDC/MIxS sample-level standards.',
        'https://github.com/jkalra/Microbiome-CDM',
        '3.0',
        '2024AA',
        '2026-10-07'
    )""")
    print(f"  cdm_source: 1 row")

    # Update run_metadata
    cur.execute(
        "INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?,?)",
        ("cdm_version", "3.0"),
    )
    cur.execute(
        "INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?,?)",
        ("cdm_alignment_date", datetime.now().isoformat()),
    )
    conn.commit()

    conn.close()
    print("  All vocabulary tables built")


def phase2():
    """Phase 2: Build OMOP-style vocabulary infrastructure."""
    print("=" * 60)
    print("Phase 2: OMOP vocabulary infrastructure")
    print("=" * 60)

    if not DST_DB.exists():
        print("ERROR: v3.0 DB not found. Run Phase 1 first.")
        sys.exit(1)

    build_vocabulary_tables(DST_DB)
    print(f"\nPhase 2 complete: {DST_DB}")


# ---------------------------------------------------------------------------
# Phase 3: NMDC-aligned restructure + biosample-entity linkage
# ---------------------------------------------------------------------------

def build_nmdc_tables(db_path):
    """Add NMDC-style tables: omics_processing, data_object, and views."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # --- NMDC views (map existing tables to NMDC names) ---
    cur.execute("DROP VIEW IF EXISTS study")
    cur.execute("DROP VIEW IF EXISTS biosample")
    cur.execute("DROP VIEW IF EXISTS biosample_attributes")

    cur.execute("""CREATE VIEW study AS
        SELECT id AS study_id, project_id AS study_code, title AS study_title,
               link AS study_url, amplicon, avg_length, bead_beating, kit,
               sample_type, condition, subjects, notes, host_organism,
               journal, created_at
        FROM projects""")

    cur.execute("""CREATE VIEW biosample AS
        SELECT id AS biosample_id, srs AS biosample_code, project_id AS study_id,
               srr, library_strategy, library_source, pubdate, total_bases,
               instrument, geo_loc_name, iso, region, created_at
        FROM samples""")

    cur.execute("""CREATE VIEW biosample_attributes AS
        SELECT id AS attribute_id, sample_id AS biosample_id, tag AS attribute_name,
               value AS attribute_value, created_at
        FROM sample_tags""")

    print("  NMDC views: study, biosample, biosample_attributes")

    # --- omics_processing: one row per sample with sequencing data ---
    cur.execute("DROP TABLE IF EXISTS omics_processing")
    cur.execute("""CREATE TABLE omics_processing (
        id INTEGER PRIMARY KEY,
        biosample_id INTEGER NOT NULL,
        study_id TEXT NOT NULL,
        instrument_name TEXT,
        library_strategy TEXT,
        library_source TEXT,
        total_bases INTEGER,
        omics_type TEXT,
        srr_accession TEXT,
        pubdate TEXT,
        FOREIGN KEY (biosample_id) REFERENCES samples(id),
        FOREIGN KEY (study_id) REFERENCES projects(project_id)
    )""")

    cur.execute("""
        INSERT INTO omics_processing (biosample_id, study_id, instrument_name,
            library_strategy, library_source, total_bases, omics_type,
            srr_accession, pubdate)
        SELECT id, project_id, instrument, library_strategy, library_source,
               total_bases,
               CASE WHEN library_strategy LIKE '%WGS%' OR library_strategy LIKE '%WGA%' THEN 'metagenome'
                    WHEN library_strategy LIKE '%RNA-Seq%' OR library_strategy LIKE '%RNA%' THEN 'metatranscriptome'
                    WHEN library_strategy LIKE '%AMPLICON%' THEN 'amplicon'
                    ELSE library_strategy END,
               srr, pubdate
        FROM samples
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM omics_processing")
    print(f"  omics_processing: {cur.fetchone()[0]:,} rows")

    # --- data_object: SRR accessions as data objects ---
    cur.execute("DROP TABLE IF EXISTS data_object")
    cur.execute("""CREATE TABLE data_object (
        id INTEGER PRIMARY KEY,
        omics_processing_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        file_type TEXT DEFAULT 'FASTQ',
        url TEXT,
        FOREIGN KEY (omics_processing_id) REFERENCES omics_processing(id)
    )""")

    cur.execute("""
        INSERT INTO data_object (omics_processing_id, name, file_type)
        SELECT id, srr_accession, 'FASTQ'
        FROM omics_processing
        WHERE srr_accession IS NOT NULL AND srr_accession != ''
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM data_object")
    print(f"  data_object: {cur.fetchone()[0]:,} rows")

    conn.close()


def build_biosample_entity_links(db_path):
    """Build targeted biosample-entity links (not massive cross-join).

    Link types:
    1. project_condition: samples → DISEASE entities (via project condition string match)
    2. host_organism: samples → ORGANISM entities (via project host_organism match)
    3. sample_tag_host: samples → ORGANISM entities (via sample_tags 'host' tag match)
    4. sample_tag_env: samples → ORGANISM entities (via env_broad_scale / env_medium tags)
    """
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS biosample_entity_link")
    cur.execute("""CREATE TABLE biosample_entity_link (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        biosample_id INTEGER NOT NULL,
        entity_id INTEGER NOT NULL,
        link_type TEXT NOT NULL,
        link_value TEXT,
        confidence REAL DEFAULT 1.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (biosample_id) REFERENCES samples(id),
        FOREIGN KEY (entity_id) REFERENCES entities(id)
    )""")

    # Indexes for efficient joins
    cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_proj ON samples(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_epm_proj ON entity_project_mentions(project_id)")
    conn.commit()

    total = 0

    # --- 1. project_condition → DISEASE entities ---
    print("  Linking biosamples to DISEASE entities via project condition...")
    # Pre-compute project → matched disease entities
    cur.execute("SELECT project_id, condition FROM projects WHERE condition IS NOT NULL AND condition != ''")
    proj_conditions = cur.fetchall()

    cur.execute("SELECT id, term FROM entities WHERE entity_type = 'DISEASE'")
    diseases = cur.fetchall()

    # Build condition → disease matches
    cond_matches = {}  # project_id → [(entity_id, disease_term, condition)]
    for proj_id, condition in proj_conditions:
        cond_lower = condition.lower()
        matched = []
        for eid, term in diseases:
            term_lower = term.lower()
            if len(term_lower) >= 3 and (term_lower in cond_lower or cond_lower in term_lower):
                matched.append((eid, term, condition))
        if matched:
            cond_matches[proj_id] = matched

    # Insert links: for each project with matched diseases, link all samples
    batch = []
    for proj_id, matches in cond_matches.items():
        cur.execute("SELECT id FROM samples WHERE project_id = ?", (proj_id,))
        sample_ids = [r[0] for r in cur.fetchall()]
        for sid in sample_ids:
            for eid, term, condition in matches:
                batch.append((sid, eid, "project_condition", condition, 0.9))
        if len(batch) >= 10000:
            cur.executemany(
                "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
                batch,
            )
            total += len(batch)
            batch.clear()
            if total % 100000 == 0:
                print(f"    {total:,} links...")
                conn.commit()

    if batch:
        cur.executemany(
            "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
            batch,
        )
        total += len(batch)
    conn.commit()
    print(f"    project_condition links: {total:,}")

    # --- 2. host_organism → ORGANISM entities ---
    print("  Linking biosamples to ORGANISM entities via project host_organism...")
    cur.execute("SELECT project_id, host_organism FROM projects WHERE host_organism IS NOT NULL AND host_organism != ''")
    proj_hosts = cur.fetchall()

    cur.execute("SELECT id, term FROM entities WHERE entity_type = 'ORGANISM'")
    organisms = cur.fetchall()

    host_matches = {}
    for proj_id, host in proj_hosts:
        host_lower = host.lower()
        matched = []
        for eid, term in organisms:
            term_lower = term.lower()
            if len(term_lower) >= 3 and (term_lower in host_lower or host_lower in term_lower):
                matched.append((eid, term, host))
        if matched:
            host_matches[proj_id] = matched

    batch = []
    n_host = 0
    for proj_id, matches in host_matches.items():
        cur.execute("SELECT id FROM samples WHERE project_id = ?", (proj_id,))
        sample_ids = [r[0] for r in cur.fetchall()]
        for sid in sample_ids:
            for eid, term, host in matches:
                batch.append((sid, eid, "host_organism", host, 0.9))
        if len(batch) >= 10000:
            cur.executemany(
                "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
                batch,
            )
            n_host += len(batch)
            batch.clear()
            if n_host % 100000 == 0:
                print(f"    {n_host:,} links...")
                conn.commit()

    if batch:
        cur.executemany(
            "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
            batch,
        )
        n_host += len(batch)
    conn.commit()
    total += n_host
    print(f"    host_organism links: {n_host:,}")

    # --- 3. sample_tag 'host' → ORGANISM entities ---
    print("  Linking biosamples to ORGANISM entities via sample_tags 'host'...")
    # Get distinct host tag values and match
    cur.execute("SELECT DISTINCT value FROM sample_tags WHERE tag = 'host' AND value IS NOT NULL AND value != ''")
    host_values = [r[0] for r in cur.fetchall()]

    # Match each host value to ORGANISM entities
    host_tag_matches = {}  # host_value → [entity_ids]
    for hv in host_values:
        hv_lower = hv.lower()
        matched = []
        for eid, term in organisms:
            term_lower = term.lower()
            if len(term_lower) >= 3 and (term_lower in hv_lower or hv_lower in term_lower):
                matched.append(eid)
        if matched:
            host_tag_matches[hv] = matched

    # Insert links per matching sample
    batch = []
    n_tag = 0
    for hv, eids in host_tag_matches.items():
        cur.execute(
            "SELECT sample_id FROM sample_tags WHERE tag = 'host' AND value = ?",
            (hv,),
        )
        sample_ids = [r[0] for r in cur.fetchall()]
        for sid in sample_ids:
            for eid in eids:
                batch.append((sid, eid, "sample_tag_host", hv, 0.8))
        if len(batch) >= 10000:
            cur.executemany(
                "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
                batch,
            )
            n_tag += len(batch)
            batch.clear()
            if n_tag % 100000 == 0:
                print(f"    {n_tag:,} links...")
                conn.commit()

    if batch:
        cur.executemany(
            "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
            batch,
        )
        n_tag += len(batch)
    conn.commit()
    total += n_tag
    print(f"    sample_tag_host links: {n_tag:,}")

    # --- 4. project_mention (DISEASE + ORGANISM only, not ALL entity types) ---
    print("  Linking biosamples to DISEASE+ORGANISM entities via project mentions...")
    cur.execute("""
        SELECT entity_id, project_id FROM entity_project_mentions
        WHERE entity_id IN (SELECT id FROM entities WHERE entity_type IN ('DISEASE', 'ORGANISM'))
    """)
    mentions = cur.fetchall()

    # Group by project_id
    proj_entities = {}
    for eid, proj_id in mentions:
        proj_entities.setdefault(proj_id, set()).add(eid)

    batch = []
    n_mention = 0
    for proj_id, eids in proj_entities.items():
        cur.execute("SELECT id FROM samples WHERE project_id = ?", (proj_id,))
        sample_ids = [r[0] for r in cur.fetchall()]
        for sid in sample_ids:
            for eid in eids:
                batch.append((sid, eid, "project_mention", proj_id, 0.7))
        if len(batch) >= 50000:
            cur.executemany(
                "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
                batch,
            )
            n_mention += len(batch)
            batch.clear()
            if n_mention % 200000 == 0:
                print(f"    {n_mention:,} links...")
                conn.commit()

    if batch:
        cur.executemany(
            "INSERT INTO biosample_entity_link (biosample_id, entity_id, link_type, link_value, confidence) VALUES (?,?,?,?,?)",
            batch,
        )
        n_mention += len(batch)
    conn.commit()
    total += n_mention
    print(f"    project_mention links (DISEASE+ORGANISM only): {n_mention:,}")

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bel_biosample ON biosample_entity_link(biosample_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bel_entity ON biosample_entity_link(entity_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bel_type ON biosample_entity_link(link_type)")
    conn.commit()
    conn.close()
    return total


def phase3():
    """Phase 3: NMDC-aligned restructure + biosample-entity linkage."""
    print("=" * 60)
    print("Phase 3: NMDC-aligned restructure + biosample-entity linkage")
    print("=" * 60)

    if not DST_DB.exists():
        print("ERROR: v3.0 DB not found. Run Phase 1 first.")
        sys.exit(1)

    build_nmdc_tables(DST_DB)
    n = build_biosample_entity_links(DST_DB)
    print(f"\nPhase 3 complete: {n:,} biosample-entity links")


# ---------------------------------------------------------------------------
# Phase 4: Folder structure + schema docs + data catalogue
# ---------------------------------------------------------------------------

SCHEMA_DOC = """# Microbiome Common Data Model (MCDM) v3.0 — Schema

## Overview

The Microbiome CDM is a three-layer architecture integrating biomedical
knowledge, standardized vocabularies, and microbiome sample-level data:

1. **Vocabulary Layer** (OMOP CDM v5.4 aligned) — standardized concept tables
2. **Knowledge Layer** (Biomedical KG) — literature-derived entities & relationships
3. **Data Layer** (NMDC/MIxS aligned) — biosample-level data from 168,464 samples

## Layer 1: Vocabulary (OMOP CDM v5.4 aligned)

| Table | Rows | Description |
|-------|------|-------------|
| `concept` | 34,300 | All entities as OMOP concepts (concept_id = entity.id) |
| `vocabulary` | 26 | Vocabulary metadata (UMLS, MESH, SNOMEDCT, NCBITAXON, etc.) |
| `domain` | 14 | Domain definitions (maps entity_types to vocabularies) |
| `concept_relationship` | 54,777 | KG relationships as concept-to-concept relations |
| `concept_ancestor` | 176,480 | Hierarchical ancestor relationships (self + type-level + NCBITaxon) |
| `concept_synonym` | 140,745 | Controlled vocabulary labels as concept synonyms |
| `source_to_concept_map` | 140,745 | Source vocabulary ID → concept mapping |
| `cdm_source` | 1 | CDM release metadata |

### `concept` (34,300 rows)

| Column | Type | Description |
|--------|------|-------------|
| `concept_id` | INTEGER | Primary key (= entity.id) |
| `concept_name` | TEXT | Entity term |
| `domain_id` | TEXT | Domain (= entity_type, e.g. ORGANISM, DISEASE) |
| `vocabulary_id` | TEXT | Source vocabulary (UMLS, MESH, NCBITAXON, etc.) |
| `concept_class_id` | TEXT | Class within vocabulary |
| `standard_concept` | TEXT | 'S' for standard, NULL for non-standard |
| `concept_code` | TEXT | Code in source vocabulary |
| `valid_start_date` | DATE | Concept validity start |
| `valid_end_date` | DATE | Concept validity end |
| `invalid_reason` | TEXT | NULL if valid, 'D' if deprecated |

### `concept_relationship` (54,777 rows)

| Column | Type | Description |
|--------|------|-------------|
| `concept_id_1` | INTEGER | Source concept (= relationship.source_id) |
| `concept_id_2` | INTEGER | Target concept (= relationship.target_id) |
| `relationship_id` | TEXT | Relationship type (ASSOCIATED_WITH, CAUSES, etc.) |
| `valid_start_date` | DATE | Relationship validity start |
| `valid_end_date` | DATE | Relationship validity end |
| `invalid_reason` | TEXT | NULL if valid |

### `concept_ancestor` (176,480 rows)

| Column | Type | Description |
|--------|------|-------------|
| `ancestor_concept_id` | INTEGER | Ancestor concept |
| `descendant_concept_id` | INTEGER | Descendant concept |
| `min_levels_of_separation` | INTEGER | Minimum hierarchy levels |
| `max_levels_of_separation` | INTEGER | Maximum hierarchy levels |

### `concept_synonym` (140,745 rows)

| Column | Type | Description |
|--------|------|-------------|
| `concept_id` | INTEGER | FK to concept |
| `concept_synonym_name` | TEXT | Alternative label |
| `language_concept_id` | INTEGER | Language reference |

### `source_to_concept_map` (140,745 rows)

| Column | Type | Description |
|--------|------|-------------|
| `source_vocabulary_id` | TEXT | Source vocabulary |
| `source_code` | TEXT | Code in source vocabulary |
| `target_concept_id` | INTEGER | FK to concept |
| `source_code_description` | TEXT | Source code label |

## Layer 2: Knowledge (Biomedical KG)

| Table | Rows | Description |
|-------|------|-------------|
| `entities` | 34,300 | Biomedical entities (14 types) |
| `entity_types` | 14 | Entity type definitions with descriptions |
| `relationships` | 54,788 | KG relationships between entities |
| `edge_evidence` | 622,893 | Textual evidence linking relationships to source papers |
| `controlled_vocabularies` | 140,745 | External vocabulary mappings (UMLS, MESH, NCBITAXON, etc.) |
| `entity_project_mentions` | 1,081,219 | Entity mentions in source papers |

### `entities` (34,300 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key (= concept.concept_id) |
| `term` | TEXT | Entity name (e.g. "Bacteroides", "obesity") |
| `entity_type` | TEXT | One of 14 CDM types (ORGANISM, DISEASE, etc.) |
| `categories` | TEXT | Semicolon-separated sub-categories |
| `confidence_score` | REAL | NER confidence (0-1) |
| `paper_count` | INTEGER | Number of papers mentioning this entity |
| `frequency` | INTEGER | Total mention count across corpus |
| `definition` | TEXT | Entity definition (if available) |
| `contextual_definition` | TEXT | Context-specific definition |
| `aliases` | TEXT | Semicolon-separated alternative names |
| `is_core_term` | BOOLEAN | True if core domain term |
| `relevance_classification` | TEXT | Relevance tag |
| `ner_gliner` | BOOLEAN | Detected by GLiNER model |
| `ner_pubmedbert` | BOOLEAN | Detected by PubMedBERT model |
| `ner_pubtator3` | BOOLEAN | Detected by PubTator3 model |
| `ner_qwen` | BOOLEAN | Detected by Qwen LLM model |
| `ner_scispacy` | BOOLEAN | Detected by sciSpaCy model |
| `umls_mapped` | BOOLEAN | Has UMLS mapping |
| `umls_concepts` | TEXT | UMLS concept IDs (JSON) |
| `umls_best_match` | TEXT | Best UMLS match details |

### `relationships` (54,788 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `source_id` | INTEGER | FK to entities (subject) |
| `target_id` | INTEGER | FK to entities (object) |
| `relationship_type` | TEXT | Predicate (ASSOCIATED_WITH, CAUSES, etc.) |
| `source_db` | TEXT | Provenance: llm_triple, co-occurrence, biological_kb, co-occurrence+kb |
| `source_type` | TEXT | Source type: llm_extracted, llm_triple, co_occurrence, kb |
| `confidence` | REAL | Relationship confidence score |
| `evidence` | TEXT | Supporting evidence text |
| `evidence_type` | TEXT | Evidence classification |
| `mechanism` | TEXT | Biological mechanism description |
| `pubmed_ids` | TEXT | Semicolon-separated PubMed IDs |
| `paper_doi` | TEXT | Source paper DOI |
| `p_value` | REAL | Statistical significance (co-occurrence) |
| `q_value` | REAL | FDR-corrected p-value |
| `co_occurrence_count` | INTEGER | Co-occurrence frequency |
| `npm_i` | REAL | Normalized pointwise mutual information |

### `edge_evidence` (622,893 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `relationship_id` | INTEGER | FK to relationships |
| `paper_id` | TEXT | Source paper BioProject ID (PRJ*) |
| `char_start` | INTEGER | Character offset start in source text |
| `char_end` | INTEGER | Character offset end in source text |
| `source_model` | TEXT | NER model that produced the evidence |

### `controlled_vocabularies` (140,745 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `entity_id` | INTEGER | FK to entities |
| `vocabulary_name` | TEXT | Vocabulary name (UMLS, MESH, NCBITAXON, etc.) |
| `vocabulary_id` | TEXT | Vocabulary ID code |
| `vocabulary_uri` | TEXT | URI to vocabulary entry |
| `vocabulary_label` | TEXT | Label in vocabulary |
| `mapping_confidence` | REAL | Mapping confidence score |
| `mapping_source` | TEXT | Mapping method/tool |
| `mapping_tier` | INTEGER | Mapping quality tier |
| `is_canonical` | BOOLEAN | True if canonical mapping |

### `entity_project_mentions` (1,081,219 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `entity_id` | INTEGER | FK to entities |
| `project_id` | TEXT | BioProject ID (PRJ*) |
| `mention_type` | TEXT | Mention type classification |
| `paper_context` | TEXT | Surrounding text context |
| `char_start` | INTEGER | Character offset in source text |
| `char_end` | INTEGER | Character offset end |
| `source_model` | TEXT | NER model that detected the mention |

## Layer 3: Data (NMDC/MIxS aligned)

| Table/View | Rows | Description |
|------------|------|-------------|
| `study` (view) | 444 | NMDC study = projects table (444 microbiome BioProjects) |
| `biosample` (view) | 168,464 | NMDC biosample = samples table (168k samples) |
| `biosample_attributes` (view) | 3,489,745 | MIxS attributes = sample_tags (geo_loc, host, env_medium, etc.) |
| `omics_processing` | 168,464 | Sequencing metadata per sample (instrument, library, omics_type) |
| `data_object` | ~168k | Sequencing data objects (SRR accessions as FASTQ files) |
| `biosample_entity_link` | varies | Targeted links connecting biosamples to KG entities |

### `projects` / `study` (444 rows)

Core columns:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `project_id` | TEXT | BioProject accession (PRJ*) |
| `title` | TEXT | Project title |
| `link` | TEXT | URL to NCBI BioProject |
| `amplicon` | TEXT | Amplicon target (16S, ITS, etc.) |
| `sample_type` | TEXT | Sample type classification |
| `condition` | TEXT | Study condition/disease focus |
| `host_organism` | TEXT | Host organism(s) studied |
| `kit` | TEXT | DNA extraction kit |
| `bead_beating` | BOOLEAN | Bead beating used |
| `subjects` | TEXT | Number of subjects |
| `journal` | TEXT | Publication journal |

Clinical metadata columns (from NCBI BioSample):

| Column | Type | Description |
|--------|------|-------------|
| `age_min` | REAL | Minimum age of participants (years, cleaned) |
| `age_max` | REAL | Maximum age of participants (years, cleaned) |
| `age_mean` | REAL | Mean age of participants (years, cleaned) |
| `bmi_mean` | REAL | Mean BMI of participants |
| `n_male` | INTEGER | Number of male participants |
| `n_female` | INTEGER | Number of female participants |
| `sex_distribution` | TEXT | Sex distribution summary |
| `body_site` | TEXT | Body site(s) sampled (semicolon-separated) |
| `diseases` | TEXT | Disease conditions studied (semicolon-separated) |
| `disease_flags` | TEXT | Disease flag labels |
| `geo_locations` | TEXT | Geographic locations |
| `nationalities` | TEXT | Nationality/ethnicity |
| `races` | TEXT | Race/ethnicity categories |
| `diet_types` | TEXT | Diet type categories |
| `smoking_status` | TEXT | Smoking status |
| `antibiotic_history` | TEXT | Antibiotic use history |
| `probiotic_use` | TEXT | Probiotic use |
| `intervention_groups` | TEXT | Intervention group labels |
| `lifestyle` | TEXT | Lifestyle factors |
| `biosample_age_values` | TEXT | Raw age values from BioSample (JSON array) |
| `biosample_bmi_values` | TEXT | Raw BMI values from BioSample (JSON array) |
| `biosample_n_samples_checked` | INTEGER | Samples checked for BioSample metadata |
| `biosample_n_samples_found` | INTEGER | Samples with BioSample metadata found |
| `biosample_all_attribute_keys` | TEXT | All MIxS attribute keys found (semicolon-separated) |

Note: Age values are cleaned during Phase 4 — birth-year tags (e.g. "birth year: 1994")
are filtered out, and day-scale ages (e.g. host_age=221) are converted to years.
Fields with <2 projects of data are flagged as `near_empty` in the data catalogue.

### `samples` / `biosample` (168,464 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `srs` | TEXT | SRS accession (NCBI BioSample) |
| `project_id` | TEXT | FK to projects (BioProject ID) |
| `srr` | TEXT | SRR accession (NCBI SRA run) |
| `library_strategy` | TEXT | Sequencing strategy (WGS, AMPLICON, etc.) |
| `library_source` | TEXT | Library source (GENOMIC, etc.) |
| `pubdate` | TEXT | Publication date |
| `total_bases` | INTEGER | Total sequencing bases |
| `instrument` | TEXT | Sequencing instrument |
| `geo_loc_name` | TEXT | Geographic location (country:region format) |
| `iso` | TEXT | ISO country code |
| `region` | TEXT | Geographic region |

### `sample_tags` / `biosample_attributes` (3,489,745 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `sample_id` | INTEGER | FK to samples |
| `tag` | TEXT | MIxS attribute name (host, env_medium, body_site, etc.) |
| `value` | TEXT | Attribute value |

### `omics_processing` (168,464 rows)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `biosample_id` | INTEGER | FK to samples |
| `study_id` | TEXT | FK to projects (BioProject ID) |
| `instrument_name` | TEXT | Sequencing instrument |
| `library_strategy` | TEXT | Sequencing strategy |
| `library_source` | TEXT | Library source |
| `total_bases` | INTEGER | Total bases sequenced |
| `omics_type` | TEXT | Omics type (metagenome, 16S, etc.) |
| `srr_accession` | TEXT | SRA run accession |
| `pubdate` | TEXT | Publication date |

### `biosample_entity_link`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `biosample_id` | INTEGER | FK to samples |
| `entity_id` | INTEGER | FK to entities |
| `link_type` | TEXT | Link type (see below) |
| `link_value` | TEXT | Match value that created the link |
| `confidence` | REAL | Link confidence score |

#### Link types

| link_type | Description |
|-----------|-------------|
| `project_condition` | Sample linked to DISEASE entity via project condition string match |
| `host_organism` | Sample linked to ORGANISM entity via project host_organism match |
| `sample_tag_host` | Sample linked to ORGANISM entity via MIxS 'host' tag value match |
| `project_mention` | Sample linked to DISEASE/ORGANISM entity mentioned in the same project's papers |

## Entity Types (14 CDM domains)

| Type | Description |
|------|-------------|
| ORGANISM | Microorganisms, taxa, species mentioned in microbiome studies |
| CHEMICAL | Chemicals, metabolites, compounds, drugs |
| DISEASE | Diseases, conditions, disorders, syndromes |
| PROTEIN | Proteins, enzymes, peptides, functional gene products |
| PATHWAY | Metabolic pathways, signaling pathways, biological processes |
| DNA_RNA | DNA/RNA sequences, genes, transcripts, oligonucleotides |
| CELL_TYPE | Cell types, cell lines, tissue types |
| GENOMICS | Genomic concepts, mutations, variants, sequencing terms |
| CLINICAL | Clinical findings, symptoms, patient characteristics |
| DATA_ANALYSIS | Statistical methods, bioinformatics tools, analysis approaches |
| EXPERIMENTAL_METHOD | Experimental designs, interventions, procedures |
| LAB_METHOD | Laboratory methods, techniques, protocols |
| SAMPLE_METHOD | Sample collection, preparation, storage methods |
| STUDY_DESIGN | Study types, cohort designs, trial structures |

## Relationship Types

| Type | Count | Description |
|------|-------|-------------|
| CO_OCCURS_WITH | 33,624 | Two entities co-occur in the same paper/context |
| ASSOCIATED_WITH | 17,754 | General association between entities |
| ENRICHED_IN | 480 | Entity is enriched in a condition/context |
| DEPLETED_IN | 363 | Entity is depleted in a condition/context |
| IMPLICATED_IN | 298 | Entity is implicated in a disease/process |
| PRODUCES | 288 | Entity produces a product/metabolite |
| INCREASES | 276 | Entity increases a quantity/activity |
| PART_OF_PATHWAY | 261 | Entity is part of a biological pathway |
| MODULATES | 179 | Entity modulates a process/activity |
| CAUSES | 161 | Entity causes a disease/condition |
| METABOLIZES | 153 | Entity metabolizes a substrate |
| PREDICTS | 132 | Entity predicts an outcome |
| DECREASES | 125 | Entity decreases a quantity/activity |
| PARTICIPATES_IN | 104 | Entity participates in a process |
| TREATS | 101 | Entity treats a disease/condition |
| IMPROVES | 88 | Entity improves an outcome |
| INHIBITS | 86 | Entity inhibits a process/activity |
| ACTIVATES | 71 | Entity activates a process/receptor |
| BINDS | 69 | Entity binds to a target |
| PRODUCED_BY | 46 | Entity is produced by a source |
| PREVENTS | 44 | Entity prevents a disease/condition |
| EXPRESSES | 41 | Entity expresses a gene/protein |
| REGULATES | 25 | Entity regulates a process/target |
| DISRUPTS | 14 | Entity disrupts a process/function |
| ENCODES | 4 | Gene encodes a protein |
| TREATED_BY | 1 | Disease is treated by a treatment |

### Relationship provenance

| source_type | Description |
|-------------|-------------|
| `llm_extracted` | Extracted by LLM (Qwen) from paper text |
| `llm_triple` | LLM-extracted subject-predicate-object triple |
| `co_occurrence` | Statistically significant co-occurrence in papers |
| `kb` | Derived from biological knowledge base |

| source_db | Description |
|-----------|-------------|
| `llm_triple` | LLM-extracted triples |
| `co-occurrence` | Co-occurrence-derived relationships |
| `biological_kb` | Biological knowledge base derived |
| `co-occurrence+kb` | Both co-occurrence and KB derived |

## Reproducibility

```bash
# Verify table counts
sqlite3 cdm/microbiome_cdm.db "SELECT count(*) FROM concept"
sqlite3 cdm/microbiome_cdm.db "SELECT count(*) FROM biosample"
sqlite3 cdm/microbiome_cdm.db "SELECT count(*) FROM biosample_entity_link"

# Check entity types
sqlite3 cdm/microbiome_cdm.db "SELECT type_name, description FROM entity_types"

# Check relationship types
sqlite3 cdm/microbiome_cdm.db "SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC"

# Check clinical metadata coverage
sqlite3 cdm/microbiome_cdm.db "SELECT COUNT(*) FROM projects WHERE age_min IS NOT NULL"
sqlite3 cdm/microbiome_cdm.db "SELECT COUNT(*) FROM projects WHERE bmi_mean IS NOT NULL"
```
"""

CORPUS_README = """# Microbiome-CDM Corpus

## Source

444 microbiome research papers from `data/papers_txt/`, each named by BioProject
accession (PRJ*). The corpus covers the 482 BioProjects in the 168k-samples
compendium (Abdill et al. 2025, Cell).

## Files

- `corpus_metadata.json` — per-paper metadata (project ID, file path, md5, entity count)
- `data/papers_txt/` — source text files (symlinked from repo root)

## Provenance

Papers were collected from PubMed Central and NCBI BioProject pages. Five
duplicate clusters (9 files, 5 unique md5s) were identified; canonical
representatives per cluster are documented in the v2.0 release.
"""

DATA_CATALOGUE_README = """# Microbiome-CDM Data Catalogue

## Files

- `data_catalogue.json` — full database statistics (all tables, vocabulary coverage, entity distribution, clinical metadata)
- `data_catalogue.csv` — flat table of per-table row counts
- `db_statistics.json` — detailed statistics (relationships by type, vocab by name, top entities, clinical aggregates)
- `clinical_metadata.csv` — clinical field coverage across 444 projects
- `disease_distribution.csv` — disease prevalence across projects
- `body_site_distribution.csv` — body site distribution across projects
- `README.md` — this file

## Clinical metadata coverage

The CDM captures all available clinical metadata from NCBI BioSample records:

| Field | Coverage | Description |
|-------|----------|-------------|
| Geo location | 80.7% | Country/region of sample collection |
| Host organism | 78.4% | Host species (Homo sapiens, Mus musculus, etc.) |
| Body site | 50.2% | Sample body site (feces, stool, biopsy, etc.) |
| Age | 21.4% | Age range/mean of study participants |
| Sex | 24.3% | Male/female counts per project |
| BMI | 9.8% | Body mass index mean |
| Diseases | 7.3% | Disease conditions studied |
| Race | 1.5% | Race/ethnicity |
| Lifestyle | 0.4% | Lifestyle factors |
| Diet | 0.2% | Diet type |
| Smoking | 0.2% | Smoking status |
| Antibiotic history | 0.2% | Antibiotic use |
| Probiotic use | 0.2% | Probiotic use |

## Usage

```python
import json
with open('data_catalogue.json') as f:
    catalogue = json.load(f)
print(f"Total entities: {catalogue['total_entities']:,}")
print(f"Total biosamples: {catalogue['total_biosamples']:,}")
print(f"CDM version: {catalogue['cdm_version']}")
# Clinical metadata
clinical = catalogue['clinical_metadata']
print(f"Diseases studied: {len(clinical['disease_distribution'])}")
print(f"Body sites: {len(clinical['body_site_distribution'])}")
print(f"Age range: {clinical['age_statistics']['min_age_global']}-{clinical['age_statistics']['max_age_global']}")
```
"""

CDM_README = """# Microbiome-CDM v3.0 — Common Data Model

## What is this?

The Microbiome Common Data Model (MCDM) v3.0 is a three-layer architecture:

1. **Vocabulary Layer** — OMOP CDM v5.4 aligned concept tables (26 vocabularies)
2. **Knowledge Layer** — 34,300 biomedical entities + 54,788 relationships extracted
   from 444 microbiome papers using multi-NER (GLiNER, PubMedBERT, PubTator3,
   sciSpaCy, Qwen)
3. **Data Layer** — 168,464 microbiome biosamples from 482 BioProjects (NMDC/MIxS aligned)

## Files

| File | Description |
|------|-------------|
| `microbiome_cdm.db` | SQLite database (three-layer CDM) |
| `schema.sql` | Full database schema (DDL) |
| `cdm_schema.md` | Human-readable schema documentation |

## Quick stats

| Metric | Value |
|--------|-------|
| Total entities | 34,300 |
| Total relationships | 54,788 |
| Total biosamples | 168,464 |
| Total sample attributes | 3,489,745 |
| Vocabulary mappings | 140,745 |
| OMOP vocabularies | 26 |
| CDM entity types | 14 |
| Source papers | 444 |
| BioProjects | 482 |

## How to verify

```bash
sqlite3 cdm/microbiome_cdm.db "SELECT count(*) FROM concept"
sqlite3 cdm/microbiome_cdm.db "SELECT count(*) FROM biosample"
sqlite3 cdm/microbiome_cdm.db "SELECT count(*) FROM omics_processing"
```

## Derived from

- v2.1.1-clean release (frozen knowledge graph)
- 168k-samples compendium (Abdill et al. 2025, Cell)
"""

RELEASE_README = """# Microbiome-CDM v3.0-cdm

**Status:** CDM-aligned release — the knowledge graph + OMOP vocabulary
infrastructure + NMDC-aligned sample-level data.

## Directory structure

```
v3.0-cdm/
├── corpus/           # Source papers + corpus metadata
│   ├── corpus_metadata.json
│   └── README.md
├── releases/data_catalogue/   # Database statistics + metadata
│   ├── data_catalogue.json
│   ├── data_catalogue.csv
│   ├── db_statistics.json
│   └── README.md
├── cdm/              # The Common Data Model
│   ├── microbiome_cdm.db
│   ├── schema.sql
│   ├── cdm_schema.md
│   └── README.md
└── README.md          # This file
```

## Three-layer CDM architecture

1. **Vocabulary Layer** (OMOP CDM v5.4 aligned): 8 concept tables, 26 vocabularies
2. **Knowledge Layer** (Biomedical KG): 34,300 entities, 54,788 relationships
3. **Data Layer** (NMDC/MIxS aligned): 168,464 biosamples, 3.5M attributes

See `cdm/cdm_schema.md` for full schema documentation.
"""


def export_schema_sql(db_path, out_path):
    """Export full database schema as SQL DDL."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type IN ('table','view','index') AND sql IS NOT NULL ORDER BY type DESC, name")
    statements = [r[0] for r in cur.fetchall()]
    conn.close()

    with open(out_path, "w") as f:
        f.write("-- Microbiome CDM v3.0 — Schema DDL\n")
        f.write(f"-- Generated: {datetime.now().isoformat()}\n")
        f.write(f"-- Database: {db_path.name}\n\n")
        for stmt in statements:
            f.write(stmt.strip() + ";\n\n")


def build_corpus_metadata(out_dir):
    """Build corpus metadata JSON."""
    corpus_dir = _paths.papers_txt()
    papers = []
    for f in sorted(corpus_dir.glob("PRJ*.txt")):
        import hashlib as hl
        content = f.read_bytes()
        papers.append({
            "project_id": f.stem,
            "filename": f.name,
            "size_bytes": len(content),
            "md5": hl.md5(content).hexdigest(),
        })
    metadata = {
        "name": "Microbiome-CDM Corpus",
        "version": "3.0",
        "total_papers": len(papers),
        "source": "PubMed Central / NCBI BioProject pages",
        "papers": papers,
    }
    out_path = out_dir / "corpus_metadata.json"
    with open(out_path, "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"  corpus_metadata.json: {len(papers)} papers")
    return out_path


def build_data_catalogue(db_path, out_dir):
    """Build data_catalogue.json, data_catalogue.csv, db_statistics.json."""
    import hashlib

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    sha256 = hashlib.sha256(open(db_path, "rb").read()).hexdigest()

    def count(table):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]

    def fetchall(sql):
        cur.execute(sql)
        return cur.fetchall()

    # Data catalogue (JSON)
    catalogue = {
        "name": "Microbiome Common Data Model",
        "version": "3.0",
        "release_name": "v3.0-cdm",
        "created": datetime.now().isoformat(),
        "db_sha256": sha256,
        "db_size_mb": round(db_path.stat().st_size / 1024 / 1024, 1),
        "architecture": "three-layer (vocabulary + knowledge + data)",
        "cdm_version": "3.0",

        # Corpus
        "source_papers": 444,
        "source_projects_metadata": 482,

        # Knowledge layer
        "total_entities": count("entities"),
        "total_relationships": count("relationships"),
        "total_edge_evidence": count("edge_evidence"),
        "total_controlled_vocabularies": count("controlled_vocabularies"),
        "total_mentions": count("entity_project_mentions"),
        "total_entity_types": count("entity_types"),

        # Data layer (NMDC-aligned)
        "total_studies": count("study"),
        "total_biosamples": count("biosample"),
        "total_biosample_attributes": count("biosample_attributes"),
        "total_omics_processing": count("omics_processing"),
        "total_data_objects": count("data_object"),
        "total_biosample_entity_links": count("biosample_entity_link"),

        # Vocabulary layer (OMOP)
        "total_concepts": count("concept"),
        "total_vocabularies": count("vocabulary"),
        "total_domains": count("domain"),
        "total_concept_relationships": count("concept_relationship"),
        "total_concept_synonyms": count("concept_synonym"),
        "total_concept_ancestors": count("concept_ancestor"),
        "total_source_to_concept_maps": count("source_to_concept_map"),

        # Mapping stats
        "mapped_entities": fetchall("SELECT COUNT(DISTINCT entity_id) FROM controlled_vocabularies")[0][0],
    }
    catalogue["mapping_rate"] = f"{catalogue['mapped_entities'] / catalogue['total_entities'] * 100:.1f}%"

    # Detailed distributions
    catalogue["entities_by_type"] = {r[0]: r[1] for r in fetchall(
        "SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC")}
    catalogue["vocabularies"] = [r[0] for r in fetchall(
        "SELECT vocabulary_id FROM vocabulary ORDER BY vocabulary_id")]
    catalogue["domains"] = [r[0] for r in fetchall("SELECT domain_id FROM domain ORDER BY domain_id")]
    catalogue["relationships_by_type"] = {r[0]: r[1] for r in fetchall(
        "SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC")}

    # --- Missing v2.0 sections ---
    # Top entities by frequency (top 20)
    catalogue["top_entities_by_frequency"] = [
        {"term": r[0], "type": r[1], "frequency": r[2]}
        for r in fetchall(
            "SELECT term, entity_type, frequency FROM entities "
            "ORDER BY frequency DESC LIMIT 20")
    ]

    # Top entities by mapping / paper_count (top 20)
    catalogue["top_entities_by_mapping"] = [
        {"term": r[0], "type": r[1], "paper_count": r[2]}
        for r in fetchall(
            "SELECT term, entity_type, paper_count FROM entities "
            "ORDER BY paper_count DESC LIMIT 20")
    ]

    # Relationships by source_type (v3.0 column name; v2.0 used 'source')
    catalogue["relationships_by_source"] = {
        r[0]: r[1] for r in fetchall(
            "SELECT COALESCE(source_type, 'NULL'), COUNT(*) FROM relationships "
            "GROUP BY source_type ORDER BY COUNT(*) DESC")
    }

    # Relationships by source_db
    catalogue["relationships_by_source_db"] = {
        r[0]: r[1] for r in fetchall(
            "SELECT COALESCE(source_db, 'NULL'), COUNT(*) FROM relationships "
            "GROUP BY source_db ORDER BY COUNT(*) DESC")
    }

    # Edges by provenance (v3.0 uses source_model on edge_evidence)
    catalogue["edges_by_provenance"] = {
        r[0]: r[1] for r in fetchall(
            "SELECT COALESCE(source_model, 'NULL'), COUNT(*) FROM edge_evidence "
            "GROUP BY source_model ORDER BY COUNT(*) DESC")
    }
    catalogue["vocab_by_name"] = {r[0]: r[1] for r in fetchall(
        "SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies GROUP BY vocabulary_name ORDER BY COUNT(*) DESC")}
    catalogue["biosample_links_by_type"] = {r[0]: r[1] for r in fetchall(
        "SELECT link_type, COUNT(*) FROM biosample_entity_link GROUP BY link_type ORDER BY COUNT(*) DESC")}
    catalogue["biosample_tag_distribution"] = {r[0]: r[1] for r in fetchall(
        "SELECT tag, COUNT(*) FROM sample_tags GROUP BY tag ORDER BY COUNT(*) DESC LIMIT 20")}
    catalogue["omics_type_distribution"] = {r[0]: r[1] for r in fetchall(
        "SELECT omics_type, COUNT(*) FROM omics_processing GROUP BY omics_type ORDER BY COUNT(*) DESC")}
    catalogue["build_type"] = "Multi-NER + co-occurrence + KB enrichment + 168k sample-level data + OMOP vocabulary infrastructure + NMDC-aligned biosample schema"

    # --- Clinical metadata (from BioSample demographics) ---
    clinical = {}

    # Coverage: how many projects have each clinical field populated
    clinical_fields = [
        "age_min", "age_max", "age_mean", "bmi_mean", "n_male", "n_female",
        "sex_distribution", "body_site", "diseases", "disease_flags",
        "geo_locations", "host_organism", "nationalities", "races",
        "diet_types", "smoking_status", "antibiotic_history", "probiotic_use",
        "intervention_groups", "lifestyle",
        "amplicon", "sample_type", "condition", "kit", "subjects", "link",
    ]
    n_projects = count("projects")
    clinical["coverage"] = {}
    for col in clinical_fields:
        try:
            cur.execute(f"SELECT COUNT(*) FROM projects WHERE {col} IS NOT NULL AND {col} != ''")
            n = cur.fetchone()[0]
        except sqlite3.Error:
            n = 0
        clinical["coverage"][col] = {
            "projects_with_data": n,
            "total_projects": n_projects,
            "percentage": f"{n / n_projects * 100:.1f}%" if n_projects else "0%",
            "near_empty": n < 2,
        }

    # Age statistics across all projects
    clinical["age_statistics"] = {}
    cur.execute("SELECT MIN(age_min), MAX(age_max), AVG(age_mean) FROM projects WHERE age_min IS NOT NULL")
    row = cur.fetchone()
    if row and row[0] is not None:
        clinical["age_statistics"]["min_age_global"] = row[0]
        clinical["age_statistics"]["max_age_global"] = row[1]
        clinical["age_statistics"]["avg_mean_age"] = round(row[2], 1) if row[2] else None

    cur.execute("SELECT COUNT(*) FROM projects WHERE age_mean IS NOT NULL")
    clinical["age_statistics"]["projects_with_age_data"] = cur.fetchone()[0]

    # BMI statistics
    clinical["bmi_statistics"] = {}
    cur.execute("SELECT MIN(bmi_mean), MAX(bmi_mean), AVG(bmi_mean) FROM projects WHERE bmi_mean IS NOT NULL")
    row = cur.fetchone()
    if row and row[0] is not None:
        clinical["bmi_statistics"]["min_bmi"] = row[0]
        clinical["bmi_statistics"]["max_bmi"] = row[1]
        clinical["bmi_statistics"]["avg_bmi"] = round(row[2], 1) if row[2] else None
    cur.execute("SELECT COUNT(*) FROM projects WHERE bmi_mean IS NOT NULL")
    clinical["bmi_statistics"]["projects_with_bmi_data"] = cur.fetchone()[0]

    # Sex distribution aggregates
    clinical["sex_distribution"] = {}
    cur.execute("SELECT SUM(n_male), SUM(n_female) FROM projects WHERE n_male IS NOT NULL OR n_female IS NOT NULL")
    row = cur.fetchone()
    clinical["sex_distribution"]["total_male"] = row[0] or 0
    clinical["sex_distribution"]["total_female"] = row[1] or 0
    cur.execute("SELECT COUNT(*) FROM projects WHERE n_male IS NOT NULL OR n_female IS NOT NULL")
    clinical["sex_distribution"]["projects_with_sex_data"] = cur.fetchone()[0]

    # Disease distribution (parse the semicolon-separated diseases field)
    disease_counts = {}
    cur.execute("SELECT diseases FROM projects WHERE diseases IS NOT NULL AND diseases != ''")
    for (d_str,) in cur.fetchall():
        for d in d_str.split(";"):
            d = d.strip()
            if d:
                disease_counts[d] = disease_counts.get(d, 0) + 1
    clinical["disease_distribution"] = dict(sorted(disease_counts.items(), key=lambda x: -x[1]))

    # Body site distribution
    body_site_counts = {}
    cur.execute("SELECT body_site FROM projects WHERE body_site IS NOT NULL AND body_site != ''")
    for (bs_str,) in cur.fetchall():
        for bs in bs_str.split(";"):
            bs = bs.strip()
            if bs:
                body_site_counts[bs] = body_site_counts.get(bs, 0) + 1
    clinical["body_site_distribution"] = dict(sorted(body_site_counts.items(), key=lambda x: -x[1]))

    # Host organism distribution
    host_counts = {}
    cur.execute("SELECT host_organism FROM projects WHERE host_organism IS NOT NULL AND host_organism != ''")
    for (h_str,) in cur.fetchall():
        for h in h_str.split(";"):
            h = h.strip()
            if h:
                host_counts[h] = host_counts.get(h, 0) + 1
    clinical["host_organism_distribution"] = dict(sorted(host_counts.items(), key=lambda x: -x[1]))

    # Geo location distribution (from projects)
    geo_counts = {}
    cur.execute("SELECT geo_locations FROM projects WHERE geo_locations IS NOT NULL AND geo_locations != ''")
    for (g_str,) in cur.fetchall():
        for g in g_str.split(";"):
            g = g.strip()
            if g:
                geo_counts[g] = geo_counts.get(g, 0) + 1
    clinical["geo_location_distribution"] = dict(sorted(geo_counts.items(), key=lambda x: -x[1]))

    # Race distribution
    race_counts = {}
    cur.execute("SELECT races FROM projects WHERE races IS NOT NULL AND races != ''")
    for (r_str,) in cur.fetchall():
        for r in r_str.split(";"):
            r = r.strip()
            if r:
                race_counts[r] = race_counts.get(r, 0) + 1
    clinical["race_distribution"] = dict(sorted(race_counts.items(), key=lambda x: -x[1]))

    # Nationality distribution
    nat_counts = {}
    cur.execute("SELECT nationalities FROM projects WHERE nationalities IS NOT NULL AND nationalities != ''")
    for (n_str,) in cur.fetchall():
        for n in n_str.split(";"):
            n = n.strip()
            if n:
                nat_counts[n] = nat_counts.get(n, 0) + 1
    clinical["nationality_distribution"] = dict(sorted(nat_counts.items(), key=lambda x: -x[1]))

    # Condition distribution (from projects.csv condition field)
    cond_counts = {}
    cur.execute("SELECT condition FROM projects WHERE condition IS NOT NULL AND condition != ''")
    for (c_str,) in cur.fetchall():
        c = c_str.strip()
        if c:
            cond_counts[c] = cond_counts.get(c, 0) + 1
    clinical["condition_distribution"] = dict(sorted(cond_counts.items(), key=lambda x: -x[1]))

    # Sample type distribution
    st_counts = {}
    cur.execute("SELECT sample_type FROM projects WHERE sample_type IS NOT NULL AND sample_type != ''")
    for (st_str,) in cur.fetchall():
        st = st_str.strip()
        if st:
            st_counts[st] = st_counts.get(st, 0) + 1
    clinical["sample_type_distribution"] = dict(sorted(st_counts.items(), key=lambda x: -x[1]))

    # Amplicon distribution
    amp_counts = {}
    cur.execute("SELECT amplicon FROM projects WHERE amplicon IS NOT NULL AND amplicon != ''")
    for (a_str,) in cur.fetchall():
        a = a_str.strip()
        if a:
            amp_counts[a] = amp_counts.get(a, 0) + 1
    clinical["amplicon_distribution"] = dict(sorted(amp_counts.items(), key=lambda x: -x[1]))

    # Kit distribution
    kit_counts = {}
    cur.execute("SELECT kit FROM projects WHERE kit IS NOT NULL AND kit != ''")
    for (k_str,) in cur.fetchall():
        k = k_str.strip()
        if k:
            kit_counts[k] = kit_counts.get(k, 0) + 1
    clinical["kit_distribution"] = dict(sorted(kit_counts.items(), key=lambda x: -x[1]))

    # Bead beating distribution
    cur.execute("SELECT bead_beating, COUNT(*) FROM projects WHERE bead_beating IS NOT NULL GROUP BY bead_beating")
    clinical["bead_beating_distribution"] = {str(r[0]): r[1] for r in cur.fetchall()}

    # Sequencing instrument distribution (from samples)
    clinical["instrument_distribution"] = {r[0]: r[1] for r in fetchall(
        "SELECT instrument, COUNT(*) FROM samples WHERE instrument IS NOT NULL GROUP BY instrument ORDER BY COUNT(*) DESC")}

    # Library strategy distribution (from samples)
    clinical["library_strategy_distribution"] = {r[0]: r[1] for r in fetchall(
        "SELECT library_strategy, COUNT(*) FROM samples WHERE library_strategy IS NOT NULL GROUP BY library_strategy ORDER BY COUNT(*) DESC")}

    # Geographic region distribution (from samples)
    clinical["sample_region_distribution"] = {r[0]: r[1] for r in fetchall(
        "SELECT COALESCE(region, 'Unknown'), COUNT(*) FROM samples GROUP BY region ORDER BY COUNT(*) DESC")}

    # Sample country distribution (from samples geo_loc_name, cleaned)
    clinical["sample_country_distribution"] = _clean_country_distribution(
        {r[0]: r[1] for r in fetchall(
            "SELECT COALESCE(geo_loc_name, 'Unknown'), COUNT(*) FROM samples GROUP BY geo_loc_name ORDER BY COUNT(*) DESC")}
    )

    # Pubdate range
    cur.execute("SELECT MIN(pubdate), MAX(pubdate) FROM samples WHERE pubdate IS NOT NULL")
    row = cur.fetchone()
    clinical["pubdate_range"] = {"min": row[0], "max": row[1]}

    # Total bases statistics
    cur.execute("SELECT MIN(total_bases), MAX(total_bases), AVG(total_bases) FROM samples WHERE total_bases IS NOT NULL")
    row = cur.fetchone()
    clinical["total_bases_statistics"] = {"min": row[0], "max": row[1], "avg": round(row[2], 0) if row[2] else None}

    # MIxS attribute tag distribution (from sample_tags — all 3.5M)
    clinical["mixs_attribute_distribution"] = {r[0]: r[1] for r in fetchall(
        "SELECT tag, COUNT(*) FROM sample_tags GROUP BY tag ORDER BY COUNT(*) DESC")}

    # All attribute keys across biosamples (from biosample_all_attribute_keys in projects)
    attr_key_counts = {}
    cur.execute("SELECT biosample_all_attribute_keys FROM projects WHERE biosample_all_attribute_keys IS NOT NULL AND biosample_all_attribute_keys != ''")
    for (ak_str,) in cur.fetchall():
        for ak in ak_str.split(";"):
            ak = ak.strip()
            if ak:
                attr_key_counts[ak] = attr_key_counts.get(ak, 0) + 1
    clinical["biosample_attribute_key_coverage"] = dict(sorted(attr_key_counts.items(), key=lambda x: -x[1]))

    # Lifestyle, diet, smoking, antibiotic, probiotic (low coverage but include everything)
    for field, label in [
        ("lifestyle", "lifestyle_distribution"),
        ("diet_types", "diet_distribution"),
        ("smoking_status", "smoking_status_distribution"),
        ("antibiotic_history", "antibiotic_history_distribution"),
        ("probiotic_use", "probiotic_use_distribution"),
        ("intervention_groups", "intervention_group_distribution"),
        ("disease_flags", "disease_flag_distribution"),
    ]:
        fcounts = {}
        cur.execute(f"SELECT {field} FROM projects WHERE {field} IS NOT NULL AND {field} != ''")
        for (val_str,) in cur.fetchall():
            for v in val_str.split(";"):
                v = v.strip()
                if v:
                    fcounts[v] = fcounts.get(v, 0) + 1
        clinical[label] = dict(sorted(fcounts.items(), key=lambda x: -x[1]))

    catalogue["clinical_metadata"] = clinical

    # Also dump clinical metadata as standalone CSV
    clinical_csv_path = out_dir / "clinical_metadata.csv"
    with open(clinical_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["field", "projects_with_data", "total_projects", "percentage", "near_empty"])
        for field, info in clinical["coverage"].items():
            writer.writerow([field, info["projects_with_data"], info["total_projects"], info["percentage"], info["near_empty"]])
    print(f"  clinical_metadata.csv: written")

    # Disease distribution CSV
    disease_csv_path = out_dir / "disease_distribution.csv"
    with open(disease_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["disease", "project_count"])
        for d, n in clinical["disease_distribution"].items():
            writer.writerow([d, n])
    print(f"  disease_distribution.csv: written")

    # Body site distribution CSV
    bs_csv_path = out_dir / "body_site_distribution.csv"
    with open(bs_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["body_site", "project_count"])
        for bs, n in clinical["body_site_distribution"].items():
            writer.writerow([bs, n])
    print(f"  body_site_distribution.csv: written")

    with open(out_dir / "data_catalogue.json", "w") as f:
        json.dump(catalogue, f, indent=2, ensure_ascii=False)
    print(f"  data_catalogue.json: {len(catalogue)} keys")

    # Data catalogue (CSV) — flat table of row counts
    with open(out_dir / "data_catalogue.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["table", "rows", "layer"])
        layer_map = {
            "concept": "vocabulary", "vocabulary": "vocabulary", "domain": "vocabulary",
            "concept_relationship": "vocabulary", "concept_ancestor": "vocabulary",
            "concept_synonym": "vocabulary", "source_to_concept_map": "vocabulary",
            "cdm_source": "vocabulary",
            "entities": "knowledge", "entity_types": "knowledge",
            "relationships": "knowledge", "edge_evidence": "knowledge",
            "controlled_vocabularies": "knowledge", "entity_project_mentions": "knowledge",
            "study": "data", "biosample": "data", "biosample_attributes": "data",
            "omics_processing": "data", "data_object": "data",
            "biosample_entity_link": "data",
        }
        for table in layer_map:
            try:
                n = count(table)
            except sqlite3.Error:
                n = "N/A (view)"
            writer.writerow([table, n, layer_map[table]])

    print(f"  data_catalogue.csv: written")

    # DB statistics (JSON) — detailed breakdowns
    stats = {
        "release_name": "v3.0-cdm",
        "created": datetime.now().isoformat(),
        "db_sha256": sha256,
        "db_size_mb": round(db_path.stat().st_size / 1024 / 1024, 1),
    }

    # Table list
    cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")
    all_tables = [r[0] for r in cur.fetchall()]
    stats["tables"] = {}
    for t in all_tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            stats["tables"][t] = cur.fetchone()[0]
        except sqlite3.Error:
            stats["tables"][t] = None

    # Relationships by source_db
    stats["relationships_by_source_db"] = {r[0]: r[1] for r in fetchall(
        "SELECT COALESCE(source_db, 'NULL'), COUNT(*) FROM relationships GROUP BY source_db ORDER BY COUNT(*) DESC")}

    # Projects metadata completeness
    projects_cols = ['amplicon', 'sample_type', 'condition', 'host_organism', 'link', 'kit', 'subjects',
                     'age_min', 'age_max', 'age_mean', 'bmi_mean', 'n_male', 'n_female',
                     'sex_distribution', 'body_site', 'diseases', 'disease_flags',
                     'geo_locations', 'nationalities', 'races', 'diet_types',
                     'smoking_status', 'antibiotic_history', 'probiotic_use',
                     'intervention_groups', 'lifestyle']
    for col in projects_cols:
        try:
            cur.execute(f"SELECT COUNT(*) FROM projects WHERE {col} IS NOT NULL AND {col} != ''")
            stats.setdefault("projects_metadata_coverage", {})[col] = cur.fetchone()[0]
        except sqlite3.Error:
            stats.setdefault("projects_metadata_coverage", {})[col] = 0

    # Sample geo coverage
    stats["samples_by_region"] = {r[0]: r[1] for r in fetchall(
        "SELECT COALESCE(region, 'Unknown'), COUNT(*) FROM samples GROUP BY region ORDER BY COUNT(*) DESC")}

    # Sample country coverage (cleaned: merge unknown/missing/not applicable into "Unknown")
    stats["samples_by_country"] = _clean_country_distribution(
        {r[0]: r[1] for r in fetchall(
            "SELECT COALESCE(geo_loc_name, 'Unknown'), COUNT(*) FROM samples GROUP BY geo_loc_name ORDER BY COUNT(*) DESC")}
    )

    # Instrument distribution
    stats["samples_by_instrument"] = {r[0]: r[1] for r in fetchall(
        "SELECT COALESCE(instrument, 'Unknown'), COUNT(*) FROM samples GROUP BY instrument ORDER BY COUNT(*) DESC")}

    # Library strategy distribution
    stats["samples_by_library_strategy"] = {r[0]: r[1] for r in fetchall(
        "SELECT COALESCE(library_strategy, 'Unknown'), COUNT(*) FROM samples GROUP BY library_strategy ORDER BY COUNT(*) DESC")}

    # Age + BMI aggregates across projects
    cur.execute("SELECT MIN(age_min), MAX(age_max), AVG(age_mean) FROM projects WHERE age_min IS NOT NULL")
    row = cur.fetchone()
    stats["age_global"] = {"min": row[0], "max": row[1], "avg_mean": round(row[2], 1) if row[2] else None}

    cur.execute("SELECT MIN(bmi_mean), MAX(bmi_mean), AVG(bmi_mean) FROM projects WHERE bmi_mean IS NOT NULL")
    row = cur.fetchone()
    stats["bmi_global"] = {"min": row[0], "max": row[1], "avg_mean": round(row[2], 1) if row[2] else None}

    cur.execute("SELECT SUM(n_male), SUM(n_female) FROM projects WHERE n_male IS NOT NULL OR n_female IS NOT NULL")
    row = cur.fetchone()
    stats["sex_global"] = {"total_male": row[0] or 0, "total_female": row[1] or 0}

    conn.close()

    with open(out_dir / "db_statistics.json", "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"  db_statistics.json: {len(stats)} keys")

    return catalogue


def phase4():
    """Phase 4: Create folder structure + schema docs + data catalogue."""
    print("=" * 60)
    print("Phase 4: Folder structure + schema docs + data catalogue")
    print("=" * 60)

    base = DST_DIR
    corpus_dir = base / "corpus"
    catalogue_dir = base / "data_catalogue"
    cdm_dir = base / "cdm"

    # Create folder structure
    for d in [corpus_dir, catalogue_dir, cdm_dir]:
        d.mkdir(parents=True, exist_ok=True)
    print(f"  Created folder structure: {corpus_dir.name}/, {catalogue_dir.name}/, {cdm_dir.name}/")

    # DB location: prefer DST_DB (root of release), fall back to cdm/ folder
    cdm_db = cdm_dir / "microbiome_cdm.db"
    if DST_DB.exists():
        # DB is at release root — move it into cdm/
        if cdm_db.exists():
            cdm_db.unlink()
        shutil.move(str(DST_DB), str(cdm_db))
        print(f"  Moved DB to {cdm_db}")
    elif cdm_db.exists():
        print(f"  DB already at {cdm_db}")
    else:
        print("ERROR: v3.0 DB not found. Run Phases 1-3 first.")
        sys.exit(1)

    # Clean age data (fix birth-year misinterpretation + day-scale ages)
    clean_age_data(cdm_db)

    # Export schema.sql
    export_schema_sql(cdm_db, cdm_dir / "schema.sql")
    print(f"  schema.sql: exported")

    # Write schema docs
    (cdm_dir / "cdm_schema.md").write_text(SCHEMA_DOC)
    print(f"  cdm_schema.md: written")

    # Build corpus metadata
    build_corpus_metadata(corpus_dir)

    # Copy 444 paper .txt files into corpus/papers/
    papers_src = _paths.papers_txt()
    papers_dst = corpus_dir / "papers"
    papers_dst.mkdir(parents=True, exist_ok=True)
    n_copied = 0
    for f in sorted(papers_src.glob("PRJ*.txt")):
        dst_f = papers_dst / f.name
        shutil.copy2(str(f), str(dst_f))
        n_copied += 1
    print(f"  Copied {n_copied} paper .txt files to corpus/papers/")

    # Write READMEs
    (corpus_dir / "README.md").write_text(CORPUS_README)
    (catalogue_dir / "README.md").write_text(DATA_CATALOGUE_README)
    (cdm_dir / "README.md").write_text(CDM_README)
    (base / "README.md").write_text(RELEASE_README)
    print(f"  READMEs: written")

    # Build data catalogue
    build_data_catalogue(cdm_db, catalogue_dir)

    print(f"\nPhase 4 complete")
    print(f"  Folder structure: {base}/{{corpus,data_catalogue,cdm}}/")

    # Print final structure
    import os
    for root, dirs, files in os.walk(base):
        level = root.replace(str(base), "").count(os.sep)
        indent = "  " * level
        print(f"  {indent}{os.path.basename(root)}/")
        for f in sorted(files):
            size = os.path.getsize(os.path.join(root, f))
            if size > 1024 * 1024:
                print(f"  {indent}  {f} ({size / 1024 / 1024:.1f} MB)")
            else:
                print(f"  {indent}  {f} ({size:,} bytes)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CDM Schema Alignment")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4], help="Run a specific phase")
    parser.add_argument("--all", action="store_true", help="Run all phases")
    args = parser.parse_args()

    if args.all:
        phase1()
        phase2()
        phase3()
        phase4()
    elif args.phase == 1:
        phase1()
    elif args.phase == 2:
        phase2()
    elif args.phase == 3:
        phase3()
    elif args.phase == 4:
        phase4()
    else:
        parser.print_help()
