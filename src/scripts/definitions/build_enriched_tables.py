"""Assemble the enriched terminology: one row per canonical term and one row per accepted mapping (no model run).

    ~/venvs/parquet_export/bin/python src/scripts/definitions/build_enriched_tables.py

Inputs (all read-only): CDM 3.0.3 (terms, taxonomy, mention counts, extracted definitions and abbreviation expansions,
accepted mappings, concept labels), the model-generated layers in outputs/results/term_definitions_llm_2026-11-09/
(contextual definitions, full forms, synonyms; completion pass for accepted-mapping terms; concept descriptions) and
the ontology cache outputs/results/ontology_definitions_2026-11-09/concept_ontology_info.jsonl.
Outputs in outputs/results/enriched_terminology_2026-11-09/: terms_enriched.csv.gz, mappings_enriched.csv.gz,
SUMMARY.json. Column prefixes: SOURCE_ = from the papers or an ontology; MODEL_ = model-generated (Qwen3.5-4B).
Contains paper-derived strings: internal; rights-filter before any release.
"""
from __future__ import annotations

import csv
import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
L = ROOT / "outputs/results/term_definitions_llm_2026-11-09"
OC = ROOT / "outputs/results/ontology_definitions_2026-11-09/concept_ontology_info.jsonl"
OUT = ROOT / "outputs/results/enriched_terminology_2026-11-09"


def latest(path, key):
    d = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") != "UNPARSED" or r[key] not in d:
                d[r[key]] = r
    return d


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    defs = latest(L / "all/definitions.jsonl", "term_id")
    comp = latest(L / "accepted/completion/term_completion.jsonl", "term_id")
    cdesc = latest(L / "accepted/completion/concept_descriptions.jsonl", "concept_id")
    onto = latest(OC, "concept_id")
    tax = {r["term_id"]: r for r in con.execute("SELECT term_id, category, subcategory, sub_qwen, sub_gemma, agreement_status FROM taxonomy_annotation")}
    cnt = {r[0]: (r[1], r[2]) for r in con.execute("SELECT canonical_term_id, count(*), count(DISTINCT paper_id) FROM term_mention GROUP BY 1")}
    xdef, xabbr = defaultdict(list), {}
    for r in con.execute("SELECT term_id, definition_source, definition_text, paper_id, evidence_anchor_status FROM term_definition"):
        xdef[r["term_id"]].append(r)
        if r["definition_source"] == "ABBREVIATION_EXPANSION" and (r["term_id"] not in xabbr or r["evidence_anchor_status"] == "EXACT"):
            xabbr[r["term_id"]] = (" ".join((r["definition_text"] or "").split())[:200], r["paper_id"])
    acc = defaultdict(list)
    for r in con.execute("SELECT term_id, concept_id, relation_llm_g9 FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'"):
        acc[r["term_id"]].append(r)
    concept = {r[0]: r for r in con.execute("SELECT concept_id, concept_label, source_service, ontology_name FROM concept")}
    kindmap = {"DEFINED": "CONTEXTUAL", "GENERAL": "GENERAL", "NON_CONCEPT": "NON_CONCEPT"}

    tf = ["term_id", "term", "cdm_type", "taxonomy_category", "taxonomy_subcategory", "taxonomy_agreement", "mentions",
          "papers", "found_by_models", "SOURCE_extracted_definitions", "SOURCE_paper_full_form", "SOURCE_paper_full_form_paper",
          "MODEL_definition", "MODEL_definition_kind", "MODEL_full_form", "MODEL_is_abbreviation", "MODEL_synonyms",
          "n_accepted_mappings", "accepted_concepts"]
    stats = Counter()
    with gzip.open(OUT / "terms_enriched.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=tf); w.writeheader()
        for t in con.execute("SELECT term_id, term, cdm_type, models FROM canonical_term ORDER BY term_id"):
            tid = t["term_id"]; d = defs.get(tid, {}); c = comp.get(tid, {}); tx = tax.get(tid)
            ff = c.get("full_form") if c.get("is_abbreviation") == "Y" else (d.get("full_form") or "")
            syn = c.get("synonyms") or d.get("synonyms") or []
            row = {"term_id": tid, "term": t["term"], "cdm_type": t["cdm_type"],
                   "taxonomy_category": (tx["category"] if tx else "") or "", "taxonomy_subcategory": (tx["subcategory"] if tx else "") or "",
                   "taxonomy_agreement": (tx["agreement_status"] if tx else "") or "",
                   "mentions": cnt.get(tid, (0, 0))[0], "papers": cnt.get(tid, (0, 0))[1], "found_by_models": t["models"] or "",
                   "SOURCE_extracted_definitions": " || ".join(" ".join((x["definition_text"] or "").split())[:200] for x in xdef.get(tid, [])[:3]),
                   "SOURCE_paper_full_form": xabbr.get(tid, ("", ""))[0], "SOURCE_paper_full_form_paper": xabbr.get(tid, ("", ""))[1],
                   "MODEL_definition": d.get("definition", ""), "MODEL_definition_kind": kindmap.get(d.get("status", ""), d.get("status", "")),
                   "MODEL_full_form": ff or "", "MODEL_is_abbreviation": c.get("is_abbreviation", ""), "MODEL_synonyms": "; ".join(syn),
                   "n_accepted_mappings": len(acc.get(tid, [])),
                   "accepted_concepts": "; ".join(f"{concept[m['concept_id']][1]} ({m['concept_id']})" for m in acc.get(tid, [])[:5] if m["concept_id"] in concept)}
            w.writerow(row)
            stats["terms"] += 1
            stats["with_model_definition"] += bool(row["MODEL_definition"])
            stats["with_extracted_definition"] += bool(row["SOURCE_extracted_definitions"])
            stats["with_full_form_any"] += bool(row["MODEL_full_form"] or row["SOURCE_paper_full_form"])
            stats["with_synonyms"] += bool(row["MODEL_synonyms"])
            stats[f"definition_kind_{row['MODEL_definition_kind'] or 'NONE'}"] += 1

    mf = ["term_id", "term", "cdm_type", "concept_id", "concept_label", "ontology_service", "agreed_relation",
          "SOURCE_ontology_definition", "SOURCE_ontology_definition_from", "SOURCE_ontology_synonyms",
          "MODEL_concept_description", "concept_definition_final", "concept_definition_final_origin"]
    terms = {r[0]: (r[1], r[2]) for r in con.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    with gzip.open(OUT / "mappings_enriched.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=mf); w.writeheader()
        for tid, ms in acc.items():
            for m in ms:
                cid = m["concept_id"]; o = onto.get(cid, {}); cd = cdesc.get(cid, {})
                od, md = o.get("definition", ""), cd.get("description", "")
                final, origin = (od, "ONTOLOGY") if od else ((md, "MODEL_GENERATED") if md else ("", "NONE"))
                w.writerow({"term_id": tid, "term": terms[tid][0], "cdm_type": terms[tid][1], "concept_id": cid,
                            "concept_label": concept.get(cid, ("", "", "", ""))[1], "ontology_service": concept.get(cid, ("", "", "", ""))[2],
                            "agreed_relation": m["relation_llm_g9"], "SOURCE_ontology_definition": od,
                            "SOURCE_ontology_definition_from": o.get("source", ""), "SOURCE_ontology_synonyms": "; ".join(o.get("synonyms") or []),
                            "MODEL_concept_description": md, "concept_definition_final": final, "concept_definition_final_origin": origin})
                stats["mappings"] += 1
                stats[f"mapping_definition_{origin}"] += 1
                stats["mappings_with_ontology_synonyms"] += bool(o.get("synonyms"))
    summ = dict(stats); summ["note"] = ("SOURCE_ columns from papers / ontologies; MODEL_ columns Qwen3.5-4B generated, not curated; "
                                         "internal (paper-derived strings): rights-filter before release")
    json.dump(summ, open(OUT / "SUMMARY.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
