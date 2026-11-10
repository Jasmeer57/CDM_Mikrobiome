"""Integrity checks for the Gate 4 package (read-only); prints and writes _integrity_check.json."""
import csv
import collections
import json
import os
import sqlite3
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)
ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
D = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "outputs/human_validation/gate4_2026-11-02")
c = sqlite3.connect(f"file:{ROOT / 'releases/cdm_v3/3.0.2/microbiome_cdm_v3.db'}?mode=ro", uri=True)
ANN = {"CATALOGUE_ANNOTATION_SHEET.csv": ["annotator_id", "decision", "evidence_supports", "corrected_value",
                                          "missing_important_values", "notes"],
       "TERMINOLOGY_ANNOTATION_SHEET.csv": ["annotator_id", "is_entity", "boundary_correct", "type_correct",
                                            "correct_type_if_wrong", "canonical_term_correct", "mapping_correct",
                                            "definition_supported", "notes"],
       "TRIPLE_ANNOTATION_SHEET.csv": ["annotator_id", "subject_correct", "object_correct", "predicate_correct",
                                       "direction_correct", "explicitly_supported", "scientifically_meaningful",
                                       "overall", "notes"]}
S = {f: list(csv.DictReader(open(D / f, encoding="utf-8"))) for f in ANN}
cat, term, tri = (S[f] for f in ANN)
recs = [x for x in cat if x["row_type"] == "RECORD"]
TID = {"findings": "finding_id", "assays": "assay_id", "samples": "sample_group_id", "cohorts": "cohort_id",
       "datasets": "dataset_id", "data_assets": "asset_id"}


def ids(p):
    return {(j["entity_type"], j["fields"][TID[j["entity_type"]]]) for j in map(json.loads, open(p))}


kept = ids(ROOT / "releases/data_catalogue_v3/3.1.1/records/catalogue_records.jsonl")
rem = ids(ROOT / "releases/data_catalogue_v3/3.1.1/provenance/_removed.jsonl")
papers = {p for (p,) in c.execute("SELECT paper_id FROM paper")}
allr = cat + term + tri
strata = json.load(open(D / "_sampling_strata.json"))
r = {
    "control_chars": sum(ch in open(D / f, encoding="utf-8").read() for f in os.listdir(D) if f.endswith(".csv")
                         for ch in ("\x00", "\x0b", "\x0c")),
    "items": {"catalogue": len(recs), "terminology": len(term), "triples": len(tri)},
    "catalogue_rows": dict(collections.Counter(x["row_type"] for x in cat)),
    "catalogue_by_table": dict(collections.Counter(x["table"] for x in recs)),
    "duplicates": {"catalogue": len(recs) - len({(x["table"], x["record_id"]) for x in recs}),
                   "terminology": len(term) - len({x["mention_row_id"] for x in term}),
                   "triples": len(tri) - len({x["canonical_triple_id"] for x in tri})},
    "annotation_fields_empty": all(all(x[k] == "" for k in ANN[f]) for f in ANN for x in S[f]),
    "ids_resolve": {
        "catalogue": sum(((x["table"], x["record_id"]) in (rem if x["stratum"] == "C_REMOVED_BY_G3" else kept)) for x in recs),
        "terminology": sum(c.execute("SELECT 1 FROM term_mention WHERE mention_row_id=?", (x["mention_row_id"],)).fetchone()
                           is not None for x in term),
        "triples": sum(c.execute("SELECT 1 FROM relation WHERE canonical_triple_id=? UNION SELECT 1 FROM removed_relation "
                                 "WHERE canonical_triple_id=?", (x["canonical_triple_id"],) * 2).fetchone() is not None
                       for x in tri)},
    "paper_refs_resolve": f'{sum(x["paper_id"] in papers for x in allr)}/{len(allr)}',
    "local_files_exist": f'{sum((ROOT / x["local_markdown"]).exists() and (ROOT / x["local_text"]).exists() for x in allr)}/{len(allr)}',
    "catalogue_context": dict(collections.Counter("context" if x["evidence_context_marked"] else
                                                  ("section_only" if x["section_record_id"] else "no_section") for x in recs)),
    "catalogue_offsets_from": dict(collections.Counter(x["offsets_from"] for x in recs)),
    "mention_surface_marked_in_context": f'{sum(("⟦" + x["surface_form"] + "⟧") in x["mention_context_marked"] for x in term)}/{len(term)}',
    "triples_with_source_sentence": f'{sum(bool(x["source_sentence"]) for x in tri)}/{len(tri)}',
    "double_annotated": {"catalogue": sum(x["double_annotate"] == "YES" for x in recs),
                         "terminology": sum(x["double_annotate"] == "YES" for x in term),
                         "triples": sum(x["double_annotate"] == "YES" for x in tri)},
    "strata_sums": {sh: sum(x["sample_n"] for x in strata["strata"] if x["sheet"] == sh)
                    for sh in ("catalogue", "terminology", "triples")},
    "design_probabilities_consistent": all(abs(float(x["inclusion_probability"]) - float(x["sample_n"]) / float(x["population_N"]))
                                           < 1e-6 for x in recs + term + tri),
    "papers_referenced": strata["papers_referenced"], "max_items_per_paper": strata["max_items_per_paper"],
}
r["pass"] = (r["control_chars"] == 0 and r["items"] == {"catalogue": 200, "terminology": 200, "triples": 100}
             and not any(r["duplicates"].values()) and r["annotation_fields_empty"]
             and r["ids_resolve"] == r["items"] and r["design_probabilities_consistent"])
(D / "_integrity_check.json").write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n")
print(json.dumps(r, indent=1, ensure_ascii=False))
