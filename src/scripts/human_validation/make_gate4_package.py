"""Gate 4 human-validation package: a stratified 500-item sample drawn from the frozen releases.

Reads CDM 3.0.2 (which carries catalogue 3.1.1 and terminology 1.0.1) and the catalogue 3.1.1 removed-record
file; writes only to --out. No model judgement is copied into an annotation column: annotation columns are
empty. Each item records its stratum, the stratum's population size N_h, sample size n_h, inclusion
probability n_h / N_h and design weight N_h / n_h.

    python make_gate4_package.py [--seed 20261102] [--out outputs/human_validation/gate4_2026-11-02]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.2/microbiome_cdm_v3.db"
CAT = ROOT / "releases/data_catalogue_v3/3.1.1"
TRIPLE_MENTIONS = ROOT / "pipelines/corpus_v2/data/triple_mentions.jsonl"
RELEASES = {"cdm": "releases/cdm_v3/3.0.2", "catalogue": "releases/data_catalogue_v3/3.1.1",
            "terminology": "releases/terminology/1.0.1", "corpus": "pipelines/corpus_v2/data (453 papers)"}
CONTEXT = 400            # characters of source text shown on each side of an evidence span
OVERLAP = 0.40           # share of items, per stratum, annotated independently by both annotators
MISSING = ("NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING")

TABLES = {  # CDM table -> (catalogue entity, id column, label column, content fields shown to annotators)
    "claim": ("findings", "finding_id", "finding_text",
              ["finding_text", "taxon_or_feature", "taxonomic_rank", "direction", "outcome", "comparison_or_exposure",
               "population_subgroup", "body_site", "effect_measure", "effect_estimate", "p_value", "q_value",
               "confidence_interval", "is_primary_finding", "cites_other_work", "finding_domain",
               "intervention_category", "intervention_agent", "author_interpretation", "cohort_id", "assay_id",
               "dataset_id"]),
    "assay": ("assays", "assay_id", "assay_type",
              ["assay_type", "target_gene_or_region", "sequencing_platform", "library_preparation",
               "dna_extraction_method", "primer_or_probe", "negative_controls", "positive_controls",
               "contamination_handling", "quality_control", "bioinformatics_pipeline", "software_tools",
               "taxonomic_database", "functional_database", "normalization_method", "statistical_methods", "dataset_id"]),
    "sample": ("samples", "sample_group_id", "body_site",
               ["body_site", "sample_type", "collection_method", "collection_timepoint", "storage_condition",
                "preservation_method", "sample_count", "sample_processing", "cohort_id", "dataset_id"]),
    "cohort": ("cohorts", "cohort_id", "cohort_label",
               ["cohort_label", "cohort_role", "population_description", "country_or_region", "setting",
                "recruitment_method", "participant_count", "sample_count", "age_group", "age_summary",
                "sex_or_gender_reporting", "health_status", "inclusion_criteria", "exclusion_criteria",
                "key_covariates", "longitudinal", "timepoints", "dataset_id"]),
    "dataset": ("datasets", "dataset_id", "dataset_title",
                ["dataset_title", "dataset_description", "dataset_role", "dataset_type", "repository_name",
                 "repository_accession", "accession_type", "dataset_url", "data_availability_status",
                 "access_conditions", "license_or_terms", "original_or_reused", "related_publication_dois"]),
    "data_asset": ("data_assets", "asset_id", "asset_name",
                   ["asset_name", "asset_type", "format", "description", "repository_url", "accession",
                    "file_size_bytes", "access_status", "license_or_terms", "dataset_id"]),
}
CAT_ALLOC = {"claim": 54, "assay": 27, "sample": 27, "cohort": 27, "dataset": 27, "data_asset": 18}  # + 20 removed
CELL_SHARE = {("VERBATIM", "SPECIAL"): .35, ("VERBATIM", "PLAIN"): .25, ("FUZZY", "SPECIAL"): .10,
              ("FUZZY", "PLAIN"): .10, ("UNANCHORED", "SPECIAL"): .10, ("UNANCHORED", "PLAIN"): .10}
TERM_ALLOC = {"T1_ENTITY_TYPED": 50, "T2_TYPED_MAPPING_ACCEPTED": 30, "T3_TYPED_MAPPING_NOT_ACCEPTED": 30,
              "T4_TYPED_NO_MAPPING": 20, "T5_NO_CANONICAL_TERM": 25, "T6_AMBIGUOUS_LINK": 15, "T7_TERM_WITH_DEFINITION": 30}
TRIPLE_ALLOC = {"R1_KEPT_SPECIFIC_RELATION": 50, "R2_KEPT_OTHER_RELATION": 30, "R3_REMOVED_BY_REVIEW": 20}


def jl(p):
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def loads(v):
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def allocate(n, shares, sizes):
    """Largest-remainder allocation of n over cells, capped at each cell's population; excess re-spread."""
    alloc = {k: 0 for k in shares}
    left = n
    active = {k for k in shares if sizes.get(k, 0) > 0}
    while left > 0 and active:
        tot = sum(shares[k] for k in active)
        raw = {k: left * shares[k] / tot for k in active}
        base = {k: int(v) for k, v in raw.items()}
        rem = left - sum(base.values())
        for k in sorted(active, key=lambda k: (-(raw[k] - base[k]), k))[:rem]:   # ties by name: no set-order dependence
            base[k] += 1
        for k in sorted(active):
            alloc[k] += base[k]
        over = {k: alloc[k] - sizes[k] for k in active if alloc[k] > sizes[k]}
        for k, o in over.items():
            alloc[k] = sizes[k]
        left = sum(over.values())
        active = {k for k in active if alloc[k] < sizes[k]}
    return alloc


class Pkg:
    def __init__(self, seed, out):
        self.rnd = random.Random(seed)
        self.seed = seed
        self.out = Path(out)
        self.c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
        self.c.row_factory = sqlite3.Row
        self.sec = {}
        self.sec_rec = {}
        for r in self.c.execute("SELECT section_record_id, paper_id, section_id_original, section_name_original, "
                                "section_text_original FROM section"):
            self.sec[(r["paper_id"], r["section_id_original"])] = r
            self.sec_rec[r["section_record_id"]] = r
        self.papers = {r["paper_id"]: dict(r) for r in self.c.execute(
            "SELECT paper_id, title, doi, pmcid, pmid, bioproject, license_name, full_text_url FROM paper")}
        self.strata = []          # stratum audit rows
        self.items = []           # (sheet, item_id, paper_id, section ...) for the source index
        self.paper_use = Counter()

    def pick(self, sheet, name, population, n):
        n = min(n, len(population))
        chosen = self.rnd.sample(population, n) if n else []
        k = round(OVERLAP * n)
        dbl = set(self.rnd.sample(range(n), k)) if n else set()
        self.strata.append({"sheet": sheet, "stratum": name, "population_N": len(population), "sample_n": n,
                            "inclusion_probability": round(n / len(population), 8) if population else 0,
                            "design_weight": round(len(population) / n, 4) if n else 0, "double_annotated": k})
        return [(x, i in dbl, len(population), n) for i, x in enumerate(chosen)]

    def context(self, paper_id, section_id, a, b):
        s = self.sec.get((paper_id, section_id)) or self.sec_rec.get(section_id)
        if s is None:
            return "", "", ""
        if a in (None, "") or b in (None, ""):        # no located span: annotators open the section itself
            return "", s["section_name_original"] or "", s["section_record_id"]
        t = s["section_text_original"] or ""
        a, b = int(a), int(b)
        lo, hi = max(0, a - CONTEXT), min(len(t), b + CONTEXT)
        return (("…" if lo else "") + t[lo:a] + " ⟦" + t[a:b] + "⟧ " + t[b:hi] + ("…" if hi < len(t) else ""),
                s["section_name_original"] or "", s["section_record_id"])

    def src(self, paper_id):
        p = self.papers.get(paper_id, {})
        return {"paper_id": paper_id, "paper_title": p.get("title", ""), "doi": p.get("doi", ""),
                "pmcid": p.get("pmcid", ""), "local_markdown": f"data/segmented_sections_markdown/{paper_id}.md",
                "local_text": f"data/papers_txt/{p.get('bioproject')}.txt" if p.get("bioproject") else ""}

    def ref(self, sheet, item_id, paper_id, section_record_id, a, b):
        self.items.append({"sheet": sheet, "item_id": item_id, "paper_id": paper_id,
                           "section_record_id": section_record_id, "char_start": a, "char_end": b})
        self.paper_use[paper_id] += 1

    # ── catalogue ────────────────────────────────────────────────────────────
    def catalogue(self):
        rows, n_item = [], 0
        label = {}
        for t, (_, idc, lab, _) in TABLES.items():
            w = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
            for r in self.c.execute(f'SELECT "{idc}", "{lab}" FROM "{t}"{w}'):
                label[r[0]] = (t, (r[1] or "")[:120])
        cat_ids = {(r["entity_type"], r["fields"][TABLES[t][1]])
                   for r in jl(CAT / "records/catalogue_records.jsonl")
                   for t in TABLES if TABLES[t][0] == r["entity_type"]}
        for t, (ent, idc, lab, fields) in TABLES.items():
            w = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
            recs = [dict(r) for r in self.c.execute(f'SELECT * FROM "{t}"{w}')]
            cells = defaultdict(list)
            for r in recs:
                st = r.get("evidence_anchor_status") or "NO_EVIDENCE"
                grp = ("VERBATIM" if st in ("EXACT", "WHITESPACE", "RELOCATED", "NORMALISED") else
                       "FUZZY" if st == "FUZZY" else "UNANCHORED")
                fs = loads(r.get("field_sources")) or {}
                special = (any(r.get(f) in MISSING for f in fields) or
                           any(str(v).startswith(("G1", "G3")) for v in (fs.values() if isinstance(fs, dict) else [])) or
                           any(";" in str(r.get(f) or "") for f in ("cohort_id", "assay_id", "dataset_id")))
                cells[(grp, "SPECIAL" if special else "PLAIN")].append(r)
            alloc = allocate(CAT_ALLOC[t], CELL_SHARE, {k: len(v) for k, v in cells.items()})
            for cell in CELL_SHARE:
                for r, dbl, N, n in self.pick("catalogue", f"C_{ent}_{cell[0]}_{cell[1]}", cells.get(cell, []), alloc[cell]):
                    rid = r[idc]
                    assert (ent, rid) in cat_ids, f"{rid} not in catalogue 3.1.1"
                    n_item += 1
                    rows += self.cat_rows(f"CAT-{n_item:03d}", t, ent, rid, r, fields, label, dbl, N, n,
                                          f"C_{ent}_{cell[0]}_{cell[1]}")
        # removed records: was the removal correct?
        removed = [r for r in jl(CAT / "provenance/_removed.jsonl")
                   if str(r["fields"].get("v3_status", "")).startswith("REMOVED:G3_")]
        for r, dbl, N, n in self.pick("catalogue", "C_REMOVED_BY_G3", removed, 20):
            n_item += 1
            f = dict(r["fields"])
            ent = r["entity_type"]
            t = next(k for k, v in TABLES.items() if v[0] == ent)
            f.update(section_id=r.get("section_id"), char_start=r.get("char_start"), char_end=r.get("char_end"),
                     evidence_span_start=r.get("char_start"), evidence_span_end=r.get("char_end"),
                     evidence_anchor_status="AS_EXTRACTED")
            rows += self.cat_rows(f"CAT-{n_item:03d}", t, ent, f[TABLES[t][1]], f, TABLES[t][3], label, dbl, N, n,
                                  "C_REMOVED_BY_G3", removed=f.get("v3_status"))
        return rows, n_item

    def cat_rows(self, item, t, ent, rid, r, fields, label, dbl, N, n, stratum, removed=None):
        pid = r.get("paper_id")
        located = r.get("evidence_span_start") is not None
        a = r.get("evidence_span_start") if located else r.get("char_start")
        b = r.get("evidence_span_end") if located else r.get("char_end")
        ctx, sname, srec = self.context(pid, r.get("section_id"), a, b)
        self.ref("catalogue", item, pid, srec, a, b)
        fs = loads(r.get("field_sources")) or {}
        ge = loads(r.get("gap_evidence")) or {}
        base = {"item_id": item, "stratum": stratum, "population_N": N, "sample_n": n,
                "inclusion_probability": round(n / N, 8), "design_weight": round(N / n, 4),
                "double_annotate": "YES" if dbl else "NO", "table": ent, "record_id": rid,
                "release": RELEASES["catalogue"] + (" provenance/_removed.jsonl" if removed else ""),
                **self.src(pid), "section_record_id": srec, "section_name": sname, "evidence_char_start": a,
                "evidence_char_end": b, "evidence_anchor_status": r.get("evidence_anchor_status") or "",
                "offsets_from": "located quote" if located else ("stored extraction offsets" if a is not None else "none"),
                "stored_quote": str(r.get("evidence_text") or "")[:1500], "evidence_context_marked": ctx}
        out = [{**base, "row_type": "RECORD", "field": "", "extracted_value": label.get(rid, ("", ""))[1] or str(r.get(TABLES[t][2]) or "")[:200],
                "value_source": "", "field_quote": "",
                "question": (f"This record was REMOVED by the pipeline ({removed}). Was removing it correct, i.e. is it NOT a "
                             f"genuine {ent[:-1]} record reported by this paper?" if removed else
                             f"Is this a genuine {ent[:-1]} record reported by this paper (not cited work, methods text, "
                             f"a table/figure fragment or a reagent)? Then list any important values that are missing.")}]
        for f in fields:
            v = r.get(f)
            if v in (None, "", "[]", "{}"):
                continue
            q = ("The value is a missing-data code. Search the whole paper: is the information genuinely absent "
                 "(NOT_REPORTED) or genuinely contradictory (CONFLICTING)?" if v in MISSING else
                 "Is this value correct for this record, and is it supported by the evidence passage or the quote?")
            if f in ("cohort_id", "assay_id", "dataset_id"):
                v = "; ".join(f"{x.strip()} [{label.get(x.strip(), ('', '?'))[1]}]" for x in str(v).split(";"))
                q = "Does this record really belong to the linked record(s) shown?"
            out.append({**base, "row_type": "MISSING_CODE" if r.get(f) in MISSING else ("LINK" if f.endswith("_id") else "FIELD"),
                        "field": f, "extracted_value": str(v)[:600],
                        "value_source": (fs.get(f, "") if isinstance(fs, dict) else ""),
                        "field_quote": (str(ge.get(f, ""))[:600] if isinstance(ge, dict) else ""), "question": q})
        return out

    # ── terminology ──────────────────────────────────────────────────────────
    def terminology(self):
        c = self.c
        acc = {r[0] for r in c.execute("SELECT DISTINCT term_id FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'")}
        kept = {r[0] for r in c.execute("SELECT DISTINCT term_id FROM term_concept_map WHERE guard_status='kept' AND concept_id IS NOT NULL")}
        defs = {r[0] for r in c.execute("SELECT DISTINCT term_id FROM term_definition WHERE term_status=''")}
        ttype = dict(c.execute("SELECT term_id, cdm_type FROM canonical_term"))
        pops = defaultdict(list)
        q = ("SELECT rowid, canonical_term_id, term_link_status FROM term_mention "
             "WHERE start_offset IS NOT NULL AND (canonical_term_status = '' OR canonical_term_status IS NULL)")
        for rowid, tid, ls in c.execute(q):
            if ls == "NO_CANONICAL_TERM":
                pops["T5_NO_CANONICAL_TERM"].append(rowid)
            elif ls == "AMBIGUOUS":
                pops["T6_AMBIGUOUS_LINK"].append(rowid)
            elif tid in ttype:
                if tid in defs:
                    pops["T7_TERM_WITH_DEFINITION"].append(rowid)
                elif ttype[tid] == "ENTITY":
                    pops["T1_ENTITY_TYPED"].append(rowid)
                elif tid in acc:
                    pops["T2_TYPED_MAPPING_ACCEPTED"].append(rowid)
                elif tid in kept:
                    pops["T3_TYPED_MAPPING_NOT_ACCEPTED"].append(rowid)
                else:
                    pops["T4_TYPED_NO_MAPPING"].append(rowid)
        rows, n_item = [], 0
        for name, n in TERM_ALLOC.items():
            for rowid, dbl, N, nn in self.pick("terminology", name, pops[name], n):
                m = dict(c.execute("SELECT * FROM term_mention WHERE rowid=?", (rowid,)).fetchone())
                n_item += 1
                item = f"TERM-{n_item:03d}"
                tid = m.get("canonical_term_id")
                t = dict(c.execute("SELECT term, cdm_type FROM canonical_term WHERE term_id=?", (tid,)).fetchone() or {}) if tid else {}
                mp = c.execute("SELECT concept_id, mapping_relation, mapping_disposition_reviewed, relation_deepseek "
                               "FROM term_concept_map WHERE term_id=? AND concept_id IS NOT NULL AND guard_status='kept' "
                               "ORDER BY (mapping_disposition_reviewed='ACCEPTED') DESC, is_canonical_candidate DESC, "
                               "candidate_rank LIMIT 1", (tid,)).fetchone() if tid else None
                con = dict(c.execute("SELECT concept_label, ontology_name, source_service FROM concept WHERE concept_id=?",
                                     (mp["concept_id"],)).fetchone() or {}) if mp else {}
                d = c.execute("SELECT definition_text, paper_id, section_id, evidence_span_start, evidence_span_end "
                              "FROM term_definition WHERE term_id=? AND term_status='' ORDER BY (paper_id=?) DESC LIMIT 1",
                              (tid, m["paper_id"])).fetchone() if tid else None
                ctx, sname, srec = self.context(m["paper_id"], m["section_id"], m["start_offset"], m["end_offset"])
                self.ref("terminology", item, m["paper_id"], srec, m["start_offset"], m["end_offset"])
                dctx = ""
                if d:
                    dctx, _, dsrec = self.context(d["paper_id"], d["section_id"], d["evidence_span_start"], d["evidence_span_end"])
                    self.ref("terminology_definition", item, d["paper_id"], dsrec, d["evidence_span_start"], d["evidence_span_end"])
                rows.append({"item_id": item, "stratum": name, "population_N": N, "sample_n": nn,
                             "inclusion_probability": round(nn / N, 10), "design_weight": round(N / nn, 2),
                             "double_annotate": "YES" if dbl else "NO", "release": RELEASES["cdm"] + " term_mention",
                             "mention_row_id": m["mention_row_id"], **self.src(m["paper_id"]), "section_record_id": srec,
                             "section_name": sname, "char_start": m["start_offset"], "char_end": m["end_offset"],
                             "surface_form": m["surface_form"], "mention_context_marked": ctx,
                             "extraction_model": m["extraction_model"], "extraction_method": m["extraction_method"],
                             "predicted_mention_type": m["entity_type"], "term_link_status": m["term_link_status"],
                             "canonical_term_id": tid or "", "canonical_term": t.get("term", ""),
                             "canonical_type": t.get("cdm_type", ""),
                             "mapped_concept_id": mp["concept_id"] if mp else "", "mapped_concept_label": con.get("concept_label", ""),
                             "mapped_ontology": con.get("ontology_name") or con.get("source_service") or "",
                             "mapping_relation": mp["mapping_relation"] if mp else "",
                             "definition_text": d["definition_text"] if d else "", "definition_paper_id": d["paper_id"] if d else "",
                             "definition_context_marked": dctx})
        return rows, n_item

    # ── triples ──────────────────────────────────────────────────────────────
    @staticmethod
    def tm_ids(v):
        v = loads(v)
        return [str(x).strip() for x in (v if isinstance(v, list) else str(v or "").split(",")) if str(x).strip()]

    def triples(self):
        c = self.c
        kept = [dict(r) for r in c.execute("SELECT * FROM relation")]
        rem = [dict(r) for r in c.execute("SELECT * FROM removed_relation")]
        pops = {"R1_KEPT_SPECIFIC_RELATION": [r for r in kept if r["relation_family"] != "escape"],
                "R2_KEPT_OTHER_RELATION": [r for r in kept if r["relation_family"] == "escape"],
                "R3_REMOVED_BY_REVIEW": rem}
        need = set()
        chosen = {}
        for name, n in TRIPLE_ALLOC.items():
            chosen[name] = self.pick("triples", name, pops[name], n)
            for r, *_ in chosen[name]:
                need |= set(self.tm_ids(r["triple_mention_ids"])[:3])
        tm = {m["triple_mention_id"]: m for m in jl(TRIPLE_MENTIONS) if m["triple_mention_id"] in need}
        rows, n_item = [], 0
        for name in TRIPLE_ALLOC:
            for r, dbl, N, n in chosen[name]:
                n_item += 1
                item = f"TRI-{n_item:03d}"
                ids = self.tm_ids(r["triple_mention_ids"])
                m = next((tm[i] for i in ids[:3] if i in tm), {})
                pid = m.get("paper_id") or (self.tm_ids(r["paper_ids"]) or [""])[0]
                self.ref("triples", item, pid, m.get("section_id", ""), None, None)
                rows.append({"item_id": item, "stratum": name, "population_N": N, "sample_n": n,
                             "inclusion_probability": round(n / N, 8), "design_weight": round(N / n, 4),
                             "double_annotate": "YES" if dbl else "NO",
                             "release": RELEASES["cdm"] + (" removed_relation" if name.startswith("R3") else " relation"),
                             "canonical_triple_id": r["canonical_triple_id"], "triple_mention_id": m.get("triple_mention_id", ""),
                             **self.src(pid), "section_record_id": m.get("section_id", ""), "section_name": m.get("section_name", ""),
                             "subject": r["subject_display_label"], "subject_type": r["subject_entity_type"],
                             "predicate": r["relation_normalized"], "predicate_family": r["relation_family"],
                             "object": r["object_display_label"], "object_type": r["object_entity_type"],
                             "stated_direction": m.get("relation_direction", ""), "stated_polarity": m.get("polarity", ""),
                             "relation_as_written": m.get("relation_mention", ""), "subject_as_written": m.get("subject_mention", ""),
                             "object_as_written": m.get("object_mention", ""), "source_sentence": m.get("source_sentence", ""),
                             "n_papers": r["paper_count"], "n_mentions": r["mention_count"],
                             "removal_reason": r.get("removal_reason", "") if name.startswith("R3") else ""})
        return rows, n_item


CAT_ANN = ["annotator_id", "decision", "evidence_supports", "corrected_value", "missing_important_values", "notes"]
TERM_ANN = ["annotator_id", "is_entity", "boundary_correct", "type_correct", "correct_type_if_wrong",
            "canonical_term_correct", "mapping_correct", "definition_supported", "notes"]
TRI_ANN = ["annotator_id", "subject_correct", "object_correct", "predicate_correct", "direction_correct",
           "explicitly_supported", "scientifically_meaningful", "overall", "notes"]


CTRL = {i: None for i in range(32) if i not in (9, 10, 13)}   # NUL etc. from PDF-derived text break CSV readers


def clean(v):
    return v.translate(CTRL) if isinstance(v, str) else v


def write_csv(path, rows, ann):
    keys = list(rows[0]) + ann
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: clean(v) for k, v in r.items()}, **{k: "" for k in ann}})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261102)
    ap.add_argument("--out", default=str(ROOT / "outputs/human_validation/gate4_2026-11-02"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists() and any(out.glob("*.csv")):
        raise SystemExit(f"{out} already holds sheets; refusing to overwrite a drawn sample")
    out.mkdir(parents=True, exist_ok=True)
    P = Pkg(a.seed, out)
    cat, n_cat = P.catalogue()
    term, n_term = P.terminology()
    tri, n_tri = P.triples()
    write_csv(out / "CATALOGUE_ANNOTATION_SHEET.csv", cat, CAT_ANN)
    write_csv(out / "TERMINOLOGY_ANNOTATION_SHEET.csv", term, TERM_ANN)
    write_csv(out / "TRIPLE_ANNOTATION_SHEET.csv", tri, TRI_ANN)
    with open(out / "ADJUDICATION_TEMPLATE.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet", "item_id", "row_key", "dimension", "annotator_A_decision", "annotator_B_decision",
                    "adjudicated_decision", "adjudicator_id", "rationale", "guideline_change_needed"])
    by_paper = defaultdict(lambda: {"items": [], "sections": set()})
    for it in P.items:
        b = by_paper[it["paper_id"]]
        b["items"].append(it["item_id"])
        if it["section_record_id"]:
            b["sections"].add(it["section_record_id"])
    with open(out / "SOURCE_REFERENCE_INDEX.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["paper_id", "title", "doi", "pmcid", "pmid", "bioproject", "license", "full_text_url",
                    "local_markdown", "local_text", "items", "section_record_ids"])
        for pid in sorted(by_paper):
            p = P.papers.get(pid, {})
            w.writerow([pid, clean(p.get("title")), p.get("doi"), p.get("pmcid"), p.get("pmid"), p.get("bioproject"),
                        p.get("license_name"), p.get("full_text_url"), f"data/segmented_sections_markdown/{pid}.md",
                        f"data/papers_txt/{p.get('bioproject')}.txt", ";".join(sorted(set(by_paper[pid]["items"]))),
                        ";".join(sorted(by_paper[pid]["sections"]))])
    (out / "_sampling_strata.json").write_text(json.dumps(
        {"seed": a.seed, "overlap_share": OVERLAP, "releases": RELEASES, "strata": P.strata,
         "items": {"catalogue": n_cat, "terminology": n_term, "triples": n_tri},
         "papers_referenced": len(by_paper), "max_items_per_paper": P.paper_use.most_common(1)[0][1]}, indent=1) + "\n")
    print(json.dumps({"catalogue_items": n_cat, "catalogue_rows": len(cat), "terminology_items": n_term,
                      "triple_items": n_tri, "papers": len(by_paper)}))


if __name__ == "__main__":
    raise SystemExit(main())
