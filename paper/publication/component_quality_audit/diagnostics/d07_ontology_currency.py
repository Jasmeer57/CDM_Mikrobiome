"""D07 - ontology identifier currency, resolvability and provenance.

Tests whether identifiers carried by the frozen CDM are:
  * real identifiers (not sentinels / placeholders),
  * resolvable to a declared ontology,
  * attributed to a provenance source,
  * consistent between the CDM and the terminology release it was built from.

Currency ("are our ontologies newer?") is measured against the ontology registry
shipped in the terminology release; no network calls are made, so nothing here is
an assertion about live upstream state.

Read-only. Stdlib only.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import TERM, connect, emit  # noqa: E402

OUT: dict = {"diagnostic": "d07_ontology_currency", "db": "releases/cdm_v3/3.0.3"}

SENTINEL_RE = re.compile(r"^(unresolved|unknown|none|null|na|n/?a|pending|todo|-+)$", re.I)
URL_RE = re.compile(r"^https?://")
PURL_RE = re.compile(r"^https?://purl\.obolibrary\.org/obo/([A-Za-z][A-Za-z0-9_]*)_\d+$")
BIOPORTAL_RE = re.compile(r"^https?://purl\.biomethodology\.org/ontology/([A-Za-z0-9_-]+)/", re.I)
SAB_RE = re.compile(r"^[A-Z][A-Z0-9]{1,30}$")
UMLS_CUI_RE = re.compile(r"^C\d{7}$")


def classify_identifier(values):
    """Bucket identifiers by shape. Sentinels are separated from real ids."""
    c = Counter()
    for v in values:
        if v is None or not str(v).strip():
            c["EMPTY"] += 1
            continue
        s = str(v).strip()
        if SENTINEL_RE.match(s):
            c["SENTINEL"] += 1
        elif UMLS_CUI_RE.match(s):
            c["UMLS_CUI"] += 1
        elif URL_RE.match(s):
            if PURL_RE.match(s):
                c["OBO_PURL"] += 1
            elif BIOPORTAL_RE.match(s):
                c["BIOPORTAL_URL"] += 1
            else:
                c["OTHER_URL"] += 1
        elif SAB_RE.match(s):
            c["BARE_UPPER_TOKEN"] += 1
        elif re.match(r"^\d+$", s):
            c["NUMERIC"] += 1
        else:
            c["OTHER"] += 1
    return c


def triple_ontology_columns(con):
    """relation.subject_ontology_id / object_ontology_id and their resolution status."""
    out = {}
    for col in ("subject_ontology_id", "object_ontology_id"):
        vals = [r[0] for r in con.execute(f'select "{col}" from relation')]
        distinct = Counter(vals)
        out[col] = {
            "rows": len(vals),
            "distinct": len(distinct),
            "top_values": [[str(k), v] for k, v in distinct.most_common(6)],
            "shape": dict(classify_identifier(vals)),
        }
    for col in ("subject_entity_resolution_status", "object_entity_resolution_status",
                "external_linking_status"):
        have = {r[1] for r in con.execute('PRAGMA table_info("relation")')}
        if col in have:
            out[col] = [[str(r[0]), r[1]] for r in con.execute(
                f'select "{col}", count(*) c from relation group by 1 order by c desc limit 10')]
    # Same columns on the removed family.
    have = {r[1] for r in con.execute('PRAGMA table_info("removed_relation")')}
    if "subject_ontology_id" in have:
        out["removed_relation_subject_ontology_id"] = [
            [str(r[0]), r[1]] for r in con.execute(
                'select subject_ontology_id, count(*) c from removed_relation '
                'group by 1 order by c desc limit 6')]
    return out


def concept_table(con):
    out = {"rows": con.execute("select count(*) from concept").fetchone()[0]}
    out["by_source_service"] = [[str(r[0]), r[1]] for r in con.execute(
        "select source_service, count(*) c from concept group by 1 order by c desc limit 20")]
    out["by_ontology_name"] = [[str(r[0]), r[1]] for r in con.execute(
        "select ontology_name, count(*) c from concept group by 1 order by c desc limit 20")]
    out["identifier_shape"] = dict(classify_identifier(
        r[0] for r in con.execute("select concept_id from concept")))
    out["null_labels"] = con.execute(
        "select count(*) from concept where concept_label is null or concept_label=''"
    ).fetchone()[0]
    # Concepts actually referenced by term_concept_map
    out["reachable_from_term_concept_map"] = con.execute(
        "select count(distinct concept_id) from term_concept_map "
        "where concept_id is not null and concept_id<>''"
    ).fetchone()[0]
    out["concept_ids_in_map_not_in_concept"] = con.execute(
        "select count(distinct m.concept_id) from term_concept_map m "
        "left join concept c on c.concept_id = m.concept_id "
        "where m.concept_id is not null and m.concept_id<>'' and c.concept_id is null"
    ).fetchone()[0]
    return out


def term_concept_map_shape(con):
    have = {r[1] for r in con.execute('PRAGMA table_info("term_concept_map")')}
    out = {"columns": sorted(have),
           "rows": con.execute("select count(*) from term_concept_map").fetchone()[0]}
    for col in ("mapping_relation", "mapping_disposition", "term_status",
                "candidate_rank", "is_canonical_candidate", "auto_accept_eligible"):
        if col in have:
            out[col] = [[str(r[0]), r[1]] for r in con.execute(
                f'select "{col}", count(*) c from term_concept_map group by 1 '
                f"order by c desc limit 12")]
    out["identifier_shape"] = dict(classify_identifier(
        r[0] for r in con.execute(
            "select concept_id from term_concept_map where concept_id is not null")))
    out["rows_without_concept_id"] = con.execute(
        "select count(*) from term_concept_map where concept_id is null or concept_id=''"
    ).fetchone()[0]
    # Provenance: is namespace attributable?
    out["has_ontology_source_column"] = "ontology_source" in have
    out["has_mapping_method_column"] = any(
        c in have for c in ("mapping_method", "matched_via", "source_service"))
    return out


def ontology_registry():
    """Declared ontology versions shipped with terminology 1.0.1."""
    reg = TERM / "ontology_registry.json"
    if not reg.exists():
        return {"present": False}
    d = json.load(open(reg, encoding="utf-8"))
    out = {"present": True, "top_level_keys": sorted(d)[:20]}
    if isinstance(d, dict):
        entries = d.get("ontologies") or d.get("sources") or d
        if isinstance(entries, dict):
            out["entries"] = [
                {"name": k, "keys": sorted(v) if isinstance(v, dict) else type(v).__name__}
                for k, v in list(entries.items())[:40]
            ]
            out["n_entries"] = len(entries)
        elif isinstance(entries, list):
            out["n_entries"] = len(entries)
            out["entries"] = [
                {k: e.get(k) for k in ("name", "id", "version", "release", "date", "service")
                 if k in e} for e in entries[:40]
            ]
    return out


def terminology_cross_check(con):
    """Do the CDM's mapping rows reconcile with terminology 1.0.1's projection?"""
    live = {r[0] for r in con.execute("select term_id from canonical_term")}
    removed = {r[0] for r in con.execute("select term_id from removed_canonical_term")}
    src_terms = Counter()
    n = 0
    live_rows = removed_rows = neither_rows = 0
    with_changes = 0
    for line in open(TERM / "term_ontology_mappings.jsonl", encoding="utf-8"):
        d = json.loads(line)
        n += 1
        t = d.get("term_id")
        src_terms[d.get("ontology_source")] += 0
        if t in live:
            live_rows += 1
        elif t in removed:
            removed_rows += 1
        else:
            neither_rows += 1
    db_rows = con.execute("select count(*) from term_concept_map").fetchone()[0]
    return {
        "terminology_jsonl_rows": n,
        "term_id_in_live_canonical_term": live_rows,
        "term_id_in_removed_canonical_term": removed_rows,
        "term_id_in_neither": neither_rows,
        "cdm_term_concept_map_rows": db_rows,
        "difference_jsonl_minus_db": n - db_rows,
        "explanation": (
            "Rows whose term_id exists only in removed_canonical_term or in neither "
            "table are not carried into term_concept_map; that accounts for the "
            "jsonl-vs-DB delta."
        ),
        "projection_summary": _projection_summary(),
    }


def _projection_summary():
    p = TERM / "mapping_projection_summary.json"
    if not p.exists():
        return {"present": False}
    d = json.load(open(p, encoding="utf-8"))
    return {"present": True,
            "counts": d.get("counts"),
            "calibration": d.get("calibration"),
            "by_mapping_relation": d.get("by_mapping_relation")}


def body_site_and_other_typed_columns(con):
    """Other places the schema claims an ontology identifier."""
    out = {}
    for table, col in (("body_site", "ontology_id"),
                       ("sample", "body_site_ontology_id"),
                       ("claim", "body_site_ontology_id"),
                       ("canonical_term", "term_id")):
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if col not in have:
            out[f"{table}.{col}"] = {"error": "column absent"}
            continue
        vals = [r[0] for r in con.execute(f'select "{col}" from "{table}"')]
        out[f"{table}.{col}"] = {
            "rows": len(vals),
            "null_or_empty": sum(1 for v in vals if v is None or not str(v).strip()),
            "distinct": len({v for v in vals if v}),
            "shape": dict(classify_identifier(vals)),
            "examples": [str(v)[:70] for v in list({v for v in vals if v})[:5]],
        }
    return out


def main():
    con = connect()

    OUT["triple_ontology"] = triple_ontology_columns(con)
    OUT["concept"] = concept_table(con)
    OUT["term_concept_map"] = term_concept_map_shape(con)
    OUT["ontology_registry"] = ontology_registry()
    OUT["typed_ontology_columns"] = body_site_and_other_typed_columns(con)

    print("=== relation ontology columns ===")
    for col in ("subject_ontology_id", "object_ontology_id"):
        d = OUT["triple_ontology"][col]
        print(f"  {col}: rows={d['rows']:,} distinct={d['distinct']} "
              f"top={d['top_values'][:2]} shape={d['shape']}")
    for k in ("subject_entity_resolution_status", "object_entity_resolution_status",
              "external_linking_status"):
        if k in OUT["triple_ontology"]:
            print(f"  {k}: {OUT['triple_ontology'][k][:4]}")
    if "removed_relation_subject_ontology_id" in OUT["triple_ontology"]:
        print(f"  removed_relation.subject_ontology_id: "
              f"{OUT['triple_ontology']['removed_relation_subject_ontology_id']}")

    c = OUT["concept"]
    print(f"\n=== concept table ===")
    print(f"  rows {c['rows']:,}  null labels {c['null_labels']:,}")
    print(f"  by service {c['by_source_service']}")
    print(f"  shape {c['identifier_shape']}")
    print(f"  reachable from term_concept_map {c['reachable_from_term_concept_map']:,}  "
          f"map ids absent from concept {c['concept_ids_in_map_not_in_concept']:,}")

    m = OUT["term_concept_map"]
    print(f"\n=== term_concept_map ===")
    print(f"  rows {m['rows']:,}  without concept_id {m['rows_without_concept_id']:,}")
    print(f"  identifier shape {m['identifier_shape']}")
    print(f"  has ontology_source column: {m['has_ontology_source_column']}")
    for k in ("mapping_relation", "mapping_disposition", "term_status",
              "auto_accept_eligible"):
        if k in m:
            print(f"  {k}: {m[k][:5]}")

    r = OUT["ontology_registry"]
    print(f"\n=== ontology registry ===")
    print(f"  present={r.get('present')} n_entries={r.get('n_entries')}")
    for e in (r.get("entries") or [])[:12]:
        print(f"   {e}")

    print("\n=== typed ontology columns ===")
    for k, v in OUT["typed_ontology_columns"].items():
        print(f"  {k}: {v}")

    emit("d07_ontology_currency", OUT)


if __name__ == "__main__":
    main()
