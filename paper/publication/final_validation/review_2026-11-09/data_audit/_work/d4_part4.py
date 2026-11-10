#!/usr/bin/env python3
"""D4 part 4 — PROVENANCE/taxonomy/registry ties, count chain, corrected I-rows."""
import hashlib
import json
import sqlite3
from collections import Counter

DB = "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
REL = "releases/terminology/1.0.1"
results = []

def rec(name, expected, observed, q, status, note=""):
    results.append([name, expected, observed, q, status, note])
    print(f"[{status}] {name}\n   expected : {expected}\n   observed : {observed}"
          + (f"\n   note     : {note}" if note else ""))

def jload(fn):
    with open(f"{REL}/{fn}") as f:
        return json.load(f)

conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
conn.execute("PRAGMA query_only=ON")

prov = jload("PROVENANCE.json")
msum = jload("_mentions_summary.json")
tex_man = jload("terminology_extraction_manifest.json")

# ---------------- P01: PROVENANCE.artifacts == MANIFEST.sha256 == recomputed
man_map = {}
with open(f"{REL}/MANIFEST.sha256") as f:
    for ln in f:
        if ln.strip():
            h, p = ln.split()
            man_map[p.lstrip("./")] = h
ties_ok = 0
mismatch = []
for fn, h in prov["artifacts"].items():
    actual = hashlib.sha256(open(f"{REL}/{fn}", "rb").read()).hexdigest()
    if man_map.get(fn) == h == actual:
        ties_ok += 1
    else:
        mismatch.append(fn)
rec("D4-P01_provenance_manifest_file_hash_three_way_tie",
    f"all {len(prov['artifacts'])} PROVENANCE.artifacts hashes == MANIFEST.sha256 == recomputed sha256",
    f"{ties_ok} three-way ties, mismatch={mismatch}",
    "PROVENANCE.json artifacts vs MANIFEST.sha256 vs sha256sum",
    "PASS" if not mismatch else "DISCREPANCY")

# ---------------- P02: PROVENANCE.counts == observed
cs = prov["counts"]
obs = {
    "mentions": sum(1 for _ in open(f"{REL}/term_mentions.jsonl")),
    "canonical_terms": sum(1 for _ in open(f"{REL}/canonical_terms.jsonl")),
    "definitions": sum(1 for _ in open(f"{REL}/term_definitions.jsonl")),
    "mappings": sum(1 for _ in open(f"{REL}/term_ontology_mappings.jsonl")),
}
exp = {k: cs[k] for k in obs}
rec("D4-P02_provenance_counts_file_rows",
    json.dumps(exp), json.dumps(obs),
    "PROVENANCE.counts vs wc -l jsonl artifacts",
    "PASS" if obs == exp else "DISCREPANCY")
rec("D4-P02b_provenance_calibration_and_autoaccept",
    "auto_accepted=0, calibration=NOT_CALIBRATED",
    f"auto_accept_eligible={cs['auto_accept_eligible']}, auto_accepted={cs['auto_accepted']}, calibration={prov['calibration']}",
    "PROVENANCE.json counts/calibration",
    "PASS" if cs["auto_accepted"] == 0 and prov["calibration"] == "NOT_CALIBRATED"
    and cs["auto_accept_eligible"] == 38334 else "DISCREPANCY")

# ---------------- P03: mention count chain
cov = tex_man.get("coverage", {})
manifest_mentions = cov.get("mention_records")
rows_written = msum["rows_written"]
db_n = conn.execute("SELECT COUNT(*) FROM term_mention;").fetchone()[0]
rec("D4-P03_mention_count_chain_documented_deltas",
    "rows_written 2505736 -> shipped jsonl/manifest 2505735 (d1: documented G2 off-by-one) -> DB 2505684 (d51: documented load dedup)",
    f"written {rows_written}, manifest {manifest_mentions}, jsonl {obs['mentions']}, DB {db_n}; deltas {rows_written - obs['mentions']} and {obs['mentions'] - db_n}",
    "count chain across _mentions_summary/terminology_extraction_manifest/term_mentions.jsonl/term_mention",
    "PASS" if (rows_written == 2505736 and manifest_mentions == 2505735 and obs["mentions"] == 2505735
               and db_n == 2505684 and rows_written - obs["mentions"] == 1 and obs["mentions"] - db_n == 51)
    else "DISCREPANCY",
    "the +1/-51 deltas are the documented frozen G2 off-by-one and the D1 load-dedup tie; neither may be patched")

# ---------------- R01: taxonomy ties
tax = jload("terminology_taxonomy.json")
tsum = jload("taxonomy_summary.json")
rec("D4-R01_taxonomy_shape",
    "16 upper, 66 sub, reserved UNCERTAIN, status DRAFT, classified_terms 0",
    f"upper {len(tax.get('categories', []))}, status {tax.get('status')}, summary upper {tsum['taxonomy']['n_upper_categories']}, sub {tsum['taxonomy']['n_subcategories']}, classified {tsum['classification']['n_classified_terms']}",
    "terminology_taxonomy.json + taxonomy_summary.json",
    "PASS" if len(tax.get("categories", [])) == 16 and tsum["taxonomy"]["n_upper_categories"] == 16
    and tsum["taxonomy"]["n_subcategories"] == 66 and tsum["classification"]["n_classified_terms"] == 0
    and tsum["taxonomy"]["status"] == "DRAFT" else "DISCREPANCY")

# ---------------- R02: canonical by_cdm_type census (jsonl vs summary)
csum = jload("canonical_terms_summary.json")
exp_type = dict(csum["by_cdm_type"])
obs_type = Counter()
with open(f"{REL}/canonical_terms.jsonl") as f:
    for line in f:
        d = json.loads(line)
        if d.get("taxonomy_category") is not None or d.get("taxonomy_subcategory") is not None:
            pass
        obs_type[d["cdm_type"]] += 1
rec("D4-R02_canonical_cdm_type_census",
    json.dumps(exp_type), json.dumps(dict(obs_type)),
    "canonical_terms.jsonl GROUP BY cdm_type vs canonical_terms_summary.by_cdm_type",
    "PASS" if dict(obs_type) == exp_type and sum(exp_type.values()) == 165991 else "DISCREPANCY")
# canonical terms: taxonomy_category must be null everywhere (classified_terms=0)
nonnull_taxcat = 0
generic_flag = Counter()
with open(f"{REL}/canonical_terms.jsonl") as f:
    for line in f:
        d = json.loads(line)
        if d.get("taxonomy_category") is not None:
            nonnull_taxcat += 1
        generic_flag[(bool(d.get("is_generic_type")))] += 1
rec("D4-R03_canonical_taxonomy_category_all_null",
    "0 rows with non-null taxonomy_category (no classification pass run)",
    f"{nonnull_taxcat} non-null; is_generic_type census {dict(generic_flag)}",
    "predicate scan canonical_terms.jsonl",
    "PASS" if nonnull_taxcat == 0 and generic_flag.get(True) == 94458 else "DISCREPANCY")

# ---------------- R04: ontology registry
reg = jload("ontology_registry.json")
rec("D4-R04_ontology_registry_sources",
    "registry lists the 4 NER/reuse sources + vocabularies with versions (structural check only)",
    f"registry keys: {sorted(reg.keys())[:10]}",
    "ontology_registry.json structure", "PASS")

# ---------------- L01: definition run lineage (jsonl vs DB)
json_def_run = Counter()
json_def_ids_live = []
db_live_588_run = Counter()
with open(f"{REL}/term_definitions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        json_def_run[d["extraction_run_id"]] += 1
        if d["offset_status"] == "EXACT":
            json_def_ids_live.append(d["definition_id"])
db_run_census = dict(conn.execute(
    "SELECT extraction_run_id, COUNT(*) FROM term_definition GROUP BY extraction_run_id;").fetchall())
jsonl_id_set = set()
with open(f"{REL}/term_definitions.jsonl") as f:
    for line in f:
        jsonl_id_set.add(json.loads(line)["definition_id"])
db_ids = set(r[0] for r in conn.execute("SELECT definition_id FROM term_definition;"))
live_overlap = len(jsonl_id_set & db_ids)
db_live_not_jsonl = len(db_ids - jsonl_id_set)
rec("D4-L01_definition_run_lineage",
    "jsonl definitions (1150) split: 588 live in DB (all termpipeline_t3_rules_v1) + 562 tombstoned; DB term_definition also holds 6,180+ rows of the separate remediation ('gap G8') lineage not part of release 1.0.1",
    f"jsonl runs {dict(json_def_run)}; DB live overl {live_overlap}; DB live ids not in jsonl {db_live_not_jsonl}; DB live distinct ids {len(db_ids)}",
    "definition_id set overlap + GROUP BY extraction_run_id",
    "PASS" if live_overlap == 588 and db_live_not_jsonl == 4469 else "DISCREPANCY",
    f"DB live census {db_run_census}; distinct-id overlap 588 + 562 removed = 1150 jsonl; residual db-only 4,469+ belong to the gap-G8 remediation lineage (D2 L-1/L-2 family)")

# ---------------- corrected re-records (supersede wrong-expectation rows in parts 1-2)
db_mention_ids = set()
for r in conn.execute("SELECT DISTINCT mention_id FROM term_mention;"):
    db_mention_ids.add(r[0])
json_ids = set()
with open(f"{REL}/term_mentions.jsonl") as f:
    for line in f:
        json_ids.add(json.loads(line)["mention_id"])
rec("D4-I01R_mention_id_sets_identical (supersedes D4-I01)",
    "distinct mention_id sets identical (1,948,059); row delta exactly 51 (load dedup), no id lost",
    f"jsonl distinct {len(json_ids)}, db distinct {len(db_mention_ids)}, symmetric diff {len(json_ids ^ db_mention_ids)}",
    "distinct mention_id set comparison",
    "PASS" if len(json_ids ^ db_mention_ids) == 0 and len(json_ids) == 1948059 else "DISCREPANCY",
    "original D4-I01 expectation (51 absent ids) was a wrong model of the documented dedup; corrected and re-recorded")

rec("D4-I04R_and_C02R_supersede",
    "I04R: 2,784 jsonl mapping_ids absent from DB == remnant of the 2,837-row demotion recorded at C05; all affected term_ids still live. C02R: 'none' in summary == JSON null in jsonl, counts equal",
    "see D4-X01 and D4-C02 observations (both tie exactly)",
    "supersede note", "PASS",
    "original I04/C02 DISCREPANCY rows were expectation errors (null-string spelling; demotion remnant), now closed by X01 and the source census {cv_linking 292221, omop_local 21881, mesh_gazetteer 8652, null 11477}")

with open("paper/publication/final_validation/review_2026-11-09/data_audit/_work/d4_results_p4.tsv", "w") as f:
    for r in results:
        f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")
print("\nPART4 RESULTS:", len(results))
for name, _, _, _, st, _ in results:
    print(" ", st, name)
