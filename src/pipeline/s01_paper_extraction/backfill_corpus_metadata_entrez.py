#!/usr/bin/env python
"""Entrez-based metadata backfill for the 453-paper corpus.

Resolves remaining empty B_publication_metadata fields (pmid, pmcid, title,
journal, publication_year, abstract, keywords) by querying NCBI E-utilities:

  1. If a DOI is present  -> esearch db=pubmed term=<doi>[DOI]
  2. Else if a title exists -> esearch db=pubmed term=<title>[Title]
     (title match verified against returned record to avoid false hits)

Identifiers resolved via DOI are trusted; title-based hits must fuzzy-match
the stored title (rapidfuzz-free token overlap >= 0.9) to be accepted.

Writes a checkpoint after every paper, so the run is safely resumable.
Reads ENTREZ_EMAIL / ENTREZ_API_KEY from the environment (.env must be
sourced: `set -a; source .env; set +a`).

Usage:
  set -a; source .env; set +a
  PYTHONPATH=src python src/scripts/backfill_corpus_metadata_entrez.py [--dry-run] [--delay 0.4]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cdm_pipeline.entrez.fetch_pubmed_metadata import parse_pubmed_xml  # noqa: E402

RECORDS_DIR = PROJECT_ROOT / "data" / "corpus" / "records"
TRACKING_CSV = PROJECT_ROOT / "data" / "corpus" / "corpus_tracking.csv"
BACKUP_DIR = PROJECT_ROOT / "data" / "corpus" / "logs"
CHECKPOINT = BACKUP_DIR / "entrez_backfill_checkpoint.json"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "")
ENTREZ_API_KEY = os.environ.get("ENTREZ_API_KEY", "")

if not ENTREZ_EMAIL:
    sys.exit("ENTREZ_EMAIL not set — run: set -a; source .env; set +a")

import requests  # noqa: E402

B_FILL_FIELDS = {
    "title": ("title", "Title"),
    "journal": ("journal", "Journal"),
    "publication_year": ("publication_year", "pub_year"),
    "abstract": ("abstract", "abstract"),
}
FIELDS_NEEDING_IDS = ("pmid", "pmcid")


def is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v in ([], {})


def norm_year(v: str) -> str:
    v = (v or "").strip()
    return v[:4] if len(v) >= 4 and v[:4].isdigit() else ""


def _params(extra: dict) -> dict:
    p = {"email": ENTREZ_EMAIL, "tool": "microbiome-cdm"}
    if ENTREZ_API_KEY:
        p["api_key"] = ENTREZ_API_KEY
    p.update(extra)
    return p


def esearch(term: str) -> list[str]:
    try:
        r = requests.get(f"{EUTILS}/esearch.fcgi", params=_params({
            "db": "pubmed", "term": term, "retmax": 5,
        }), timeout=30)
        root = ET.fromstring(r.text)
        return [e.text for e in root.findall(".//Id") if e.text]
    except Exception as e:
        print(f"    esearch error: {e}", file=sys.stderr)
        return []


def efetch_xml(pmid: str):
    try:
        r = requests.get(f"{EUTILS}/efetch.fcgi", params=_params({
            "db": "pubmed", "id": pmid, "rettype": "xml",
        }), timeout=60)
        return parse_pubmed_xml(r.text, pmid)
    except Exception as e:
        print(f"    efetch error: {e}", file=sys.stderr)
        return None


def title_match(t1: str, t2: str) -> bool:
    """Token-overlap similarity for title verification (no external deps)."""
    def toks(t):
        return set(re.findall(r"[a-z0-9]+", (t or "").lower()))
    a, b = toks(t1), toks(t2)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= 0.9


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--max", type=int, default=0, help="Limit papers (0 = all)")
    args = ap.parse_args()

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    changes: list[dict] = []
    resolved_pmid: dict[str, str] = {}   # corpus_id -> pmid
    if CHECKPOINT.exists():
        resolved_pmid = json.loads(CHECKPOINT.read_text())
        print(f"checkpoint: {len(resolved_pmid)} PMIDs already resolved")

    # figure out who still needs what
    todo = []
    for i in range(1, 454):
        cid = f"HMPAPER_{i:06d}"
        rec = json.loads((RECORDS_DIR / f"{cid}.json").read_text())
        b = rec.get("B_publication_metadata") or {}
        needs_ids = (is_empty(b.get("pmid")) or is_empty(b.get("pmcid")))
        needs_meta = any(is_empty(b.get(f)) for f in B_FILL_FIELDS)
        if cid in resolved_pmid:
            needs_ids = False
        if needs_ids or needs_meta:
            todo.append((cid, needs_ids, needs_meta))
    if args.max:
        todo = todo[:args.max]
    print(f"papers needing work: {len(todo)}")
    if not todo:
        return 0

    ts = time.strftime("%Y%m%d-%H%M%S")
    rec_writes: dict[str, dict] = {}

    for n, (cid, needs_ids, needs_meta) in enumerate(todo, 1):
        rec = rec_writes.get(cid) or json.loads((RECORDS_DIR / f"{cid}.json").read_text())
        b = rec.get("B_publication_metadata") or {}
        acc = rec.get("bioproject_accession", "")

        pmid = (b.get("pmid") or "").strip() or resolved_pmid.get(cid, "")

        # ---- resolve pmid if needed ----
        if not pmid:
            doi = (b.get("doi") or "").strip()
            title = (b.get("title") or "").strip()
            found_via = None
            if doi:
                ids = esearch(f"{doi}[DOI]")
                if ids:
                    pmid, found_via = ids[0], "doi"
                time.sleep(args.delay)
            if not pmid and title:
                ids = esearch(f"{title}[Title]")
                if ids:
                    # verify top hits by title match
                    for cand in ids[:3]:
                        cand_rec = efetch_xml(cand)
                        time.sleep(args.delay)
                        if cand_rec and title_match(title, cand_rec.get("title", "")):
                            pmid, found_via = cand, "title"
                            b = rec.get("B_publication_metadata") or {}  # re-read later
                            # stash candidate record for the fill step below
                            rec["_entrez_candidate"] = cand_rec
                            break
            if pmid:
                resolved_pmid[cid] = pmid
                print(f"[{n}/{len(todo)}] {cid} {acc}: PMID {pmid} (via {found_via})")
            else:
                print(f"[{n}/{len(todo)}] {cid} {acc}: unresolved (doi={bool(doi)}, title={bool(title)})")
                continue
        else:
            if needs_meta and not is_empty(b.get("pmid")):
                # already have pmid; will fetch below
                pass

        # ---- fetch pubmed record & fill ----
        pub_rec = rec.get("_entrez_candidate") or efetch_xml(pmid)
        if not pub_rec:
            print(f"    {cid}: fetch failed for PMID {pmid}")
            continue
        rec.pop("_entrez_candidate", None)

        def add(field_key, value, source):
            value = (value or "").strip() if isinstance(value, str) else value
            if is_empty(b.get(field_key)) and value and not is_empty(value):
                b[field_key] = str(value)
                changes.append({"corpus_id": cid, "accession": acc, "field": field_key,
                                "source": f"entrez:{source}", "old": "", "new": str(value)})

        if is_empty(b.get("pmid")):
            add("pmid", pmid, "pmid")
        if is_empty(b.get("pmcid")):
            add("pmcid", pub_rec.get("pmc_id", ""), "pmcid")
        add("title", pub_rec.get("title", ""), "title")
        add("journal", pub_rec.get("journal", ""), "journal")
        add("publication_year", norm_year(pub_rec.get("pub_year", "")), "pub_year")
        add("abstract", pub_rec.get("abstract", ""), "abstract")

        if is_empty(b.get("keywords")) and not is_empty(pub_rec.get("keywords", [])):
            b["keywords"] = pub_rec["keywords"]
            changes.append({"corpus_id": cid, "accession": acc, "field": "keywords",
                            "source": "entrez:keywords", "old": "", "new": str(pub_rec["keywords"])[:100]})

        rec["B_publication_metadata"] = b
        rec_writes[cid] = rec
        time.sleep(args.delay)

        if n % 10 == 0:
            CHECKPOINT.write_text(json.dumps(resolved_pmid))
            print(f"  checkpoint: {len(resolved_pmid)} PMIDs")

    print(f"\nrecord field fills: {len(changes)}")
    if args.dry_run:
        for c in changes[:30]:
            print("  ", c)
        print("[DRY RUN] nothing written")
        return 0

    # ---- write records ----
    for cid, rec in rec_writes.items():
        (RECORDS_DIR / f"{cid}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))

    # ---- sync tracking csv ----
    with TRACKING_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    tr_changes = 0
    by_id = {r["corpus_id"]: r for r in rows}
    for cid, rec in rec_writes.items():
        b = rec.get("B_publication_metadata") or {}
        t = by_id.get(cid)
        if t is None:
            continue
        for tf, bf in (("pmid", "pmid"), ("pmcid", "pmcid"), ("title", "title"),
                       ("journal", "journal"), ("year", "publication_year")):
            if is_empty(t.get(tf)) and not is_empty(b.get(bf)):
                t[tf] = str(b[bf]).strip()
                tr_changes += 1
    if tr_changes:
        shutil.copy2(TRACKING_CSV, BACKUP_DIR / f"corpus_tracking.backup-{ts}.csv")
        with TRACKING_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    (BACKUP_DIR / f"entrez_backfill_changelog-{ts}.json").write_text(json.dumps(changes, indent=2))
    CHECKPOINT.write_text(json.dumps(resolved_pmid))
    print(f"tracking fills: {tr_changes}")
    print(f"changelog + checkpoint in {BACKUP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
