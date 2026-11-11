"""Populate HUMAN_REVIEW in a 3.2.0-candidate copy of CDM 3.1.0 from the completed, pre-registered human reviews.

Never touches releases/: the frozen 3.1.0 DB is copied to outputs/scratch/cdm_v32_candidate/ and only the copy is
written.  Reviewer identities are anonymised (reviewer_A, annotator_A, annotator_B); no name, sheet file name,
document-property author or e-mail is read into the DB or the outputs.

Imported (one row per item x reviewer):
  * HSC-MAP-2026-11-09  manual review of 500 ACCEPTED term-concept mappings, reviewer A (all 500 items).
      target = term_concept_map.mapping_row_id (via KEY_model_verdicts.csv item -> mapping_row_id).
  * HSC-TRI-2026-11-09  manual check of 100 canonical triples, annotators A and B (100 items each).
      target = relation.canonical_triple_id (sample.csv triple_id).
  * Adjudicated (AGREED) labels: imported if an AGREED column exists in triple sheet A; none exists today.
NOT imported: the second mapping sheet (its notes read "Automated annotation via heuristic matching"; not a validated
human review) -- the script refuses any sheet whose notes contain that phrase.

    python src/scripts/fixes_v32/human_review/import_human_review.py [--force-copy]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema_common import CANDIDATE_DB, CDM_VERSION, DB_310, OUT, REPO_ROOT, RIGHTS_MATRIX, sha256_file  # noqa: E402

MAP_DIR = REPO_ROOT / "outputs/results/benchmark/human_spotcheck_mappings_2026-11-09"
TRI_DIR = REPO_ROOT / "outputs/results/benchmark/human_spotcheck_triples_2026-11-09"
AUTOMATED_MARK = "automated annotation via heuristic matching"

NEW_COLUMNS = [  # appended to the 3.1.0 human_review columns (review_id, target_entity, target_id, reviewer,
    # review_date, decision, notes), which keep their meaning
    ("protocol_id", "TEXT"), ("sample_item", "INTEGER"), ("review_kind", "TEXT"), ("decision_field", "TEXT"),
    ("verdicts_json", "TEXT"), ("review_date_source", "TEXT"), ("sheet_sha256", "TEXT"),
    ("preregistration_sha256", "TEXT"), ("import_run", "TEXT"),
]
PROTOCOL_DDL = """CREATE TABLE human_review_protocol (
  protocol_id TEXT PRIMARY KEY, title TEXT, target_entity TEXT, population TEXT, sampling TEXT, n_items INTEGER,
  reviewers TEXT, blinding TEXT, protocol_path TEXT, protocol_sha256 TEXT, preregistration_path TEXT,
  preregistration_sha256 TEXT, sample_path TEXT, sample_sha256 TEXT, adjudication_status TEXT, approval_status TEXT)"""


def check_prereg(folder: Path) -> dict:
    """Every file listed in PREREGISTRATION.sha256 that is meant to stay fixed (protocol, guide, sample, key) must
    still hash to the registered value. Blank sheets are listed too but are superseded by the completed copies."""
    res = {}
    for line in (folder / "PREREGISTRATION.sha256").read_text().splitlines():
        h, name = line.split(None, 1)
        p = folder / name.strip()
        if name.startswith("ANNOTATION_SHEET"):
            continue
        res[name.strip()] = "MATCH" if p.exists() and sha256_file(p) == h else "MISMATCH"
    if any(v != "MATCH" for v in res.values()):
        raise SystemExit(f"pre-registered files changed in {folder}: {res}")
    return res


def read_sheet(path: Path) -> tuple[list[dict], str, list[str]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    modified = wb.properties.modified  # date only is used; author properties are never read
    rows = list(wb["annotate"].iter_rows(values_only=True))
    head = [str(h) if h is not None else "" for h in rows[0]]
    recs = [dict(zip(head, r)) for r in rows[1:] if r and r[0] is not None]
    notes = " ".join(str(r.get("NOTES") or "") for r in recs).lower()
    if AUTOMATED_MARK in notes:
        raise SystemExit("refusing a sheet marked as automated annotation (not a human review)")
    date = modified.date().isoformat() if modified else dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    return recs, date, head


def find_one(pattern: str) -> Path:
    hits = sorted(glob.glob(str(REPO_ROOT / pattern)))
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one file for {pattern!r}, found {len(hits)}")
    return Path(hits[0])


def norm(v):
    return None if v is None or str(v).strip() == "" else str(v).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-copy", action="store_true", help="re-copy 3.1.0 even if the candidate exists")
    ap.add_argument("--map-sheet", default="ANNOTATION_SHEET_*_onto.xlsx")
    ap.add_argument("--tri-sheet-a", default="ANNOTATION_SHEET_*_triples.xlsx")
    ap.add_argument("--tri-sheet-b", default="annotator_sheet_b_triples.xlsx")
    a = ap.parse_args()
    out = OUT / "human_review"
    out.mkdir(parents=True, exist_ok=True)
    run_id = "HRIMPORT_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    prereg = {"HSC-MAP-2026-11-09": check_prereg(MAP_DIR), "HSC-TRI-2026-11-09": check_prereg(TRI_DIR)}
    sheets = {"reviewer_A_map": find_one(a.map_sheet), "annotator_A_tri": find_one(a.tri_sheet_a),
              "annotator_B_tri": find_one(a.tri_sheet_b)}

    # ---- copy the frozen DB (never written) -------------------------------------------------------------------
    manifest = {l.split()[1]: l.split()[0] for l in (DB_310.parent / "MANIFEST.sha256").read_text().splitlines()}
    CANDIDATE_DB.parent.mkdir(parents=True, exist_ok=True)
    if a.force_copy or not CANDIDATE_DB.exists():
        tmp = CANDIDATE_DB.with_suffix(".db.part")
        shutil.copyfile(DB_310, tmp)
        os.chmod(tmp, 0o644)
        copy_sha = sha256_file(tmp)
        if copy_sha != manifest[DB_310.name]:
            raise SystemExit("copy does not match the 3.1.0 MANIFEST sha256")
        tmp.rename(CANDIDATE_DB)
    else:
        copy_sha = "not re-hashed (existing copy)"
    con = sqlite3.connect(CANDIDATE_DB)
    con.row_factory = sqlite3.Row
    if con.execute("SELECT count(*) FROM human_review").fetchone()[0]:
        raise SystemExit("candidate human_review already populated; use --force-copy to start from a fresh copy")

    # ---- schema extension --------------------------------------------------------------------------------------
    have = {r[1] for r in con.execute("PRAGMA table_info(human_review)")}
    for c, t in NEW_COLUMNS:
        if c not in have:
            con.execute(f"ALTER TABLE human_review ADD COLUMN {c} {t}")
    con.execute("DROP TABLE IF EXISTS human_review_protocol")
    con.execute(PROTOCOL_DDL)

    rights = {r["paper_id"]: r["proposed_release_decision"] for r in csv.DictReader(open(RIGHTS_MATRIX))}

    def rel(p: Path) -> str:
        return str(p.relative_to(REPO_ROOT))

    protocols = [
        ("HSC-MAP-2026-11-09", "Manual review of 500 accepted ontology mappings", "term_concept_map",
         "18,272 term_concept_map rows of CDM 3.0.3 with mapping_disposition_reviewed='ACCEPTED' (same rows in 3.1.0)",
         "simple random sample n=500, random.Random(20261109)", 500,
         "reviewer_A (all 500); a second mapping sheet was received but is not a validated human review and is not "
         "imported", "no model labels in the sheet; key opened after annotation",
         MAP_DIR / "PROTOCOL.md", MAP_DIR / "PREREGISTRATION.sha256", MAP_DIR / "sample.csv",
         "NOT_APPLICABLE (single validated reviewer)"),
        ("HSC-TRI-2026-11-09", "Manual check of 100 canonical triples against their anchor sentence", "relation",
         "16,032 canonical triples judged by DeepSeek-V4.1-Flash against a sentence from a CC BY or CC0 paper",
         "simple random sample n=100, random.Random(20261109)", 100, "annotator_A, annotator_B (independent)",
         "no model output in the sheets; key opened after sheet A",
         TRI_DIR / "PROTOCOL.md", TRI_DIR / "PREREGISTRATION.sha256", TRI_DIR / "sample.csv", None),
    ]

    # ---- mapping review: reviewer A ----------------------------------------------------------------------------
    key = {int(r["item"]): r for r in csv.DictReader(open(MAP_DIR / "KEY_model_verdicts.csv"))}
    sample_map = {int(r["item"]): r for r in csv.DictReader(open(MAP_DIR / "sample.csv"))}
    recs, date_map, _ = read_sheet(sheets["reviewer_A_map"])
    rows, issues = [], []
    prereg_map = sha256_file(MAP_DIR / "PREREGISTRATION.sha256")
    sha_map = sha256_file(sheets["reviewer_A_map"])
    for r in recs:
        item = int(r["item"])
        k, s = key[item], sample_map[item]
        if norm(r.get("term")) != norm(s["term"]) or norm(r.get("concept_id")) != norm(s["concept_id"]):
            issues.append(f"map item {item}: sheet row does not match sample.csv")
        verdicts = {f: norm(r.get(f)) for f in ("MAPPING", "TERM_IS_CONCEPT", "TYPE_CORRECT", "DEFINITION")}
        rows.append(dict(review_id=f"HR-MAP-A-{item:03d}", target_entity="term_concept_map",
                         target_id=k["mapping_row_id"], reviewer="reviewer_A", review_date=date_map,
                         decision=verdicts["MAPPING"], notes=norm(r.get("NOTES")), protocol_id="HSC-MAP-2026-11-09",
                         sample_item=item, review_kind="INDEPENDENT", decision_field="MAPPING",
                         verdicts_json=json.dumps(verdicts, sort_keys=True),
                         review_date_source="sheet document property 'modified' (date part)",
                         sheet_sha256=sha_map, preregistration_sha256=prereg_map, import_run=run_id))

    # ---- triple check: annotators A and B (+ AGREED if present) ------------------------------------------------
    sample_tri = {int(r["item"]): r for r in csv.DictReader(open(TRI_DIR / "sample.csv"))}
    prereg_tri = sha256_file(TRI_DIR / "PREREGISTRATION.sha256")
    agreed_n = 0
    for who, sk in (("annotator_A", "annotator_A_tri"), ("annotator_B", "annotator_B_tri")):
        recs, date_t, head = read_sheet(sheets[sk])
        sha = sha256_file(sheets[sk])
        for r in recs:
            item = int(r["item"])
            s = sample_tri[item]
            if norm(r.get("subject")) != norm(s["subject"]) or norm(r.get("relation")) != norm(s["relation"]):
                issues.append(f"{who} item {item}: sheet row does not match sample.csv")
            verdicts = {f: norm(r.get(f)) for f in ("SUPPORT", "POLARITY", "RELATION_JUSTIFIED")}
            note = norm(r.get("NOTES"))
            if note and rights.get(s["paper_id"]) != "INCLUDE_TEXT":
                note = "[withheld: rights bucket not INCLUDE_TEXT]"
            tag = "A" if who == "annotator_A" else "B"
            rows.append(dict(review_id=f"HR-TRI-{tag}-{item:03d}", target_entity="relation", target_id=s["triple_id"],
                             reviewer=who, review_date=date_t, decision=verdicts["SUPPORT"], notes=note,
                             protocol_id="HSC-TRI-2026-11-09", sample_item=item, review_kind="INDEPENDENT",
                             decision_field="SUPPORT", verdicts_json=json.dumps(verdicts, sort_keys=True),
                             review_date_source="sheet document property 'modified' (date part)",
                             sheet_sha256=sha, preregistration_sha256=prereg_tri, import_run=run_id))
            if who == "annotator_A" and "AGREED" in head and norm(r.get("AGREED")):
                agreed_n += 1
                rows.append(dict(rows[-1], review_id=f"HR-TRI-AGREED-{item:03d}", reviewer="annotator_A+annotator_B",
                                 decision=norm(r.get("AGREED")), notes=None, review_kind="ADJUDICATED",
                                 decision_field="AGREED",
                                 verdicts_json=json.dumps({"AGREED": norm(r.get("AGREED"))})))
    adjud = (f"ADJUDICATED labels imported for {agreed_n} items" if agreed_n else
             "PENDING: no AGREED column in triple sheet A; adjudicated labels do not exist yet")
    protocols[1] = protocols[1][:-1] + (adjud,)

    # ---- link validation: every target exists ------------------------------------------------------------------
    unresolved = 0
    for r in rows:
        col = {"term_concept_map": "mapping_row_id", "relation": "canonical_triple_id"}[r["target_entity"]]
        if not con.execute(f"SELECT 1 FROM {r['target_entity']} WHERE {col}=?", (r["target_id"],)).fetchone():
            unresolved += 1
            issues.append(f"{r['review_id']}: target {r['target_id']} not found")
    if issues:
        (out / "import_issues.txt").write_text("\n".join(issues))
        raise SystemExit(f"{len(issues)} integrity issues; see import_issues.txt (nothing committed)")

    for p in protocols:
        (pid, title, tgt, pop, samp, n, revs, blind, proto, pre, smp, adj) = p
        con.execute("INSERT INTO human_review_protocol VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, title, tgt, pop, samp, n, revs, blind, rel(proto), sha256_file(proto), rel(pre),
                     sha256_file(pre), rel(smp), sha256_file(smp), adj,
                     "freeze exception PENDING lead approval"))
    cols = [c for c in rows[0]]
    con.executemany(f"INSERT INTO human_review ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [tuple(r[c] for c in cols) for r in rows])
    n = len(rows)
    con.execute("UPDATE cdm_entity_status SET rows=?, status='POPULATED' WHERE entity='HUMAN_REVIEW'",
                (n,))
    con.execute("UPDATE run_metadata SET value=? WHERE key='cdm_version'", (CDM_VERSION,))
    for k_, v_ in (("derived_from_320c", f"releases/cdm_v3/3.1.0 (sha256 {manifest[DB_310.name]})"),
                   ("build_320c_human_review", "src/scripts/fixes_v32/human_review/import_human_review.py"),
                   ("status_320c", "candidate; not a release; PENDING lead approval")):
        con.execute("INSERT INTO run_metadata(key, value) VALUES (?,?)", (k_, v_))
    con.execute("INSERT INTO cdm_change_log(step, kind, target, description, rows_affected, revert_sql) "
                "VALUES (?,?,?,?,?,?)",
                ("320c_human_review", "INSERT_ROWS", "human_review",
                 "human verdicts from pre-registered reviews HSC-MAP-2026-11-09 (reviewer_A) and HSC-TRI-2026-11-09 "
                 "(annotator_A, annotator_B); anonymised", n,
                 "DELETE FROM human_review; DROP TABLE human_review_protocol;"))
    con.commit()

    # ---- export (anonymised) + report --------------------------------------------------------------------------
    with open(out / "human_review_rows.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        k_ = f"{r['protocol_id']}|{r['reviewer']}|{r['review_kind']}"
        by.setdefault(k_, {"rows": 0, "decisions": {}})
        by[k_]["rows"] += 1
        by[k_]["decisions"][str(r["decision"])] = by[k_]["decisions"].get(str(r["decision"]), 0) + 1
    report = {"candidate_db": rel(CANDIDATE_DB), "copied_from": rel(DB_310),
              "source_manifest_sha256": manifest[DB_310.name], "copy_sha256_before_write": copy_sha,
              "import_run": run_id, "rows_imported": n, "unresolved_targets": unresolved,
              "preregistered_files_check": prereg, "by_protocol_reviewer": by,
              "adjudicated": adjud,
              "sheets": {k_: {"sha256": sha256_file(p)} for k_, p in sheets.items()},
              "not_imported": "second mapping sheet (notes: 'Automated annotation via heuristic matching')",
              "anonymisation": "reviewer ids only; no names, file names or document authors stored"}
    (out / "import_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
