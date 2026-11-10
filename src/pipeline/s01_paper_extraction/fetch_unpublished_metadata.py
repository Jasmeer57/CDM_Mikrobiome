#!/usr/bin/env python3
"""Fetch full NCBI BioProject metadata for accessions lacking a publication.

For each accession with status=no_publication_found in the coverage manifest,
resolve its BioProject UID via esearch and pull the full esummary record
(title, description, registration date, data type, submitter, publications,
SRA links). Sleeps between calls to respect NCBI rate limits (3 req/s).

Output:
  outputs/results/human_microbiome_corpus_v1/unpublished_accessions_metadata.json  (full records)
  outputs/results/human_microbiome_corpus_v1/unpublished_accessions_metadata.csv   (flat view)

Usage:
  python3 src/scripts/fetch_unpublished_metadata.py [--accessions ACC1,ACC2,...]
"""

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "outputs/results" / "human_microbiome_corpus_v1" / "fulltext_coverage_manifest.csv"
OUT_JSON = REPO / "outputs/results" / "human_microbiome_corpus_v1" / "unpublished_accessions_metadata.json"
OUT_CSV = REPO / "outputs/results" / "human_microbiome_corpus_v1" / "unpublished_accessions_metadata.csv"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
SLEEP_S = 0.4  # ~2.5 req/s, well under the 3 req/s limit


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MicrobiomeCDM-metadata/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def resolve_uid(accession):
    q = urllib.parse.quote(accession)
    d = _get(f"{EUTILS}esearch.fcgi?db=bioproject&term={q}&retmode=json")
    ids = d.get("esearchresult", {}).get("idlist", [])
    return ids[0] if ids else None


def fetch_summary(uid):
    d = _get(f"{EUTILS}esummary.fcgi?db=bioproject&id={uid}&retmode=json")
    result = d.get("result", {})
    return result.get(uid)


def flatten(rec, accession):
    """Flatten an esummary record into one CSV row."""
    pubs = rec.get("project_pub_list") or []
    pub_strs = []
    for p in pubs:
        db = p.get("db", "")
        acc = p.get("acc", "")
        pid = str(p.get("id", ""))
        pub_strs.append(f"{db}:{acc or pid}".rstrip(":"))
    samples_meta = rec.get("sample_size", "")
    return {
        "accession": accession,
        "uid": rec.get("uid", ""),
        "project_title": rec.get("project_title", ""),
        "project_description": rec.get("project_description", ""),
        "registration_date": rec.get("registration_date", ""),
        "project_data_type": rec.get("project_data_type", ""),
        "project_target_scope": rec.get("project_target_scope", ""),
        "project_target_material": rec.get("project_target_material", ""),
        "project_methodtype": rec.get("project_methodtype", ""),
        "organism_name": rec.get("organism_name", ""),
        "organism_count": rec.get("organism_count", ""),
        "sample_count_meta": samples_meta,
        "submitter_organization": rec.get("submitter_organization", "") or rec.get("submitter_contact", ""),
        "publications": "; ".join(pub_strs),
    }


def main():
    accs = None
    if "--accessions" in sys.argv:
        accs = sys.argv[sys.argv.index("--accessions") + 1].split(",")

    if accs is None:
        with open(MANIFEST, newline="") as f:
            accs = [r["accession"] for r in csv.DictReader(f) if r["status"] == "no_publication_found"]

    print(f"Fetching metadata for {len(accs)} accessions")
    records, failed = {}, []
    for i, acc in enumerate(accs, 1):
        try:
            uid = resolve_uid(acc)
            time.sleep(SLEEP_S)
            if not uid:
                print(f"  [{i}/{len(accs)}] {acc}: no BioProject UID found")
                failed.append(acc)
                continue
            rec = fetch_summary(uid)
            time.sleep(SLEEP_S)
            if not rec:
                print(f"  [{i}/{len(accs)}] {acc}: empty summary for uid={uid}")
                failed.append(acc)
                continue
            records[acc] = {"uid": uid, **rec}
            print(f"  [{i}/{len(accs)}] {acc}: {rec.get('project_title', '')[:60]}")
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(accs)}] {acc}: ERROR {e}")
            failed.append(acc)

    OUT_JSON.write_text(json.dumps(records, indent=2))
    print(f"\nWrote {len(records)} records -> {OUT_JSON}")

    rows = [flatten(r, a) for a, r in records.items()]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote flattened CSV -> {OUT_CSV}")

    if failed:
        print(f"Failed: {len(failed)}: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
