#!/bin/bash
# Fetch the official standards term lists used by the crosswalk into outputs/scratch/standards_fetch_2026-11-11/
# and record URL, version, licence and sha256 in STANDARDS_SOURCES.json (copied to the results folder).
# Generic User-Agent only. Re-running re-downloads and re-hashes (a changed hash shows an upstream change).
set -euo pipefail
CDM_ROOT="$(pwd)"; while [ ! -f "$CDM_ROOT/.cdm_root" ] && [ "$CDM_ROOT" != "/" ]; do CDM_ROOT="$(dirname "$CDM_ROOT")"; done
D="$CDM_ROOT/outputs/scratch/standards_fetch_2026-11-11"; mkdir -p "$D"; cd "$D"
UA="cdm-fixes/1.0"
fetch(){ timeout 60 curl -sSfL -A "$UA" -o "$1" "$2"; }
fetch mixs_v7.0.1_mixs.yaml https://raw.githubusercontent.com/GenomicsStandardsConsortium/mixs/v7.0.1/src/mixs/schema/mixs.yaml
fetch mixs_v7.0.1_LICENSE https://raw.githubusercontent.com/GenomicsStandardsConsortium/mixs/v7.0.1/LICENSE
fetch biolink_v4.4.6_biolink-model.yaml https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/biolink-model.yaml
fetch biolink_v4.4.6_LICENSE https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/LICENSE
fetch STORMS_Excel_1.03.xlsx https://zenodo.org/api/records/5714305/files/STORMS_Excel_1.03.xlsx/content
fetch prov-o_20130430.ttl https://www.w3.org/ns/prov-o-20130430
python3 - "$D" <<'PY'
import hashlib, json, sys, datetime
from pathlib import Path
d = Path(sys.argv[1])
def sha(p): return hashlib.sha256((d / p).read_bytes()).hexdigest()
src = [
 {"standard": "MIxS", "version": "v7.0.1 (GitHub release, 2026-08-01)", "file": "mixs_v7.0.1_mixs.yaml",
  "url": "https://raw.githubusercontent.com/GenomicsStandardsConsortium/mixs/v7.0.1/src/mixs/schema/mixs.yaml",
  "release_page": "https://github.com/GenomicsStandardsConsortium/mixs/releases/tag/v7.0.1",
  "licence": "CC0 1.0 Universal (repository LICENSE)", "licence_file": "mixs_v7.0.1_LICENSE"},
 {"standard": "Biolink Model", "version": "v4.4.6 (GitHub release, 2026-10-09)", "file": "biolink_v4.4.6_biolink-model.yaml",
  "url": "https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/biolink-model.yaml",
  "release_page": "https://github.com/biolink/biolink-model/releases/tag/v4.4.6",
  "licence": "Apache License 2.0 (repository LICENSE)", "licence_file": "biolink_v4.4.6_LICENSE"},
 {"standard": "STORMS checklist", "version": "1.03 (Zenodo record 5714305, concept DOI 10.5281/zenodo.5703116)",
  "file": "STORMS_Excel_1.03.xlsx", "url": "https://zenodo.org/api/records/5714305/files/STORMS_Excel_1.03.xlsx/content",
  "md5_published_by_zenodo": "4962fd585c25bd797c1319e648c46d0a",
  "citation": "Mirzayi C. et al. Nat Med 27, 1885-1892 (2021), doi:10.1038/s41591-021-01552-x",
  "licence": "CC BY 4.0 (Zenodo record metadata)"},
 {"standard": "PROV-O", "version": "W3C Recommendation 2013-04-30", "file": "prov-o_20130430.ttl",
  "url": "https://www.w3.org/ns/prov-o-20130430", "licence": "W3C Software and Document License"},
]
for s in src:
    s["sha256"] = sha(s["file"])
    if "licence_file" in s: s["licence_file_sha256"] = sha(s["licence_file"])
    s["bytes"] = (d / s["file"]).stat().st_size
out = {"fetched": datetime.date.today().isoformat(), "user_agent": "cdm-fixes/1.0", "sources": src}
(d / "STANDARDS_SOURCES.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
PY
