"""Peek at catalogue-NER results while a run is still in progress.

Reads the resumable checkpoint (`_catalogue_cache.json`) and renders the records
extracted so far — counts per entity type, the most common values per field, and
optional preview CSVs. Nothing is finalised and no IDs are assigned, so this is
strictly a progress window onto a running job.

Checkpoint entries written by catalogue_ner.py >= v1.1 carry provenance
(cid/sid/char span); older entries do not, in which case paper/section columns
are left blank rather than guessed.

Usage:
    PYTHONPATH=src python src/scripts/vllm_termpop/peek_records.py \
        --run_dir outputs/results/catalogue_ner_full [--csv] [--samples 3]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalogue_ner as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Peek at in-progress catalogue NER")
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--csv", action="store_true",
                    help="also write preview CSVs into <run_dir>/preview/")
    ap.add_argument("--samples", type=int, default=3,
                    help="example values to print per field")
    ap.add_argument("--top", type=int, default=8,
                    help="most common values to print per field")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    cache_path = run_dir / "_catalogue_cache.json"
    if not cache_path.exists():
        print("no checkpoint yet at", cache_path)
        return

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    done = sum(1 for v in cache.values() if v.get("records"))
    errors = sum(1 for v in cache.values() if v.get("error"))
    print("requests checkpointed: %d (with records: %d, errors: %d)"
          % (len(cache), done, errors))

    headers = C.load_schema_headers()
    buckets = collections.defaultdict(list)
    for key, entry in cache.items():
        if entry.get("error") or "records" not in entry:
            continue
        prov = {k: entry.get(k) for k in ("cid", "sid", "s", "e")}
        for entity, recs in entry["records"].items():
            if entity not in C.ENTITY_SPECS:
                continue
            allowed = C.ENTITY_SPECS[entity][3]
            for rec in recs or []:
                clean = C.normalise_record(entity, rec, allowed)
                if clean:
                    buckets[entity].append((prov, clean))

    total = sum(len(v) for v in buckets.values())
    print("records so far: %s (total %d)"
          % ({k: len(v) for k, v in sorted(buckets.items())}, total))
    if not total:
        return

    for entity in sorted(buckets):
        recs = buckets[entity]
        print("\n=== %s (%d) ===" % (entity, len(recs)))
        # value frequency per informative field
        for field in C.ENTITY_SPECS[entity][3]:
            if field == "evidence_text":
                continue
            vals = [str(r.get(field)) for _p, r in recs if r.get(field)]
            if not vals:
                continue
            top = collections.Counter(vals).most_common(args.top)
            shown = "; ".join("%s (%d)" % (v[:60], n) for v, n in top)
            print("  %-26s %s" % (field, shown))

    if args.csv:
        out = run_dir / "preview"
        out.mkdir(parents=True, exist_ok=True)
        for entity, recs in buckets.items():
            cols = headers[entity]
            path = out / ("preview_%s.csv" % entity)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols + ["_paper", "_section"],
                                   extrasaction="ignore")
                w.writeheader()
                for prov, rec in recs:
                    row = {k: rec.get(k, "") for k in cols}
                    row["_paper"] = prov.get("cid") or ""
                    row["_section"] = prov.get("sid") or ""
                    w.writerow(row)
            print("wrote", path)


if __name__ == "__main__":
    main()
