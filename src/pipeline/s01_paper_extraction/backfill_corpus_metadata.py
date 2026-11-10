#!/usr/bin/env python
"""Offline metadata backfill for the 453-paper corpus.

Sources (all local, no network):
  1. data/168000-samples-paper/fulltext/manifest.csv  (compendium: doi/pmid/pmcid/title/journal/year)
  2. data/168000-samples-paper/projects.csv            (compendium: doi links, sample_type)
  3. data/corpus/id_map.csv                       (corpus_id -> accession -> doi/title)
  4. data/papers_txt/<ACCESSION>.txt                   (inline DOI/PMCID/identifiers scraped from header text)

Targets:
  - data/corpus/records/HMPAPER_*.json  B_publication_metadata (+ G_study_metadata)
  - data/corpus/corpus_tracking.csv     doi/pmid/pmcid/year/journal

Idempotent: only fills empty fields, never overwrites non-empty values.
A backup of corpus_tracking.csv and a JSON change log are written to
data/corpus/logs/ on every run that makes changes.

Usage:
  PYTHONPATH=src python src/scripts/backfill_corpus_metadata.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

RECORDS_DIR = PROJECT_ROOT / "data" / "corpus" / "records"
TRACKING_CSV = PROJECT_ROOT / "data" / "corpus" / "corpus_tracking.csv"
ID_MAP_CSV = PROJECT_ROOT / "data" / "corpus" / "id_map.csv"
COMPENDIUM_MANIFEST = PROJECT_ROOT / "data/168000-samples-paper" / "fulltext" / "manifest.csv"
COMPENDIUM_PROJECTS = PROJECT_ROOT / "data/168000-samples-paper" / "projects.csv"
BACKUP_DIR = PROJECT_ROOT / "data" / "corpus" / "logs"
PAPERS_TXT_DIR = PROJECT_ROOT / "data/papers_txt"

B_FIELDS = ("title", "doi", "pmid", "pmcid", "journal", "publication_year")
TRACKING_FIELDS = ("title", "doi", "pmid", "pmcid", "year", "journal")

DOI_RE = re.compile(
    r'(?:https?://(?:dx\.)?doi\.org/|DOI\s*[:/]?\s*|doi\s*[:/]?\s*)(10\.\d{4,9}/[^\s"<>;,)]+)',
    re.IGNORECASE,
)
# trailing run-together chars like "10.1186/...-16721Research" from PDF text gluing
DOI_TAIL_RE = re.compile(r"([0-9])([A-Za-z].*)$")
PMCID_RE = re.compile(r"\b(PMC\d{4,8})\b")


def is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v in ([], {})


def load_csv_index(path: Path, key: str, encoding: str = "utf-8-sig") -> dict:
    if not path.exists():
        print(f"[warn] missing source file: {path}", file=sys.stderr)
        return {}
    out = {}
    with path.open(encoding=encoding) as fh:
        for r in csv.DictReader(fh):
            k = (r.get(key) or "").strip()
            if k:
                out[k] = {k2: (v or "").strip() for k2, v in r.items()}
    return out


def norm_doi(v: str) -> str:
    v = (v or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if v.lower().startswith(prefix.lower()):
            v = v[len(prefix):]
    return v.strip()


def get_doi(row: dict) -> str:
    v = norm_doi(row.get("doi") or "")
    return v


def get_year(row: dict) -> str:
    v = (row.get("year") or "").strip()
    if len(v) >= 4 and v[:4].isdigit():
        return v[:4]
    return ""


def clean_scraped_doi(v: str) -> str:
    """Strip run-together PDF tail text from a scraped DOI (e.g. '...-16721Research')."""
    m = DOI_TAIL_RE.search(v)
    if m and len(m.group(2)) > 0 and v.count("/") >= 1:
        # only trim if the tail starts right after a digit without separator,
        # and the trimmed form still looks like a DOI
        candidate = v[: m.start() + len(m.group(1))]
        if re.fullmatch(r"10\.\d{4,9}/\S+", candidate):
            return candidate
    return v


def scrape_paper_text(acc: str) -> dict:
    """Extract DOI / PMCID from the header of the local extracted full text."""
    path = PAPERS_TXT_DIR / f"{acc}.txt"
    out = {"doi": "", "pmcid": ""}
    if not path.exists():
        return out
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:6000]
    except OSError:
        return out
    m = DOI_RE.search(head)
    if m:
        out["doi"] = clean_scraped_doi(m.group(1))
    m = PMCID_RE.search(head)
    if m:
        out["pmcid"] = m.group(1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = ap.parse_args()

    compendium = load_csv_index(COMPENDIUM_MANIFEST, "project")
    projects = load_csv_index(COMPENDIUM_PROJECTS, "project")
    id_map = load_csv_index(ID_MAP_CSV, "corpus_id")

    tracking_rows: list[dict] = []
    with TRACKING_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        tracking_fields = list(reader.fieldnames or [])
        tracking_rows = list(reader)
    tracking_by_id = {r["corpus_id"]: r for r in tracking_rows}

    # Load all 453 records once, track changes per (corpus_id, field, target)
    changes = []
    b_fill = collections.Counter()
    tr_fill = collections.Counter()
    record_updates: dict[str, dict] = {}

    expected_ids = [f"HMPAPER_{i:06d}" for i in range(1, 454)]
    for cid in expected_ids:
        rec_path = RECORDS_DIR / f"{cid}.json"
        if not rec_path.exists():
            changes.append({"corpus_id": cid, "field": "_record", "target": "records",
                            "old": "", "new": "MISSING_RECORD"})
            continue
        rec = json.loads(rec_path.read_text())
        b: dict = rec.get("B_publication_metadata") or {}
        acc = (rec.get("bioproject_accession") or "").strip()
        comp = compendium.get(acc, {})
        proj = projects.get(acc, {})
        imap = id_map.get(cid, {})

        sources = {
            "compendium": {
                "title": comp.get("title", ""),
                "doi": get_doi(comp),
                "pmid": comp.get("pmid", ""),
                "pmcid": comp.get("pmcid", ""),
                "journal": comp.get("journal", ""),
                "publication_year": get_year(comp),
            }
        }
        if proj:
            sources["compendium_projects"] = {"doi": norm_doi(proj.get("link", ""))}
        sources["id_map"] = {"doi": norm_doi(imap.get("doi", "")), "title": imap.get("title", "")}
        scraped = scrape_paper_text(acc)
        if scraped["doi"] or scraped["pmcid"]:
            sources["paper_text"] = {
                "doi": clean_scraped_doi(norm_doi(scraped["doi"])),
                "pmcid": scraped["pmcid"],
            }

        field_map = {"publication_year": b, **{f: b for f in ("title", "doi", "pmid", "pmcid", "journal")}}

        # ---- B_publication_metadata fill ----
        b_changed = False
        for fld in B_FIELDS:
            if not is_empty(b.get(fld)):
                continue
            for src_name, src in sources.items():
                val = (src.get(fld) or "").strip()
                if fld == "publication_year":
                    val = val[:4] if (len(val) >= 4 and val[:4].isdigit()) else ""
                if not val:
                    continue
                b[fld] = val
                b_changed = True
                b_fill[fld] += 1
                changes.append({"corpus_id": cid, "accession": acc, "field": fld,
                                "target": "record", "source": src_name, "old": "", "new": val})
                break

        if b_changed:
            rec["B_publication_metadata"] = b
            record_updates[cid] = rec

        # ---- corpus_tracking.csv fill ----
        trow = tracking_by_id.get(cid)
        if trow is None:
            continue
        tr_changed = False
        for fld, tfld in (("title", "title"), ("doi", "doi"), ("pmid", "pmid"),
                          ("pmcid", "pmcid"), ("publication_year", "year"), ("journal", "journal")):
            if not is_empty(trow.get(tfld)):
                continue
            # canonical value from the (possibly just-updated) record, else sources
            val = ""
            if fld in b and not is_empty(b.get(fld)):
                val = str(b[fld]).strip()
            else:
                for src_name, src in sources.items():
                    sv = (src.get(fld) or "").strip()
                    if fld == "publication_year":
                        sv = sv[:4] if (len(sv) >= 4 and sv[:4].isdigit()) else ""
                    if sv:
                        val = sv
                        break
            if val:
                old = trow.get(tfld, "")
                trow[tfld] = val
                tr_changed = True
                tr_fill[tfld] += 1
                changes.append({"corpus_id": cid, "accession": acc, "field": tfld,
                                "target": "tracking", "source": "offline", "old": old, "new": val})
        _ = tr_changed  # rows list is mutated in place; nothing to store

    # ---- report ----
    print(f"records changed: {len(record_updates)}/453")
    print(f"tracking rows changed: {sum(1 for c in changes if c['target'] == 'tracking')}/453")
    print("record B_publication_metadata fills:", dict(b_fill))
    print("tracking fills:", dict(tr_fill))
    if any(c.get("target") == "_record" or c.get("field") == "_record" for c in changes):
        pass

    if args.dry_run:
        print("\n[DRY RUN] no files written")
        for c in changes[:20]:
            print("  ", c)
        if len(changes) > 20:
            print(f"  ... and {len(changes) - 20} more")
        return 0

    if not changes:
        print("no changes needed; already up to date")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TRACKING_CSV, BACKUP_DIR / f"corpus_tracking.backup-{ts}.csv")
    (BACKUP_DIR / f"backfill_changelog-{ts}.json").write_text(json.dumps(changes, indent=2))

    if record_updates:
        for cid, rec in record_updates.items():
            (RECORDS_DIR / f"{cid}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))

    with TRACKING_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=tracking_fields)
        w.writeheader()
        w.writerows(tracking_rows)

    print(f"\nwrote {len(changes)} fills; backup + changelog in {BACKUP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
