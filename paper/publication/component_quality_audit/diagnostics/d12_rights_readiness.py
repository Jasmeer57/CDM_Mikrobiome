"""D12 - rights and public-release readiness (component N).

Read-only. Tests whether the proposed release architecture is internally
consistent with what is actually inside the frozen CDM 3.0.3 and catalogue
3.1.1. Makes no legal determination.
"""
from __future__ import annotations

import collections
import csv
import json
import sqlite3

from common import AUDIT, DB, emit

RIGHTS = AUDIT.parent / "rights" / "PAPER_RIGHTS_MATRIX.csv"

SENTINEL_LICENCE = {"", "NONE_FOUND", "nan", "None"}


def cols(c, table):
    return [r[1] for r in c.execute("PRAGMA table_info(%s)" % table)]


def main():
    out = {}
    rows = list(csv.DictReader(open(RIGHTS, encoding="utf-8")))
    out["matrix_rows"] = len(rows)
    out["matrix_columns"] = list(rows[0].keys())

    out["licence"] = dict(collections.Counter(r["licence"] or "NONE_FOUND" for r in rows))
    out["decision"] = dict(collections.Counter(r["proposed_release_decision"] for r in rows))
    out["needs_legal"] = sum(1 for r in rows if r["needs_legal_confirmation"].strip().lower().startswith("yes"))
    out["needs_legal_by_reason"] = dict(
        collections.Counter(r["needs_legal_confirmation"].strip() for r in rows
                            if r["needs_legal_confirmation"].strip().lower().startswith("yes"))
    )
    out["reviewer_filled"] = sum(1 for r in rows if r["rights_reviewer"].strip())
    out["final_decision_filled"] = sum(1 for r in rows if r["final_decision"].strip())
    out["publisher_filled"] = sum(1 for r in rows if r["publisher"].strip())

    # decision consistency: quote policy applied in catalogue vs proposed decision
    out["quote_policy"] = dict(collections.Counter(r["quote_policy_applied_in_catalogue_3_1_1"] for r in rows))
    cross = collections.Counter(
        (r["quote_policy_applied_in_catalogue_3_1_1"], r["proposed_release_decision"]) for r in rows
    )
    out["quote_policy_x_decision"] = {"%s|%s" % k: v for k, v in cross.most_common()}
    inc = {r["paper_id"] for r in rows if r["proposed_release_decision"] == "INCLUDE_TEXT"}
    keep = {r["paper_id"] for r in rows if r["quote_policy_applied_in_catalogue_3_1_1"] == "KEEP"}
    out["include_text_not_keep"] = sorted(inc - keep)[:20]
    out["keep_not_include_text"] = sorted(keep - inc)[:20]
    out["include_n"] = len(inc)
    out["keep_n"] = len(keep)

    # per-layer permission agreement within a row (internal consistency of the matrix itself)
    def ok(r, f):
        return (r[f] or "").strip().lower().startswith(("allow", "yes"))

    out["row_level_layers"] = {
        "full_text_allowed": sum(1 for r in rows if ok(r, "full_text_redistribution")),
        "quotes_allowed": sum(1 for r in rows if ok(r, "verbatim_quotations")),
        "metadata_allowed": sum(1 for r in rows if ok(r, "bibliographic_metadata")),
        "annotations_allowed": sum(1 for r in rows if ok(r, "derived_annotations")),
        "quotes_but_no_fulltext": sum(
            1 for r in rows if ok(r, "verbatim_quotations") and not ok(r, "full_text_redistribution")
        ),
        "annotations_but_no_metadata": sum(
            1 for r in rows if ok(r, "derived_annotations") and not ok(r, "bibliographic_metadata")
        ),
    }

    # what the frozen DB actually ships, per decision
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    sec = cols(c, "section")
    out["section_columns"] = sec
    textcol = "section_text_original" if "section_text_original" in sec else "section_text"

    shipped = {}
    for name, q in [
        ("section_text_rows", "SELECT COUNT(*) FROM section WHERE %s IS NOT NULL AND LENGTH(%s)>0" % (textcol, textcol)),
        ("section_text_chars", "SELECT SUM(LENGTH(%s)) FROM section" % textcol),
        ("papers_with_section_text", "SELECT COUNT(DISTINCT paper_id) FROM section WHERE %s IS NOT NULL AND LENGTH(%s)>0" % (textcol, textcol)),
        ("section_hash_rows", "SELECT COUNT(*) FROM section WHERE text_hash_sha256 IS NOT NULL"),
    ]:
        shipped[name] = c.execute(q).fetchone()[0]
    out["section_shipped"] = shipped

    # section text by licence decision
    dec = {r["paper_id"]: r["proposed_release_decision"] for r in rows}
    per = c.execute(
        "SELECT paper_id, SUM(LENGTH(%s)) FROM section WHERE %s IS NOT NULL GROUP BY paper_id" % (textcol, textcol)
    ).fetchall()
    agg = collections.Counter()
    chars = collections.Counter()
    for pid, n in per:
        agg[dec.get(pid, "NOT_IN_MATRIX")] += 1
        chars[dec.get(pid, "NOT_IN_MATRIX")] += n or 0
    out["db_section_text_papers_by_decision"] = dict(agg)
    out["db_section_text_chars_by_decision"] = dict(chars)

    # claim_evidence: how much quote text ships. The CDM carries no per-row
    # redaction flag (the catalogue CSV layer does), so presence of text is the test.
    ce = cols(c, "claim_evidence")
    out["claim_evidence_columns"] = ce
    q = "evidence_text"
    r = c.execute(
        "SELECT paper_id, COUNT(*) FROM claim_evidence WHERE %s IS NOT NULL AND LENGTH(%s)>0 GROUP BY 1" % (q, q)
    ).fetchall()
    bydec = collections.Counter()
    bydec_papers = collections.Counter()
    for pid, n in r:
        d = dec.get(pid, "NOT_IN_MATRIX")
        bydec[d] += n
        bydec_papers[d] += 1
    out["claim_evidence_quote_rows_by_decision"] = dict(bydec)
    out["claim_evidence_quote_papers_by_decision"] = dict(bydec_papers)
    out["claim_evidence_quote_rows_total"] = sum(bydec.values())

    # relation_evidence source_sentence as a second quote surface
    re_ = cols(c, "relation_evidence")
    out["relation_evidence_columns"] = re_
    if "source_sentence" in re_:
        r = c.execute(
            "SELECT paper_id, COUNT(*) FROM relation_evidence WHERE source_sentence IS NOT NULL AND LENGTH(source_sentence)>0 GROUP BY 1"
        ).fetchall()
        bydec2 = collections.Counter()
        for pid, n in r:
            bydec2[dec.get(pid, "NOT_IN_MATRIX")] += n
        out["relation_evidence_sentence_rows_by_decision"] = dict(bydec2)

    # paper.license_name inside the CDM vs the rights matrix
    if "license_name" in cols(c, "paper"):
        db_lic = dict(c.execute("SELECT paper_id, license_name FROM paper").fetchall())
        out["db_license_name_distinct"] = dict(
            collections.Counter("NULL" if v is None else str(v) for v in db_lic.values()).most_common(10)
        )
        mism = [
            (pid, db_lic.get(pid), r["licence"])
            for r in rows
            for pid in [r["paper_id"]]
            if (db_lic.get(pid) or "NONE_FOUND").strip().lower() != (r["licence"] or "NONE_FOUND").strip().lower()
        ]
        out["db_vs_matrix_licence_mismatch"] = len(mism)
        out["db_vs_matrix_licence_mismatch_sample"] = mism[:15]

    c.close()
    emit("d12_rights_readiness", out)


if __name__ == "__main__":
    main()
