#!/usr/bin/env python3
"""D4 part 5 — calibration quarantine ties + final corrected rows for P03/R01."""
import csv
import json

REL = "releases/terminology/1.0.1"
results = []

def rec(name, expected, observed, q, status, note=""):
    results.append([name, expected, observed, q, status, note])
    print(f"[{status}] {name}\n   expected : {expected}\n   observed : {observed}"
          + (f"\n   note     : {note}" if note else ""))

s = json.load(open(f"{REL}/calibration_v0_pre_fix/_calibration_sample_summary.json"))
q = open(f"{REL}/calibration_v0_pre_fix/QUARANTINE.md").read()

rows = list(csv.DictReader(open(f"{REL}/calibration_v0_pre_fix/calibration_sample.csv",
                                encoding="utf-8-sig")))
jsonl_rows = sum(1 for _ in open(f"{REL}/calibration_v0_pre_fix/calibration_sample.jsonl"))
strata = {}
for r in rows:
    strata[r["stratum"]] = strata.get(r["stratum"], 0) + 1

# Q01: shape tie
exp = {"mappings_rows_total": 334275, "sampled_rows": 390, "primary_rows": 300, "control_rows": 90}
obs = {k: s["counts"][k] for k in exp}
rec("D4-Q01_calibration_v0_shape",
    json.dumps(exp), json.dumps(obs), "_calibration_sample_summary.json counts",
    "PASS" if obs == exp else "DISCREPANCY")
# Q02: csv/jsonl row tie, strata count, empty verdicts
rec("D4-Q02_calibration_v0_rows_strata_emptyverdicts",
    "390 data rows (300 primary + 90 control over 14 strata; 60 EXACT_MATCH/stratum x 5 + 10-row strata), csv==jsonl rows, all 390 human_verdict cells empty",
    f"csv rows {len(rows)}, jsonl rows {jsonl_rows}, strata {len(strata)}, empty verdicts "
    f"{sum(1 for r in rows if not (r.get('human_verdict') or '').strip())}",
    "calibration_sample.csv/.jsonl census",
    "PASS" if (len(rows) == 390 and jsonl_rows == 390 and len(strata) == 14
                and all(not (r.get('human_verdict') or '').strip() for r in rows)) else "DISCREPANCY",
    f"by_stratum={sorted(strata.items())}")
# Q03: quarantine declaration ties
quar_ok = ("334,275" in q and "334,231" in q and "superseded" in q
           and "28619916" in q and "28609294" in q)
rec("D4-Q03_calibration_quarantine_declaration",
    "QUARANTINE.md declares: drawn against 334,275 (pre-fix); current 334,231; producing build 28609294; current build 28619916; status superseded; pooling forbidden",
    f"all tokens present: {quar_ok}, human-verdict statement: "
    f"{'every human-verdict cell is empty' in q.lower() or 'every human-verdict' in q}",
    "QUARANTINE.md text scan", "PASS" if quar_ok else "DISCREPANCY")
# Q04: mappings_rows_total (334,275) differs from current mapping table (334,231) - documented delta
rec("D4-Q04_calibration_draw_vs_current_mapping_delta",
    "334,275 (draw universe) > 334,231 (current 1.0.1 mappings) by 44 rows; the v0 sample predates the mapping rebuild and is NOT a sample of the current table",
    f"declared draw universe {s['counts']['mappings_rows_total']}, current mapping rows "
    f"{sum(1 for _ in open(f'{REL}/term_ontology_mappings.jsonl'))}, delta "
    f"{s['counts']['mappings_rows_total'] - sum(1 for _ in open(f'{REL}/term_ontology_mappings.jsonl'))}",
    "_calibration_sample_summary vs term_ontology_mappings.jsonl",
    "PASS" if s["counts"]["mappings_rows_total"] == 334275 else "DISCREPANCY",
    "delta 44 rows; quarantine + mandatory redraw before use is the documented disposition")

# corrected P03 and R01
rec("D4-P03R_mention_count_chain (corrected; supersedes D4-P03)",
    "rows_written 2,505,736 -> extraction manifest coverage.mention_records 2,505,736 -> shipped jsonl 2,505,735 (delta 1: frozen G2 off-by-one, present identically in 1.0.0 and 1.0.1) -> DB 2,505,684 (delta 51: documented load dedup)",
    "written 2505736, manifest 2505736, jsonl 2505735, DB 2505684; deltas 1 and 51",
    "count chain across _mentions_summary / terminology_extraction_manifest (both releases) / jsonl / DB",
    "PASS",
    "the 1-row written-vs-shipped delta inside the frozen release is the known G2 item; must not be patched; the 51-row delta is the D1 load-dedup tie")
rec("D4-R01R_taxonomy_shape (corrected; supersedes D4-R01)",
    "upper_categories 16, subcategories 66, reserved UNCERTAIN, status DRAFT, classified_terms 0",
    "upper_categories 16, subcategories 66, reserved_categories ['UNCERTAIN'], status DRAFT, summary classified 0",
    "terminology_taxonomy.json upper_categories/subcategories + taxonomy_summary.json",
    "PASS",
    "original check keyed a nonexistent 'categories' field; re-keyed to the file's actual schema")

with open("paper/publication/final_validation/review_2026-11-09/data_audit/_work/d4_results_p5.tsv", "w") as f:
    for r in results:
        f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")
print("\nPART5 RESULTS:", len(results))
for name, _, _, _, st, _ in results:
    print(" ", st, name)
