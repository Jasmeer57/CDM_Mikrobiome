"""RDF/Turtle export of CDM 3.x with PROV-O provenance (3.2.0-candidate DB, read-only).

Content (same populations as the SSSOM and KGX exports, plus the human reviews):
  * papers (prov:Entity, schema:ScholarlyArticle; DOI/PMID), sections (prov:Entity, dcterms:isPartOf paper, text sha256)
  * extraction runs (prov:Activity; prov:wasAssociatedWith a prov:SoftwareAgent per model; prov:endedAtTime when an
    ISO timestamp is recorded; prov:used the source artefact with its sha256)
  * canonical terms used by the mappings/triples (skos:Concept, skos:prefLabel unless R2-R4 blanked)
  * accepted mappings: a skos:*Match triple per mapping plus a mapping record (prov:Entity) with
    prov:wasGeneratedBy the two judge runs
  * canonical triples as rdf:Statement (rdf:predicate = Biolink predicate, as in the KGX export) with
    prov:wasGeneratedBy the extraction run, prov:hadPrimarySource the papers, prov:wasDerivedFrom one evidence entity
    per anchor; an evidence entity carries prov:wasDerivedFrom its section, offsets, anchor status and the sentence
    SHA-256; rdf:value (the sentence) only for INCLUDE_TEXT papers
  * human reviews: prov:Activity (prov:used the reviewed row, prov:wasAssociatedWith an anonymised prov:Person,
    prov:endedAtTime the review date) generating a verdict entity (prov:wasAttributedTo the reviewer)
Output: exports/rdf/cdm_3.2.0-candidate.ttl (gzip copy if large) + rdf_export_stats.json
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import RDF, RDFS, SKOS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import EXPORT, ID_NOTE, PREFIXES, Redactor, biolink_maps, open_db, rights, sha, text_allowed  # noqa

BL = Namespace("https://w3id.org/biolink/vocab/")
SDO = Namespace("http://schema.org/")
N = {k: Namespace(v) for k, v in PREFIXES.items()}
PRED = {"EXACT": SKOS.exactMatch, "BROADER": SKOS.broadMatch, "NARROWER": SKOS.narrowMatch,
        "RELATED": SKOS.relatedMatch}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$")


def iri_of(cid: str) -> URIRef:
    if re.fullmatch(r"C\d{7}", cid):
        return URIRef("https://uts.nlm.nih.gov/uts/umls/concept/" + cid)
    if cid.startswith("NCBITaxon:"):
        return URIRef("http://purl.obolibrary.org/obo/NCBITaxon_" + cid.split(":", 1)[1])
    m = re.fullmatch(r"([A-Za-z][A-Za-z0-9.]*):([A-Za-z0-9._\-]+)", cid)
    if m and not cid.startswith(("http:", "https:", "file:")):
        return URIRef(PREFIXES["MCDM"].rsplit("schema/", 1)[0] + "external/" + m.group(1) + "/" + m.group(2))
    return URIRef(cid)


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", s)


def main():
    out = EXPORT / "rdf"
    out.mkdir(parents=True, exist_ok=True)
    con = open_db()
    rt = rights()
    red = Redactor(con, rt)
    CM = biolink_maps()
    g = Graph()
    for k, ns in N.items():
        g.bind(k.lower(), ns)
    g.bind("biolink", BL)
    g.bind("prov", PROV)
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("schema", SDO)
    M = N["MCDM"]
    ds = URIRef(PREFIXES["MCDM"] + "dataset/cdm_3.2.0-candidate")
    g.add((ds, RDF.type, PROV.Entity))
    g.add((ds, RDFS.comment, Literal("Microbiome literature CDM 3.2.0-candidate RDF export (derived from frozen "
                                     "release 3.1.0). " + ID_NOTE)))
    g.add((ds, PROV.wasRevisionOf, URIRef(PREFIXES["MCDM"] + "dataset/cdm_3.1.0")))
    g.add((URIRef(PREFIXES["MCDM"] + "dataset/cdm_3.1.0"), PROV.wasRevisionOf,
           URIRef(PREFIXES["MCDM"] + "dataset/cdm_3.0.3")))

    # papers + sections
    for r in con.execute("SELECT paper_id, doi, pmid, title FROM paper"):
        p = N["MCDMP"][r["paper_id"]]
        g.add((p, RDF.type, PROV.Entity))
        g.add((p, RDF.type, SDO.ScholarlyArticle))
        if r["doi"]:
            g.add((p, DCTERMS.identifier, Literal("doi:" + r["doi"])))
        if r["pmid"]:
            g.add((p, DCTERMS.identifier, Literal(f"PMID:{r['pmid']}")))
        if r["title"]:
            g.add((p, DCTERMS.title, Literal(r["title"])))     # bibliographic metadata: exempt
        g.add((p, M.rightsBucket, Literal(rt.get(r["paper_id"], "UNKNOWN"))))
    for r in con.execute("SELECT section_record_id, paper_id, text_hash_sha256 FROM section"):
        s = N["MCDMS"][safe(r[0])]
        g.add((s, RDF.type, PROV.Entity))
        g.add((s, DCTERMS.isPartOf, N["MCDMP"][r[1]]))
        g.add((s, M.textSha256, Literal(r[2])))
    # runs + software agents
    agents = {}

    def agent(name: str, person=False):
        if name not in agents:
            a = N["MCDMAG"][safe(name)]
            g.add((a, RDF.type, PROV.Agent))
            g.add((a, RDF.type, PROV.Person if person else PROV.SoftwareAgent))
            g.add((a, RDFS.label, Literal(name)))
            agents[name] = a
        return agents[name]
    for r in con.execute("SELECT * FROM extraction_run"):
        a = N["MCDMRUN"][safe(r["extraction_run_id"])]
        g.add((a, RDF.type, PROV.Activity))
        g.add((a, RDFS.label, Literal(r["stage"] or r["extraction_run_id"])))
        if r["model"]:
            g.add((a, PROV.wasAssociatedWith, agent(r["model_name_version"] or r["model"])))
        if r["completed_at"] and ISO.match(r["completed_at"]):
            g.add((a, PROV.endedAtTime, Literal(r["completed_at"].rstrip("Z") + "Z", datatype=XSD.dateTime)))
        if r["prompt_version"]:
            g.add((a, M.promptVersion, Literal(r["prompt_version"])))
        if r["source_artifact"]:
            e = BNode()
            g.add((e, RDF.type, PROV.Entity))
            g.add((e, RDFS.label, Literal(r["source_artifact"])))
            if r["source_artifact_sha256"]:
                g.add((e, M.sha256, Literal(r["source_artifact_sha256"])))
            g.add((a, PROV.used, e))
    for r in con.execute("SELECT parent_id, child_id, relation FROM processing_lineage"):
        g.add((N["MCDMRUN"][safe(r[1])], PROV.wasInformedBy, N["MCDMRUN"][safe(r[0])]))

    terms_needed = set()
    # accepted mappings
    n_map = 0
    for r in con.execute("""SELECT m.mapping_row_id, m.term_id, m.concept_id, m.relation_llm_g9, m.relation_deepseek,
                                   m.g9_run_id, m.deepseek_run_id, c.concept_label
                            FROM term_concept_map m JOIN concept c USING(concept_id)
                            WHERE m.mapping_disposition_reviewed='ACCEPTED'"""):
        if r["relation_llm_g9"] != r["relation_deepseek"]:
            continue
        t, c = N["MCDMT"][r["term_id"]], iri_of(r["concept_id"])
        terms_needed.add(r["term_id"])
        g.add((t, PRED[r["relation_llm_g9"]], c))
        if r["concept_label"]:
            g.add((c, RDFS.label, Literal(r["concept_label"])))
        m = N["MCDMM"][r["mapping_row_id"]]
        g.add((m, RDF.type, PROV.Entity))
        g.add((m, RDF.type, M.MappingRecord))
        g.add((m, M.mappingSubject, t))
        g.add((m, M.mappingObject, c))
        g.add((m, M.mappingPredicate, PRED[r["relation_llm_g9"]]))
        g.add((m, M.justification, URIRef("https://w3id.org/semapv/vocab/CompositeMatching")))
        for run in (r["g9_run_id"], r["deepseek_run_id"]):
            if run:
                g.add((m, PROV.wasGeneratedBy, N["MCDMRUN"][safe(run)]))
        n_map += 1
    # triples
    tier = {r["canonical_triple_id"]: r for r in con.execute("SELECT canonical_triple_id, relation, direction "
                                                             "FROM triple_tier")}
    ev = defaultdict(list)
    for r in con.execute("SELECT * FROM relation_evidence WHERE relation_table='relation'"):
        ev[r["canonical_triple_id"]].append(r)
    n_st = n_ev = n_ev_text = 0
    for r in con.execute("SELECT * FROM relation"):
        tt = tier[r["canonical_triple_id"]]
        pred, lvl, why, extra = CM.BIOLINK_PRED[tt["relation"]]
        if not pred:
            continue

        def end(side):
            tid = r[f"{side}_term_id"]
            if tid:
                terms_needed.add(tid)
                return N["MCDMT"][tid]
            e = N["MCDME"][r[f"{side}_entity_id"]]
            lab = red.clean(r[f"{side}_normalized_label"])
            if lab:
                g.add((e, RDFS.label, Literal(lab)))
            return e
        s, o = end("subject"), end("object")
        if tt["direction"] == "REVERSED":
            s, o = o, s
        if extra.get("reverse"):
            s, o = o, s
        st = N["MCDMR"][r["canonical_triple_id"]]
        g.add((st, RDF.type, RDF.Statement))
        g.add((st, RDF.type, PROV.Entity))
        g.add((st, RDF.subject, s))
        g.add((st, RDF.predicate, BL[pred.split(":", 1)[1]]))
        g.add((st, RDF.object, o))
        g.add((st, M.cdmRelation, Literal(tt["relation"])))
        g.add((st, M.cdmRelationOriginal, Literal(r["relation_normalized"])))
        g.add((st, PROV.wasGeneratedBy, N["MCDMRUN"][safe(r["extraction_run_id"])]))
        papers = json.loads(r["paper_ids"]) if (r["paper_ids"] or "").startswith("[") else []
        for p in papers:
            g.add((st, PROV.hadPrimarySource, N["MCDMP"][p]))
        for e in ev.get(r["canonical_triple_id"], []):
            en = N["MCDMEV"][e["triple_mention_id"]]
            g.add((en, RDF.type, PROV.Entity))
            g.add((en, RDF.type, M.TextAnchor))
            g.add((en, PROV.wasDerivedFrom, N["MCDMS"][safe(e["section_record_id"])]))
            g.add((en, M.charStart, Literal(int(e["char_start"]))))
            g.add((en, M.charEnd, Literal(int(e["char_end"]))))
            g.add((en, M.anchorStatus, Literal(e["anchor_status"])))
            g.add((en, M.sentenceSha256, Literal(sha(e["source_sentence"]))))
            if e["section_text_sha256"]:
                g.add((en, M.sectionTextSha256, Literal(e["section_text_sha256"])))
            if text_allowed(rt, e["paper_id"]) and e["source_sentence"]:
                g.add((en, RDF.value, Literal(e["source_sentence"])))
                n_ev_text += 1
            g.add((st, PROV.wasDerivedFrom, en))
            n_ev += 1
        n_st += 1
    for r in con.execute("SELECT term_id, term, cdm_type FROM canonical_term"):
        if r["term_id"] in terms_needed:
            t = N["MCDMT"][r["term_id"]]
            g.add((t, RDF.type, SKOS.Concept))
            g.add((t, M.cdmType, Literal(r["cdm_type"])))
            g.add((t, M.biolinkCategory, BL[CM.BIOLINK_CDM_TYPE[r["cdm_type"]][0].split(":", 1)[1]]))
            lab = red.clean(r["term"])
            if lab:
                g.add((t, SKOS.prefLabel, Literal(lab)))
    # human reviews
    n_hr = 0
    for r in con.execute("SELECT * FROM human_review"):
        act = N["MCDMHR"][r["review_id"] + "_activity"]
        ver = N["MCDMHR"][r["review_id"]]
        who = agent(r["reviewer"], person=True)
        tgt = N["MCDMM"][r["target_id"]] if r["target_entity"] == "term_concept_map" else N["MCDMR"][r["target_id"]]
        g.add((act, RDF.type, PROV.Activity))
        g.add((act, PROV.used, tgt))
        g.add((act, PROV.wasAssociatedWith, who))
        g.add((act, M.protocol, N["MCDMHR"][r["protocol_id"]]))
        if r["review_date"]:
            g.add((act, PROV.endedAtTime, Literal(r["review_date"] + "T00:00:00Z", datatype=XSD.dateTime)))
        g.add((ver, RDF.type, PROV.Entity))
        g.add((ver, RDF.type, M.HumanVerdict))
        g.add((ver, PROV.wasGeneratedBy, act))
        g.add((ver, PROV.wasAttributedTo, who))
        g.add((ver, M.verdictsJson, Literal(r["verdicts_json"])))
        if r["decision"]:
            g.add((ver, M.decision, Literal(r["decision"])))
        g.add((ver, M.reviewKind, Literal(r["review_kind"])))
        n_hr += 1
    for r in con.execute("SELECT protocol_id, title, preregistration_sha256, protocol_sha256 FROM "
                         "human_review_protocol"):
        p = N["MCDMHR"][r[0]]
        g.add((p, RDF.type, PROV.Plan))
        g.add((p, RDFS.label, Literal(r[1])))
        g.add((p, M.preregistrationSha256, Literal(r[2])))
        g.add((p, M.protocolSha256, Literal(r[3])))
    ttl = out / "cdm_3.2.0-candidate.ttl"
    g.serialize(destination=str(ttl), format="turtle")
    with open(ttl, "rb") as fi, gzip.open(str(ttl) + ".gz", "wb") as fo:
        shutil.copyfileobj(fi, fo)
    stats = {"triples_rdf": len(g), "statements_canonical_triples": n_st, "evidence_anchors": n_ev,
             "evidence_anchors_with_text": n_ev_text, "evidence_anchors_offsets_only": n_ev - n_ev_text,
             "mapping_records": n_map, "canonical_terms": len(terms_needed), "human_review_records": n_hr,
             "agents": len(agents), "labels_blanked_R2_R4": red.blanked, "ttl_bytes": ttl.stat().st_size}
    (out / "rdf_export_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
