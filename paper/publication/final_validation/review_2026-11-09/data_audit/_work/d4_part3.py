#!/usr/bin/env python3
"""D4 part 3 — offset-fix ties, validation ties, missing-mapping-id investigation."""
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

conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
conn.execute("PRAGMA query_only=ON")

fix = json.load(open(f"{REL}/OFFSET_FIX_REPORT.json"))
vsum = json.load(open(f"{REL}/validation_summary.json"))
dsum = json.load(open(f"{REL}/_definitions_summary.json"))

# ---------------- f: OFFSET_FIX_REPORT vs jsonl censuses
fx = fix["files"]["term_mentions.jsonl"]
exp_link = {k.split(":")[1]: v for k, v in fx.items() if k.startswith("link:")}
json_link = Counter()
json_offstat = Counter()
json_corr = Counter()
jsonl_def_offstat = Counter()
with open(f"{REL}/term_mentions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        json_link[d["term_link_status"]] += 1
        json_offstat[d["offset_status"]] += 1
        json_corr[d["offset_correction"]] += 1
with open(f"{REL}/term_definitions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        jsonl_def_offstat[d["offset_status"]] += 1

rec("D4-F01_term_link_status_jsonl_eq_fixreport", json.dumps(exp_link), json.dumps(dict(json_link)),
    "jsonl census vs OFFSET_FIX_REPORT link:*",
    "PASS" if dict(json_link) == exp_link else "DISCREPANCY")
exp_offstat = {"EXACT": fx["EXACT"], "CORRECTED": fx["CORRECTED"], "UNANCHORED": fx["UNANCHORED"]}
rec("D4-F02_offset_status_jsonl_eq_fixreport", json.dumps(exp_offstat), json.dumps(dict(json_offstat)),
    "jsonl census vs OFFSET_FIX_REPORT",
    "PASS" if dict(json_offstat) == exp_offstat else "DISCREPANCY")
exp_def_offstat = {"EXACT": fix["files"]["term_definitions.jsonl"]["EXACT"],
                   "CORRECTED": fix["files"]["term_definitions.jsonl"]["CORRECTED"]}
rec("D4-F03_definitions_offset_status_jsonl_eq_fixreport", json.dumps(exp_def_offstat),
    json.dumps(dict(jsonl_def_offstat)), "jsonl census vs OFFSET_FIX_REPORT",
    "PASS" if dict(jsonl_def_offstat) == exp_def_offstat else "DISCREPANCY")
rec("D4-F04_sections_shifted", "75 (67 shift-1 + 8 shift-2)",
    f"{fix['sections_shifted']} ({fix['shift_histogram']})",
    "OFFSET_FIX_REPORT sections_shifted", "PASS" if fix["sections_shifted"] == 75
    and fix["shift_histogram"] == {"1": 67, "2": 8} else "DISCREPANCY")

# DB side censuses for the same fields
db_link = dict(conn.execute("SELECT term_link_status, COUNT(*) FROM term_mention GROUP BY term_link_status;").fetchall())
db_offstat = dict(conn.execute("SELECT offset_status, COUNT(*) FROM term_mention GROUP BY offset_status;").fetchall())
db_corr = dict(conn.execute("SELECT offset_correction, COUNT(*) FROM term_mention GROUP BY offset_correction;").fetchall())
print("DB term_link_status:", db_link)
print("DB offset_status   :", db_offstat)
print("DB offset_corr     :", db_corr)
json_rows = sum(json_link.values())
# expected DB = jsonl census minus the 51 deduped rows; record delta explicitly
delta_link = {k: json_link[k] - db_link.get(k, 0) for k in json_link}
delta_offstat = {k: json_offstat[k] - db_offstat.get(k, 0) for k in json_offstat}
delta_corr = {k: json_corr[k] - db_corr.get(k, 0) for k in json_corr}
print("deltas link:", delta_link, "offstat:", delta_offstat, "corr:", delta_corr)
delta_total = sum(delta_link.values())
rec("D4-F05_jsonl_vs_db_census_delta_51",
    "jsonl - DB per-status deltas sum to exactly 51 (load dedup), non-negative, spread over statuses of duplicated mentions",
    f"delta sums: link {delta_total}, offstat {sum(delta_offstat.values())}, corr {sum(delta_corr.values())}",
    "census diff (jsonl - DB) over term_mention",
    "PASS" if delta_total == 51 and sum(delta_offstat.values()) == 51 and sum(delta_corr.values()) == 51
    and all(v >= 0 for v in list(delta_link.values()) + list(delta_offstat.values()) + list(delta_corr.values()))
    else "DISCREPANCY",
    f"deltas: {delta_link} / {delta_offstat} / {delta_corr}")

# corrected rows must have nonzero offset_correction (jsonl)
json_corr_of_corrected = Counter()
with open(f"{REL}/term_mentions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        if d["offset_status"] == "CORRECTED":
            json_corr_of_corrected[d["offset_correction"] > 0] += 1
        elif d["offset_status"] == "EXACT":
            pass
rec("D4-F06_corrected_rows_have_nonzero_correction",
    "all CORRECTED rows offset_correction>0; all EXACT rows 0",
    f"corrected: >0 {json_corr_of_corrected.get(True, 0)}, ==0 {json_corr_of_corrected.get(False, 0)}",
    "jsonl predicate scan", "PASS" if json_corr_of_corrected.get(False, 0) == 0 else "DISCREPANCY")
# EXACT rows with nonzero correction (definitions of semantics: correction applies to CORRECTED only)
json_exact_nonzero = 0
with open(f"{REL}/term_mentions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        if d["offset_status"] == "EXACT" and d["offset_correction"] > 0:
            json_exact_nonzero += 1
rec("D4-F07_exact_rows_zero_correction",
    "0 EXACT rows with nonzero offset_correction",
    str(json_exact_nonzero), "jsonl predicate scan",
    "PASS" if json_exact_nonzero == 0 else "DISCREPANCY")

# ---------------- V: validation_summary ties
cov = vsum["coverage"]
rec("D4-V01_validation_papers", "453 processed / 0 not processed / 0 flagged",
    f"{cov['papers_processed']} / {cov['papers_not_processed']} / {cov['papers_flagged']}",
    "validation_summary.json coverage", "PASS" if cov["papers_processed"] == 453
    and cov["papers_not_processed"] == 0 and cov["papers_flagged"] == 0 else "DISCREPANCY")
rec("D4-V02_validation_sections", "3,553 validated + 453 not_applicable = 4,006 total",
    f"{cov['sections_validated']} + {cov['sections_not_applicable']} = {cov['sections_total']}",
    "validation_summary.json coverage", "PASS" if cov["sections_validated"] == 3553
    and cov["sections_not_applicable"] == 453 and cov["sections_total"] == 4006 else "DISCREPANCY")
mov = vsum["mention_offset_verification"]
rec("D4-V03_validation_mentions_resolved", "2,505,650 checked, 100.0% resolved, 0 unresolved",
    f"{mov['mentions_checked']} checked, {mov['pct_resolved']}% resolved, {mov['mentions_unresolved']} unresolved",
    "validation_summary.json mention_offset_verification",
    "PASS" if mov["mentions_checked"] == 2505650 and mov["pct_resolved"] == 100.0
    and mov["mentions_unresolved"] == 0 else "DISCREPANCY")
rec("D4-V04_validation_status", "COMPLETE", vsum["overall_status"], "validation_summary.json",
    "PASS" if vsum["overall_status"] == "COMPLETE" else "DISCREPANCY")
# jsonl validation file: distinct validated sections & statuses
val_status = Counter()
val_papers = set()
with open(f"{REL}/terminology_validation.jsonl") as f:
    for line in f:
        d = json.loads(line)
        val_status[d["validation_status"]] += 1
        val_papers.add(d["paper_id"])
rec("D4-V05_validation_jsonl_status_census",
    "VALIDATED 3553 (summary sections_validated), NOT_APPLICABLE 453, over 453 papers",
    f"{dict(val_status)} over {len(val_papers)} papers",
    "terminology_validation.jsonl census",
    "PASS" if val_status.get("VALIDATED") == 3553 and val_status.get("NOT_APPLICABLE") == 453
    and len(val_papers) == 453 else "DISCREPANCY",
    f"statuses={dict(val_status)}")
jmov = sum(d["mentions_checked"] for d in map(json.loads, open(f"{REL}/terminology_validation.jsonl"))) if False else None

# ---------------- D: definitions summary ties
rec("D4-D01_definitions_rows", "1150 (= 1087 EXACT + 63 CORRECTED)",
    f"{dsum['definition_rows']}", "_definitions_summary.json",
    "PASS" if dsum["definition_rows"] == 1150 and exp_def_offstat["EXACT"] + exp_def_offstat["CORRECTED"] == 1150
    else "DISCREPANCY")
rec("D4-D02_definitions_sources", "CONTEXTUAL_DESCRIPTION 1003 / ABBREVIATION_EXPANSION 126 / EXPLICIT_AUTHOR_DEFINITION 21",
    json.dumps(dsum["by_definition_source"]), "_definitions_summary.json by_definition_source",
    "PASS" if dsum["by_definition_source"] == {"CONTEXTUAL_DESCRIPTION": 1003,
    "ABBREVIATION_EXPANSION": 126, "EXPLICIT_AUTHOR_DEFINITION": 21} else "DISCREPANCY")
rec("D4-D03_definitions_review_status_all_REVIEW_REQUIRED",
    "every jsonl definition row review_status == REVIEW_REQUIRED",
    "", "jsonl predicate scan",
    "PASS")  # filled in below

# actual scan for D4-D03 + provenance_class census
def_revstat = Counter()
def_provclass = Counter()
with open(f"{REL}/term_definitions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        def_revstat[d["review_status"]] += 1
        def_provclass[d["provenance_class"]] += 1
res_d03 = next(r for r in results if r[0] == "D4-D03_definitions_review_status_all_REVIEW_REQUIRED")
res_d03[2] = f"{dict(def_revstat)}; provenance_class={dict(def_provclass)}"
res_d03[4] = "PASS" if set(def_revstat) == {"REVIEW_REQUIRED"} else "DISCREPANCY"

# ---------------- X: missing mapping_ids investigation
db_mapping_ids = set(r[0] for r in conn.execute("SELECT mapping_id FROM term_concept_map;"))
missing_ids = set()
miss_rows = []
with open(f"{REL}/term_ontology_mappings.jsonl") as f:
    for line in f:
        d = json.loads(line)
        if d["mapping_id"] not in db_mapping_ids:
            missing_ids.add(d["mapping_id"])
            miss_rows.append(d)
print(f"missing mapping_ids: {len(missing_ids)}, rows involved: {len(miss_rows)}")
miss_rel = Counter(r["mapping_relation"] for r in miss_rows)
miss_disp = Counter(r["mapping_disposition"] for r in miss_rows)
miss_src = Counter(str(r["ontology_source"]) for r in miss_rows)
miss_terms = set(r["term_id"] for r in miss_rows)
live_canon = set(r[0] for r in conn.execute("SELECT term_id FROM canonical_term;"))
removed_canon = set(r[0] for r in conn.execute("SELECT term_id FROM removed_canonical_term;"))
t_live = len([t for t in miss_terms if t in live_canon])
t_removed = len([t for t in miss_terms if t in removed_canon])
t_absent = len([t for t in miss_terms if t not in live_canon and t not in removed_canon])
print("missing-id rows: rel", dict(miss_rel), "disp", dict(miss_disp), "src", dict(miss_src))
print("missing-id terms: live", t_live, "removed", t_removed, "absent", t_absent)
rec("D4-X01_missing_mapping_ids_characterized",
    "2,784 jsonl mapping_ids absent from DB; involvement = the 2,837 demoted mapping rows' remnant groups; their terms all still resolvable in canonical_term/removed_canonical_term",
    f"{len(missing_ids)} ids / {len(miss_rows)} rows; terms live {t_live}, removed {t_removed}, absent {t_absent}",
    "set diff + join census", "PASS" if t_absent == 0 else "DISCREPANCY",
    f"missing rows by relation {dict(miss_rel)}, disposition {dict(miss_disp)}")

# DB-side demotion status for the missing rows' mapping_ids' term_ids
# (informational for D6: term_status census on tcm)
db_termstat = dict(conn.execute("SELECT term_status, COUNT(*) FROM term_concept_map GROUP BY term_status;").fetchall())
print("DB tcm term_status census:", db_termstat)

with open("paper/publication/final_validation/review_2026-11-09/data_audit/_work/d4_results_p3.tsv", "w") as f:
    for r in results:
        f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")
print("\nPART3 RESULTS:", len(results))
for name, _, _, _, st, _ in results:
    print(" ", st, name)
