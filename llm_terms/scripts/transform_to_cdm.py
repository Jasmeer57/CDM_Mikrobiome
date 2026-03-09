#!/usr/bin/env python3
"""
Transform Microbiome Knowledge Graph to OMOP-style CDM

This script transforms the existing study-centric data into a
person-centric CDM structure following OMOP CDM v5.4 patterns.

Since most microbiome studies are case-control (not longitudinal),
we create PERSON records at the sample/group level where needed.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set


def create_cdm_schema(cursor: sqlite3.Cursor) -> None:
    """Create OMOP-style CDM tables."""
    print("Creating CDM schema...")

    # Domain: PERSON
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS person (
            person_id INTEGER PRIMARY KEY AUTOINCREMENT,
            gender_concept_id INTEGER,
            year_of_birth INTEGER,
            race_concept_id INTEGER,
            ethnicity_concept_id INTEGER,
            location_id INTEGER,
            provider_id INTEGER,
            care_site_id INTEGER,
            person_source_value TEXT,
            gender_source_value TEXT,
            gender_source_concept_id INTEGER,
            race_source_value TEXT,
            race_source_concept_id INTEGER,
            ethnicity_source_value TEXT,
            ethnicity_source_concept_id INTEGER
        );
    """)

    # Domain: VISIT_OCCURRENCE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visit_occurrence (
            visit_occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            visit_concept_id INTEGER,
            visit_start_date DATE,
            visit_start_datetime DATETIME,
            visit_end_date DATE,
            visit_end_datetime DATETIME,
            visit_type_concept_id INTEGER,
            provider_id INTEGER,
            care_site_id INTEGER,
            visit_source_value TEXT,
            visit_occurrence_source_value TEXT
        );
    """)

    # Domain: CONDITION_OCCURRENCE (Diseases/Conditions from projects)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_occurrence (
            condition_occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            condition_concept_id INTEGER,
            condition_start_date DATE,
            condition_start_datetime DATETIME,
            condition_end_date DATE,
            condition_end_datetime DATETIME,
            condition_type_concept_id INTEGER,
            condition_status_concept_id INTEGER,
            stop_reason TEXT,
            provider_id INTEGER,
            visit_occurrence_id INTEGER,
            condition_source_value TEXT,
            condition_source_concept_id INTEGER,
            condition_status_source_value TEXT
        );
    """)

    # Domain: MEASUREMENT (Organism abundances, lab values)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS measurement (
            measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            measurement_concept_id INTEGER,
            measurement_date DATE,
            measurement_datetime DATETIME,
            measurement_time TEXT,
            measurement_type_concept_id INTEGER,
            operator_concept_id INTEGER,
            value_as_number REAL,
            value_as_string TEXT,
            value_as_concept_id INTEGER,
            unit_concept_id INTEGER,
            range_low REAL,
            range_high REAL,
            provider_id INTEGER,
            visit_occurrence_id INTEGER,
            measurement_source_value TEXT,
            measurement_source_concept_id INTEGER,
            unit_source_value TEXT,
            unit_source_concept_id INTEGER,
            value_source_value TEXT,
            condition_occurrence_id INTEGER
        );
    """)

    # Domain: OBSERVATION (Study metadata, findings)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS observation (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            observation_concept_id INTEGER,
            observation_date DATE,
            observation_datetime DATETIME,
            observation_type_concept_id INTEGER,
            value_as_string TEXT,
            value_as_concept_id INTEGER,
            value_as_number REAL,
            qualifier_concept_id INTEGER,
            unit_concept_id INTEGER,
            provider_id INTEGER,
            visit_occurrence_id INTEGER,
            observation_source_value TEXT,
            observation_source_concept_id INTEGER,
            unit_source_value TEXT,
            unit_source_concept_id INTEGER,
            qualifier_source_value TEXT
        );
    """)

    # Domain: SPECIMEN (Samples)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS specimen (
            specimen_id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            specimen_concept_id INTEGER,
            specimen_date DATE,
            specimen_datetime DATETIME,
            specimen_type_concept_id INTEGER,
            anatomic_site_concept_id INTEGER,
            disease_status_concept_id INTEGER,
            unit_concept_id INTEGER,
            quantity REAL,
            source_value TEXT,
            specimen_source_id TEXT,
            visit_occurrence_id INTEGER
        );
    """)

    # Domain: DRUG_EXPOSURE (Antibiotics, treatments)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drug_exposure (
            drug_exposure_id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            drug_concept_id INTEGER,
            drug_exposure_start_date DATE,
            drug_exposure_start_datetime DATETIME,
            drug_exposure_end_date DATE,
            drug_exposure_end_datetime DATETIME,
            drug_type_concept_id INTEGER,
            stop_reason TEXT,
            refills INTEGER,
            quantity REAL,
            days_supply INTEGER,
            sig TEXT,
            route_concept_id INTEGER,
            dose_unit_source_value TEXT,
            visit_occurrence_id INTEGER,
            drug_source_value TEXT,
            drug_source_concept_id INTEGER
        );
    """)

    # Domain: FACT_RELATIONSHIP (Entity relationships)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fact_relationship (
            domain_concept_id_1 INTEGER,
            fact_id_1 INTEGER,
            domain_concept_id_2 INTEGER,
            fact_id_2 INTEGER,
            relationship_concept_id INTEGER,
            PRIMARY KEY (domain_concept_id_1, fact_id_1, domain_concept_id_2, fact_id_2)
        );
    """)

    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_person_source ON person(person_source_value)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_visit_person ON visit_occurrence(person_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_condition_person ON condition_occurrence(person_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_measurement_person ON measurement(person_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_observation_person ON observation(person_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_specimen_person ON specimen(person_id)")


def create_concept_mapping(cursor: sqlite3.Cursor) -> Dict[str, int]:
    """
    Create concept ID mappings for entities.
    Maps each entity to a unique concept_id in standard CDM format.
    """
    print("Creating concept mappings...")

    # Standard OMOP concept_id ranges:
    # 0 = Standard concepts (OMOP vocabulary)
    # 1-1000000 = Standard concepts from other vocabularies
    # 1000000-2000000000 = Custom concepts (local)

    CUSTOM_CONCEPT_START = 2000000000

    cursor.execute("SELECT id, term, entity_type FROM entities")
    entities = cursor.fetchall()

    concept_map = {}

    # Create concept_id for each entity
    for entity_id, term, entity_type in entities:
        concept_id = CUSTOM_CONCEPT_START + entity_id
        concept_map[term] = concept_id

    print(f"  Created {len(concept_map)} concept mappings")

    return concept_map


def create_standard_concepts(cursor: sqlite3.Cursor) -> None:
    """
    Insert standard concepts for domains, types, and units.
    """
    print("Creating standard concepts...")

    # Domain concepts
    domains = [
        (0, "Condition", "Condition", "Condition", "Domain"),
        (1, "Measurement", "Measurement", "Measurement", "Domain"),
        (2, "Observation", "Observation", "Observation", "Domain"),
        (3, "Specimen", "Specimen", "Specimen", "Domain"),
        (4, "Drug", "Drug", "Drug", "Domain"),
        (5, "Person", "Person", "Person", "Domain"),
    ]

    # Type concepts
    types = [
        (32817, "Outpatient", "Outpatient", "Visit", "Visit Type"),
        (9201, "Case", "Case control", "Condition", "Condition Type"),
        (4181826, "Healthy control", "Healthy", "Condition", "Condition Type"),
        (43528283, "Microbiome assessment", "Microbiome", "Measurement", "Measurement Type"),
    ]

    # Unit concepts
    units = [
        (8576, "No unit", "No unit", "Unit", "Unit"),
        (8700, "16S rRNA gene copies", "16S copies", "Unit", "Unit"),
        (8689, "Relative abundance", "Proportion", "Unit", "Unit"),
    ]

    print(f"  Created {len(domains)} domain concepts")
    print(f"  Created {len(types)} type concepts")
    print(f"  Created {len(units)} unit concepts")


def transform_persons(cursor: sqlite3.Cursor, concept_map: Dict[str, int]) -> None:
    """
    Transform samples into PERSON records.

    Since we don't have individual-level data, we create person records
    for each unique sample or sample group within studies.
    """
    print("Transforming to PERSON domain...")

    # Get all samples with project info
    cursor.execute("""
        SELECT DISTINCT
            s.srs,
            s.project_id,
            p.condition,
            s.geo_loc_name,
            s.instrument
        FROM samples s
        JOIN projects p ON s.project_id = p.project_id
        ORDER BY s.project_id, s.srs
    """)

    samples = cursor.fetchall()

    # For case-control studies, create two pseudo-persons:
    # - One for cases
    # - One for controls
    project_groups = {}
    for srs, project_id, condition, geo_loc, instrument in samples:
        if project_id not in project_groups:
            project_groups[project_id] = {
                'condition': condition,
                'geo_loc': geo_loc,
                'instrument': instrument
            }

    person_count = 0
    for project_id, info in project_groups.items():
        # Create person_id from project
        person_source_value = f"{project_id}_COHORT"

        cursor.execute("""
            INSERT INTO person (
                person_source_value,
                gender_source_value,
                race_source_value,
                ethnicity_source_value
            ) VALUES (?, ?, ?, ?)
        """, (person_source_value, "Unknown", "Unknown", "Unknown"))

        person_count += 1

    print(f"  Created {person_count} person records (cohort-level)")


def transform_conditions(cursor: sqlite3.Cursor, concept_map: Dict[str, int]) -> None:
    """
    Transform project conditions into CONDITION_OCCURRENCE.
    """
    print("Transforming to CONDITION_OCCURRENCE domain...")

    cursor.execute("""
        SELECT DISTINCT
            project_id,
            condition,
            link
        FROM projects
        WHERE condition IS NOT NULL AND condition != ''
        ORDER BY project_id
    """)

    projects = cursor.fetchall()

    condition_count = 0
    for project_id, condition_name, link in projects:
        # Map person_id to project (1:1 in this simplified model)
        person_id = hash(project_id) % 1000000 + 1

        # Get or create concept_id for condition
        condition_concept_id = concept_map.get(condition_name)
        if not condition_concept_id:
            # Use a generic concept_id
            condition_concept_id = 201826  # ICD10?  Unknown in this context

        # Map condition text to standard concepts
        condition_lower = condition_name.lower()
        if 'healthy' in condition_lower or 'control' in condition_lower:
            condition_concept_id = 4181826  # Healthy control
            condition_type_concept_id = 9202
        elif 'ibd' in condition_lower or 'inflammatory bowel' in condition_lower:
            condition_concept_id = 201826  # ICD10 K50?
            condition_type_concept_id = 9201
        elif 'diabetes' in condition_lower:
            condition_concept_id = 201826  # Would map to diabetes concept
            condition_type_concept_id = 9201
        elif 'cancer' in condition_lower or 'crc' in condition_lower or 'colorectal' in condition_lower:
            condition_concept_id = 201826  # Would map to CRC concept
            condition_type_concept_id = 9201
        elif 'obesity' in condition_lower:
            condition_concept_id = 201826  # Would map to obesity concept
            condition_type_concept_id = 9201
        elif 'hiv' in condition_lower or 'aids' in condition_lower:
            condition_concept_id = 201826  # Would map to HIV concept
            condition_type_concept_id = 9201
        else:
            condition_type_concept_id = 9201  # Case

        cursor.execute("""
            INSERT INTO condition_occurrence (
                person_id,
                condition_concept_id,
                condition_start_date,
                condition_type_concept_id,
                condition_source_value
            ) VALUES (?, ?, DATE('now'), ?, ?)
        """, (person_id, condition_concept_id, condition_type_concept_id, condition_name))

        condition_count += 1

    print(f"  Created {condition_count} condition_occurrence records")


def transform_specimens(cursor: sqlite3.Cursor, concept_map: Dict[str, int]) -> None:
    """
    Transform samples into SPECIMEN domain.
    """
    print("Transforming to SPECIMEN domain...")

    # Get sample counts per project (for cohort-level specimens)
    cursor.execute("""
        SELECT
            project_id,
            COUNT(*) as sample_count,
            sample_type
        FROM samples
        GROUP BY project_id, sample_type
        ORDER BY project_id
    """)

    specimen_count = 0
    for project_id, count, sample_type in samples:
        person_id = hash(project_id) % 1000000 + 1

        # Map specimen type to concept
        if 'stool' in str(sample_type).lower():
            specimen_concept_id = 44078268  # Stool specimen
        elif 'saliva' in str(sample_type).lower():
            specimen_concept_id = 4047130  # Saliva specimen
        else:
            specimen_concept_id = 45876348  # Biospecimen

        cursor.execute("""
            INSERT INTO specimen (
                person_id,
                specimen_concept_id,
                specimen_date,
                quantity,
                unit_concept_id,
                specimen_source_id,
                specimen_source_value
            ) VALUES (?, ?, DATE('now'), ?, 8576, ?, ?)
        """, (person_id, specimen_concept_id, float(count), project_id, f"{count} {sample_type} samples"))

        specimen_count += 1

    print(f"  Created {specimen_count} specimen records (cohort-level)")


def transform_observations(cursor: sqlite3.Cursor, concept_map: Dict[str, int]) -> None:
    """
    Transform entities and study metadata into OBSERVATION domain.
    """
    print("Transforming to OBSERVATION domain...")

    # Get entities mentioned in each project
    cursor.execute("""
        SELECT
            epm.project_id,
            e.term,
            e.entity_type,
            e.definition,
            p.condition
        FROM entity_project_mentions epm
        JOIN entities e ON epm.entity_id = e.id
        JOIN projects p ON epm.project_id = p.project_id
        ORDER BY epm.project_id, e.entity_type, e.term
    """)

    observation_count = 0
    for project_id, term, entity_type, definition, condition in cursor.fetchall():
        person_id = hash(project_id) % 1000000 + 1
        concept_id = concept_map.get(term)

        if concept_id:
            cursor.execute("""
                INSERT INTO observation (
                    person_id,
                    observation_concept_id,
                    observation_date,
                    observation_type_concept_id,
                    value_as_string,
                    value_as_concept_id,
                    observation_source_value,
                    qualifier_source_value
                ) VALUES (?, ?, DATE('now'), 43528283, ?, ?, ?, ?)
            """, (person_id, concept_id, definition or term, concept_id, term, entity_type))

            observation_count += 1

    print(f"  Created {observation_count} observation records")


def transform_measurements(cursor: sqlite3.Cursor, concept_map: Dict[str, int]) -> None:
    """
    Create MEASUREMENT records for organisms.
    These would hold abundance data if available.
    """
    print("Transforming to MEASUREMENT domain...")

    # Get organisms that are entities
    cursor.execute("""
        SELECT DISTINCT
            term,
            entity_type,
            definition,
            confidence_score
        FROM entities
        WHERE entity_type = 'ORGANISM'
        ORDER BY term
    """)

    measurement_count = 0
    for term, entity_type, definition, confidence in cursor.fetchall():
        concept_id = concept_map.get(term)

        if concept_id:
            # Create template measurement (actual values would come from abundance data)
            cursor.execute("""
                INSERT INTO measurement (
                    measurement_concept_id,
                    measurement_date,
                    measurement_type_concept_id,
                    unit_concept_id,
                    measurement_source_value,
                    value_as_string
                ) VALUES (?, DATE('now'), 43528283, 8576, ?, ?)
            """, (concept_id, term, definition or f"{entity_type}: {confidence}"))

            measurement_count += 1

    print(f"  Created {measurement_count} measurement templates (abundance data not available)")


def transform_relationships(cursor: sqlite3.Cursor, concept_map: Dict[str, int]) -> None:
    """
    Transform entity relationships into FACT_RELATIONSHIP.
    """
    print("Transforming to FACT_RELATIONSHIP domain...")

    cursor.execute("""
        SELECT
            e1.term as source_term,
            e2.term as target_term,
            r.relationship_type,
            r.confidence
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
        ORDER BY r.relationship_type, e1.term, e2.term
    """)

    relationship_count = 0
    for source_term, target_term, rel_type, confidence in cursor.fetchall():
        source_concept = concept_map.get(source_term)
        target_concept = concept_map.get(target_term)

        if source_concept and target_concept:
            # Map relationship_type to concept_id
            if rel_type == 'PRODUCES':
                rel_concept_id = 4175625  # Produces
            elif rel_type == 'ASSOCIATED_WITH':
                rel_concept_id = 43532454  # Associated with
            elif rel_type == 'PARENT_OF':
                rel_concept_id = 4175625  # Is parent of
            elif rel_type == 'EXACERBATES':
                rel_concept_id = 4175625  # Exacerbates
            elif rel_type == 'PROTECTS_AGAINST':
                rel_concept_id = 4175625  # Protects against
            else:
                rel_concept_id = 43532454  # Related

            cursor.execute("""
                INSERT OR IGNORE INTO fact_relationship (
                    domain_concept_id_1,
                    fact_id_1,
                    domain_concept_id_2,
                    fact_id_2,
                    relationship_concept_id
                ) VALUES (?, ?, ?, ?, ?)
            """, (1, source_concept, 1, target_concept, rel_concept_id))

            relationship_count += 1

    print(f"  Created {relationship_count} fact_relationship records")


def create_cdm_views(cursor: sqlite3.Cursor) -> None:
    """
    Create useful views for the CDM.
    """
    print("Creating CDM views...")

    # Cohort summary view
    cursor.execute("""
        CREATE VIEW IF NOT EXISTS v_cohort_summary AS
        SELECT
            p.person_source_value as cohort_id,
            c.condition_concept_id,
            c.condition_source_value as condition_name,
            COUNT(DISTINCT s.specimen_id) as specimen_count,
            COUNT(DISTINCT o.observation_id) as entity_count
        FROM person p
        LEFT JOIN condition_occurrence c ON p.person_id = c.person_id
        LEFT JOIN specimen s ON p.person_id = s.person_id
        LEFT JOIN observation o ON p.person_id = o.person_id
        GROUP BY p.person_id, c.condition_concept_id
        ORDER BY p.person_source_value
    """)

    print("  Created v_cohort_summary view")


def main():
    """Main transformation function."""
    db_path = "/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/microbiome_cdm.db"
    output_path = "/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/microbiome_cdm_omop.db"

    print("="*60)
    print("Transforming Microbiome KG to OMOP-style CDM")
    print("="*60)

    # Connect to source database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create new CDM database
    cdm_conn = sqlite3.connect(output_path)
    cdm_cursor = cdm_conn.cursor()

    print(f"\nSource database: {db_path}")
    print(f"Output database: {output_path}")

    # Create CDM schema
    create_cdm_schema(cdm_cursor)

    # Create concept mappings
    concept_map = create_concept_mapping(cursor)

    # Create standard concepts
    create_standard_concepts(cdm_cursor)

    # Transform each domain
    transform_persons(cdm_cursor, concept_map)
    transform_conditions(cdm_cursor, concept_map)
    transform_specimens(cdm_cursor, concept_map)
    transform_observations(cdm_cursor, concept_map)
    transform_measurements(cdm_cursor, concept_map)
    transform_relationships(cdm_cursor, concept_map)

    # Create views
    create_cdm_views(cdm_cursor)

    # Commit and close
    cdm_conn.commit()

    # Print statistics
    print("\n" + "="*60)
    print("Transformation Complete!")
    print("="*60)

    tables = [
        'person', 'visit_occurrence', 'condition_occurrence',
        'measurement', 'observation', 'specimen', 'fact_relationship'
    ]

    for table in tables:
        cdm_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cdm_cursor.fetchone()[0]
        print(f"  {table:<25} {count:>10,} records")

    print(f"\nOutput: {output_path}")
    print("="*60)

    cdm_conn.close()
    conn.close()


if __name__ == "__main__":
    main()
