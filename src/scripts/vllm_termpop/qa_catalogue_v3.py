"""Fail-closed integrity checks for the v3 catalogue (Phase D3 of
docs/catalogue_cleanup_plan.md). Read-only.

Hard checks (any failure -> exit 1):
  corpus_453          catalogue_papers.csv has exactly the expected papers, every
                      record's paper is in it, every paper has a record
  primary_keys        ids present and unique per entity
  links_resolve       every dataset_id/cohort_id/assay_id names a record of the
                      right entity IN THE SAME PAPER
  no_placeholders     no "n/a", "not stated", ... left in data fields
  accessions_valid    every filled repository_accession is a recognisable id
  counts_plausible    no participant_count > 50,000 or sample_count > 500,000
  direction_vocab     direction in the controlled vocabulary
  vocab_labels        normalised columns hold only labels from vocab.yaml
  csv_matches_jsonl   each CSV has exactly the JSONL's rows for its entity
  v2_traceable        every v2 record id appears once in _v2_to_v3_map.csv and
                      every folded id is in _removed.jsonl

Measures (reported, not gating): evidence located, link fill, vocabulary and
taxon coverage, primary-finding verdicts.

Usage:
    python src/scripts/vllm_termpop/qa_catalogue_v3.py \
        [--catalogue_dir outputs/results/catalogue_v3_vocab]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))

import clean_catalogue as cc  # noqa: E402

ENTITIES = cc.ENTITIES
ID_FIELD = cc.ID_FIELD
LINK_TARGET = {"dataset_id": "datasets", "cohort_id": "cohorts", "assay_id": "assays"}
# template missing-data vocabulary: valid values, not placeholders
MISSING_CODES = {"NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING"}
DATA_SKIP = {"direction", "direction_original", "direction_llm", "finding_source", "v3_status", "link_status",
             "taxon_link_status", "body_site_status", "sample_type_normalization_status"}


def run_checks(cat_dir, v2_records, expected, vocab_path):
    cat_dir = Path(cat_dir)
    records = [json.loads(line) for line in open(cat_dir / "catalogue_records.jsonl", encoding="utf-8")]
    with open(cat_dir / "catalogue_papers.csv", newline="", encoding="utf-8") as fh:
        papers = [p["paper_id"] for p in csv.DictReader(fh)]
    checks, details = {}, {}

    # corpus
    rec_papers = {r["paper_id"] for r in records}
    problems = []
    if len(papers) != expected or len(set(papers)) != len(papers):
        problems.append(f"papers table has {len(papers)} rows ({len(set(papers))} unique), expected {expected}")
    if rec_papers - set(papers):
        problems.append(f"{len(rec_papers - set(papers))} record papers not in papers table")
    if set(papers) - rec_papers:
        problems.append(f"papers with no record: {sorted(set(papers) - rec_papers)}")
    checks["corpus_453"], details["corpus_453"] = not problems, problems

    # primary keys
    ids = defaultdict(Counter)
    for r in records:
        ids[r["entity_type"]][r["fields"].get(ID_FIELD[r["entity_type"]], "")] += 1
    bad = {e: {"blank": c.get("", 0), "duplicated": sum(1 for k, v in c.items() if k and v > 1)}
           for e, c in ids.items()}
    checks["primary_keys"] = all(v["blank"] == 0 and v["duplicated"] == 0 for v in bad.values())
    details["primary_keys"] = bad

    # links
    owner = {}
    for r in records:
        owner[(r["entity_type"], r["fields"][ID_FIELD[r["entity_type"]]])] = r["paper_id"]
    broken = Counter()
    for r in records:
        for fld, tgt in LINK_TARGET.items():
            if fld == ID_FIELD[r["entity_type"]]:
                continue
            for i in filter(None, (x.strip() for x in str(r["fields"].get(fld, "")).split(";"))):
                if owner.get((tgt, i)) != r["paper_id"]:
                    broken[f"{r['entity_type']}.{fld}"] += 1
    checks["links_resolve"], details["links_resolve"] = not broken, dict(broken)

    # placeholders
    ph = Counter()
    for r in records:
        for k, v in r["fields"].items():
            if k in DATA_SKIP or k in cc.VOCAB_KEEP:
                continue
            if isinstance(v, str) and v.strip() not in MISSING_CODES and v.strip().lower().strip(" .") in cc.PLACEHOLDERS - {"0"}:
                ph[k] += 1
    checks["no_placeholders"], details["no_placeholders"] = not ph, dict(ph)

    # accessions
    bad_acc = [r["fields"]["repository_accession"] for r in records if r["entity_type"] == "datasets"
               and str(r["fields"].get("repository_accession", "")).strip()
               and str(r["fields"]["repository_accession"]).strip() not in MISSING_CODES
               and not cc.find_accessions(str(r["fields"]["repository_accession"]))]
    checks["accessions_valid"], details["accessions_valid"] = not bad_acc, bad_acc[:20]

    # counts
    big = []
    for r in records:
        f = r["fields"]
        for fld, lim in (("participant_count", cc.PARTICIPANT_MAX), ("sample_count", cc.SAMPLE_MAX)):
            if r["entity_type"] in ("cohorts", "samples") and str(f.get(fld, "")).strip() not in ("", *MISSING_CODES):
                try:
                    if int(f[fld]) > lim:
                        big.append((f[ID_FIELD[r["entity_type"]]], fld, f[fld]))
                except (TypeError, ValueError):
                    big.append((f[ID_FIELD[r["entity_type"]]], fld, f[fld]))
    checks["counts_plausible"], details["counts_plausible"] = not big, big[:20]

    # direction
    dirs = Counter(r["fields"].get("direction") for r in records if r["entity_type"] == "findings")
    off = {k: v for k, v in dirs.items() if k not in cc.DIRECTIONS}
    checks["direction_vocab"], details["direction_vocab"] = not off, off

    # vocabulary labels
    import yaml
    vocab = yaml.safe_load(Path(vocab_path).read_text(encoding="utf-8"))
    allowed = {
        "body_site_normalized": {x["label"] for x in vocab["body_site"]["rules"]},
        "assay_type_normalized": {x["label"] for x in vocab["assay_type"]["rules"]},
        "repository_normalized": ({x["label"] for x in vocab["repository_name"]["rules"]}
                                  | set(vocab["repository_name"]["from_accession_type"].values())),
        "finding_domain_normalized": {x["label"] for x in vocab["finding_domain"]["rules"]},
        "taxonomic_rank_normalized": {x["label"] for x in vocab["taxonomic_rank"]["rules"]},
    }
    off_vocab = Counter()
    present = Counter()
    for r in records:
        for col, ok in allowed.items():
            if col in r["fields"]:
                present[col] += 1
                v = r["fields"][col]
                if v and v not in ok:
                    off_vocab[f"{col}={v}"] += 1
    missing_cols = [c for c in allowed if not present[c]]
    checks["vocab_labels"] = not off_vocab and not missing_cols
    details["vocab_labels"] = {"off_vocabulary": dict(off_vocab), "columns_missing": missing_cols}

    # csv vs jsonl
    mism = {}
    per = Counter(r["entity_type"] for r in records)
    for e in ENTITIES:
        with open(cat_dir / f"catalogue_{e}.csv", newline="", encoding="utf-8") as fh:
            n = sum(1 for _ in csv.DictReader(fh))
        if n != per[e]:
            mism[e] = {"csv": n, "jsonl": per[e]}
    checks["csv_matches_jsonl"], details["csv_matches_jsonl"] = not mism, mism

    # v2 traceability
    with open(cat_dir / "_v2_to_v3_map.csv", newline="", encoding="utf-8") as fh:
        mapped = Counter(r["v2_id"] for r in csv.DictReader(fh))
    removed = {json.loads(line)["fields"][ID_FIELD[json.loads(line)["entity_type"]]]
               for line in open(cat_dir / "_removed.jsonl", encoding="utf-8")}
    v2_ids = [r["fields"][ID_FIELD[r["entity_type"]]] for r in v2_records]
    kept_ids = {r["fields"][ID_FIELD[r["entity_type"]]] for r in records}
    unmapped = [i for i in v2_ids if mapped[i] != 1]
    lost = [i for i in v2_ids if i not in kept_ids and i not in removed]
    checks["v2_traceable"] = not unmapped and not lost
    details["v2_traceable"] = {"v2_records": len(v2_ids), "not_mapped_once": unmapped[:20],
                               "neither_kept_nor_removed": lost[:20]}

    # measures
    by = defaultdict(list)
    for r in records:
        by[r["entity_type"]].append(r)
    measures = {
        "records": len(records), "records_per_entity": dict(per),
        "evidence_located_pct": {e: round(100 * sum(int(r["evidence_verified"]) for r in by[e]) / max(1, len(by[e])), 1)
                                 for e in ENTITIES},
        "link_fill_pct": {e: {fld: round(100 * sum(1 for r in by[e] if str(r["fields"].get(fld, "")).strip())
                                         / max(1, len(by[e])), 1)
                              for fld in LINK_TARGET if fld != ID_FIELD[e] and fld in r_fields(by[e])}
                          for e in ENTITIES},
        "body_site_normalized_pct": {e: round(100 * sum(1 for r in by[e] if r["fields"].get("body_site_status") == "NORMALIZED")
                                              / max(1, sum(1 for r in by[e] if r["fields"].get("body_site_status") not in (None, "EMPTY"))), 1)
                                     for e in ("samples", "findings")},
        "taxon_link_status": dict(Counter(r["fields"].get("taxon_link_status") for r in by["findings"]).most_common()),
        "is_primary_finding": dict(Counter(r["fields"].get("is_primary_finding") for r in by["findings"])),
        "is_primary_finding_source": dict(Counter(r["fields"].get("is_primary_finding_source", "RULE") for r in by["findings"])),
    }
    return checks, details, measures


def r_fields(rows):
    keys = set()
    for r in rows[:50]:
        keys |= set(r["fields"])
    return keys


def main(argv=None):
    ap = argparse.ArgumentParser(description="v3 catalogue integrity checks")
    ap.add_argument("--catalogue_dir", default=str(REPO_ROOT / "outputs/results/catalogue_v3_vocab"))
    ap.add_argument("--v2_records", default=str(REPO_ROOT / "outputs/results/catalogue_ner_v2/catalogue_records.jsonl"))
    ap.add_argument("--vocab", default=str(REPO_ROOT / "src/configs/catalogue_vocab/vocab.yaml"))
    ap.add_argument("--expected_papers", type=int, default=453)
    args = ap.parse_args(argv)

    v2 = [json.loads(line) for line in open(args.v2_records, encoding="utf-8")]
    checks, details, measures = run_checks(args.catalogue_dir, v2, args.expected_papers, args.vocab)
    verdict = "PASS" if all(checks.values()) else "FAIL"
    report = {"catalogue_dir": args.catalogue_dir, "verdict": verdict, "checks": checks,
              "details": details, "measures": measures}
    out = Path(args.catalogue_dir)
    (out / "qa_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    L = [f"# v3 catalogue QA — {verdict}", "", "| check | result |", "|---|---|"]
    L += [f"| {k} | {'pass' if v else '**FAIL**'} |" for k, v in checks.items()]
    L += ["", "Failures, if any, are detailed in `qa_report.json`.", "", "## Measures", "",
          "```json", json.dumps(measures, indent=1), "```", ""]
    (out / "QA_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    for k, v in checks.items():
        print(f"{'pass' if v else 'FAIL'}  {k}" + ("" if v else f"  {json.dumps(details[k], default=str)[:300]}"))
    print("verdict:", verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
