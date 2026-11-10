"""Read-only publication-readiness audit (2026-11-02).

Recomputes the project's headline numbers from the frozen release files, re-verifies every release
manifest, and runs regression checks for the bugs fixed in CDM 3.0.1 / 3.0.2 and terminology 1.0.1.
Writes only to --out (default outputs/audit/2026-11-02/); never modifies data or releases.

    python publication_audit.py [--out outputs/audit/2026-11-02]
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.2/microbiome_cdm_v3.db"
CAT = ROOT / "releases/data_catalogue_v3/3.1.1"
TERM = ROOT / "releases/terminology/1.0.1"
CORPUS = ROOT / "pipelines/corpus_v2/data"
COMP = ROOT / "data/168000-samples-paper"
GD = ROOT / "outputs/results/gap_runs"

F = {}          # fact id -> {value, source, method}
ISSUES = []     # unresolved issues


def fact(fid, value, source, method):
    F[fid] = {"value": value, "source": source, "method": method}
    print(f"  {fid}: {value}", flush=True)


def issue(iid, severity, release, title, evidence, impact, resolution, human):
    ISSUES.append({"id": iid, "severity": severity, "affected_release": release, "title": title,
                   "evidence": evidence, "scientific_impact": impact, "recommended_resolution": resolution,
                   "human_intervention_required": human})


def jl(p):
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT))


# ── A. corpus ────────────────────────────────────────────────────────────────
def corpus():
    print("A corpus")
    papers = list(jl(CORPUS / "papers.jsonl"))
    fact("A.papers", len(papers), rel(CORPUS / "papers.jsonl"), "row count")
    fact("A.papers_distinct_id", len({p["paper_id"] for p in papers}), rel(CORPUS / "papers.jsonl"), "distinct paper_id")
    secs = list(jl(CORPUS / "sections.jsonl"))
    fact("A.sections", len(secs), rel(CORPUS / "sections.jsonl"), "row count")
    fact("A.papers_with_sections", len({s["paper_id"] for s in secs}), rel(CORPUS / "sections.jsonl"), "distinct paper_id")
    bad = sum(1 for s in secs if s.get("text_hash_sha256") and
              hashlib.sha256((s.get("section_text_original") or "").encode("utf-8")).hexdigest() != s["text_hash_sha256"])
    hashed = sum(1 for s in secs if s.get("text_hash_sha256"))
    fact("A.section_hash_mismatch", f"{bad}/{hashed}", rel(CORPUS / "sections.jsonl"),
         "sha256(section_text_original) vs text_hash_sha256")
    if bad:
        issue("A1", "major", "corpus_v2", "Section text hashes do not match stored sha256",
              f"{bad} of {hashed} sections", "Text may have changed after hashing; provenance claim weakened",
              "Identify the hashing convention (normalisation/encoding) or re-hash in a new corpus release", "no")
    st = Counter(s.get("section_type") for s in secs)
    fact("A.section_types", dict(st), rel(CORPUS / "sections.jsonl"), "count by section_type")
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    bps = [r[0] for r in c.execute("SELECT bioproject FROM paper")]
    fact("A.paper_bioprojects_distinct", len(set(b for b in bps if b)), rel(CDM), "distinct paper.bioproject")
    fact("A.publications_distinct", c.execute("SELECT COUNT(*) FROM publication").fetchone()[0], rel(CDM),
         "publication rows (DOI / PMID / paper)")
    fact("A.publications_shared_by_bioprojects",
         c.execute("SELECT COUNT(*), SUM(n_bioprojects) FROM publication WHERE n_bioprojects > 1").fetchone(), rel(CDM),
         "publications with >1 BioProject (count, BioProjects involved)")
    # recompute the linked-sample number from the compendium itself, not from the CDM
    bpset = set(bps)
    n_s, projs = 0, set()
    with open(COMP / "sample_metadata.tsv", encoding="utf-8") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        tot = 0
        for r in rd:
            tot += 1
            if r["project"] in bpset:
                n_s += 1
                projs.add(r["project"])
    fact("A.compendium_samples_total", tot, rel(COMP / "sample_metadata.tsv"), "row count")
    fact("A.compendium_samples_linked", n_s, rel(COMP / "sample_metadata.tsv"), "rows whose project is a corpus BioProject")
    fact("A.compendium_projects_linked", len(projs), rel(COMP / "sample_metadata.tsv"), "distinct linked projects")
    miss = sorted(bpset - projs - {None, ""})
    fact("A.bioprojects_without_compendium_samples", miss, rel(CDM), "corpus BioProjects absent from sample_metadata")
    issue("A2", "minor", "manuscript", "Precise sample-linkage wording required",
          f"{n_s:,} of {tot:,} compendium samples belong to corpus BioProjects ({len(projs)} projects)",
          "Implying all ~168k samples are linked would overstate the resource",
          "State the exact linked count and that links are at BioProject level, not per sample", "no")


# ── manifests ────────────────────────────────────────────────────────────────
def manifests():
    print("manifests")
    out = []
    for m in sorted(ROOT.glob("releases/**/MANIFEST.sha256")):
        r = subprocess.run(["sha256sum", "-c", "--quiet", m.name], cwd=m.parent, capture_output=True, text=True)
        n = sum(1 for _ in open(m))
        out.append({"manifest": rel(m), "files": n, "ok": r.returncode == 0,
                    "failures": [l for l in (r.stdout + r.stderr).splitlines() if "FAILED" in l or "No such" in l][:10]})
        print(f"  {rel(m)}: {'OK' if r.returncode == 0 else 'FAIL'}", flush=True)
    fact("R.manifests", {o["manifest"]: ("OK" if o["ok"] else f"FAIL {o['failures'][:3]}") for o in out},
         "releases/**/MANIFEST.sha256", "sha256sum -c")
    for o in out:
        if not o["ok"]:
            issue(f"R-{o['manifest']}", "critical", o["manifest"], "Release manifest verification failed",
                  "; ".join(o["failures"][:5]), "Frozen release integrity cannot be asserted",
                  "Investigate missing/changed files; never edit in place — issue a new version", "no")
    return out


# ── B. terminology ───────────────────────────────────────────────────────────
def terminology():
    print("B terminology")
    rows, keys, link, off = 0, set(), Counter(), Counter()
    for m in jl(TERM / "term_mentions.jsonl"):
        rows += 1
        keys.add(f"{m['mention_id']}|{m.get('extraction_model')}")
        link[m.get("term_link_status")] += 1
        off[m.get("offset_status")] += 1
    fact("B.mentions_rows", rows, rel(TERM / "term_mentions.jsonl"), "row count")
    fact("B.mentions_distinct_id_model", len(keys), rel(TERM / "term_mentions.jsonl"), "distinct mention_id|model")
    fact("B.mention_link_status", dict(link), rel(TERM / "term_mentions.jsonl"), "term_link_status counts")
    fact("B.mention_offset_status", dict(off), rel(TERM / "term_mentions.jsonl"), "offset_status counts")
    terms = sum(1 for _ in jl(TERM / "canonical_terms.jsonl"))
    fact("B.canonical_terms_release", terms, rel(TERM / "canonical_terms.jsonl"), "row count")
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    q = lambda s: c.execute(s).fetchall()
    fact("B.canonical_terms_cdm", q("SELECT COUNT(*) FROM canonical_term")[0][0], rel(CDM), "canonical_term rows (after DeepSeek review)")
    fact("B.removed_terms_cdm", q("SELECT COUNT(*) FROM removed_canonical_term")[0][0], rel(CDM), "removed_canonical_term rows")
    fact("B.term_types", dict(q("SELECT cdm_type, COUNT(*) FROM canonical_term GROUP BY 1 ORDER BY 2 DESC")), rel(CDM), "cdm_type counts")
    fact("B.mapping_rows", q("SELECT COUNT(*) FROM term_concept_map")[0][0], rel(CDM), "term_concept_map rows")
    fact("B.mapping_guard_status", dict(q("SELECT guard_status, COUNT(*) FROM term_concept_map GROUP BY 1")), rel(CDM), "guard_status")
    fact("B.mapping_disposition", dict(q("SELECT COALESCE(mapping_disposition,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1")), rel(CDM), "mapping_disposition")
    fact("B.mapping_reviewed_disposition", dict(q("SELECT COALESCE(mapping_disposition_reviewed,'(not reviewed)'), COUNT(*) FROM term_concept_map GROUP BY 1")), rel(CDM), "mapping_disposition_reviewed")
    fact("B.terms_with_any_kept_mapping", q("SELECT COUNT(DISTINCT term_id) FROM term_concept_map WHERE guard_status='kept' AND concept_id IS NOT NULL")[0][0], rel(CDM), "distinct terms with a kept mapping to a concept")
    fact("B.terms_with_accepted_mapping", q("SELECT COUNT(DISTINCT term_id) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'")[0][0], rel(CDM), "distinct terms with a two-model-accepted mapping")
    fact("B.definitions", q("SELECT COUNT(*), COUNT(DISTINCT term_id) FROM term_definition")[0], rel(CDM), "definitions, distinct terms")
    fact("B.taxonomy_status", dict(q("SELECT agreement_status, COUNT(*) FROM taxonomy_annotation GROUP BY 1")), rel(CDM), "taxonomy agreement_status")
    fact("B.relations", q("SELECT COUNT(*) FROM relation")[0][0], rel(CDM), "relation rows")
    fact("B.relation_link_status", dict(q("SELECT subject_link_status||'/'||object_link_status, COUNT(*) FROM relation GROUP BY 1 ORDER BY 2 DESC LIMIT 6")), rel(CDM), "subject/object link status")
    issue("B1", "major", "terminology 1.0.1 / CDM 3.0.2", "No human-verified accuracy for terms, types, mappings or definitions",
          "All term-level verdicts come from Gemma / DeepSeek / Qwen; human_review table empty",
          "Precision of the terminology layer is unknown", "Stratified human validation (Gate 4)", "yes")
    tx = dict(q("SELECT agreement_status, COUNT(*) FROM taxonomy_annotation GROUP BY 1"))
    issue("B2", "major", "CDM 3.0.2", "Taxonomy covers a minority of terms",
          f"AGREED+PARENT_AGREED = {tx.get('AGREED', 0) + tx.get('PARENT_AGREED', 0):,} of {sum(tx.values()):,}",
          "Taxonomy-based browsing/statistics would be incomplete", "Report as partial; prune junk terms; human sample", "partly")
    issue("B3", "major", "CDM 3.0.2", "Most ontology mappings remain unadjudicated",
          json.dumps(dict(q("SELECT COALESCE(mapping_disposition_reviewed,'(not reviewed)'), COUNT(*) FROM term_concept_map GROUP BY 1"))),
          "Mapping-based normalisation claims must be limited to the accepted subset",
          "Report accepted subset separately; human-validate a stratified mapping sample", "yes")


# ── C. catalogue ─────────────────────────────────────────────────────────────
def catalogue():
    print("C catalogue")
    recs = list(jl(CAT / "catalogue_records.jsonl")) if (CAT / "catalogue_records.jsonl").exists() else []
    if not recs:
        files = sorted(glob.glob(str(CAT / "**/*.jsonl"), recursive=True))
        fact("C.files", [rel(f) for f in files], rel(CAT), "listing")
        recs = list(jl(next(f for f in files if "records" in f)))
    fact("C.records", len(recs), rel(CAT), "catalogue_records rows")
    fact("C.records_by_entity", dict(Counter(r["entity_type"] for r in recs)), rel(CAT), "entity_type counts")
    fact("C.papers_in_records", len({r["fields"].get("paper_id") or r.get("paper_id") for r in recs}), rel(CAT), "distinct paper_id")
    qa = next(iter(glob.glob(str(CAT / "**/qa_report.json"), recursive=True)), None)
    if qa:
        q = json.load(open(qa))
        fact("C.qa_verdict", {"verdict": q.get("verdict"), "checks": q.get("checks")}, rel(qa), "release QA report")
    vals, missing = Counter(), Counter()
    for r in recs:
        for k, v in r["fields"].items():
            if v in ("NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING"):
                missing[v] += 1
        for k, v in (r["fields"].get("field_sources") or {}).items() if isinstance(r["fields"].get("field_sources"), dict) else []:
            vals[v] += 1
    fact("C.missing_codes", dict(missing), rel(CAT), "field values equal to a missing-data code")
    fact("C.field_sources", dict(vals.most_common(12)), rel(CAT), "field_sources provenance values")
    for name, p in (("G1 report", GD / "G1/catalogue/_G1_report.json"), ("G3 report", GD / "G3/catalogue/_G3_report.json"),
                    ("finalize report", ROOT / "outputs/results/catalogue_v3_1_pre_vocab/_finalize_report.json")):
        if p.exists():
            fact(f"C.{name}", json.load(open(p)), rel(p), "stage report")
    rm = list(glob.glob(str(GD / "G3/catalogue/*removed*"))) + list(glob.glob(str(CAT / "**/*removed*"), recursive=True))
    fact("C.removed_files", [rel(x) for x in rm], "gap_runs/G3 + release", "listing")
    n_rm = 0
    for x in rm:
        if x.endswith(".jsonl"):
            n_rm = max(n_rm, sum(1 for _ in open(x)))
    fact("C.removed_records_traceable", n_rm, ";".join(rel(x) for x in rm), "rows in removed-record file(s)")
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    anc = Counter()
    for t in ("claim", "cohort", "sample", "assay", "dataset", "data_asset"):
        w = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
        for s, n in c.execute(f"SELECT COALESCE(evidence_anchor_status,'(null)'), COUNT(*) FROM {t}{w} GROUP BY 1"):
            anc[s] += n
    fact("C.quote_anchor_status", dict(anc), rel(CDM), "evidence_anchor_status over the six catalogue tables")
    verb = sum(anc[k] for k in ("EXACT", "WHITESPACE", "RELOCATED", "NORMALISED"))
    fact("C.quote_verbatim_pct", round(100 * verb / sum(anc.values()), 1), rel(CDM),
         "EXACT+WHITESPACE+RELOCATED+NORMALISED / all records — quotation matching, not factual accuracy")
    issue("C1", "critical", "catalogue 3.1.1", "No human validation of catalogue facts",
          "Only model judges (Gemma G10; Claude 400-sample on v3.0)", "Accuracy of the central resource is unestablished",
          "Gate 4: 200-record stratified human sample, two annotators, adjudication", "yes")
    issue("C2", "major", "catalogue 3.1.1", "Quote match does not imply the quote supports the value",
          f"{F['C.quote_verbatim_pct']['value']}% verbatim; support not assessed by a human",
          "Reporting 88% as accuracy would be misleading", "Report as quotation matching; assess support in Gate 4", "yes")
    issue("C3", "major", "catalogue 3.1.1", "NOT_REPORTED codes unverified",
          f"{missing.get('NOT_REPORTED', 0):,} NOT_REPORTED values", "False NOT_REPORTED hides real data",
          "Include NOT_REPORTED fields in the human sample (check the paper truly lacks the value)", "yes")


# ── D. CDM regression tests ──────────────────────────────────────────────────
def cdm(term_rows):
    print("D CDM")
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    q = lambda s: c.execute(s).fetchall()
    fact("D.entity_status", dict(q("SELECT status, COUNT(*) FROM cdm_entity_status GROUP BY 1")), rel(CDM), "cdm_entity_status")
    fact("D.entity_empty", q("SELECT entity, status FROM cdm_entity_status WHERE status NOT IN ('POPULATED','EMBEDDED')"), rel(CDM), "non-populated entities")
    fact("D.load_audit_dropped", q("SELECT \"table\", rows_offered, rows_kept, rows_dropped FROM load_audit WHERE rows_dropped > 0"), rel(CDM), "load_audit")
    n = q("SELECT COUNT(*) FROM term_mention")[0][0]
    t1 = n == term_rows - 51
    fact("D.REG1_lost_mentions", {"cdm_rows": n, "release_rows": term_rows, "expected_dropped_identical": 51, "pass": t1},
         rel(CDM), "term_mention rows == release rows minus 51 byte-identical duplicates")
    # REG2: reviewed verdicts attached only to matching (mapping_id, term_id, concept_id)
    ds = {}
    p = ROOT / "outputs/results/deepseek_review/corrected/term_concept_map.reviewed.jsonl"
    for r in jl(p):
        ds[(r["mapping_id"], r["term_id"], r.get("concept_id"))] = r.get("relation_deepseek")
    bad = tot = 0
    for mid, tid, cid, rd in c.execute("SELECT mapping_id, term_id, concept_id, relation_deepseek FROM term_concept_map "
                                       "WHERE relation_deepseek IS NOT NULL"):
        tot += 1
        bad += (mid, tid, cid) not in ds or ds[(mid, tid, cid)] != rd
    fact("D.REG2_mapping_verdicts", {"rows_with_verdict": tot, "mismatched": bad, "pass": bad == 0}, rel(CDM),
         "every DeepSeek verdict matches the reviewed record with the same (mapping_id, term_id, concept_id)")
    # REG3: mention -> canonical links
    lk = dict(q("SELECT term_link_status, COUNT(*) FROM term_mention GROUP BY 1"))
    nulls_linked = q("SELECT COUNT(*) FROM term_mention WHERE term_link_status IN ('LINKED','LINKED_BY_TYPE') AND canonical_term_id IS NULL")[0][0]
    fact("D.REG3_canonical_links", {"status": lk, "linked_but_null": nulls_linked, "pass": nulls_linked == 0 and "LINKED" in lk},
         rel(CDM), "term_link_status distribution; no LINKED row without an id")
    # REG4: offsets — exhaustive check of all mentions
    sec = {(p, s): t for p, s, t in c.execute("SELECT paper_id, section_id_original, section_text_original FROM section")}
    ok = badn = miss = 0
    for pid, sid, a, b, sf in c.execute("SELECT paper_id, section_id, start_offset, end_offset, surface_form FROM term_mention"):
        t = sec.get((pid, sid))
        if t is None or a is None:
            miss += 1
        elif t[a:b] == sf:
            ok += 1
        else:
            badn += 1
    fact("D.REG4_offsets", {"exact": ok, "mismatch": badn, "no_section_or_offset": miss,
                            "exact_pct": round(100 * ok / max(1, ok + badn), 3), "pass": badn <= 100},
         rel(CDM), "ALL term_mention rows: section_text[start:end] == surface_form")
    for k in ("D.REG1_lost_mentions", "D.REG2_mapping_verdicts", "D.REG3_canonical_links", "D.REG4_offsets"):
        if not F[k]["value"]["pass"]:
            issue(k, "critical", "CDM 3.0.2", f"Regression check failed: {k}", json.dumps(F[k]["value"]),
                  "A previously fixed integrity bug is present", "Fix in a new release", "no")
    rem = q("SELECT COUNT(*) FROM term_mention WHERE canonical_term_status != ''")[0][0]
    fact("D.mentions_pointing_removed_or_unknown", rem, rel(CDM), "term_mention.canonical_term_status flagged")
    dangling = q("SELECT COUNT(*) FROM relation WHERE subject_term_id != '' AND subject_term_id NOT IN (SELECT term_id FROM canonical_term)")[0][0]
    fact("D.relation_dangling_subject", dangling, rel(CDM), "relation.subject_term_id not in canonical_term")
    qa = json.load(open(ROOT / "releases/cdm_v3/3.0.2/qa_cdm_report.json"))
    fact("D.cdm_qa", {"verdict": qa["verdict"], "fails": qa["fails"], "warnings": qa["warnings"]},
         "releases/cdm_v3/3.0.2/qa_cdm_report.json", "release QA")
    issue("D1", "minor", "CDM 3.0.2", "HUMAN_REVIEW entity empty", "cdm_entity_status = EMPTY_NO_HUMAN_REVIEW_YET",
          "Template rule: only humans set ACCEPTED", "Populate from Gate 4 results in a new release", "yes")
    issue("D2", "major", "CDM 3.0.2", "No external usability test of the CDM",
          "No documented end-user queries verified against papers", "Utility claim unsupported",
          "Gate 5: 3-5 research queries, results checked against papers", "yes")


# ── E. evaluation ────────────────────────────────────────────────────────────
def evaluation():
    print("E evaluation")
    v, st = Counter(), Counter()
    for p in sorted(glob.glob(str(GD / "G10/C1_part*_verdicts.jsonl"))):
        for r in jl(p):
            st["rows"] += 1
            v[str(r.get("verdict") or r.get("label") or r.get("C1") or r.get("decision") or "?").upper()] += 1
    fact("E.G10_verdicts", dict(v), "outputs/results/gap_runs/G10/C1_part*_verdicts.jsonl", "verdict counts")
    md = GD / "G10/JUDGE_METRICS_V3_1.md"
    if md.exists():
        m = re.search(r"([0-9]{2}\.[0-9])\s*%", md.read_text())
        fact("E.G10_reported", m.group(0) if m else None, rel(md), "first percentage in the metrics report")
    sc = ROOT / "outputs/results/catalogue_v3_validation/validation_scores.json"
    if sc.exists():
        fact("E.claude400", json.load(open(sc)), rel(sc), "scores file of the 400-record LLM-judge evaluation")
    rep = ROOT / "outputs/results/catalogue_v3_validation/EVALUATION_REPORT.md"
    if rep.exists():
        head = rep.read_text()[:1500]
        fact("E.claude400_report_head", head.splitlines()[:12], rel(rep), "report header (release + judge identity)")
    issue("E1", "critical", "manuscript", "The 59% figure is an LLM-judge result, not a manual evaluation",
          "Claude Opus 5.5 scored 400 v3.0 records", "Calling it manual/human would misrepresent the validation",
          "Label as LLM-judge; obtain a human evaluation on the final release", "yes")
    issue("E2", "major", "catalogue 3.0 vs 3.1.1", "Model-judge results refer to different releases and rubrics",
          "G10 = Gemma, lenient C1, all v3.1 records; Claude = strict, 400 sampled v3.0 records",
          "92.2% and 59% are not comparable", "Re-score the same 400 records on 3.1.1 with the strict rubric; report both with definitions", "no")
    meta = {}
    for p in sorted(glob.glob(str(ROOT / "outputs/results/ner_fair_bench/preds/*.jsonl"))):
        ds, name = Path(p).stem.split("__", 1)
        meta.setdefault(name, []).append(ds)
    llm = sorted({n.rsplit("_", 1)[0] for n in meta if n.startswith("llm_")})
    non = sorted(n for n in meta if not n.startswith("llm_"))
    fact("E.benchmark_models", {"non_llm": non, "n_non_llm": len(non), "llms": llm, "n_llm": len(llm),
                                "configurations": len(meta), "datasets_per_config": {k: sorted(v) for k, v in meta.items()}},
         "outputs/results/ner_fair_bench/preds/", "files present")


# ── F. readiness ─────────────────────────────────────────────────────────────
def readiness():
    print("F readiness")
    lic = ROOT / "outputs/results/catalogue_v3_licences/paper_licences.csv"
    if lic.exists():
        rows = list(csv.DictReader(open(lic, encoding="utf-8")))
        fact("F.licences", dict(Counter((r.get("license") or "(none)") for r in rows).most_common(10)), rel(lic), "licence counts")
        open_ = sum(1 for r in rows if re.search(r"cc[- ]?by|cc0|public", (r.get("license") or "").lower()))
        fact("F.open_licence_papers", f"{open_}/{len(rows)}", rel(lic), "licence matches CC-BY*/CC0/public")
        issue("F1", "critical", "public release", "Full-text redistribution rights",
              f"{open_}/{len(rows)} papers carry an open licence", "Releasing non-OA full text/section text breaches copyright",
              "Release section text only for open-licence papers; elsewhere quotes + offsets/hashes", "yes")
    ms = ROOT / "paper/manuscript/manuscript.md"
    if ms.exists():
        t = ms.read_text()
        fact("F.manuscript_counts", {k: len(re.findall(k, t)) for k in ("444", "452", "453", "1,200", "100% ")}, rel(ms),
             "occurrences of corpus-size and suspect strings")
        issue("F2", "major", "manuscript", "Manuscript reflects superseded builds and claims",
              json.dumps(F["F.manuscript_counts"]["value"]),
              "Numbers (444/452 papers, BioRED 1,200 test docs, Claim F 100%) contradict the final release",
              "Rewrite against the frozen releases; reframe Claims C/D/F", "no")
    zen = list(ROOT.glob("releases/zenodo_v1/**/*"))
    fact("F.zenodo_dir_files", len(zen), "releases/zenodo_v1", "file count (local staging only; no DOI evidence)")
    issue("F3", "major", "public release", "No public DOI deposit", "No DOI recorded for the v3 releases",
          "Data availability statement cannot be satisfied", "Deposit CDM 3.0.2 + catalogue 3.1.1 + terminology 1.0.1 on Zenodo", "yes")


def regression(cdm_path, term_rows):
    """REG1-REG4 only, against any CDM build (used for release candidates)."""
    global CDM
    CDM = Path(cdm_path)
    cdm(term_rows)
    return {k: F[k]["value"] for k in F if k.startswith("D.REG")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "outputs/audit/2026-11-02"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    corpus()
    man = manifests()
    terminology()
    catalogue()
    cdm(F["B.mentions_rows"]["value"])
    evaluation()
    readiness()
    (out / "audit_facts.json").write_text(json.dumps({"facts": F, "manifests": man}, indent=1, default=str) + "\n")
    with open(out / "UNRESOLVED_ISSUES.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ISSUES[0]))
        w.writeheader()
        w.writerows(ISSUES)
    print(f"{len(F)} facts, {len(ISSUES)} issues -> {out}")


if __name__ == "__main__":
    raise SystemExit(main())
