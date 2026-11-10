"""D02 - Hand-written referential integrity across the frozen CDM.

The database declares no FOREIGN KEY constraints, so every link is checked by
hand. Three link shapes are handled separately:

  scalar        one id per row (term_mention.canonical_term_id)
  list          semicolon-joined ids in one text column (claim.dataset_id)
  json_list     JSON array of ids (relation.paper_ids)

For each check we report dangling values (non-empty but absent from the parent
key set) and, where the CDM ships a tombstone table, how many of the dangling
ids are accounted for by that tombstone (removed_canonical_term,
removed_relation). A dangling id that the model itself flags as removed is an
honest historical reference; a dangling id with no explanation is a defect.

Read-only. Writes no release artifact.
"""

from __future__ import annotations

import json as _json
import sys

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from common import connect, emit


def key_set(con, sql):
    return {r[0] for r in con.execute(sql) if r[0] not in (None, "")}


def columns(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}


def split_ids(raw, sep=";"):
    if raw is None:
        return []
    s = raw.strip()
    if not s:
        return []
    return [p.strip() for p in s.split(sep) if p.strip()]


def check(con, table, col, valid, shape="scalar", tombstone=None, cap=None):
    """shape: scalar | list | json_list. tombstone: set of ids explained by removal."""
    rows = bad_rows = total_ids = bad_ids = 0
    explained = 0
    unknown = 0
    samples_bad = []
    samples_unknown = []
    # SQLite treats an unknown column in double quotes as a string literal, which
    # would silently produce nonsense. Refuse to run against a missing column.
    if col not in columns(con, table):
        return {"table": table, "column": col, "shape": shape,
                "error": "NO_SUCH_COLUMN"}
    sql = f'select "{col}" from "{table}"'
    for r in con.execute(sql):
        raw = r[0]
        if raw in (None, ""):
            continue
        rows += 1
        if shape == "scalar":
            vals = [raw]
        elif shape == "list":
            vals = split_ids(raw)
        else:  # json_list
            try:
                parsed = _json.loads(raw)
            except Exception:
                bad_ids += 1
                bad_rows += 1
                continue
            vals = [v for v in parsed if v not in (None, "")] if isinstance(parsed, list) else []
        hit = False
        for v in vals:
            total_ids += 1
            if v in valid:
                continue
            bad_ids += 1
            hit = True
            if tombstone is not None and v in tombstone:
                explained += 1
            else:
                unknown += 1
                if len(samples_unknown) < 5:
                    samples_unknown.append(v)
            if len(samples_bad) < 5:
                samples_bad.append(v)
        if hit:
            bad_rows += 1
        if cap is not None and rows >= cap:
            break
    return {
        "table": table,
        "column": col,
        "shape": shape,
        "rows_scanned": rows,
        "ids_seen": total_ids,
        "dangling_ids": bad_ids,
        "pct_dangling_ids": round(100.0 * bad_ids / total_ids, 4) if total_ids else None,
        "rows_with_dangling": bad_rows,
        "explained_by_tombstone": explained,
        "unexplained": unknown,
        "pct_unexplained_of_ids": round(100.0 * unknown / total_ids, 4) if total_ids else None,
        "sample_dangling": samples_bad,
        "sample_unexplained": samples_unknown,
    }


def main():
    con = connect()
    out = {"status": "OK", "checks": [], "orphans": []}

    papers = key_set(con, "select paper_id from paper")
    sections = key_set(con, "select section_record_id from section")
    terms = key_set(con, "select term_id from canonical_term")
    terms_removed = key_set(con, "select term_id from removed_canonical_term")
    concepts = key_set(con, "select concept_id from concept")
    datasets = key_set(con, "select dataset_id from dataset")
    cohorts = key_set(con, "select cohort_id from cohort")
    assays = key_set(con, "select assay_id from assay")
    studies = key_set(con, "select study_id from study")
    claims = key_set(con, "select finding_id from claim")
    equations = key_set(con, "select triple_mention_id from relation_evidence")

    def add(*a, **k):
        out["checks"].append(check(con, *a, **k))

    # --- scalar paper links -------------------------------------------------
    for t in ("section", "claim", "sample", "assay", "cohort", "dataset",
              "data_asset", "study", "term_mention", "relation_evidence",
              "paper_publication"):
        add(t, "paper_id", papers)

    # --- term links (tombstone-aware) --------------------------------------
    add("term_mention", "canonical_term_id", terms, tombstone=terms_removed)
    add("term_definition", "term_id", terms, tombstone=terms_removed)
    add("term_concept_map", "term_id", terms, tombstone=terms_removed)
    add("taxonomy_annotation", "term_id", terms, tombstone=terms_removed)
    add("type_harmonization", "canonical_term_id", terms, tombstone=terms_removed)
    add("relation", "subject_term_id", terms, tombstone=terms_removed)
    add("relation", "object_term_id", terms, tombstone=terms_removed)

    # --- concept links ------------------------------------------------------
    add("term_concept_map", "concept_id", concepts)

    # --- catalogue links are semicolon lists -------------------------------
    for t, c in (("sample", "dataset_id"), ("sample", "cohort_id"),
                 ("assay", "dataset_id"), ("cohort", "dataset_id"),
                 ("data_asset", "dataset_id"), ("claim", "dataset_id"),
                 ("claim", "cohort_id"), ("claim", "assay_id"),
                 ("dataset", "study_id"), ("cohort", "study_id"),
                 ("sample", "study_id"), ("assay", "study_id")):
        add(t, c, datasets if c == "dataset_id"
            else cohorts if c == "cohort_id"
            else assays if c == "assay_id"
            else studies, shape="list")

    # --- scalar catalogue links --------------------------------------------
    add("claim", "study_id", studies)

    # --- result / evidence links -------------------------------------------
    add("quantitative_result", "finding_id", claims)
    add("claim_evidence", "finding_id", claims)
    add("relation_evidence", "section_record_id", sections)

    # --- json list links ----------------------------------------------------
    add("relation", "triple_mention_ids", equations, shape="json_list", cap=400000)
    add("relation", "paper_ids", papers, shape="json_list", cap=400000)

    # --- orphans ------------------------------------------------------------
    def orphan(name, sql):
        out["orphans"].append({"childless": name, "count": con.execute(sql).fetchone()[0]})

    orphan("paper with no section",
           "select count(*) from paper p where not exists "
           "(select 1 from section s where s.paper_id=p.paper_id)")
    orphan("paper with no claim (KEPT only)",
           "select count(*) from paper p where not exists "
           "(select 1 from claim c where c.paper_id=p.paper_id and c.v3_status='KEPT')")
    orphan("paper with no dataset",
           "select count(*) from paper p where not exists "
           "(select 1 from dataset d where d.paper_id=p.paper_id)")
    orphan("paper with no study",
           "select count(*) from paper p where not exists "
           "(select 1 from study s where s.paper_id=p.paper_id)")
    orphan("dataset with no cohort/sample/assay",
           "select count(*) from dataset d where not exists "
           "(select 1 from cohort c where c.dataset_id like d.dataset_id||'%') "
           "and not exists (select 1 from sample s where s.dataset_id like d.dataset_id||'%') "
           "and not exists (select 1 from assay a where a.dataset_id like d.dataset_id||'%')")
    orphan("canonical term with no mention",
           "select count(*) from canonical_term t where not exists "
           "(select 1 from term_mention m where m.canonical_term_id=t.term_id)")
    orphan("canonical term with no concept map",
           "select count(*) from canonical_term t where not exists "
           "(select 1 from term_concept_map x where x.term_id=t.term_id)")
    orphan("canonical term with no definition",
           "select count(*) from canonical_term t where not exists "
           "(select 1 from term_definition d where d.term_id=t.term_id)")
    orphan("canonical term with no taxonomy annotation",
           "select count(*) from canonical_term t where not exists "
           "(select 1 from taxonomy_annotation a where a.term_id=t.term_id)")
    orphan("claim with no evidence row",
           "select count(*) from claim c where not exists "
           "(select 1 from claim_evidence e where e.finding_id=c.finding_id)")
    orphan("relation with no evidence",
           "select count(*) from relation r where not exists "
           "(select 1 from relation_evidence e where e.canonical_triple_id=r.canonical_triple_id)")

    unexplained = [c for c in out["checks"] if c.get("unexplained")]
    errors = [c for c in out["checks"] if c.get("error")]
    out["summary"] = {
        "checks": len(out["checks"]),
        "checks_errored": len(errors),
        "checks_with_any_dangling": sum(1 for c in out["checks"] if c.get("dangling_ids")),
        "checks_with_unexplained_dangling": len(unexplained),
        "total_dangling_ids": sum(c.get("dangling_ids", 0) for c in out["checks"]),
        "total_explained_by_tombstone": sum(c.get("explained_by_tombstone", 0) for c in out["checks"]),
        "total_unexplained": sum(c.get("unexplained", 0) for c in out["checks"]),
    }
    emit("d02_referential_integrity", out)
    for c in out["checks"]:
        if c.get("error"):
            print(f"  ERROR {c['table']}.{c['column']}: {c['error']}")
            continue
        flag = ""
        if c["unexplained"]:
            flag = f"  UNEXPLAINED {c['unexplained']:,}"
        elif c["dangling_ids"]:
            flag = f"  (all {c['explained_by_tombstone']:,} tombstoned)"
        if c["dangling_ids"]:
            print(f"  {c['table']}.{c['column']:22s} [{c['shape']:9s}] "
                  f"dangling {c['dangling_ids']:>8,}/{c['ids_seen']:>10,}{flag}")
    for o in out["orphans"]:
        print(f"  ORPHAN {o['childless']:46s} {o['count']:>9,}")
    print("summary", out["summary"])


if __name__ == "__main__":
    main()
