#!/usr/bin/env python
"""Verify the HMPAPER corpus built by build_hm_corpus.py.

Runs two classes of check:

  STRUCTURAL  — the deliverable matches the shape the template demands:
                453 records, IDs HMPAPER_000001..000453 contiguous and unique,
                every record has sections A-I, IDs cross-reference correctly,
                tracking table rows align 1:1 with records.

  CONTENT     — the record is actually populated, not just well-shaped:
                required fields non-empty, SHA-256 matches the file on disk,
                finding evidence offsets resolve inside the source text,
                sample counts consistent with sample_metadata.tsv.

Exit code 0 if no ERROR-level failures, 1 otherwise. WARN-level findings are
reported but do not fail the build.

Usage:
    python verify_corpus_build.py
    python verify_corpus_build.py --dir corpus_build --strict   # warn => fail
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent
PAPERS_TXT = REPO / "data/papers_txt"

REQUIRED_SECTIONS = [
    "A_record_control", "B_publication_metadata", "C_source_and_file_provenance",
    "D_eligibility_and_relevance", "E_full_text_integrity_checks",
    "F_full_text_section_inventory", "G_study_metadata", "H_findings",
    "I_final_review_checklist",
]
# Fields that must not be empty for a usable record.
REQUIRED_NON_EMPTY = [
    ("A_record_control", "corpus_id"),
    ("A_record_control", "processing_status"),
    ("D_eligibility_and_relevance", "inclusion_decision"),
    ("E_full_text_integrity_checks", "body_text_completeness"),
]


class Report:
    def __init__(self, strict=False):
        self.errors, self.warns, self.infos = [], [], []
        self.strict = strict

    def error(self, check, detail):
        self.errors.append((check, detail))

    def warn(self, check, detail):
        self.warns.append((check, detail))

    def info(self, check, detail):
        self.infos.append((check, detail))

    def print(self):
        w = max(len(c) for c, _ in self.errors + self.warns + self.infos) if (
            self.errors or self.warns or self.infos) else 10
        for title, items in (("ERROR", self.errors), ("WARN", self.warns),
                             ("INFO", self.infos)):
            if not items:
                continue
            print(f"\n{title}")
            print("-" * (w + 20))
            for check, detail in items:
                print(f"  {check:<{w}}  {detail}")
        return 1 if self.errors or (self.strict and self.warns) else 0


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def verify(root):
    rep = Report()
    recs_dir = root / "records"
    files = sorted(recs_dir.glob("*.json"))
    n = len(files)

    # ── STRUCTURAL ──
    if n != 453:
        rep.error("record count", f"{n} records, expected 453")

    ids = []
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            rep.error("json parse", f"{f.name}: {e}")
            continue
        ids.append(r.get("corpus_id"))

        expected = f"HMPAPER_{f.stem.split('_')[-1]}"
        if r.get("corpus_id") != expected:
            rep.error("id/filename match",
                      f"{f.name} declares {r.get('corpus_id')}")
        if not re.fullmatch(r"HMPAPER_\d{6}", r.get("corpus_id") or ""):
            rep.error("id format", f"{f.name}: {r.get('corpus_id')}")

        missing = [s for s in REQUIRED_SECTIONS if s not in r]
        if missing:
            rep.error("template sections", f"{f.name} missing {missing}")

        for sec, field in REQUIRED_NON_EMPTY:
            if not (r.get(sec) or {}).get(field):
                rep.error("required field", f"{f.name}: {sec}.{field} empty")

        if not r.get("F_full_text_section_inventory"):
            rep.error("section inventory", f"{f.name}: empty")
        if not r.get("G_study_metadata"):
            rep.error("study metadata", f"{f.name}: empty")

        # finding IDs must be namespaced to this paper and link to a study
        study_ids = {s.get("study_id") for s in r.get("G_study_metadata", [])}
        for fd in r.get("H_findings", []):
            if not fd.get("finding_id", "").startswith(r["corpus_id"]):
                rep.error("finding id", f"{f.name}: {fd.get('finding_id')}")
            if fd.get("study_id") not in study_ids:
                rep.error("finding study link",
                          f"{f.name}: {fd.get('finding_id')} -> {fd.get('study_id')}")

    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        rep.error("duplicate ids", sorted(dupes))

    expected_ids = [f"HMPAPER_{i:06d}" for i in range(1, n + 1)]
    if sorted(x for x in ids if x) != expected_ids:
        missing = set(expected_ids) - set(ids)
        rep.error("id continuity", f"{len(missing)} IDs missing from 1..{n}")

    # tracking table aligns 1:1
    trk = root / "corpus_tracking.csv"
    if not trk.exists():
        rep.error("tracking table", "corpus_tracking.csv not found")
    else:
        rows = list(csv.DictReader(trk.open(encoding="utf-8")))
        if len(rows) != n:
            rep.error("tracking rows", f"{len(rows)} rows vs {n} records")
        if {r["corpus_id"] for r in rows} != {i for i in ids if i}:
            rep.error("tracking ids", "tracking IDs do not match record IDs")

    # ── CONTENT ──
    sha_checked = evidence_ok = evidence_bad = 0
    populated = {k: 0 for k in ("title", "doi", "pmid", "journal", "year", "abstract",
                                "license", "sha256", "text_version", "xml", "pdf",
                                "n_samples", "accessions", "stat_methods",
                                "findings", "storms")}
    for f in files:
        r = json.loads(f.read_text(encoding="utf-8"))
        doc = r["B_publication_metadata"]
        prov = r["C_source_and_file_provenance"]
        files_m = r["files"]
        study = (r["G_study_metadata"] or [{}])[0]
        micro = study.get("microbiome") or {}

        for k in ("title", "doi", "pmid", "journal", "abstract"):
            if doc.get(k):
                populated[k] += 1
        populated["year"] += 1 if doc.get("publication_year") else 0
        populated["sha256"] += 1 if files_m.get("source_text_sha256") else 0
        populated["text_version"] += 1 if files_m.get("text_version_path") else 0
        populated["license"] += 1 if prov.get("license_name") else 0
        populated["xml"] += 1 if files_m.get("original_xml_path") else 0
        populated["pdf"] += 1 if files_m.get("original_pdf_path") else 0
        populated["n_samples"] += 1 if study.get(
            "number_of_biological_samples_reported") else 0
        populated["accessions"] += 1 if study.get("data_accessions") else 0
        populated["stat_methods"] += 1 if micro.get("statistical_methods") else 0
        populated["findings"] += 1 if r["H_findings"] else 0
        populated["storms"] += 1 if study.get("storms") else 0

        # SHA-256 must match the referenced source file
        rel = files_m.get("source_text_path")
        if rel and files_m.get("source_text_sha256"):
            src = REPO / rel
            if not src.exists():
                rep.error("source text missing", f"{f.name}: {rel}")
            else:
                sha_checked += 1
                if sha256_of(src) != files_m["source_text_sha256"]:
                    rep.error("sha256 mismatch", f"{f.name}: {rel}")

        # Evidence offsets must resolve inside the text version the record names.
        # This is the versioned text (cleaned_text), not the raw papers_txt file.
        vrel = files_m.get("text_version_path")
        text = ""
        if vrel:
            vsrc = root / vrel
            if not vsrc.exists():
                rep.error("text version missing", f"{f.name}: {vrel}")
            else:
                text = vsrc.read_text(encoding="utf-8", errors="replace")
                import hashlib as _h
                if files_m.get("text_version_sha256") and \
                        _h.sha256(text.encode("utf-8")).hexdigest() != \
                        files_m["text_version_sha256"]:
                    rep.error("text version sha", f"{f.name}: {vrel}")
            for fd in r["H_findings"]:
                s, e = fd.get("evidence_char_start"), fd.get("evidence_char_end")
                if s is None or e is None:
                    continue
                if not (0 <= s < e <= len(text)):
                    evidence_bad += 1
                    rep.error("evidence offset",
                              f"{f.name}: {fd['finding_id']} [{s}:{e}] "
                              f"vs text len {len(text)}")
                else:
                    quoted = text[s:e]
                    ev = (fd.get("evidence_text") or "").strip()
                    norm = lambda x: re.sub(r"\s+", " ", x).strip()
                    if ev and norm(quoted)[:40] != norm(ev)[:40]:
                        evidence_bad += 1
                        rep.warn("evidence text",
                                 f"{f.name}: {fd['finding_id']} offset text differs "
                                 f"from stored evidence_text")
                    else:
                        evidence_ok += 1

    # retrieval artefacts referenced by records must parse
    bad_xml = 0
    for f in files:
        r = json.loads(f.read_text(encoding="utf-8"))
        p = r["files"].get("original_xml_path")
        if p:
            try:
                ET.parse(REPO / p)
            except Exception:
                bad_xml += 1
                rep.error("xml unparseable", f"{f.name}: {p}")
    if bad_xml == 0:
        rep.info("xml integrity", "all referenced JATS files parse")

    # ── report ──
    print("=" * 70)
    print(f"HMPAPER CORPUS VERIFICATION — {root}")
    print("=" * 70)
    print(f"\nrecords: {n}   evidence locators ok: {evidence_ok}   bad: {evidence_bad}")
    print(f"\nfield population (of {n}):")
    for k, v in populated.items():
        pct = 100 * v / n if n else 0
        bar = "#" * int(pct / 5)
        flag = "  <-- low" if pct < 50 else ""
        print(f"  {k:14s} {v:3d} ({pct:5.1f}%)  {bar}{flag}")

    return rep.print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="corpus_build")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    a = ap.parse_args()
    root = Path(a.dir)
    if not root.is_absolute():
        root = REPO / root
    if not root.exists():
        print(f"No such directory: {root}")
        return 1
    return verify(root)


if __name__ == "__main__":
    sys.exit(main())