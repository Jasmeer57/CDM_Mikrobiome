#!/usr/bin/env bash
# Verify every component of the current frozen set against its own manifest. Exit 1 on any failure.
set -u
cd "$(dirname "$0")"
rc=0
for d in 01_corpus_release 05_terminology 06_data_catalogue 07_common_data_model ../frozen_output; do
  (cd "$d" && sha256sum -c --quiet MANIFEST.sha256 >/dev/null 2>&1) && echo "OK   $d" || { echo "FAIL $d"; rc=1; }
done
echo "(02_corpus_segmented, 03_corpus_markdown, 04_ner_per_model are covered by ../frozen_output/MANIFEST.sha256)"
exit $rc
