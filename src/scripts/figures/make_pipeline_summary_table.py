"""Generate the pipeline-summary table (LaTeX) from the claims register. Every value is read from the register.

    python src/scripts/figures/make_pipeline_summary_table.py

Writes oup-authoring-template/tables/table_pipeline_summary.tex (a table* body, \\input by manuscript.tex). Values
come only from paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv, looked up by (claim id, section)
(ids are unique since 2026-11-10; triple-reference rows are XR01-XR06); the script stops if a row is missing or not MATCH. Row labels are short
descriptions for the authors to edit; the caption is left to the authors. Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REG = ROOT / "paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv"
OUT = ROOT / "oup-authoring-template/tables/table_pipeline_summary.tex"

rows = {}
for r in csv.DictReader(open(REG, encoding="utf-8")):
    rows[(r["claim_id"], r["section"])] = r
    rows.setdefault((r["claim_id"], None), r)


def v(cid, section=None, i=None):
    r = rows.get((cid, section)) if section else rows.get((cid, None))
    if r is None:
        raise SystemExit(f"register row missing: {cid} {section or ''}")
    if section is None and sum(1 for k in rows if k[0] == cid and k[1]) > 1:
        raise SystemExit(f"{cid} is used twice in the register: give its section")
    if r["status"] != "MATCH":
        raise SystemExit(f"{cid} is not MATCH: {r['status']}")
    s = r["stated"].split("/")
    s = s[i] if i is not None else r["stated"]
    try:
        f = float(s)
        return f"{int(f):,}" if f.is_integer() and "." not in s else s
    except ValueError:
        return s


# (stage, quantity, value, register ids)
T = [
    ("Corpus", "papers / distinct publications", f"{v('C01')} / {v('C02')}", "C01, C02"),
    ("", "sections (SHA-256 hashed)", v("C07"), "C07, C08"),
    ("", "compendium samples in corpus BioProjects", f"{v('C05')} of {v('C06')} ({v('C09')}\\%)", "C05, C06, C09"),
    ("", "papers whose text may be redistributed", f"{v('RT01', i=1)} of {v('RT01', i=0)}", "RT01, RT02"),
    ("Extraction", "mentions, four sources kept separate", v("M01"), "M01"),
    ("", "CPU NER ensemble / Qwen3.5-4B full-body / Qwen3.5-4B section-level / MeSH",
     f"{v('M03')} / {v('M04')} / {v('M05')} / {v('M06')}", "M03--M06"),
    ("Normalisation", "canonical terms (after review)", v("T02"), "T02"),
    ("", "vocabulary mappings: candidates / kept by guards / accepted by two-model agreement",
     f"{v('P01')} / {v('P02')} / {v('P05')}", "P01, P02, P05"),
    ("Catalogue", "evidence-quoted records", v("K01"), "K01"),
    ("", "quotes found verbatim at their offsets", f"{v('K08')}\\%", "K08"),
    ("CDM 3.0.3", "tables / columns", f"{v('X01', 'CDM')} / {v('X02', 'CDM')}", "X01, X02 (CDM)"),
    ("", "registered extraction runs", v("X03", "CDM"), "X03 (CDM)"),
    ("", "relation triples as extracted / with a generic label (before repair)", f"{v('R01')} / {v('R02')}", "R01, R02"),
    ("", "schema, value and provenance tests: pass / fail / conditional",
     f"{v('X07', i=0)} / {v('X07', i=1)} / {v('X07', i=2)}", "X07"),
    ("CDM 3.1.0", "terms after dedup / kept after relevance filter", f"{v('CL01', i=1)} / {v('CL01', i=2)}", "CL01"),
    ("", "accepted concepts after ID normalisation / dedup / kept", f"{v('CL02', i=1)} / {v('CL02', i=2)} / {v('CL02', i=3)}", "CL02"),
    ("", "accepted mappings, clean rows (of which EXACT agreements in 3.0.3)", f"{v('CL03', i=1)} ({v('CL04', i=0)})", "CL03, CL04"),
    ("", "triples with a specific relation and verified cue after repair (interim)", v("CL05", i=0), "CL05"),
    ("", "triple tiers 1 / 2 / 3", f"{v('CL06', i=0)} / {v('CL06', i=1)} / {v('CL06', i=2)}", "CL06"),
    ("", "terms with a model definition: contextual / general / descriptive",
     f"{v('CL08', i=0)} / {v('CL08', i=1)} / {v('CL08', i=2)}", "CL08"),
    ("Re-typing", "triples with a specific, cue-verified relation after repair and re-typing (final; of 25,788)", f"{v('JV05', i=0)} ({v('JV05', i=1)}\\%)", "JV05"),
    ("", "kept terms in one of the 14 CDM types (of 116,755; none left generic)", f"{v('JV06', i=3)} ({v('JV06', i=4)}\\%)", "JV06"),
    ("Evaluation", "best exact F1, public gold standards (BC5CDR / BioRED)", f"{v('B01')} / {v('B02')}", "B01, B02"),
    ("", "BugSigDB: same direction of reported findings, of n pairs (chance)",
     f"{v('N05', i=0)}\\% of {v('N05', i=1)} ({v('N05', i=2)}\\%)", "N05"),
    ("", "triples judged against a CC BY / CC0 sentence (LLM screen)", v("W02"), "W02"),
    ("", "judged supported / partial / not supported / conflicting",
     " / ".join(x + "\\%" for x in v("W03").split("/")), "W03"),
    ("", "catalogue judges, three models, 51,837 held-out records: Cohen $\\kappa$ best pair / Fleiss $\\kappa$",
     f"{v('JV01', i=1)} / {v('JV02', i=0)}", "JV01, JV02"),
]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    L = ["%% GENERATED by src/scripts/figures/make_pipeline_summary_table.py from the claims register -- do not edit;",
         "%% re-run the script. Row labels: author review. Caption: written by the authors (in manuscript.tex).",
         # The body is 24 two-line rows: at the sn-jnl body size it is taller than
         # the text block and collides with the page number, so it is set one size
         # down with tightened row spacing (checked by rendering the page).
         r"\footnotesize",
         r"\renewcommand{\arraystretch}{0.95}%",
         r"\tabcolsep=3pt%",
         # ragged-right paragraph columns: justified narrow columns stretch the inter-word
         # gaps badly (needs the array package, loaded in manuscript.tex);
         # tabular* breaks in this class (tested)
         r"\begin{tabular}{@{}l>{\raggedright\arraybackslash}p{0.40\textwidth}"
         r">{\raggedright\arraybackslash}p{0.27\textwidth}l@{}}",
         r"\toprule",
         r"Stage & Quantity & Value & Register \\", r"\midrule"]
    for k, (stage, what, val, ids) in enumerate(T):
        if stage and k:
            L.append(r"\midrule")
        L.append(f"{stage} & {what} & {val} & {ids} \\\\")
    L += [r"\botrule", r"\end{tabular}"]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(OUT.relative_to(ROOT), len(T), "rows")


if __name__ == "__main__":
    main()
