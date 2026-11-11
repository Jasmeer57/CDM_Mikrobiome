"""Generate the formal schema specification of the CDM 3.x model from the introspected 3.1.0 DB.

Inputs (all produced from the frozen DB, opened read-only):
  schema/db_profile.json, schema/key_check.csv, schema/referential_integrity.csv   (introspect.py)
  releases/cdm_v3/3.0.3/remediation/CDM_COLUMN_DICTIONARY.csv and UPDATED_ENTITY_REGISTRY_PROPOSAL.csv
  crosswalk/*.csv (build_crosswalk.py) -> slot/class mappings to MIxS, PROV-O, Biolink
Outputs (outputs/results/schema_exports_v32_2026-11-11/schema/):
  microbiome_cdm_v3.linkml.yaml   LinkML schema: one class per table, typed slots, identifiers / unique keys,
                                  enums for small controlled value sets, references as declared ranges
  microbiome_cdm_v3.ddl.sql       SQLite DDL with PRIMARY KEY / UNIQUE / FOREIGN KEY constraints
  fk_declarations.csv             every reference with how it is declared (SQL FK / LinkML range / logical only)
  REFERENTIAL_INTEGRITY.md        orphan counts per reference (from introspect.py)
The human_review extension (3.2.0-candidate) is included: columns added by import_human_review.py and the
human_review_protocol table.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema_common import (CDM_VERSION, DICTIONARY_303, KEYS, OUT, REFS, REGISTRY_303, SCHEMA_ID,  # noqa: E402
                           sha256_file, DB_310)

ALT_UNIQUE = {"section": [["paper_id", "section_id_original"]], "paper": [["bioproject"]]}
ENUM_NAME_RE = re.compile(r"(status|_type$|^type|kind|role|decision|verdict|relation$|family|tier|disposition|"
                          r"agreement|direction$|_flag$|category|_level$|stage$|^claim_source$|_class$)")
PV_RE = re.compile(r"^[A-Za-z0-9_.:\- /()+,]+$")
HR_EXT = [("protocol_id", "HumanReviewProtocol", "Pre-registered review protocol of this verdict."),
          ("sample_item", "integer", "Item number in the pre-registered sample (sample.csv)."),
          ("review_kind", "string", "INDEPENDENT (one reviewer) or ADJUDICATED (agreed label)."),
          ("decision_field", "string", "Sheet column holding the primary verdict (MAPPING or SUPPORT)."),
          ("verdicts_json", "string", "All verdict fields of the item as JSON."),
          ("review_date_source", "string", "How review_date was determined."),
          ("sheet_sha256", "string", "SHA-256 of the completed annotation sheet."),
          ("preregistration_sha256", "string", "SHA-256 of the protocol's PREREGISTRATION.sha256 file."),
          ("import_run", "string", "Import run id (prov:wasGeneratedBy).")]
HRP_COLS = [("protocol_id", "Protocol id."), ("title", "Title."), ("target_entity", "CDM table reviewed."),
            ("population", "Population sampled."), ("sampling", "Sampling design and seed."),
            ("n_items", "Number of sampled items."), ("reviewers", "Anonymised reviewer ids."),
            ("blinding", "Blinding."), ("protocol_path", "Repo-relative path of PROTOCOL.md."),
            ("protocol_sha256", "SHA-256 of PROTOCOL.md."), ("preregistration_path", "Path of PREREGISTRATION.sha256."),
            ("preregistration_sha256", "SHA-256 of PREREGISTRATION.sha256."), ("sample_path", "Path of sample.csv."),
            ("sample_sha256", "SHA-256 of sample.csv."), ("adjudication_status", "Adjudication status."),
            ("approval_status", "Approval status.")]


def camel(t: str) -> str:
    return "".join(p.capitalize() for p in t.split("_") if p) or t


def load_csv(p: Path):
    return list(csv.DictReader(open(p, newline="")))


def storage_range(c) -> tuple[str, bool]:
    st = {k: v for k, v in (c.get("storage_types") or {}).items() if k != "null"}
    if not st:
        return "string", False
    if set(st) == {"integer"}:
        return "integer", False
    if set(st) <= {"integer", "real"}:
        return "float", False
    return "string", len(st) > 1


def main():
    sdir = OUT / "schema"
    prof = json.loads((sdir / "db_profile.json").read_text())["tables"]
    keys = {r["table"]: r for r in load_csv(sdir / "key_check.csv")}
    ri = load_csv(sdir / "referential_integrity.csv")
    dic = {(r["table"], r["column"]): r for r in load_csv(DICTIONARY_303)}
    reg = {r["entity"].lower(): r for r in load_csv(REGISTRY_303)}
    status = {}
    for t, e in prof.items():
        if t == "cdm_entity_status":
            break
    cw = OUT / "crosswalk"
    mixs = load_csv(cw / "crosswalk_mixs.csv") if (cw / "crosswalk_mixs.csv").exists() else []
    storms = load_csv(cw / "crosswalk_storms.csv") if (cw / "crosswalk_storms.csv").exists() else []
    provm = load_csv(cw / "crosswalk_provo.csv") if (cw / "crosswalk_provo.csv").exists() else []
    blc = load_csv(cw / "crosswalk_biolink_classes.csv") if (cw / "crosswalk_biolink_classes.csv").exists() else []

    slot_maps = defaultdict(lambda: defaultdict(set))   # (table, col) -> level -> {curies}
    slot_storms = defaultdict(set)
    for r in mixs:
        for a in filter(None, [x.strip() for x in r["cdm_attributes"].split("+")]):
            if r["level"] != "none":
                slot_maps[tuple(a.split(".", 1))][r["level"]].add(r["mixs_id"])
    for r in storms:
        for a in filter(None, [x.strip() for x in r["cdm_attributes"].split("+")]):
            if r["level"] in ("exact", "close"):
                slot_storms[tuple(a.split(".", 1))].add("STORMS " + r["storms_item"])
    class_maps = defaultdict(lambda: defaultdict(set))
    for r in provm:
        if r["cdm_column"] == "(whole table)":
            class_maps[r["cdm_table"]][r["level"]].add(r["prov_term"])
        elif not r["cdm_column"].startswith("key="):
            slot_maps[(r["cdm_table"], r["cdm_column"])][r["level"]].add(r["prov_term"])
    for r in blc:
        class_maps[r["cdm_table"]][r["level"]].add(r["biolink_class"])

    # reference index: (child, col) -> parent table (single-column, resolvable to an identifier)
    ref_by_col = {}
    fk_rows = []
    for (ct, cc, pt, pc, mv, src), rr in zip(REFS, ri):
        assert rr["child_table"] == ct and rr["child_columns"] == "+".join(cc)
        pkey = KEYS.get(pt, ([], ""))[0] if pt != "*" else []
        single_to_id = len(cc) == 1 and pc == pkey
        alt = any(pc == u for u in ALT_UNIQUE.get(pt, [])) or (pc == pkey)
        if pt == "*":
            how = "LinkML: polymorphic (target_entity + target_id); checked in the candidate DB"
        elif mv:
            how = "LinkML: multivalued range (';'-separated list); not an SQL FK"
        elif alt:
            how = "SQL FOREIGN KEY + LinkML range" if single_to_id else "SQL FOREIGN KEY (composite) + LinkML annotation"
        else:
            how = "logical only (parent columns not a key)"
        fk_rows.append({**{k: rr.get(k, "") for k in ("child_table", "child_columns", "parent_table",
                                                       "parent_columns", "multivalued", "source", "status",
                                                       "non_null_rows", "orphan_rows",
                                                       "orphan_rows_resolving_in_archive",
                                                       "unexplained_orphan_rows")}, "declared_as": how})
        if len(cc) == 1 and pt != "*":
            ref_by_col[(ct, cc[0])] = (pt, pc, mv, single_to_id, rr)

    schema = {
        "id": SCHEMA_ID + "/v3",
        "name": "microbiome_cdm_v3",
        "title": "Microbiome literature Common Data Model (CDM) 3.x",
        "version": CDM_VERSION,
        "description": (
            "Formal schema of the provenance-traceable microbiome literature CDM, generated by introspection of the "
            "frozen release 3.1.0 (" + DB_310.name + ") plus the 3.2.0-candidate human_review extension. "
            "Classes = tables, slots = columns. Keys and references were inferred from the 3.0.3 column dictionary "
            "and by name/value matching, and every key and reference was checked against the data "
            "(schema/key_check.csv, schema/referential_integrity.csv). Ranges that name a class are foreign-key-style "
            "references. Text values follow SQLite dynamic typing; empty string = missing."),
        "license": "CC-BY-4.0",
        "prefixes": {"linkml": "https://w3id.org/linkml/", "mcdm": SCHEMA_ID + "/", "MIXS": "https://w3id.org/mixs/",
                     "biolink": "https://w3id.org/biolink/vocab/", "prov": "http://www.w3.org/ns/prov#",
                     "skos": "http://www.w3.org/2004/02/skos/core#", "schema": "http://schema.org/"},
        "default_prefix": "mcdm",
        "default_range": "string",
        "imports": ["linkml:types"],
        "subsets": {}, "enums": {}, "classes": {},
    }
    modules = {}
    for r in reg.values():
        modules[r["entity"].lower()] = r["module"]
    ces = prof.get("cdm_entity_status")
    validation = {}
    for t, e in sorted(prof.items()):
        if e["type"] != "table":
            continue
        cname = camel(t)
        kcols, ksrc = KEYS.get(t, ([], "none"))
        kc = keys.get(t, {})
        rg = reg.get(t, {})
        desc = rg.get("purpose") or f"Table `{t}` of CDM 3.1.0."
        cls = {"description": desc, "annotations": {"sql_table": t, "rows_3_1_0": e["rows"],
                                                    "key_source": ksrc, "key_check": kc.get("status", "NO_KEY")},
               "attributes": {}}
        if rg.get("module"):
            cls["annotations"]["module"] = rg["module"]
            cls["in_subset"] = [rg["module"]]
            schema["subsets"].setdefault(rg["module"], {"description": f"CDM module {rg['module']}"})
        for lvl, terms in class_maps.get(t, {}).items():
            cls.setdefault(f"{lvl}_mappings" if lvl != "none" else "related_mappings", []).extend(sorted(terms))
        if len(kcols) > 1 and kc.get("status") == "VALID":
            cls["unique_keys"] = {f"{t}_pk": {"unique_key_slots": kcols}}
        for u in ALT_UNIQUE.get(t, []):
            cls.setdefault("unique_keys", {})[f"{t}_uk_{'_'.join(u)}"] = {"unique_key_slots": u}
        for c in e["columns"]:
            col = c["name"]
            rng, mixed = storage_range(c)
            d = dic.get((t, col), {})
            a = {}
            text = (d.get("definition") or "").strip()
            if not text and d.get("extraction_rule"):
                text = d["extraction_rule"].strip()
            a["description"] = text or f"Column `{col}` of `{t}`."
            ann = {"null_or_empty_rows": (c.get("null") or 0) + (c.get("empty") or 0),
                   "distinct_values": c.get("distinct")}
            if mixed:
                ann["mixed_storage"] = ",".join(sorted(k for k in c["storage_types"] if k != "null"))
            if d.get("logical_type"):
                ann["logical_type"] = d["logical_type"]
            if (t, col) in ref_by_col:
                pt, pc, mv, single_to_id, rr = ref_by_col[(t, col)]
                if single_to_id:
                    a["range"] = camel(pt)
                ann["references"] = f"{pt}.{'+'.join(pc)}"
                ann["orphan_rows"] = rr.get("orphan_rows", "")
                if rr.get("orphan_rows_resolving_in_archive") not in (None, "", "0"):
                    ann["orphan_rows_resolving_in_archive"] = rr["orphan_rows_resolving_in_archive"]
                if mv:
                    a["multivalued"] = True
                    ann["serialisation"] = "'; '-separated list in SQL"
            if "range" not in a:
                a["range"] = rng
            if len(kcols) == 1 and col == kcols[0] and kc.get("status") == "VALID":
                a["identifier"] = True
                a["required"] = True
                a.pop("multivalued", None)
                if a["range"] not in ("string", "integer"):
                    a["range"] = "string"
            elif col in kcols:
                a["required"] = True
            vals = c.get("values")
            if (vals and rng == "string" and not mixed and ENUM_NAME_RE.search(col) and "range" in a
                    and a["range"] == "string" and not col.endswith("_id")):
                pv = [v for v in vals if v != ""]
                if 0 < len(pv) <= 25 and all(PV_RE.match(v) and len(v) <= 60 for v in pv):
                    ename = f"{cname}{camel(col)}Enum"
                    schema["enums"][ename] = {"description": f"Values observed in {t}.{col} (3.1.0).",
                                              "permissible_values": {v: {} for v in pv}}
                    a["range"] = ename
            for lvl, terms in slot_maps.get((t, col), {}).items():
                a.setdefault(f"{lvl}_mappings", []).extend(sorted(terms))
            if slot_storms.get((t, col)):
                ann["storms_items"] = "; ".join(sorted(slot_storms[(t, col)]))
            a["annotations"] = ann
            cls["attributes"][col] = a
        if t == "human_review":
            cls["description"] = ("Human verdicts on CDM rows (3.2.0-candidate: populated from the pre-registered "
                                  "mapping review and triple check; reviewer ids anonymised).")
            cls["annotations"]["extension"] = "3.2.0-candidate columns added by import_human_review.py"
            for col, rng, ds in HR_EXT:
                cls["attributes"][col] = {"description": ds, "range": rng,
                                          "annotations": {"added_in": CDM_VERSION}}
            cls["attributes"]["review_id"].update(identifier=True, required=True)
            cls["attributes"]["target_entity"]["description"] = "CDM table of the reviewed row."
            cls["attributes"]["target_id"]["description"] = ("Key of the reviewed row in target_entity "
                                                             "(polymorphic reference).")
        schema["classes"][cname] = cls
    schema["classes"]["HumanReviewProtocol"] = {
        "description": "Pre-registered human review protocol (3.2.0-candidate).",
        "annotations": {"sql_table": "human_review_protocol", "added_in": CDM_VERSION},
        "attributes": {c: ({"description": d, "identifier": True, "required": True} if c == "protocol_id"
                           else {"description": d, "range": "integer" if c == "n_items" else "string"})
                       for c, d in HRP_COLS}}
    (sdir / "microbiome_cdm_v3.linkml.yaml").write_text(
        "# Generated by src/scripts/fixes_v32/schema/build_linkml.py from CDM 3.1.0 (read-only); do not edit.\n" +
        yaml.safe_dump(schema, sort_keys=False, allow_unicode=True, width=120))

    # --------------------------- DDL --------------------------------------------------------------------------
    ddl = ["-- Microbiome CDM 3.x (" + CDM_VERSION + ") SQLite DDL with declared keys and foreign keys.",
           "-- Generated by src/scripts/fixes_v32/schema/build_linkml.py from the introspected 3.1.0 DB.",
           "-- Column order equals 3.1.0 (INSERT ... SELECT * is valid). Declared types only where the stored values",
           "-- are of one storage class (no affinity conversion); mixed columns are declared without a type.",
           "-- ';'-list references and polymorphic human_review.target_id are not SQL FKs (see fk_declarations.csv).",
           "PRAGMA foreign_keys = ON;", ""]
    fks = defaultdict(list)
    for (ct, cc, pt, pc, mv, src) in REFS:
        if pt == "*" or mv:
            continue
        pkey = KEYS.get(pt, ([], ""))[0]
        if pc == pkey or any(pc == u for u in ALT_UNIQUE.get(pt, [])):
            fks[ct].append((cc, pt, pc))
    order_tables = [t for t, e in sorted(prof.items()) if e["type"] == "table"]
    for t in order_tables:
        e = prof[t]
        kcols = KEYS.get(t, ([], ""))[0]
        kok = keys.get(t, {}).get("status") == "VALID"
        lines = []
        for c in e["columns"]:
            rng, mixed = storage_range(c)
            st = {k for k in (c.get("storage_types") or {}) if k != "null"}
            typ = {"integer": "INTEGER", "float": "REAL"}.get(rng, "TEXT") if not mixed else ""
            if rng == "float" and st != {"real"}:
                typ = ""  # integer+real mixture: no affinity, to keep values byte-identical
            lines.append(f'  "{c["name"]}"' + (f" {typ}" if typ else ""))
        if t == "human_review":
            lines += [f'  "{c}" ' + ("INTEGER" if r == "integer" else "TEXT") for c, r, _ in HR_EXT]
        if kcols and kok:
            lines.append("  PRIMARY KEY (" + ", ".join(f'"{k}"' for k in kcols) + ")")
        elif t == "human_review":
            lines.append('  PRIMARY KEY ("review_id")')
        for u in ALT_UNIQUE.get(t, []):
            lines.append("  UNIQUE (" + ", ".join(f'"{k}"' for k in u) + ")")
        for cc, pt, pc in fks.get(t, []):
            lines.append("  FOREIGN KEY (" + ", ".join(f'"{x}"' for x in cc) + f') REFERENCES "{pt}" (' +
                         ", ".join(f'"{x}"' for x in pc) + ")")
        if t == "human_review":
            lines.append('  FOREIGN KEY ("protocol_id") REFERENCES "human_review_protocol" ("protocol_id")')
        ddl.append(f'CREATE TABLE "{t}" (\n' + ",\n".join(lines) + "\n);")
    ddl.append('CREATE TABLE "human_review_protocol" (\n' + ",\n".join(
        f'  "{c}" ' + ("INTEGER" if c == "n_items" else "TEXT") + (" PRIMARY KEY" if c == "protocol_id" else "")
        for c, _ in HRP_COLS) + "\n);")
    (sdir / "microbiome_cdm_v3.ddl.sql").write_text("\n".join(ddl) + "\n")

    with open(sdir / "fk_declarations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fk_rows[0]))
        w.writeheader()
        w.writerows(fk_rows)
    n_fk = sum(len(v) for v in fks.values()) + 1
    tot = sum(int(r["orphan_rows"] or 0) for r in fk_rows)
    unexpl = sum(int(r["unexplained_orphan_rows"] or 0) for r in fk_rows)
    md = ["# Referential integrity of CDM 3.1.0 (read-only check)", "",
          f"- References checked: {len([r for r in fk_rows if r['parent_table'] != '*'])} "
          f"(+1 polymorphic human_review.target_id, checked in the candidate DB)",
          f"- Declared as SQL FOREIGN KEY in the DDL: {n_fk} (incl. human_review.protocol_id)",
          f"- References with orphans: {sum(1 for r in fk_rows if r['status'] == 'ORPHANS')}; orphan rows "
          f"{tot:,}; of these resolving in an archive table (removed_canonical_term / removed_relation): "
          f"{tot - unexpl:,}; unexplained: {unexpl:,}", "",
          "| child | parent | declared as | non-null rows | orphan rows | in archive | unexplained |", "|---|---|---|---|---|---|---|"]
    for r in fk_rows:
        if r["parent_table"] == "*":
            continue
        md.append(f"| {r['child_table']}.{r['child_columns']} | {r['parent_table']}.{r['parent_columns']} | "
                  f"{r['declared_as']} | {r['non_null_rows']} | {r['orphan_rows']} | "
                  f"{r['orphan_rows_resolving_in_archive']} | {r['unexplained_orphan_rows']} |")
    (sdir / "REFERENTIAL_INTEGRITY.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:6]))
    print(f"classes {len(schema['classes'])}, enums {len(schema['enums'])}, "
          f"slots {sum(len(c['attributes']) for c in schema['classes'].values())}")


if __name__ == "__main__":
    main()
