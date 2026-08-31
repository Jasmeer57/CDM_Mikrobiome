#!/usr/bin/env python3
"""
Build a structured corpus index from bioproject_data_export.json + papers_txt/.

Extracts and normalises:
  - bioproject_id
  - journal name (parsed from publication_info)
  - publication year
  - first author
  - DOI (normalised from study_id)
  - paper title (study_title or title)
  - abstract/summary
  - body_site, sequencing_type, health_status, sample_type, sample_source
  - experimental_design
  - n_entities (count of extracted entities in the bioproject entry)
  - txt_file_exists (whether papers_txt/<id>.txt exists)
  - txt_word_count (word count of the .txt file if it exists)

Outputs:
  - paper_claims/corpus_index.json   (full structured records)
  - paper_claims/corpus_index.csv    (flat table for quick inspection)
"""
import json, re, sys
from pathlib import Path
from collections import Counter

REPO = Path(r"C:\Users\jkalra\Documents\Microbiome-CDM")
EXPORT_JSON = REPO / "bioproject_data_export.json"
PAPERS_DIR = REPO / "papers_txt"
OUT_JSON = REPO / "paper_claims" / "corpus_index.json"
OUT_CSV = REPO / "paper_claims" / "corpus_index.csv"


def parse_publication_info(pi):
    """Parse publication_info into (journal, year, first_author).

    Two formats:
      comma:    "BMC Microbiology, 2021, Jonguk Park"
      keyvalue: "Journal: Cancers; Year: 2021; First author: Yushinori Uchino"
    """
    if not pi or not isinstance(pi, str):
        return None, None, None

    pi = pi.strip()

    # keyvalue format
    if pi.lower().startswith("journal:"):
        parts = {}
        for seg in pi.split(";"):
            seg = seg.strip()
            if ":" in seg:
                k, v = seg.split(":", 1)
                parts[k.strip().lower()] = v.strip()
        journal = parts.get("journal")
        year = parts.get("year")
        author = parts.get("first author") or parts.get("author")
        return journal, _safe_int(year), author

    # comma format: "Journal Name, Year, Author"
    # Journal names can embed the year: "Nutrients 2021, 13, 2081"
    # So we try to extract a 4-digit year (2000-2030) from parts[0] first,
    # then scan remaining parts for a standalone 4-digit year.
    parts = [p.strip() for p in pi.split(",")]
    journal = parts[0] if parts else None
    year = None
    author = None

    # Try to extract year from journal part (e.g. "Nutrients 2021")
    if journal:
        m = re.search(r"\b(20[0-3]\d)\b", journal)
        if m:
            year = int(m.group(1))
            # Strip the year from journal name for cleaner output
            journal = re.sub(r"\s*20[0-3]\d\s*$", "", journal).strip() or journal

    # Scan remaining parts for year and author
    for p in parts[1:]:
        # Standalone 4-digit year (2000-2030)
        if re.match(r"^(20[0-3]\d)$", p):
            if not year:
                year = int(p)
        elif p and not author:
            author = p
    return journal, year, author


def _safe_int(v):
    if v is None:
        return None
    m = re.search(r"(\d{4})", str(v))
    return int(m.group(1)) if m else None


def parse_doi(study_id):
    """Extract a clean DOI from study_id, which can be:
      - https://doi.org/10.xxx/yyy
      - doi: 10.xxx/yyy
      - 10.xxx/yyy
      - 10.xxx/yyy, PRJNA12345  (with trailing bioproject id)
    """
    if not study_id or not isinstance(study_id, str):
        return None
    s = study_id.strip()
    # strip "doi:" prefix
    s = re.sub(r"^doi:\s*", "", s, flags=re.IGNORECASE)
    # strip "https://doi.org/" prefix
    s = re.sub(r"^https?://doi\.org/", "", s, flags=re.IGNORECASE)
    # take everything up to first comma (strip trailing bioproject id etc.)
    s = s.split(",")[0].strip()
    # validate it looks like a DOI
    if re.match(r"^10\.\d{4,}/", s):
        return s
    return None


def count_words(txt_path):
    """Count words in a text file, handling encoding issues."""
    try:
        text = Path(txt_path).read_text(encoding="utf-8", errors="replace")
        return len(text.split())
    except Exception:
        return 0


def main():
    print(f"Loading: {EXPORT_JSON}")
    data = json.loads(EXPORT_JSON.read_text(encoding="utf-8"))
    bps = data["bioprojects"]
    print(f"  {len(bps)} bioprojects")

    # Build papers_txt lookup
    txt_files = {p.stem: p for p in PAPERS_DIR.glob("*.txt")}
    print(f"  {len(txt_files)} .txt files in papers_txt/")

    records = []
    journal_counter = Counter()
    year_counter = Counter()
    n_with_doi = 0
    n_with_txt = 0
    n_with_journal = 0
    n_with_year = 0
    n_with_author = 0
    n_with_title = 0
    n_with_summary = 0

    for bp in bps:
        pid = bp["bioproject_id"]

        # Parse publication_info
        journal, year, author = parse_publication_info(bp.get("publication_info"))

        # Override journal if publication_info parsing failed but journal field exists
        # (journal field is often garbage, but keep it as fallback)
        if not journal and bp.get("journal"):
            journal = bp.get("journal")

        # Parse DOI
        doi = parse_doi(bp.get("study_id"))

        # Title
        title = bp.get("study_title") or bp.get("title") or None

        # Summary
        summary = bp.get("summary") or None

        # Entity count
        entities = bp.get("entities", [])
        n_entities = len(entities) if entities else 0

        # TXT file
        txt_path = txt_files.get(pid)
        txt_exists = txt_path is not None
        txt_word_count = count_words(txt_path) if txt_exists else 0

        # Type distribution (if entities exist)
        type_dist = {}
        if entities:
            for e in entities:
                et = e.get("entity_type") or e.get("type") or "UNKNOWN"
                type_dist[et] = type_dist.get(et, 0) + 1

        rec = {
            "bioproject_id": pid,
            "doi": doi,
            "journal": journal,
            "year": year,
            "first_author": author,
            "title": title,
            "summary": summary[:500] if summary else None,
            "body_site": bp.get("body_site"),
            "sequencing_type": bp.get("sequencing_type"),
            "health_status": bp.get("health_status"),
            "sample_type": bp.get("sample_type"),
            "sample_source": bp.get("sample_source"),
            "experimental_design": bp.get("experimental_design"),
            "host_organism": bp.get("host_organism"),
            "n_entities": n_entities,
            "entity_type_distribution": type_dist,
            "txt_file_exists": txt_exists,
            "txt_word_count": txt_word_count,
        }
        records.append(rec)

        if journal:
            journal_counter[journal] += 1
            n_with_journal += 1
        if year:
            year_counter[year] += 1
            n_with_year += 1
        if author:
            n_with_author += 1
        if doi:
            n_with_doi += 1
        if txt_exists:
            n_with_txt += 1
        if title:
            n_with_title += 1
        if summary:
            n_with_summary += 1

    # Write JSON
    OUT_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote: {OUT_JSON} ({len(records)} records)")

    # Write CSV
    import csv
    csv_fields = [
        "bioproject_id", "doi", "journal", "year", "first_author",
        "title", "body_site", "sequencing_type", "health_status",
        "sample_type", "sample_source", "experimental_design",
        "host_organism", "n_entities", "txt_file_exists", "txt_word_count",
    ]
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            w.writerow(rec)
    print(f"Wrote: {OUT_CSV}")

    # Summary stats
    print()
    print("=" * 70)
    print("CORPUS INDEX SUMMARY")
    print("=" * 70)
    print(f"  Total bioprojects:       {len(records)}")
    print(f"  With DOI:                {n_with_doi} ({100*n_with_doi/len(records):.0f}%)")
    print(f"  With journal:            {n_with_journal} ({100*n_with_journal/len(records):.0f}%)")
    print(f"  With year:               {n_with_year} ({100*n_with_year/len(records):.0f}%)")
    print(f"  With first author:       {n_with_author} ({100*n_with_author/len(records):.0f}%)")
    print(f"  With title:              {n_with_title} ({100*n_with_title/len(records):.0f}%)")
    print(f"  With summary:            {n_with_summary} ({100*n_with_summary/len(records):.0f}%)")
    print(f"  With .txt file:          {n_with_txt} ({100*n_with_txt/len(records):.0f}%)")
    print()
    print(f"  Top 15 journals:")
    for j, c in journal_counter.most_common(15):
        print(f"    {c:4d}  {j}")
    print()
    print(f"  Year distribution:")
    for y, c in sorted(year_counter.items()):
        print(f"    {y}: {c}")

    # Coverage gap analysis
    missing_txt = [r["bioproject_id"] for r in records if not r["txt_file_exists"]]
    missing_doi = [r["bioproject_id"] for r in records if not r["doi"]]
    missing_journal = [r["bioproject_id"] for r in records if not r["journal"]]
    print()
    if missing_txt:
        print(f"  Missing .txt files ({len(missing_txt)}): {', '.join(missing_txt[:10])}{'...' if len(missing_txt)>10 else ''}")
    if missing_doi:
        print(f"  Missing DOI ({len(missing_doi)}): {', '.join(missing_doi[:10])}{'...' if len(missing_doi)>10 else ''}")
    if missing_journal:
        print(f"  Missing journal ({len(missing_journal)}): {', '.join(missing_journal[:10])}{'...' if len(missing_journal)>10 else ''}")


if __name__ == "__main__":
    main()
