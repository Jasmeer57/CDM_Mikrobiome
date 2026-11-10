#!/usr/bin/env python3
"""Write the deduplicated + relevance-filtered vocabulary as CSV and JSON(L).

Inputs (all read-only):
  CDM 3.0.3 db                                      terms, mappings, concept labels
  concept_dedup_2026-11-09/{stage_a,terms,concepts} exact/fuzzy/embedding dedup maps
  term_relevance_2026-11-09, concept_relevance_2026-11-09   FhGenie verdicts
  term_definitions_llm_2026-11-09/all              contextual definitions, full forms, synonyms
  ontology_definitions_2026-11-09                  ontology definitions + synonyms
Rule: an item is KEPT unless FhGenie judged it NOT_A_CONCEPT or IRRELEVANT (UNSURE is kept).

Output: outputs/results/clean_vocabulary_2026-11-10/
  terms_all.{csv,jsonl}            every canonical term, with verdict + kept flag
  terms_clean.{csv,jsonl}          kept canonical terms only
  term_id_map.{csv,json}           every original term_id -> canonical term_id, dedup pass, kept
  concepts_all.{csv,jsonl}         every canonical concept (CURIE), with verdict + kept flag
  concepts_clean.{csv,jsonl}       kept concepts only
  concept_id_map.{csv,json}        every accepted concept IRI -> canonical CURIE, kept
  term_concept_map_clean.{csv,jsonl}  accepted mappings remapped to canonical ids; dropped items removed
  summary.json
Frozen releases and the CDM are not changed. New labelled layer, pending lead approval (CHANGE_RECORD).
"""
import collections
import csv
import json
import sqlite3
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
R = ROOT / "outputs/results"
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = R / "clean_vocabulary_2026-11-10"
DROP = {"NOT_A_CONCEPT", "IRRELEVANT"}


def tsv(path):
    lines = open(path, encoding="utf-8").read().split("\n")
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:] if l]


def jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write(name, rows, cols, as_json_map=None):
    with open(OUT / f"{name}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("|".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()})
    if as_json_map:
        (OUT / f"{name}.json").write_text(json.dumps(as_json_map, ensure_ascii=False, indent=0))
    else:
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({k: r.get(k) for k in cols}, ensure_ascii=False) + "\n")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    # ---------------- concepts
    curie_rows = tsv(R / "concept_dedup_2026-11-09/stage_a/concept_curie_map.tsv")
    iri2curie = {r["concept_id"]: r["curie"] for r in curie_rows}
    accepted_iris = [r["concept_id"] for r in curie_rows if r["accepted"] == "1"]
    cdedup = {r["id"]: r for r in tsv(R / "concept_dedup_2026-11-09/concepts/dedup_map.tsv")}
    cverd = {r["id"]: r for r in jl(R / "concept_relevance_2026-11-09/judgements.jsonl")}
    onto = {}
    for r in jl(R / "ontology_definitions_2026-11-09/concept_ontology_info.jsonl"):
        onto.setdefault(iri2curie.get(r["concept_id"], r["concept_id"]), r)

    def canon_concept(iri):
        cu = iri2curie.get(iri, iri)
        return cdedup[cu]["canonical_id"] if cu in cdedup else cu

    members = collections.defaultdict(lambda: {"curies": set(), "iris": set()})
    for iri in accepted_iris:
        cc = canon_concept(iri)
        members[cc]["curies"].add(iri2curie.get(iri, iri))
        members[cc]["iris"].add(iri)
    concepts_all = []
    for cc, m in sorted(members.items()):
        v = cverd.get(cc, {})
        o = onto.get(cc, {})
        syn = set(o.get("synonyms") or [])
        for cu in m["curies"]:
            syn |= set((onto.get(cu) or {}).get("synonyms") or [])
        concepts_all.append({
            "concept_id": cc, "label": (cdedup.get(cc) or {}).get("canonical") or v.get("label", ""),
            "ontology": v.get("ontology", cc.split(":")[0]), "cdm_type": v.get("cdm_type", ""),
            "merged_curies": sorted(m["curies"]), "merged_iris": sorted(m["iris"]),
            "n_merged": len(m["curies"]), "ontologies": sorted({c.split(":")[0] for c in m["curies"]}),
            "definition": o.get("definition", ""), "definition_source": o.get("source", ""),
            "synonyms": sorted(syn)[:50], "verdict": v.get("verdict", "UNJUDGED"),
            "verdict_reason": v.get("reason", ""), "kept": v.get("verdict") not in DROP})
    kept_concepts = {c["concept_id"] for c in concepts_all if c["kept"]}
    ccols = ["concept_id", "label", "ontology", "cdm_type", "n_merged", "merged_curies", "ontologies",
             "merged_iris", "definition", "definition_source", "synonyms", "verdict", "verdict_reason", "kept"]
    write("concepts_all", concepts_all, ccols)
    write("concepts_clean", [c for c in concepts_all if c["kept"]], ccols)
    cmap = [{"concept_iri": iri, "curie": iri2curie.get(iri, iri), "canonical_concept_id": canon_concept(iri),
             "kept": canon_concept(iri) in kept_concepts} for iri in sorted(accepted_iris)]
    write("concept_id_map", cmap, ["concept_iri", "curie", "canonical_concept_id", "kept"],
          as_json_map={r["concept_iri"]: {"canonical_concept_id": r["canonical_concept_id"], "kept": r["kept"]} for r in cmap})

    # ---------------- terms
    tdedup = {r["id"]: r for r in tsv(R / "concept_dedup_2026-11-09/terms/dedup_map.tsv")}
    tverd = {r["id"]: r for r in jl(R / "term_relevance_2026-11-09/judgements.jsonl")}
    defs = {r["term_id"]: r for r in jl(R / "term_definitions_llm_2026-11-09/all/definitions.jsonl")}
    info = {r[0]: r for r in db.execute("""select term_id, term, cdm_type, coalesce(mention_count,0),
                                           coalesce(paper_count,0) from canonical_term""")}
    t2c = {t: c for t, c in db.execute(
        "select term_id, concept_id from term_concept_map where mapping_disposition_reviewed='ACCEPTED'")}
    groups = collections.defaultdict(list)
    for tid, r in tdedup.items():
        groups[r["canonical_id"]].append(tid)
    terms_all = []
    for ct, mem in sorted(groups.items()):
        v, d, i = tverd.get(ct, {}), defs.get(ct, {}), info[ct]
        if not v:  # cluster head changed after re-dedup: take the majority verdict of judged members (KEEP wins ties)
            vs = collections.Counter(tverd[m]["verdict"] for m in mem if m in tverd)
            if vs:
                top = max(vs.items(), key=lambda kv: (kv[1], kv[0] == "KEEP"))[0]
                v = {"verdict": top, "reason": "inherited from merged members"}
        variants = sorted({info[m][1] for m in mem if m != ct})
        cons = sorted({canon_concept(t2c[m]) for m in mem if m in t2c})
        syn = set(d.get("synonyms") or [])
        for m in mem:
            syn |= set((defs.get(m) or {}).get("synonyms") or [])
        terms_all.append({
            "term_id": ct, "term": i[1], "cdm_type": i[2],
            "mention_count": sum(info[m][3] for m in mem), "paper_count_max": max(info[m][4] for m in mem),
            "n_merged": len(mem), "merged_term_ids": sorted(m for m in mem if m != ct), "variants": variants,
            "dedup_passes": sorted({tdedup[m]["pass"] for m in mem if m != ct}),
            "concept_ids": cons, "definition": d.get("definition", ""), "definition_status": d.get("status", ""),
            "full_form": d.get("full_form", ""), "synonyms": sorted(syn)[:50],
            "verdict": v.get("verdict", "UNJUDGED"), "verdict_reason": v.get("reason", ""),
            "kept": v.get("verdict") not in DROP})
    kept_terms = {t["term_id"] for t in terms_all if t["kept"]}
    tcols = ["term_id", "term", "cdm_type", "mention_count", "paper_count_max", "n_merged", "variants",
             "merged_term_ids", "dedup_passes", "concept_ids", "definition", "definition_status", "full_form",
             "synonyms", "verdict", "verdict_reason", "kept"]
    write("terms_all", terms_all, tcols)
    write("terms_clean", [t for t in terms_all if t["kept"]], tcols)
    tmap = [{"term_id": tid, "term": info[tid][1], "canonical_term_id": r["canonical_id"],
             "dedup_pass": r["pass"], "kept": r["canonical_id"] in kept_terms} for tid, r in sorted(tdedup.items())]
    write("term_id_map", tmap, ["term_id", "term", "canonical_term_id", "dedup_pass", "kept"],
          as_json_map={r["term_id"]: {"canonical_term_id": r["canonical_term_id"], "dedup_pass": r["dedup_pass"],
                                      "kept": r["kept"]} for r in tmap})

    # ---------------- mappings
    tcanon = {r["term_id"]: r["canonical_term_id"] for r in tmap}
    seen, maps = set(), []
    for tid, cid, rel, svc in db.execute("""select term_id, concept_id, mapping_relation, source_service_mapping
                                            from term_concept_map where mapping_disposition_reviewed='ACCEPTED'"""):
        ct, cc = tcanon.get(tid, tid), canon_concept(cid)
        if ct not in kept_terms or cc not in kept_concepts or (ct, cc) in seen:
            continue
        seen.add((ct, cc))
        maps.append({"term_id": ct, "term": info[ct][1], "concept_id": cc, "mapping_relation": rel or "",
                     "source_service": svc or ""})
    write("term_concept_map_clean", maps, ["term_id", "term", "concept_id", "mapping_relation", "source_service"])

    vt = collections.Counter(t["verdict"] for t in terms_all)
    vc = collections.Counter(c["verdict"] for c in concepts_all)
    n_acc_rows = db.execute("select count(*) from term_concept_map where mapping_disposition_reviewed='ACCEPTED'").fetchone()[0]
    summary = {
        "what": "deduplicated + relevance-filtered vocabulary (CSV and JSON); frozen CDM 3.0.3 and releases unchanged",
        "rule": "kept unless FhGenie verdict is NOT_A_CONCEPT or IRRELEVANT (UNSURE kept)",
        "terms": {"original": len(info), "after_dedup": len(terms_all), "kept": len(kept_terms), "verdicts": dict(vt)},
        "concepts": {"accepted_iris": len(accepted_iris), "after_iri_normalisation": len({iri2curie.get(i, i) for i in accepted_iris}),
                     "after_dedup": len(concepts_all), "kept": len(kept_concepts), "verdicts": dict(vc)},
        "accepted_mappings": {"original_rows": n_acc_rows, "clean_rows": len(maps)},
        "files": sorted(p.name for p in OUT.iterdir() if p.suffix in (".csv", ".json", ".jsonl")),
        "note": "model-assisted dedup and relevance screen; not accuracy; new labelled layer pending lead approval (CHANGE_RECORD)",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
