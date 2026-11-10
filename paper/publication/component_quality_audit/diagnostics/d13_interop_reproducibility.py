"""D13 - interoperability and reproducibility of the public release (component M).

Read-only. Tests the zenodo_frozen public bundle: manifest verification, gzip
integrity, CSV round-trip fidelity, DuckDB-compatibility of the schema types,
reproduction of headline counts from the shipped files, and independent
re-verification of the text-withholding rule.
"""
from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import json
import sqlite3

from common import AUDIT, DB, emit

Z = AUDIT.parents[2] / "releases/zenodo_frozen"


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    out = {}
    out["bundle_exists"] = Z.exists()
    files = sorted(p for p in Z.rglob("*") if p.is_file())
    out["file_count"] = len(files)

    # 1. manifest verification
    man = Z / "MANIFEST.sha256"
    listed = {}
    for line in open(man, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d, _, name = line.partition("  ")
        listed[name.lstrip("*")] = d
    out["manifest_entries"] = len(listed)
    ok = bad = miss = 0
    bad_list = []
    for name, d in listed.items():
        p = Z / name
        if not p.exists():
            miss += 1
            bad_list.append(("MISSING", name))
            continue
        if sha256_file(p) == d:
            ok += 1
        else:
            bad += 1
            bad_list.append(("MISMATCH", name))
    out["manifest_ok"] = ok
    out["manifest_mismatch"] = bad
    out["manifest_missing"] = miss
    out["manifest_problems"] = bad_list[:20]
    on_disk = {str(p.relative_to(Z)) for p in files}
    out["on_disk_not_in_manifest"] = sorted(on_disk - set(listed))[:20]

    # 2. gzip JSONL/CSV integrity + counts
    counts = {}
    for name, key in [
        ("corpus/sections.jsonl.gz", "sections"),
        ("terminology/canonical_terms.csv.gz", "canonical_terms"),
        ("terminology/term_definitions.csv.gz", "term_definitions"),
        ("terminology/term_concept_mappings.csv.gz", "term_concept_mappings"),
        ("triples/triples.csv.gz", "triples"),
        ("triples/triple_evidence.csv.gz", "triple_evidence"),
    ]:
        p = Z / name
        if name.endswith(".csv.gz"):
            # A line count over-counts: CSV fields contain embedded newlines.
            # Parse records instead.
            try:
                with gzip.open(p, "rt", encoding="utf-8", errors="replace", newline="") as fh:
                    rd = csv.reader(fh)
                    head = next(rd, None)
                    n = sum(1 for _ in rd)
            except Exception as e:  # noqa: BLE001
                counts[key] = "ERROR %s" % e
                continue
        else:
            n = 0
            head = None
            try:
                with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if line.strip():
                            n += 1
            except Exception as e:  # noqa: BLE001
                counts[key] = "ERROR %s" % e
                continue
        counts[key] = n
        if head:
            counts[key + "_columns"] = head
    out["shipped_counts"] = counts

    # 3. CSV round-trip fidelity for catalogue tables vs the frozen DB
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rt = {}
    pairs = [
        ("cohorts.csv", "cohort"),
        ("samples.csv", "sample"),
        ("assays.csv", "assay"),
        ("datasets.csv", "dataset"),
        ("data_assets.csv", "data_asset"),
    ]
    for fname, table in pairs:
        p = Z / "catalogue" / fname
        dbcols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % table)]
        try:
            rd = csv.DictReader(open(p, encoding="utf-8", errors="replace", newline=""))
            csvcols = list(rd.fieldnames or [])
            n = sum(1 for _ in rd)
        except Exception as e:  # noqa: BLE001
            rt[fname] = "ERROR %s" % e
            continue
        dbn = c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
        rt[fname] = {
            "csv_rows": n,
            "db_rows": dbn,
            "row_delta": n - dbn,
            "csv_cols_only": sorted(set(csvcols) - set(dbcols)),
            "db_cols_only": sorted(set(dbcols) - set(csvcols)),
        }
    out["csv_roundtrip"] = rt

    # 4. schema type portability (DuckDB-compatible type families)
    types = collections.Counter()
    risky = []
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        for r in c.execute("PRAGMA table_info(%s)" % t):
            decl = (r[2] or "").upper()
            types[decl or "NONE"] += 1
            if decl not in ("", "TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC", "INT", "BOOLEAN", "JSON"):
                risky.append((t, r[1], r[2]))
    out["declared_types"] = dict(types)
    out["non_portable_declarations"] = risky[:25]
    out["non_portable_count"] = len(risky)
    out["fk_declared"] = len(c.execute("PRAGMA foreign_key_list(paper)").fetchall())
    fk_any = 0
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        fk_any += len(c.execute("PRAGMA foreign_key_list(%s)" % t).fetchall())
    out["fk_total_all_tables"] = fk_any
    out["journal_mode_persisted"] = c.execute("PRAGMA journal_mode").fetchone()[0]
    out["page_count"] = c.execute("PRAGMA page_count").fetchone()[0]
    out["page_size"] = c.execute("PRAGMA page_size").fetchone()[0]

    # 5. JSON-in-TEXT columns (documented as a consumer burden)
    jsonish = []
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
        n = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        if n == 0:
            continue
        for col in cols:
            v = c.execute(
                'SELECT "%s" FROM "%s" WHERE "%s" IS NOT NULL LIMIT 1' % (col, t, col)
            ).fetchone()
            if v and isinstance(v[0], str) and v[0][:1] in "[{" and v[0][-1:] in "]}":
                jsonish.append("%s.%s" % (t, col))
    out["json_encoded_columns"] = len(jsonish)
    out["json_encoded_sample"] = jsonish[:40]

    # 6. semicolon multi-value columns
    semi = []
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
        n = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        if n == 0:
            continue
        for col in cols:
            hit = c.execute(
                'SELECT COUNT(*) FROM "%s" WHERE "%s" LIKE "%%;%%"' % (t, col)
            ).fetchone()[0]
            if hit:
                semi.append((t, col, hit, n))
    semi.sort(key=lambda x: -x[2])
    out["semicolon_columns"] = semi[:25]
    out["semicolon_column_count"] = len(semi)

    c.close()

    # 7. reproduce headline counts independently
    head_claims = {
        "sections": 4006,
        "canonical_terms": 162409,
        "term_definitions": 6773,
        "term_concept_mappings": 331394,
        "triples": 25788,
        "triple_evidence": 34416,
        "catalogue_records": 52400,
    }
    repro = {}
    for k, claim in head_claims.items():
        if k == "catalogue_records":
            got = sum(
                v.get("csv_rows", 0) if isinstance(v, dict) else 0
                for f, v in rt.items()
            ) + _findings_rows(Z)
        else:
            got = counts.get(k)
        repro[k] = {"claimed": claim, "recomputed": got,
                    "match": (got == claim) if isinstance(got, int) else "n/a"}
    out["headline_reproduction"] = repro

    # 8. independent text-withholding re-verification
    out["rights_scan"] = _rights_recheck(Z)

    emit("d13_interop_reproducibility", out)


def _findings_rows(Z):
    p = Z / "catalogue" / "findings.csv"
    if not p.exists():
        return 0
    n = 0
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for _ in rd:
            n += 1
    return n


def _rights_recheck(Z):
    """Re-run the withholding test on the shipped section layer with a different
    window/stride than the project's own scan (40-char window, stride 7), and
    report only whether any withheld-paper passage survives."""
    lic = Z / "rights" / "PAPER_LICENCES.csv"
    if not lic.exists():
        return {"error": "no licence table"}
    withheld = set()
    included = set()
    for r in csv.DictReader(open(lic, encoding="utf-8")):
        if r["text_layer"] == "TEXT_INCLUDED":
            included.add(r["paper_id"])
        else:
            withheld.add(r["paper_id"])

    # build 40-char passage set from the ORIGINAL frozen CDM for withheld papers
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    passages = set()
    for pid, txt in c.execute(
        "SELECT paper_id, section_text_original FROM section WHERE section_text_original IS NOT NULL"
    ):
        if pid not in withheld:
            continue
        t = " ".join(txt.split())
        for i in range(0, max(0, len(t) - 40), 7):
            s = t[i:i + 40]
            if len(s) == 40:
                passages.add(s)
    c.close()

    # A passage matching withheld text is only a leak if the shipped section
    # belongs to a withheld paper. The same wording appearing in an INCLUDED
    # paper is shared boilerplate (publisher fronts, affiliations, citations),
    # not a rights violation. The project's own scan makes the same distinction
    # (`shared_wording_in_included_paper` vs `unexplained_hits`).
    leak = []
    shared = 0
    checked = 0
    withheld_sections = 0
    text_papers = set()
    sec = Z / "corpus" / "sections.jsonl.gz"
    with gzip.open(sec, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            o = json.loads(line)
            txt = o.get("text") or o.get("section_text") or o.get("section_text_original") or ""
            if not txt:
                continue
            checked += 1
            text_papers.add(o.get("paper_id"))
            if o.get("paper_id") in withheld:
                withheld_sections += 1
            t = " ".join(txt.split())
            for i in range(0, max(0, len(t) - 40), 7):
                s = t[i:i + 40]
                if s in passages:
                    if o.get("paper_id") in withheld:
                        leak.append({"paper_id": o.get("paper_id"), "snippet": s[:60]})
                    else:
                        shared += 1
                    break
    return {
        "withheld_papers": len(withheld),
        "included_papers": len(included),
        "withheld_passages_indexed": len(passages),
        "sections_with_text_shipped": checked,
        "papers_shipping_text": len(text_papers),
        "withheld_papers_shipping_text": len(text_papers & withheld),
        "sections_with_text_from_withheld_papers": withheld_sections,
        "leaks_in_withheld_papers": len(leak),
        "leak_sample": leak[:10],
        "shared_wording_in_included_papers": shared,
        "window": 40,
        "stride": 7,
        "pass": len(leak) == 0,
    }


if __name__ == "__main__":
    main()
