#!/usr/bin/env python3
"""Fetch full text for BioProject-linked papers via Europe PMC (no API key needed).

Targets:
- The 39 BioProjects from data/168000-samples-paper/projects.csv with no paper in data/papers_txt/
- Broken files in data/papers_txt/ (wrong paper, abstract-only, or corrupt extraction):
  PRJEB32077 PRJEB38948 PRJNA517509 PRJNA715036 PRJEB43667 PRJEB27807
  PRJDB6499 PRJNA389431 PRJNA491657 PRJNA644520

DOIs come from projects.csv 'link' column (38 of the 39 missing have links after
resolving via NCBI BioProject->publication links). Output: data/papers_txt/<ACC>.txt
(pure text, dehyphenated, section headers on their own lines). Records that have
no retrievable full text get a one-line "FULLTEXT_UNAVAILABLE" marker file so the
corpus builder skips them and the roster reflects reality.

API notes: Europe PMC search by DOI -> fullTextXML (OA only). Rate: sleep 0.35s.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UA = {"User-Agent": "MicrobiomeCDM-corpus/1.0 (academic research)"}
SLEEP = 0.35

BROKEN = [
    "PRJEB32077",
    "PRJEB38948",
    "PRJNA517509",
    "PRJNA715036",
    "PRJEB43667",
    "PRJEB27807",
    "PRJDB6499",
    "PRJNA389431",
    "PRJNA491657",
    "PRJNA644520",
]


def http_get(url: str, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def epmc_by_doi(doi: str) -> dict | None:
    q = urllib.parse.quote(f'DOI:"{doi}"')
    d = json.loads(http_get(f"{EPMC}/search?query={q}&resultType=core&format=json"))
    results = d.get("resultList", {}).get("result", [])
    return results[0] if results else None


def strip_tags(xml: str) -> str:
    xml = re.sub(r"<xref[^>]*>.*?</xref>", " ", xml, flags=re.S)
    xml = re.sub(r"</?(ext-link|uri)[^>]*>.*?</\1>", " ", xml, flags=re.S)
    xml = re.sub(r"<sub[^>]*>", "", xml)
    xml = re.sub(r"</sub>", "", xml)
    xml = re.sub(r"<sup[^>]*>.*?</sup>", "", xml, flags=re.S)
    for blk in [
        "abstract", "body", "sec", "title", "p", "caption", "front", "article-title",
        "journal-title", "contrib-group", "aff", "kwd-group", "abstract", "notes",
    ]:
        xml = re.sub(rf"</{blk}>", "\n", xml)
    xml = re.sub(r"<title[^>]*>", "\n\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    xml = xml.replace("&#x2009;", " ").replace("&#x2013;", "-").replace("&#x2014;", "--")
    xml = re.sub(r"&#x[0-9a-fA-F]+;", " ", xml)
    xml = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))) if int(m.group(1)) < 0x3000 else " ", xml)
    xml = re.sub(r"&[a-z]+;", " ", xml)
    xml = re.sub(r"[ \t]+", " ", xml)
    xml = re.sub(r" ?\n ?", "\n", xml)
    xml = re.sub(r"\n{3,}", "\n\n", xml)
    xml = re.sub(r"(\w)-\n(\w)", r"\1\2", xml)  # dehyphenate
    xml = re.sub(r"\n(?=[a-z])", " ", xml)
    return xml.strip()


def fetch_fulltext_path(rec: dict) -> tuple[str | None, str]:
    """Return (fulltext_xml_or_none, status)."""
    pmcid = rec.get("pmcid")
    if not pmcid:
        return None, "no_pmcid"
    try:
        x = http_get(f"{EPMC}/{pmcid}/fullTextXML").decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        if "404" in str(e):
            return None, "no_oa_fulltext"
        return None, f"error:{e}"
    if "<article" not in x:
        return None, "no_article_xml"
    return x, "ok"


def main() -> None:
    root = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
    proj_csv = root / "data" / "168000-samples-paper" / "projects.csv"
    papers = root / "data" / "papers_txt"
    rows = list(csv.DictReader(open(proj_csv, encoding="utf-8-sig")))
    meta = {r["project"]: r for r in rows}

    # Build target list: missing accs + known-broken files
    missing = [p for p in meta if not (papers / f"{p}.txt").exists()]
    targets = missing + [a for a in BROKEN if a in meta and (papers / f"{a}.txt").exists()]
    # resolve PRJNA644520's project link (it was a redirect page)
    print(f"targets: {len(targets)} ({len(missing)} missing + {len(BROKEN)} broken)")

    report = []
    for i, acc in enumerate(targets, 1):
        doi = meta[acc]["link"].replace("https://doi.org/", "").strip()
        if not doi:
            report.append({"acc": acc, "doi": "", "status": "no_doi_in_csv"})
            print(f"[{i}/{len(targets)}] {acc}: NO DOI -> skipping")
            continue
        rec = epmc_by_doi(doi)
        time.sleep(SLEEP)
        if not rec:
            report.append({"acc": acc, "doi": doi, "status": "doi_not_in_epmc"})
            print(f"[{i}/{len(targets)}] {acc}: DOI not in EPMC")
            continue
        dx, status = fetch_fulltext_path(rec)
        time.sleep(SLEEP)
        title = (rec.get("title") or "")[:70]
        if dx:
            text = strip_tags(dx)
            out = papers / f"{acc}.txt"
            out.write_text(f"{title}\n\n{text}\n", encoding="utf-8")
            report.append({"acc": acc, "doi": doi, "pmcid": rec.get("pmcid"), "status": status, "bytes": len(text), "title": title})
            print(f"[{i}/{len(targets)}] {acc}: fetched {len(text)} chars ({status}) - {title}")
        else:
            report.append({"acc": acc, "doi": doi, "pmcid": rec.get("pmcid"), "status": status, "title": title})
            print(f"[{i}/{len(targets)}] {acc}: {status} - {title}")

    Path("/tmp/opencode/fulltext_audit/fetch_report.json").write_text(json.dumps(report, indent=1))
    ok = [r for r in report if r["status"] == "ok"]
    print(f"\ndone: {len(ok)}/{len(report)} full texts fetched")
    for r in report:
        if r["status"] != "ok":
            print(f"  UNRESOLVED {r['acc']}: {r['status']}")


if __name__ == "__main__":
    sys.exit(main())
