"""Revise the 500-mapping review sheets BEFORE annotation: same sample, more columns filled from pipeline outputs.

    ~/venvs/parquet_export/bin/python src/scripts/final_validation/human_spotcheck_mappings_revise.py

Keeps the identical 500 rows (checked against KEY_model_verdicts.csv) and refuses to run if any reviewer column in
the existing sheets is filled. Adds: taxonomy from taxonomy_annotation (Qwen and Gemma categories, agreement status),
mention and paper counts recomputed from term_mention, the extraction models that found the term, and the ontology's
own definition of the mapped concept (OLS4, BioPortal, UMLS, NCBI Taxonomy rank; only concept ids are sent, no paper
text). Old hashes are kept as PREREGISTRATION_v1.sha256; new ones written to PREREGISTRATION.sha256.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "outputs/results/benchmark/human_spotcheck_mappings_2026-11-09"
SRC = ROOT / "src/scripts/final_validation"
FILL = ["MAPPING", "TERM_IS_CONCEPT", "TYPE_CORRECT", "DEFINITION", "NOTES"]
REL = ["EXACT", "BROADER", "NARROWER", "RELATED", "WRONG"]
def _env_keys():
    keys = dict(os.environ)
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                keys.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return keys


_K = _env_keys()
BP = _K.get("BIOPORTAL_API_KEY"); UM = _K.get("UMLS_API_KEY")
LLM = ROOT / "outputs/results/term_definitions_llm_2026-11-09/sample500/definitions.jsonl"
def _jl(path, key):
    d = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r.get("status", "OK") != "UNPARSED" or r[key] not in d:
                    d[r[key]] = r
            except (ValueError, KeyError):
                pass
    return d


ONTINFO = _jl(ROOT / "outputs/results/ontology_definitions_2026-11-09/concept_ontology_info.jsonl", "concept_id")
_CP = ROOT / "outputs/results/term_definitions_llm_2026-11-09/sample500/completion"
COMP = _jl(_CP / "term_completion.jsonl", "term_id")
CDESC = _jl(_CP / "concept_descriptions.jsonl", "concept_id")
_OC = ROOT / "outputs/results/ontology_definitions_2026-11-09/concept_definitions.jsonl"
ONTCACHE = {}
if _OC.exists():
    for _l in open(_OC, encoding="utf-8"):
        try:
            _r = json.loads(_l); ONTCACHE[_r["concept_id"]] = _r
        except ValueError:
            pass


def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "cdm-review-sheet", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def clean(s):
    return " ".join(re.sub(r"<[^>]+>", " ", s or "").split())[:500]


def ont_definition(cid):
    """(definition, source) for one concept id; '' when the ontology gives none."""
    try:
        m = re.search(r"bioontology\.org/ontology/([^/]+)/(.+)$", cid)
        if m and BP:
            d = get(f"https://data.bioontology.org/ontologies/{m.group(1)}/classes/{urllib.parse.quote(cid, safe='')}",
                    {"Authorization": f"apikey token={BP}"})
            return clean("; ".join(d.get("definition") or [])), f"BioPortal {m.group(1)}"
        m = re.match(r"https?://snomed\.info/id/(\d+)$", cid)
        if m and BP:
            iri = f"http://purl.bioontology.org/ontology/SNOMEDCT/{m.group(1)}"
            d = get(f"https://data.bioontology.org/ontologies/SNOMEDCT/classes/{urllib.parse.quote(iri, safe='')}",
                    {"Authorization": f"apikey token={BP}"})
            return clean("; ".join(d.get("definition") or [])), "BioPortal SNOMEDCT"
        m = re.match(r"https?://id\.nlm\.nih\.gov/mesh/(\w+)$", cid)
        if m and BP:
            iri = f"http://purl.bioontology.org/ontology/MESH/{m.group(1)}"
            d = get(f"https://data.bioontology.org/ontologies/MESH/classes/{urllib.parse.quote(iri, safe='')}",
                    {"Authorization": f"apikey token={BP}"})
            return clean("; ".join(d.get("definition") or [])), "BioPortal MESH"
        m = re.search(r"NCBITaxon[:_](\d+)$", cid) or re.search(r"taxonomy/(\d+)$", cid)
        if m:
            d = get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=taxonomy&id={m.group(1)}&retmode=json")
            r = d["result"][m.group(1)]
            return clean(f"NCBI Taxonomy {r.get('rank', '')} {r.get('scientificname', '')} ({r.get('division', '')}); "
                         "taxonomy entries carry no textual definition"), "NCBI Taxonomy"
        m = re.match(r"(?:UMLS:)?(C\d{7})$", cid)
        if m and UM:
            d = get(f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{m.group(1)}/definitions?apiKey={UM}")
            res = d.get("result") or []
            eng = [x for x in res if x.get("rootSource", "").endswith(("MSH", "NCI", "CSP", "HPO", "MEDLINEPLUS"))] or res
            return (clean(eng[0]["value"]), f"UMLS {eng[0].get('rootSource', '')}") if eng else ("", "UMLS")
        m = re.search(r"Thesaurus\.owl#(C\d+)$", cid)
        if m:
            cid = f"http://purl.obolibrary.org/obo/NCIT_{m.group(1)}"
        if cid.startswith("http"):
            d = get(f"https://www.ebi.ac.uk/ols4/api/terms?iri={urllib.parse.quote(cid, safe='')}")
            terms = (d.get("_embedded") or {}).get("terms") or []
            for t in terms:
                if t.get("description"):
                    return clean(t["description"][0]), f"OLS {t.get('ontology_prefix', '')}"
            return "", "OLS (no definition)"
    except urllib.error.HTTPError as e:
        return "", ("no definition in source (HTTP 404)" if e.code == 404 else f"lookup failed: HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        return "", f"lookup failed: {type(e).__name__}"
    return "", "no source"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    for f in ("ANNOTATION_SHEET_A.xlsx", "ANNOTATION_SHEET_B_overlap100.xlsx"):
        ws = load_workbook(OUT / f)["annotate"]
        head = [c.value for c in ws[1]]
        idx = [head.index(x) for x in FILL if x in head]
        if any(row[i] not in (None, "") for row in ws.iter_rows(min_row=2, values_only=True) for i in idx):
            raise SystemExit(f"{f} already has reviewer input; not revising")
    key = list(csv.DictReader(open(OUT / "KEY_model_verdicts.csv", encoding="utf-8")))
    old = list(csv.DictReader(open(OUT / "sample.csv", encoding="utf-8")))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    global PAPER_EXP
    PAPER_EXP = {}
    for r in con.execute("""SELECT term_id, definition_text, paper_id FROM term_definition
                            WHERE definition_source='ABBREVIATION_EXPANSION' AND definition_text IS NOT NULL
                            ORDER BY (evidence_anchor_status='EXACT') ASC"""):
        PAPER_EXP[r["term_id"]] = (" ".join(r["definition_text"].split())[:150], r["paper_id"])   # EXACT rows last = win
    llm = {}
    if LLM.exists():
        for l in open(LLM, encoding="utf-8"):
            r = json.loads(l)
            if r.get("status") != "UNPARSED" or r["term_id"] not in llm:
                llm[r["term_id"]] = r
    rows = []
    for k, o in zip(key, old):
        assert k["item"] == o["item"]
        t = con.execute("SELECT term, cdm_type, models, n_models FROM canonical_term WHERE term_id=?", (k["term_id"],)).fetchone()
        assert t["term"] == o["term"], k["item"]
        tx = con.execute("SELECT category, subcategory, sub_qwen, sub_gemma, agreement_status FROM taxonomy_annotation "
                         "WHERE term_id=?", (k["term_id"],)).fetchone()
        cnt = con.execute("SELECT count(*), count(DISTINCT paper_id) FROM term_mention WHERE canonical_term_id=?",
                          (k["term_id"],)).fetchone()
        try:
            models = ", ".join(json.loads(t["models"] or "[]"))
        except ValueError:
            models = t["models"] or ""
        info = ONTINFO.get(k["concept_id"]) or {}
        odef, osrc = info.get("definition", ""), info.get("source", "")
        if not odef and not info:
            cached = ONTCACHE.get(k["concept_id"])
            if cached and not cached["source"].startswith("lookup failed"):
                odef, osrc = cached["definition"], cached["source"]
        if not odef and CDESC.get(k["concept_id"], {}).get("description"):
            odef = CDESC[k["concept_id"]]["description"]
            osrc = f"MODEL_GENERATED from concept label (no definition in {o['ontology']} or UMLS)"
        if not odef:
            odef, osrc = "NOT AVAILABLE", osrc or "no source"
        osyn = "; ".join(info.get("synonyms") or []) or f"none listed in {o['ontology']}"
        pexp = PAPER_EXP.get(k["term_id"])
        comp = COMP.get(k["term_id"], {})
        first = llm.get(k["term_id"], {})
        kind = {"DEFINED": "CONTEXTUAL", "GENERAL": "GENERAL", "NON_CONCEPT": "NON_CONCEPT"}.get(first.get("status", ""), first.get("status", ""))
        nonconcept = kind == "NON_CONCEPT"
        if comp.get("is_abbreviation") == "Y":
            mff = comp.get("full_form") or (pexp[0] if pexp else "") or "abbreviation, expansion not determinable from context"
        elif comp.get("is_abbreviation") == "N":
            mff = "n/a (not an abbreviation)"
        else:
            mff = first.get("full_form") or "n/a (not an abbreviation)"
        msyn = comp.get("synonyms") or first.get("synonyms") or []
        msyn = "; ".join(msyn) if msyn else ("n/a (not a concept)" if nonconcept else "none suggested")
        def_doi = o["definition_doi"] or ("n/a" if not o["definition_in_paper"] else "")
        rows.append({"item": o["item"], "term": o["term"], "term_type": o["term_type"],
                     "taxonomy_category": (tx["category"] if tx else "") or "no agreed category",
                     "taxonomy_subcategory": (tx["subcategory"] if tx else "") or "no agreed subcategory",
                     "taxonomy_qwen_gemma": f"{(tx['sub_qwen'] or '-')} / {(tx['sub_gemma'] or '-')}" if tx else "-",
                     "taxonomy_agreement": (tx["agreement_status"] if tx else "") or "none",
                     "mentions": cnt[0], "papers": cnt[1], "found_by_models": models or "-", "n_models": t["n_models"],
                     "concept_label": o["concept_label"], "ontology": o["ontology"], "concept_id": o["concept_id"],
                     "concept_link": o["concept_link"],
                     "ontology_definition": odef, "ontology_definition_source": osrc, "ontology_synonyms": osyn,
                     "definition_in_paper": o["definition_in_paper"] or ("defined in a paper whose licence does not allow sharing; see DOI"
                                                                         if o["definition_doi"].startswith("(") else "not defined in any paper"),
                     "definition_doi": def_doi or "n/a",
                     "paper_full_form": f"{pexp[0]} [{pexp[1]}]" if pexp else "n/a (no expansion written in the papers)",
                     "MODEL_GENERATED_definition": first.get("definition", "") or "NOT AVAILABLE",
                     "MODEL_GENERATED_definition_kind": kind or "-",
                     "MODEL_GENERATED_is_abbreviation": comp.get("is_abbreviation") or "-",
                     "MODEL_GENERATED_full_form": mff,
                     "MODEL_GENERATED_synonyms": msyn})
        if int(o["item"]) % 50 == 0:
            print(o["item"], "rows done", flush=True)
    if not (OUT / "PREREGISTRATION_v1.sha256").exists():
        (OUT / "PREREGISTRATION.sha256").rename(OUT / "PREREGISTRATION_v1.sha256")
    with open(OUT / "sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    shown = list(rows[0])
    opts = {"MAPPING": REL, "TERM_IS_CONCEPT": ["Y", "N"], "TYPE_CORRECT": ["Y", "N"],
            "DEFINITION": ["DEFINITION", "MENTION", "WRONG_TERM", "NA"]}
    wide = {"term": 28, "ontology_definition": 60, "definition_in_paper": 50, "concept_label": 28, "found_by_models": 26,
            "concept_link": 30, "NOTES": 36}
    for who, items in (("A", rows), ("B_overlap100", rows[:100])):
        wb = Workbook(); ws = wb.active; ws.title = "annotate"
        ws.append(shown + FILL)
        for c in ws[1]:
            c.font = Font(bold=True)
        for c in ws[1][len(shown):]:
            c.fill = PatternFill("solid", fgColor="FFF2CC")
        for r in items:
            ws.append([r[c] for c in shown] + [""] * len(FILL))
        from openpyxl.utils import get_column_letter
        for i, h in enumerate(shown + FILL, 1):
            ws.column_dimensions[get_column_letter(i)].width = wide.get(h, 14)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
            row[shown.index("concept_link")].hyperlink = row[shown.index("concept_link")].value
        for j, f in enumerate(FILL):
            if f in opts:
                col = get_column_letter(len(shown) + j + 1)
                dv = DataValidation(type="list", formula1='"' + ",".join(opts[f]) + '"', allow_blank=True)
                ws.add_data_validation(dv); dv.add(f"{col}2:{col}{len(items) + 1}")
        ws.freeze_panes = "C2"
        g = wb.create_sheet("guide")
        for line in (SRC / "human_spotcheck_mappings_guide.txt").read_text(encoding="utf-8").splitlines():
            g.append([line])
        g.column_dimensions["A"].width = 120
        wb.save(OUT / f"ANNOTATION_SHEET_{who}.xlsx")
    for name, dest in (("human_spotcheck_mappings_protocol.md", "PROTOCOL.md"),
                       ("human_spotcheck_mappings_guide.txt", "GUIDE.txt")):
        (OUT / dest).write_bytes((SRC / name).read_bytes())
    files = sorted(p for p in OUT.iterdir() if p.is_file() and not p.name.startswith("PREREGISTRATION"))
    (OUT / "PREREGISTRATION.sha256").write_text("".join(f"{sha(p)}  {p.name}\n" for p in files), encoding="utf-8")
    empty = {c: sum(1 for r in rows if r[c] in ("", None)) for c in shown}
    print("empty cells per column:", {c: n for c, n in empty.items() if n})


if __name__ == "__main__":
    main()
