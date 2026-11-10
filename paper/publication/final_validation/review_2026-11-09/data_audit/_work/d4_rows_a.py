#!/usr/bin/env python3
"""D4 deliverable consolidation — fragment A part 2 (rows M01..I04R).

Emits _work/d4_rows_a.json containing 15 DATA_AUDIT.csv row dicts:
M01, M02, T01, T02R, T03R, T04R, T05, T06, T07, T08R, I01R, I02, I02b, I03, I04R
Run from repo root:  python3 .../d4_rows_a.py
No DB access, no paper text; figures verbatim from raw D4 result runs.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DBART = "microbiome_cdm_v3.db"
REL = "releases/terminology/1.0.1"
TJ = f"{REL}/term_mentions.jsonl"

def R(check_name, artifact, expected, observed, query_or_file, status, note=""):
    return {
        "pass": "D4", "artifact": artifact, "check_name": check_name,
        "expected": expected, "observed": observed, "query_or_file": query_or_file,
        "status": status, "note": note,
    }
