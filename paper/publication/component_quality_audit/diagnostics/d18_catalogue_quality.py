"""D18 - catalogue record quality (component F).

Read-only. Audits all 52,400 catalogue records in the six record types by
joining the frozen catalogue CSV layer (release 3.1.1) to the CDM tables and to
the section text. Five measures are computed and reported SEPARATELY, never
collapsed into one accuracy score:

  1. literal correspondence  - is the recorded value/quote literally present in
                               the cited section text?
  2. evidence relevance      - does the cited passage look like it is about the
                               record's own field rather than a neighbouring one?
  3. model-judge verdicts    - inherited from the project's own judge outputs
                               (reported as model opinion only)
  4. cross-method agreement  - do the two judges / two extraction paths agree?
  5. unresolved cases        - rows that cannot be resolved either way

PRIORITY_DIAGNOSTIC: the project's BOTH_JUDGES_FAIL worklist is used as a
priority diagnostic set, never as a gold-standard error set.
"""
from __future__ import annotations

import collections
import csv
import gzip
import io
import json
import os
import re
import sqlite3

from common import CAT, DB, REPO, emit


def norm_ws(s):
    return " ".join((s or "").split())


def norm_lo(s):
    return norm_ws(s).lower()


SENTINELS = {
    "NOT_REPORTED", "NOT_DEPOSITED", "NOT_APPLICABLE", "NOT_ACCESSIBLE",
    "CONFLICTING", "UNKNOWN", "NA", "N/A", "NONE", "UNSPECIFIED",
    "NOT_STATED", "", "NAN",
}


def is_sentinel(v):
    return str(v or "").strip().upper() in SENTINELS


def read_csv_safe(path):
    """Catalogue CSVs carry NUL bytes and embedded newlines.

    The file must be parsed as ONE stream: quoting means a field can contain a
    newline, so splitting on lines first would fabricate rows. This is the same
    trap that made `wc -l` over-count every catalogue CSV.
    """
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        raw = fh.read()
    raw = raw.replace("\x00", " ")
    return list(csv.DictReader(io.StringIO(raw, newline="")))


def main():
    out = {}

    # ---------------- record inventory across the six types -----------------
    types = ["cohorts", "samples", "assays", "datasets", "data_assets", "findings", "papers"]
    # The release keeps its CSVs under tables/, not at the release root
    # (verified on disk: releases/data_catalogue_v3/3.1.1/tables/*.csv).
    out["catalogue_files"] = {}
    for t in types:
        p = CAT / "tables" / ("%s.csv" % t)
        if not p.exists():
            p = CAT / ("%s.csv" % t)
        if not p.exists():
            out["catalogue_files"][t] = "ABSENT"
            continue
        rows = read_csv_safe(str(p))
        out["catalogue_files"][t] = {
            "rows": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "nonzero_bytes": os.path.getsize(p),
        }

    cat_tables = {
        "cohorts": "cohort", "samples": "sample", "assays": "assay",
        "datasets": "dataset", "data_assets": "data_asset", "findings": "claim",
    }
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    out["db_counts"] = {
        tbl: c.execute('SELECT COUNT(*) FROM "%s"' % tbl).fetchone()[0]
        for tbl in cat_tables.values()
    }
    out["db_counts"]["claim_catalogue_half"] = c.execute(
        "SELECT COUNT(*) FROM claim WHERE claim_source='catalogue_v3_1'"
    ).fetchone()[0]

    # ---------------- evidence anchoring census per record type -------------
    # Catalogue evidence lives in claim_evidence (findings) and in the CSV
    # evidence/quote columns for the other five types.
    out["evidence_anchor_status_by_source"] = c.execute(
        "SELECT claim_source, COALESCE(evidence_anchor_status,'(null)'), COUNT(*) "
        "FROM claim_evidence GROUP BY 1,2 ORDER BY 3 DESC"
    ).fetchall()
    out["evidence_locator_status_by_source"] = c.execute(
        "SELECT claim_source, COALESCE(evidence_locator_status,'(null)'), COUNT(*) "
        "FROM claim_evidence GROUP BY 1,2 ORDER BY 3 DESC"
    ).fetchall()

    # ---------------- 1. literal correspondence ----------------------------
    # For findings (catalogue half) test whether the stored evidence_span /
    # evidence_text is present in the cited section.
    sec = {}
    for pid, sid, txt in c.execute(
        "SELECT paper_id, section_id_original, section_text_original FROM section"
    ):
        sec[(pid, sid)] = txt or ""

    lit = collections.Counter()
    lit_examples = []
    for fid, pid, sid, evtext, span, cstart, cend, anchor in c.execute(
        "SELECT finding_id, paper_id, section_id, evidence_text, evidence_span, "
        "char_start, char_end, evidence_anchor_status FROM claim_evidence "
        "WHERE claim_source='catalogue_v3_1'"
    ):
        txt = sec.get((pid, sid))
        if txt is None:
            lit["section_missing"] += 1
            continue
        if anchor == "NO_EVIDENCE" or not (evtext or "").strip():
            lit["no_evidence"] += 1
            continue
        if cstart is not None and cend is not None and 0 <= cstart < cend <= len(txt):
            got = txt[cstart:cend]
            if got == evtext:
                lit["offset_exact"] += 1
            elif norm_lo(got) == norm_lo(evtext):
                lit["offset_normalised"] += 1
            else:
                lit["offset_mismatch"] += 1
        elif norm_lo(evtext) in norm_lo(txt):
            lit["substring_exact"] += 1
        else:
            lit["absent_from_section"] += 1
            if len(lit_examples) < 12:
                lit_examples.append(
                    {"finding_id": fid, "paper": pid, "section": sid,
                     "evidence": evtext[:90], "anchor": anchor}
                )
    out["finding_literal_correspondence"] = dict(lit)
    tot_lit = sum(v for k, v in lit.items() if k != "section_missing")
    out["finding_literal_correspondence_pct"] = {
        k: round(100.0 * v / max(1, tot_lit), 3) for k, v in lit.items()
    }
    out["finding_literal_mismatch_examples"] = lit_examples

    # ---------------- field-level relevance probes -------------------------
    # Real schema (verified by PRAGMA, not guessed): cohort has country_or_region
    # but no study_design (that lives on `study`); assay has no sample_id -- the
    # record chain is sample -> dataset -> cohort and assay -> dataset.
    field_probe = [
        ("assay", "sequencing_platform"),
        ("assay", "assay_type"),
        ("cohort", "country_or_region"),
        ("cohort", "cohort_role"),
        ("sample", "sample_type"),
        ("sample", "body_site"),
        ("dataset", "repository_accession"),
        ("study", "study_design"),
    ]
    field_stats = {}
    for tbl, col in field_probe:
        cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % tbl)]
        if col not in cols or "evidence_text" not in cols:
            field_stats["%s.%s" % (tbl, col)] = {"status": "column absent"}
            continue
        q = (
            'SELECT a."%s", a.evidence_text FROM "%s" a WHERE a.evidence_text IS NOT NULL '
            "AND TRIM(a.evidence_text)<>''" % (col, tbl)
        )
        st = {"rows": 0, "value_token_in_evidence": 0, "value_absent": 0,
              "sentinel_value": 0}
        for val, ev in c.execute(q):
            if is_sentinel(val):
                st["sentinel_value"] += 1
                continue
            st["rows"] += 1
            toks = [w for w in re.findall(r"[A-Za-z0-9]{4,}", str(val).lower())]
            evl = norm_lo(ev)
            if not toks:
                st["value_absent"] += 1
            elif any(w in evl for w in toks):
                st["value_token_in_evidence"] += 1
            else:
                st["value_absent"] += 1
        for k in ("value_token_in_evidence", "value_absent"):
            st[k + "_pct"] = round(100.0 * st[k] / max(1, st["rows"]), 3)
        field_stats["%s.%s" % (tbl, col)] = st
    out["field_relevance_probe"] = field_stats

    # ---------------- 3. model-judge verdicts (inherited) ------------------
    judge_paths = [
        REPO / "paper/publication/final_validation/evidence_judge/BOTH_JUDGES_FAIL.csv",
        REPO / "outputs/results/catalogue_v3/evidence_judge/BOTH_JUDGES_FAIL.csv",
    ]
    jp = next((p for p in judge_paths if p.exists()), None)
    out["both_judges_fail_path"] = str(jp) if jp else "ABSENT"
    if jp:
        rows = read_csv_safe(str(jp))
        out["both_judges_fail_rows"] = len(rows)
        out["both_judges_fail_columns"] = list(rows[0].keys()) if rows else []
        # which record types and fields are concentrated there
        for k in ("record_type", "field_name", "cdm_type", "table"):
            if rows and k in rows[0]:
                out["both_judges_fail_by_%s" % k] = dict(
                    collections.Counter(r.get(k) or "(null)" for r in rows).most_common(20)
                )

    # judge verdict vocabulary present in the DB (model opinion, not truth)
    jcols = [r[1] for r in c.execute("PRAGMA table_info(claim)")]
    out["claim_columns"] = jcols
    for col in jcols:
        if "judge" in col.lower() or "verdict" in col.lower():
            out["claim_%s" % col] = dict(
                c.execute(
                    'SELECT COALESCE("%s",\'(null)\'), COUNT(*) FROM claim GROUP BY 1 ORDER BY 2 DESC LIMIT 15' % col
                ).fetchall()
            )

    # ---------------- 4. cross-method agreement ---------------------------
    # Within the catalogue: does the CSV layer agree with the DB layer on
    # count and on key fields? (independent path comparison)
    agreement = {}
    for csv_name, tbl in cat_tables.items():
        p = CAT / "tables" / ("%s.csv" % csv_name)
        if not p.exists():
            p = CAT / ("%s.csv" % csv_name)
        if not p.exists():
            agreement[csv_name] = "ABSENT"
            continue
        n_csv = len(read_csv_safe(str(p)))
        n_db = c.execute('SELECT COUNT(*) FROM "%s"' % tbl).fetchone()[0]
        if tbl == "claim":
            n_db = c.execute(
                "SELECT COUNT(*) FROM claim WHERE claim_source='catalogue_v3_1'"
            ).fetchone()[0]
        agreement["%s" % csv_name] = {"csv": n_csv, "db": n_db, "match": n_csv == n_db}
    out["csv_db_count_agreement"] = agreement

    # ---------------- 5. unresolved cases ---------------------------------
    out["catalogue_unresolved"] = {
        "NO_MATCH_FOUND_mappings": c.execute(
            "SELECT COUNT(*) FROM term_concept_map WHERE mapping_relation='NO_MATCH_FOUND'"
        ).fetchone()[0],
        "claim_evidence_UNABLE_TO_VERIFY": c.execute(
            "SELECT COUNT(*) FROM claim_evidence WHERE evidence_anchor_status='UNANCHORED'"
        ).fetchone()[0],
        "claim_evidence_unanchored_or_no_evidence": c.execute(
            "SELECT COUNT(*) FROM claim_evidence WHERE evidence_anchor_status IN ('UNANCHORED','NO_EVIDENCE')"
        ).fetchone()[0],
        "disposition_UNRESOLVED": c.execute(
            "SELECT COUNT(*) FROM term_concept_map WHERE mapping_disposition='UNRESOLVED'"
        ).fetchone()[0],
    }

    # ---------------- gap-fill versus original extraction ------------------
    # provenance/_clean_report.json records the clean run
    pc = CAT / "provenance" / "_clean_report.json"
    if pc.exists():
        d = json.loads(pc.read_text(encoding="utf-8"))
        out["clean_report_keys"] = sorted(d.keys())
        out["clean_report"] = {k: v for k, v in d.items() if not isinstance(v, (list, dict))}
        for k, v in d.items():
            if isinstance(v, list) and len(v) < 60:
                out["clean_report_%s" % k] = v[:40]
            elif isinstance(v, dict) and len(v) < 60:
                out["clean_report_%s" % k] = v

    # gap-filled values: computed from field_sources, NOT copied from the
    # project's own 14,845 figure. field_sources names the producer per field
    # (G1/G2/G5 = gap pipeline; finalize_* = cleanup pass).
    gap_entries = 0
    gap_by_source = collections.Counter()
    gap_by_table = {}
    for tbl in ("cohort", "sample", "dataset"):
        cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % tbl)]
        if "field_sources" not in cols:
            continue
        n = 0
        for (fs,) in c.execute(
            'SELECT field_sources FROM "%s" WHERE field_sources IS NOT NULL '
            "AND TRIM(field_sources) NOT IN ('','[]','{}')" % tbl
        ):
            try:
                d = json.loads(fs)
            except (ValueError, TypeError):
                continue
            if not isinstance(d, dict):
                continue
            for _f, src in d.items():
                gap_by_source[str(src)] += 1
                n += 1
        gap_by_table[tbl] = n
        gap_entries += n
    out["gap_provenance_entries_by_table"] = gap_by_table
    out["gap_provenance_entries_total"] = gap_entries
    out["gap_provenance_by_source_token"] = dict(gap_by_source.most_common(20))
    out["gap_provenance_g1g5_entries"] = sum(
        v for k, v in gap_by_source.items() if k.startswith(("G1", "G2", "G5"))
    )
    out["gap_provenance_note"] = (
        "computed from field_sources JSON; the project doc's 14,845 is a "
        "different unit (values filled) and is NOT independently reproduced here"
    )

    # ---------------- field-level completeness -----------------------------
    comp = {}
    for csv_name, tbl in cat_tables.items():
        cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % tbl)]
        ent = {}
        for col in cols:
            n = c.execute('SELECT COUNT(*) FROM "%s"' % tbl).fetchone()[0]
            filled = c.execute(
                'SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL AND TRIM(CAST("%s" AS TEXT))<>\'\'' %
                (tbl, col, col)
            ).fetchone()[0]
            sent = c.execute(
                'SELECT COUNT(*) FROM "%s" WHERE UPPER(TRIM(CAST("%s" AS TEXT))) IN (%s)' %
                (tbl, col, ",".join("'%s'" % s for s in SENTINELS if s))
            ).fetchone()[0]
            ent[col] = {
                "filled": filled,
                "filled_pct": round(100.0 * filled / max(1, n), 3),
                "sentinel": sent,
                "effective_pct": round(100.0 * max(0, filled - sent) / max(1, n), 3),
            }
        comp[csv_name] = ent
    out["field_completeness"] = comp

    # ---------------- cross-paper contamination probes --------------------
    # a record whose evidence section belongs to a different paper than the
    # record's own paper_id
    out["claim_evidence_cross_paper"] = c.execute(
        "SELECT COUNT(*) FROM claim_evidence e JOIN claim k ON k.finding_id=e.finding_id "
        "WHERE k.paper_id<>e.paper_id"
    ).fetchone()[0]
    out["relation_evidence_cross_paper"] = c.execute(
        "SELECT COUNT(*) FROM relation_evidence e JOIN relation r "
        "ON r.canonical_triple_id=e.canonical_triple_id "
        "WHERE e.paper_id NOT IN (SELECT value FROM json_each(r.paper_ids))"
    ).fetchone()[0] if True else 0

    # entity relationships: do child records point at a parent in the same paper
    # Verified chain: sample.cohort_id -> cohort, sample.dataset_id -> dataset,
    # assay.dataset_id -> dataset, data_asset.dataset_id -> dataset.
    # `assay` has NO sample_id column -- do not invent that link.
    for child, parent, ck, pk in [
        ("sample", "cohort", "cohort_id", "cohort_id"),
        ("sample", "dataset", "dataset_id", "dataset_id"),
        ("assay", "dataset", "dataset_id", "dataset_id"),
        ("data_asset", "dataset", "dataset_id", "dataset_id"),
    ]:
        cc = [r[1] for r in c.execute('PRAGMA table_info("%s")' % child)]
        if ck not in cc:
            out["parent_link_%s_%s" % (child, parent)] = "column absent"
            continue
        q = (
            'SELECT COUNT(*) FROM "%s" ch JOIN "%s" pa ON pa."%s"=ch."%s" '
            "WHERE pa.paper_id<>ch.paper_id" % (child, parent, pk, ck)
        )
        try:
            out["parent_link_%s_%s_cross_paper" % (child, parent)] = c.execute(q).fetchone()[0]
        except sqlite3.Error as e:
            out["parent_link_%s_%s" % (child, parent)] = "ERR %s" % e
        # dangling child rows: ck populated but no parent
        try:
            out["parent_link_%s_%s_dangling" % (child, parent)] = c.execute(
                'SELECT COUNT(*) FROM "%s" ch WHERE ch."%s" IS NOT NULL '
                'AND TRIM(ch."%s")<>\'\' AND ch."%s" NOT IN (SELECT "%s" FROM "%s")'
                % (child, ck, ck, ck, pk, parent)
            ).fetchone()[0]
        except sqlite3.Error as e:
            out["parent_link_%s_%s_dangling" % (child, parent)] = "ERR %s" % e

    # granularity: cohorts vs samples vs assays per paper
    out["per_paper_record_counts"] = c.execute(
        "SELECT paper_id, "
        "(SELECT COUNT(*) FROM cohort x WHERE x.paper_id=s.paper_id), "
        "(SELECT COUNT(*) FROM sample x WHERE x.paper_id=s.paper_id), "
        "(SELECT COUNT(*) FROM assay x WHERE x.paper_id=s.paper_id), "
        "(SELECT COUNT(*) FROM claim x WHERE x.paper_id=s.paper_id AND x.claim_source='catalogue_v3_1') "
        "FROM (SELECT DISTINCT paper_id FROM section) s LIMIT 5"
    ).fetchall()
    out["papers_with_cohort_but_no_sample"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT paper_id FROM cohort) x "
        "WHERE x.paper_id NOT IN (SELECT DISTINCT paper_id FROM sample)"
    ).fetchone()[0]
    out["papers_with_sample_but_no_assay"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT paper_id FROM sample) x "
        "WHERE x.paper_id NOT IN (SELECT DISTINCT paper_id FROM assay)"
    ).fetchone()[0]

    c.close()
    emit("d18_catalogue_quality", out)


if __name__ == "__main__":
    main()
