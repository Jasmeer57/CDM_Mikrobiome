"""Build the template-shaped Common Data Model (CDM 3.0) as one SQLite database.

Implements the entity registry in src/template/cdm/ (modules M1-M10, HM* keys)
from the frozen and gap-pipeline artifacts — no model calls. Template rules
carried into the tables:
  * every L2+ row has `review_status` (UNVERIFIED / REVIEW_REQUIRED unless a
    human review exists — none does yet) and, where known, `extraction_run_id`;
  * model outputs and competing predictions are separate rows, never merged;
  * missing data keeps the template codes (NOT_REPORTED, CONFLICTING, ...);
  * BioProject <-> paper duplicates are recorded, not resolved.

    python build_cdm_v3.py [--out outputs/results/cdm_v3/microbiome_cdm_v3.db] [--skip_mentions]
"""
from __future__ import annotations

import argparse
import csv
import difflib
import gzip
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

csv.field_size_limit(sys.maxsize)
ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
R = ROOT / "outputs/results"
GD = R / "gap_runs"
TERM = next(ROOT / f"releases/terminology/{v}" for v in ("1.0.1", "1.0.0")
            if (ROOT / f"releases/terminology/{v}/MANIFEST.sha256").exists())
CAT = R / "catalogue_v3_1"
CORPUS = ROOT / "pipelines/corpus_v2/data"
FROZEN = ROOT / "releases/frozen_output"
COMP = ROOT / "data/168000-samples-paper"
DSR = R / "deepseek_review/corrected"   # DeepSeek review outputs (new files), used when present


def jl(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _did(d):
    """Definition id as used by deepseek_review.py (G8 rows: G8_<n>)."""
    i = d.get("definition_id") or ""
    return "G8_" + i[len("HMDEF_LLM_"):] if i.startswith("HMDEF_LLM_") else i


def val(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    return v


class DB:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        self.c = sqlite3.connect(path)
        self.c.execute("PRAGMA journal_mode=OFF")
        self.c.execute("PRAGMA synchronous=OFF")
        self.counts = {}
        self.offered = {}   # rows handed to table(); offered - kept = rows dropped by the primary key

    def table(self, name, rows, cols=None, pk=None, indexes=(), batch=50000):
        rows = iter(rows)
        first = next(rows, None)
        if first is None:
            cols = cols or ["id"]
        else:
            cols = cols or list(first)
        defs = ", ".join(f'"{c}"' + (" PRIMARY KEY" if c == pk else "") for c in cols)
        self.c.execute(f'CREATE TABLE "{name}" ({defs})')
        q = f'INSERT OR IGNORE INTO "{name}" VALUES ({",".join("?" * len(cols))})'
        n, buf = 0, []
        for r in ([first] if first is not None else []):
            buf.append([val(r.get(c)) for c in cols])
        for r in rows:
            buf.append([val(r.get(c)) for c in cols])
            if len(buf) >= batch:
                self.c.executemany(q, buf)
                n += len(buf)
                buf = []
        if buf:
            self.c.executemany(q, buf)
            n += len(buf)
        for ix in indexes:
            self.c.execute(f'CREATE INDEX "ix_{name}_{ix}" ON "{name}"("{ix}")')
        self.c.commit()
        self.counts[name] = self.c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        self.offered[name] = n
        lost = f"  ({n - self.counts[name]:,} dropped on {pk})" if n != self.counts[name] else ""
        print(f"  {name:28s} {self.counts[name]:>10,}{lost}", flush=True)


SEC = {}   # (paper_id, section_id_original) -> section text, filled in main()


def _alnum(text):
    """Lower-case alphanumerics of text and, for each kept char, its index in text."""
    keep = [(ch.lower(), i) for i, ch in enumerate(text) if ch.isalnum()]
    return "".join(k for k, _ in keep), [i for _, i in keep]


def anchor_span(text, quote, start, end):
    """Locate a stored quote in its section (template rule 5: quote == text[start:end]).

    Returns (status, start, end): EXACT, WHITESPACE (offsets right, spacing differs), RELOCATED (same text
    elsewhere in the section), NORMALISED (matches ignoring punctuation / Unicode), FUZZY (>= 90% of the
    quote's characters align near the offsets, within 1.5x its length), UNANCHORED."""
    if not text or not quote:
        return ("NO_EVIDENCE" if not quote else "NO_SECTION"), None, None
    if start is not None and end is not None and text[start:end] == quote:
        return "EXACT", start, end
    ws = lambda x: " ".join(x.split())
    if start is not None and end is not None and ws(text[start:end]) == ws(quote):
        return "WHITESPACE", start, end
    i = text.find(quote)
    if i >= 0:
        return "RELOCATED", i, i + len(quote)
    pat = r"\s+".join(map(re.escape, quote.split()))
    m = re.search(pat, text) if pat else None
    if m:
        return "RELOCATED", m.start(), m.end()
    tq, _ = _alnum(quote)
    tt, ix = _alnum(text)
    if not tq:
        return "UNANCHORED", None, None
    j = tt.find(tq)
    if j >= 0:
        return "NORMALISED", ix[j], ix[j + len(tq) - 1] + 1
    # fuzzy: align inside a window around the stored offsets (or the whole section)
    lo = 0 if start is None else max(0, sum(1 for k in ix if k < start) - 300)
    hi = len(tt) if end is None else min(len(tt), sum(1 for k in ix if k < end) + 300)
    sm = difflib.SequenceMatcher(None, tq, tt[lo:hi], autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 3]
    ends = [b for b in blocks if b.size >= 8] or blocks   # span ends come from solid runs, not stray matches
    if blocks and sum(b.size for b in blocks) / len(tq) >= 0.9:
        a, z = lo + ends[0].b, lo + ends[-1].b + ends[-1].size - 1
        if z - a + 1 <= 1.5 * len(tq) + 20:   # a scattered alignment means a stitched or paraphrased quote
            return "FUZZY", ix[a], ix[z] + 1
    return "UNANCHORED", None, None


def anchored(f, quote_key, start_key, end_key, paper_id, section_id):
    """Add evidence_anchor_status / evidence_span(_start/_end); the stored quote is left unchanged."""
    text = SEC.get((paper_id, section_id))
    st, a, b = anchor_span(text, f.get(quote_key), f.get(start_key), f.get(end_key))
    f.update(evidence_anchor_status=st, evidence_span_start=a, evidence_span_end=b,
             evidence_span=text[a:b] if a is not None else None)
    return f


def catalogue(entity):
    for r in jl(CAT / "catalogue_records.jsonl"):
        if r["entity_type"] == entity:
            f = dict(r["fields"])
            f.update(section_id=r.get("section_id"), char_start=r.get("char_start"), char_end=r.get("char_end"),
                     evidence_verified=r.get("evidence_verified"), extraction_run_id=r.get("extraction_run_id"),
                     extraction_model=r.get("extraction_model"), review_status="UNVERIFIED")
            yield anchored(f, "evidence_text", "char_start", "char_end", f.get("paper_id"), f.get("section_id"))


def main(argv=None):
    global CAT
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(R / "cdm_v3/microbiome_cdm_v3.db"))
    ap.add_argument("--catalogue", default=str(CAT))
    ap.add_argument("--version", default="3.0.1")
    ap.add_argument("--skip_mentions", action="store_true", help="skip the 2.5M term mentions (testing)")
    args = ap.parse_args(argv)
    CAT = Path(args.catalogue)
    t0 = time.time()
    db = DB(Path(args.out))
    print("M1 source documents")
    papers = list(csv.DictReader(open(CAT / "catalogue_papers.csv", newline="", encoding="utf-8")))
    lic = {r["paper_id"]: r for r in csv.DictReader(open(R / "catalogue_v3_licences/paper_licences.csv", encoding="utf-8"))}
    corpus_p = {p["paper_id"]: p for p in jl(CORPUS / "papers.jsonl")}
    for p in papers:
        cp = corpus_p.get(p["paper_id"], {})
        p.update(license_name=lic.get(p["paper_id"], {}).get("license", p.get("license_name")),
                 duplicate_group_id=cp.get("duplicate_group_id"), canonical_paper_id=cp.get("canonical_paper_id"))
    db.table("paper", papers, pk="paper_id", indexes=("bioproject", "doi"))
    # publications: one row per DOI (else PMID, else the paper itself); BioProject->paper is many-to-one
    pubs, links = {}, []
    for p in papers:
        key = (p.get("doi") or "").lower().strip() or (f"pmid:{p['pmid']}" if p.get("pmid") else f"paper:{p['paper_id']}")
        pubs.setdefault(key, {"publication_id": f"HMPUB_{len(pubs) + 1:06d}", "doi": p.get("doi"), "pmid": p.get("pmid"),
                              "title": p.get("title"), "n_bioprojects": 0})
        pubs[key]["n_bioprojects"] += 1
        links.append({"paper_id": p["paper_id"], "bioproject": p.get("bioproject"),
                      "publication_id": pubs[key]["publication_id"]})
    for k, pu in pubs.items():
        pu["duplicate_status"] = "CONFLICTING" if pu["n_bioprojects"] > 1 else ""
    db.table("publication", pubs.values(), pk="publication_id")
    db.table("paper_publication", links, indexes=("publication_id",))
    secs = list(jl(CORPUS / "sections.jsonl"))
    SEC.update({(s["paper_id"], s["section_id_original"]): s.get("section_text_original") or "" for s in secs})
    db.table("source_asset", ({"paper_id": s["paper_id"], "source_file_hash_sha256": s.get("source_file_hash_sha256"),
                               "source_location": s.get("source_location")} for s in secs
                              if s.get("section_order") == 0))
    print("M2 document structure")
    db.table("section", ({k: s.get(k) for k in ("section_record_id", "paper_id", "section_id_original",
                          "section_name_original", "section_name_normalized", "section_type", "heading_path",
                          "section_order", "character_count", "word_count", "text_hash_sha256",
                          "section_text_original", "section_quality_status")} for s in secs),
             pk="section_record_id", indexes=("paper_id",))

    print("M3 processing")
    runs = [
        {"extraction_run_id": "CATNER_20261030T092214_1923898", "stage": "catalogue extraction v2", "model": "Qwen/Qwen3.5-4B"},
        {"extraction_run_id": "28619916", "stage": "terminology build 1.0.0", "model": "multi-NER + qwen3.5:4b"},
        {"extraction_run_id": "CATCLEAN_v3", "stage": "catalogue phase A cleanup", "model": "deterministic"},
        {"extraction_run_id": "CATLINK_v2", "stage": "catalogue phase B linking", "model": "Qwen/Qwen3.5-4B"},
    ]
    chain = (ROOT / "outputs/logs/gap/chain_jobs.txt")
    if chain.exists():
        for tok in chain.read_text().split():
            if "=" in tok and tok.split("=")[1].isdigit():
                st, jid = tok.split("=")
                runs.append({"extraction_run_id": jid, "stage": f"gap {st}", "model": ""})
    db.table("extraction_run", runs, pk="extraction_run_id")
    db.table("processing_event", jl(CORPUS / "processing_events.jsonl"), indexes=("paper_id",))
    db.table("processing_lineage", [
        {"parent_id": "CATNER_20261030T092214_1923898", "child_id": "CATCLEAN_v3", "relation": "input_of"},
        {"parent_id": "CATCLEAN_v3", "child_id": "CATLINK_v2", "relation": "input_of"},
        {"parent_id": "CATLINK_v2", "child_id": "gap G1", "relation": "input_of"},
        {"parent_id": "28619916", "child_id": "gap G8", "relation": "input_of"},
        {"parent_id": "28619916", "child_id": "gap G9", "relation": "input_of"},
    ])

    print("M4 terminology")
    terms = list(jl(DSR / "canonical_terms.reviewed.jsonl")) if (DSR / "canonical_terms.reviewed.jsonl").exists() \
        else list(jl(FROZEN / "02_data_catalogue/terminology/canonical_terms.jsonl"))
    db.table("canonical_term", terms, cols=sorted({k for t in terms[:2000] for k in t}), pk="term_id",
             indexes=("term_norm", "cdm_type"))
    if (DSR / "REMOVED_terms.jsonl").exists():
        db.table("removed_canonical_term", jl(DSR / "REMOVED_terms.jsonl"))
    live = {t["term_id"] for t in terms}
    gone = {t["term_id"] for t in jl(DSR / "REMOVED_terms.jsonl")} if (DSR / "REMOVED_terms.jsonl").exists() else set()

    def term_status(tid):
        # rows that point at a term not in canonical_term are kept and flagged, never silently dangling
        return "" if not tid or tid in live else ("REMOVED" if tid in gone else "NOT_IN_TERMINOLOGY")
    if not args.skip_mentions:
        # mention_id is per span, not per model (gliner_medium and gliner_biomed share ids), so the row
        # key adds the model; competing predictions stay separate rows (template rule)
        drop = {"supporting_passage"}
        cols = ["mention_row_id"] + [k for k in next(jl(TERM / "term_mentions.jsonl")) if k not in drop] \
            + ["canonical_term_status"]

        def mentions():
            for m in jl(TERM / "term_mentions.jsonl"):
                yield {**m, "mention_row_id": f"{m['mention_id']}|{m.get('extraction_model')}",
                       "canonical_term_status": term_status(m.get("canonical_term_id"))}
        db.table("term_mention", mentions(), cols=cols, pk="mention_row_id",
                 indexes=("mention_id", "paper_id", "canonical_term_id", "occurrence_key"))
        db.c.execute('CREATE TABLE term_occurrence AS SELECT occurrence_key, paper_id, section_id, '
                     'MIN(start_offset) AS start_offset, MAX(end_offset) AS end_offset, COUNT(*) AS n_mentions, '
                     'COUNT(DISTINCT extraction_model) AS n_models FROM term_mention GROUP BY occurrence_key')
        db.counts["term_occurrence"] = db.c.execute("SELECT COUNT(*) FROM term_occurrence").fetchone()[0]
        print(f"  {'term_occurrence':28s} {db.counts['term_occurrence']:>10,}")
    defs = list(jl(TERM / "term_definitions.jsonl"))
    g8 = GD / "G8/term_definitions_llm.jsonl"
    if g8.exists():
        for i, d in enumerate(jl(g8)):
            for tid in d["canonical_term_ids"] or [None]:
                defs.append({"definition_id": f"HMDEF_LLM_{i:07d}", "term_id": tid, "term": d["term"],
                             "paper_id": d["paper_id"], "section_id": d["section_id"],
                             "definition_text": d["definition_text"], "definition_char_start": d["char_start"],
                             "definition_char_end": d["char_end"], "definition_source": d["definition_source"],
                             "provenance_class": "SOURCE_DERIVED", "extraction_method": d["extraction_method"],
                             "extraction_run_id": "gap G8", "review_status": "REVIEW_REQUIRED"})
    if (DSR / "term_definitions.reviewed.jsonl").exists():  # DeepSeek-reviewed set replaces the raw union
        kept_ids = {d["_id"] for d in jl(DSR / "term_definitions.reviewed.jsonl")}
        verdict = {d["_id"]: d.get("verdict_deepseek") for d in jl(DSR / "term_definitions.reviewed.jsonl")}
        defs = [dict(d, verdict_deepseek=verdict.get(_did(d))) for d in defs if _did(d) in kept_ids]
        db.table("removed_term_definition", jl(DSR / "REMOVED_definitions.jsonl"))
    defs = [anchored(dict(d, term_status=term_status(d.get("term_id"))), "definition_text", "definition_char_start",
                     "definition_char_end", d.get("paper_id"), d.get("section_id")) for d in defs]
    db.table("term_definition", defs, cols=["definition_id", "term_id", "term", "paper_id", "section_id", "verdict_deepseek",
             "definition_text", "definition_char_start", "definition_char_end", "evidence_anchor_status", "evidence_span_start", "evidence_span_end",
             "definition_source", "term_status",
             "provenance_class", "extraction_method", "extraction_run_id", "review_status"], indexes=("term_id",))

    print("M5 semantic mappings")
    # mapping_id is not unique upstream (11,477 NO_MATCH rows have none; 3,506 ids are shared by different
    # term/concept rows), so rows get their own key and reviews attach on (mapping_id, term_id, concept_id)
    def mkey(r):
        return r.get("mapping_id"), r.get("term_id"), r.get("concept_id")
    ds_map = {mkey(r): r for r in jl(DSR / "term_concept_map.reviewed.jsonl")} if (DSR / "term_concept_map.reviewed.jsonl").exists() else {}
    ds_removed = {mkey(r) for r in jl(DSR / "REMOVED_mappings.jsonl")} if (DSR / "REMOVED_mappings.jsonl").exists() else set()
    g9 = {mkey(r): r for r in jl(GD / "G9/mapping_adjudication.jsonl")} if (GD / "G9/mapping_adjudication.jsonl").exists() else {}
    concepts = {}
    guard_files = (("kept", FROZEN / "02_data_catalogue/terminology/mapping_guards_v2/mapping_remapped.jsonl"),
                   ("rejected_guard", FROZEN / "02_data_catalogue/terminology/mapping_guards_v2/mapping_rejected.jsonl"))
    id_n = Counter(m["mapping_id"] for _, path in guard_files for m in jl(path) if m.get("mapping_id"))

    def maps():
        n = 0
        for name, path in guard_files:
            for m in jl(path):
                n += 1
                cid = m.get("concept_id")
                if cid and cid not in concepts:
                    concepts[cid] = {"concept_id": cid, "concept_label": m.get("concept_label"),
                                     "source_service": m.get("source_service"), "ontology_name": m.get("ontology_name")}
                a = g9.get(mkey(m), {})
                d = ds_map.get(mkey(m))
                yield {"mapping_row_id": f"HMMAPROW_{n:07d}", "mapping_id": m["mapping_id"],
                       "mapping_id_status": "MISSING" if not m.get("mapping_id") else
                       ("SHARED" if id_n[m["mapping_id"]] > 1 else ""),
                       "term_id": m["term_id"], "term_status": term_status(m["term_id"]), "concept_id": cid,
                       "candidate_rank": m.get("candidate_rank"), "is_canonical_candidate": m.get("is_canonical_candidate"),
                       "mapping_relation": m.get("mapping_relation"), "guard_status": name,
                       "mapping_disposition": a.get("mapping_disposition_after_g9") or m.get("mapping_disposition")
                       if name == "kept" else "REJECTED",
                       "relation_llm_g9": a.get("relation_llm"),
                       "relation_deepseek": (d or {}).get("relation_deepseek"),
                       "mapping_disposition_reviewed": ("REMOVED" if mkey(m) in ds_removed else
                                                        (d or {}).get("mapping_disposition")),
                       "review_status": m.get("review_status") or "REVIEW_REQUIRED"}
    db.table("term_concept_map", maps(), pk="mapping_row_id", indexes=("mapping_id", "term_id", "concept_id"))
    db.table("concept", concepts.values(), pk="concept_id")
    g11 = GD / "G11/term_taxonomy.jsonl"   # two-model classification (Qwen + Gemma); category only where they agree
    db.table("taxonomy_annotation", jl(g11) if g11.exists() else
             ({"term_id": t["term_id"], "taxonomy_version": "term_taxonomy_v1", "category": t.get("taxonomy_category"),
               "subcategory": t.get("taxonomy_subcategory")} for t in terms if t.get("taxonomy_category")),
             indexes=("term_id", "category"))
    g7 = GD / "G7/type_harmonization.jsonl"
    if g7.exists():
        db.table("type_harmonization", jl(g7))

    print("M6 research context")
    db.table("study", ({**s, "review_status": "UNVERIFIED"} for s in jl(CORPUS / "studies.jsonl")), pk="study_id",
             indexes=("paper_id",))
    for e, t in (("cohorts", "cohort"), ("samples", "sample"), ("assays", "assay")):
        db.table(t, catalogue(e), indexes=("paper_id",))
    bs = Counter()
    for e in ("samples", "findings"):
        for f in catalogue(e):
            if f.get("body_site_normalized"):
                bs[(f["body_site_normalized"], f.get("body_site_ontology_id"))] += 1
    db.table("body_site", ({"body_site_label": k[0], "ontology_id": k[1], "n_records": n} for k, n in bs.items()))
    iv = Counter()
    for f in catalogue("findings"):
        if f.get("intervention_category"):
            iv[(f["intervention_category"], f.get("intervention_agent") or "")] += 1
    db.table("intervention", ({"intervention_id": f"HMINT_{i + 1:05d}", "category": k[0], "agent": k[1], "n_findings": n}
                              for i, (k, n) in enumerate(sorted(iv.items()))), pk="intervention_id")

    print("M7 findings")

    def claims():
        for f in jl(CORPUS / "findings.jsonl"):
            yield {**f, "claim_source": "corpus_stage52", "review_status": f.get("verification_status") or "UNVERIFIED"}
        for f in catalogue("findings"):
            yield {**f, "claim_source": "catalogue_v3_1"}
    ccols = sorted({k for c in [next(jl(CORPUS / "findings.jsonl")), next(catalogue("findings"))] for k in c}
                   | {"claim_source", "review_status"})
    db.table("claim", claims(), cols=ccols, indexes=("paper_id", "finding_id"))
    db.c.execute("CREATE TABLE quantitative_result AS SELECT finding_id, claim_source, paper_id, effect_measure, "
                 "effect_estimate, confidence_interval, p_value, q_value FROM claim WHERE "
                 "COALESCE(effect_estimate,'') NOT IN ('', 'not_reported') OR COALESCE(p_value,'') NOT IN ('', 'not_reported')")
    db.counts["quantitative_result"] = db.c.execute("SELECT COUNT(*) FROM quantitative_result").fetchone()[0]
    db.c.execute("CREATE TABLE claim_evidence AS SELECT finding_id, claim_source, paper_id, "
                 "COALESCE(evidence_section_id, section_id) AS section_id, evidence_text, evidence_locator, "
                 "evidence_location, char_start, char_end, evidence_locator_status, evidence_anchor_status, "
                 "evidence_span_start, evidence_span_end, evidence_span FROM claim")
    db.counts["claim_evidence"] = db.c.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0]
    links = {}
    for p in (GD / "E/g6_direct.jsonl", GD / "G6/triple_entity_links.jsonl"):
        if p.exists():
            for r in jl(p):
                tid = r.get("term_id") or r.get("term_id_llm")
                if tid:
                    links[r["label"]] = (tid, r.get("method") or "G6_gemma")

    def link(label):
        tid, how = links.get(label, ("", ""))
        st = term_status(tid)
        return ("", how, st) if st else (tid, how, "LINKED" if tid else "UNLINKED")   # link to a removed term is dropped

    def rel(t):
        s, o = link(t.get("subject_display_label")), link(t.get("object_display_label"))
        return {"subject_term_id": s[0], "object_term_id": o[0], "entity_link_method": s[1] or o[1],
                "subject_link_status": s[2], "object_link_status": o[2]}
    db.table("relation", ({**t, **rel(t),
                           "review_status": t.get("human_review_status") or "UNVERIFIED"}
                          for t in jl(DSR / "canonical_triples.reviewed.jsonl" if (DSR / "canonical_triples.reviewed.jsonl").exists()
                                      else CORPUS / "canonical_triples.jsonl")), pk="canonical_triple_id")
    if (DSR / "REMOVED_triples.jsonl").exists():
        db.table("removed_relation", jl(DSR / "REMOVED_triples.jsonl"))

    print("M9 quality & review")
    qa = json.loads((CAT / "qa_report.json").read_text()) if (CAT / "qa_report.json").exists() else {"checks": {}}
    vr = [{"validation_result_id": f"QA_v3_1_{k}", "target": "catalogue_v3_1", "check": k, "passed": int(v)}
          for k, v in qa.get("checks", {}).items()]
    vr += [{"validation_result_id": f"CORPUS_{i}", "target": r.get("paper_id"), "check": "per_paper_validation",
            "passed": None, "detail": r} for i, r in enumerate(jl(CORPUS / "validation_per_paper.jsonl"))]
    db.table("validation_result", vr, cols=["validation_result_id", "target", "check", "passed", "detail"])
    ev = [{"evaluation_run_id": "JUDGE_V2_GEMMA_FULL", "target": "catalogue v2 / terminology", "method": "LLM-as-judge Gemma 4 E4B",
           "report": "releases/frozen_output/02_data_catalogue/judge/JUDGE_METRICS_FULL.md"},
          {"evaluation_run_id": "EVAL_V3_CLAUDE_400", "target": "catalogue v3.0.0", "method": "LLM-as-judge Claude Opus 5.5, 400-record sample",
           "report": "outputs/results/catalogue_v3_validation/EVALUATION_REPORT.md"}]
    if (GD / "G10/JUDGE_METRICS_V3_1.md").exists():
        ev.append({"evaluation_run_id": "JUDGE_V3_1_GEMMA_FULL", "target": "catalogue v3.1", "method": "LLM-as-judge Gemma 4 E4B, full census",
                   "report": "outputs/results/gap_runs/G10/JUDGE_METRICS_V3_1.md"})
    db.table("evaluation_run", ev, pk="evaluation_run_id")
    db.table("human_review", [], cols=["review_id", "target_entity", "target_id", "reviewer", "review_date",
                                       "decision", "notes"])

    print("M10 catalogue & releases")
    db.table("dataset", catalogue("datasets"), pk="dataset_id", indexes=("paper_id",))
    db.table("data_asset", catalogue("data_assets"), pk="asset_id", indexes=("paper_id", "dataset_id"))
    rel = []
    for m in sorted(ROOT.glob("releases/**/MANIFEST.sha256")):
        rel.append({"release_id": str(m.parent.relative_to(ROOT)), "manifest": str(m.relative_to(ROOT)),
                    "n_files": sum(1 for _ in open(m))})
    db.table("dataset_release", rel, pk="release_id")

    print("Compendium (Abdill et al. 2025) samples for the corpus BioProjects")
    bps = {p.get("bioproject") for p in papers}
    db.table("compendium_sample", (r for r in csv.DictReader(open(COMP / "sample_metadata.tsv", encoding="utf-8"),
                                                             delimiter="\t") if r["project"] in bps),
             pk="srs", indexes=("project",))
    with gzip.open(COMP / "tags.tsv.gz", "rt", encoding="utf-8") as fh:
        db.table("compendium_sample_tag", (r for r in csv.DictReader(fh, delimiter="\t") if r["project"] in bps),
                 indexes=("srs", "tag"))
    db.table("compendium_project", (r for r in csv.DictReader(open(COMP / "projects.csv", encoding="utf-8-sig"))
                                    if r["project"] in bps), pk="project")

    # template entity status table
    reg = list(csv.DictReader(open(ROOT / "src/template/cdm/cdm_entity_registry.csv", encoding="utf-8")))
    table_of = {e["entity"]: e["entity"].lower() for e in reg}
    st = []
    for e in reg:
        t = table_of[e["entity"]]
        n = db.counts.get(t)
        status = ("POPULATED" if n else "EMPTY") if n is not None else "NOT_A_TABLE"
        if e["entity"] in ("PARAGRAPH", "SENTENCE", "MODEL_RUN", "MENTION_EVIDENCE", "DEFINITION_EVIDENCE"):
            status = "EMBEDDED"  # carried as columns of term_mention / term_definition / extraction_run
        if e["entity"] == "HUMAN_REVIEW":
            status = "EMPTY_NO_HUMAN_REVIEW_YET"
        st.append({"entity": e["entity"], "module": e["module"], "table": t, "rows": n, "status": status})
    db.table("cdm_entity_status", st)
    db.table("load_audit", [{"table": t, "rows_offered": n, "rows_kept": db.counts[t], "rows_dropped": n - db.counts[t]}
                            for t, n in db.offered.items()])
    db.table("run_metadata", [{"key": "cdm_version", "value": args.version}, {"key": "built_at", "value": time.strftime("%Y-%m-%dT%H:%M:%S")},
                              {"key": "catalogue", "value": str(CAT.resolve().relative_to(ROOT))},
                              {"key": "template", "value": "src/template/cdm 0.1.0"},
                              {"key": "terminology", "value": str(TERM.relative_to(ROOT))},
                              {"key": "papers", "value": str(len(papers))}])
    db.c.execute("VACUUM")
    db.c.close()
    (Path(args.out).parent / "cdm_v3_counts.json").write_text(json.dumps(db.counts, indent=1) + "\n")
    print(f"built {args.out} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    raise SystemExit(main())
