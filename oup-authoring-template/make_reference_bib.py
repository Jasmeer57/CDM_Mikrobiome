#!/usr/bin/env python3
"""Convert the registry-verified bibliography.json into reference.bib (BibTeX).

Mechanical format conversion only:
  - input:  ../paper/publication/submission_readiness/references_source/bibliography.json
            (56 records, re-verified against Crossref / PubMed / arXiv API /
            Hugging Face API / GitHub API on 2026-11-07)
  - output: ./reference.bib (overwrites; the template's sample bibliography is
            kept as reference_template_sample.bib)

Entry type is inferred from the record (journal article, book, inproceedings,
arXiv preprint, model card / software -> @misc). Authors are emitted as
"Family, I." for people; records whose author list is an organisation
(Hugging Face org, GitHub repo, corporate strings) are emitted as braced
literals so BibTeX does not abbreviate them.

Re-run after every re-verification:  python3 make_reference_bib.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "paper" / "public" / "submission_readiness" / "references_source" / "bibliography.json"
# 'public' above is only a typo guard; resolve the real path explicitly:
if not SRC.exists():
    SRC = HERE.parent / "paper" / "publication" / "submission_readiness" / "references_source" / "bibliography.json"

DATE_VERIFIED = None  # read from records below


def tex_escape(s: str) -> str:
    if s is None:
        return ""
    out = s
    for ch, esc in (("\\", r"$\backslash$"), ("&", r"\&"), ("%", r"\%"),
                    ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                    ("{", r"\{"), ("}", r"\}")):
        out = out.replace(ch, esc)
    return out


def looks_like_corporate(name: str) -> bool:
    """No capitals pattern of a person = treat as corporate literal."""
    toks = name.split()
    if len(toks) == 1:
        return True  # 'deepseek-ai', 'ollama', 'Sentence-Transformers'
    alpha_first = re.match(r"[A-Z]", toks[0])
    if not alpha_first:
        return True  # 'on behalf of the International ...'
    return False


def init_token(t: str) -> str:
    """Initialise one name token; keep hyphen compounds ('Wei-Lin' -> 'W.-L.')."""
    # PubMed-style compound initials arrive as one all-caps token without
    # separators ('PH' in 'Li PH', 'YY' in 'Sun YY'): expand letter by letter
    # so no initials are dropped ('Li PH' -> 'Li, P.H.').
    parts = [p for p in re.split(r"-", t) if p]
    inits = []
    for p in parts:
        if len(p) > 1 and p.isalpha() and p.isupper():
            for ch in p:
                inits.append(ch.upper())
            continue
        c = next((ch for ch in p if ch.isalpha()), None)
        if c is None:
            continue
        inits.append(c.upper())
    if not inits:
        return ""
    if len(inits) == 1:
        return inits[0] + "."
    return (".").join(inits) + "."  # 'Wei-Lin' -> 'W.-L.', 'PH' -> 'P.H.'


def parse_author(name: str) -> str:
    """Return a BibTeX author field fragment."""
    name = name.strip()
    if not name:
        return ""
    if looks_like_corporate(name):
        return "{" + name + "}"
    toks = name.replace(".", "").split()
    last = toks[-1]
    # Families stored as 'Abdill R' (already Family-Initial) end in a short
    # all-caps token; 'Lianmin Zheng' (Given Family) ends in a proper family.
    if len(last) <= 3 and last.isupper():
        family, given = toks[0], toks[1:]           # 'Hogan W' -> initial is the last token
    else:
        family, given = last, toks[:-1]             # 'Lianmin Zheng' -> Given Family
    inits = "".join(init_token(g) for g in given)
    return f"{family}, {inits}" if inits else family


def author_field(authors):
    frags = [parse_author(a) for a in authors if a]
    # BiB renders 3 authors + et al.; 'and others' = 'et al.' in BibTeX.
    if len(frags) > 3:
        frags = frags[:3] + ["others"]
    return " and ".join(frags)


def bib_entry(r: dict) -> str:
    key = r["key"]
    venue = (r.get("venue") or "").strip()
    year = r.get("year")
    authors = r.get("authors") or []
    author = author_field(authors)
    title = tex_escape(r.get("title", ""))
    f = {
        "author": author,
        "title": "{" + title + "}",
        "year": str(year) if year else None,
    }
    if venue.startswith("Proceedings"):
        typ = "inproceedings"
        f["booktitle"] = "{" + tex_escape(venue) + "}"
        if r.get("doi"):
            f["url"] = "https://doi.org/" + tex_escape(r["doi"])
    elif venue == "arXiv" or (r.get("identifier") or "").startswith("arxiv:"):
        typ = "article"
        f["journal"] = "{arXiv}"
        f["note"] = tex_escape(r.get("identifier") or "")
    elif venue in ("Hugging Face", "GitHub"):
        typ = "misc"
        if r.get("url"):
            f["howpublished"] = r"\url{" + r["url"] + "}"
        note = ["Registry-verified " + (r.get("verified") or "")]
        if r.get("license"):
            note.append("License: " + r["license"])
        if not year and r.get("last_modified"):
            note.append("Last modified " + r["last_modified"][:10])
        f["note"] = tex_escape("; ".join(note))
    elif venue and venue.lower().endswith(("springer us", "springer")) or "Springer" in venue:
        typ = "book"
        f["publisher"] = "{" + tex_escape(venue) + "}"
        if r.get("doi"):
            f["url"] = "https://doi.org/" + tex_escape(r["doi"])
    else:
        typ = "article"
        if venue:
            f["journal"] = "{" + tex_escape(venue) + "}"
        if r.get("doi"):
            f["url"] = "https://doi.org/" + tex_escape(r["doi"])
    if r.get("volume"):
        f["volume"] = str(r["volume"])
    if r.get("issue") and typ == "article":
        f["number"] = str(r["issue"])
    if r.get("pages"):
        f["pages"] = str(r["pages"]).replace("-", "--")
    # brace every value EXCEPT the bare numeric year
    order = ["author", "title", "journal", "booktitle", "publisher", "year",
             "volume", "number", "pages", "howpublished", "note", "url"]
    fields = []
    for k in order:
        v = f.get(k)
        if not v:
            continue
        if k == "year" and str(v).isdigit():
            fields.append(f"{k} = {v}")
        else:
            fields.append(f"{k} = {{{str(v)}}}")
    body = ",\n  ".join(fields)
    return f"@{typ}{{{key},\n  {body}\n}}\n"


def main():
    records = json.load(open(SRC, encoding="utf-8"))
    bad = [r["key"] for r in records if "error" in r]
    if bad:
        raise SystemExit(f"bibliography.json contains error records; refusing: {bad}")
    verified = sorted({(r.get("verified") or "") for r in records})
    header = (
        "%% GENERATED FILE - do not edit by hand.\n"
        "%% Source: submission_readiness/references_source/bibliography.json\n"
        "%% All records re-verified against their registries on: "
        + (", ".join(v for v in verified if v) or "(dates in records)") + "\n"
        "%% Regenerate with: python3 make_reference_bib.py\n%%\n"
    )
    entries = "\n".join(bib_entry(r) for r in records)
    out = HERE / "reference.bib"
    if not (HERE / "reference_template_sample.bib").exists():
        old = HERE / "reference.bib"
        if old.exists() and not old.read_text(encoding="utf-8", errors="ignore").startswith("%% GENERATED FILE"):
            old.rename(HERE / "reference_template_sample.bib")
    out.write_text(header + entries, encoding="utf-8")
    print(f"wrote {out} ({len(records)} entries)")


if __name__ == "__main__":
    main()
