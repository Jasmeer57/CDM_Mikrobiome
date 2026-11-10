#!/usr/bin/env python3
"""Network verification of catalogue BioProject accessions against primary registries.

Kept deliberately separate from build_data_catalogue.py (deterministic construction)
because network verification has different failure modes. Per the review:
- retries, rate limits, timeouts, redirect handling
- machine-readable JSON output
- a confirmed-missing accession (registry definitively says no) is different
  from a timeout/5xx/rate-limit (transient — re-run must resolve these)
- HTTP 200 alone does not prove the accession belongs to the paper; metadata
  identity is checked by comparing registry project metadata against the paper
- verification never edits the catalogue in place: results go to
  repository_verification.json, and only a later, explicit reconcile step
  (or human decision) updates catalogue fields

Registries:
- PRJNA*    NCBI BioProject  (eutils esearch/esummary, api.ncbi.nlm.nih.gov)
- PRJEB*    ENA BioProject   (www.ebi.ac.uk/ena/browser/api/xml)
- PRJDB*    DDBJ BioProject  (ddbj.nig.ac.jp search API)
- others    UNVERIFIED_UNSUPPORTED_REGISTRY (no invention, recorded as-is)

Statuses (terminal taxonomy):
  OK_VERIFIED          registry record found + metadata identity check passed
  OK_REVIEW            registry record found; weak/no metadata match — queued for
                       human review (NOT auto-promoted to verified)
  CONFIRMED_MISSING    registry authoritatively says the accession doesn't exist
  TRANSIENT            timeout / connection error / 5xx / rate-limit — MUST be
                       re-run; release gate blocks on any TRANSIENT
  CONFLICTING          registry record found but its publication identifiers
                       reference a different paper (hard disagreement)
  UNVERIFIED_UNSUPPORTED_REGISTRY  accession prefix without a registry client

Usage (login node ok; ~453 accessions at polite rate limits ≈ 20–40 min):
  python corpus_builder/verify_repository_accessions.py
  python corpus_builder/verify_repository_accessions.py --only HMPAPER_000001,HMPAPER_000009
  python corpus_builder/verify_repository_accessions.py --status TRANSIENT   # re-run leftovers
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from defusedxml import ElementTree as DET
    XML_LIB = "defusedxml"
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as DET
    XML_LIB = "stdlib"

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

CATALOGUE = REPO / "outputs/results/human_microbiome_data_catalogue/human_microbiome_data_catalogue.json"
OUT = REPO / "outputs/results/human_microbiome_data_catalogue/repository_verification.json"

VERSION = "1.0.0"
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
TRANSIENT_STATUSES = {"TRANSIENT"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("verify_repo")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------ HTTP plumbing


class FetchError(Exception):
    def __init__(self, kind, detail, http_status=None):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind  # "transient" | "missing" | "error"


def fetch(url, timeout=30, retries=3, backoff=5.0, extra_headers=None):
    """GET with redirects honored by default; classify failures:
    404 -> missing; 429/5xx/connection+timeout -> transient (retried)."""
    headers = {"User-Agent": "hmp-data-catalogue-verifier/1.0 (research; contact via repo)"}
    if extra_headers:
        headers.update(extra_headers)
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), resp.geturl()
        except HTTPError as e:
            if e.code == 404:
                raise FetchError("missing", f"HTTP 404 for {url}", http_status=404) from None
            if e.code in RETRYABLE_HTTP:
                last = FetchError("transient", f"HTTP {e.code} attempt {attempt}", http_status=e.code)
            else:
                raise FetchError("error", f"HTTP {e.code} for {url}", http_status=e.code) from None
        except (URLError, TimeoutError, OSError) as e:
            last = FetchError("transient", f"connection: {e} attempt {attempt}")
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise last or FetchError("error", "exhausted retries without a concrete error")


def fetch_json(url, **kw):
    status, body, _ = fetch(url, **kw)
    return json.loads(body.decode("utf-8", errors="replace"))


def fetch_xml(url, **kw):
    status, body, _ = fetch(url, **kw)
    return DET.fromstring(body)


# ------------------------------------------------------------- registry APIs


def norm_title(s):
    import re
    s = re.sub(r"\s+", " ", str(s or "")).strip().lower()
    # strip HTML/XML encodes that registries sprinkle in
    for pat in (r"&#\d+;", r"&[a-z]+;", r"\u2002", r"\u2013", r"\u2014"):
        s = re.sub(pat, " ", s)
    return s


def title_tokens(s):
    import re
    stop = {"the", "a", "an", "of", "in", "and", "for", "with", "study", "human",
            "microbiome", "microbiota"}
    return set(re.findall(r"[a-z0-9]+", norm_title(s))) - stop


def identity_score(paper_title, reg_title, paper_doi, reg_dois):
    """Title-token Jaccard (microbiome stop-stripped) + DOI exact-hit.
    Returns (score, basis). A DOI match alone is decisive."""

    def jac(a, b):
        if not a or not b:
            return 0.0
        inter = len(a & b) / len(a | b)
        # microbiome-domain relaxation: subset overlap counts partially
        subset_bonus = (len(a & b) / len(a)) * 0.35 if a and a <= b else 0
        return round(min(inter + subset_bonus, 1.0), 3)

    ta, tb = title_tokens(paper_title), title_tokens(reg_title)
    scores = {"title_jaccard": jac(ta, tb)}
    if paper_doi:
        reg_doi_norm = {norm_title(d).replace("https://doi.org/", "").replace("doi:", "")
                        for d in (reg_dois or [])}
        want = norm_title(paper_doi).replace("https://doi.org/", "").replace("doi:", "")
        scores["doi_exact"] = 1.0 if want in reg_doi_norm else 0.0
        if scores["doi_exact"] == 1.0:
            return 1.0, scores
    return scores["title_jaccard"], scores


def verify_ncbi(acc, paper_title, paper_doi):
    """PRJNA*/PRJDB* (and any other INSDC accession NCBI mirrors) via eutils:
    esearch BioProject DB -> esummary. NCBI indexes all INSDC BioProjects,
    including DDBJ submissions (PRJDB*), whose own JSON API 403s.

    Gotcha: a bare accession as the esearch term is interpreted as FUZZY
    text search and can return unrelated projects whose text merely contains
    the accession-like token. We therefore (1) use the fielded exact form
    `PRJNA601994[bioproject]`, and (2) verify the returned summary's
    project_acc actually equals the requested accession."""
    search = fetch_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urlencode(
        {"db": "bioproject", "term": f"{acc}[bioproject]", "retmode": "json"}))
    ids = (search.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return {"found": False, "confirmed_missing": True,
                "detail": "NCBI esearch returned 0 BioProject ids for accession"}
    summ = fetch_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urlencode(
        {"db": "bioproject", "id": ",".join(ids), "retmode": "json"}))
    # pick the summary whose project_acc equals the requested accession
    node = None
    uid = None
    for i in ids:  # ids order is relevance, not accession
        n = summ.get("result", {}).get(i) or {}
        if (n.get("project_acc") or "").upper() == acc.upper():
            node, uid = n, i
            break
    if node is None:
        return {"found": False, "confirmed_missing": True,
                "detail": "esearch hits existed but none carried the exact accession"}
    reg_title = node.get("project_title") or node.get("projectname") or node.get("project_name")
    # DOIs can appear anywhere in the summary blob; extract conservatively
    reg_dois = re.findall(r"10\.\d{4,9}/[^\s\"',]+", json.dumps(node))
    return {"found": True, "reg_title": reg_title, "reg_dois": reg_dois, "reg_uid": uid}


def verify_ena(acc, paper_title, paper_doi):
    """PRJEB* via ENA browser API XML (project)."""
    root = fetch_xml(f"https://www.ebi.ac.uk/ena/browser/api/xml/{acc}")
    # ENA returns a well-formed error 404 -> FetchError('missing'); malformed -> not found
    titles = list(root.iter("TITLE"))
    name_attrs = [t for t in root.iter("PROJECT") if t.get("name")]
    reg_title = (titles[0].text if titles else
                 (name_attrs[0].get("name") if name_attrs else None))
    reg_dois = [x.text for x in root.iter("DOI") if x.text]
    return {"found": reg_title is not None, "reg_title": reg_title, "reg_dois": reg_dois}


def verify_ddbj(acc, paper_title, paper_doi):
    """PRJDB* via DDBJ BioProject search API (JSON)."""
    data = fetch_json("https://ddbj.nig.ac.jp/api/publications/bioprojects/search?" + urlencode(
        {"bioproject_acc": acc}))
    hits = data if isinstance(data, list) else (data.get("hit") or data.get("results") or [])
    if not hits:
        return {"found": False, "confirmed_missing": True,
                "detail": "DDBJ search returned 0 hits"}
    first = hits[0] if isinstance(hits, list) else hits
    reg_title = (first.get("title") or (first.get("bioproject") or {}).get("title"))
    reg_dois = [first.get("doi")] if first.get("doi") else []
    return {"found": True, "reg_title": reg_title, "reg_dois": reg_dois}


REGISTRY_CLIENTS = {
    "PRJNA": verify_ncbi,
    "PRJEB": verify_ena,
    "PRJDB": verify_ncbi,  # DDBJ's own JSON API 403s; NCBI mirrors all INSDC BioProjects
}


def _looks_like_non_title(t):
    """Heuristic: extracted 'title' is actually a stray author/affiliation
    block or citation header, not a real article title."""
    if not t:
        return True
    s = t.strip()
    if re.search(r"(?:MD|PhD|Prof|BSc|MSc|FRCP)\b", s):
        return True
    if re.match(r"^[,;.\s]*\d", s):
        return True                      # ',1 Amir Hadi...' — numbering splice
    if re.search(r"\bSupplementary|\bCorrespondence|\bAffiliat", s, re.I):
        return True
    if s.startswith("http") or s.startswith("www."):
        return True
    return False


def classify(found_result, paper_title, paper_doi, attempt_note=None):
    """Apply the metadata-identity gate. HTTP-found alone is NOT verified."""
    if not found_result.get("found"):
        return ("CONFIRMED_MISSING", found_result)
    if found_result.get("accession_mismatch"):
        return ("CONFLICTING", dict(found_result,
                                    reason="registry returned a different accession than requested"))
    score, basis = identity_score(paper_title, found_result.get("reg_title"),
                                  paper_doi, found_result.get("reg_dois"))
    found_result["identity"] = basis
    found_result["identity_score"] = score
    if score >= 0.35:
        return ("OK_VERIFIED", found_result)
    # weak identity: never auto-promote. Decide between REVIEW and CONFLICTING
    # strictly on the evidence we have: a registry title that shares essentially
    # zero tokens is a disagreement signal only if BOTH titles are substantive
    # AND look like titles (a corrupt extracted paper title must never
    # manufacture a conflict).
    pt, rt = title_tokens(paper_title), title_tokens(found_result.get("reg_title"))
    paper_title_is_title = pt and len(pt) >= 3 and not _looks_like_non_title(paper_title)
    if paper_title_is_title and rt and not (pt & rt):
        return ("CONFLICTING", dict(found_result, reason="registry title shares no tokens with paper title"))
    return ("OK_REVIEW", dict(found_result, reason="weak metadata identity; queued for human review"))


def verify_one(paper, dataset, rp_per_sec=0.34):
    pid = paper["paper_id"]
    accs = [a for a in (dataset.get("repository_accession") or []) if a]
    if not accs:
        return {"paper_id": pid, "accession": None, "status": "CONFIRMED_MISSING",
                "checked_at": now_iso(), "detail": "catalogue row has no accession"}
    acc = accs[0]
    prefix = acc[:5]
    client = REGISTRY_CLIENTS.get(prefix)
    if client is None:
        return {"paper_id": pid, "accession": acc, "status": "UNVERIFIED_UNSUPPORTED_REGISTRY",
                "checked_at": now_iso(),
                "detail": f"no registry client for prefix {prefix}; recorded as-is, never invented"}
    time.sleep(1.0 / rp_per_sec if rp_per_sec else 0)
    try:
        found = client(acc, paper.get("title"), paper.get("doi"))
    except FetchError as e:
        status = "TRANSIENT" if e.kind in ("transient", "error") else (
            "CONFIRMED_MISSING" if e.kind == "missing" else "TRANSIENT")
        # unknown FetchError kinds are never quietly downgraded to
        # 'unsupported' — that status is reserved for prefixes with no client
        return {"paper_id": pid, "accession": acc, "status": status,
                "checked_at": now_iso(), "detail": f"{e}", "attempts_detail": attempt_note(pid, acc, e)}
    except Exception as e:
        return {"paper_id": pid, "accession": acc, "status": "TRANSIENT",
                "checked_at": now_iso(), "detail": f"unexpected client error: {e}",
                "attempts_detail": attempt_note(pid, acc, e)}
    status, payload = classify(found, paper.get("title"), paper.get("doi"), None)
    row = {"paper_id": pid, "accession": acc, "status": status,
           "checked_at": now_iso(), "reg_title": found.get("reg_title"),
           "reg_dois": found.get("reg_dois") or [],
           "identity": found.get("identity", {}),
           "detail": found.get("reason") or found.get("detail")}
    return row


def attempt_note(pid, acc, e):
    return f"paper={pid} acc={acc} err={e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalogue", default=str(CATALOGUE))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--only", default=None,
                    help="comma-separated paper_ids or accessions to verify (testing/small runs)")
    ap.add_argument("--status", default=None,
                    help="re-run only rows currently in this status (e.g. TRANSIENT)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--rate", type=float, default=0.34,
                    help="requests per second (default 0.34 = ~3s politeness)")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    catalogue = json.load(open(args.catalogue))
    paper_by = {p["paper_id"]: p for p in catalogue["papers"]}
    acc_by_paper = {}
    for d in catalogue["datasets"]:
        accs = [a for a in (d.get("repository_accession") or []) if a]
        if accs:
            acc_by_paper[d["paper_id"]] = d

    prev_rows = {}
    out_path = Path(args.out)
    if out_path.exists():
        prev = json.load(open(out_path))
        prev_rows = {r["paper_id"]: r for r in prev.get("results", [])}

    todo = list(acc_by_paper.items())
    if args.only:
        keys = {x.strip() for x in args.only.split(",")}
        todo = [(p, d) for p, d in todo if p in keys or
                any(a in keys for a in (d.get("repository_accession") or []))]
    if args.status:
        keep = {p for p, r in prev_rows.items() if r.get("status") == args.status}
        todo = [(p, d) for p, d in todo if p in keep]
    if args.limit:
        todo = todo[: args.limit]
    log.info("verifying %d accessions (rate %.2f req/s, timeout %ds)", len(todo), args.rate, args.timeout)

    results = []
    kept_prev = {p: r for p, r in prev_rows.items()
                 if not any(p == t[0] for t in todo)}
    for pid, d in todo:
        row = verify_one(paper_by[pid], d, rp_per_sec=args.rate)
        results.append(row)
        if len(results) % 25 == 0:
            log.info("%d/%d done (last: %s %s %s)", len(results), len(todo),
                     row["paper_id"], row.get("accession"), row["status"])
    results.extend(kept_prev.values())

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    report = {
        "verifier_version": VERSION,
        "generated_at": now_iso(),
        "catalogue": str(args.catalogue),
        "lib_xml": XML_LIB,
        "n_accessions_checked": len(results),
        "status_counts": counts,
        "blocking_for_release": ["TRANSIENT", "CONFLICTING"],
        "protocol": {
            "statuses": {
                "OK_VERIFIED": "registry record found + metadata identity passed",
                "OK_REVIEW": "found; weak/no identity evidence -> human review queue",
                "CONFIRMED_MISSING": "registry authoritatively reports absence",
                "TRANSIENT": "timeout/5xx/rate-limit — must re-run before release",
                "CONFLICTING": "registry metadata points at a different paper (hard disagreement, must be reconciled)",
                "UNVERIFIED_UNSUPPORTED_REGISTRY": "prefix with no registry client — uncertainty preserved",
            },
            "identity_policy": "DOI exact match is decisive; else relaxed title-token overlap; "
                                "HTTP 200 alone NEVER equals verified",
            "rate_limit_per_sec": args.rate,
        },
        "results": sorted(results, key=lambda r: r["paper_id"]),
    }
    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=1)
    log.info("status counts: %s", counts)
    log.info("wrote %s", out_path)
    blocking = {s: counts.get(s, 0) for s in report["blocking_for_release"] if counts.get(s)}
    if blocking:
        log.warning("BLOCKING-RELEASE statuses present (must be resolved): %s", blocking)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
