"""Validate the 3.x exports: SSSOM (sssom-py parse + validate), KGX (kgx validate, Biolink 4.4.6),
RDF (rdflib parse, SHACL shapes with pyshacl, SPARQL sanity queries) and the licence policy in every export.
Writes exports/VALIDATION.json (+ tool reports).
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from rdflib import Graph

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import EXPORT, rights  # noqa: E402

BIN = Path(sys.executable).parent
SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix mcdm: <https://w3id.org/microbiome-cdm/schema/> .
mcdm:StatementShape a sh:NodeShape ; sh:targetClass rdf:Statement ;
  sh:property [ sh:path rdf:subject ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path rdf:predicate ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path rdf:object ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path prov:wasGeneratedBy ; sh:minCount 1 ; sh:class prov:Activity ] ;
  sh:property [ sh:path prov:hadPrimarySource ; sh:minCount 1 ] .
mcdm:AnchorShape a sh:NodeShape ; sh:targetClass mcdm:TextAnchor ;
  sh:property [ sh:path mcdm:charStart ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ] ;
  sh:property [ sh:path mcdm:charEnd ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ] ;
  sh:property [ sh:path mcdm:sentenceSha256 ; sh:minCount 1 ; sh:maxCount 1 ] ;
  sh:property [ sh:path prov:wasDerivedFrom ; sh:minCount 1 ; sh:maxCount 1 ; sh:class prov:Entity ] .
mcdm:MappingShape a sh:NodeShape ; sh:targetClass mcdm:MappingRecord ;
  sh:property [ sh:path mcdm:mappingSubject ; sh:minCount 1 ; sh:maxCount 1 ] ;
  sh:property [ sh:path mcdm:mappingObject ; sh:minCount 1 ; sh:maxCount 1 ] ;
  sh:property [ sh:path prov:wasGeneratedBy ; sh:minCount 1 ; sh:class prov:Activity ] .
mcdm:VerdictShape a sh:NodeShape ; sh:targetClass mcdm:HumanVerdict ;
  sh:property [ sh:path prov:wasGeneratedBy ; sh:minCount 1 ; sh:maxCount 1 ; sh:class prov:Activity ] ;
  sh:property [ sh:path prov:wasAttributedTo ; sh:minCount 1 ; sh:class prov:Person ] .
"""
SPARQL = {
    "statements": "SELECT (COUNT(?s) AS ?n) WHERE { ?s a rdf:Statement }",
    "statements_without_run": "SELECT (COUNT(?s) AS ?n) WHERE { ?s a rdf:Statement FILTER NOT EXISTS "
                              "{ ?s prov:wasGeneratedBy ?a } }",
    "anchors": "SELECT (COUNT(?e) AS ?n) WHERE { ?e a mcdm:TextAnchor }",
    "anchors_with_text": "SELECT (COUNT(?e) AS ?n) WHERE { ?e a mcdm:TextAnchor ; rdf:value ?v }",
    "LICENCE_text_from_non_INCLUDE_TEXT_paper": (
        "SELECT (COUNT(?e) AS ?n) WHERE { ?e a mcdm:TextAnchor ; rdf:value ?v ; prov:wasDerivedFrom ?s . "
        "?s dcterms:isPartOf ?p . ?p mcdm:rightsBucket ?b FILTER(?b != 'INCLUDE_TEXT') }"),
    "mapping_records": "SELECT (COUNT(?m) AS ?n) WHERE { ?m a mcdm:MappingRecord }",
    "human_verdicts": "SELECT (COUNT(?v) AS ?n) WHERE { ?v a mcdm:HumanVerdict }",
    "human_verdicts_by_reviewer": "SELECT ?l (COUNT(?v) AS ?n) WHERE { ?v a mcdm:HumanVerdict ; prov:wasAttributedTo "
                                  "?a . ?a rdfs:label ?l } GROUP BY ?l",
    "persons": "SELECT (COUNT(?a) AS ?n) WHERE { ?a a prov:Person }",
    "software_agents": "SELECT (COUNT(?a) AS ?n) WHERE { ?a a prov:SoftwareAgent }",
    "activities": "SELECT (COUNT(?a) AS ?n) WHERE { ?a a prov:Activity }",
}


def run(cmd, log):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    Path(log).write_text(f"$ {' '.join(map(str, cmd))}\nexit {p.returncode}\n--- stdout\n{p.stdout}\n--- stderr\n"
                         f"{p.stderr}")
    return p


def main():
    res = {}
    rt = rights()
    # ---------------- SSSOM ----------------
    sdir = EXPORT / "sssom"
    tsv = sdir / "cdm_3.2.0-candidate_mappings.sssom.tsv"
    p1 = run([BIN / "sssom", "parse", "-I", "sssom-tsv", str(tsv), "-o", str(sdir / "_reparsed.sssom.tsv")],
             sdir / "sssom_parse.log")
    p2 = run([BIN / "sssom", "validate", "-V", "JsonSchema", "-V", "PrefixMapCompleteness", "-V", "StrictCurieFormat",
              str(tsv)], sdir / "sssom_validate.log")
    n_in = sum(1 for l in open(tsv) if not l.startswith("#")) - 1
    n_re = sum(1 for l in open(sdir / "_reparsed.sssom.tsv") if not l.startswith("#")) - 1 if p1.returncode == 0 else 0
    res["sssom"] = {"rows": n_in, "parse_exit": p1.returncode, "rows_after_roundtrip": n_re,
                    "validate_exit": p2.returncode,
                    "validate_output_tail": (p2.stdout + p2.stderr).strip().splitlines()[-5:],
                    "PASS": p1.returncode == 0 and p2.returncode == 0 and n_re == n_in}
    # ---------------- KGX ----------------
    kdir = EXPORT / "kgx"
    nodes, edges = kdir / "cdm_3.2.0-candidate_nodes.tsv", kdir / "cdm_3.2.0-candidate_edges.tsv"
    p3 = run([BIN / "kgx", "validate", "-i", "tsv", "-o", str(kdir / "kgx_validate_report.json"),
              "--biolink-release", "4.4.6", str(nodes), str(edges)], kdir / "kgx_validate.log")
    rep = {}
    if (kdir / "kgx_validate_report.json").exists():
        try:
            rep = json.loads((kdir / "kgx_validate_report.json").read_text() or "{}")
        except json.JSONDecodeError:
            rep = {"unparsed": True}

    def count(d, depth=0):
        """kgx report: {ErrorLevel: {ErrorType: {message: [ids]}}} -> {level: {type: n_ids}}"""
        out = {}
        for lvl, types in (d or {}).items():
            if isinstance(types, dict):
                out[lvl] = {t: sum(len(v) if isinstance(v, list) else 1 for v in (m.values() if isinstance(m, dict)
                                                                                 else [m]))
                            for t, m in types.items()}
        return out
    kc = count(rep)
    n_err = sum(sum(v.values()) for k, v in kc.items() if k.upper() == "ERROR")
    ev_bad = 0
    with open(kdir / "edge_evidence.tsv") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["sentence"] and rt.get(r["paper_id"]) != "INCLUDE_TEXT":
                ev_bad += 1
    res["kgx"] = {"validate_exit": p3.returncode, "report_counts": kc, "errors": n_err,
                  "nodes": sum(1 for _ in open(nodes)) - 1, "edges": sum(1 for _ in open(edges)) - 1,
                  "LICENCE_evidence_text_from_non_INCLUDE_TEXT_paper": ev_bad,
                  "PASS": p3.returncode == 0 and n_err == 0 and ev_bad == 0}
    # ---------------- RDF ----------------
    rdir = EXPORT / "rdf"
    g = Graph()
    g.parse(rdir / "cdm_3.2.0-candidate.ttl", format="turtle")
    ns = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
          "prov": "http://www.w3.org/ns/prov#", "dcterms": "http://purl.org/dc/terms/",
          "mcdm": "https://w3id.org/microbiome-cdm/schema/"}
    sp = {}
    for k, qtxt in SPARQL.items():
        rows = list(g.query(qtxt, initNs=ns))
        sp[k] = int(rows[0][0]) if len(rows) == 1 and len(rows[0]) == 1 else {str(r[0]): int(r[1]) for r in rows}
    import pyshacl
    shapes = Graph().parse(data=SHAPES, format="turtle")
    (rdir / "shapes.ttl").write_text(SHAPES)
    conforms, rg, rtext = pyshacl.validate(g, shacl_graph=shapes, inference="none", allow_warnings=True)
    n_viol = len(list(rg.subjects(predicate=None, object=None))) if not conforms else 0
    (rdir / "shacl_report.txt").write_text(rtext[:200000])
    res["rdf"] = {"parsed_triples": len(g), "sparql": sp, "shacl_conforms": bool(conforms),
                  "shacl_report_head": rtext.splitlines()[:3],
                  "PASS": bool(conforms) and sp["statements_without_run"] == 0
                  and sp["LICENCE_text_from_non_INCLUDE_TEXT_paper"] == 0}
    res["all_pass"] = all(v["PASS"] for v in res.values() if isinstance(v, dict))
    (EXPORT / "VALIDATION.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
