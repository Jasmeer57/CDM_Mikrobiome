"""Quality checks for a CDM v3 SQLite build (no model calls).

Checks: corpus = 453 papers, rows dropped at load, referential integrity, references to
removed records, exact-quote anchoring (template rule 5) of definitions / mentions / claims /
catalogue records, review status, per-paper coverage and key-field fill rates. Writes
<out>/qa_cdm_report.json and <out>/QA_CDM.md.

    python qa_cdm_v3.py --db releases/cdm_v3/3.0.1/microbiome_cdm_v3.db --out outputs/results/cdm_v3_qa/3.0.1
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
N_PAPERS = 453
SAMPLE = 20000

# (table, column, target table, target column) — every non-empty value must resolve
FKS = [
    ("term_mention", "canonical_term_id", "canonical_term", "term_id"),
    ("term_mention", "paper_id", "paper", "paper_id"),
    ("term_definition", "term_id", "canonical_term", "term_id"),
    ("term_concept_map", "term_id", "canonical_term", "term_id"),
    ("term_concept_map", "concept_id", "concept", "concept_id"),
    ("relation", "subject_term_id", "canonical_term", "term_id"),
    ("relation", "object_term_id", "canonical_term", "term_id"),
    ("taxonomy_annotation", "term_id", "canonical_term", "term_id"),
    ("type_harmonization", "term_id", "canonical_term", "term_id"),
    ("section", "paper_id", "paper", "paper_id"),
    ("study", "paper_id", "paper", "paper_id"),
    ("claim", "paper_id", "paper", "paper_id"),
    ("claim", "dataset_id", "dataset", "dataset_id"),
    ("claim", "cohort_id", "cohort", "cohort_id"),
    ("claim", "assay_id", "assay", "assay_id"),
    ("cohort", "dataset_id", "dataset", "dataset_id"),
    ("sample", "dataset_id", "dataset", "dataset_id"),
    ("sample", "cohort_id", "cohort", "cohort_id"),
    ("assay", "dataset_id", "dataset", "dataset_id"),
    ("data_asset", "dataset_id", "dataset", "dataset_id"),
    ("paper_publication", "publication_id", "publication", "publication_id"),
    ("compendium_sample", "project", "paper", "bioproject"),
    ("compendium_project", "project", "paper", "bioproject"),
]
PAPER_TABLES = ["section", "study", "term_mention", "term_definition", "claim", "cohort", "sample", "assay",
                "dataset", "data_asset"]
FILL = {
    "paper": ["doi", "title", "keywords", "primary_research_domain", "human_study_design", "data_availability_status",
              "license_name"],
    "cohort": ["country_or_region", "participant_count", "health_status", "age_group"],
    "sample": ["body_site_normalized", "sample_type_normalized", "collection_method", "storage_condition"],
    "assay": ["assay_type_normalized", "sequencing_platform", "target_gene_or_region", "dna_extraction_method",
              "bioinformatics_pipeline"],
    "dataset": ["repository_name", "repository_accession", "data_availability_status", "license_or_terms"],
    "relation": ["subject_term_id", "object_term_id"],
}
MISSING_CODES = ("NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING")


def cols(c, t):
    return [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]


def has(c, t):
    return c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone() is not None


def anchor_check(c, label, sql, sec, rng):
    """sql yields (paper_id, section_id, start, end, quote); quote must equal section_text[start:end]."""
    tbl = sql.split(" FROM ")[1].split()[0].strip('"')
    if not has(c, tbl):
        return {"check": label, "rows": 0, "with_offsets": 0, "sampled": 0, "exact": 0, "whitespace_only_diff": 0,
                "section_not_found": 0, "mismatch": 0, "exact_pct": None, "mismatch_examples": []}
    rows = c.execute(sql).fetchall()
    with_off = [r for r in rows if r[2] is not None and r[3] is not None and r[4]]
    sample = rng.sample(with_off, min(SAMPLE, len(with_off)))
    exact = ws = bad_sec = 0
    examples = []
    for pid, sid, a, b, q in sample:
        t = sec.get((pid, sid))
        if t is None:
            bad_sec += 1
            continue
        span = t[int(a):int(b)]
        if span == q:
            exact += 1
        elif " ".join(span.split()) == " ".join(str(q).split()):
            ws += 1
        elif len(examples) < 5:
            examples.append({"paper_id": pid, "section_id": sid, "quote": str(q)[:120], "span": span[:120]})
    n = len(sample)
    return {"check": label, "rows": len(rows), "with_offsets": len(with_off), "sampled": n,
            "exact": exact, "whitespace_only_diff": ws, "section_not_found": bad_sec,
            "mismatch": n - exact - ws - bad_sec,
            "exact_pct": round(100 * exact / n, 2) if n else None, "mismatch_examples": examples}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    rep, fails, warns = {}, [], []
    one = lambda q, *p: c.execute(q, p).fetchone()[0]

    # corpus
    papers = {r[0] for r in c.execute("SELECT paper_id FROM paper")}
    rep["papers"] = len(papers)
    if len(papers) != N_PAPERS:
        fails.append(f"paper table has {len(papers)} papers, expected {N_PAPERS}")
    cov = {}
    for t in PAPER_TABLES:
        if has(c, t):
            ids = {r[0] for r in c.execute(f'SELECT DISTINCT paper_id FROM "{t}"')}
            cov[t] = {"papers_with_rows": len(ids & papers), "unknown_paper_ids": len(ids - papers - {None, ""})}
            if cov[t]["unknown_paper_ids"]:
                fails.append(f"{t}: {cov[t]['unknown_paper_ids']} paper_ids not in paper")
    rep["paper_coverage"] = cov

    # load losses
    if has(c, "load_audit"):
        la = [dict(zip(("table", "offered", "kept", "dropped"), r)) for r in
              c.execute('SELECT "table", rows_offered, rows_kept, rows_dropped FROM load_audit WHERE rows_dropped > 0')]
        rep["load_dropped"] = la
        for r in la:
            (warns if r["dropped"] < 100 else fails).append(f"{r['table']}: {r['dropped']:,} rows dropped at load")
    else:
        warns.append("no load_audit table (build predates 3.0.1)")

    # referential integrity: catalogue links may hold several ids ("A; B"); rows flagged in
    # term_status / canonical_term_status (REMOVED, NOT_IN_TERMINOLOGY) are counted apart, not as dangling
    fk = []
    for t, col, tt, tc in FKS:
        if not (has(c, t) and has(c, tt) and col in cols(c, t)):
            continue
        target = {r[0] for r in c.execute(f'SELECT "{tc}" FROM "{tt}" WHERE "{tc}" IS NOT NULL')}
        tcs = cols(c, t)
        flag_col = next((f for f in ("term_status", "canonical_term_status") if f in tcs and "term" in col), None)
        sel = f'SELECT "{col}", {f"{flag_col}" if flag_col else "NULL"} FROM "{t}" WHERE COALESCE("{col}", \'\') != \'\''
        tot = dang = flagged = 0
        for v, fl in c.execute(sel):
            tot += 1
            ids = [x.strip() for x in str(v).split(";") if x.strip()]
            if all(i in target for i in ids):
                continue
            if fl:
                flagged += 1
            else:
                dang += 1
        fk.append({"fk": f"{t}.{col} -> {tt}.{tc}", "non_empty": tot, "dangling": dang, "flagged": flagged,
                   "dangling_pct": round(100 * dang / tot, 2) if tot else 0})
        if dang:
            (fails if dang / max(tot, 1) > 0.01 else warns).append(f"{t}.{col}: {dang:,}/{tot:,} dangling")
        if flagged:
            warns.append(f"{t}.{col}: {flagged:,} rows point at removed / unknown terms (flagged)")
    rep["foreign_keys"] = fk

    # references to records the review removed
    rm = {}
    if has(c, "removed_canonical_term"):
        rm_terms = "(SELECT term_id FROM removed_canonical_term)"
        for t, col in (("term_mention", "canonical_term_id"), ("term_definition", "term_id"),
                       ("term_concept_map", "term_id"), ("relation", "subject_term_id"), ("relation", "object_term_id")):
            if has(c, t):
                rm[f"{t}.{col}"] = one(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IN {rm_terms}')
        if "canonical_term_status" in cols(c, "term_mention"):
            rm["term_mention flagged REMOVED"] = one("SELECT COUNT(*) FROM term_mention WHERE canonical_term_status='REMOVED'")
    if has(c, "removed_relation"):
        rm["relation also in removed_relation"] = one(
            "SELECT COUNT(*) FROM relation WHERE canonical_triple_id IN (SELECT canonical_triple_id FROM removed_relation)")
        if rm["relation also in removed_relation"]:
            fails.append("removed triples still present in relation")
    rep["removed_references"] = rm

    # duplicates in key columns
    dups = {}
    for t, col in (("canonical_term", "term_id"), ("term_mention", "mention_id"), ("term_concept_map", "mapping_id"),
                   ("relation", "canonical_triple_id"), ("claim", "finding_id"), ("cohort", "cohort_id"),
                   ("sample", "sample_group_id"), ("assay", "assay_id"), ("dataset", "dataset_id")):
        if has(c, t) and col in cols(c, t):
            dups[f"{t}.{col}"] = {"null": one(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IS NULL'),
                                  "ids_repeated": one(f'SELECT COUNT(*) FROM (SELECT "{col}" FROM "{t}" WHERE "{col}" '
                                                      f'IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1)')}
    rep["key_duplicates"] = dups

    # exact-quote anchoring (template rule 5)
    sec = {(p, s): t for p, s, t in c.execute("SELECT paper_id, section_id_original, section_text_original FROM section")}
    sec.update({(p, r): t for p, r, t in c.execute("SELECT paper_id, section_record_id, section_text_original FROM section")})
    anc = [anchor_check(c, "term_definition", "SELECT paper_id, section_id, definition_char_start, definition_char_end, "
                        "definition_text FROM term_definition", sec, rng),
           anchor_check(c, "term_mention", "SELECT paper_id, section_id, start_offset, end_offset, surface_form "
                        "FROM term_mention", sec, rng)]
    for t in ("claim", "cohort", "sample", "assay", "dataset", "data_asset"):
        where = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
        anc.append(anchor_check(c, t, f'SELECT paper_id, section_id, char_start, char_end, evidence_text FROM "{t}"{where}',
                                sec, rng))
        if has(c, t) and "evidence_span" in cols(c, t):
            a = anchor_check(c, f"{t} (re-anchored span)", f'SELECT paper_id, section_id, evidence_span_start, '
                             f'evidence_span_end, evidence_span FROM "{t}"{where}', sec, rng)
            a["anchor_status"] = dict(c.execute(f'SELECT COALESCE(evidence_anchor_status, "(null)"), COUNT(*) '
                                                f'FROM "{t}"{where} GROUP BY 1').fetchall())
            anc.append(a)
    rep["anchoring"] = anc
    for a in anc:
        if not a["sampled"]:
            continue
        a["anchored_pct"] = round(100 * (a["exact"] + a["whitespace_only_diff"]) / a["sampled"], 2)
        reanchored = any(x["check"] == f"{a['check']} (re-anchored span)" for x in anc)
        if a["anchored_pct"] < 95:
            (warns if reanchored or a["anchored_pct"] >= 80 else fails).append(
                f"{a['check']}: {a['anchored_pct']}% of quotes found at their offsets")
        if a["exact_pct"] < 95 <= a["anchored_pct"]:
            warns.append(f"{a['check']}: {a['exact_pct']}% byte-exact; rest differ only in whitespace (template rule 5)")

    # review status (no human review exists, so nothing may be ACCEPTED by a human)
    rs = {}
    for t in ("canonical_term", "term_mention", "term_definition", "term_concept_map", "relation", "claim", "cohort",
              "sample", "assay", "dataset"):
        if has(c, t) and "review_status" in cols(c, t):
            rs[t] = dict(c.execute(f'SELECT COALESCE(review_status, "(null)"), COUNT(*) FROM "{t}" GROUP BY 1').fetchall())
            if rs[t].get("(null)"):
                warns.append(f"{t}: {rs[t]['(null)']:,} rows without review_status")
    rep["review_status"] = rs
    if has(c, "human_review") and one("SELECT COUNT(*) FROM human_review") == 0:
        acc = {t: v.get("ACCEPTED", 0) for t, v in rs.items() if v.get("ACCEPTED")}
        if acc:
            fails.append(f"review_status ACCEPTED without any human review: {acc}")

    # fill rates
    fill = {}
    for t, cs in FILL.items():
        if not has(c, t):
            continue
        n = one(f'SELECT COUNT(*) FROM "{t}"')
        tc = cols(c, t)
        fill[t] = {"rows": n}
        for col in cs:
            if col not in tc:
                continue
            v = one(f'SELECT COUNT(*) FROM "{t}" WHERE COALESCE(TRIM("{col}"), \'\') != \'\' '
                    f'AND "{col}" NOT IN ({",".join("?" * len(MISSING_CODES))})', *MISSING_CODES)
            m = one(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IN ({",".join("?" * len(MISSING_CODES))})', *MISSING_CODES)
            fill[t][col] = {"value_pct": round(100 * v / n, 1) if n else 0, "missing_code_pct": round(100 * m / n, 1) if n else 0}
    rep["fill_rates"] = fill

    # template entity status
    if has(c, "cdm_entity_status"):
        rep["entity_status"] = dict(c.execute("SELECT status, COUNT(*) FROM cdm_entity_status GROUP BY 1").fetchall())
        rep["empty_entities"] = [r[0] for r in c.execute("SELECT entity FROM cdm_entity_status WHERE status LIKE 'EMPTY%'")]
    rep["fails"], rep["warnings"] = fails, warns
    rep["verdict"] = "FAIL" if fails else "PASS"
    (out / "qa_cdm_report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")

    L = [f"# CDM QA — {Path(args.db).parent.name}", "", f"Verdict: **{rep['verdict']}** "
         f"({len(fails)} fail, {len(warns)} warning). Papers: {rep['papers']}.", ""]
    L += ["## Fails", ""] + [f"- {f}" for f in fails] + ["", "## Warnings", ""] + [f"- {w}" for w in warns]
    L += ["", "## Exact-quote anchoring (sample of up to 20,000 rows each)", "",
          "| table | rows | with offsets | sampled | exact % | anchored % | whitespace-only | section missing | mismatch |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {a['check']} | {a['rows']:,} | {a['with_offsets']:,} | {a['sampled']:,} | {a['exact_pct']} | {a.get('anchored_pct')} | "
          f"{a['whitespace_only_diff']:,} | {a['section_not_found']:,} | {a['mismatch']:,} |" for a in anc]
    L += ["", "Anchor status of re-anchored tables: " + "; ".join(
        f"{a['check'].split()[0]} {a['anchor_status']}" for a in anc if "anchor_status" in a)]
    L += ["", "## Referential integrity", "", "| link | non-empty | dangling | flagged | % dangling |", "|---|---:|---:|---:|---:|"]
    L += [f"| `{f['fk']}` | {f['non_empty']:,} | {f['dangling']:,} | {f['flagged']:,} | {f['dangling_pct']} |" for f in fk]
    L += ["", "## References to removed records", ""] + [f"- {k}: {v:,}" for k, v in rm.items()]
    L += ["", "## Key duplicates", "", "| key | null | ids repeated |", "|---|---:|---:|"]
    L += [f"| `{k}` | {v['null']:,} | {v['ids_repeated']:,} |" for k, v in dups.items()]
    L += ["", "## Paper coverage (of 453)", "", "| table | papers with rows |", "|---|---:|"]
    L += [f"| {t} | {v['papers_with_rows']} |" for t, v in cov.items()]
    L += ["", "## Fill rates (value % / missing-code %)", ""]
    for t, d in fill.items():
        L.append(f"- **{t}** ({d['rows']:,} rows): " + "; ".join(
            f"{k} {v['value_pct']}% / {v['missing_code_pct']}%" for k, v in d.items() if k != "rows"))
    L += ["", f"Entity status: {rep.get('entity_status')}; empty: {rep.get('empty_entities')}", ""]
    (out / "QA_CDM.md").write_text("\n".join(L))
    print("\n".join(L[:12 + len(fails) + len(warns)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
