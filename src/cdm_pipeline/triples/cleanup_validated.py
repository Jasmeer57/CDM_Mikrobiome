#!/usr/bin/env python3
"""Clean up validated triples: normalize non-CDM relations and slash-type entity types.

Fixes two issues identified in the validated triples:
1. 21 non-CDM relation predicates → mapped to closest CDM relation
2. 34 slash-type entity types (e.g., "DISEASE/CONDITION") → normalized to first part

Updates both the per-paper .validated.json files and the combined all_validated_triples.csv.
"""

import csv
import json
import os
import glob

REPO_ROOT = str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                     if (p / ".cdm_root").is_file()))
VALIDATED_DIR = os.path.join(
    REPO_ROOT, "paper", "_multi_ner_runs", "cdm_output", "triples", "validated",
)

CDM_RELATIONS = {
    "associated_with", "treats", "treated_by", "produces", "produced_by",
    "disrupts", "depleted_in", "enriched_in", "co_occurs_with", "encodes",
    "expresses", "part_of_pathway", "participates_in", "implicated_in",
}

CDM_TYPES = {
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
}

PREDICATE_MAP = {
    "induces_production_of": "produces",
    "part_of": "associated_with",
    "enriches_in": "enriched_in",
    "prevents": "treats",
    "tolerated_by": "associated_with",
    "inhibits": "disrupts",
    "modulates": "associated_with",
    "clears": "treats",
    "composed_of": "associated_with",
    "depletes": "disrupts",
}

SLASH_TYPE_MAP = {
    "DISEASE/CONDITION": "DISEASE",
    "CLINICAL/CONDITION": "CLINICAL",
    "DISEASE/CLINICAL": "DISEASE",
    "CHEMICAL/CLINICAL": "CHEMICAL",
    "LAB_METHOD/CLINICAL_TOOL": "LAB_METHOD",
    "CLINICAL/PROTEIN_EXPRESSION": "CLINICAL",
    "CHEMICAL/PHENOTYPE": "CHEMICAL",
    "CLINICAL/PHENOTYPE": "CLINICAL",
}


def fix_predicate(pred):
    pred_lower = pred.strip().lower()
    if pred_lower in CDM_RELATIONS:
        return pred, False
    mapped = PREDICATE_MAP.get(pred_lower)
    if mapped:
        return mapped, True
    return pred, False


def fix_entity_type(etype):
    if etype is None:
        return etype, False
    etype_stripped = etype.strip()
    if "/" not in etype_stripped:
        return etype_stripped, False
    mapped = SLASH_TYPE_MAP.get(etype_stripped)
    if mapped:
        return mapped, True
    first_part = etype_stripped.split("/")[0].strip()
    if first_part in CDM_TYPES:
        return first_part, True
    return etype_stripped, False


def process_json_file(path, stats):
    with open(path) as f:
        data = json.load(f)

    modified = False
    for triple in data.get("validated_triples", []):
        old_pred = triple.get("predicate", "")
        new_pred, changed = fix_predicate(old_pred)
        if changed:
            triple["predicate"] = new_pred
            stats["predicates_fixed"] += 1
            stats["predicate_details"].append(
                f"  {data['paper_id']}: ({triple['subject']}, {old_pred}→{new_pred}, {triple['object']})"
            )
            modified = True

        for field in ("subject_type", "object_type"):
            old_val = triple.get(field, "")
            new_val, changed = fix_entity_type(old_val)
            if changed:
                triple[field] = new_val
                stats["types_fixed"] += 1
                stats["type_details"].append(
                    f"  {data['paper_id']}: {field} {old_val}→{new_val} ({triple['subject']}, {triple['predicate']}, {triple['object']})"
                )
                modified = True

    if modified:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        stats["files_modified"] += 1


def process_csv(path, stats):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    modified = False
    for row in rows:
        old_pred = row.get("predicate", "")
        new_pred, changed = fix_predicate(old_pred)
        if changed:
            row["predicate"] = new_pred
            modified = True

        for field in ("subject_type", "object_type", "original_subject_type", "original_object_type"):
            old_val = row.get(field, "")
            if not old_val:
                continue
            new_val, changed = fix_entity_type(old_val)
            if changed:
                row[field] = new_val
                modified = True

    if modified:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        stats["csv_modified"] = True


def main():
    stats = {
        "predicates_fixed": 0,
        "types_fixed": 0,
        "files_modified": 0,
        "csv_modified": False,
        "predicate_details": [],
        "type_details": [],
    }

    json_files = sorted(glob.glob(os.path.join(VALIDATED_DIR, "*.validated.json")))
    print(f"Processing {len(json_files)} validated JSON files...")

    for path in json_files:
        process_json_file(path, stats)

    csv_path = os.path.join(VALIDATED_DIR, "all_validated_triples.csv")
    if os.path.exists(csv_path):
        print("Processing combined CSV...")
        process_csv(csv_path, stats)

    print()
    print("=" * 70)
    print("CLEANUP SUMMARY")
    print("=" * 70)
    print(f"  JSON files modified:        {stats['files_modified']}")
    print(f"  Predicates fixed:           {stats['predicates_fixed']}")
    print(f"  Entity types fixed:         {stats['types_fixed']}")
    print(f"  CSV modified:               {stats['csv_modified']}")

    if stats["predicate_details"]:
        print()
        print("--- Predicate Fixes ---")
        for d in stats["predicate_details"]:
            print(d)

    if stats["type_details"]:
        print()
        print("--- Entity Type Fixes ---")
        for d in stats["type_details"]:
            print(d)

    # Verify: re-scan for remaining issues
    print()
    print("=" * 70)
    print("VERIFICATION")
    print("=" * 70)
    remaining_pred = 0
    remaining_types = 0
    for path in json_files:
        with open(path) as f:
            data = json.load(f)
        for triple in data.get("validated_triples", []):
            pred = triple.get("predicate", "").strip().lower()
            if pred not in CDM_RELATIONS:
                remaining_pred += 1
            for field in ("subject_type", "object_type"):
                val = triple.get(field, "")
                if "/" in val:
                    remaining_types += 1

    print(f"  Remaining non-CDM predicates: {remaining_pred}")
    print(f"  Remaining slash-type fields:  {remaining_types}")
    print("  PASS" if remaining_pred == 0 and remaining_types == 0 else "  FAIL")


if __name__ == "__main__":
    main()
