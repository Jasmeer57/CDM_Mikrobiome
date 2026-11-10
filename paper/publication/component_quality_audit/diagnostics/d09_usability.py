"""D09 - usability: can the eight research questions actually be answered?

Two independent things are measured and kept strictly apart:

  1. REPRODUCIBILITY - does each *as-published* query still run against the frozen
     DB, and does it still return the published row/paper count? A query that no
     longer runs, or drifts, is a release-consistency defect regardless of the
     scientific merit of the question.
  2. DISCRIMINATION - does each query's answer depend on populated, non-placeholder
     values? A filter that matches on a placeholder, or on a pattern that also
     matches a *different* literal, returns papers for the wrong reason even when
     its paper count is stable.

Neither is an accuracy measure. There is no gold standard for "IBD studies using
16S sequencing", so no precision or recall is reported here, and the published
CDM-vs-keyword Jaccard is restated as agreement between two automated readers -
it is not accuracy of either.

Where the published SQL is weak, the finding is reported with the *corrected*
count alongside, so the size of the gap is visible without asserting which number
is scientifically right.

Read-only. Stdlib only.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import AUDIT, REPO, connect, emit  # noqa: E402

OUT: dict = {"diagnostic": "d09_usability", "db": "releases/cdm_v3/3.0.3"}

REG_DIR = (REPO / "releases/cdm_v3/3.0.3/remediation/regression/"
           "cdm_validation_current_registry")
RESEARCH = REG_DIR / "RESEARCH_QUERY_VALIDATION.csv"
COMPARISON = REPO / "paper/publication/final_validation/queries/QUERY_COMPARISON.csv"
PAPERS_TXT = REPO / "data/papers_txt"

# Placeholder tokens that mean "we do not know". A filter that accepts these is
# accepting absence as a value.
SENTINELS = ("NOT_REPORTED", "NOT_DEPOSITED", "NOT_APPLICABLE", "NOT_ACCESSIBLE",
             "CONFLICTING", "UNKNOWN", "NA", "N/A", "NONE", "UNSPECIFIED",
             "NOT_STATED", "NOT_REPORTED_IN_PAPER", "")


def read_research_queries():
    if not RESEARCH.exists():
        return {"present": False, "path": str(RESEARCH)}
    rows = []
    with open(RESEARCH, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    return {"present": True, "path": str(RESEARCH), "n": len(rows), "rows": rows}


def read_comparison():
    if not COMPARISON.exists():
        return {"present": False, "path": str(COMPARISON)}
    out = []
    with open(COMPARISON, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            out.append(r)
    return {"present": True, "path": str(COMPARISON), "n": len(out), "rows": out}


def tables_and_columns(con):
    cols = {}
    for (t,) in con.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
    ):
        cols[t] = {r[1] for r in con.execute('PRAGMA table_info("%s")' % t)}
    return cols


def referenced_columns(sql):
    """Resolve alias.column references in a SELECT against the real schema."""
    s = re.sub(r"--[^\n]*", " ", sql or "")
    s = re.sub(r"'[^']*'", "''", s)
    pairs = set()
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", s):
        pairs.add((m.group(1).lower(), m.group(2)))
    aliases = {}
    for m in re.finditer(
        r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*)?",
        s, re.I,
    ):
        tbl, al = m.group(1), m.group(2)
        if al and al.upper() in ("ON", "WHERE", "JOIN", "LEFT", "INNER", "GROUP",
                                 "ORDER", "USING", "AND", "OR"):
            al = None
        aliases[(al or tbl).lower()] = tbl
    return pairs, aliases


def run_queries(con, qdoc, colmap):
    results = []
    if not qdoc.get("present"):
        return results
    for r in qdoc["rows"]:
        sql = (r.get("sql") or "").strip()
        entry = {
            "query_id": r.get("query_id"),
            "question": (r.get("research_question") or "")[:120],
            "published_returned_rows": r.get("returned_rows"),
            "published_returned_papers": r.get("returned_papers"),
        }
        if not sql:
            entry["status"] = "NO_SQL_STORED"
            results.append(entry)
            continue
        pairs, aliases = referenced_columns(sql)
        unknown = []
        for al, col in sorted(pairs):
            tbl = aliases.get(al)
            if tbl is None:
                unknown.append("%s.%s (alias resolves to no table)" % (al, col))
            elif col not in colmap.get(tbl, set()):
                unknown.append("%s.%s -> table %s has no such column" % (al, col, tbl))
        entry["referenced_alias_columns"] = len(pairs)
        entry["unresolvable_column_refs"] = unknown
        try:
            cur = con.execute(sql)
            rows = cur.fetchall()
            one_col = len(cur.description or []) == 1
            papers = {row[1] for row in rows if len(row) > 1 and row[1]} if not one_col \
                else {row[0] for row in rows if row}
            entry["status"] = "RUNS"
            entry["rerun_rows"] = len(rows)
            entry["rerun_papers"] = len(papers)
            entry["rows_are_paper_ids"] = one_col
            pub_r, pub_p = r.get("returned_rows"), r.get("returned_papers")
            entry["row_count_matches_published"] = (
                str(pub_r) == str(len(rows)) if pub_r not in (None, "") else None)
            entry["paper_count_matches_published"] = (
                str(pub_p) == str(len(papers)) if pub_p not in (None, "") else None)
        except Exception as e:  # noqa: BLE001 - report, never swallow
            entry["status"] = "FAILS"
            entry["error"] = "%s: %s" % (type(e).__name__, e)
        results.append(entry)
    return results


def q7_storage_filter_audit(con):
    """Q7 uses `storage_condition LIKE '%80%'`. What else does '%80%' match?"""
    stool = ("(lower(coalesce(sample_type_normalized, sample_type, '')) like '%stool%' "
             "or lower(coalesce(sample_type_normalized, sample_type, '')) like '%fec%' "
             "or lower(coalesce(sample_type_normalized, sample_type, '')) like '%faec%')")
    published = con.execute(
        "select count(*), count(distinct paper_id) from sample where %s "
        "and storage_condition like '%%80%%'" % stool).fetchone()

    # A signed minus in any of the common Unicode dashes, optional space.
    signed = ("(storage_condition like '%-80%' or storage_condition like '%\u221280%' "
              "or storage_condition like '%\u201380%' or storage_condition like '%\u201480%')")
    corrected = con.execute(
        "select count(*), count(distinct paper_id) from sample where %s and %s"
        % (stool, signed)).fetchone()

    vals = [r[0] for r in con.execute(
        "select distinct storage_condition from sample where %s "
        "and storage_condition like '%%80%%'" % stool)]
    classes = {"signed_minus_80": 0, "minus_lost_280_OR_80": 0, "other": 0}
    offenders = []
    for v in vals:
        n = re.sub(r"[\u2212\u2013\u2014]", "-", v)
        if re.search(r"-\s*80", n):
            classes["signed_minus_80"] += 1
        elif re.search(r"(?<![0-9])280\s*[\u00b0\u02dauU]?\s*C", n) or \
                re.search(r"(?<![0-9])80\s*[\u00b0\u02da uU]?\s*C", n):
            classes["minus_lost_280_OR_80"] += 1
            offenders.append(v[:100])
        else:
            classes["other"] += 1
            offenders.append(v[:100])

    only_published = con.execute(
        "select count(distinct paper_id) from sample where %s "
        "and storage_condition like '%%80%%' and not %s" % (stool, signed)).fetchone()[0]
    any_stool = con.execute(
        "select count(*), count(distinct paper_id) from sample where %s" % stool).fetchone()

    return {
        "published_sql": "storage_condition LIKE '%80%'",
        "stool_and_like80_rows": published[0],
        "stool_and_like80_papers": published[1],
        "stool_and_signed_minus80_rows": corrected[0],
        "stool_and_signed_minus80_papers": corrected[1],
        "papers_counted_only_because_minus_was_accepted": only_published,
        "stool_rows_total": any_stool[0],
        "stool_papers_total": any_stool[1],
        "distinct_matching_values": len(vals),
        "value_classes": classes,
        "offending_value_examples": offenders[:12],
        "interpretation": (
            "LIKE '%80%' also accepts text where the minus sign was lost upstream "
            "('-80 C' written as '280 C' or '80 C'), so Q7 over-counts. The error is "
            "inherited from the corpus text, not introduced by the query, but the "
            "query does not defend against it."),
    }


def minus_loss_corpus_census():
    """How widespread is minus-loss in the source text? Independent of the CDM."""
    if not PAPERS_TXT.exists():
        return {"present": False}
    p280 = re.compile(r"(?<![0-9\u2212\-\u2013\u2014])280\s*[\u00b0\u02dauU]?\s*C")
    p80 = re.compile(r"(?<![0-9\u2212\-\u2013\u2014])80\s*[\u00b0\u02dauU]?\s*C")
    files = sorted(glob.glob(str(PAPERS_TXT / "*.txt")))
    n280 = n80 = 0
    papers = []
    for f in files:
        try:
            t = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        a, b = len(p280.findall(t)), len(p80.findall(t))
        if a or b:
            n280 += a
            n80 += b
            papers.append(os.path.basename(f)[:-4])
    return {
        "present": True,
        "files_scanned": len(files),
        "minus_lost_280C_occurrences": n280,
        "minus_lost_80C_occurrences": n80,
        "papers_affected": len(papers),
        "pct_papers_affected": round(100.0 * len(papers) / max(1, len(files)), 2),
        "example_papers": papers[:12],
        "interpretation": (
            "These are literal '280 C' / '80 C' strings with no preceding sign, in "
            "freezers/temperature context. They are upstream PDF-extraction damage "
            "in data/papers_txt/ and therefore present in the frozen corpus and the "
            "CDM section text. Any '%80%' filter (Q7) or any downstream numeric "
            "reading of storage temperature is exposed to them."),
    }


def q4_accession_audit(con):
    """Q4 filters accession_valid='YES' + a placeholder blocklist. Is that sound?"""
    marks = ", ".join("?" for _ in SENTINELS)
    yes_rows = con.execute(
        "select count(*) from dataset where accession_valid='YES'").fetchone()[0]
    yes_papers = con.execute(
        "select count(distinct paper_id) from dataset where accession_valid='YES'").fetchone()[0]
    yes_with_sentinel = con.execute(
        "select count(*) from dataset where accession_valid='YES' and "
        "upper(trim(coalesce(repository_accession,''))) in (%s)" % marks,
        SENTINELS).fetchone()[0]
    any_rows = con.execute(
        "select count(*) from dataset where coalesce(repository_accession,'')<>''").fetchone()[0]
    sentinel_any = con.execute(
        "select count(*) from dataset where upper(trim(coalesce(repository_accession,''))) "
        "in (%s)" % marks, SENTINELS).fetchone()[0]
    return {
        "yes_rows": yes_rows,
        "yes_papers": yes_papers,
        "yes_distinct_accessions": con.execute(
            "select count(distinct repository_accession) from dataset "
            "where accession_valid='YES'").fetchone()[0],
        "yes_rows_carrying_a_placeholder": yes_with_sentinel,
        "nonempty_accession_rows": any_rows,
        "nonempty_but_placeholder": sentinel_any,
        "pct_nonempty_that_are_placeholders": round(
            100.0 * sentinel_any / max(1, any_rows), 2),
        "accession_valid_domain": [[r[0], r[1]] for r in con.execute(
            "select coalesce(accession_valid,'(null)'), count(*) c from dataset "
            "group by 1 order by c desc")],
        "interpretation": (
            "The as-published Q4 does defend against placeholders, both through the "
            "accession_valid flag and an explicit blocklist; it is the soundest of "
            "the eight filters. The placeholder census is reported because it shows "
            "how large the trap was: a naive 'accession is not null and non-empty' "
            "filter would have matched the placeholder population instead."),
    }


def answerability_profile(con):
    def one(sql):
        try:
            return con.execute(sql).fetchone()[0]
        except Exception as e:  # noqa: BLE001
            return "ERR:%s" % e

    return {
        "papers_total": one("select count(*) from paper"),
        "papers_with_assay": one("select count(distinct paper_id) from assay"),
        "papers_with_cohort": one("select count(distinct paper_id) from cohort"),
        "papers_with_sample": one("select count(distinct paper_id) from sample"),
        "papers_with_claim": one("select count(distinct paper_id) from claim"),
        "papers_with_dataset": one("select count(distinct paper_id) from dataset"),
        "papers_with_typed_assay": one(
            "select count(distinct paper_id) from assay where assay_type_normalized "
            "is not null and trim(assay_type_normalized)<>''"),
        "papers_with_health_status": one(
            "select count(distinct paper_id) from cohort where health_status "
            "is not null and trim(health_status)<>''"),
        "papers_with_intervention": one(
            "select count(distinct paper_id) from claim where intervention_agent "
            "is not null and trim(intervention_agent)<>''"),
        "papers_with_storage": one(
            "select count(distinct paper_id) from sample where storage_condition "
            "is not null and trim(storage_condition)<>''"),
        "papers_with_linked_taxon": one(
            "select count(distinct paper_id) from claim where taxon_link_status='LINKED'"),
        "relations_total": one("select count(*) from relation"),
        "papers_reachable_via_relation_paper_ids": one(
            "select count(distinct paper_id) from paper where paper_id in "
            "(select distinct paper_id from claim)"),
        "note": ("relation has paper_ids (a list column) and paper_count, not a scalar "
                 "paper_id; per-paper triple reach is therefore a list-scan, not a join. "
                 "That is a usability cost, recorded but not scored as a defect."),
    }


def comparison_jaccard():
    c = read_comparison()
    if not c.get("present"):
        return c
    rows = []
    for r in c["rows"]:
        try:
            j = float(r.get("jaccard") or 0)
        except ValueError:
            j = None
        rows.append({
            "query_id": r.get("query_id"),
            "cdm_papers": int(r.get("cdm_papers") or 0),
            "text_rule_papers": int(r.get("text_papers") or 0),
            "both": int(r.get("both") or 0),
            "cdm_only": int(r.get("cdm_only") or 0),
            "text_only": int(r.get("text_only") or 0),
            "jaccard": j,
        })
    js = [r["jaccard"] for r in rows if r["jaccard"] is not None]
    return {
        "present": True,
        "rows": rows,
        "mean_jaccard": round(sum(js) / len(js), 3) if js else None,
        "min_jaccard": min(js) if js else None,
        "max_jaccard": max(js) if js else None,
        "caveat": ("Both sides are computational. The keyword rules match any paper "
                   "mentioning the criterion, so this is agreement between two "
                   "automated readers - not accuracy of either, and not validation "
                   "by a human."),
    }


def main():
    con = connect()
    colmap = tables_and_columns(con)

    qdoc = read_research_queries()
    OUT["research_query_package"] = {
        "present": qdoc.get("present"),
        "path": qdoc.get("path"),
        "n": qdoc.get("n"),
        "note": ("The usability report cites RESEARCH_QUERY_VALIDATION.csv but "
                 "paper/publication/final_validation does not contain it. The only "
                 "copies are under releases/cdm_v3/3.0.3/remediation/regression/ and "
                 "outputs/. The query package is therefore stored inside the release "
                 "it validates, not beside the publication materials."),
    }
    OUT["query_reproduction"] = run_queries(con, qdoc, colmap)
    OUT["q7_storage_filter"] = q7_storage_filter_audit(con)
    OUT["minus_loss_corpus_census"] = minus_loss_corpus_census()
    OUT["q4_accession"] = q4_accession_audit(con)
    OUT["answerability"] = answerability_profile(con)
    OUT["published_comparison"] = comparison_jaccard()

    q = OUT["research_query_package"]
    print("=== research query package === present=%s n=%s" % (q["present"], q["n"]))
    print("  " + q["note"])

    print("\n=== query reproduction (as published) ===")
    ok = 0
    for r in OUT["query_reproduction"]:
        st = r["status"]
        extra = ""
        if st == "RUNS":
            extra = (" rows=%s/%s papers=%s/%s" % (
                r["rerun_rows"], r["published_returned_rows"],
                r["rerun_papers"], r["published_returned_papers"]))
            if r["row_count_matches_published"] and r["paper_count_matches_published"]:
                ok += 1
                extra += "  MATCH"
            else:
                extra += "  DRIFT"
        elif st == "FAILS":
            extra = "  " + r["error"][:100]
        bad = r.get("unresolvable_column_refs") or []
        if bad:
            extra += "  BADREFS=%s" % bad[:3]
        print("  %-3s %-11s%s" % (r["query_id"], st, extra))
    print("  -> %d/%d reproduce exactly" % (ok, len(OUT["query_reproduction"])))

    s = OUT["q7_storage_filter"]
    print("\n=== Q7 storage filter audit (LIKE '%%80%%') ===")
    print("  published: %s rows / %s papers" % (
        format(s["stool_and_like80_rows"], ","), s["stool_and_like80_papers"]))
    print("  signed-minus-80 only: %s rows / %s papers" % (
        format(s["stool_and_signed_minus80_rows"], ","),
        s["stool_and_signed_minus80_papers"]))
    print("  papers counted only because the minus was dropped: %s" %
          s["papers_counted_only_because_minus_was_accepted"])
    print("  distinct matching values: %s -> %s" % (
        s["distinct_matching_values"], s["value_classes"]))
    for v in s["offending_value_examples"][:6]:
        print("     ", repr(v))

    m = OUT["minus_loss_corpus_census"]
    print("\n=== minus-loss census in data/papers_txt (corpus, not CDM) ===")
    print("  files=%s  '280 C'=%s  '80 C'=%s  papers affected=%s (%s%%)" % (
        m["files_scanned"], m["minus_lost_280C_occurrences"],
        m["minus_lost_80C_occurrences"], m["papers_affected"],
        m["pct_papers_affected"]))

    a = OUT["q4_accession"]
    print("\n=== Q4 accession filter audit ===")
    print("  accession_valid='YES': %s rows / %s papers / %s distinct accessions" % (
        format(a["yes_rows"], ","), a["yes_papers"], a["yes_distinct_accessions"]))
    print("  YES rows carrying a placeholder: %s" % a["yes_rows_carrying_a_placeholder"])
    print("  non-empty accessions that are placeholders: %s (%s%%)" % (
        format(a["nonempty_but_placeholder"], ","),
        a["pct_nonempty_that_are_placeholders"]))

    print("\n=== answerability ===")
    for k, v in OUT["answerability"].items():
        if isinstance(v, int):
            print("  %-42s %s" % (k, format(v, ",")))

    c = OUT["published_comparison"]
    if c.get("present"):
        print("\n=== published CDM-vs-keyword agreement (restated, not rescored) ===")
        for r in c["rows"]:
            print("  %s cdm=%4d text=%4d both=%4d cdm_only=%3d text_only=%3d J=%s" % (
                r["query_id"], r["cdm_papers"], r["text_rule_papers"], r["both"],
                r["cdm_only"], r["text_only"], r["jaccard"]))
        print("  mean J=%s range %s-%s" % (
            c["mean_jaccard"], c["min_jaccard"], c["max_jaccard"]))

    emit("d09_usability", OUT)


if __name__ == "__main__":
    main()
