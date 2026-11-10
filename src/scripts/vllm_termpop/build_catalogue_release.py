"""Freeze the v3 catalogue as a release (Phase D2/D4 of
docs/catalogue_cleanup_plan.md).

Refuses to run unless `qa_catalogue_v3.py` has passed on the same directory,
and never overwrites an existing release (frozen releases are checksummed).

Licence handling (from fetch_paper_licences.py): an evidence quote ships only
for papers under a Creative Commons licence that allows excerpts. For every
other paper the quote is removed from the public files and only its location
(section + character span) is kept; `evidence_redacted` = LICENCE marks those
rows. The unredacted catalogue stays in outputs/results/ for internal use.

Layout written to --out (default releases/data_catalogue_v3/3.0.0):
    tables/       papers + six entity CSVs (public, redacted)
    records/      catalogue_records.jsonl (public, redacted)
    review/       review queues (redacted)
    provenance/   step reports, QA, v2->v3 map, removed records, licences,
                  vocabulary, ontology-id check, NCBI cache
    scripts/      the code and launcher that produced it
    README.md, MANIFEST.json, MANIFEST.sha256

Usage:
    python src/scripts/vllm_termpop/build_catalogue_release.py \
        [--catalogue_dir outputs/results/catalogue_v3_vocab] [--version 3.0.0]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import stat
import sys
import time
from collections import Counter
from pathlib import Path

csv.field_size_limit(sys.maxsize)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
RESULTS = REPO_ROOT / "outputs/results"
ENTITIES = ("datasets", "data_assets", "cohorts", "samples", "assays", "findings")
SCRIPTS = ("clean_catalogue.py", "link_catalogue.py", "normalize_catalogue_vocab.py",
           "fetch_paper_licences.py", "qa_catalogue_v3.py", "build_catalogue_release.py",
           "make_validation_sample.py", "catalogue_link_a40.sbatch", "catalogue_finalize_v3.sbatch",
           "gaplib.py", "gap_stages.py", "gap_embed.py", "gap_g10.py", "gap_gpu.sbatch", "gap_cpu.sbatch",
           "submit_gap_chain.sh", "llm_judge_validation.py")


def redact_fields(f, redact):
    if redact and str(f.get("evidence_text", "")).strip():
        f["evidence_text"] = ""
        f["evidence_redacted"] = "LICENCE"
    else:
        f.setdefault("evidence_redacted", "")
    return f


def copy_csv(src, dst, policy, extra_cols=()):
    with open(src, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames) + [c for c in extra_cols if c not in reader.fieldnames]
        rows = list(reader)
    if "evidence_text" in cols and "evidence_redacted" not in cols:
        cols.append("evidence_redacted")
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            if "evidence_text" in cols:
                redact_fields(r, policy.get(r.get("paper_id"), "REDACT") == "REDACT")
            w.writerow(r)
    return len(rows)


def write_jsonl(src, dst, policy):
    n = 0
    with open(src, encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            r = json.loads(line)
            redact = policy.get(r["paper_id"], "REDACT") == "REDACT"
            redact_fields(r["fields"], redact)
            if redact:
                for m in r.get("merged_evidence") or []:
                    m["evidence_text"] = ""
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Freeze the v3 data catalogue release")
    ap.add_argument("--catalogue_dir", default=str(RESULTS / "catalogue_v3_vocab"))
    ap.add_argument("--clean_dir", default=str(RESULTS / "catalogue_v3_clean"))
    ap.add_argument("--licences", default=str(RESULTS / "catalogue_v3_licences/paper_licences.csv"))
    ap.add_argument("--version", default="3.0.0")
    ap.add_argument("--out", default=None, help="default: releases/data_catalogue_v3/<version>")
    ap.add_argument("--expected_papers", type=int, default=453)
    args = ap.parse_args(argv)

    cat, clean = Path(args.catalogue_dir), Path(args.clean_dir)
    out = Path(args.out) if args.out else REPO_ROOT / "releases/data_catalogue_v3" / args.version
    if out.exists():
        sys.exit(f"{out} already exists — releases are frozen; bump --version instead")
    qa = json.loads((cat / "qa_report.json").read_text(encoding="utf-8"))
    if qa["verdict"] != "PASS" or Path(qa["catalogue_dir"]).resolve() != cat.resolve():
        sys.exit("qa_report.json is not a PASS for this directory; run qa_catalogue_v3.py first")
    with open(args.licences, newline="", encoding="utf-8") as fh:
        lic = {r["paper_id"]: r for r in csv.DictReader(fh)}
    if len(lic) != args.expected_papers:
        sys.exit(f"licence table has {len(lic)} papers, expected {args.expected_papers}")
    policy = {pid: r["quote_policy"] for pid, r in lic.items()}

    tmp = out.with_name(out.name + ".building")
    if tmp.exists():
        shutil.rmtree(tmp)
    for d in ("tables", "records", "review", "provenance", "scripts"):
        (tmp / d).mkdir(parents=True)

    # papers: licence columns filled from Europe PMC
    with open(cat / "catalogue_papers.csv", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames) + ["evidence_quote_policy", "license_source"]
        papers = list(reader)
    for p in papers:
        L = lic[p["paper_id"]]
        p["license_name"], p["license_url"] = L["license"], L["license_url"]
        p["evidence_quote_policy"] = L["quote_policy"]
        p["license_source"] = f"Europe PMC ({L['matched_by']})"
    with open(tmp / "tables/papers.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(papers)

    counts = {e: copy_csv(cat / f"catalogue_{e}.csv", tmp / f"tables/{e}.csv", policy) for e in ENTITIES}
    n_records = write_jsonl(cat / "catalogue_records.jsonl", tmp / "records/catalogue_records.jsonl", policy)
    write_jsonl(cat / "_removed.jsonl", tmp / "provenance/_removed.jsonl", policy)
    for f in sorted(clean.glob("review_*.csv")) + sorted(cat.glob("review_*.csv")):
        copy_csv(f, tmp / "review" / f.name, policy)

    prov = [(clean / "_clean_report.json", None), (clean / "CLEAN_REPORT.md", None),
            (cat / "_link_report.json", None), (cat / "_vocab_report.json", None),
            (cat / "VOCAB_REPORT.md", None), (cat / "qa_report.json", None), (cat / "QA_REPORT.md", None),
            (cat / "_v2_to_v3_map.csv", None), (Path(args.licences), "paper_licences.csv"),
            (REPO_ROOT / "src/configs/catalogue_vocab/vocab.yaml", None),
            (REPO_ROOT / "src/configs/catalogue_vocab/ontology_id_check.json", None),
            (REPO_ROOT / "src/configs/catalogue_vocab/ncbi_taxon_cache.json", None)]
    for src, name in prov:
        if not src.exists():
            sys.exit(f"missing provenance file {src}")
        shutil.copy2(src, tmp / "provenance" / (name or src.name))
    for s in SCRIPTS:
        src = REPO_ROOT / "src/scripts/vllm_termpop" / s
        if src.exists():
            shutil.copy2(src, tmp / "scripts" / s)

    link = json.loads((cat / "_link_report.json").read_text(encoding="utf-8"))
    pol = Counter(policy.values())
    redacted_rows = 0
    for e in ENTITIES:
        with open(tmp / f"tables/{e}.csv", newline="", encoding="utf-8") as fh:
            redacted_rows += sum(1 for r in csv.DictReader(fh) if r.get("evidence_redacted") == "LICENCE")
    write_readme(tmp / "README.md", args.version, len(papers), n_records, counts, qa, link, pol, redacted_rows)

    files = sorted(p for p in tmp.rglob("*") if p.is_file())
    manifest = {"name": "Human microbiome data catalogue", "version": args.version,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "papers": len(papers), "records": n_records, "records_per_entity": counts,
                "qa_verdict": qa["verdict"], "quote_policy_papers": dict(pol),
                "evidence_rows_redacted": redacted_rows,
                "source_dir": os.path.relpath(cat.resolve(), REPO_ROOT),
                "files": {str(p.relative_to(tmp)): {"bytes": p.stat().st_size, "sha256": sha256(p)}
                          for p in files}}
    (tmp / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    with open(tmp / "MANIFEST.sha256", "w", encoding="utf-8") as fh:
        for p in sorted(p for p in tmp.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"):
            fh.write(f"{sha256(p)}  {p.relative_to(tmp)}\n")

    tmp.rename(out)
    for p in out.rglob("*"):  # freeze: read-only, like the other releases
        if p.is_file():
            os.chmod(p, p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    print(f"release {args.version}: {len(papers)} papers, {n_records} records, "
          f"{len(files) + 1} files -> {out}")
    return 0


def write_readme(path, version, n_papers, n_records, counts, qa, link, pol, redacted_rows):
    m = qa["measures"]
    L = [f"# Human microbiome data catalogue — v{version}", "",
         f"**{n_papers} papers, {n_records:,} machine-extracted records** in six linked tables, "
         "cleaned, linked within each paper, and mapped to controlled vocabularies.", "",
         "> **Status: machine-extracted, not yet human-validated.** A validation sample and "
         "reviewer guide exist (`outputs/results/catalogue_v3_validation/`); precision figures "
         "will be added once curators have scored it.", "",
         "## Tables", "", "| table | rows |", "|---|---:|", f"| papers | {n_papers} |"]
    L += [f"| {e} | {n:,} |" for e, n in counts.items()]
    L += ["", "Join key: `paper_id` (`HMPAPER_######`). Within a paper, `dataset_id`, "
          "`cohort_id` and `assay_id` link records to each other (several ids are `; `-separated); "
          "every link is checked to point at a record of the same paper.", "",
          "## Quality (from `provenance/qa_report.json`)", "",
          f"- All {len(qa['checks'])} integrity checks: **{qa['verdict']}**.",
          f"- Evidence sentence located in the paper: "
          + ", ".join(f"{e} {v}%" for e, v in m["evidence_located_pct"].items()) + ".",
          "- Link fill: " + "; ".join(f"{e}: " + ", ".join(f"{k} {v}%" for k, v in d.items())
                                     for e, d in m["link_fill_pct"].items() if d) + ".",
          f"- Findings that are the paper's own result (`is_primary_finding`): "
          + ", ".join(f"{k} {v:,}" for k, v in m["is_primary_finding"].items()) + ".",
          f"- Taxa linked to NCBI Taxonomy: "
          + ", ".join(f"{k} {v:,}" for k, v in m["taxon_link_status"].items()) + ".", "",
          "## Licence of quoted evidence", "",
          f"Quotes are shipped only for papers whose licence allows it (Europe PMC licence: "
          + ", ".join(f"{k} {v}" for k, v in pol.items()) + f" papers). {redacted_rows:,} rows "
          "from other papers have `evidence_text` removed (`evidence_redacted` = LICENCE); their "
          "`evidence_location` still points to the exact section and character span.", "",
          "## How it was built", "",
          "| step | script | output |", "|---|---|---|",
          "| extraction (v2, Qwen3.5-4B) | `catalogue_ner.py` | `catalogue_ner_v2` |",
          "| A — deterministic cleanup | `clean_catalogue.py` | `catalogue_v3_clean` |",
          f"| B — within-paper linking ({link.get('model', '')}) | `link_catalogue.py` | `catalogue_v3_linked` |",
          "| C — controlled vocabularies | `normalize_catalogue_vocab.py` | `catalogue_v3_vocab` |",
          "| v3.1 gap pipeline — field completion with NOT_REPORTED (G1), paper fields (G2), "
          "record verify-and-repair Gemma+Llama (G3), strict relinking (G4), interventions (G5) | "
          "`gap_stages.py`, `link_catalogue.py --prompt_version v3` | `gap_runs/` |",
          "| D — licences, QA, freeze | `fetch_paper_licences.py`, `qa_catalogue_v3.py`, "
          "`build_catalogue_release.py` | this release |", "",
          "Every v2 record is accounted for in `provenance/_v2_to_v3_map.csv` (KEPT, "
          "MERGED_INTO, DUPLICATE_OF); folded records are in `provenance/_removed.jsonl`.", "",
          "## Columns to know", "",
          "- `*_normalized`, `*_ontology_id`: controlled values next to the original text (never replacing it).",
          "- `finding_source`, `cites_other_work`, `is_primary_finding` (+ `_source` RULE/LLM).",
          "- `direction_flag` / `direction_llm`: rule and model second opinions; `direction` itself is as extracted, spelling-normalised.",
          "- `count_flag`, `accession_valid`, `evidence_match`, `link_status`: why a value was changed or how reliable it is.",
          "- An empty cell means *not extracted*, not *absent from the paper*.", "",
          "## Verify", "", "```bash", "sha256sum -c MANIFEST.sha256", "```", ""]
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
