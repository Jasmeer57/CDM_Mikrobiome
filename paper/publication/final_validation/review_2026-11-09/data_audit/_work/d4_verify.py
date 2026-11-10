#!/usr/bin/env python3
"""D4 — terminology chain cross-checks (read-only).

Cross-checks releases/terminology/1.0.1/ artifacts against the frozen CDM 3.0.3 DB.
No paper text is read; offsets validated against stored section lengths only.
All DB access strictly read-only (mode=ro, immutable, query_only).
"""
import json
import sqlite3
from collections import Counter

DB = "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
REL = "releases/terminology/1.0.1"

results = []

def rec(name, expected, observed, q, status, note=""):
    results.append((name, expected, observed, q, status, note))
    print(f"  [{status}] {name}\n      expected: {expected}\n      observed: {observed}" + (f"\n      note: {note}" if note else ""))

def jload(fn):
    with open(f"{REL}/{fn}") as f:
        return json.load(f)

def isummary(fn, key_count):
    d = jload(fn)
    v = d
    for k in key_count.split("."):
        v = v[k]
    return v

# ---------------------------------------------------------------- DB ground truth
conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
conn.execute("PRAGMA query_only=ON")

print("== DB ground counts ==")
db_counts = {}
for t in ["term_mention", "term_occurrence", "canonical_term", "term_concept_map", "term_definition"]:
    db_counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
    print(f"  {t}: {db_counts[t]}")

db_sum_mentions = conn.execute("SELECT SUM(n_mentions) FROM term_occurrence;").fetchone()[0]
print(f"  SUM(n_mentions) over occurrences: {db_sum_mentions}")

# ---------------------------------------------------------------- M checks: MANIFEST
print("== M: MANIFEST ==")
msum = jload("_mentions_summary.json")
csum = jload("canonical_terms_summary.json")
dsum = jload("_definitions_summary.json")
mpsum = jload("mapping_projection_summary.json")
vsum = jload("validation_summary.json")
fixrep = jload("OFFSET_FIX_REPORT.json")

import hashlib
man_ok = man_bad = 0
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
rec("D4-M01 manifest_sha256_22_files", "22 verified, 0 failed", f"{man_ok} verified, {man_bad} failed",
    "sha256sum -c MANIFEST.sha256", "PASS" if man_bad == 0 else "DISCREPANCY")

# ---------------------------------------------------------------- T: row ties
print("== T: row-count ties ==")
def wc(fn):
    n = 0
    with open(f"{REL}/{fn}") as f:
        for line in f:
            if line.strip():
                n += 1
    return n

n_mentions = wc("term_mentions.jsonl")
n_canon = wc("canonical_terms.jsonl")
n_map = wc("term_ontology_mappings.jsonl")
n_def = wc("term_definitions.jsonl")
print(f"  jsonl lines: mentions={n_mentions} canon={n_canon} map={n_map} def={n_def}")

rec("D4-T01 mentions_jsonl_rows", f"{db_counts['term_mention']} (DB term_mention) + 51 load-dedup",
    f"{n_mentions} (DB={db_counts['term_mention']})",
    "wc -l term_mentions.jsonl vs SELECT COUNT(*) FROM term_mention",
    "PASS" if n_mentions == db_counts["term_mention"] + 51 else "DISCREPANCY",
    "51-row load dedup is a documented D1 tie")
rec("D4-T02 canonical_jsonl_rows", str(db_counts["canonical_term"]), str(n_canon),
    "wc -l canonical_terms.jsonl vs SELECT COUNT(*) FROM canonical_term",
    "PASS" if n_canon == db_counts["canonical_term"] else "DISCREPANCY")
rec("D4-T03 mappings_jsonl_rows", str(db_counts["term_concept_map"]), str(n_map),
    "wc -l term_ontology_mappings.jsonl vs SELECT COUNT(*) FROM term_concept_map",
    "PASS" if n_map == db_counts["term_concept_map"] else "DISCREPANCY")
rec("D4-T04 definitions_jsonl_rows", str(db_counts["term_definition"]), str(n_def),
    "wc -l term_definitions.jsonl vs SELECT COUNT(*) FROM term_definition",
    "PASS" if n_def == db_counts["term_definition"] else "DISCREPANCY")
rec("D4-T05 occurrences_sum_n_mentions", str(db_counts["term_mention"]),
    str(db_sum_mentions), "SELECT SUM(n_mentions) FROM term_occurrence",
    "PASS" if db_sum_mentions == db_counts["term_mention"] else "DISCREPANCY")

# mentions summary sources tie to cat/frozen bundle counts
srcs = msum["sources"]
src_ok = (srcs["cpu_ensemble"]["rows"] == 1705501 and srcs["qwen_ollama"]["rows"] == 186024
          and srcs["qwen_vllm_body"]["rows"] == 366123 and srcs["qwen_vllm_body"]["rows"] == 366123
          and srcs["mesh_gazetteer"]["rows"] == 248088)
rec("D4-T06 mentions_source_rows", "cpu_ensemble 1,705,501 / qwen_ollama 186,024 / qwen_vllm_body 366,123 / mesh_gazetteer 248,088",
    f"cpu {srcs['cpu_ensemble']['rows']} / ollama {srcs['qwen_ollama']['rows']} / vllm {srcs['qwen_vllm_body']['rows']} / mesh {srcs['mesh_gazetteer']['rows']}",
    "_mentions_summary.json sources", "PASS" if src_ok else "DISCREPANCY")
rec("D4-T07 mentions_rows_written_tie", "2505736 (= 2,505,735 jsonl + 1 header?)",
    str(msum["rows_written"]), "_mentions_summary.json rows_written",
    "PASS" if msum["rows_written"] == 2505736 else "DISCREPANCY")
rec("D4-T08 mentions_offsets_verified", "2505616 (= rows_written - 85 UNANCHORED - 34 recovered? per summary)",
    f"verified={msum['offsets_verified']} recovered={msum['offsets_recovered']} unverified={msum['offsets_unverified']}",
    "_mentions_summary.json", "PASS" if msum["offsets_verified"] == 2505616 else "DISCREPANCY")

# ---------------------------------------------------------------- I: id-space containment
print("== I: ID-space containment (JSONL -> DB) ==")
db_mention_ids = set(r[0] for r in conn.execute("SELECT mention_id FROM term_mention;"))
db_canon_ids = set(r[0] for r in conn.execute("SELECT term_id FROM canonical_term;"))
db_def_ids = set(r[0] for r in conn.execute("SELECT definition_id FROM term_definition;"))
db_mapping_ids = set(r[0] for r in conn.execute("SELECT mapping_id FROM term_concept_map;"))

# mentions: expect 50 absent (2,505,735 - 2,505,684 = 51 in D1; but dedupe result exact)
absent_m = 0
total_m = 0
abs_samples = []
with open(f"{REL}/term_mentions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        total_m += 1
        if d["mention_id"] absent := False:
            pass
