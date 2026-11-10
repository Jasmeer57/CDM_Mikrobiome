"""Flag wording, number and terminology problems in an author-written manuscript file. Never rewrites anything.

    python .opencode/skills/manuscript-style-check/check_manuscript.py FILE [--log-model NAME] [--json]

Checks
  1. claim language the project does not allow (MASTER_VALIDATION_REPORT.md "Not allowed", PUBLICATION_INDEX.md)
  2. numbers that do not appear among the stated values of MANUSCRIPT_CLAIMS_REGISTER.csv
  3. spelling / terminology variants used inconsistently in the same file
For .tex files LaTeX comments are ignored. With --log-model the run is appended to the AI-assistance log
(paper/publication/submission_readiness/AI_ASSIST_LOG.md) so it can be declared.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REGISTER = ROOT / "paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv"
LOG = ROOT / "paper/publication/submission_readiness/AI_ASSIST_LOG.md"

# (pattern, why it is flagged) - sources: MASTER_VALIDATION_REPORT.md:83, PUBLICATION_INDEX.md:59, CLAUDE.md
CLAIM_RULES = [
    (r"\bvalidat\w*", "'validated/validation' only with qualification (e.g. computational checks); never for the CDM itself"),
    (r"\baccura(?:te|cy)\b", "accuracy not established; only F1 on public gold standards measures the NER programs"),
    (r"\brecall\b", "recall not established for the CDM (no human annotation)"),
    (r"\bcompleteness\b|\bcomplete coverage\b", "completeness not established"),
    (r"\bindependent(?:ly)? (?:judges?|confirm\w*|verif\w*)", "LLM judges are not independent confirmation"),
    (r"\bsemantically coherent\b|\bready for adoption\b", "not allowed (MASTER_VALIDATION_REPORT.md)"),
    (r"\blegally cleared\b|\bpublicly available\b|\bfreely available\b|\bopen(?:ly)? available\b|\bDOI\b",
     "no public-availability or DOI claim until the release exists"),
    (r"\bLLMs? (?:outperform\w*|beat\w*|surpass\w*|(?:are|is) better)\b|\boutperform\w* (?:NLP|NER|trained)",
     "'LLMs beat NLP' is not supported"),
    (r"\bhuman[- ](?:validat\w*|annotat\w*|expert|review\w*|curat\w*)|\bmanual(?:ly)? (?:validat\w*|annotat\w*|check\w*)",
     "no human annotation was done [H01]; only BugSigDB is human-curated, by others"),
    (r"\bgold[- ]standard\b", "only for public corpora (BC5CDR, BioRED, S1000); the microbiome corpus has none"),
    (r"\bverif(?:y|ied|ication)\b", "for LLM judges say 'screen' or 'judged', not verification"),
    (r"\b168[,.]?(?:000|464)\b|\b168\s?K\b", "compendium: BioProject-level linkage only, no sample analysis"),
    (r"\bco-?occurrence\b", "the 17,717 generic triples are 'generic (escape) relations' [R02], not co-occurrence"),
    (r"\b100\s?%", "check: Claim F 100% must not be cited; any 100% needs its register ID"),
    (r"\bknowledge graph\b", "the triples are a minor layer (68.7% generic); do not present the work as a KG"),
]

VARIANTS = [(r"\bcatalogue", r"\bcatalog(?!ue)"), (r"normalis", r"normaliz"), (r"harmonis", r"harmoniz"),
            (r"standardis", r"standardiz"), (r"analys(?:e|ed|ing)\b", r"analyz"), (r"characteris", r"characteriz"),
            (r"\borganis", r"\borganiz"), (r"\bmodell(?:ing|ed)\b", r"\bmodel(?:ing|ed)\b"),
            (r"\bdata set", r"\bdataset"), (r"\bopen-source", r"\bopen source")]

NUM = re.compile(r"(?<![\w.\-/])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w\-]|\.\d)(\s?%)?")


def strip_tex_comments(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


def register_values():
    vals, by_val = set(), {}
    for r in csv.DictReader(open(REGISTER, encoding="utf-8")):
        for tok in re.split(r"[/;|\s]+", r["stated"] or ""):
            tok = tok.replace(",", "").rstrip("%")
            try:
                v = float(tok)
            except ValueError:
                continue
            forms = {v, round(v, 1), round(v, 2)}
            if 0 < v < 1:
                forms |= {round(v * 100, 1), round(v * 100)}
            for f in forms:
                vals.add(f)
                by_val.setdefault(f, set()).add(r["claim_id"])
    return vals, by_val


def ignorable(v: float, raw: str, line: str, start: int) -> bool:
    if "." not in raw and "," not in raw and v <= 20:
        return True                                       # small counts, list items, section numbers
    if "." not in raw and "," not in raw and 1900 <= v <= 2035:
        return True                                       # years
    before = line[max(0, start - 12):start]
    return bool(re.search(r"(?:Fig(?:ure)?\.?|Table|Section|Stage|ref|\\cite\{|\[|v|version|Phase)\s*$", before, re.I))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--log-model", help="model name to record in AI_ASSIST_LOG.md (e.g. 'opencode/deepseek-v4.1')")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    path = a.file.resolve()
    tex = path.suffix == ".tex"
    lines = path.read_text(encoding="utf-8").splitlines()
    vals, by_val = register_values()
    claims, numbers = [], []
    text_all = []
    for i, raw in enumerate(lines, 1):
        line = strip_tex_comments(raw) if tex else raw
        if not line.strip():
            continue
        text_all.append(line)
        for pat, why in CLAIM_RULES:
            for m in re.finditer(pat, line, re.I):
                claims.append({"line": i, "match": m.group(0), "why": why, "context": line.strip()[:160]})
        for m in NUM.finditer(line):
            s, pct = m.group(1), m.group(2)
            v = float(s.replace(",", ""))
            if ignorable(v, s, line, m.start()):
                continue
            hit = v in vals or round(v, 1) in vals
            numbers.append({"line": i, "number": s + (pct or "").strip(), "in_register": hit,
                            "ids": sorted(by_val.get(v, by_val.get(round(v, 1), set())))[:6],
                            "context": line.strip()[:160]})
    joined = "\n".join(text_all)
    variants = []
    for a_, b_ in VARIANTS:
        na, nb = len(re.findall(a_, joined, re.I)), len(re.findall(b_, joined, re.I))
        if na and nb:
            variants.append({"forms": [a_, b_], "counts": [na, nb]})

    unmatched = [n for n in numbers if not n["in_register"]]
    out = {"file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
           "claim_language": claims, "numbers_checked": len(numbers), "numbers_not_in_register": unmatched,
           "inconsistent_variants": variants}
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        print(f"# Style check: {out['file']}\n")
        print(f"## Claim language ({len(claims)} flags)")
        for c in claims:
            print(f"- L{c['line']}: '{c['match']}': {c['why']}\n    {c['context']}")
        print(f"\n## Numbers: {len(numbers)} checked, {len(unmatched)} not among register stated values")
        for n in unmatched:
            print(f"- L{n['line']}: {n['number']}\n    {n['context']}")
        print(f"\n## Inconsistent variants ({len(variants)})")
        for v in variants:
            print(f"- /{v['forms'][0]}/ ×{v['counts'][0]} vs /{v['forms'][1]}/ ×{v['counts'][1]}")
    if a.log_model:
        new = not LOG.exists()
        with open(LOG, "a", encoding="utf-8") as f:
            if new:
                f.write("# AI-assistance log (for the BiB AI-use declaration)\n\n"
                        "| Date | Tool / model | File | What the tool did | Flags |\n|---|---|---|---|---|\n")
            f.write(f"| {datetime.date.today()} | {a.log_model} | {out['file']} | manuscript-style-check: flagged "
                    f"wording, numbers, variants (no text written) | {len(claims)} claim, {len(unmatched)} number, "
                    f"{len(variants)} variant |\n")


if __name__ == "__main__":
    main()
