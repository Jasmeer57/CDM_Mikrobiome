"""Draw a blinded random sample of 500 accepted term-to-ontology mappings for manual review; write the sheets.

    ~/venvs/parquet_export/bin/python src/scripts/final_validation/human_spotcheck_mappings_sample.py

Population: the 18,272 term_concept_map rows of CDM 3.0.3 with mapping_disposition_reviewed = 'ACCEPTED' (P05),
i.e. Gemma (G9) and DeepSeek-R1 agreed on the relation; covers 16,750 deduplicated canonical terms (P06). Simple
random sample, n = 500, fixed seed. Shown: term, type, taxonomy category, counts, mapped concept (id, label,
ontology, link) and, where one exists and its paper is CC BY / CC0, an in-paper definition. Hidden in the key: the
two models' relation labels and the string matcher's scores. Writes
outputs/results/benchmark/human_spotcheck_mappings_2026-11-09/ (refuses to overwrite).
"""
from __future__ import annotations

import csv
import hashlib
import random
import re
import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
OUT = ROOT / "outputs/results/benchmark/human_spotcheck_mappings_2026-11-09"
SRC = ROOT / "src/scripts/final_validation"
SEED, N, OVERLAP = 20261109, 500, 100
OPEN = {"cc by", "cc0"}
REL = ["EXACT", "BROADER", "NARROWER", "RELATED", "WRONG"]


def ontology(cid, svc, name):
    if name:
        return name.upper()
    for p in (r"bioontology\.org/ontology/([^/]+)/", r"/obo/([A-Za-z]+)_", r"/obo/([A-Za-z]+)/"):
        m = re.search(p, cid)
        if m:
            return m.group(1).upper()
    if "Thesaurus.owl" in cid:
        return "NCIT"
    m = re.match(r"https?://([^/]+)/([^/#?]+)", cid)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.match(r"([A-Za-z][A-Za-z0-9]*)[:_]", cid)
    return m.group(1).upper() if m else ("UMLS" if svc == "umls" else "")


def link(cid):
    if cid.startswith("http"):
        return cid
    m = re.match(r"NCBITaxon:(\d+)$", cid)
    if m:
        return f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={m.group(1)}"
    m = re.match(r"(?:UMLS:)?(C\d{7})$", cid)
    if m:
        return f"https://uts.nlm.nih.gov/uts/umls/concept/{m.group(1)}"
    return f"https://www.ebi.ac.uk/ols4/search?q={cid}"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    if OUT.exists():
        raise SystemExit("sample already drawn; the draw must happen once")
    rights = {r["paper_id"]: r for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    pop = [r["mapping_row_id"] for r in con.execute(
        "SELECT mapping_row_id FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED' ORDER BY mapping_row_id")]
    assert len(pop) == 18272, f"population {len(pop)} != P05 18,272"
    rnd = random.Random(SEED)
    pick = rnd.sample(pop, N)                           # random presentation order
    rows, key = [], []
    for k, mid in enumerate(pick, 1):
        m = con.execute("""SELECT m.*, c.concept_label, c.source_service, c.ontology_name, t.term, t.cdm_type,
                                  t.mention_count, t.paper_count, t.taxonomy_category, t.taxonomy_subcategory
                           FROM term_concept_map m JOIN concept c USING(concept_id) JOIN canonical_term t USING(term_id)
                           WHERE m.mapping_row_id=?""", (mid,)).fetchone()
        defn, ddoi = "", ""
        for d in con.execute("SELECT definition_text, paper_id FROM term_definition WHERE term_id=? "
                             "ORDER BY (evidence_anchor_status='EXACT') DESC, length(definition_text)", (m["term_id"],)):
            r = rights.get(d["paper_id"], {})
            if r.get("licence", "").lower() in OPEN and d["definition_text"]:
                defn, ddoi = d["definition_text"][:400], r.get("doi", "")
                break
            if not ddoi:
                ddoi = "(definition exists in a paper whose licence does not allow sharing its text)"
        rows.append({"item": k, "term": m["term"], "term_type": m["cdm_type"],
                     "taxonomy": " / ".join(x for x in (m["taxonomy_category"], m["taxonomy_subcategory"]) if x),
                     "mentions": m["mention_count"], "papers": m["paper_count"],
                     "concept_label": m["concept_label"], "ontology": ontology(m["concept_id"], m["source_service"], m["ontology_name"]),
                     "concept_id": m["concept_id"], "concept_link": link(m["concept_id"]),
                     "definition_in_paper": defn, "definition_doi": ddoi})
        key.append({"item": k, "mapping_row_id": mid, "term_id": m["term_id"], "concept_id": m["concept_id"],
                    "gemma_g9": m["relation_llm_g9"], "deepseek_r1": m["relation_deepseek"],
                    "string_matcher_relation": m["mapping_relation"], "candidate_rank": m["candidate_rank"],
                    "match_scores": m["match_scores"], "service": m["source_service_mapping"]})
    OUT.mkdir(parents=True)
    for name, data in (("sample.csv", rows), ("KEY_model_verdicts.csv", key)):
        with open(OUT / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0])); w.writeheader(); w.writerows(data)

    shown = list(rows[0])
    fill = ["MAPPING", "TERM_IS_CONCEPT", "TYPE_CORRECT", "DEFINITION", "NOTES"]
    opts = {"MAPPING": REL, "TERM_IS_CONCEPT": ["Y", "N"], "TYPE_CORRECT": ["Y", "N"],
            "DEFINITION": ["DEFINITION", "MENTION", "WRONG_TERM", "NA"]}
    widths = [6, 28, 14, 22, 9, 8, 30, 12, 26, 30, 60, 22, 14, 16, 14, 14, 36]
    for who, items in (("A", rows), ("B_overlap100", rows[:OVERLAP])):
        wb = Workbook(); ws = wb.active; ws.title = "annotate"
        ws.append(shown + fill)
        for c in ws[1]:
            c.font = Font(bold=True)
        for c in ws[1][len(shown):]:
            c.fill = PatternFill("solid", fgColor="FFF2CC")
        for r in items:
            ws.append([r[c] for c in shown] + [""] * len(fill))
        for i, wdt in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = wdt
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
            row[shown.index("concept_link")].hyperlink = row[shown.index("concept_link")].value
        for j, f in enumerate(fill):
            if f in opts:
                col = chr(65 + len(shown) + j)
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
    files = sorted(p for p in OUT.iterdir() if p.is_file())
    (OUT / "PREREGISTRATION.sha256").write_text("".join(f"{sha(p)}  {p.name}\n" for p in files), encoding="utf-8")
    nd = sum(1 for r in rows if r["definition_in_paper"])
    print(f"population {len(pop)}; sample {N} ({len({r['term'] for r in rows})} distinct terms); "
          f"shareable definitions {nd}; wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
