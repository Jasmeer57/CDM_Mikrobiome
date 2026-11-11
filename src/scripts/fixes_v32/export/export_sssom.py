"""SSSOM export of the ACCEPTED term-concept mappings of CDM 3.x (3.2.0-candidate DB, read-only).

Population: term_concept_map rows with mapping_disposition_reviewed = 'ACCEPTED' (the two judge models, Gemma G9 and
DeepSeek-R1, agreed on the relation).  The agreed relation gives the SKOS predicate (subject = CDM term, object =
ontology concept; BROADER = "the concept is more general than the term"):
    EXACT -> skos:exactMatch   BROADER -> skos:broadMatch   NARROWER -> skos:narrowMatch   RELATED -> skos:relatedMatch
Rows with the same (subject, predicate, object) are merged (their mapping_row_ids are kept in `other`).
mapping_justification = semapv:CompositeMatching (candidate retrieved by lexical search of OLS / BioPortal / UMLS /
NCBI Taxonomy, relation assigned by agreement of two language-model judges; guard rules applied).  Human verdicts
of the pre-registered review (reviewer_A) are attached in `other` for the reviewed rows; they do not change the
justification.  subject_label is blanked where the public-release rules R2-R4 would flag it (licence policy).

Outputs: exports/sssom/cdm_3.2.0-candidate_mappings.sssom.tsv (embedded YAML metadata block) + .sssom.yml
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import EXPORT, ID_NOTE, PREFIXES, CurieMaker, Redactor, biolink_maps, open_db, rights  # noqa

PRED = {"EXACT": "skos:exactMatch", "BROADER": "skos:broadMatch", "NARROWER": "skos:narrowMatch",
        "RELATED": "skos:relatedMatch"}
FIELDS = ["subject_id", "subject_label", "subject_category", "predicate_id", "object_id", "object_label",
          "mapping_justification", "confidence", "subject_source", "mapping_tool",
          "mapping_date", "comment", "other"]


def main():
    out = EXPORT / "sssom"
    out.mkdir(parents=True, exist_ok=True)
    con = open_db()
    rt = rights()
    red = Redactor(con, rt)
    CM = biolink_maps()
    cm = CurieMaker()
    hr = {r["target_id"]: r for r in con.execute(
        "SELECT target_id, reviewer, decision, protocol_id FROM human_review WHERE target_entity='term_concept_map'")}
    q = """SELECT m.mapping_row_id, m.term_id, m.concept_id, m.relation_llm_g9, m.relation_deepseek, m.match_scores,
                  m.source_service_mapping, m.g9_run_id, m.deepseek_run_id, m.guard_status, m.candidate_rank,
                  t.term, t.cdm_type, c.concept_label, c.source_service, c.ontology_name
           FROM term_concept_map m JOIN canonical_term t USING(term_id) JOIN concept c USING(concept_id)
           WHERE m.mapping_disposition_reviewed='ACCEPTED' ORDER BY m.mapping_row_id"""
    groups = defaultdict(list)
    n_rows = disagree = 0
    for r in con.execute(q):
        n_rows += 1
        if r["relation_llm_g9"] != r["relation_deepseek"]:
            disagree += 1
            continue
        groups[(r["term_id"], PRED[r["relation_llm_g9"]], r["concept_id"])].append(r)
    today = dt.date.today().isoformat()
    rows = []
    for (tid, pred, cid), rs in groups.items():
        r0 = rs[0]
        conf = []
        for r in rs:
            try:
                conf.append(float(json.loads(r["match_scores"] or "{}").get("confidence")))
            except (TypeError, ValueError):
                pass
        svc = sorted({r["source_service"] or r["source_service_mapping"] or "" for r in rs})
        other = {"cdm_mapping_row_ids": [r["mapping_row_id"] for r in rs], "agreed_relation": r0["relation_llm_g9"],
                 "judge_runs": sorted({x for r in rs for x in (r["g9_run_id"], r["deepseek_run_id"]) if x}),
                 "guard_status": sorted({r["guard_status"] or "" for r in rs}), "lookup_service": svc}
        rev = [hr[r["mapping_row_id"]] for r in rs if r["mapping_row_id"] in hr]
        if rev:
            other["human_review"] = [{"reviewer": v["reviewer"], "verdict": v["decision"],
                                      "protocol": v["protocol_id"]} for v in rev]
        cat = CM.BIOLINK_CDM_TYPE.get(r0["cdm_type"], ("biolink:NamedThing",))[0]
        obj = cm.curie(cid)
        rows.append({"subject_id": f"MCDMT:{tid}", "subject_label": red.clean(r0["term"]), "subject_category": cat,
                     "predicate_id": pred, "object_id": obj, "object_label": r0["concept_label"] or "",
                     "mapping_justification": "semapv:CompositeMatching",
                     "confidence": round(max(conf), 4) if conf else "",
                     "subject_source": "MCDM:cdm_3.1.0",
                     "mapping_tool": "CDM cv_linking (OLS4/BioPortal/UMLS/NCBI Taxonomy lookup) + mapping_guards_v2 "
                                     "+ agreement of Gemma-G9 and DeepSeek-R1 relation judgements",
                     "mapping_date": today, "comment": "model-judged mapping, not human-curated" +
                     ("; human-reviewed in a pre-registered sample" if rev else ""),
                     "other": json.dumps(other, separators=(",", ":"), sort_keys=True)})
    rows.sort(key=lambda r: (r["subject_id"], r["object_id"], r["predicate_id"]))
    curie_map = {**{k: v for k, v in PREFIXES.items() if k in ("MCDM", "MCDMT")}, **cm.used,
                 "skos": "http://www.w3.org/2004/02/skos/core#", "semapv": "https://w3id.org/semapv/vocab/",
                 "biolink": "https://w3id.org/biolink/vocab/"}
    meta = {"curie_map": dict(sorted(curie_map.items())),
            "mapping_set_id": "https://w3id.org/microbiome-cdm/mappings/cdm_3.2.0-candidate_mappings.sssom.tsv",
            "mapping_set_version": "3.2.0-candidate",
            "mapping_set_title": "Microbiome literature CDM: accepted term-to-concept mappings (3.2.0-candidate)",
            "mapping_set_description": (
                "ACCEPTED term_concept_map rows of CDM 3.1.0 (two model judges agreed on the relation). "
                "Model-judged, not human-curated; a pre-registered random sample of 500 rows was reviewed by one "
                "human reviewer (verdicts in `other`). " + ID_NOTE),
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "mapping_date": today,
            "comment": "Candidate package, PENDING lead approval; rights review of source papers pending."}
    with open(out / "cdm_3.2.0-candidate_mappings.sssom.tsv", "w") as f:
        for line in yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).splitlines():
            f.write("#" + line + "\n")
        f.write("\t".join(FIELDS) + "\n")
        for r in rows:
            f.write("\t".join(str(r[k]).replace("\t", " ").replace("\n", " ") for k in FIELDS) + "\n")
    (out / "cdm_3.2.0-candidate_mappings.sssom.yml").write_text(yaml.safe_dump(meta, sort_keys=False))
    stats = {"accepted_rows": n_rows, "rows_with_judge_disagreement_skipped": disagree,
             "sssom_mappings": len(rows),
             "by_predicate": {p: sum(r["predicate_id"] == p for r in rows) for p in PRED.values()},
             "human_reviewed_mappings": sum('"human_review"' in r["other"] for r in rows),
             "subject_labels_blanked_R2_R4": red.blanked, "prefixes": len(curie_map)}
    (out / "sssom_export_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
