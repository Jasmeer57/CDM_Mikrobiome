"""Terminology and knowledge-triple assessment of CDM 3.0.3 against external references (read-only).

Terminology: canonical-term grounding by CDM type in reference vocabularies (NCBI Taxonomy, NCBI Gene,
CTD/MeSH diseases + Mondo + HPO, CTD/MeSH chemicals), the generic-ENTITY investigation (which reference, if any,
an ENTITY term resolves in — reported as a PROPOSAL, nothing is retyped), mapping candidates vs accepted
mappings (label agreement, service, relation), definition provenance.
Triples: subject/object grounding by triple domain, KG support (CTD curated, Disbiome), polarity conflicts,
generic relations, sentence evidence. KG absence is reported as UNSUPPORTED_BY_KG, never as wrong.

    python term_triple_validation.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))
import corpus_bench as CB  # noqa: E402  (same lexicons, KGs and matching rules as the corpus benchmark)

CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "paper/publication/final_validation/term_triple"
TYPE_LEX = {"ORGANISM": "OrganismTaxon", "DISEASE": "DiseaseOrPhenotypicFeature", "CHEMICAL": "ChemicalEntity",
            "PROTEIN": "GeneOrGeneProduct", "DNA_RNA": "GeneOrGeneProduct"}
DOMAIN_LEX = {"microorganism_taxon": "OrganismTaxon", "disease_phenotype": "DiseaseOrPhenotypicFeature",
              "gene_protein_product": "GeneOrGeneProduct", "drug_intervention": "ChemicalEntity"}


def main():
    lex, gcase, kg = CB.build_lexicon(None)
    par = CB.taxon_parents()

    def ground(t, s):
        s = (s or "").strip()
        if t == "GeneOrGeneProduct" and (len(s) <= 3 or (len(s) <= 5 and s.isalpha())):
            return set(gcase.get(s, []))
        ids = set()
        for v in CB.variants(s):
            ids |= lex[t].get(v, set())
        return ids

    def lift(tid, seen=0):
        out, cur = {tid}, tid
        while cur in par and seen < 30:
            nxt, rank = par[cur]
            if nxt == cur:
                break
            out.add(nxt)
            if rank in ("genus", "family"):
                break
            cur, seen = nxt, seen + 1
        return out

    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    R = {}
    # ── terminology ──
    by_type = defaultdict(Counter)
    entity_res = Counter()
    nm = dict(c.execute("SELECT canonical_term_id, COUNT(*) FROM term_mention WHERE canonical_term_id IS NOT NULL GROUP BY 1").fetchall())
    for tid, term, ty, linked in c.execute("SELECT term_id, term, cdm_type, has_linked_mention FROM canonical_term"):
        by_type[ty]["terms"] += 1
        by_type[ty]["mentions"] += nm.get(tid, 0)
        by_type[ty]["with_linked_mention"] += linked or 0
        if ty in TYPE_LEX:
            g = ground(TYPE_LEX[ty], term)
            by_type[ty]["grounded_same_type"] += bool(g)
            by_type[ty]["mentions_of_grounded_terms"] += nm.get(tid, 0) if g else 0
            if not g:
                other = [t for t in lex if t != TYPE_LEX[ty] and ground(t, term)]
                by_type[ty]["grounded_other_type_only"] += bool(other)
        elif ty == "ENTITY":
            hits = [t for t in lex if ground(t, term)]
            entity_res[hits[0] if len(hits) == 1 else ("MULTIPLE" if hits else "NONE")] += 1
    R["terms_by_type"] = {k: dict(v) for k, v in sorted(by_type.items(), key=lambda x: -x[1]["terms"])}
    R["entity_terms_resolution_proposal"] = dict(entity_res)
    m = Counter()
    lab = Counter()
    for disp, svc, rel, term, clabel in c.execute(
            "SELECT COALESCE(m.mapping_disposition_reviewed,'NOT_REVIEWED'), COALESCE(m.source_service_mapping,'(none)'), "
            "COALESCE(m.relation_deepseek, m.relation_llm_g9, '(none)'), t.term, k.concept_label FROM term_concept_map m "
            "LEFT JOIN canonical_term t ON t.term_id = m.term_id LEFT JOIN concept k ON k.concept_id = m.concept_id "
            "WHERE m.guard_status='kept'"):
        m[(disp, svc)] += 1
        same = term is not None and clabel is not None and CB.norm(term) == CB.norm(clabel)
        lab[(disp, "LABEL_EQUALS_TERM" if same else ("NO_CONCEPT_LABEL" if clabel is None else "LABEL_DIFFERS"))] += 1
    R["mappings_kept_by_disposition_service"] = {f"{a}|{b}": n for (a, b), n in sorted(m.items())}
    R["mappings_label_agreement"] = {f"{a}|{b}": n for (a, b), n in sorted(lab.items())}
    R["definitions_anchor"] = dict(c.execute("SELECT evidence_anchor_status, COUNT(*) FROM term_definition GROUP BY 1").fetchall())
    R["definitions_source"] = dict(c.execute("SELECT extraction_run_id, COUNT(*) FROM term_definition GROUP BY 1").fetchall())
    # ── triples ──
    tr = Counter()
    pairs = Counter()
    rows = c.execute("SELECT canonical_triple_id, subject_display_label, subject_entity_type, object_display_label, "
                     "object_entity_type, relation_family, polarity_agreement FROM relation").fetchall()
    for cid, sl, st, ol, ot, fam, pol in rows:
        tr["triples"] += 1
        tr["generic_relation_escape"] += fam == "escape"
        tr["polarity_conflicting"] += pol == "conflicting"
        gs = ground(DOMAIN_LEX[st], sl) if st in DOMAIN_LEX else None
        go = ground(DOMAIN_LEX[ot], ol) if ot in DOMAIN_LEX else None
        tr["subject_groundable_domain"] += gs is not None
        tr["subject_grounded"] += bool(gs)
        tr["object_groundable_domain"] += go is not None
        tr["object_grounded"] += bool(go)
        kind = {frozenset(("microorganism_taxon", "disease_phenotype")): "microbe_disease",
                frozenset(("gene_protein_product", "disease_phenotype")): "gene_disease",
                frozenset(("drug_intervention", "disease_phenotype")): "chem_disease",
                frozenset(("drug_intervention", "gene_protein_product")): "chem_gene"}.get(frozenset((st, ot)))
        if not kind:
            pairs[("OTHER_DOMAINS", "UNASSESSED")] += 1
            continue
        a, b = (gs, go) if st in ("microorganism_taxon", "gene_protein_product") or (kind == "chem_disease" and st == "drug_intervention") or (kind == "chem_gene" and st == "drug_intervention") else (go, gs)
        if kind == "microbe_disease" and st == "disease_phenotype":
            a, b = go, gs
        if not a or not b:
            pairs[(kind, "NOT_BOTH_GROUNDED")] += 1
            continue
        if kind == "microbe_disease":
            a = set().union(*(lift(i) for i in a))
        hit = any((x, y) in kg[kind] for x in a for y in b)
        pairs[(kind, "SUPPORTED_BY_KG" if hit else "UNSUPPORTED_BY_KG")] += 1
    R["triples"] = dict(tr)
    R["triple_kg_support"] = {f"{a}|{b}": n for (a, b), n in sorted(pairs.items())}
    R["triple_sentence_evidence"] = dict(c.execute("SELECT anchor_status, COUNT(*) FROM relation_evidence "
                                                   "WHERE relation_table='relation' GROUP BY 1").fetchall())
    R["triple_relation_families"] = dict(c.execute("SELECT relation_family, COUNT(*) FROM relation GROUP BY 1 ORDER BY 2 DESC").fetchall())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "term_triple_summary.json").write_text(json.dumps(R, indent=1) + "\n")
    print(json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
