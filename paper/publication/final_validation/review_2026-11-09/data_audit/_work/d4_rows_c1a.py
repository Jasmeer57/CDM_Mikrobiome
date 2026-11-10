#!/usr/bin/env python3
"""D4 rows fragment c1a: P01, P02, P02b, P03R, R01R, R02, R03, R04. Emits d4_rows_c1a.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REL = "releases/terminology/1.0.1"
DB = "microbiome_cdm_v3.db"


def R(check_name, artifact, expected, observed, query_or_file, status, note=""):
    return {"pass": "D4", "artifact": artifact, "check_name": check_name,
            "expected": expected, "observed": observed,
            "query_or_file": query_or_file, "status": status, "note": note}


rows = [
    R("provenance_hashes_three_way_tie",
      f"{REL}/PROVENANCE.json + MANIFEST.sha256",
      "all 8 PROVENANCE.artifacts hashes == MANIFEST.sha256 == recomputed sha256",
      "8 three-way ties, mismatch=[]",
      "PROVENANCE.json artifacts vs MANIFEST.sha256 vs sha256sum recompute",
      "PASS", ""),
    R("provenance_counts_match_file_rows",
      f"{REL}/PROVENANCE.json",
      "mentions 2,505,735 / canonical_terms 165,991 / definitions 1,150 / mappings 334,231",
      "mentions 2,505,735 / canonical_terms 165,991 / definitions 1,150 / mappings 334,231",
      "PROVENANCE.counts vs wc -l of the four jsonl artifacts",
      "PASS", ""),
    R("provenance_calibration_and_autoaccept",
      f"{REL}/PROVENANCE.json",
      "auto_accepted 0; calibration NOT_CALIBRATED",
      "auto_accept_eligible 38,334, auto_accepted 0, calibration NOT_CALIBRATED",
      "PROVENANCE.json counts/calibration fields",
      "PASS", ""),
    R("mention_count_chain_deltas_documented",
      f"{REL}/_mentions_summary.json + terminology_extraction_manifest.json (1.0.0 AND 1.0.1) + term_mentions.jsonl + {DB}:term_mention",
      "rows_written 2,505,736 -> manifest coverage.mention_records 2,505,736 -> shipped jsonl 2,505,735 (delta 1: frozen G2 off-by-one) -> DB 2,505,684 (delta 51: documented load dedup)",
      "written 2505736, manifest 2505736 (identically in 1.0.0 and 1.0.1), jsonl 2505735, DB 2505684; deltas exactly 1 and 51",
      "count chain across the four sources in both releases",
      "PASS",
      "supersedes original P03 (expected manifest 2,505,735 — wrong: the manifest writes 2,505,736 in both releases); the +1/-51 deltas are the documented frozen G2 off-by-one (must not be patched) and the D1 load-dedup tie"),
    R("taxonomy_shape_keys_reverified",
      f"{REL}/terminology_taxonomy.json + taxonomy_summary.json",
      "upper_categories 16, subcategories 66, reserved_categories [UNCERTAIN], status DRAFT, classified_terms 0",
      "upper_categories 16 / subcategories 66 / reserved_categories ['UNCERTAIN'] / status DRAFT / summary classified 0",
      "terminology_taxonomy.json actual schema keys + taxonomy_summary.json",
      "PASS",
      "supersedes original R01 (keyed a nonexistent 'categories' field, scored DISCREPANCY): re-keyed to the file's actual schema (upper_categories/subcategories)"),
    R("canonical_cdm_type_census",
      f"{REL}/canonical_terms.jsonl",
      "ENTITY 94,458 / ORGANISM 12,248 / CHEMICAL 9,673 / PROTEIN 8,752 / DISEASE 7,351 / DNA_RNA 6,386 / CELL_TYPE 4,853 / CLINICAL 3,932 / DATA_ANALYSIS 3,716 / EXPERIMENTAL_METHOD 3,698 / LAB_METHOD 3,179 / GENOMICS 2,201 / PATHWAY 1,905 / SAMPLE_METHOD 1,829 / STUDY_DESIGN 1,810",
      "all 15 values match (sum 165,991)",
      "canonical_terms.jsonl GROUP BY cdm_type vs canonical_terms_summary.by_cdm_type",
      "PASS", ""),
    R("canonical_taxonomy_category_all_null",
      f"{REL}/canonical_terms.jsonl",
      "0 rows with non-null taxonomy_category (no classification pass run)",
      "0 non-null; is_generic_type census {False: 71,533, True: 94,458}",
      "predicate scan of canonical_terms.jsonl",
      "PASS", ""),
    R("ontology_registry_structure",
      f"{REL}/ontology_registry.json",
      "registry lists local-only vocabularies with versions (structural check)",
      "keys: ['credentials_policy', 'generated_at', 'local_only_note', 'local_only_supported', 'n_local', 'n_network', 'n_vocabularies', 'note', 'vocabularies']",
      "ontology_registry.json structure scan",
      "PASS", ""),
]

with open(os.path.join(HERE, "d4_rows_c1a.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"c1a: wrote {len(rows)} rows")
