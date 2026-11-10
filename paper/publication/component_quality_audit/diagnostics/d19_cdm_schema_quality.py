"""D19 - CDM 3.0.3 schema and structural quality (component H).

Read-only. Audits the 44 tables / 866 columns as a data model: key and
cardinality structure, undeclared foreign keys, multi-value columns, JSON-in-TEXT
columns, redundant representations, provenance columns, text-version hashes,
column documentation coverage, and whether the schema can express the
distinctions the source literature makes.

Does not restate D02 (referential integrity), D03 (rollups) or D09 (queries).
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3

from common import CAT, DB, REPO, emit

CDM_TYPES = {
    "ORGANISM", "TAXON", "CHEMICAL", "GENE", "PROTEIN", "DISEASE", "PHENOTYPE",
    "ANATOMY", "HABITAT", "DIET", "HOST", "EXPERIMENTAL_METHOD",
    "SEQUENCING_PLATFORM", "STATISTICAL_METHOD", "CLINICAL", "OTHER", "ENTITY",
}


def main():
    out = {}
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    views = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
    )]
    out["tables"] = len(tables)
    out["table_names"] = tables
    out["views"] = views

    schema = {}
    total_cols = 0
    for t in tables:
        info = list(c.execute('PRAGMA table_info("%s")' % t))
        idx = list(c.execute('PRAGMA index_list("%s")' % t))
        pk = [r[1] for r in info if r[5]]
        cols = [r[1] for r in info]
        total_cols += len(cols)
        schema[t] = {
            "columns": len(cols),
            "column_names": cols,
            "pk": pk,
            "indexes": [r[1] for r in idx],
            "unique_indexes": [
                (r[1], [x[2] for x in c.execute('PRAGMA index_info("%s")' % r[1])])
                for r in idx if r[2]
            ],
            "rows": c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0],
            "declared_fk": len([r for r in info if r[3]]),
        }
    out["total_columns"] = total_cols
    out["schema"] = schema

    # ---- identifier and cardinality structure ------------------------------
    out["tables_without_pk"] = [t for t, s in schema.items() if not s["pk"]]
    out["tables_without_unique_index"] = [
        t for t, s in schema.items() if s["rows"] > 0 and not s["unique_indexes"]
    ]
    out["tables_without_index"] = [
        t for t, s in schema.items() if s["rows"] > 1000 and not s["indexes"]
    ]

    # ---- multi-value (semicolon) and JSON-in-TEXT columns ------------------
    semicolon = {}
    jsonish = {}
    for t in tables:
        for col in schema[t]["column_names"]:
            n = c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
            if n == 0:
                continue
            probe = c.execute(
                'SELECT COUNT(*) FROM "%s" WHERE "%s" LIKE \'%%;%%\'' % (t, col)
            ).fetchone()[0]
            if probe:
                semicolon["%s.%s" % (t, col)] = {
                    "rows_with_semicolon": probe, "table_rows": n,
                    "pct": round(100.0 * probe / n, 2),
                }
    out["semicolon_columns"] = semicolon
    out["semicolon_column_count"] = len(semicolon)

    # JSON-shaped columns: leading [ or { on a sample
    for t in tables:
        for col in schema[t]["column_names"]:
            n = c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
            if n == 0:
                continue
            probe = c.execute(
                'SELECT COUNT(*) FROM "%s" WHERE "%s" LIKE \'[%%\' OR "%s" LIKE \'{{%%\'' % (t, col, col)
            ).fetchone()[0]
            if probe:
                jsonish["%s.%s" % (t, col)] = probe
    out["json_encoded_columns"] = jsonish
    out["json_encoded_column_count"] = len(jsonish)

    # ---- provenance coverage ----------------------------------------------
    prov_tokens = ("run_id", "extraction_run", "provenance", "source_", "created",
                   "built", "version", "sha256", "generated")
    prov_by_table = {}
    for t in tables:
        hits = [col for col in schema[t]["column_names"]
                if any(tok in col.lower() for tok in prov_tokens)]
        prov_by_table[t] = hits
    out["provenance_columns_by_table"] = prov_by_table
    out["tables_with_no_provenance_column"] = [t for t, v in prov_by_table.items() if not v]
    out["tables_with_run_id"] = [
        t for t, v in prov_by_table.items() if any("run_id" in x.lower() for x in v)
    ]

    # ---- text-version hashes ---------------------------------------------
    hash_cols = collections.Counter()
    for t in tables:
        for col in schema[t]["column_names"]:
            if "sha256" in col.lower() or col.lower().endswith("_hash"):
                hash_cols["%s.%s" % (t, col)] += 1
    out["hash_columns"] = dict(hash_cols)
    # does every text-bearing table carry the section hash?
    out["section_hash_coverage"] = {
        "section.text_hash_sha256": c.execute(
            "SELECT COUNT(*) FROM section WHERE text_hash_sha256 IS NOT NULL"
        ).fetchone()[0],
        "term_mention.section_text_sha256": c.execute(
            "SELECT COUNT(*) FROM term_mention WHERE section_text_sha256 IS NOT NULL"
        ).fetchone()[0],
        "claim_evidence_has_hash": "section_text_sha256" in [
            r[1] for r in c.execute("PRAGMA table_info(claim_evidence)")
        ],
        "relation_evidence_has_hash": "section_text_sha256" in [
            r[1] for r in c.execute("PRAGMA table_info(relation_evidence)")
        ],
        "term_definition_has_hash": "section_text_sha256" in [
            r[1] for r in c.execute("PRAGMA table_info(term_definition)")
        ],
    }

    # ---- data dictionary coverage ----------------------------------------
    dpath = [p for p in (REPO_DICT()) if p.exists()]
    out["dictionary_path"] = str(dpath[0]) if dpath else "ABSENT"
    if dpath:
        import csv
        with open(dpath[0], encoding="utf-8", errors="replace", newline="") as fh:
            drows = list(csv.DictReader(fh))
        out["dictionary_rows"] = len(drows)
        out["dictionary_columns"] = list(drows[0].keys()) if drows else []
        for col in ("definition_status", "table_name", "column_name"):
            if drows and col in drows[0]:
                out["dictionary_%s" % col] = dict(
                    collections.Counter(r.get(col) or "(null)" for r in drows).most_common(12)
                )
        # Real headers are `table` and `column` (verified by reading the CSV);
        # guessing table_name/column_name silently made every column look
        # undocumented. Probe for either spelling.
        tcol = next((x for x in ("table", "table_name") if drows and x in drows[0]), None)
        ccol = next((x for x in ("column", "column_name") if drows and x in drows[0]), None)
        out["dictionary_table_column_header"] = tcol
        out["dictionary_column_column_header"] = ccol
        documented = {(r.get(tcol), r.get(ccol)) for r in drows} if (tcol and ccol) else set()
        missing = []
        for t in tables:
            for col in schema[t]["column_names"]:
                if (t, col) not in documented:
                    missing.append("%s.%s" % (t, col))
        out["dictionary_undocumented_columns"] = missing[:120]
        out["dictionary_undocumented_count"] = len(missing)
        out["dictionary_coverage_pct"] = round(
            100.0 * (total_cols - len(missing)) / max(1, total_cols), 2
        )

    # ---- can the schema express the source distinctions? ------------------
    # probe specific research distinctions the literature makes
    probes = {}
    probes["cohort_has_country"] = "country_or_region" in [
        r[1] for r in c.execute("PRAGMA table_info(cohort)")]
    probes["sample_has_sample_count"] = "sample_count" in [
        r[1] for r in c.execute("PRAGMA table_info(sample)")]
    probes["assay_has_platform"] = "sequencing_platform" in [
        r[1] for r in c.execute("PRAGMA table_info(assay)")]
    probes["has_storage_condition_field"] = any(
        "storage" in col.lower()
        for t in tables for col in schema[t]["column_names"])
    probes["has_preservation_field"] = any(
        "preserv" in col.lower()
        for t in tables for col in schema[t]["column_names"])
    probes["has_dna_extraction_field"] = any(
        "extraction" in col.lower() and "dna" in col.lower()
        for t in tables for col in schema[t]["column_names"])
    probes["has_diet_field"] = any(
        "diet" in col.lower() for t in tables for col in schema[t]["column_names"])
    probes["has_dose_field"] = any(
        "dose" in col.lower() or "dosage" in col.lower()
        for t in tables for col in schema[t]["column_names"])
    probes["has_timepoint_field"] = any(
        "timepoint" in col.lower() or "time_point" in col.lower()
        for t in tables for col in schema[t]["column_names"])
    probes["has_effect_size_field"] = any(
        "effect_size" in col.lower() for t in tables for col in schema[t]["column_names"])
    probes["has_pvalue_field"] = any(
        "p_value" in col.lower() or "pvalue" in col.lower() or "fdr" in col.lower()
        for t in tables for col in schema[t]["column_names"])
    probes["has_confidence_interval"] = any(
        "confidence" in col.lower() or "_ci" in col.lower()
        for t in tables for col in schema[t]["column_names"])
    out["research_distinction_probes"] = probes
    out["missing_distinctions"] = [k for k, v in probes.items() if not v]

    # ---- entity type vocabulary in the DB --------------------------------
    # type_harmonization carries canonical_type, not cdm_type (PRAGMA-guarded).
    for t, candidates in (
        ("canonical_term", ("cdm_type", "entity_type", "type")),
        ("term_mention", ("entity_type", "cdm_type", "type")),
        ("type_harmonization", ("canonical_type", "cdm_type", "entity_type", "type")),
    ):
        cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % t)]
        for cand in candidates:
            if cand in cols:
                out["%s_type_column" % t] = cand
                out["%s_type_values" % t] = dict(
                    c.execute(
                        'SELECT "%s", COUNT(*) FROM "%s" GROUP BY 1 ORDER BY 2 DESC LIMIT 25'
                        % (cand, t)
                    ).fetchall()
                )
                break
        else:
            out["%s_type_column" % t] = "ABSENT"

    # ---- redundant representations ---------------------------------------
    redundant = {}
    # both a term_id and a denormalised term string in the same table
    for t in tables:
        cols = schema[t]["column_names"]
        if any(x.endswith("_id") for x in cols) and "term" in cols and "term_id" in cols:
            redundant["%s.term_denormalised" % t] = {
                "term_id_present": True, "term_string_present": True,
            }
    out["denormalised_term_string_tables"] = redundant
    # claim has both catalogue-v3 and corpus-v2 section columns
    cc = [r[1] for r in c.execute("PRAGMA table_info(claim)")]
    out["claim_section_columns"] = [x for x in cc if "section" in x]
    # evidence duplicated between claim_evidence and claim columns
    out["claim_columns_with_evidence"] = [x for x in cc if "evidence" in x]
    out["claim_evidence_table_rows"] = c.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0]

    # ---- sample-versus-sample-group ambiguity ----------------------------
    sc = [r[1] for r in c.execute("PRAGMA table_info(sample)")]
    out["sample_columns"] = sc
    out["sample_group_table_exists"] = "sample_group" in tables
    out["sample_has_group_column"] = [x for x in sc if "group" in x.lower()]
    out["sample_count_column_meaning"] = "aggregate vs per-row ambiguity" if "sample_count" in sc else "absent"

    # ---- versioning / migration ------------------------------------------
    out["has_change_log"] = "cdm_change_log" in tables
    if "cdm_change_log" in tables:
        out["change_log_rows"] = c.execute("SELECT COUNT(*) FROM cdm_change_log").fetchone()[0]
    out["has_run_metadata"] = "run_metadata" in tables
    out["has_load_audit"] = "load_audit" in tables
    out["has_extraction_run"] = "extraction_run" in tables

    # ---- column naming hygiene -------------------------------------------
    out["columns_named_id_without_id_type"] = [
        "%s.%s" % (t, col) for t in tables for col in schema[t]["column_names"]
        if col == "id"
    ]
    out["columns_with_space_or_caps"] = [
        "%s.%s" % (t, col) for t in tables for col in schema[t]["column_names"]
        if re.search(r"[A-Z ]", col)
    ]

    c.close()
    emit("d19_cdm_schema_quality", out)


def REPO_DICT():
    return [
        REPO / "releases/cdm_v3/3.0.3/remediation/CDM_COLUMN_DICTIONARY.csv",
        REPO / "releases/cdm_v3/3.0.3/CDM_COLUMN_DICTIONARY.csv",
    ]


if __name__ == "__main__":
    main()
