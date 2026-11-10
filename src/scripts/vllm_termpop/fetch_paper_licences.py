"""Per-paper licence for the 453-paper corpus from Europe PMC (Phase D1 of
docs/catalogue_cleanup_plan.md).

The catalogue quotes an evidence sentence from every paper. Whether that quote
may be redistributed depends on the paper's licence, which `papers.csv` does
not record (`license_name` is empty). This looks each paper up in Europe PMC by
PMCID, then PMID, then DOI, and records the licence and open-access flag.

Network step; run on a login node. Results are cached, so a re-run only
queries papers that are still missing.

Usage:
    python src/scripts/vllm_termpop/fetch_paper_licences.py \
        [--papers_csv releases/data_catalogue/tables/papers.csv] \
        [--out outputs/results/catalogue_v3_licences/paper_licences.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
COLUMNS = ["paper_id", "doi", "pmid", "pmcid", "license", "license_url", "is_open_access",
           "in_pmc", "matched_by", "quote_policy"]
CC_PREFIX = "cc"


def _cc_terms(lic):
    """"cc by-nc-nd" -> ["by", "nc", "nd"]; "cc0" -> ["0"]; non-CC -> None."""
    lic = (lic or "").strip().lower()
    if not lic.startswith(CC_PREFIX):
        return None
    return [t for t in re.split(r"[\s-]+", lic[len(CC_PREFIX):]) if t]


def quote_policy(lic):
    """May the evidence quote ship in the public release?"""
    terms = _cc_terms(lic)
    if terms is None:
        return "REDACT"          # unknown or publisher licence: location only
    if "nd" in terms:
        return "REDACT"          # no-derivatives: do not excerpt into a new work
    return "KEEP_NC" if "nc" in terms else "KEEP"


def license_url(lic):
    """Licence family page. Europe PMC gives no version, so none is invented."""
    terms = _cc_terms(lic)
    if not terms:
        return ""
    if terms == ["0"]:
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return "https://creativecommons.org/licenses/%s/" % "-".join(terms)


def query(q):
    url = EPMC + "?" + urllib.parse.urlencode({"query": q, "resultType": "core",
                                               "format": "json", "pageSize": 1})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                res = json.loads(resp.read())["resultList"]["result"]
                return res[0] if res else {}
        except Exception:  # noqa: BLE001 — retry, then give up on this paper
            time.sleep(2 ** attempt)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Per-paper licences from Europe PMC")
    ap.add_argument("--papers_csv", default=str(REPO_ROOT / "releases/data_catalogue/tables/papers.csv"))
    ap.add_argument("--out", default=str(REPO_ROOT / "outputs/results/catalogue_v3_licences/paper_licences.csv"))
    ap.add_argument("--expected_papers", type=int, default=453)
    args = ap.parse_args(argv)

    with open(args.papers_csv, newline="", encoding="utf-8") as fh:
        papers = list(csv.DictReader(fh))
    if len(papers) != args.expected_papers:
        sys.exit(f"papers.csv has {len(papers)} papers, expected {args.expected_papers}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if out.exists():
        with open(out, newline="", encoding="utf-8") as fh:
            done = {r["paper_id"]: r for r in csv.DictReader(fh) if r["matched_by"] != "LOOKUP_FAILED"}

    rows = []
    for i, p in enumerate(papers):
        if p["paper_id"] in done:  # cached lookup; derived columns recomputed
            r = done[p["paper_id"]]
            r.update(license_url=license_url(r["license"]), quote_policy=quote_policy(r["license"]))
            rows.append(r)
            continue
        hit, how = {}, "NOT_IN_EUROPE_PMC"
        for key, q in (("pmcid", f'PMCID:{p["pmcid"]}'), ("pmid", f'EXT_ID:{p["pmid"]} AND SRC:MED'),
                       ("doi", f'DOI:"{p["doi"]}"')):
            if not p.get(key, "").strip():
                continue
            res = query(q)
            if res is None:
                how = "LOOKUP_FAILED"
                break
            if res:
                hit, how = res, key
                break
            time.sleep(0.1)
        lic = (hit.get("license") or "").strip().lower()
        rows.append({"paper_id": p["paper_id"], "doi": p["doi"], "pmid": p["pmid"],
                     "pmcid": hit.get("pmcid") or p["pmcid"], "license": lic,
                     "license_url": license_url(lic),
                     "is_open_access": hit.get("isOpenAccess", ""), "in_pmc": hit.get("inPMC", ""),
                     "matched_by": how, "quote_policy": quote_policy(lic)})
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(papers)}", flush=True)
        time.sleep(0.1)

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    summary = {"papers": len(rows),
               "matched_by": dict(Counter(r["matched_by"] for r in rows)),
               "license": dict(Counter(r["license"] or "(none)" for r in rows).most_common()),
               "quote_policy": dict(Counter(r["quote_policy"] for r in rows))}
    out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 1 if summary["matched_by"].get("LOOKUP_FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
