#!/usr/bin/env python3
"""Stage 20: metadata backfill from Entrez (NCBI) + enrichment via Semantic Scholar.

Inputs : data/papers.jsonl (from stage 10)
Outputs: data/papers.jsonl updated in place (metadata ONLY; no touching of
         text/coverage fields), data/eligibility_decisions.csv,
         raw/metadata/*.json (write-once API payloads)

Never fabricates: identifiers are filled only when an API returns them with a
title whose normalized token overlap is >= TITLE_MATCH_MIN (cross-source
verification). Each attribution records source + vote evidence in
metadata_provenance. Every paper is checkpointed, so a killed job resumes.

API keys come from config/secrets.env (loaded via common.load_secrets); they are
never written into the corpus.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage20_metadata"
PV = "2.0.0"
ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
S2_BASE = "https://api.semanticscholar.org/graph/v1"

TITLE_MATCH_MIN = 0.90  # normalized-title similarity for cross-source verification

# Internal cross-references used ONLY to recover a title that the segmented
# markdown front matter lacks, so that an API lookup becomes possible. Checked in
# order; the exact source is recorded. Identifiers (PMID/DOI) still come from the
# APIs, never from these files.
INTERNAL_TITLE_SOURCES = [
    ("internal:id_map.csv", C.REPO_ROOT / "data" / "corpus" / "id_map.csv"),
    ("internal:corpus_tracking.csv",
     C.REPO_ROOT / "data" / "corpus" / "corpus_tracking.csv"),
]


def load_internal_titles() -> dict:
    """paper_id -> {title, source, bioproject}. First source with a title wins."""
    import csv
    out = {}
    for source, path in INTERNAL_TITLE_SOURCES:
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                cid = (row.get("corpus_id") or "").strip()
                title = (row.get("title") or "").strip()
                if cid and title and cid not in out:
                    out[cid] = {
                        "title": title,
                        "source": source,
                        "bioproject": (row.get("bioproject_accession")
                                       or row.get("bioproject") or "").strip() or None,
                    }
    return out


def similarity(a: str, b: str) -> float:
    a_tok, b_tok = set(a.split()), set(b.split())
    if not a_tok or not b_tok:
        return 0.0
    return len(a_tok & b_tok) / min(len(a_tok), len(b_tok))


def entrez_lookup_title(client, api_key, email, tool, title, retmax=3):
    """esearch in pubmed, then esummary; returns (best title-matched record, provenance)."""
    provenance = []
    try:
        res = client.get_json(f"{ENTREZ_BASE}/esearch.fcgi", {
            "db": "pubmed", "term": f"{title}[Title]", "retmax": retmax,
            "api_key": api_key, "email": email, "tool": tool,
            "retmode": "json", "sort": "relevance"})
        ids = res.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None, provenance
        summ = client.get_json(f"{ENTREZ_BASE}/esummary.fcgi", {
            "db": "pubmed", "id": ",".join(ids[:retmax]), "retmode": "json",
            "api_key": api_key, "email": email, "tool": tool})
        best, best_score = None, 0.0
        for pmid in ids:
            rec = summ.get("result", {}).get(pmid)
            if not rec:
                continue
            score = similarity(C.normalize_title(title), C.normalize_title(rec.get("title", "")))
            provenance.append({"pmid": pmid, "pubmed_title": rec.get("title"),
                               "score": round(score, 3)})
            if score > best_score:
                best, best_score = rec, score
        if best and best_score >= TITLE_MATCH_MIN:
            aid = best.get("articleids", [])

            def getid(idtype):
                return next((a["value"] for a in aid if a["idtype"] == idtype), None)

            return {
                "PMID": str(best.get("uid")), "DOI": getid("doi"),
                "title_pubmed": best.get("title"),
                "journal_name": best.get("fulljournalname") or best.get("source"),
                "publication_year": int(str(best.get("pubdate", "0"))[:4]) or None,
                "publication_type": ",".join(best.get("pubtype", [])) or None,
                "authors": [a.get("name") for a in best.get("authors", [])],
                "match_score": best_score,
                "match_method": f"normalized-title token overlap >= {TITLE_MATCH_MIN}",
            }, provenance
    except Exception as e:  # noqa: BLE001 - record failure, never crash the stage
        return None, [{"error": repr(e)}]
    return None, provenance


def s2_lookup(client, api_key, title, fields):
    provenance = []
    try:
        data = client.get_json(f"{S2_BASE}/paper/search", {
            "query": title, "limit": 3, "fields": fields},
            headers={"x-api-key": api_key} if api_key else None)
        best, best_score = None, 0.0
        for rec in data.get("data", []):
            score = similarity(C.normalize_title(title), C.normalize_title(rec.get("title", "")))
            provenance.append({"s2_paper_id": rec.get("paperId"), "score": round(score, 3)})
            if score > best_score:
                best, best_score = rec, score
        if best and best_score >= TITLE_MATCH_MIN:
            out = dict(best)
            out["match_score"] = best_score
            out["match_method"] = f"normalized-title token overlap >= {TITLE_MATCH_MIN}"
            return out, provenance
    except Exception as e:  # noqa: BLE001
        return None, [{"error": repr(e)}]
    return None, provenance


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    secrets = C.load_secrets()
    entrez_key = secrets.get("ENTREZ_API_KEY", "")
    entrez_email = secrets.get("ENTREZ_EMAIL", "")
    entrez_tool = secrets.get("ENTREZ_TOOL", "corpusv2")
    s2_key = secrets.get("S2_API_KEY", "")
    fields = cfg["search_strategy"]["s2_fields"]

    client = C.RateLimitedClient(min_interval=1.05)  # S2/NCBI: stay at ~1 req/s
    raw = C.WriteOnceRaw(C.CORPUS_DIR / "raw" / "metadata")
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()
    id_map = load_internal_titles()
    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    if not papers:
        sys.exit("ERROR: data/papers.jsonl missing/empty; run stage 10 first")

    prog = C.Progress(STAGE, total=len(papers), unit="paper", desc="metadata")
    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl", key="paper_id")
    started = C.now_utc()
    n_entrez = n_s2 = n_miss = n_skipped = 0

    def put_raw(relpath: str, payload: dict):
        """Write-once raw artifact. A changed upstream payload is recorded, not fatal."""
        try:
            raw.put(relpath, json.dumps(payload, indent=1, sort_keys=True).encode())
        except RuntimeError as e:
            cur.add(relpath.split("_")[0], STAGE, "stage20_metadata", PV,
                    "raw write-once", "conflict", problem=str(e),
                    resolution="first-seen payload retained; new payload not stored")

    for p in papers:
        pid = p["paper_id"]
        title = (p.get("title") or "").strip()
        fingerprint = C.sha256_text(title or f"{pid}:no-title")
        if ckpt.has(pid, fingerprint):
            n_skipped += 1
            prog.update(1, detail=f"{pid} resumed-from-checkpoint")
            continue

        rec = dict(p)
        title_source = "segmented_markdown_frontmatter" if title else None
        if not title and id_map.get(pid, {}).get("title"):
            internal = id_map[pid]
            title = internal["title"]
            rec["title"] = title
            rec["title_source"] = internal["source"]
            rec["title_recovered"] = True
            title_source = internal["source"]
            cur.add(pid, STAGE, "stage20_metadata", PV,
                    "title recovery", "recovered",
                    problem="source front matter has no title",
                    resolution=f"title taken from {internal['source']} by exact corpus_id; "
                               "identifiers still require API title match")

        prov = {"paper_id": pid, "entrez": [], "s2": [],
                "queried_title": title or None, "title_source": title_source}

        if title:
            ent, ent_prov = entrez_lookup_title(
                client, entrez_key, entrez_email, entrez_tool, title)
            prov["entrez"] = ent_prov
            if ent:
                put_raw(f"{pid}_entrez.json", ent)
                score = ent.pop("match_score", None)
                ent.pop("match_method", None)
                for k in ("PMID", "DOI", "journal_name", "publication_year",
                          "publication_type", "authors"):
                    if ent.get(k) and not rec.get(k):
                        rec[k] = ent[k]
                        rec.setdefault("metadata_provenance", {})[k] = {
                            "source": "entrez:esummary", "match_score": score,
                            "match_method": f"normalized-title >= {TITLE_MATCH_MIN}"}
                n_entrez += 1

            s2, s2_prov = s2_lookup(client, s2_key, title, fields)
            prov["s2"] = s2_prov
            if s2:
                put_raw(f"{pid}_s2.json", s2)
                ext = s2.get("externalIds") or {}
                src = {"source": "s2", "match_score": s2.get("match_score")}
                if ext.get("PubMed") and not rec.get("PMID"):
                    rec["PMID"] = str(ext["PubMed"])
                    rec.setdefault("metadata_provenance", {})["PMID"] = src
                if ext.get("DOI") and not rec.get("DOI"):
                    rec["DOI"] = ext["DOI"]
                    rec.setdefault("metadata_provenance", {})["DOI"] = src
                if ext.get("CorpusId"):
                    rec.setdefault("metadata_provenance", {})["s2_corpus_id"] = {
                        "value": ext["CorpusId"], "source": "s2"}
                oa = s2.get("openAccessPdf") or {}
                if oa.get("url") and not rec.get("full_text_url"):
                    rec["full_text_url"] = oa["url"]
                    rec.setdefault("metadata_provenance", {})["full_text_url"] = src
                for k, v in (("citation_count", s2.get("citationCount")),
                             ("venue", s2.get("venue") or (s2.get("journal") or {}).get("name")),
                             ("publication_date_s2", s2.get("publicationDate")),
                             ("abstract_s2", s2.get("abstract")),
                             ("external_ids", ext)):
                    if v is not None:
                        rec[k] = v
                n_s2 += 1
            if not ent and not s2:
                n_miss += 1

        rec["eligibility_status"] = rec.get("eligibility_status", "pending")
        rec["metadata_completeness"] = {
            "has_pmid": bool(rec.get("PMID")) or None,
            "has_doi": bool(rec.get("DOI")) or None,
            "has_title": bool(title) or None,
            "entrez_hit": bool(prov["entrez"] and not prov["entrez"][0].get("error")),
            "s2_hit": bool(prov["s2"] and not prov["s2"][0].get("error")),
            "entrez_error": next((v.get("error") for v in prov["entrez"] if "error" in v), None),
            "s2_error": next((v.get("error") for v in prov["s2"] if "error" in v), None),
            "checked_at": C.now_utc(),
        }
        rec["metadata_provenance"] = rec.get("metadata_provenance", {})
        rec["metadata_provenance"]["lookup"] = prov

        ckpt.add({"paper_id": pid, "paper": rec,
                  "decision": {
                      "paper_id": pid,
                      "title_similarity_checked": bool(title),
                      "eligibility_status": rec["eligibility_status"],
                      "decision_stage": STAGE,
                      "entrez_hit": rec["metadata_completeness"]["entrez_hit"],
                      "s2_hit": rec["metadata_completeness"]["s2_hit"],
                      "exclusion_reason": rec.get("exclusion_reason"),
                  }}, fingerprint=fingerprint)
        ev.record(pipeline_stage=STAGE, paper_id=pid,
                  run_status="success" if (prov["entrez"] or prov["s2"]) else "not_found",
                  input_artifact_hash=C.sha256_text(title),
                  output_artifact_hash=C.sha256_text(
                      json.dumps(prov, sort_keys=True, default=str)))
        prog.update(1, detail=f"{pid} entrez={rec['metadata_completeness']['entrez_hit']} "
                              f"s2={rec['metadata_completeness']['s2_hit']}"
                              + (" title=recovered" if rec.get("title_recovered") else ""))

    ckpt.close()
    updated = [ckpt.done[p["paper_id"]]["paper"] for p in papers]
    decisions = [ckpt.done[p["paper_id"]]["decision"] for p in papers]
    C.write_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl", updated)
    C.write_tracking_table(updated)

    with open(C.CORPUS_DIR / "data" / "eligibility_decisions.csv", "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["paper_id", "title_similarity_checked",
                                           "eligibility_status", "decision_stage",
                                           "entrez_hit", "s2_hit", "exclusion_reason"])
        w.writeheader()
        w.writerows(decisions)

    def cnt(field):
        return sum(1 for r in updated if r.get("metadata_completeness", {}).get(field))

    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "papers": len(updated),
        "resumed_from_checkpoint": n_skipped,
        "entrez_title_match": cnt("entrez_hit"),
        "s2_title_match": cnt("s2_hit"),
        "no_metadata_source": sum(1 for r in updated
                                  if not r["metadata_completeness"]["entrez_hit"]
                                  and not r["metadata_completeness"]["s2_hit"]),
        "with_pmid": cnt("has_pmid"),
        "with_doi": cnt("has_doi"),
        "with_title": cnt("has_title"),
        "titles_recovered_from_internal": sum(1 for r in updated if r.get("title_recovered")),
        "titles_still_missing": [r["paper_id"] for r in updated if not r.get("title")],
        "entrez_errors": sum(1 for r in updated if r["metadata_completeness"]["entrez_error"]),
        "s2_errors": sum(1 for r in updated if r["metadata_completeness"]["s2_error"]),
        "rate_limit_interval_s": 0.4 if s2_key else 1.1,
        "match_threshold": TITLE_MATCH_MIN,
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "metadata_report.json", summary)
    ev.record(pipeline_stage=STAGE, run_status="success", started_at=started,
              completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"entrez={summary['entrez_title_match']} s2={summary['s2_title_match']} "
                   f"none={summary['no_metadata_source']}")
    ev.close()
    prog.close(summary=json.dumps({k: summary[k] for k in
                                   ("entrez_title_match", "s2_title_match", "no_metadata_source")}))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
