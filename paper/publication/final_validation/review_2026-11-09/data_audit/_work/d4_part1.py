#!/usr/bin/env python3
"""D4 part 1 — MANIFEST, row-count ties, summary ties. Read-only."""
import hashlib
import json
import sqlite3
from collections import Counter

DB = "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
REL = "releases/terminology/1.0.1"
results = []

def rec(name, expected, observed, q, status, note=""):
    results.append((name, expected, observed, q, status, note))
    print(f"[{status}] {name}\n   expected : {expected}\n   observed : {observed}"
          + (f"\n   note     : {note}" if note else ""))

def jload(fn):
    with open(f"{REL}/{fn}") as f:
        return json.load(f)

def wc(fn):
    n = 0
    with open(f"{REL}/{fn}") as f:
        for line in f:
            if line.strip():
                n += 1
    return n

conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
conn.execute("PRAGMA query_only=ON")

db_counts = {}
for t in ["term_mention", "term_occurrence", "canonical_term", "term_concept_map", "term_definition"]:
    db_counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
db_sum_mentions = conn.execute("SELECT SUM(n_mentions) FROM term_occurrence;").fetchone()[0]
print("DB ground counts:", db_counts, "sum(n_mentions) =", db_sum_mentions)

# -- M01/M02 manifest
man_ok = man_bad = 0
bad_files = []
with open(f"{REL}/MANIFEST.sha256") as f:
    for ln in f:
        if not ln.strip():
            continue
        h, p = ln.split()
        digest = hashlib.sha256(open(f"{REL}/{p.lstrip('./')}", "rb").read()).hexdigest()
        if digest == h:
            man_ok += 1
        else:
            man_bad += 1
            bad_files.append(p)
n_manifest = man_ok + man_bad
rec("D4-M01_manifest_files_listed", "22", str(n_manifest), "MANIFEST.sha256 line count",
    "PASS" if n_manifest == 22 else "DISCREPANCY")
rec("D4-M02_manifest_sha256_verified", "22 verified, 0 failed",
    f"{man_ok} verified, {man_bad} failed; bad={bad_files}",
    "sha256sum -c MANIFEST.sha256", "PASS" if man_bad == 0 else "DISCREPANCY")

# -- T01..T05 row ties
n_mentions = wc("term_mentions.jsonl")
n_canon = wc("canonical_terms.jsonl")
n_map = wc("term_ontology_mappings.jsonl")
n_def = wc("term_definitions.jsonl")
print("jsonl rows:", n_mentions, n_canon, n_map, n_def)

rec("D4-T01_mentions_jsonl_rows_vs_db",
    f"{db_counts['term_mention'] + 51} (DB term_mention {db_counts['term_mention']} + 51 load dedup)",
    f"{n_mentions}", "wc -l term_mentions.jsonl vs COUNT(term_mention)",
    "PASS" if n_mentions == db_counts["term_mention"] + 51 else "DISCREPANCY",
    "51-row load-dedup is the documented D1 tie")
rec("D4-T02_canonical_jsonl_rows_vs_db", str(db_counts["canonical_term"]), str(n_canon),
    "wc -l canonical_terms.jsonl vs COUNT(canonical_term)",
    "PASS" if n_canon == db_counts["canonical_term"] else "DISCREPANCY")
rec("D4-T03_mappings_jsonl_rows_vs_db", str(db_counts["term_concept_map"]), str(n_map),
    "wc -l term_ontology_mappings.jsonl vs COUNT(term_concept_map)",
    "PASS" if n_map == db_counts["term_concept_map"] else "DISCREPANCY")
rec("D4-T04_definitions_jsonl_rows_vs_db", str(db_counts["term_definition"]), str(n_def),
    "wc -l term_definitions.jsonl vs COUNT(term_definition)",
    "PASS" if n_def == db_counts["term_definition"] else "DISCREPANCY")
rec("D4-T05_occurrence_sum_n_mentions", str(db_counts["term_mention"]), str(db_sum_mentions),
    "SELECT SUM(n_mentions) FROM term_occurrence",
    "PASS" if db_sum_mentions == db_counts["term_mention"] else "DISCREPANCY")

# -- T06..T08 summary ties
msum = jload("_mentions_summary.json")
s = msum["sources"]
expect_src = {"cpu_ensemble": 1705501, "qwen_ollama": 186024, "qwen_vllm_body": 366123, "mesh_gazetteer": 248088}
obs_src = {k: s[k]["rows"] for k in expect_src}
rec("D4-T06_mentions_source_rows", json.dumps(expect_src), json.dumps(obs_src),
    "_mentions_summary.json sources[].rows",
    "PASS" if obs_src == expect_src else "DISCREPANCY")
rec("D4-T07_mentions_rows_written", "2505736", str(msum["rows_written"]),
    "_mentions_summary.json rows_written",
    "PASS" if msum["rows_written"] == 2505736 else "DISCREPANCY",
    "manifest coverage.mention_records = 2505735 vs real 2505736 is the known G2 off-by-one")
rec("D4-T08_mentions_offset_verification", "verified 2505616 / recovered 34 / unverified 85; sum == rows_written",
    f"verified {msum['offsets_verified']} / recovered {msum['offsets_recovered']} / unverified {msum['offsets_unverified']}",
    "_mentions_summary.json",
    "PASS" if (msum["offsets_verified"] + msum["offsets_recovered"] + msum["offsets_unverified"]
               == msum["rows_written"]) else "DISCREPANCY")

# save results for the CSV append step
with open("paper/publication/final_validation/review_2026-11-09/data_audit/_work/d4_results_p1.tsv", "w") as f:
    for r in results:
        f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")
print("\nPART1 RESULTS:", len(results))
for name, _, _, _, st, _ in results:
    print(" ", st, name)
