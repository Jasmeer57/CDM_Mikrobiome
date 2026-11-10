#!/usr/bin/env python3
"""Render the must-cite list from the registry-verified bibliography.json
into Briefings in Bioinformatics reference style (2026-11-07).

Style (OUP/BiB, numbered):
  - numbered [n], in-text before punctuation, ordered by first appearance
    (this render uses a provisional phase order; RENUMBER at submission)
  - authors: all if <=3, else first three + et al.; 'Family I.' format
  - journal: italic ABBREV Year;Volume:Pages  (no issue, per journal example)
  - proceedings: In: *Proceedings ...*, Year, pages
  - preprints: *arXiv* Year;arXiv:ID  /  *medRxiv* Year;ID
  - software / model cards per OUP: 'Developer, Release date, Title,
    Publisher (repository), Identifier'
Every field comes from bibliography.json (registry-verified 2026-11-07).
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
BIB = {r["key"]: r for r in json.load(open(HERE / "bibliography.json"))}

SECTION = [
    ("Argument (Introduction)", [
        "abdill2025", "goncalves2019", "geistlinger2023",
        "langarica2025minerva", "chirumbolo2025minerva", "langarica2025response",
        "hogan2024midred", "hong2025dimbre", "higashi2024harmonization", "chen2025llmbench"]),
    ("Annotated relation corpora used for audit", ["li2016bc5cdr", "luo2022biored"]),
    ("NER programs, corpora and base models", [
        "wei2024pubtator3", "sanger2024hunflair2", "akbik2019flair",
        "neumann2019scispacy", "cohen2017craft", "kim2004jnlpba", "pyysalo2015bionlp13",
        "lee2019biobert", "beltagy2019scibert", "zaratiana2024gliner", "zaratiana2025gliner2"]),
    ("LLMs, embedding, inference and judging", [
        "grattafiori2024llama3", "jiang2023mistral", "abdin2024phi3", "guo2025deepseekr1",
        "gemma2026gemma4", "qwen35card", "deepseek2026v4", "deepseekv4flashcard",
        "deepseekv41card", "zheng2023mtbench", "liu2019sbert", "minilmcard",
        "kwon2023vllm", "ollama2026", "lin2023awq"]),
    ("Vocabularies, services, archives and standards", [
        "schoch2020taxonomy", "brown2015gene", "lipscomb2000mesh", "davis2026ctd",
        "barrett2012bioproject", "leinonen2011", "vasilevsky2022mondo", "gargano2024hpo",
        "bodenreider2004umls", "whetzel2011bioportal", "cote2006ols", "hripcsak2015ohdsi",
        "yilmaz2011mixs", "janssens2018disbiome"]),
    ("Statistics", ["wilson1927", "efron1993bootstrap", "cohen1960kappa"]),
]

PRINT_YEAR = {  # Crossref 'issued' = online date; vol belongs to the print year (per earlier notes)
    "barrett2012bioproject": 2012, "leinonen2011": 2011, "brown2015gene": 2015, "gargano2024hpo": 2024,
}
ABBR = {
    "Cell": "Cell", "Nucleic Acids Research": "Nucleic Acids Res",
    "Scientific Data": "Sci Data", "Nature Biotechnology": "Nat Biotechnol",
    "Database": "Database (Oxford)", "Briefings in Bioinformatics": "Brief Bioinform",
    "Nature Communications": "Nat Commun", "Bioinformatics": "Bioinformatics",
    "BMC Bioinformatics": "BMC Bioinformatics", "BMC Microbiology": "BMC Microbiol",
    "Journal of the American Medical Informatics Association": "J Am Med Inform Assoc",
    "Studies in Health Technology and Informatics": "Stud Health Technol Inform",
    "Bulletin of the Medical Library Association": "Bull Med Libr Assoc",
    "Educational and Psychological Measurement": "Educ Psychol Meas",
    "Journal of the American Statistical Association": "J Am Stat Assoc",
    "Open Biology": "Open Biol",
}
# authors that must not pass through the 'Given Family -> Family I' heuristic
AUTHOR_OVERRIDE = {
    "hripcsak2015ohdsi": ["Hripcsak G", "Duke JD", "Shah NH"],   # Crossref packs full names into 'family'
    "gemma2026gemma4": ["Gemma Team", "El Abd S", "Aggarwal V"],
    "deepseek2026v4": ["DeepSeek-AI", "Xu A", "Lin B"],
    "efron1993bootstrap": ["Efron B", "Tibshirani R"],
}
MODEL_CARD = {"qwen35card": "Qwen", "deepseekv4flashcard": "DeepSeek-AI",
              "deepseekv41card": "DeepSeek-AI", "minilmcard": "Sentence-Transformers"}


def authorfy(name):
    if name.count(" ") == 0 or ":" in name:
        return name
    parts = name.split()
    if len(parts) == 2 and (len(parts[1]) == 1 or parts[1].replace('.', '').isupper()):
        return name  # already 'Family I[JK]'
    fam, given = parts[-1], parts[:-1]
    inits = "".join(p[0] for p in given if p[:1].isalpha())
    return f"{fam} {inits}".strip()


def authors_of(key):
    if key in AUTHOR_OVERRIDE:
        return AUTHOR_OVERRIDE[key]
    return [authorfy(a) for a in BIB[key]["authors"] if a]


def author_str(key):
    au = authors_of(key)
    s = ", ".join(au[:3])
    if len(au) > 3 or len(BIB[key].get("authors", [])) > 3:
        s += " et al"
    return s + "."


def dash(s):
    return s.replace("-", "–") if s else s


def entry(key):
    r = BIB[key]
    role = r.get("role", "")

    # --- OUP software / model-card format -----------------------------
    if key in MODEL_CARD:
        hf = r["url"].replace("https://huggingface.co/", "")
        rel = (r.get("last_modified") or "")[:10]
        return (f"{MODEL_CARD[key]}, {rel or r.get('year') or 'n.d.'} (accessed 2026-11-07): {hf} "
                f"model card, Hugging Face (repository), https://huggingface.co/{hf}.")
    if key == "ollama2026":
        return ("Ollama, Release 0.32.9 (cluster version; accessed 2026-11-07): Ollama local "
                "large-language-model runtime, GitHub (repository), https://github.com/ollama/ollama (MIT license).")

    au = author_str(key)
    astr = au
    title = r["title"]
    venue, yr, vol, pg = r.get("venue"), r.get("year"), r.get("volume"), r.get("pages")
    if key in PRINT_YEAR:
        yr = PRINT_YEAR[key]

    # --- preprints -----------------------------------------------------
    if venue == "arXiv":
        aid = r["identifier"].split(":", 1)[1]
        return f"{astr} {title}. *arXiv* {yr};arXiv:{aid}."
    if venue == "openRxiv":
        return f"{astr} {title}. *medRxiv* {yr};{r['doi'].split('10.1101/')[1]} (preprint)."

    # --- book / book chapter -------------------------------------------
    if key == "efron1993bootstrap":
        return f"{astr} {title}. Boston: Springer, 1993."
    if key == "hripcsak2015ohdsi":  # mEDRA start page 574 verified; end page from IOS chapter pagination
        return (f"{astr} {title}. In: *MEDINFO 2015: eHealth-enabled Health*. "
                f"Amsterdam: IOS Press, 2015, 574–79 (see note).")
    if venue and venue.startswith("Handbook"):
        return f"{astr} {title}. In: *{venue}*. Dordrecht: Springer, {yr}, {dash(pg)}."

    # --- proceedings ----------------------------------------------------
    if venue and venue.startswith("Proceedings"):
        return f"{astr} {title}. In: *{venue}*, {yr}, {dash(pg)}."

    # --- journal --------------------------------------------------------
    abbr = ABBR.get(venue, venue)
    if pg and vol:
        return f"{astr} {title}. *{abbr}* {yr};{vol}:{dash(pg)}."
    if pg and not vol:  # advance-access article number
        return f"{astr} {title}. *{abbr}* {yr};{pg}."
    if vol and not pg:
        return f"{astr} {title}. *{abbr}* {yr};{vol}."
    return f"{astr} {title}. *{abbr}* {yr} (accessed 2026-11-07)."


def main():
    lines = ["# Must-cite list — *Briefings in Bioinformatics* format",
             "",
             "*2026-11-07 render. Every entry is registry-verified (Crossref / PubMed / arXiv API /"
             " Hugging Face API / GitHub API, today) and recorded in"
             " `references_source/bibliography.json` (regenerate with"
             " `references_source/fetch_bibliography.py`; 56 records, 0 errors)."
             " Numbering below is provisional pipeline-phase order — BiB numbers by first appearance"
             " in the text, so RENUMBER at submission and cite [n–m] before punctuation.*",
             "",
             "## Reference list",
             ""]
    keys = []
    n = 0
    for i, (sec, ks) in enumerate(SECTION):
        lines.append(f"### {sec} (provisional [{n+1}–{n+len(ks)}])")
        lines.append("")
        keys += ks
        for k in ks:
            n += 1
            lines.append(f"{n}. {entry(k)}")
        lines.append("")
    lines += ["## In-text style (apply at submission)",
              "",
              "Numbers enclosed in square brackets, before the punctuation: e.g. "
              "*'…curated differential-abundance evidence [3, 11, 12]…'*. 1–3 authors listed in full;"
              " 4+ → first three + et al. Do not include papers in preparation/submitted (a registered"
              " preprint is fine, labelled as such).",
              "",
              "## Notes and open decisions (do not silently resolve)",
              "",
              "- **OHDSI/Hripcsak [50]**: MEDINFO-2015 book chapter; Crossref registers only the start"
              " page 574 — the end page 579 comes from IOS chapter pagination, confirm against the PDF"
              " if exact ranges are required.",
              "- **Barrett [43], Leinonen [44], Brown [40], Gargano [46]**: Crossref 'issued' = online"
              " year; the shown year is the volume's print year (per the earlier verification notes in"
              " VERIFIED_REFERENCES.md).",
              "- **Davis/CTD [42]**: advance access; volume pages must be updated when the 2027-update"
              " issue is assigned.",
              "- **DeepSeek-V4.1-Flash [32]**: no arXiv report; the model repo ships its own tech-report"
              " PDF — cite the model card with an access date.",
              "- **DeepSeek-V4 [30]**: arXiv:2606.19348 verified (register says DeepSeek-AI as first"
              " author); the checkpoint actually run was deepseek-ai/DeepSeek-V4-Flash-0731 [31].",
              "- **Qwen3.5-4B [29]**: no technical report exists — model card only (do not substitute"
              " the Qwen3 report).",
              "- **Gemma [28]**: arXiv:2607.02770 verified via the HF model card of the checkpoint run"
              " (google/gemma-4-E4B-it-qat-w4a16-ct).",
              "- **Mondo [45]**: medRxiv preprint; check for a peer-reviewed version before typesetting.",
              "- **GLiNER-BioMed**: the Bioinformatics 2026 paper needs author confirmation that it"
              " describes the `gliner-large-v2.5-biomed` checkpoint actually run; else cite that model"
              " card as well.",
              "- **OMOP vocabularies**: record the Athena/vocabulary release version + access date in"
              " Methods; the OHDSI paper covers the initiative, not the vocabulary snapshot.",
              "- **FhGenie (Fraunhofer on-prem gateway)**: infrastructure, not cited — describe in Methods.",
              "- **S1000 species corpus**: NOT included — the comparison is not registered yet; register"
              " it first, then cite what was actually used.",
              "- **Not essential here** (kept in the wider verified list): SapBERT (`liu2021sapbert`,"
              " NAACL 2021) if entity-linking baselines are discussed; the spaCy framework itself is"
              " covered by the scispaCy paper [16]."]
    out = HERE.parent / "REFERENCES_BRIEF_BIOINFORM.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out} ({n} entries)")
    print(json.dumps({k: i + 1 for i, k in enumerate(keys)}))


if __name__ == "__main__":
    main()
