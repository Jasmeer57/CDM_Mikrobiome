"""D14 - corpus quality (component A).

Read-only. Tests the 453-record corpus: publication identity, identifier
consistency, full-text availability, section segmentation completeness, text
extraction quality proxies, and text-version provenance. Does not regenerate or
repair anything.
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3

from common import CORPUS, DB, SECTIONS, emit


def load_jsonl(p):
    out = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
PMID_RE = re.compile(r"^\d{1,9}$")


def main():
    out = {}
    papers = load_jsonl(CORPUS / "papers.jsonl")
    out["papers"] = len(papers)
    out["paper_keys"] = sorted(papers[0].keys())

    out["is_canonical"] = dict(collections.Counter(str(p.get("is_canonical")) for p in papers))
    out["validation_status"] = dict(
        collections.Counter(str(p.get("validation_status")) for p in papers)
    )
    out["full_text_completeness"] = dict(
        collections.Counter(str(p.get("full_text_completeness")) for p in papers)
    )

    # publication identity: DOI clusters
    dois = collections.Counter()
    for p in papers:
        d = (p.get("DOI") or "").strip().lower()
        if d:
            dois[d] += 1
    out["distinct_doi"] = len(dois)
    out["papers_without_doi"] = sum(1 for p in papers if not (p.get("DOI") or "").strip())
    out["doi_duplicate_groups"] = sum(1 for d, n in dois.items() if n > 1)
    out["doi_duplicate_extra_rows"] = sum(n - 1 for n in dois.values() if n > 1)
    out["doi_duplicate_examples"] = [
        (d, n) for d, n in dois.most_common(8) if n > 1
    ]

    # identifier format validity
    fmt = collections.Counter()
    bad = collections.defaultdict(list)
    for p in papers:
        d = (p.get("DOI") or "").strip()
        if d:
            if DOI_RE.match(d):
                fmt["doi_ok"] += 1
            else:
                fmt["doi_bad_format"] += 1
                bad["doi"].append((p["paper_id"], d))
        m = (p.get("PMID") or "").strip()
        if m:
            if PMID_RE.match(m):
                fmt["pmid_ok"] += 1
            else:
                fmt["pmid_bad_format"] += 1
                bad["pmid"].append((p["paper_id"], m))
        b = (p.get("bioproject") or "").strip()
        if b:
            if re.match(r"^PRJ[EDN][A-Z]\d+$", b):
                fmt["bioproject_ok"] += 1
            else:
                fmt["bioproject_bad_format"] += 1
                bad["bioproject"].append((p["paper_id"], b))
    out["identifier_format"] = dict(fmt)
    out["identifier_bad_examples"] = {k: v[:8] for k, v in bad.items()}

    # shared BioProjects (many papers -> one project)
    bp = collections.Counter((p.get("bioproject") or "").strip() for p in papers)
    bp.pop("", None)
    out["distinct_bioproject"] = len(bp)
    out["shared_bioproject_groups"] = sum(1 for n in bp.values() if n > 1)
    out["shared_bioproject_extra_papers"] = sum(n - 1 for n in bp.values() if n > 1)
    out["shared_bioproject_examples"] = [(k, n) for k, n in bp.most_common(8) if n > 1]
    out["bioproject_null"] = sum(1 for p in papers if not (p.get("bioproject") or "").strip())

    # metadata richness and text-version provenance (component A reproducibility)
    out["has_pmid"] = sum(1 for p in papers if (p.get("PMID") or "").strip())
    out["has_pmcid"] = sum(1 for p in papers if (p.get("PMCID") or "").strip())
    out["has_title"] = sum(1 for p in papers if (p.get("title") or "").strip())
    out["has_abstract"] = sum(1 for p in papers if (p.get("abstract") or "").strip())
    out["metadata_review_status"] = dict(
        collections.Counter(str(p.get("metadata_review_status")) for p in papers)
    )
    out["full_text_availability"] = dict(
        collections.Counter(str(p.get("full_text_availability")) for p in papers)
    )
    out["full_text_parse_status"] = dict(
        collections.Counter(str(p.get("full_text_parse_status")) for p in papers)
    )
    out["license_name_null"] = sum(1 for p in papers if p.get("license_name") is None)
    out["reuse_permission_checked"] = dict(
        collections.Counter(str(p.get("reuse_permission_checked")) for p in papers)
    )
    out["eligibility_status"] = dict(
        collections.Counter(str(p.get("eligibility_status")) for p in papers)
    )
    out["inclusion_decision"] = dict(
        collections.Counter(str(p.get("inclusion_decision")) for p in papers)
    )
    out["annotation_status"] = dict(
        collections.Counter(str(p.get("annotation_status")) for p in papers)
    )
    # unconverted character accounting: the corpus's own claim of full coverage
    unc = [p.get("conversion_uncovered_chars") for p in papers]
    out["conversion_uncovered_chars_nonzero"] = sum(1 for v in unc if v)
    out["conversion_uncovered_chars_total"] = sum(v or 0 for v in unc)
    out["source_characters_total"] = sum(p.get("source_characters") or 0 for p in papers)
    # source integrity flags recorded upstream
    si = collections.Counter()
    for p in papers:
        s = p.get("source_integrity") or {}
        if s.get("nul_bytes"):
            si["papers_with_nul_bytes"] += 1
        if s.get("non_utf8_bytes"):
            si["papers_with_non_utf8"] += 1
        if s.get("encoding_status"):
            si["encoding_%s" % s["encoding_status"]] += 1
    out["source_integrity"] = dict(si)
    # metadata conflicts recorded per paper
    out["papers_with_metadata_conflicts"] = sum(
        1 for p in papers if p.get("metadata_conflicts")
    )
    out["text_version_ids_distinct"] = len(
        {p.get("text_version_id") for p in papers if p.get("text_version_id")}
    )
    out["sections_discovered_vs_complete"] = {
        "discovered": sum(p.get("sections_discovered") or 0 for p in papers),
        "complete": sum(p.get("sections_complete") or 0 for p in papers),
        "needing_review": sum(p.get("sections_needing_review") or 0 for p in papers),
    }
    out["fulltext_crosscheck_status"] = dict(
        collections.Counter(
            str((p.get("fulltext_crosscheck") or {}).get("status")) for p in papers
        )
    )

    # sections per paper from the frozen DB
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    per = dict(
        c.execute("SELECT paper_id, COUNT(*) FROM section GROUP BY paper_id").fetchall()
    )
    out["db_papers_with_section"] = len(per)
    out["db_sections"] = sum(per.values())
    dist = collections.Counter(per.values())
    out["sections_per_paper_distribution"] = dict(sorted(dist.items()))
    out["papers_with_one_section"] = sorted(p for p, n in per.items() if n == 1)[:15]
    out["papers_with_zero_chars"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT paper_id, SUM(LENGTH(section_text_original)) s "
        "FROM section GROUP BY paper_id HAVING COALESCE(s,0)=0)"
    ).fetchone()[0]

    # section text length distribution and text-quality proxies
    rows = c.execute(
        "SELECT paper_id, section_id_original, section_text_original FROM section"
    ).fetchall()
    lens = []
    nul = 0
    ctrl = 0
    mojibake = 0
    hyphenbreak = 0
    runon = 0
    for pid, sid, txt in rows:
        t = txt or ""
        lens.append(len(t))
        if "\x00" in t:
            nul += 1
        if re.search(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", t):
            ctrl += 1
        if "Â" in t or "â€" in t or "Ã©" in t:
            mojibake += 1
        if re.search(r"\w-\n\w", t):
            hyphenbreak += 1
        if re.search(r"[a-z]{45,}", t):
            runon += 1
    lens_sorted = sorted(lens)
    out["section_chars_total"] = sum(lens)
    out["section_chars_median"] = lens_sorted[len(lens_sorted) // 2]
    out["section_chars_max"] = lens_sorted[-1]
    out["zero_char_sections"] = sum(1 for n in lens if n == 0)
    out["sections_under_200_chars"] = sum(1 for n in lens if 0 < n < 200)
    out["text_quality_proxies"] = {
        "sections_with_nul": nul,
        "sections_with_control_chars": ctrl,
        "sections_with_mojibake": mojibake,
        "sections_with_hyphen_linebreak": hyphenbreak,
        "sections_with_runon_token": runon,
    }

    # the 179-paper text quality split: do withheld papers look different?
    # (structural only; no licence inference here - see D12)
    out["papers_with_zero_char_sections"] = c.execute(
        "SELECT COUNT(DISTINCT paper_id) FROM section WHERE LENGTH(COALESCE(section_text_original,''))=0"
    ).fetchone()[0]

    # section-name vocabulary and segmentation shape
    out["section_type"] = dict(
        collections.Counter(
            r[0] for r in c.execute("SELECT section_type FROM section").fetchall()
        )
    )
    out["section_name_top"] = dict(
        collections.Counter(
            r[0] for r in c.execute("SELECT section_name_normalized FROM section").fetchall()
        ).most_common(20)
    )

    # corpus jsonl layer: entities / triples / findings / studies
    for name in ("sections", "entities", "canonical_triples", "triple_mentions", "findings", "studies"):
        p = CORPUS / ("%s.jsonl" % name)
        if p.exists():
            out["corpus_layer_%s" % name] = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        else:
            out["corpus_layer_%s" % name] = "ABSENT"

    c.close()

    # markdown segment marker integrity (independent of D01's hash test)
    md = sorted(SECTIONS.glob("HMPAPER_*.md"))
    out["markdown_files"] = len(md)
    mk = collections.Counter()
    no_marker = []
    for p in md:
        txt = p.read_text(encoding="utf-8", errors="replace")
        nseg = txt.count("<!-- SEGMENT:")
        nend = txt.count("<!-- END_SEGMENT:")
        mk["segments"] += nseg
        mk["end_segments"] += nend
        if nseg == 0:
            no_marker.append(p.name)
        if nseg != nend:
            mk["unbalanced_files"] += 1
    out["markdown_markers"] = dict(mk)
    out["markdown_files_without_marker"] = no_marker[:10]

    emit("d14_corpus_quality", out)


if __name__ == "__main__":
    main()
