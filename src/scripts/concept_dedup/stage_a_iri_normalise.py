#!/usr/bin/env python3
"""Stage A of concept deduplication: collapse IRI spelling variants of the SAME concept.

Deterministic, no model. Example: http://id.nlm.nih.gov/mesh/D000109 and
http://purl.bioontology.org/ontology/MESH/D000109 are one concept (MESH:D000109).

Reads the frozen CDM 3.0.3 read-only; writes a new labelled layer to
outputs/results/concept_dedup_2026-11-09/stage_a/. The CDM itself is not changed.

Outputs
  concept_curie_map.tsv   concept_id -> curie (every concept, accepted flag)
  iri_variant_groups.jsonl  one row per CURIE that has >1 IRI spelling
  summary.json
"""
import collections
import json
import re
import sqlite3
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "outputs/results/concept_dedup_2026-11-09/stage_a"

# ontology prefix aliases -> one canonical prefix
PREFIX_ALIAS = {
    "NCBITAXON": "NCBITaxon", "NCBITAXONOMY": "NCBITaxon",
    "MESH": "MESH", "MSH": "MESH",
    "SNOMEDCT": "SNOMEDCT", "SNOMEDCT_US": "SNOMEDCT", "SCTID": "SNOMEDCT",
    "NCIT": "NCIT", "NCI": "NCIT", "NCIT_THESAURUS": "NCIT",
    "HGNC": "HGNC", "EFO": "EFO", "ORPHANET": "ORDO", "ORDO": "ORDO",
}

RULES = [
    # (regex, prefix or None to take group 'p', id group)
    (re.compile(r"^https?://purl\.obolibrary\.org/obo/(?P<p>[A-Za-z][A-Za-z0-9]*)_(?P<i>.+)$"), None),
    (re.compile(r"^https?://purl\.bioontology\.org/ontology/(?P<p>[A-Za-z0-9_\-]+)/(?P<i>.+)$"), None),
    (re.compile(r"^https?://id\.nlm\.nih\.gov/mesh/(?P<i>[A-Z]\d+)$"), "MESH"),
    (re.compile(r"^https?://ncicb\.nci\.nih\.gov/xml/owl/EVS/Thesaurus\.owl#(?P<i>C\d+)$"), "NCIT"),
    (re.compile(r"^https?://snomed\.info/id/(?P<i>\d+)$"), "SNOMEDCT"),
    (re.compile(r"^https?://www\.genenames\.org/data/gene-symbol-report/#!/hgnc_id/(?:HGNC:)?(?P<i>\d+)$"), "HGNC"),
    (re.compile(r"^https?://identifiers\.org/hgnc/(?:HGNC:)?(?P<i>\d+)$"), "HGNC"),
    (re.compile(r"^https?://www\.ebi\.ac\.uk/efo/EFO_(?P<i>\d+)$"), "EFO"),
    (re.compile(r"^https?://www\.orpha\.net/ORDO/Orphanet_(?P<i>\d+)$"), "ORDO"),
    (re.compile(r"^(?P<p>[A-Za-z][A-Za-z0-9_]*):(?P<i>[^/].*)$"), None),  # already a CURIE
]


def to_curie(iri: str) -> str:
    s = iri.strip()
    for rx, fixed in RULES:
        m = rx.match(s)
        if not m:
            continue
        p = fixed or m.group("p")
        if p.lower().startswith("http"):
            break
        p = PREFIX_ALIAS.get(p.upper(), p.upper())
        i = m.group("i")
        if p == "HGNC":
            i = i.split(":")[-1]
        return f"{p}:{i}"
    return s  # unknown namespace: the IRI is its own key


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    accepted = {r[0] for r in db.execute(
        "select distinct concept_id from term_concept_map where mapping_disposition_reviewed='ACCEPTED'")}
    labels = dict(db.execute("select concept_id, concept_label from concept"))
    all_ids = set(labels) | accepted | {r[0] for r in db.execute("select distinct concept_id from term_concept_map")}
    all_ids = {c for c in all_ids if c}  # mapping rows without a concept id carry no concept

    groups = collections.defaultdict(list)
    with open(OUT / "concept_curie_map.tsv", "w", encoding="utf-8") as f:
        f.write("concept_id\tcurie\taccepted\tconcept_label\n")
        for cid in sorted(all_ids):
            cu = to_curie(cid)
            groups[cu].append(cid)
            f.write(f"{cid}\t{cu}\t{int(cid in accepted)}\t{' '.join((labels.get(cid) or '').split())}\n")

    multi = {cu: ids for cu, ids in groups.items() if len(ids) > 1}
    with open(OUT / "iri_variant_groups.jsonl", "w", encoding="utf-8") as f:
        for cu, ids in sorted(multi.items()):
            f.write(json.dumps({"curie": cu, "iris": sorted(ids),
                                "accepted_iris": sorted(i for i in ids if i in accepted),
                                "labels": sorted({labels.get(i) or "" for i in ids})}) + "\n")

    acc_curies = {to_curie(c) for c in accepted}
    summary = {
        "stage": "A - IRI spelling variants (deterministic, no model)",
        "source": "CDM 3.0.3 (read-only)",
        "all_concepts": {"iris": len(all_ids), "distinct_after": len(groups),
                         "curies_with_variants": len(multi),
                         "iris_collapsed": sum(len(v) - 1 for v in multi.values())},
        "accepted_concepts": {"iris": len(accepted), "distinct_after": len(acc_curies),
                              "iris_collapsed": len(accepted) - len(acc_curies)},
        "unparsed_namespaces_kept_as_is": sum(1 for cu in groups if cu.startswith("http")),
        "note": "new labelled layer; frozen CDM unchanged; needs lead approval before any use (CHANGE_RECORD)",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
