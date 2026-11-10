"""CDM 3.0.3 release candidate: additive remediation of CDM 3.0.2 (no data regeneration).

Copies releases/cdm_v3/3.0.2/microbiome_cdm_v3.db and applies only ADDITIVE changes, each logged in the new
table `cdm_change_log` and reversed by the generated REVERT_303.sql:

  R1  register every extraction run named by a row, with its verifiable evidence (code, file hash, job log);
      runs that cannot be verified are registered as UNAVAILABLE, never invented
  R2  run columns for tables that had none (relation, taxonomy_annotation, term_concept_map, type_harmonization)
      and a recovered run + status for corpus claims (original column untouched)
  R3  mapping evidence restored into TERM_CONCEPT_MAP from the frozen guard files (matched by row order and
      verified on mapping_id + term_id + concept_id)
  R4  section_text_sha256 (text-version reference) on every offset-bearing table
  R5  study_id derived through PAPER (one study per paper, verified) on cohort / sample / assay / dataset /
      data_asset, and study_id_derived on catalogue claims
  R6  unique indexes enforcing the implemented primary keys that the database did not declare
  R7  RELATION_EVIDENCE: triple mentions anchored to exact section offsets
  R8  canonical_term.has_linked_mention + identifier_crosswalk; run_metadata version keys

Nothing in an existing column or row is modified except run_metadata.cdm_version (documented).

    python migrate_303.py [--out outputs/results/cdm_v3_3.0.3_rc1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/vllm_termpop"))
from build_cdm_v3 import _alnum  # noqa: E402  (same normalisation as the catalogue quote anchoring)

SRC = ROOT / "releases/cdm_v3/3.0.2/microbiome_cdm_v3.db"
GUARDS = ROOT / "releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2"
CORPUS = ROOT / "pipelines/corpus_v2"
TERM_PROV = ROOT / "releases/terminology/1.0.0/PROVENANCE.json"
LOGS = ROOT / "outputs/logs/gap"
VERSION = "3.0.3-rc1"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def anchor_sentence(text, s):
    """Locate a sentence without offsets: EXACT | WHITESPACE | NORMALISED | UNANCHORED (no fuzzy matching:
    without offsets it would search whole sections, and an approximate span would be a guess)."""
    if not text or not s:
        return ("NO_SECTION" if not text else "NO_SENTENCE"), None, None
    i = text.find(s)
    if i >= 0:
        return "EXACT", i, i + len(s)
    import re
    mm = re.search(r"\s+".join(map(re.escape, s.split())), text)
    if mm:
        return "WHITESPACE", mm.start(), mm.end()
    tq, _ = _alnum(s)
    tt, ix = _alnum(text)
    j = tt.find(tq) if tq else -1
    if j >= 0:
        return "NORMALISED", ix[j], ix[j + len(tq) - 1] + 1
    return "UNANCHORED", None, None


def jl(p):
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


class M:
    def __init__(self, db):
        self.c = sqlite3.connect(db)
        self.c.execute("PRAGMA journal_mode=OFF")
        self.c.execute("PRAGMA synchronous=OFF")
        self.c.execute("CREATE TABLE cdm_change_log (step, kind, target, description, rows_affected, revert_sql)")
        self.revert = []

    def log(self, step, kind, target, desc, rows, revert):
        self.c.execute("INSERT INTO cdm_change_log VALUES (?,?,?,?,?,?)", (step, kind, target, desc, rows, revert))
        self.revert.append(revert)
        print(f"  {step} {kind} {target}: {rows}", flush=True)

    def add_col(self, step, t, col, desc):
        self.c.execute(f'ALTER TABLE "{t}" ADD COLUMN "{col}"')
        self.log(step, "ADD_COLUMN", f"{t}.{col}", desc, 0, f'ALTER TABLE "{t}" DROP COLUMN "{col}";')

    def cols(self, t):
        return [r[1] for r in self.c.execute(f'PRAGMA table_info("{t}")')]


def job_done(jobid, pattern="*"):
    """'== done <date>' line of a gap/ds job log, if present."""
    for p in sorted(LOGS.glob(f"{pattern}{jobid}*.out")):
        for line in open(p, encoding="utf-8", errors="replace"):
            if line.startswith("== done"):
                return line.strip()[8:]
    return None


def mtime(p):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p))) if Path(p).exists() else None


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    db = out / "microbiome_cdm_v3.db"
    if db.exists():
        raise SystemExit(f"{db} exists; choose a new rc folder")
    src_hash = sha256_file(SRC)
    shutil.copyfile(SRC, db)
    assert sha256_file(db) == src_hash, "copy differs from 3.0.2"
    m = M(db)
    c = m.c

    # ── R1 runs ──────────────────────────────────────────────────────────────
    print("R1 extraction runs")
    for col, d in (("run_kind", "what produced the rows: NER source / LLM stage / deterministic stage / build"),
                   ("source_artifact", "file the run produced or the rows were loaded from"),
                   ("source_artifact_sha256", "sha256 of source_artifact as recorded in an existing manifest"),
                   ("job_ids", "SLURM job id(s) that executed the run, if verifiable"),
                   ("completed_at", "completion time from the job log or run event"),
                   ("model_name_version", "model and version used, if any"),
                   ("prompt_version", "prompt version used, if any"),
                   ("provenance_evidence", "where each recorded fact comes from"),
                   ("verification", "VERIFIED_LOG | VERIFIED_CODE_AND_HASH | VERIFIED_RUN_EVENT | RECORDED_IN_DATA | UNAVAILABLE"),
                   ("stage_corrected", "corrected stage label where the 3.0.2 label was wrong (3.0.2 'stage' kept)")):
        m.add_col("R1", "extraction_run", col, d)
    prov = json.loads(TERM_PROV.read_text())["sources"]
    term_runs = [  # assemble_mentions.py SOURCES registry: name -> (path, method, run id)
        ("cpu_ensemble_v1", "cpu_ensemble_ner", "ner_model_ensemble (7 CPU NER models, zenodo_v1 section run)", None),
        ("qwen_ollama_cell7c_v1", "qwen_ollama_ner", "llm_section_ner (Qwen via Ollama, notebook cell 7c)", "qwen3.5 (ollama)"),
        ("qwen35_vllm_body_v1", "qwen_vllm_body_ner", "llm_section_ner (Qwen3.5 via vLLM, body sections)", "qwen3.5:4b (vllm)"),
        ("mesh_gazetteer_2026", "mesh_gazetteer", "gazetteer_dictionary_match (MeSH 2026)", None)]
    new_runs = []
    for rid, key, kind, model in term_runs:
        s = prov[key]
        jobs = "28607825" if rid == "qwen35_vllm_body_v1" else None   # template §5 run inventory (llm-ner-body)
        new_runs.append((rid, "terminology source run", model, kind, s["path"], s["sha256"], jobs, None, model, None,
                         "run id + method: src/scripts/termpipeline/assemble_mentions.py SOURCES; path + sha256: "
                         "releases/terminology/1.0.0/PROVENANCE.json sources" + ("; job id: template §5 run inventory" if jobs else
                                                                                   "; job id not recorded anywhere"),
                         "VERIFIED_CODE_AND_HASH", None))
    new_runs.append(("termpipeline_t3_rules_v1", "terminology definitions (rule patterns)", None, "deterministic stage (rule_pattern)",
                     "releases/terminology/1.0.0/term_definitions.jsonl",
                     json.loads(TERM_PROV.read_text())["artifacts"]["term_definitions.jsonl"], "28619916", None, None, None,
                     "run id: src/pipeline/s05_terminology/extract_definitions.py; artifact sha256 + job 28619916: terminology 1.0.0 PROVENANCE.json",
                     "VERIFIED_CODE_AND_HASH", None))
    g8_done = job_done("28671788")
    new_runs.append(("gap G8", "gap G8 definitions (label used by the 3.0.x builder)", "Qwen/Qwen3.5-4B", "LLM stage",
                     "outputs/results/gap_runs/G8/term_definitions_llm.jsonl", None, "28671784 (generation, 3 shards); 28671788 (apply)",
                     g8_done, "Qwen/Qwen3.5-4B", None,
                     f"shard logs gap-G8_28671784_[0-2].out end at the mtimes of responses.shard[0-2].jsonl; apply log 28671788 done {g8_done}",
                     "VERIFIED_LOG", None))
    ev = {e["run_id"]: e for e in jl(CORPUS / "data/processing_events.jsonl")}
    s52 = [e for k, e in ev.items() if k.startswith("stage52_findings_extract")]
    assert len(s52) == 1, f"expected one stage-52 run, found {len(s52)}"
    e52 = s52[0]
    new_runs.append((e52["run_id"], "corpus stage 52 findings extraction", e52.get("model_name_version"), "LLM stage",
                     "pipelines/corpus_v2/checkpoints/stage52_findings_extract.jsonl", None, None, e52.get("completed_at"),
                     e52.get("model_name_version"), e52.get("prompt_version"),
                     f"run event in pipelines/corpus_v2/data/processing_events.jsonl (status {e52.get('run_status')}); "
                     f"its output_artifact_hash matches no current file", "VERIFIED_RUN_EVENT", None))
    for k, e in ev.items():
        if k.startswith("stage53_triples_extract"):
            new_runs.append((k, "corpus stage 53 triples extraction", e.get("model_name_version"), "LLM stage" if e.get("model_name_version") else "merge",
                             "pipelines/corpus_v2/data/triple_mentions.jsonl", None, None, e.get("completed_at"),
                             e.get("model_name_version"), e.get("prompt_version"), "run event in processing_events.jsonl",
                             "VERIFIED_RUN_EVENT", None))
    new_runs.append(("stage53_triples_extract@2.1.0", "corpus stage 53 triples (label carried by every triple mention)", "qwen3.5:4b",
                     "LLM stage", "pipelines/corpus_v2/data/triple_mentions.jsonl", None, None, None, "qwen3.5:4b", None,
                     "label in triple_mentions.extraction_run_id; executed by the stage53_triples_extract-s0/-s1/-merge run events",
                     "RECORDED_IN_DATA", None))
    new_runs.append(("CATCLEAN_20261030T173958", "catalogue phase A cleanup (id as recorded on records)", None, "deterministic stage",
                     "releases/data_catalogue_v3/3.1.1/records/catalogue_records.jsonl", None, None, None, None, None,
                     "clean_run_id on catalogue 3.1.1 records; no job log references this id; probably the run labelled "
                     "CATCLEAN_v3 in 3.0.2 (not verifiable)", "RECORDED_IN_DATA", None))
    gs = json.loads((GUARDS / "guard_summary.json").read_text())
    new_runs.append(("mapping_guards_v2", "terminology mapping guards v2", None, "deterministic stage",
                     str(GUARDS.relative_to(ROOT)), sha256_file(GUARDS / "mapping_remapped.jsonl"), None, gs.get("generated_at"),
                     None, None, "guard_summary.json generated_at; sha256 of mapping_remapped.jsonl computed now; no job id recorded",
                     "RECORDED_IN_DATA", None))
    for rid, stage, jobs, outp in (("gap G7 apply", "G7 type harmonisation", "28671787 (Gemma); 28671791 (apply)", "outputs/results/gap_runs/G7/type_harmonization.jsonl"),
                                   ("gap G9 apply", "G9 mapping adjudication", "28671785 (Gemma); 28671789 (apply)", "outputs/results/gap_runs/G9/mapping_adjudication.jsonl"),
                                   ("gap G11 apply", "G11 term taxonomy", "28674575 (Qwen); 28674576 (Gemma); 28674577 (apply)", "outputs/results/gap_runs/G11/term_taxonomy.jsonl"),
                                   ("deepseek_review apply", "DeepSeek-R1 review", "28672565 (review); 28672567 (apply)", "outputs/results/deepseek_review/corrected")):
        apply_job = jobs.split(";")[-1].split()[0]
        done = job_done(apply_job)
        new_runs.append((rid, stage, None, "LLM stage", outp, None, jobs, done, None, None,
                         f"apply job {apply_job} log done {done}; output mtime {mtime(ROOT / outp)}", "VERIFIED_LOG", None))
    existing = {r[0] for r in c.execute("SELECT extraction_run_id FROM extraction_run")}
    rows = [r for r in new_runs if r[0] not in existing]
    c.executemany("INSERT INTO extraction_run (extraction_run_id, stage, model, run_kind, source_artifact, source_artifact_sha256, "
                  "job_ids, completed_at, model_name_version, prompt_version, provenance_evidence, verification, stage_corrected) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    m.log("R1", "INSERT_ROWS", "extraction_run", "runs referenced by rows but absent from EXTRACTION_RUN", len(rows),
          "DELETE FROM extraction_run WHERE extraction_run_id IN (" + ",".join("'" + r[0].replace("'", "''") + "'" for r in rows) + ");")
    # corrected labels for 3.0.2 rows parsed from chain_jobs.txt (both G8 jobs were labelled 'gap G8')
    chain = (LOGS / "chain_jobs.txt").read_text()
    fix = {}
    for line in chain.splitlines():
        apply_mode = False
        for tok in line.split():
            if tok == "apply:":
                apply_mode = True
            if "=" in tok and tok.split("=")[1].isdigit():
                st, jid = tok.split("=")
                fix[jid] = ("gap apply_" + st) if apply_mode and not st.startswith("apply") else ("gap " + st)
    n = 0
    for jid, label in fix.items():
        c.execute("UPDATE extraction_run SET verification='VERIFIED_LOG', job_ids=?, "
                  "provenance_evidence='job listed in outputs/logs/gap/chain_jobs.txt' WHERE extraction_run_id=?", (jid, jid))
        n += c.execute("UPDATE extraction_run SET stage_corrected=? WHERE extraction_run_id=? AND stage IS NOT ?",
                       (label, jid, label)).rowcount
    c.execute("UPDATE extraction_run SET verification='AS_IN_3.0.2_UNVERIFIED', "
              "provenance_evidence='row carried from 3.0.2; no independent evidence checked' WHERE verification IS NULL")
    m.log("R1", "FILL_NEW_COLUMN", "extraction_run.stage_corrected", "corrected stage labels from chain_jobs.txt (3.0.2 'stage' kept)", n,
          "-- dropped with the column")

    # ── R2 run columns ───────────────────────────────────────────────────────
    print("R2 run provenance on rows")
    m.add_col("R2", "claim", "extraction_run_id_recovered", "run recovered for corpus claims that had none (original column untouched)")
    m.add_col("R2", "claim", "run_provenance_status", "ORIGINAL (run id present in 3.0.2) | RECOVERED_UNIQUE_STAGE_RUN | UNAVAILABLE")
    ck_secs = {r["section_record_id"] for r in jl(CORPUS / "checkpoints/stage52_findings_extract.jsonl")}
    n_ok = n_un = 0
    for rowid, sec in c.execute("SELECT rowid, evidence_section_id FROM claim WHERE claim_source='corpus_stage52'").fetchall():
        if sec in ck_secs:
            c.execute("UPDATE claim SET extraction_run_id_recovered=?, run_provenance_status='RECOVERED_UNIQUE_STAGE_RUN' WHERE rowid=?",
                      (e52["run_id"], rowid))
            n_ok += 1
        else:
            c.execute("UPDATE claim SET run_provenance_status='UNAVAILABLE' WHERE rowid=?", (rowid,))
            n_un += 1
    c.execute("UPDATE claim SET run_provenance_status='ORIGINAL' WHERE claim_source='catalogue_v3_1'")
    m.log("R2", "FILL_NEW_COLUMN", "claim.extraction_run_id_recovered",
          f"stage-52 run for corpus claims whose evidence section is in the stage-52 checkpoint ({n_un} UNAVAILABLE)", n_ok, "-- dropped with the column")
    for t, rid, note in (("relation", "stage53_triples_extract@2.1.0", "label carried by every triple mention"),
                         ("taxonomy_annotation", "gap G11 apply", "G11 apply job 28674577"),
                         ("type_harmonization", "gap G7 apply", "G7 apply job 28671791"),
                         ("term_concept_map", "mapping_guards_v2", "guard files; G9 / DeepSeek verdict runs in their own columns")):
        m.add_col("R2", t, "extraction_run_id", f"run that produced the row ({note})")
        n = c.execute(f'UPDATE "{t}" SET extraction_run_id=?', (rid,)).rowcount
        m.log("R2", "FILL_NEW_COLUMN", f"{t}.extraction_run_id", note, n, "-- dropped with the column")
    for col, rid, cond in (("g9_run_id", "gap G9 apply", "relation_llm_g9 IS NOT NULL"),
                           ("deepseek_run_id", "deepseek_review apply", "relation_deepseek IS NOT NULL OR mapping_disposition_reviewed IS NOT NULL")):
        m.add_col("R2", "term_concept_map", col, f"run that produced the {col.split('_')[0]} verdict on this row")
        n = c.execute(f"UPDATE term_concept_map SET {col}=? WHERE {cond}", (rid,)).rowcount
        m.log("R2", "FILL_NEW_COLUMN", f"term_concept_map.{col}", "", n, "-- dropped with the column")

    # ── R3 mapping evidence ──────────────────────────────────────────────────
    print("R3 mapping evidence")
    for col, d in (("matched_via", "how the candidate was found (frozen guard file)"), ("match_scores", "candidate scores (JSON)"),
                   ("mapping_provenance", "query, services queried, error (JSON)"), ("source_service_mapping", "service that returned the candidate"),
                   ("guard_rejection_reason", "reason a guard rejected the candidate"), ("mapping_evidence_status", "RESTORED | MISMATCH")):
        m.add_col("R3", "term_concept_map", col, d)
    n = bad = 0
    upd = []
    for name in ("mapping_remapped.jsonl", "mapping_rejected.jsonl"):
        for r in jl(GUARDS / name):
            n += 1
            key = f"HMMAPROW_{n:07d}"
            upd.append((r.get("matched_via"), json.dumps(r.get("scores")) if r.get("scores") is not None else None,
                        json.dumps(r.get("provenance")) if r.get("provenance") is not None else None, r.get("source_service"),
                        r.get("guard_rejection_reason"), r.get("mapping_id"), r.get("term_id"), r.get("concept_id"), key))
    for i in range(0, len(upd), 50000):
        for u in upd[i:i + 50000]:
            cur = c.execute("UPDATE term_concept_map SET matched_via=?, match_scores=?, mapping_provenance=?, source_service_mapping=?, "
                            "guard_rejection_reason=?, mapping_evidence_status='RESTORED' WHERE mapping_row_id=? "
                            "AND mapping_id IS ? AND term_id IS ? AND concept_id IS ?", (*u[:5], u[8], *u[5:8]))
            if cur.rowcount != 1:
                bad += 1
                c.execute("UPDATE term_concept_map SET mapping_evidence_status='MISMATCH' WHERE mapping_row_id=?", (u[8],))
    total = c.execute("SELECT COUNT(*) FROM term_concept_map").fetchone()[0]
    m.log("R3", "FILL_NEW_COLUMN", "term_concept_map.(matched_via, match_scores, mapping_provenance, …)",
          f"restored from {GUARDS.relative_to(ROOT)} by row order, verified on mapping_id+term_id+concept_id; {bad} mismatches",
          n - bad, "-- dropped with the columns")
    assert n == total, f"guard rows {n} != CDM rows {total}"

    # ── R4 text version ──────────────────────────────────────────────────────
    print("R4 text version")
    c.execute("CREATE INDEX ix303_section_paper_sec ON section(paper_id, section_id_original)")
    m.log("R4", "CREATE_INDEX", "section(paper_id, section_id_original)", "lookup index", 0, "DROP INDEX ix303_section_paper_sec;")
    for t in ("term_mention", "term_definition", "cohort", "sample", "assay", "dataset", "data_asset", "claim"):
        m.add_col("R4", t, "section_text_sha256", "sha256 of section.section_text_original — the text version the offsets index")
        n = c.execute(f'UPDATE "{t}" SET section_text_sha256 = (SELECT s.text_hash_sha256 FROM section s WHERE '
                      f's.paper_id = "{t}".paper_id AND s.section_id_original = "{t}".section_id)').rowcount
        if t == "claim":
            c.execute("UPDATE claim SET section_text_sha256 = (SELECT s.text_hash_sha256 FROM section s WHERE "
                      "s.section_record_id = claim.evidence_section_id) WHERE section_text_sha256 IS NULL AND evidence_section_id IS NOT NULL")
        filled = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE section_text_sha256 IS NOT NULL').fetchone()[0]
        m.log("R4", "FILL_NEW_COLUMN", f"{t}.section_text_sha256", "via (paper_id, section_id) or evidence_section_id", filled, "-- dropped with the column")

    # ── R5 study links ───────────────────────────────────────────────────────
    print("R5 study links")
    per = Counter(p for (p,) in c.execute("SELECT paper_id FROM study"))
    assert set(per.values()) == {1}, "not exactly one study per paper"
    for t in ("cohort", "sample", "assay", "dataset", "data_asset"):
        m.add_col("R5", t, "study_id", "study of the record's paper (derived: exactly one STUDY per PAPER in this release)")
        n = c.execute(f'UPDATE "{t}" SET study_id = (SELECT s.study_id FROM study s WHERE s.paper_id = "{t}".paper_id)').rowcount
        m.log("R5", "FILL_NEW_COLUMN", f"{t}.study_id", "derived via PAPER", n, "-- dropped with the column")
    m.add_col("R5", "claim", "study_id_derived", "study of the claim's paper (derived via PAPER); claim.study_id (corpus claims) untouched")
    n = c.execute("UPDATE claim SET study_id_derived = (SELECT s.study_id FROM study s WHERE s.paper_id = claim.paper_id)").rowcount
    m.log("R5", "FILL_NEW_COLUMN", "claim.study_id_derived", "derived via PAPER", n, "-- dropped with the column")
    agree = c.execute("SELECT COUNT(*) FROM claim WHERE COALESCE(study_id,'')!='' AND study_id != study_id_derived").fetchone()[0]
    m.log("R5", "CHECK", "claim.study_id vs study_id_derived", "corpus claims whose original study_id differs from the derived one", agree, "-- check only")

    # ── R6 key constraints ───────────────────────────────────────────────────
    print("R6 unique indexes")
    for t, key in (("cohort", "cohort_id"), ("sample", "sample_group_id"), ("assay", "assay_id"), ("study", "study_id"),
                   ("dataset", "dataset_id"), ("data_asset", "asset_id"), ("claim", "finding_id, claim_source"),
                   ("term_definition", "definition_id, term_id"), ("taxonomy_annotation", "term_id, taxonomy_version"),
                   ("quantitative_result", "finding_id, claim_source"), ("claim_evidence", "finding_id, claim_source"),
                   ("section", "paper_id, section_id_original")):
        declared = any(r[5] for r in c.execute(f'PRAGMA table_info("{t}")'))
        if declared and "," not in key:
            continue
        name = f"ux303_{t}"
        c.execute(f'CREATE UNIQUE INDEX "{name}" ON "{t}" ({key})')
        m.log("R6", "CREATE_UNIQUE_INDEX", f"{t}({key})", "enforces the implemented primary key", 0, f'DROP INDEX "{name}";')

    # ── R7 relation evidence ─────────────────────────────────────────────────
    print("R7 relation evidence")
    want = {}
    for t in ("relation", "removed_relation"):
        for cid, ids in c.execute(f'SELECT canonical_triple_id, triple_mention_ids FROM "{t}"'):
            for i in (json.loads(ids) if ids else []):
                want[i] = (cid, t)
    sec = {r: (p, txt) for r, p, txt in c.execute("SELECT section_record_id, paper_id, section_text_original FROM section")}
    c.execute("CREATE TABLE relation_evidence (triple_mention_id, canonical_triple_id, relation_table, paper_id, section_record_id, "
              "source_sentence, char_start, char_end, anchor_status, extraction_run_id, section_text_sha256)")
    rows, st = [], Counter()
    hashes = dict(c.execute("SELECT section_record_id, text_hash_sha256 FROM section").fetchall())
    for tm in jl(CORPUS / "data/triple_mentions.jsonl"):
        if tm["triple_mention_id"] not in want:
            continue
        cid, t = want[tm["triple_mention_id"]]
        p, txt = sec.get(tm.get("section_id"), (tm.get("paper_id"), None))
        a, b, s = anchor_sentence(txt, tm.get("source_sentence"))
        st[a] += 1
        rows.append((tm["triple_mention_id"], cid, t, tm.get("paper_id"), tm.get("section_id"), tm.get("source_sentence"),
                     b, s, a, tm.get("extraction_run_id"), hashes.get(tm.get("section_id"))))
    c.executemany("INSERT INTO relation_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.execute("CREATE INDEX ix303_relation_evidence ON relation_evidence(canonical_triple_id)")
    m.log("R7", "CREATE_TABLE", "relation_evidence", "triple mentions anchored to section offsets: " + json.dumps(dict(st)), len(rows),
          "DROP TABLE relation_evidence;")

    # ── R8 terms, crosswalk, version ─────────────────────────────────────────
    print("R8 terms / crosswalk / version")
    m.add_col("R8", "canonical_term", "has_linked_mention", "1 if at least one term_mention links to this term")
    c.execute("CREATE TEMP TABLE linked AS SELECT DISTINCT canonical_term_id t FROM term_mention WHERE canonical_term_id IS NOT NULL")
    n = c.execute("UPDATE canonical_term SET has_linked_mention = CASE WHEN term_id IN (SELECT t FROM linked) THEN 1 ELSE 0 END").rowcount
    m.log("R8", "FILL_NEW_COLUMN", "canonical_term.has_linked_mention", "", n, "-- dropped with the column")
    c.execute("CREATE TABLE identifier_crosswalk (\"table\", row_key, original_id_column, original_id_unique, note)")
    c.executemany("INSERT INTO identifier_crosswalk VALUES (?,?,?,?,?)", [
        ("term_mention", "mention_row_id", "mention_id", 0, "mention_row_id = mention_id|extraction_model (since 3.0.1); mention_id kept unchanged"),
        ("term_concept_map", "mapping_row_id", "mapping_id", 0, "mapping_row_id = HMMAPROW_<row order in mapping_remapped + mapping_rejected> (since 3.0.1); mapping_id kept, null on 11,477 rows"),
        ("relation", "canonical_triple_id", "canonical_triple_id", 1, "unchanged"),
        ("claim", "finding_id + claim_source", "finding_id", 1, "finding_id unique within each claim_source")])
    m.log("R8", "CREATE_TABLE", "identifier_crosswalk", "row keys vs original identifiers", 4, "DROP TABLE identifier_crosswalk;")
    old = c.execute("SELECT value FROM run_metadata WHERE key='cdm_version'").fetchone()[0]
    c.execute("UPDATE run_metadata SET value=? WHERE key='cdm_version'", (VERSION,))
    c.executemany("INSERT INTO run_metadata VALUES (?,?)", [("derived_from", f"releases/cdm_v3/3.0.2 (sha256 {src_hash})"),
                                                             ("migration", "src/scripts/cdm_remediation/migrate_303.py"),
                                                             ("migrated_at", time.strftime("%Y-%m-%dT%H:%M:%S"))])
    m.log("R8", "UPDATE_VALUE", "run_metadata.cdm_version", f"{old} -> {VERSION}", 1,
          f"UPDATE run_metadata SET value='{old}' WHERE key='cdm_version'; DELETE FROM run_metadata WHERE key IN ('derived_from','migration','migrated_at');")
    m.revert.append("DROP TABLE cdm_change_log;")
    c.commit()
    # revert script: newest first; DROP COLUMN statements deduplicated
    seen, lines = set(), []
    for s in reversed(m.revert):
        if s.startswith("--") or s in seen:
            continue
        seen.add(s)
        lines.append(s)
    (out / "REVERT_303.sql").write_text("-- Reverts CDM 3.0.3-rc1 to the 3.0.2 content (SQLite >= 3.35)\n" + "\n".join(lines) + "\n")
    c.execute("VACUUM")
    c.close()
    print("done", db)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "outputs/results/cdm_v3_3.0.3_rc1"))
    a = ap.parse_args(argv)
    run(Path(a.out))


if __name__ == "__main__":
    raise SystemExit(main())
