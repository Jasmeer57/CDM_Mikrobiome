"""Human-validation kit for the v3 catalogue (Phase E of
docs/catalogue_cleanup_plan.md), and its scorer.

`make` draws a fixed, seeded, stratified sample (findings over-sampled, since
they are the weakest table) and writes a sheet with blank columns for two
independent reviewers, plus a reviewer guide. `score` reads the filled sheet
and reports precision per table with a 95% Wilson interval, link precision,
and Cohen's kappa between the two reviewers.

Usage:
    python src/scripts/vllm_termpop/make_validation_sample.py make \
        [--catalogue_dir outputs/results/catalogue_v3_vocab]
    python src/scripts/vllm_termpop/make_validation_sample.py score \
        --sheet outputs/results/catalogue_v3_validation/validation_sample.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OUT_DIR = REPO_ROOT / "outputs/results/catalogue_v3_validation"
ID_FIELD = {"datasets": "dataset_id", "data_assets": "asset_id", "cohorts": "cohort_id",
            "samples": "sample_group_id", "assays": "assay_id", "findings": "finding_id"}
QUOTA = {"findings": 160, "cohorts": 48, "samples": 48, "assays": 48, "datasets": 48, "data_assets": 48}
SEED = 20261030
VERDICTS = ("CORRECT", "PARTIAL", "WRONG", "UNSURE")
LINK_VERDICTS = ("CORRECT", "WRONG", "NO_LINK_NEEDED", "MISSING_LINK", "UNSURE")
KEY_FIELDS = {
    "findings": ("taxon_or_feature", "direction", "outcome", "comparison_or_exposure",
                 "is_primary_finding", "finding_domain_normalized", "taxon_ncbi_names"),
    "cohorts": ("cohort_label", "population_description", "participant_count", "country_or_region",
                "health_status"),
    "samples": ("body_site", "body_site_normalized", "sample_type", "sample_type_normalized", "sample_count"),
    "assays": ("assay_type", "assay_type_normalized", "target_gene_or_region", "sequencing_platform"),
    "datasets": ("dataset_title", "repository_normalized", "repository_accession", "data_availability_status"),
    "data_assets": ("asset_name", "asset_type", "accession", "repository_url"),
}
SHEET_COLS = ["sample_no", "entity", "record_id", "paper_id", "doi", "evidence_location", "evidence_text",
              "extracted_values", "links", "reviewer_A_record", "reviewer_A_links", "reviewer_A_notes",
              "reviewer_B_record", "reviewer_B_links", "reviewer_B_notes"]


def make(args):
    cat = Path(args.catalogue_dir)
    records = [json.loads(line) for line in open(cat / "catalogue_records.jsonl", encoding="utf-8")]
    with open(cat / "catalogue_papers.csv", newline="", encoding="utf-8") as fh:
        doi = {p["paper_id"]: p.get("doi", "") for p in csv.DictReader(fh)}
    by = defaultdict(list)
    for r in records:
        if r["fields"].get("record_source") == "corpus_bioproject_link":
            continue  # not model output; nothing to validate
        by[r["entity_type"]].append(r)
    rng = random.Random(SEED)
    rows = []
    for e, n in QUOTA.items():
        pool = sorted(by[e], key=lambda r: r["fields"][ID_FIELD[e]])
        # spread across papers: at most 2 records per paper per entity
        rng.shuffle(pool)
        seen, pick = Counter(), []
        for r in pool:
            if seen[r["paper_id"]] < 2:
                pick.append(r)
                seen[r["paper_id"]] += 1
            if len(pick) == n:
                break
        for r in pick:
            f = r["fields"]
            vals = {k: f.get(k, "") for k in KEY_FIELDS[e] if str(f.get(k, "")).strip()}
            links = {k: f.get(k, "") for k in ("dataset_id", "cohort_id", "assay_id")
                     if k != ID_FIELD[e] and str(f.get(k, "")).strip()}
            rows.append({"entity": e, "record_id": f[ID_FIELD[e]], "paper_id": r["paper_id"],
                         "doi": doi.get(r["paper_id"], ""), "evidence_location": f.get("evidence_location", ""),
                         "evidence_text": f.get("evidence_text", ""),
                         "extracted_values": json.dumps(vals, ensure_ascii=False),
                         "links": json.dumps(links, ensure_ascii=False)})
    rng.shuffle(rows)  # reviewers should not see the tables in blocks
    for i, row in enumerate(rows, 1):
        row["sample_no"] = i
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sheet = out / "validation_sample.csv"
    if sheet.exists() and not args.force:
        sys.exit(f"{sheet} exists (reviewers may have filled it); use --force to overwrite")
    with open(sheet, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SHEET_COLS)
        w.writeheader()
        w.writerows(rows)
    (out / "REVIEWER_GUIDE.md").write_text(GUIDE.format(n=len(rows), quota=json.dumps(QUOTA),
                                                        seed=SEED, cat=cat.name), encoding="utf-8")
    print(f"wrote {len(rows)} sample rows -> {sheet}")
    return 0


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * p, 1), round(100 * (c - h), 1), round(100 * (c + h), 1))


def kappa(pairs):
    pairs = [(a, b) for a, b in pairs if a and b]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def score(args):
    with open(args.sheet, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    res = {"rows": len(rows), "per_entity": {}, "links": {}, "kappa": {}}
    for e in QUOTA:
        rs = [r for r in rows if r["entity"] == e]
        # a record counts as correct only if both reviewers (or the one present) say CORRECT;
        # UNSURE and blank are excluded from the denominator and reported
        decided, correct, unsure = 0, 0, 0
        for r in rs:
            vs = [r[c].strip().upper() for c in ("reviewer_A_record", "reviewer_B_record") if r[c].strip()]
            vs = [v for v in vs if v in VERDICTS]
            if not vs or all(v == "UNSURE" for v in vs):
                unsure += 1
                continue
            decided += 1
            correct += all(v == "CORRECT" for v in vs if v != "UNSURE")
        res["per_entity"][e] = {"sampled": len(rs), "decided": decided, "unsure_or_blank": unsure,
                                "precision_pct_ci95": wilson(correct, decided)}
        lk = [r[c].strip().upper() for r in rs for c in ("reviewer_A_links", "reviewer_B_links")
              if r[c].strip().upper() in ("CORRECT", "WRONG")]
        res["links"][e] = {"judged": len(lk), "precision_pct_ci95": wilson(lk.count("CORRECT"), len(lk))}
    res["kappa"]["record"] = kappa([(r["reviewer_A_record"].strip().upper(), r["reviewer_B_record"].strip().upper())
                                    for r in rows])
    res["kappa"]["links"] = kappa([(r["reviewer_A_links"].strip().upper(), r["reviewer_B_links"].strip().upper())
                                   for r in rows])
    out = Path(args.sheet).with_name("validation_scores.json")
    out.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


GUIDE = """# Reviewer guide — catalogue v3 validation sample

`validation_sample.csv` holds **{n} records** drawn at random (seed {seed}) from
`{cat}`, stratified by table ({quota}; findings over-sampled) with at most two
records per paper per table. Rows are shuffled.

Two reviewers score every row **independently** (do not look at each other's
columns). Open the paper by DOI, go to `evidence_location`, and judge:

## `reviewer_X_record` — is the record right?
- **CORRECT** — every value in `extracted_values` is stated in the paper and
  describes the same thing (the same cohort / assay / finding).
- **PARTIAL** — the record is real but at least one value is wrong or belongs
  to a different group.
- **WRONG** — the record is not supported, misread, or (for findings) not a
  finding at all.
- **UNSURE** — cannot decide; explain in notes.

For findings also check `direction` and `is_primary_finding` (YES = the
paper's own result; NO = background or another study). A wrong direction makes
the record PARTIAL.

## `reviewer_X_links` — are the links right?
Judge `links` (dataset/cohort/assay ids; look them up in the catalogue tables
of the same paper):
- **CORRECT** — every linked id is the right one.
- **WRONG** — at least one linked id is wrong.
- **MISSING_LINK** — no link given but the paper makes it clear.
- **NO_LINK_NEEDED** — no link given and none is clear.
- **UNSURE**.

## Scoring
`python src/scripts/vllm_termpop/make_validation_sample.py score --sheet <this csv>`
reports precision per table (95% Wilson interval), link precision and Cohen's
kappa between reviewers, in `validation_scores.json`. Report those numbers, not
the LLM-judge ones, as the catalogue's precision.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Catalogue validation sample")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--catalogue_dir", default=str(REPO_ROOT / "outputs/results/catalogue_v3_vocab"))
    m.add_argument("--out_dir", default=str(OUT_DIR))
    m.add_argument("--force", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--sheet", default=str(OUT_DIR / "validation_sample.csv"))
    args = ap.parse_args(argv)
    return make(args) if args.cmd == "make" else score(args)


if __name__ == "__main__":
    raise SystemExit(main())
