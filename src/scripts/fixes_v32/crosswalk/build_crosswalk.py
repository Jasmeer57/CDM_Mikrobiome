"""Build the field-level crosswalk CDM 3.1.0 <-> MIxS / STORMS / Biolink / PROV-O and its coverage counts.

Inputs: the official term lists fetched to outputs/scratch/standards_fetch_2026-11-11/ (fetch_standards.sh records
URL, version, licence, sha256 in STANDARDS_SOURCES.json), the curated mapping table curated_mappings.py, and the
3.1.0 DB profile (schema/db_profile.json from introspect.py) for column existence and population counts.
Every standard term in the curated table must exist in the fetched file and every CDM column must exist in the DB;
otherwise the build fails.

Outputs (outputs/results/schema_exports_v32_2026-11-11/crosswalk/):
  crosswalk_mixs.csv, crosswalk_storms.csv, crosswalk_biolink_classes.csv, crosswalk_biolink_cdm_types.csv,
  crosswalk_biolink_predicates.csv, crosswalk_provo.csv, coverage.json, COVERAGE.md
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import yaml
from openpyxl import load_workbook
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema_common import OUT, STANDARDS, ro_connect  # noqa: E402
import curated_mappings as CM  # noqa: E402

LEVELS = ("exact", "close", "broad", "none")
HOLD = ("exact", "close")  # "can hold" = exact or close


def load_profile():
    p = json.loads((OUT / "schema/db_profile.json").read_text())["tables"]
    cols = {}
    for t, e in p.items():
        if e["type"] != "table":
            continue
        for c in e["columns"]:
            cols[(t, c["name"])] = e["rows"] - (c.get("null") or 0) - (c.get("empty") or 0)
    return p, cols


def check_attrs(spec: str, cols) -> tuple[list[str], int]:
    """'a.b + c.d' -> list, max populated count; fails on unknown columns."""
    parts = [x.strip() for x in spec.split("+")]
    for x in parts:
        t, c = x.split(".", 1)
        if (t, c) not in cols:
            raise SystemExit(f"crosswalk names unknown CDM column {x}")
    return parts, max(cols[tuple(x.split(".", 1))] for x in parts)


def mixs(cols):
    d = yaml.safe_load(open(STANDARDS / "mixs_v7.0.1_mixs.yaml"))
    cl, sl = d["classes"], d["slots"]
    sets = {"MIMARKS-survey (MimarksS)": cl["MimarksS"]["slots"], "HostAssociated": cl["HostAssociated"]["slots"],
            "HumanGut": cl["HumanGut"]["slots"]}
    order = []
    for v in sets.values():
        order += [s for s in v if s not in order]
    for s in CM.MIXS:
        if s not in sl:
            raise SystemExit(f"MIxS slot {s} not in v7.0.1")
    # compendium layer: BioSample attributes carried verbatim as tag/value pairs
    con = ro_connect()
    tags = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT tag, count(DISTINCT srs), count(DISTINCT project) FROM compendium_sample_tag GROUP BY tag")}
    rows = []
    for s in order:
        req = any((cl[c].get("slot_usage") or {}).get(s, {}).get("required") for c in ("MimarksS",)) or \
            sl[s].get("required", False)
        lit = [m for m in CM.MIXS.get(s, []) if not m[0].startswith("compendium")]
        comp = [m for m in CM.MIXS.get(s, []) if m[0].startswith("compendium")]
        base = {"mixs_slot": s, "mixs_id": sl[s].get("slot_uri"), "title": sl[s].get("title"),
                "in_sets": "; ".join(k for k, v in sets.items() if s in v), "mimarks_survey_required": bool(req)}
        if lit:
            attrs, n = check_attrs(lit[0][0], cols)
            base.update(cdm_attributes=" + ".join(attrs), level=lit[0][1], justification=lit[0][2],
                        cdm_populated_rows=n)
        else:
            base.update(cdm_attributes="", level="none", justification="no CDM attribute holds this information",
                        cdm_populated_rows=0)
        if comp:
            attrs, n = check_attrs(comp[0][0], cols)
            base.update(compendium_attribute=" + ".join(attrs), compendium_level=comp[0][1])
        tagname = s if s in tags else None
        base.update(compendium_tag=tagname or "", compendium_tag_samples=tags[tagname][0] if tagname else 0,
                    compendium_tag_projects=tags[tagname][1] if tagname else 0)
        if not comp:
            base.update(compendium_attribute="compendium_sample_tag(tag=%s)" % s if tagname else "",
                        compendium_level="exact" if tagname else "none")
        rows.append(base)
    return rows, sets


def storms(cols):
    wb = load_workbook(STANDARDS / "STORMS_Excel_1.03.xlsx", read_only=True, data_only=True)
    ws = wb["Checklist"]
    items, section, prev = [], None, None
    for r in ws.iter_rows(values_only=True):
        r = list(r) + [None] * 7
        num, item, rec, src = r[0], r[1], r[2], r[3]
        if num is not None and item is None and rec is None and str(num) not in ("Version:", "Number"):
            section = str(num).strip()
            continue
        if num is None or str(num) in ("Version:", "Number") or item is None:
            continue
        n = str(num).strip()
        if n == "4.1" and prev == "4.9":  # Excel stored 4.10 as the number 4.1
            n = "4.10"
        prev = n
        items.append({"storms_item": n, "section": section, "item": str(item).strip(),
                      "recommendation": str(rec or "").strip(), "item_source": str(src or "").strip()})
    nums = [i["storms_item"] for i in items]
    if len(nums) != len(set(nums)):
        raise SystemExit(f"duplicate STORMS item numbers: {[x for x, c in Counter(nums).items() if c > 1]}")
    for k in CM.STORMS:
        if k not in nums:
            raise SystemExit(f"STORMS item {k} not in checklist 1.03")
    for i in items:
        m = CM.STORMS.get(i["storms_item"])
        if m:
            attrs, n = check_attrs(m[0][0], cols)
            i.update(cdm_attributes=" + ".join(attrs), level=m[0][1], justification=m[0][2], cdm_populated_rows=n)
        else:
            i.update(cdm_attributes="", level="none", justification="no CDM attribute holds this information",
                     cdm_populated_rows=0)
    return items


def biolink(cols, profile):
    d = yaml.safe_load(open(STANDARDS / "biolink_v4.4.6_biolink-model.yaml"))
    classes, slots = d["classes"], d["slots"]

    def cls_ok(curie):
        name = curie.split(":", 1)[1]
        # Biolink class names are space-separated in the YAML ("organism taxon"); convert CamelCase
        import re
        key = re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
        alt = {k.lower().replace(" ", ""): k for k in classes}
        k = classes.get(key) and key or alt.get(name.lower())
        if not k:
            raise SystemExit(f"Biolink class {curie} not in 4.4.6")
        c = classes[k]
        return k, bool(c.get("mixin")), bool(c.get("abstract")), bool(c.get("deprecated"))

    def pred_ok(curie):
        name = curie.split(":", 1)[1].replace("_", " ")
        if name not in slots:
            raise SystemExit(f"Biolink predicate {curie} not in 4.4.6")
        s = slots[name]
        anc, cur = [], s
        while cur and cur.get("is_a"):
            anc.append(cur["is_a"])
            cur = slots.get(cur["is_a"])
        return {"is_predicate": "related to" in anc or name == "related to", "abstract": bool(s.get("abstract")),
                "mixin": bool(s.get("mixin")), "deprecated": bool(s.get("deprecated")),
                "canonical": bool((s.get("annotations") or {}).get("canonical_predicate")),
                "inverse": s.get("inverse") or ""}

    out_c = []
    for t, (cu, lvl, why) in CM.BIOLINK_CLASSES.items():
        if t not in profile:
            raise SystemExit(f"unknown CDM table {t}")
        k, mx, ab, dep = cls_ok(cu)
        out_c.append({"cdm_table": t, "rows": profile[t]["rows"], "biolink_class": cu, "level": lvl,
                      "justification": why, "biolink_mixin": mx, "biolink_abstract": ab, "biolink_deprecated": dep})
    con = ro_connect()
    tcount = dict(con.execute("SELECT cdm_type, count(*) FROM canonical_term GROUP BY 1").fetchall())
    out_t = []
    for ty, n in sorted(tcount.items(), key=lambda x: -x[1]):
        cu, lvl, why = CM.BIOLINK_CDM_TYPE[ty]
        k, mx, ab, dep = cls_ok(cu)
        out_t.append({"cdm_type": ty, "canonical_terms": n, "biolink_category": cu, "level": lvl,
                      "justification": why, "biolink_mixin": mx, "biolink_abstract": ab, "biolink_deprecated": dep})
    for r in out_t:
        if r["biolink_mixin"] or r["biolink_abstract"] or r["biolink_deprecated"]:
            raise SystemExit(f"category {r['biolink_category']} is mixin/abstract/deprecated")
    ecount = {}
    for side in ("subject", "object"):
        for ty, n in con.execute(f"SELECT {side}_entity_type, count(*) FROM relation GROUP BY 1"):
            ecount[ty] = ecount.get(ty, 0) + n
    out_e = []
    for ty, n in sorted(ecount.items(), key=lambda x: -x[1]):
        cu, lvl, why = CM.BIOLINK_ENTITY_TYPE[ty]
        k, mx, ab, dep = cls_ok(cu)
        if mx or ab or dep:
            raise SystemExit(f"category {cu} is mixin/abstract/deprecated")
        out_e.append({"relation_entity_type": ty, "endpoint_occurrences": n, "biolink_category": cu, "level": lvl,
                      "justification": why})
    rcount = dict(con.execute("SELECT relation, count(*) FROM triple_tier GROUP BY 1").fetchall())
    out_p = []
    for rel, n in sorted(rcount.items(), key=lambda x: -x[1]):
        if rel not in CM.BIOLINK_PRED:
            raise SystemExit(f"no Biolink mapping for relation {rel}")
        cu, lvl, why, extra = CM.BIOLINK_PRED[rel]
        info = pred_ok(cu) if cu else {}
        if cu and (not info["is_predicate"] or info["mixin"] or info["deprecated"]):
            raise SystemExit(f"{cu} is not a usable predicate: {info}")
        out_p.append({"cdm_relation": rel, "triples": n, "biolink_predicate": cu or "", "level": lvl,
                      "justification": why, "export_reversed": bool(extra.get("reverse")),
                      "cdm_direction": extra.get("cdm_direction", ""), **{f"biolink_{k}": v for k, v in info.items()}})
    return out_c, out_t, out_p, out_e, d.get("version")


def provo(profile):
    g = Graph()
    g.parse(STANDARDS / "prov-o_20130430.ttl", format="turtle")
    prov = "http://www.w3.org/ns/prov#"
    terms = {str(s).replace(prov, "prov:") for s in g.subjects() if str(s).startswith(prov)}
    rows = []
    for key, (term, lvl, why) in CM.PROV.items():
        if term not in terms:
            raise SystemExit(f"PROV-O term {term} not in the W3C ontology file")
        if key.startswith("TABLE:"):
            t = key[6:]
            if t not in profile:
                raise SystemExit(f"unknown table {t}")
            rows.append({"cdm_table": t, "cdm_column": "(whole table)", "rows_populated": profile[t]["rows"],
                         "prov_term": term, "level": lvl, "justification": why})
            continue
        hits = 0
        for t, e in profile.items():
            if e["type"] != "table":
                continue
            for c in e["columns"]:
                if c["name"] == key:
                    hits += 1
                    rows.append({"cdm_table": t, "cdm_column": key,
                                 "rows_populated": e["rows"] - (c.get("null") or 0) - (c.get("empty") or 0),
                                 "prov_term": term, "level": lvl, "justification": why})
        if key == "derived_from":  # a run_metadata key, not a column
            rows.append({"cdm_table": "run_metadata", "cdm_column": "key='derived_from' / 'derived_from_310'",
                         "rows_populated": 2, "prov_term": term, "level": lvl, "justification": why})
            hits += 1
        if not hits:
            raise SystemExit(f"PROV mapping names column {key} that exists in no table")
    used = sorted({r["prov_term"] for r in rows})
    return rows, used, terms


def write(path: Path, rows: list[dict]):
    fields = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    out = OUT / "crosswalk"
    out.mkdir(parents=True, exist_ok=True)
    profile, cols = load_profile()
    m_rows, sets = mixs(cols)
    s_rows = storms(cols)
    b_cls, b_typ, b_pred, b_ent, bl_version = biolink(cols, profile)
    p_rows, p_used, p_terms = provo(profile)
    for name, rows in (("crosswalk_mixs.csv", m_rows), ("crosswalk_storms.csv", s_rows),
                       ("crosswalk_biolink_classes.csv", b_cls), ("crosswalk_biolink_cdm_types.csv", b_typ),
                       ("crosswalk_biolink_predicates.csv", b_pred),
                       ("crosswalk_biolink_entity_types.csv", b_ent), ("crosswalk_provo.csv", p_rows)):
        write(out / name, rows)

    def lv(rows, key="level", subset=None):
        rows = [r for r in rows if subset is None or subset(r)]
        c = Counter(r[key] for r in rows)
        return {"n": len(rows), **{k: c.get(k, 0) for k in LEVELS},
                "can_hold_exact_or_close": sum(c.get(k, 0) for k in HOLD),
                "populated_exact_or_close": sum(1 for r in rows if r[key] in HOLD and r.get("cdm_populated_rows", 1))}
    cov = {
        "definitions": {"exact": "same meaning and granularity", "close": "same information, different granularity "
                        "or value syntax (paper-reported, group-level)", "broad": "CDM attribute more general",
                        "none": "not held", "can_hold": "exact + close"},
        "mixs_v7.0.1": {
            "literature_layer": {
                "all_95_slots(MimarksS+HostAssociated+HumanGut)": lv(m_rows),
                "MIMARKS-survey_43_slots": lv(m_rows, subset=lambda r: "MimarksS" in r["in_sets"]),
                "MIMARKS-survey_required_slots": lv(m_rows, subset=lambda r: r["mimarks_survey_required"]),
                "HostAssociated_50_slots": lv(m_rows, subset=lambda r: "HostAssociated" in r["in_sets"]),
                "HumanGut_37_slots": lv(m_rows, subset=lambda r: "HumanGut" in r["in_sets"])},
            "compendium_layer_biosample_tags": {
                "slots_present_as_tag_or_column": sum(1 for r in m_rows if r["compendium_level"] == "exact"),
                "of": len(m_rows),
                "note": "SRA BioSample attributes of the 156,330 compendium samples, carried verbatim; describes "
                        "what the table holds, not a result on the compendium"}},
        "storms_1.03": {"items": lv(s_rows),
                        "by_section": {sec: lv(s_rows, subset=lambda r, sec=sec: r["section"] == sec)
                                       for sec in dict.fromkeys(r["section"] for r in s_rows)}},
        "biolink_" + str(bl_version): {
            "cdm_tables_mapped": lv(b_cls, subset=None) | {"n": len(b_cls)},
            "cdm_types": {"types": len(b_typ), **Counter(r["level"] for r in b_typ),
                          "terms_with_specific_category": sum(r["canonical_terms"] for r in b_typ
                                                              if r["biolink_category"] != "biolink:NamedThing")},
            "relations": {"labels": len(b_pred), **Counter(r["level"] for r in b_pred),
                          "triples_exportable_as_edges": sum(r["triples"] for r in b_pred if r["biolink_predicate"]),
                          "triples_exact_or_close": sum(r["triples"] for r in b_pred if r["level"] in HOLD),
                          "triples_related_to_only": sum(r["triples"] for r in b_pred
                                                         if r["biolink_predicate"] == "biolink:related_to")}},
        "prov-o_2013-04-30": {"column_mappings": len(p_rows), **Counter(r["level"] for r in p_rows),
                              "distinct_prov_terms_used": len(p_used), "prov_terms_used": p_used,
                              "starting_point_terms_used": [t for t in CM.PROV_STARTING_POINT if t in p_used],
                              "starting_point_terms_not_used": [t for t in CM.PROV_STARTING_POINT if t not in p_used]},
    }
    (out / "coverage.json").write_text(json.dumps(cov, indent=1, default=int))
    md = ["# Crosswalk coverage (CDM 3.1.0 attributes; 3.2.0-candidate package)", "",
          "Levels: exact = same meaning and granularity; close = same information but paper-reported at study/"
          "cohort/sample-group level or free text; broad = CDM attribute more general; none = not held. "
          "'Can hold' = exact + close.", ""]
    mm = cov["mixs_v7.0.1"]["literature_layer"]
    for k, v in mm.items():
        md.append(f"- MIxS {k}: exact {v['exact']}, close {v['close']}, broad {v['broad']}, none {v['none']} "
                  f"(can hold {v['can_hold_exact_or_close']}/{v['n']})")
    c = cov["mixs_v7.0.1"]["compendium_layer_biosample_tags"]
    md.append(f"- MIxS slots present verbatim in the compendium BioSample tags: {c['slots_present_as_tag_or_column']}"
              f"/{c['of']}")
    v = cov["storms_1.03"]["items"]
    md.append(f"- STORMS 1.03 items: exact {v['exact']}, close {v['close']}, broad {v['broad']}, none {v['none']} "
              f"(can hold {v['can_hold_exact_or_close']}/{v['n']})")
    b = cov["biolink_" + str(bl_version)]
    md.append(f"- Biolink {bl_version}: {len(b_cls)} CDM tables mapped to classes; {b['cdm_types']['types']} CDM types "
              f"-> categories; {b['relations']['labels']} relation labels -> predicates "
              f"({b['relations']['triples_exact_or_close']} triples exact/close, "
              f"{b['relations']['triples_related_to_only']} only biolink:related_to)")
    p = cov["prov-o_2013-04-30"]
    md.append(f"- PROV-O: {p['column_mappings']} table/column mappings using {p['distinct_prov_terms_used']} PROV terms;"
              f" starting-point terms used {len(p['starting_point_terms_used'])}/12 "
              f"(not used: {', '.join(p['starting_point_terms_not_used'])})")
    (out / "COVERAGE.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
