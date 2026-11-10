"""Gate 4 CDM / catalogue validation, layers 1, 3 and 4 (automated, exhaustive, read-only).

Tests CDM 3.0.2 against its own design documents — the entity registry
(src/template/cdm/cdm_entity_registry.csv), the template's identifier scheme (§3), evidence / provenance
contract (§5) and traceability milestone (§8), and the relationship graph (docs/cdm_design/cdm_relationships.md).
Writes CSV results only into --out. Semantic validity is NOT decided here: this script prepares the
expert-review matrix; experts decide.

    python cdm_validation.py [--out outputs/human_validation/gate4_2026-11-02/CDM_VALIDATION]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.2/microbiome_cdm_v3.db"
REG = ROOT / "src/template/cdm/cdm_entity_registry.csv"
TRIPLE_MENTIONS = ROOT / "pipelines/corpus_v2/data/triple_mentions.jsonl"
CDM_TYPES = {"ORGANISM", "PROTEIN", "CHEMICAL", "DISEASE", "DNA_RNA", "CELL_TYPE", "SAMPLE_METHOD", "LAB_METHOD",
             "DATA_ANALYSIS", "PATHWAY", "EXPERIMENTAL_METHOD", "STUDY_DESIGN", "GENOMICS", "CLINICAL"}
MISSING = ("NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING")
CAT = {"cohort": "cohort_id", "sample": "sample_group_id", "assay": "assay_id", "dataset": "dataset_id",
       "data_asset": "asset_id", "claim": "finding_id"}
CATW = {"claim": " WHERE claim_source='catalogue_v3_1'"}


def where(t, cond):
    """CATW filter for table t combined with an extra condition."""
    return (CATW[t] + " AND " if t in CATW else " WHERE ") + cond


class V:
    def __init__(self):
        self.c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
        self.tests, self.rels, self.prov, self.queries = [], [], [], []

    def q(self, s, *p):
        return self.c.execute(s, p).fetchall()

    def one(self, s, *p):
        return self.c.execute(s, p).fetchone()[0]

    def cols(self, t):
        return [r[1] for r in self.q(f'PRAGMA table_info("{t}")')]

    def has(self, t):
        return bool(self.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", t))

    def test(self, tid, layer, cat, target, desc, population, violations, result, detail=""):
        self.tests.append({"test_id": tid, "layer": layer, "category": cat, "target": target, "description": desc,
                           "method": "automated, exhaustive", "population": population, "violations": violations,
                           "result": result, "detail": detail})


def split_ids(v):
    return [x.strip() for x in str(v).split(";") if x.strip()]


def run(out):
    v = V()
    reg = list(csv.DictReader(open(REG, encoding="utf-8")))
    status = dict(v.q("SELECT entity, status FROM cdm_entity_status"))
    table_of = {r["entity"]: r["entity"].lower() for r in reg}

    # ── L1 schema: module coverage, entity implementation, registry agreement ─
    mods = defaultdict(list)
    for r in reg:
        mods[r["module"]].append(r["entity"])
    for m, ents in sorted(mods.items()):
        pop = [e for e in ents if status.get(e) == "POPULATED"]
        v.test(f"S1.{m[:3]}", "L1", "module coverage", m, "module has at least one populated entity table",
               len(ents), len(ents) - len(pop) if not pop else 0, "PASS" if pop else "FAIL",
               f"populated: {', '.join(pop) or '-'}; other: " + ", ".join(f"{e}={status.get(e)}" for e in ents if e not in pop))
    stale = []
    for r in reg:
        e, t = r["entity"], table_of[r["entity"]]
        actual = status.get(e, "MISSING")
        documented = r["status"]
        if (documented == "PLANNED" and actual == "POPULATED") or (documented.startswith("POPULATED") and actual not in ("POPULATED", "EMBEDDED")):
            stale.append(f"{e}: registry {documented} vs release {actual}")
    v.test("S2", "L1", "documentation vs implementation", "cdm_entity_registry.csv",
           "registry status agrees with the release (cdm_entity_status)", len(reg), len(stale),
           "PASS" if not stale else "FAIL", "; ".join(stale))

    # primary keys: documented vs implemented, uniqueness, non-null, declared constraint
    pk_impl = {"paper": ["paper_id"], "source_asset": ["paper_id"], "section": ["section_record_id"],
               "extraction_run": ["extraction_run_id"], "processing_lineage": ["parent_id", "child_id", "relation"],
               "term_mention": ["mention_row_id"], "term_occurrence": ["occurrence_key"], "canonical_term": ["term_id"],
               "term_definition": ["definition_id", "term_id"], "concept": ["concept_id"],
               "term_concept_map": ["mapping_row_id"], "taxonomy_annotation": ["term_id", "taxonomy_version"],
               "study": ["study_id"], "cohort": ["cohort_id"], "sample": ["sample_group_id"], "assay": ["assay_id"],
               "body_site": ["body_site_label", "ontology_id"], "intervention": ["intervention_id"],
               "claim": ["finding_id", "claim_source"], "relation": ["canonical_triple_id"],
               "quantitative_result": ["finding_id", "claim_source"], "claim_evidence": ["finding_id", "claim_source"],
               "validation_result": ["validation_result_id"], "evaluation_run": ["evaluation_run_id"],
               "dataset": ["dataset_id"], "data_asset": ["asset_id"], "dataset_release": ["release_id"],
               "publication": ["publication_id"], "compendium_sample": ["srs"], "compendium_project": ["project"]}
    documented_pk = {table_of[r["entity"]]: r["primary_key"] for r in reg}
    for t, key in pk_impl.items():
        if not v.has(t):
            continue
        k = ", ".join(f'"{x}"' for x in key)
        n = v.one(f'SELECT COUNT(*) FROM "{t}"')
        dup = v.one(f'SELECT COALESCE(SUM(c - 1), 0) FROM (SELECT COUNT(*) c FROM "{t}" GROUP BY {k} HAVING c > 1)')
        nul = v.one(f'SELECT COUNT(*) FROM "{t}" WHERE ' + " OR ".join(f'"{x}" IS NULL' for x in key))
        declared = any(r[5] for r in v.q(f'PRAGMA table_info("{t}")'))
        v.test(f"S3.{t}", "L1", "primary key", t, f"key ({', '.join(key)}) unique and non-null", n, dup + nul,
               "PASS" if dup + nul == 0 else "FAIL",
               f"duplicates {dup}, nulls {nul}; PRIMARY KEY declared in SQLite: {'yes' if declared else 'no'}; "
               f"registry key: {documented_pk.get(t, '-')}")
    # documented keys that do not hold
    for t in ("term_mention", "term_concept_map"):
        col = documented_pk.get(t, "").split()[0]
        n = v.one(f'SELECT COUNT(*) FROM "{t}"')
        dup = v.one(f'SELECT COALESCE(SUM(c - 1), 0) FROM (SELECT COUNT(*) c FROM "{t}" WHERE "{col}" IS NOT NULL GROUP BY "{col}" HAVING c > 1)')
        nul = v.one(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IS NULL')
        v.test(f"S3D.{t}", "L1", "documented primary key", t, f"registry primary key '{col}' is unique and non-null",
               n, dup + nul, "PASS" if dup + nul == 0 else "FAIL",
               f"{dup} rows share an id, {nul} null" + ("; the release uses a surrogate key instead (documentation not updated)" if dup + nul else ""))
    # identifier patterns (template §3)
    pats = [("paper", "paper_id", r"^HMPAPER_[0-9]{6}$"), ("canonical_term", "term_id", r"^HMCTERM_[0-9a-f]{16}$"),
            ("term_mention", "mention_id", r"^HMTERM_[0-9a-f]{16}$"), ("term_mention", "occurrence_key", r"^HMOCC_[0-9a-f]{16}$"),
            ("cohort", "cohort_id", r"^HMCOHORT_[0-9]{6}$"), ("sample", "sample_group_id", r"^HMSAMPLE_[0-9]{6}$"),
            ("assay", "assay_id", r"^HMASSAY_[0-9]{6}$"), ("dataset", "dataset_id", r"^HMDATA_[0-9]{6}$"),
            ("data_asset", "asset_id", r"^HMASSET_[0-9]{6}$"), ("claim", "finding_id", r"^(HMFINDING_[0-9]{6}|HMPAPER_[0-9]{6}_FIND_[0-9]{4})$"),
            ("study", "study_id", r"^HMPAPER_[0-9]{6}_STUDY_[0-9]{3}$"), ("term_definition", "definition_id", r"^(HMDEF_[0-9a-f]{16}|HMDEF_LLM_[0-9]{7})$"),
            ("term_concept_map", "mapping_id", r"^HMMAP_[0-9a-f]{16}$")]
    for t, col, p in pats:
        rx = re.compile(p)
        vals = [r[0] for r in v.q(f'SELECT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL')]
        bad = [x for x in vals if not rx.match(str(x))]
        v.test(f"S4.{t}.{col}", "L1", "identifier pattern", f"{t}.{col}", f"matches {p}", len(vals), len(bad),
               "PASS" if not bad else "FAIL", f"examples: {bad[:3]}" if bad else "")

    # allowed values
    allowed = [("canonical_term", "cdm_type", CDM_TYPES | {"ENTITY"}),
               ("term_mention", "term_link_status", {"LINKED", "LINKED_BY_TYPE", "AMBIGUOUS", "NO_CANONICAL_TERM"}),
               ("term_mention", "offset_status", {"EXACT", "CORRECTED", "UNANCHORED"}),
               ("term_concept_map", "mapping_disposition_reviewed", {"ACCEPTED", "REVIEW_REQUIRED", "REMOVED", None}),
               ("taxonomy_annotation", "agreement_status", {"AGREED", "PARENT_AGREED", "UNCERTAIN", "CONFLICTING", "SINGLE_MODEL"})]
    for t, col in [(t, "evidence_anchor_status") for t in CAT]:
        allowed.append((t, col, {"EXACT", "WHITESPACE", "RELOCATED", "NORMALISED", "FUZZY", "UNANCHORED", "NO_EVIDENCE",
                                 "NO_SECTION", None} if t == "claim" else
                        {"EXACT", "WHITESPACE", "RELOCATED", "NORMALISED", "FUZZY", "UNANCHORED", "NO_EVIDENCE", "NO_SECTION"}))
    for t, col, ok in allowed:
        if not (v.has(t) and col in v.cols(t)):
            v.test(f"S5.{t}.{col}", "L1", "allowed values", f"{t}.{col}", "column exists", 0, 1, "FAIL", "column missing")
            continue
        dist = dict(v.q(f'SELECT "{col}", COUNT(*) FROM "{t}" GROUP BY 1'))
        bad = {k: n for k, n in dist.items() if k not in ok}
        v.test(f"S5.{t}.{col}", "L1", "allowed values", f"{t}.{col}", "only documented values", sum(dist.values()),
               sum(bad.values()), "PASS" if not bad else "FAIL", json.dumps(bad)[:300] if bad else "")
    # review status: no ACCEPTED without a human review
    hr = v.one("SELECT COUNT(*) FROM human_review")
    acc = {}
    for t in ("canonical_term", "term_mention", "term_definition", "term_concept_map", "relation", "claim", "cohort",
              "sample", "assay", "dataset", "data_asset", "study"):
        if "review_status" in v.cols(t):
            n = v.one(f"SELECT COUNT(*) FROM \"{t}\" WHERE review_status IN ('ACCEPTED','APPROVED','REJECTED')")
            nn = v.one(f"SELECT COUNT(*) FROM \"{t}\" WHERE review_status IS NULL OR review_status=''")
            if n or nn:
                acc[t] = {"human_terminal_status": n, "missing_status": nn}
    v.test("S6", "L1", "review-status contract", "all L2+ tables",
           "no human-terminal status (ACCEPTED/REJECTED) while human_review is empty; every row has a status",
           hr, sum(x["human_terminal_status"] + x["missing_status"] for x in acc.values()),
           "PASS" if not acc else "FAIL", json.dumps(acc)[:400])
    # missing-data vocabulary: no free-text variants of the codes in catalogue fields
    variants = re.compile(r"^(n/?a|none|not (reported|stated|specified|available|mentioned)|unknown|nr|-+)$", re.I)
    bad = Counter()
    for t in CAT:
        for col in v.cols(t):
            if col.endswith(("_id", "_status", "_source", "_sources", "_flag", "status")) or col in ("evidence_span", "evidence_text"):
                continue
            cond = f"\"{col}\" IS NOT NULL AND \"{col}\" != ''"
            for (x,) in v.q(f'SELECT "{col}" FROM "{t}"' + where(t, cond)):
                if isinstance(x, str) and variants.match(x.strip()):
                    bad[f"{t}.{col}"] += 1
    v.test("S7", "L1", "missing-data convention", "catalogue tables",
           "missing information uses only NOT_REPORTED / NOT_APPLICABLE / NOT_ACCESSIBLE / CONFLICTING (template §4)",
           "all catalogue values", sum(bad.values()), "PASS" if not bad else "FAIL", json.dumps(dict(bad.most_common(8))))
    # data types: count fields numeric
    for t, col in (("cohort", "participant_count"), ("cohort", "sample_count"), ("sample", "sample_count")):
        vals = [x for (x,) in v.q(f'SELECT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL AND "{col}" != \'\'') if x not in MISSING]
        badv = [x for x in vals if not re.fullmatch(r"\s*\d[\d,]*\s*", str(x))]
        v.test(f"S8.{t}.{col}", "L1", "data type", f"{t}.{col}", "count is an integer or a missing-data code",
               len(vals), len(badv), "PASS" if not badv else "FAIL", f"examples: {badv[:4]}" if badv else "")
    # column type homogeneity
    mixed = []
    for (t,) in v.q("SELECT name FROM sqlite_master WHERE type='table'"):
        if t in ("term_mention",):           # 2.5M rows: sampled by rowid below
            sql = f'SELECT {{c}}, COUNT(*) FROM (SELECT typeof("{{col}}") {{c}} FROM "{t}" WHERE rowid % 25 = 0) GROUP BY 1'
        else:
            sql = f'SELECT {{c}}, COUNT(*) FROM (SELECT typeof("{{col}}") {{c}} FROM "{t}") GROUP BY 1'
        for col in v.cols(t):
            ty = {k for k, n in v.q(sql.format(c="ty", col=col)) if k != "null"}
            if len(ty) > 1:
                mixed.append(f"{t}.{col}:{'/'.join(sorted(ty))}")
    v.test("S9", "L1", "data type", "all tables", "each column holds one storage type (besides NULL)", "all columns",
           len(mixed), "PASS" if not mixed else "FAIL", "; ".join(mixed[:25]) + (f" … (+{len(mixed) - 25})" if len(mixed) > 25 else ""))

    # ── L3 relationships: foreign keys, cardinality, same-paper consistency ──
    papers = {x for (x,) in v.q("SELECT paper_id FROM paper")}
    secs = {(p, s) for p, s in v.q("SELECT paper_id, section_id_original FROM section")}
    sec_rec = {x for (x,) in v.q("SELECT section_record_id FROM section")}
    runs = {x for (x,) in v.q("SELECT extraction_run_id FROM extraction_run")}
    recs = {}
    for t, idc in CAT.items():
        recs[t] = {i: p for i, p in v.q(f'SELECT "{idc}", paper_id FROM "{t}"{CATW.get(t, "")}')}
    links = [("claim", "cohort_id", "cohort"), ("claim", "assay_id", "assay"), ("claim", "dataset_id", "dataset"),
             ("cohort", "dataset_id", "dataset"), ("sample", "cohort_id", "cohort"), ("sample", "dataset_id", "dataset"),
             ("assay", "dataset_id", "dataset"), ("data_asset", "dataset_id", "dataset")]
    for t, col, tt in links:
        rows = v.q(f'SELECT "{CAT[t]}", paper_id, "{col}" FROM "{t}"' + where(t, f"COALESCE(\"{col}\", '') != ''"))
        dangling = cross = multi = 0
        card = Counter()
        for rid, pid, val in rows:
            ids = split_ids(val)
            card[min(len(ids), 4)] += 1
            multi += len(ids) > 1
            for i in ids:
                if i not in recs[tt]:
                    dangling += 1
                elif recs[tt][i] != pid:
                    cross += 1
        n = len(recs[t])
        v.rels.append({"relationship": f"{t}.{col} -> {tt}", "documented": "n-1 (one parent)", "records": n,
                       "with_link": len(rows), "without_link": n - len(rows), "multi_valued": multi,
                       "cardinality_distribution": json.dumps({("4+" if k == 4 else str(k)): c for k, c in sorted(card.items())}),
                       "dangling_ids": dangling, "cross_paper_links": cross,
                       "result": "FAIL" if dangling or cross else ("CONDITIONAL" if multi else "PASS"),
                       "note": "multi-valued text field instead of a junction table" if multi else ""})
        v.test(f"R.{t}.{col}", "L3", "relationship", f"{t}.{col}->{tt}",
               "every linked id resolves and belongs to the same paper", len(rows), dangling + cross,
               "PASS" if not dangling + cross else "FAIL", f"dangling {dangling}, cross-paper {cross}, multi-valued {multi}")
    # paper-scoped tables
    for t in ("section", "study", "cohort", "sample", "assay", "dataset", "data_asset", "claim", "term_mention",
              "term_definition", "source_asset", "paper_publication"):
        n = v.one(f'SELECT COUNT(*) FROM "{t}"')
        bad = v.one(f'SELECT COUNT(*) FROM "{t}" WHERE paper_id IS NULL OR paper_id NOT IN (SELECT paper_id FROM paper)')
        v.test(f"R.paper.{t}", "L3", "relationship", f"{t}.paper_id->paper", "paper_id present and resolves", n, bad,
               "PASS" if not bad else "FAIL")
    # section references (evidence geometry)
    for t, pc, sc in (("term_mention", "paper_id", "section_id"), ("term_definition", "paper_id", "section_id"),
                      ("cohort", "paper_id", "section_id"), ("sample", "paper_id", "section_id"),
                      ("assay", "paper_id", "section_id"), ("dataset", "paper_id", "section_id"),
                      ("data_asset", "paper_id", "section_id"), ("claim", "paper_id", "section_id")):
        rows = v.q(f'SELECT "{pc}", "{sc}" FROM "{t}"{CATW.get(t, "")}')
        has = [(p, s) for p, s in rows if s]
        bad = sum((p, s) not in secs and s not in sec_rec for p, s in has)
        v.test(f"R.section.{t}", "L3", "relationship", f"{t}.(paper_id, section_id)->section",
               "evidence section resolves", len(has), bad, "PASS" if not bad else "FAIL",
               f"{len(rows) - len(has)} rows without a section")
    corp = v.q("SELECT evidence_section_id FROM claim WHERE claim_source='corpus_stage52'")
    bad = sum(1 for (s,) in corp if s and s not in sec_rec)
    v.test("R.section.claim_corpus", "L3", "relationship", "claim(corpus).evidence_section_id->section",
           "evidence section resolves", len(corp), bad, "PASS" if not bad else "FAIL")
    # run provenance contract (§5): every L2+ row has a run that exists in EXTRACTION_RUN
    run_tables = ["term_mention", "term_definition", "claim", "cohort", "sample", "assay", "dataset", "data_asset"]
    run_tables += [t for t in ("relation", "taxonomy_annotation", "term_concept_map", "type_harmonization")
                   if v.has(t) and "extraction_run_id" in v.cols(t)]
    for t in run_tables:
        dist = dict(v.q(f'SELECT extraction_run_id, COUNT(*) FROM "{t}" GROUP BY 1'))
        if t == "claim" and "extraction_run_id_recovered" in v.cols(t):     # 3.0.3: recovered run for corpus claims
            dist = dict(v.q('SELECT COALESCE(extraction_run_id, extraction_run_id_recovered), COUNT(*) FROM claim GROUP BY 1'))
        missing = sum(n for k, n in dist.items() if not k)
        orphan = {k: n for k, n in dist.items() if k and k not in runs}
        v.test(f"R.run.{t}", "L3", "provenance contract", f"{t}.extraction_run_id->extraction_run",
               "every row names a run listed in EXTRACTION_RUN (template §5: orphans fail the build)",
               sum(dist.values()), missing + sum(orphan.values()), "PASS" if not missing and not orphan else "FAIL",
               f"no run id: {missing}; run ids not in extraction_run: {json.dumps(orphan)[:300]}")
    for t in ("relation", "taxonomy_annotation", "term_concept_map", "type_harmonization"):
        if v.has(t) and t not in run_tables:
            v.test(f"R.run.{t}", "L3", "provenance contract", t, "row carries an extraction_run_id", v.one(f'SELECT COUNT(*) FROM "{t}"'),
                   v.one(f'SELECT COUNT(*) FROM "{t}"') if "extraction_run_id" not in v.cols(t) else 0,
                   "FAIL" if "extraction_run_id" not in v.cols(t) else "PASS",
                   "no extraction_run_id column" if "extraction_run_id" not in v.cols(t) else "")
    # text_version_id contract
    for t in ("term_mention", "term_definition", "cohort", "claim"):
        has_col = "text_version_id" in v.cols(t) or "section_text_sha256" in v.cols(t)
        v.test(f"R.textversion.{t}", "L3", "provenance contract", t, "row carries text_version_id (template §5)",
               v.one(f'SELECT COUNT(*) FROM "{t}"'), 0 if has_col else v.one(f'SELECT COUNT(*) FROM "{t}"'),
               "PASS" if has_col else "FAIL", "" if has_col else "column absent; offsets index section_text_original implicitly")
    # documented cardinalities (cdm_relationships.md)
    def card_row(name, documented, q_parent_child, note=""):
        dist = Counter(n for (n,) in v.q(q_parent_child))
        v.rels.append({"relationship": name, "documented": documented, "records": sum(dist.values()), "with_link": "",
                       "without_link": dist.get(0, ""), "multi_valued": sum(c for k, c in dist.items() if k > 1),
                       "cardinality_distribution": json.dumps(dict(sorted(Counter(min(k, 4) for k in dist.elements()).items()))),
                       "dangling_ids": "", "cross_paper_links": "", "result": "", "note": note})
        return dist
    d = card_row("PAPER 1-n STUDY", "1-n", "SELECT (SELECT COUNT(*) FROM study s WHERE s.paper_id=p.paper_id) FROM paper p",
                 "implemented as exactly one study per paper")
    v.rels[-1]["result"] = "PASS" if set(d) == {1} else "CONDITIONAL"
    v.rels.append({"relationship": "STUDY 1-n COHORT", "documented": "1-n", "records": v.one("SELECT COUNT(*) FROM cohort"),
                   "with_link": 0, "without_link": v.one("SELECT COUNT(*) FROM cohort"), "multi_valued": "", "cardinality_distribution": "",
                   "dangling_ids": "", "cross_paper_links": "", "result": "NOT_IMPLEMENTED",
                   "note": "cohort has no study_id column; cohorts attach to PAPER (and DATASET) only"})
    v.rels.append({"relationship": "STUDY 1-n ASSAY", "documented": "1-n", "records": v.one("SELECT COUNT(*) FROM assay"),
                   "with_link": 0, "without_link": v.one("SELECT COUNT(*) FROM assay"), "multi_valued": "", "cardinality_distribution": "",
                   "dangling_ids": "", "cross_paper_links": "", "result": "NOT_IMPLEMENTED", "note": "assay has no study_id column"})
    st = v.one("SELECT COUNT(*) FROM claim WHERE claim_source='catalogue_v3_1' AND COALESCE(study_id,'')!=''")
    v.rels.append({"relationship": "CLAIM n-1 STUDY", "documented": "registry FK CLAIM.study_id", "records": len(recs["claim"]),
                   "with_link": st, "without_link": len(recs["claim"]) - st, "multi_valued": "", "cardinality_distribution": "",
                   "dangling_ids": "", "cross_paper_links": "", "result": "FAIL" if st < len(recs["claim"]) else "PASS",
                   "note": "catalogue findings carry no study_id; corpus findings do"})
    d = card_row("CLAIM 1-n CLAIM_EVIDENCE", "1-n (locator + status mandatory)",
                 "SELECT COUNT(*) FROM claim_evidence GROUP BY finding_id, claim_source", "one evidence row per claim (no multiple locators)")
    v.rels[-1]["result"] = "PASS" if set(d) == {1} else "CONDITIONAL"
    d = card_row("CANONICAL_TERM 1-n TAXONOMY_ANNOTATION", "1-n",
                 "SELECT COUNT(*) FROM taxonomy_annotation GROUP BY term_id", "one annotation per term")
    v.rels[-1]["result"] = "PASS"
    d = card_row("TERM_OCCURRENCE 1-n TERM_MENTION", "1-n", "SELECT n_mentions FROM term_occurrence",
                 "competing model tags kept as separate mentions")
    v.rels[-1]["result"] = "PASS"
    contra = v.one("SELECT COUNT(*) FROM (SELECT term_id FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED' "
                   "AND relation_deepseek='EXACT' GROUP BY term_id HAVING COUNT(DISTINCT concept_id) > 1)")
    v.rels.append({"relationship": "CANONICAL_TERM 1-n TERM_CONCEPT_MAP (EXACT, accepted)", "documented": "every candidate kept",
                   "records": v.one("SELECT COUNT(DISTINCT term_id) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'"),
                   "with_link": "", "without_link": "", "multi_valued": contra, "cardinality_distribution": "",
                   "dangling_ids": "", "cross_paper_links": "", "result": "CONDITIONAL" if contra else "PASS",
                   "note": f"{contra} terms have accepted EXACT mappings to more than one concept (cross-ontology duplicates or contradictions — expert check)"})
    # aggregate tables consistent with their sources
    bs_rows = v.one("SELECT SUM(n_records) FROM body_site")
    bs_src = v.one("SELECT (SELECT COUNT(*) FROM sample WHERE COALESCE(body_site_normalized,'')!='') + "
                   "(SELECT COUNT(*) FROM claim WHERE claim_source='catalogue_v3_1' AND COALESCE(body_site_normalized,'')!='')")
    v.test("N1", "L1", "redundancy", "body_site", "aggregate n_records equals source records with a normalised body site",
           bs_src, abs(bs_rows - bs_src), "PASS" if bs_rows == bs_src else "FAIL", f"{bs_rows} vs {bs_src}")
    iv = v.one("SELECT SUM(n_findings) FROM intervention")
    iv_src = v.one("SELECT COUNT(*) FROM claim WHERE claim_source='catalogue_v3_1' AND COALESCE(intervention_category,'')!=''")
    v.test("N2", "L1", "redundancy", "intervention", "aggregate n_findings equals findings with an intervention category",
           iv_src, abs(iv - iv_src), "PASS" if iv == iv_src else "FAIL", f"{iv} vs {iv_src}")
    two = dict(v.q("SELECT claim_source, COUNT(*) FROM claim GROUP BY 1"))
    v.test("N3", "L1", "redundancy", "claim", "CLAIM holds one representation of each finding", sum(two.values()),
           0, "CONDITIONAL", f"two independent extractions share the table: {json.dumps(two)}; overlap between them is not reconciled (expert decision)")

    # ── provenance paths ─────────────────────────────────────────────────────
    sec_text = {(p, s): t for p, s, t in v.q("SELECT paper_id, section_id_original, section_text_original FROM section")}
    sec_text_rec = {r: t for r, t in v.q("SELECT section_record_id, section_text_original FROM section")}
    ws = lambda x: " ".join(str(x).split())
    # P1 record -> paper
    tot = sum(len(r) for r in recs.values())
    bad = sum(1 for r in recs.values() for p in r.values() if p not in papers)
    v.prov.append({"path": "catalogue record -> source paper", "population": tot, "traced": tot - bad, "result": "PASS" if not bad else "FAIL",
                   "method": "paper_id resolves in PAPER", "note": ""})
    # P2 value -> its own quote (gap-filled fields carry a per-field quote)
    n = ok = found = conflict_notes = 0
    for t in [t for t in CAT if "gap_evidence" in v.cols(t)]:
        for ge, pid in v.q(f'SELECT gap_evidence, paper_id FROM "{t}"' + where(t, "COALESCE(gap_evidence, '') NOT IN ('', '{}')")):
            try:
                d = json.loads(ge)
            except (TypeError, json.JSONDecodeError):
                continue
            for f, e in d.items():
                if not isinstance(e, dict):
                    continue
                if "quote" not in e:          # CONFLICTING notes list the competing values; no quote by design
                    conflict_notes += 1
                    continue
                n += 1
                txt = sec_text.get((pid, e.get("section_id")))
                if txt is None:
                    continue
                ok += 1
                a, b = e.get("char_start"), e.get("char_end")
                if a is not None and txt[a:b] == e.get("quote"):
                    found += 1
                elif e.get("quote") and ws(e["quote"]) in ws(txt):
                    found += 1
    v.prov.append({"path": "gap-filled value -> its supporting quote -> section + offsets", "population": n, "traced": found,
                   "result": "PASS" if found == n else ("CONDITIONAL" if found / max(n, 1) > .95 else "FAIL"),
                   "method": "gap_evidence quote equals section_text[start:end] or occurs whitespace-normalised",
                   "note": f"section resolved for {ok}; quote found {found}; {conflict_notes} CONFLICTING notes carry competing values instead of a quote"})
    # P3 record quote -> located span (anchor status)
    anc = Counter()
    for t in CAT:
        for s, c in v.q(f'SELECT evidence_anchor_status, COUNT(*) FROM "{t}"{CATW.get(t, "")} GROUP BY 1'):
            anc[s] += c
    verb = sum(anc[k] for k in ("EXACT", "WHITESPACE", "RELOCATED", "NORMALISED"))
    v.prov.append({"path": "catalogue record quote -> exact section span", "population": sum(anc.values()), "traced": verb,
                   "result": "CONDITIONAL", "method": "evidence_anchor_status (verbatim statuses)",
                   "note": f"FUZZY {anc['FUZZY']} approximate; UNANCHORED {anc['UNANCHORED']}; NO_EVIDENCE {anc['NO_EVIDENCE']}"})
    # P4 canonical term -> mentions
    nt = v.one("SELECT COUNT(*) FROM canonical_term")
    with_m = v.one("SELECT COUNT(*) FROM canonical_term WHERE term_id IN (SELECT DISTINCT canonical_term_id FROM term_mention)")
    v.prov.append({"path": "canonical term -> its original mentions", "population": nt, "traced": with_m,
                   "result": "PASS" if with_m == nt else "CONDITIONAL", "method": "term_id appears as term_mention.canonical_term_id",
                   "note": f"{nt - with_m} terms have no linked mention (normalised-string link did not reach them)"})
    # P5 mapping -> mapping evidence
    mcols = v.cols("term_concept_map")
    ev_cols = [c for c in mcols if c in ("matched_via", "scores", "provenance", "source_service", "query")]
    v.prov.append({"path": "ontology mapping -> mapping evidence (query, service, score)", "population": v.one("SELECT COUNT(*) FROM term_concept_map"),
                   "traced": 0 if not ev_cols else v.one("SELECT COUNT(*) FROM term_concept_map"),
                   "result": "FAIL" if not ev_cols else "PASS", "method": "evidence columns present in TERM_CONCEPT_MAP",
                   "note": "CDM keeps relation, rank and dispositions but drops matched_via / scores / service-query provenance present in the frozen mapping files"
                   if not ev_cols else ",".join(ev_cols)})
    # P6 triple -> source evidence
    ids = {}
    for cid, tm in v.q("SELECT canonical_triple_id, triple_mention_ids FROM relation"):
        try:
            ids[cid] = json.loads(tm) if tm else []
        except json.JSONDecodeError:
            ids[cid] = []
    need = {x for l in ids.values() for x in l}
    tms = {}
    with open(TRIPLE_MENTIONS, encoding="utf-8") as fh:
        for line in fh:
            m = json.loads(line)
            if m["triple_mention_id"] in need:
                tms[m["triple_mention_id"]] = (m.get("section_id"), m.get("source_sentence"))
    resolved = insec = 0
    for cid, l in ids.items():
        hits = [tms[i] for i in l if i in tms]
        if hits:
            resolved += 1
            if any(s and t and ws(s) in ws(sec_text_rec.get(sid, "")) for sid, s in hits):
                insec += 1
    v.prov.append({"path": "knowledge triple -> source sentence -> section text", "population": len(ids), "traced": insec,
                   "result": "PASS" if insec == len(ids) else ("CONDITIONAL" if insec / len(ids) > .9 else "FAIL"),
                   "method": "triple_mention_ids resolve; source_sentence occurs (whitespace-normalised) in its section",
                   "note": f"mention ids resolve for {resolved}; sentence found in section for {insec}; no character offsets recorded (source_character_start 'unavailable')"})
    # P7 definition -> source span
    dd = dict(v.q("SELECT evidence_anchor_status, COUNT(*) FROM term_definition GROUP BY 1"))
    v.prov.append({"path": "definition -> source span", "population": sum(dd.values()), "traced": dd.get("EXACT", 0) + dd.get("RELOCATED", 0),
                   "result": "PASS" if dd.get("EXACT", 0) + dd.get("RELOCATED", 0) == sum(dd.values()) else "CONDITIONAL",
                   "method": "evidence_anchor_status", "note": json.dumps(dd)})
    # P8 template §8 end-to-end trace for catalogue findings (funnel)
    f = v.q("SELECT finding_id, paper_id, section_id, evidence_span_start, evidence_span_end, cohort_id, assay_id "
            "FROM claim WHERE claim_source='catalogue_v3_1'")
    m_by_sec = defaultdict(list)
    for pid, sid, a, b, tid in v.q("SELECT paper_id, section_id, start_offset, end_offset, canonical_term_id FROM term_mention "
                                   "WHERE canonical_term_id IS NOT NULL"):
        m_by_sec[(pid, sid)].append((a, b, tid))
    acc_terms = {x for (x,) in v.q("SELECT DISTINCT term_id FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'")}
    def_terms = {x for (x,) in v.q("SELECT DISTINCT term_id FROM term_definition WHERE term_status=''")}
    trip_papers = Counter(json.loads(p)[0] if p and p.startswith("[") else p for (p,) in v.q("SELECT paper_ids FROM relation"))
    funnel = Counter()
    for fid, pid, sid, a, b, coh, asy in f:
        funnel["1 finding"] += 1
        if (pid, sid) not in sec_text or a is None:
            continue
        funnel["2 located source passage"] += 1
        if not (coh and asy):
            continue
        funnel["3 linked cohort and assay context"] += 1
        terms = {t for x, y, t in m_by_sec.get((pid, sid), []) if x is not None and x < b and y > a}
        if not terms:
            continue
        funnel["4 NER mentions -> canonical terms inside the passage"] += 1
        if not terms & acc_terms:
            continue
        funnel["5 at least one term with an accepted vocabulary mapping"] += 1
        if not terms & def_terms:
            continue
        funnel["6 ... and a source-derived definition"] += 1
        if not trip_papers.get(pid):
            continue
        funnel["7 paper has knowledge triples"] += 1
    for step, k in sorted(funnel.items()):
        v.prov.append({"path": f"end-to-end trace (template §8): {step}", "population": funnel["1 finding"], "traced": k,
                       "result": "", "method": "exhaustive over catalogue findings", "note": f"{100 * k / funnel['1 finding']:.1f}%"})

    # ── L4 interoperability ──────────────────────────────────────────────────
    inter = []
    ic = v.one("PRAGMA quick_check")
    inter.append(("SQLite integrity (PRAGMA quick_check)", ic, "PASS" if ic == "ok" else "FAIL"))
    bad_rt = []
    big = v.one("SELECT MAX(LENGTH(section_text_original)) FROM section")
    inter.append(("largest text field vs Python csv default field limit (131,072 chars)",
                  f"{big:,} chars in section.section_text_original — default CSV readers fail on an export unless the limit is raised",
                  "CONDITIONAL" if big > 131072 else "PASS"))
    csv.field_size_limit(1 << 30)
    for (t,) in v.q("SELECT name FROM sqlite_master WHERE type='table'"):
        if t in ("term_mention", "compendium_sample_tag"):
            continue        # large tables: covered by row-count check only
        buf = io.StringIO()
        w = csv.writer(buf)
        rows = v.q(f'SELECT * FROM "{t}"')
        w.writerow(v.cols(t))
        w.writerows(rows)
        back = list(csv.reader(io.StringIO(buf.getvalue())))
        if len(back) - 1 != len(rows) or any(len(r) != len(v.cols(t)) for r in back):
            bad_rt.append(t)
    inter.append(("CSV export round-trip (rows and columns preserved), all tables except the two largest", f"{len(bad_rt)} tables failed", "PASS" if not bad_rt else "FAIL"))
    js = Counter()
    for (t,) in v.q("SELECT name FROM sqlite_master WHERE type='table'"):
        if t in ("term_mention", "compendium_sample_tag"):
            continue
        for col in v.cols(t):
            x = v.q(f'SELECT "{col}" FROM "{t}" WHERE "{col}" LIKE \'[%\' OR "{col}" LIKE \'{{%\' LIMIT 1')
            if x:
                js[t] += 1
    inter.append(("columns holding JSON-encoded lists/objects inside text (need parsing by consumers)",
                  f"{sum(js.values())} columns in {len(js)} tables: " + ", ".join(f"{k}({n})" for k, n in js.most_common(8)), "CONDITIONAL"))
    snake = [f"{t}.{c}" for (t,) in v.q("SELECT name FROM sqlite_master WHERE type='table'") for c in v.cols(t)
             if not re.fullmatch(r"[a-z][a-z0-9_]*", c)]
    inter.append(("column names are lower snake_case", f"{len(snake)} exceptions: {snake[:6]}", "PASS" if not snake else "CONDITIONAL"))
    fk_decl = sum(len(v.q(f'PRAGMA foreign_key_list("{t}")')) for (t,) in v.q("SELECT name FROM sqlite_master WHERE type='table'"))
    inter.append(("foreign keys declared in the database schema (machine-readable relationships)", f"{fk_decl} declared", "FAIL" if not fk_decl else "PASS"))
    ntab = v.one("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    nview = v.one("SELECT COUNT(*) FROM sqlite_master WHERE type='view'")
    inter.append(("tables / views", f"{ntab} tables, {nview} views", "INFO"))

    # ── L4 research queries (expected answers to be set by humans) ──────────
    Q = [
        ("Q1", "IBD studies using 16S rRNA amplicon sequencing",
         "SELECT DISTINCT a.paper_id FROM assay a JOIN cohort c ON c.paper_id=a.paper_id WHERE "
         "(LOWER(a.assay_type_normalized) LIKE '%16s%' OR LOWER(a.target_gene_or_region) LIKE '%16s%' OR LOWER(a.assay_type) LIKE '%16s%') "
         "AND (LOWER(c.health_status) LIKE '%inflammatory bowel%' OR LOWER(c.health_status) LIKE '%ibd%' OR LOWER(c.health_status) LIKE '%crohn%' OR LOWER(c.health_status) LIKE '%ulcerative colitis%')"),
        ("Q2", "Cohorts of patients with type 2 diabetes",
         "SELECT cohort_id, paper_id, cohort_label FROM cohort WHERE LOWER(health_status) LIKE '%type 2 diabetes%' OR LOWER(health_status) LIKE '%t2d%' OR LOWER(cohort_label) LIKE '%type 2 diabet%'"),
        ("Q3", "Own-result findings reporting Faecalibacterium prausnitzii decreased in disease vs control",
         "SELECT finding_id, paper_id, direction FROM claim WHERE claim_source='catalogue_v3_1' AND LOWER(taxon_or_feature) LIKE '%faecalibacterium%' "
         "AND LOWER(direction) LIKE '%decrease%' AND COALESCE(cites_other_work,'') NOT IN ('YES','yes','true','1')"),
        ("Q4", "Datasets with a valid public accession (SRA / ENA / DDBJ BioProject or run)",
         "SELECT dataset_id, paper_id, repository_accession FROM dataset WHERE accession_valid IN (1,'1','true','True','YES') AND COALESCE(repository_accession,'') NOT IN ('',"
         + ",".join(f"'{m}'" for m in MISSING) + ")"),
        ("Q5", "Trace one finding to its quotation and publication (HMFINDING ids sampled: provenance completeness)",
         "SELECT c.finding_id, c.paper_id, p.doi, s.section_name_original, c.evidence_span_start, c.evidence_span_end, c.evidence_anchor_status "
         "FROM claim c JOIN paper p ON p.paper_id=c.paper_id LEFT JOIN section s ON s.paper_id=c.paper_id AND s.section_id_original=c.section_id "
         "WHERE c.claim_source='catalogue_v3_1'"),
        ("Q6", "Studies with a probiotic intervention",
         "SELECT DISTINCT paper_id FROM claim WHERE claim_source='catalogue_v3_1' AND LOWER(intervention_category) LIKE '%probiotic%'"),
        ("Q7", "Stool samples stored at -80 C",
         "SELECT sample_group_id, paper_id FROM sample WHERE (LOWER(COALESCE(sample_type_normalized, sample_type, '')) LIKE '%stool%' OR LOWER(COALESCE(sample_type_normalized, sample_type, '')) LIKE '%fec%' "
         "OR LOWER(COALESCE(sample_type_normalized, sample_type, '')) LIKE '%faec%') AND storage_condition LIKE '%80%'"),
        ("Q8", "Shotgun metagenomics studies with an NCBI-linked taxon finding",
         "SELECT DISTINCT a.paper_id FROM assay a JOIN claim f ON f.paper_id=a.paper_id AND f.claim_source='catalogue_v3_1' "
         "WHERE (LOWER(a.assay_type_normalized) LIKE '%shotgun%' OR LOWER(a.assay_type) LIKE '%metagenom%') AND f.taxon_link_status='LINKED'"),
    ]
    for qid, question, sql in Q:
        rows = v.q(sql)
        papers_q = sorted({next(x for x in r if str(x).startswith("HMPAPER")) for r in rows
                           if any(str(x).startswith("HMPAPER") for x in r)})
        v.queries.append({"query_id": qid, "research_question": question, "sql": sql, "returned_rows": len(rows),
                          "returned_papers": len(papers_q), "returned_paper_ids": ";".join(papers_q[:60]) + (" …" if len(papers_q) > 60 else ""),
                          "expected_paper_ids_from_source_review": "", "missing_expected": "", "false_inclusions": "",
                          "provenance_complete": "", "reproducible_from_documentation": "", "reviewer_id": "", "notes": ""})
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("CDM_CONSTRAINT_TEST_RESULTS.csv", v.tests), ("CDM_RELATIONSHIP_VALIDATION.csv", v.rels),
                       ("PROVENANCE_PATH_TESTS.csv", v.prov), ("RESEARCH_QUERY_VALIDATION.csv", v.queries)):
        keys = []
        for r in rows:
            keys += [k for k in r if k not in keys]
        with open(out / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    (out / "_interoperability_tests.json").write_text(json.dumps(inter, indent=1) + "\n")
    # entity matrix with expert columns
    rows = []
    for r in reg:
        e, t = r["entity"], table_of[r["entity"]]
        exists = v.has(t)
        rows.append({"entity": e, "module": r["module"], "layer": r["layer"], "documented_purpose": r["purpose"],
                     "documented_primary_key": r["primary_key"], "documented_foreign_keys": r["foreign_keys"],
                     "registry_status": r["status"], "release_status": status.get(e, ""), "implemented_table": t if exists else "(embedded / none)",
                     "rows": v.one(f'SELECT COUNT(*) FROM "{t}"') if exists else "", "columns": len(v.cols(t)) if exists else "",
                     "population_sources": r["population_sources"], "coverage_note": r["coverage_note"],
                     "expert_meaning_clear": "", "expert_granularity_appropriate": "", "expert_relationships_appropriate": "",
                     "expert_attributes_on_right_entity": "", "expert_required_attributes_present": "",
                     "expert_adoptable_by_others": "", "expert_comments": ""})
    with open(out / "CDM_ENTITY_REVIEW_MATRIX.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {"tests": dict(Counter(t["result"] for t in v.tests)), "failed": [t["test_id"] for t in v.tests if t["result"] == "FAIL"],
               "relationships": dict(Counter(r["result"] for r in v.rels)), "provenance": [(p["path"], p["traced"], p["population"], p["result"]) for p in v.prov],
               "interop": inter, "queries": [(q["query_id"], q["returned_rows"], q["returned_papers"]) for q in v.queries],
               "funnel": dict(funnel)}
    (out / "_cdm_validation_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


def main(argv=None):
    global CDM, REG
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "outputs/human_validation/gate4_2026-11-02/CDM_VALIDATION"))
    ap.add_argument("--cdm", default=str(CDM))
    ap.add_argument("--registry", default=str(REG))
    a = ap.parse_args(argv)
    CDM, REG = Path(a.cdm), Path(a.registry)
    run(Path(a.out))


if __name__ == "__main__":
    raise SystemExit(main())
