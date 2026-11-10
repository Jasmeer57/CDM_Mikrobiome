#!/usr/bin/env python3
"""Full-sweep full-text fetcher: check EVERY corpus paper and grab whatever
original-format full text is legally available (PDF preferred, JATS XML second).

Per-paper resolution order:
  0. Skip if pdfs/<ACC>.pdf or fulltext/<ACC>.jats.xml already on disk.
  1. Resolve DOI from projects.csv (bare DOI extracted from 'link' column);
     fallback: Europe PMC reverse lookup by BioProject accession.
  2. Unpaywall v2 -> oa_locations:
       - try each url_for_pdf: plain requests first, then headless Chromium
         (some CDNs only serve to browsers);
       - remember landing URLs for repositories we can API instead.
  3. Europe PMC REST fullTextXML (works for inEPMC OA subset even when PDF is
     WAF-blocked).
  4. Record per-paper status in pdfs/fulltext_fetch_sweep.json. Never a silent
     miss: every accession gets a status line.

Outputs: pdfs/<ACC>.pdf, fulltext/<ACC>.jats.xml, pdfs/fulltext_fetch_sweep.json
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
PDF_DIR = ROOT / "pdfs"
XML_DIR = ROOT / "data" / "fulltext"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UNPAYWALL = "https://api.unpaywall.org/v2"
EMAIL = "jkalra@uni-potsdam.de"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
REQ = requests.Session()
REQ.headers.update({"User-Agent": UA, "Accept": "application/pdf,text/xml,*/*"})


def log(*a):
    print(*a, flush=True)


def csv_dois() -> dict:
    out = {}
    p = ROOT / "data/168000-samples-paper" / "projects.csv"
    with open(p, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            m = re.search(r"(10\.\d{4,9}/[^\s\"']+)", (row.get("link") or "").strip())
            if m:
                out[row["project"].strip()] = m.group(1).rstrip(".,);")
    return out


def doi_from_bioproject(acc: str) -> str | None:
    """Reverse lookup: search EPMC for papers whose full text mentions this BioProject."""
    try:
        r = REQ.get(
            EPMC + "/search",
            params={"query": f'"{acc}"', "format": "json", "pageSize": 5},
            timeout=30,
        )
        for hit in r.json().get("resultList", {}).get("result", []):
            doi = (hit.get("doi") or "").strip()
            if doi.startswith("10."):
                return doi
    except Exception:
        pass
    return None


def is_pdf(data: bytes) -> bool:
    return data[:4] == b"%PDF" and len(data) > 10000


def try_pdf_requests(url: str) -> bytes | None:
    try:
        r = REQ.get(url, timeout=90)
        if r.status_code == 200 and is_pdf(r.content):
            return r.content
    except Exception:
        pass
    return None


class Browser:
    """Lazy headless-Chromium helper; created once per sweep."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None

    def _ensure(self):
        if self._page is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._ctx = self._browser.new_context(user_agent=UA, accept_downloads=True)
            self._page = self._ctx.new_page()
        return self._page

    def try_pdf(self, url: str) -> bytes | None:
        page = self._ensure()
        # case 1: server sends Content-Disposition -> download event
        try:
            with page.expect_download(timeout=45000) as dl:
                try:
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                except Exception:
                    pass  # "Download is starting" raises - the download event still fires
            d = dl.value
            path = d.path()
            data = Path(path).read_bytes()
            if data[:4] == b"%PDF" and len(data) > 10000:
                return data
        except Exception:
            pass
        # case 2: inline PDF navigation (Chromium PDF viewer) -> fetch bytes via CDP-free route:
        # response body of the main document
        try:
            resp = page.request.get(url, timeout=90000)
            body = resp.body()
            if body[:4] == b"%PDF" and len(body) > 10000:
                return body
        except Exception:
            pass
        return None

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def epmc_xml_for_pmcid(pmcid: str) -> bytes | None:
    try:
        r = REQ.get(f"{EPMC}/{pmcid}/fullTextXML", timeout=90)
        if r.status_code == 200 and b"<article" in r.content[:8000]:
            return r.content
    except Exception:
        pass
    return None


def unpaywall(doi: str) -> dict | None:
    try:
        r = REQ.get(f"{UNPAYWALL}/{urllib.parse.quote(doi)}", params={"email": EMAIL}, timeout=30)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def epmc_pmcid(doi: str) -> tuple[str | None, dict | None]:
    try:
        r = REQ.get(
            EPMC + "/search",
            params={"query": f'DOI:"{doi}"', "format": "json", "resultType": "core"},
            timeout=30,
        )
        hits = r.json().get("resultList", {}).get("result", [])
        if not hits:
            return None, None
        return hits[0].get("pmcid"), hits[0]
    except Exception:
        return None, None


def fetch_one(acc: str, doi: str, browser: Browser) -> dict:
    status = {"accession": acc, "doi": doi, "got": None, "source": None}

    # --- Unpaywall PDFs (publisher or repository direct) ---
    up = unpaywall(doi) if doi else None
    if up and up.get("is_oa"):
        for loc in up.get("oa_locations") or []:
            pdf_url = loc.get("url_for_pdf")
            if not pdf_url:
                continue
            data = try_pdf_requests(pdf_url)
            src = f"unpaywall:{loc.get('host_type')}"
            if data is None:
                data = browser.try_pdf(pdf_url)
            if data:
                (PDF_DIR / f"{acc}.pdf").write_bytes(data)
                status.update(got="pdf", source=src, pdf_url=pdf_url)
                return status
            time.sleep(0.3)

    # --- Europe PMC XML (full text JATS; covers many PDF-less OA records) ---
    pmcid, rec = epmc_pmcid(doi) if doi else (None, None)
    if pmcid:
        xml = epmc_xml_for_pmcid(pmcid)
        if xml:
            (XML_DIR / f"{acc}.jats.xml").write_bytes(xml)
            status.update(got="xml", source="europepmc:fullTextXML", pmcid=pmcid)
            return status

    # --- Europe PMC PDF via EPMC article URL trick? (render is WAF'd; skip) ---
    status.update(got=None, source=None, pmcid=pmcid,
                  note="no legal OA location reachable from this host")
    return status


def main() -> None:
    PDF_DIR.mkdir(exist_ok=True)
    XML_DIR.mkdir(exist_ok=True)
    dois = csv_dois()
    accs = sorted(f[:-4] for f in os.listdir(ROOT / "data/papers_txt") if f.endswith(".txt"))

    # resume: load prior sweep results
    sweep_path = PDF_DIR / "fulltext_fetch_sweep.json"
    prior = json.loads(sweep_path.read_text()) if sweep_path.is_file() else {}

    todo = [a for a in accs
            if not prior.get(a, {}).get("got")
            and not (PDF_DIR / f"{a}.pdf").is_file()]
    for a in accs:
        if (PDF_DIR / f"{a}.pdf").is_file() and not prior.get(a, {}).get("got"):
            prior[a] = {"accession": a, "got": "pdf", "source": "preexisting"}
    sweep_path.write_text(json.dumps(prior, indent=1))
    log(f"{len(accs)} papers: {len(accs) - len(todo)} already covered, {len(todo)} to fetch")

    n_workers = 8
    queue = list(todo)
    lock = __import__("threading").Lock()

    def worker(browser: Browser, results: dict):
        while True:
            with lock:
                if not queue:
                    return
                acc = queue.pop(0)
            doi = dois.get(acc) or doi_from_bioproject(acc)
            try:
                res = fetch_one(acc, doi, browser)
            except Exception as e:  # noqa: BLE001
                res = {"accession": acc, "doi": doi, "got": None, "note": f"error:{type(e).__name__}"}
            with lock:
                prior[acc] = res
                results[acc] = res
                sweep_path.write_text(json.dumps(prior, indent=1))
                got = res.get("got") or "NONE"
                log(f"[{len(results)}/{len(todo)}] {acc}: {got:>4}  ({res.get('source') or res.get('note') or ''})")

    import threading
    threads = []
    for _ in range(n_workers):
        b = Browser()
        t = threading.Thread(target=worker, args=(b, {}), daemon=True)
        t.start()
        threads.append((t, b))
        time.sleep(2)  # stagger browser launches
    for t, _ in threads:
        t.join()
    for _, b in threads:
        b.close()

    n_pdf = sum(1 for v in prior.values() if v.get("got") == "pdf")
    n_xml = sum(1 for v in prior.values() if v.get("got") == "xml")
    n_none = sum(1 for v in prior.values() if not v.get("got"))
    log(f"\nSWEEP DONE over {len(accs)} papers -> {n_pdf} PDF, {n_xml} XML, {n_none} no OA full text")
    log(f"results: {sweep_path}")


if __name__ == "__main__":
    main()
