"""Stage A: read-only inventory and baseline of the frozen inputs for the CDM 3.1 repair candidate.

What it does (and nothing else):
  1. verifies the manifests of CDM 3.0.3, catalogue 3.1.1, terminology 1.0.1 and zenodo_frozen;
  2. hashes every other input (rights matrix, vocabularies, earlier DeepSeek outputs) into input_manifest.sha256;
  3. recounts the baseline and reconciles it with the documented values in config.yaml (stops on any mismatch);
  4. writes one input record per canonical term and per triple, with evidence REFERENCES (ids, offsets,
     SHA-256 of the sentence) but no source text, and the rights route each record would take;
  5. writes a paper-level rights eligibility register and the two reports.

It sends nothing to any API, reads no secrets, and opens every database read-only.

    python 01_inventory.py [--run-id stage_a_inventory]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from common import (ROOT, AtomicOutputDir, code_hashes, connect_ro, load_config, now_iso, require_stage, rp,
                    sha256_file, software_versions, verify_frozen, write_json, write_manifest)

csv.field_size_limit(10 ** 9)

CATALOGUE_TABLES = ["findings", "assays", "cohorts", "datasets", "data_assets", "samples"]
CATALOGUE_K01_TABLES = ["findings", "assays", "cohorts", "datasets", "data_assets", "samples"]


def count_lines(path: Path) -> int:
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 24), b""):
            n += chunk.count(b"\n")
    return n


def read_csv_nul_safe(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(io.StringIO(fh.read().replace("\x00", ""))))


def sha_text(s: str | None) -> str | None:
    return hashlib.sha256(s.encode("utf-8")).hexdigest() if s else None


def _ws(s: str) -> str:
    return " ".join(s.split())


def _norm(s: str) -> str:
    """NFKC, unified quotes/dashes, collapsed whitespace, case-folded: the 'NORMALISED' anchor level."""
    s = unicodedata.normalize("NFKC", s)
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"),
                 ("−", "-"), (" ", " ")):
        s = s.replace(a, b)
    return _ws(s).casefold()


def _alnum(s: str) -> str:
    """Letters and digits only, case-folded: tolerates markup, hyphenation and punctuation differences."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", s).casefold() if ch.isalnum())


def anchor_check(sentence: str | None, section_text: str, cs, ce) -> str:
    """Local re-verification of a stored evidence sentence at its stored offsets.
    Returns EXACT, WHITESPACE, NORMALISED, ELSEWHERE_IN_SECTION or NOT_FOUND."""
    if not sentence:
        return "NOT_FOUND"
    if cs is not None and ce is not None and 0 <= cs <= ce <= len(section_text):
        span = section_text[cs:ce]
        if span == sentence:
            return "EXACT"
        if _ws(span) == _ws(sentence):
            return "WHITESPACE"
        if _norm(span) == _norm(sentence):
            return "NORMALISED"
        if _alnum(span) and _alnum(span) == _alnum(sentence):
            return "ALNUM_NORMALISED"
    if _ws(sentence) in _ws(section_text):
        return "ELSEWHERE_IN_SECTION"
    return "NOT_FOUND"


# --------------------------------------------------------------------------------------------- rights
def load_rights(cfg) -> tuple[dict, list[dict]]:
    rows = read_csv_nul_safe(rp(cfg["other_inputs"]["rights_matrix"]))
    zen = {r["paper_id"]: r for r in read_csv_nul_safe(rp(cfg["other_inputs"]["zenodo_licences"]))}
    cand, blocked = cfg["rights"]["candidate_decision"], set(cfg["rights"]["blocked_decisions"])
    route = {}
    for r in rows:
        d = r["proposed_release_decision"]
        if d == cand:
            route[r["paper_id"]] = "CANDIDATE_PENDING_VERIFICATION"
        elif d in blocked:
            route[r["paper_id"]] = "BLOCKED_PENDING_LEGAL_CONFIRMATION"
        else:
            route[r["paper_id"]] = "BLOCKED_UNKNOWN_DECISION"
    for r in rows:
        r["_zenodo_text_layer"] = zen.get(r["paper_id"], {}).get("text_layer", "NOT_IN_ZENODO_LIST")
    return route, rows


# --------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="stage_a_inventory")
    args = ap.parse_args()
    cfg = load_config()
    require_stage(cfg, "A")
    started = now_iso()
    ws = rp(cfg["pipeline"]["workspace"])
    final = ws / args.run_id
    if final.exists():
        print(f"{final} exists: Stage A already completed for this run id. Nothing to do.")
        return 0

    # 1. frozen releases --------------------------------------------------------------------------
    print("verifying frozen release manifests ...", flush=True)
    frozen = verify_frozen(cfg)
    for k, v in frozen.items():
        print(f"  {k}: listed {v['listed']}, mismatched {len(v['mismatched'])}, missing {len(v['missing'])}, "
              f"on disk {v['files_on_disk_excl_manifest']}, fingerprint_ok {v['fingerprint_ok']}", flush=True)
    frozen_ok = all(v["ok"] for v in frozen.values())

    fi = cfg["frozen_inputs"]
    db = rp(fi["cdm"]["dir"]) / fi["cdm"]["database"]
    con = connect_ro(db)
    q1 = lambda s, *a: con.execute(s, a).fetchone()[0]

    # 2. rights ------------------------------------------------------------------------------------
    route, rights_rows = load_rights(cfg)
    cdm_papers = {r[0]: r for r in con.execute("SELECT paper_id, license_name FROM paper")}
    candidate_papers = {p for p, r in route.items() if r == "CANDIDATE_PENDING_VERIFICATION"}

    # 3. vocabularies and other inputs --------------------------------------------------------------
    vocab_dir = rp(cfg["other_inputs"]["vocabularies_dir"])
    vsums, vcheck = rp(cfg["other_inputs"]["vocabularies_checksums"]), []
    for line in vsums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d, name = line.split(None, 1)
        f = vocab_dir / name.lstrip("*").strip()
        vcheck.append({"file": name.strip(), "exists": f.is_file(),
                       "ok": f.is_file() and sha256_file(f) == d})
    vocab_status = {k: {"path": p, "exists": rp(p).is_file()} for k, p in cfg["other_inputs"]["vocabularies"].items()}

    # 4. baseline counts ---------------------------------------------------------------------------
    print("counting baseline ...", flush=True)
    term_dir = rp(fi["terminology"]["dir"])
    cat_dir = rp(fi["catalogue"]["dir"]) / "tables"
    cat_counts = {t: len(read_csv_nul_safe(cat_dir / f"{t}.csv")) for t in CATALOGUE_TABLES}
    computed = {
        "papers": q1("SELECT count(*) FROM paper"),
        "sections": q1("SELECT count(*) FROM section"),
        "mentions_cdm": q1("SELECT count(*) FROM term_mention"),
        "mentions_terminology_1_0_1": count_lines(term_dir / "term_mentions.jsonl"),
        "canonical_terms_terminology": count_lines(term_dir / "canonical_terms.jsonl"),
        "canonical_terms_cdm": q1("SELECT count(*) FROM canonical_term"),
        "removed_terms": q1("SELECT count(*) FROM removed_canonical_term"),
        "terms_typed_entity": q1("SELECT count(*) FROM canonical_term WHERE cdm_type = ?", cfg["generic_type"]),
        "mapping_rows": q1("SELECT count(*) FROM term_concept_map"),
        "mapping_rows_kept_by_guards": q1("SELECT count(*) FROM term_concept_map WHERE guard_status = 'kept'"),
        "mapping_rows_rejected_by_guards": q1("SELECT count(*) FROM term_concept_map WHERE guard_status = 'rejected_guard'"),
        "mapping_rows_accepted_two_models": q1("SELECT count(*) FROM term_concept_map WHERE mapping_disposition_reviewed = 'ACCEPTED'"),
        "terms_with_accepted_mapping": q1("SELECT count(DISTINCT term_id) FROM term_concept_map WHERE mapping_disposition_reviewed = 'ACCEPTED'"),
        "mapping_rows_with_matched_via": q1("SELECT count(*) FROM term_concept_map WHERE matched_via IS NOT NULL AND matched_via <> ''"),
        "triples": q1("SELECT count(*) FROM relation"),
        "triples_other_relation": q1("SELECT count(*) FROM relation WHERE relation_normalized = 'OTHER_RELATION'"),
        "triples_typed": q1("SELECT count(*) FROM relation WHERE relation_normalized <> 'OTHER_RELATION'"),
        "triple_evidence_rows": q1("SELECT count(*) FROM relation_evidence"),
        "definitions": q1("SELECT count(*) FROM term_definition"),
        "catalogue_records": sum(cat_counts[t] for t in CATALOGUE_K01_TABLES),
        "catalogue_findings": cat_counts["findings"],
    }
    recon = []
    for k, spec in cfg["expected_baseline"].items():
        got = computed.get(k)
        recon.append({"quantity": k, "expected": spec["value"], "recomputed": got, "source": spec["source"],
                      "status": "MATCH" if got == spec["value"] else "MISMATCH"})
    # identity: terminology 1.0.1 = CDM terms + removed terms (T04)
    t04 = computed["canonical_terms_cdm"] + computed["removed_terms"]
    recon.append({"quantity": "T04: CDM terms + removed = terminology 1.0.1", "expected": computed["canonical_terms_terminology"],
                  "recomputed": t04, "source": "T04", "status": "MATCH" if t04 == computed["canonical_terms_terminology"] else "MISMATCH"})
    recon_ok = all(r["status"] == "MATCH" for r in recon)

    # distributions and identifier integrity
    dist = {
        "cdm_type": dict(con.execute("SELECT cdm_type, count(*) FROM canonical_term GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        "relation_family": dict(con.execute("SELECT relation_family, count(*) FROM relation GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        "evidence_anchor_status": dict(con.execute("SELECT anchor_status, count(*) FROM relation_evidence GROUP BY 1").fetchall()),
        "mapping_disposition_reviewed": {str(k): v for k, v in con.execute("SELECT mapping_disposition_reviewed, count(*) FROM term_concept_map GROUP BY 1").fetchall()},
        "mapping_relation": dict(con.execute("SELECT mapping_relation, count(*) FROM term_concept_map GROUP BY 1").fetchall()),
        "mapping_evidence_status": dict(con.execute("SELECT mapping_evidence_status, count(*) FROM term_concept_map GROUP BY 1").fetchall()),
        "concept_ontology_top": {str(k): v for k, v in con.execute("SELECT ontology_name, count(*) FROM concept GROUP BY 1 ORDER BY 2 DESC LIMIT 15").fetchall()},
    }
    declared = set(cfg["cdm_types"]) | {cfg["generic_type"]}
    undeclared = {k: v for k, v in dist["cdm_type"].items() if k not in declared}
    term_ids = {r[0] for r in con.execute("SELECT term_id FROM canonical_term")}
    removed_ids = {r[0] for r in con.execute("SELECT term_id FROM removed_canonical_term")}
    integrity = {
        "types_not_in_config_CDM_TYPES": undeclared,
        "relation_subject_no_term_link": 0, "relation_object_no_term_link": 0,
        "relation_subject_term_unresolved": 0, "relation_object_term_unresolved": 0,
        "relation_subject_term_in_removed": 0, "relation_object_term_in_removed": 0,
        "mapping_term_ids_not_in_cdm_terms": q1("SELECT count(DISTINCT term_id) FROM term_concept_map WHERE term_id NOT IN (SELECT term_id FROM canonical_term)"),
        "mention_paper_ids_not_in_rights_matrix": 0,
        "evidence_rows_of_removed_triples": q1("SELECT count(*) FROM relation_evidence WHERE canonical_triple_id NOT IN (SELECT canonical_triple_id FROM relation) AND canonical_triple_id IN (SELECT canonical_triple_id FROM removed_relation)"),
        "evidence_rows_without_any_triple": q1("SELECT count(*) FROM relation_evidence WHERE canonical_triple_id NOT IN (SELECT canonical_triple_id FROM relation) AND canonical_triple_id NOT IN (SELECT canonical_triple_id FROM removed_relation)"),
        "duplicate_triple_ids": q1("SELECT count(*) - count(DISTINCT canonical_triple_id) FROM relation"),
        "duplicate_term_ids": q1("SELECT count(*) - count(DISTINCT term_id) FROM canonical_term"),
    }

    # 5. section text (local only, for anchoring checks; never written out) ---------------------------
    sec_text = {r[0]: (r[1], r[2] or "") for r in con.execute("SELECT section_record_id, paper_id, section_text_original FROM section")}

    # 6. triple inputs -----------------------------------------------------------------------------
    print("building triple inputs ...", flush=True)
    maxlen = cfg["rights"]["max_label_chars_for_transmission"]
    ev_by_triple, anchor_stats = defaultdict(list), Counter()
    for (tm, tid, pid, srid, s, cs, ce, anc, run, shash) in con.execute(
            "SELECT triple_mention_id, canonical_triple_id, paper_id, section_record_id, source_sentence, char_start, char_end, "
            "anchor_status, extraction_run_id, section_text_sha256 FROM relation_evidence"):
        sec_pid, text = sec_text.get(srid, (None, ""))
        local = anchor_check(s, text, cs, ce)
        at_offsets = local in ("EXACT", "WHITESPACE", "NORMALISED", "ALNUM_NORMALISED")
        r = route.get(pid, "PAPER_NOT_IN_RIGHTS_MATRIX")
        eligible = (r == "CANDIDATE_PENDING_VERIFICATION" and anc != "UNANCHORED" and at_offsets)
        anchor_stats[(anc, local)] += 1
        ev_by_triple[tid].append({
            "triple_mention_id": tm, "paper_id": pid, "section_record_id": srid, "char_start": cs, "char_end": ce,
            "anchor_status": anc, "local_anchor_check": local, "sentence_sha256": sha_text(s),
            "sentence_matches_offsets": at_offsets, "sentence_found_in_section": local != "NOT_FOUND",
            "section_text_sha256": shash, "extraction_run_id": run,
            "paper_rights_route": r, "eligible_for_sentence_review": eligible})
    rel_cols = ["canonical_triple_id", "subject_term_id", "subject_display_label", "subject_entity_type", "relation_normalized",
                "relation_family", "object_term_id", "object_display_label", "object_entity_type", "polarity_variants",
                "effect_direction_variants", "assertion_status_variants", "paper_ids", "mention_count", "verdict_deepseek",
                "subject_ontology_id", "object_ontology_id"]
    triples, tri_stats = [], Counter()
    for row in con.execute(f"SELECT {', '.join(rel_cols)} FROM relation ORDER BY canonical_triple_id"):
        r = dict(zip(rel_cols, row))
        for side in ("subject", "object"):
            t = r[f"{side}_term_id"]
            if not t:
                integrity[f"relation_{side}_no_term_link"] += 1
            elif t not in term_ids:
                integrity[f"relation_{side}_term_unresolved"] += 1
                if t in removed_ids:
                    integrity[f"relation_{side}_term_in_removed"] += 1
        ev = ev_by_triple.get(r["canonical_triple_id"], [])
        n_el = sum(e["eligible_for_sentence_review"] for e in ev)
        touches_blocked = any(e["paper_rights_route"] != "CANDIDATE_PENDING_VERIFICATION" for e in ev)
        for side in ("subject", "object"):
            lab = r[f"{side}_display_label"] or ""
            r[f"{side}_label_sha256"] = sha_text(lab)
            r[f"{side}_label_withheld"] = len(lab) > maxlen and touches_blocked
            if r[f"{side}_label_withheld"]:
                r[f"{side}_display_label"] = None
                tri_stats[f"{side}_label_withheld_long_string_from_withheld_paper"] += 1
        baseline = "GENERIC_COOCCURRENCE_BASELINE" if r["relation_normalized"] == "OTHER_RELATION" else "TYPED_RELATION_BASELINE"
        stage_c = ("SENTENCE_CANDIDATE_PENDING_RIGHTS_VERIFICATION" if n_el else
                   "NO_ELIGIBLE_SENTENCE_REMAINS_GENERIC_OR_UNRESOLVED")
        rec = {"canonical_triple_id": r["canonical_triple_id"],
               "subject": {"term_id": r["subject_term_id"], "label": r["subject_display_label"], "type": r["subject_entity_type"],
                           "ontology_id": r["subject_ontology_id"], "label_sha256": r["subject_label_sha256"],
                           "label_withheld": r["subject_label_withheld"]},
               "predicate_original": r["relation_normalized"], "relation_family_original": r["relation_family"],
               "object": {"term_id": r["object_term_id"], "label": r["object_display_label"], "type": r["object_entity_type"],
                          "ontology_id": r["object_ontology_id"], "label_sha256": r["object_label_sha256"],
                          "label_withheld": r["object_label_withheld"]},
               "polarity_variants": r["polarity_variants"], "effect_direction_variants": r["effect_direction_variants"],
               "assertion_status_variants": r["assertion_status_variants"], "paper_ids": r["paper_ids"],
               "mention_count": r["mention_count"], "prior_deepseek_verdict_reference_only": r["verdict_deepseek"],
               "baseline_population": baseline, "n_evidence": len(ev), "n_evidence_eligible_for_sentence_review": n_el,
               "evidence": ev, "stage_c_route": stage_c, "processing_status": "INVENTORIED"}
        triples.append(rec)
        tri_stats[stage_c] += 1
        tri_stats[baseline + "|" + stage_c] += 1
        tri_stats["evidence_rows"] += len(ev)
        tri_stats["evidence_sentence_matches_offsets"] += sum(e["sentence_matches_offsets"] for e in ev)
        tri_stats["evidence_sentence_found_in_section"] += sum(e["sentence_found_in_section"] for e in ev)
        tri_stats["evidence_eligible"] += n_el
        tri_stats["triples_with_no_evidence"] += (len(ev) == 0)

    # 7. term inputs -------------------------------------------------------------------------------
    print("building term inputs ...", flush=True)
    maps = {r[0]: r[1:] for r in con.execute(
        "SELECT term_id, count(*), sum(guard_status = 'kept'), sum(mapping_disposition_reviewed = 'ACCEPTED'), "
        "sum(matched_via IS NOT NULL AND matched_via <> ''), sum(mapping_relation = 'EXACT_MATCH') FROM term_concept_map GROUP BY term_id")}
    m_tot, m_cand, m_block, m_anch_cand = Counter(), Counter(), Counter(), Counter()
    unknown_paper = set()
    for tid, pid, n, n_anch in con.execute(
            "SELECT canonical_term_id, paper_id, count(*), sum(start_offset IS NOT NULL) FROM term_mention "
            "WHERE canonical_term_id IS NOT NULL GROUP BY canonical_term_id, paper_id"):
        r = route.get(pid)
        if r is None:
            unknown_paper.add(pid)
        m_tot[tid] += n
        if r == "CANDIDATE_PENDING_VERIFICATION":
            m_cand[tid] += n
            m_anch_cand[tid] += n_anch
        else:
            m_block[tid] += n
    integrity["mention_paper_ids_not_in_rights_matrix"] = len(unknown_paper)
    cand_list = ",".join("'" + p.replace("'", "''") + "'" for p in sorted(candidate_papers))
    refs = defaultdict(list)
    for tid, mrid, pid, sid, sent, so, eo in con.execute(
            "SELECT canonical_term_id, mention_row_id, paper_id, section_id, sentence_id, start_offset, end_offset FROM ("
            " SELECT canonical_term_id, mention_row_id, paper_id, section_id, sentence_id, start_offset, end_offset,"
            " ROW_NUMBER() OVER (PARTITION BY canonical_term_id ORDER BY mention_row_id) AS rn FROM term_mention"
            f" WHERE canonical_term_id IS NOT NULL AND start_offset IS NOT NULL AND paper_id IN ({cand_list})) WHERE rn <= 3"):
        refs[tid].append({"mention_row_id": mrid, "paper_id": pid, "section_id": sid, "sentence_id": sent,
                          "start_offset": so, "end_offset": eo})
    maxlen = cfg["rights"]["max_label_chars_for_transmission"]
    tcols = ["term_id", "term", "term_norm", "cdm_type", "cdm_type_original", "is_generic_type", "type_source",
             "taxonomy_category", "taxonomy_subcategory", "alternative_types", "mention_count", "paper_count",
             "definition_count", "is_non_concept_surface", "review_status"]
    terms, term_stats = [], Counter()
    for row in con.execute(f"SELECT {', '.join(tcols)} FROM canonical_term ORDER BY term_id"):
        r = dict(zip(tcols, row))
        tid = r["term_id"]
        mp = maps.get(tid, (0, 0, 0, 0, 0))
        label_len = len(r["term"] or "")
        if label_len > maxlen and m_block[tid] > 0:
            label_route = "LABEL_BLOCKED_LONG_STRING_FROM_WITHHELD_PAPER"
        elif label_len > maxlen:
            label_route = "LABEL_LONG_STRING_CANDIDATE_PENDING_RIGHTS_VERIFICATION"
        else:
            label_route = "LABEL_ONLY_ELIGIBLE"
        ctx_route = ("CONTEXT_CANDIDATE_PENDING_RIGHTS_VERIFICATION" if refs.get(tid) else "NO_ELIGIBLE_CONTEXT")
        withheld = label_route == "LABEL_BLOCKED_LONG_STRING_FROM_WITHHELD_PAPER"
        r["term_sha256"] = sha_text(r["term"])
        if withheld:  # a passage-length string from a withheld paper: keep its hash, not its text
            r["term"], r["term_norm"] = None, None
        rec = {**r, "label_withheld": withheld, "label_chars": label_len,
               "mentions_total": m_tot[tid], "mentions_in_candidate_papers": m_cand[tid],
               "mentions_in_blocked_papers": m_block[tid], "anchored_mentions_in_candidate_papers": m_anch_cand[tid],
               "mapping_candidates": mp[0], "mapping_kept_by_guards": mp[1] or 0, "mapping_accepted_two_models": mp[2] or 0,
               "mapping_with_matched_via": mp[3] or 0, "mapping_exact_match_relation": mp[4] or 0,
               "context_refs": refs.get(tid, []), "stage_b_label_route": label_route, "stage_b_context_route": ctx_route,
               "processing_status": "INVENTORIED"}
        terms.append(rec)
        term_stats[label_route] += 1
        term_stats[ctx_route] += 1
        term_stats["generic_ENTITY" if r["cdm_type"] == cfg["generic_type"] else "typed"] += 1
        term_stats["has_definition"] += bool(r["definition_count"])
        term_stats["has_any_mapping_candidate"] += mp[0] > 0
        term_stats["has_accepted_mapping"] += (mp[2] or 0) > 0
        term_stats["no_mention_link"] += m_tot[tid] == 0

    # 8. rights register ---------------------------------------------------------------------------
    tri_per_paper, el_per_paper, ment_per_paper = Counter(), Counter(), Counter()
    for t in triples:
        for e in t["evidence"]:
            tri_per_paper[e["paper_id"]] += 1
            el_per_paper[e["paper_id"]] += e["eligible_for_sentence_review"]
    for pid, n in con.execute("SELECT paper_id, count(*) FROM term_mention GROUP BY paper_id"):
        ment_per_paper[pid] = n
    reg_rows, unresolved = [], Counter()
    for r in rights_rows:
        pid = r["paper_id"]
        notes = []
        cdm_lic = (cdm_papers.get(pid) or (None, None))[1]
        if pid not in cdm_papers:
            notes.append("paper not in CDM")
        if (cdm_lic or "").strip().lower() != (r["licence"] or "").strip().lower() and not (r["licence"] == "NONE_FOUND" and not cdm_lic):
            notes.append(f"CDM licence '{cdm_lic}' differs from matrix '{r['licence']}'")
        if r["licence"] == "NONE_FOUND" and r["in_pmc"] == "Y":
            notes.append("no licence found although in PMC")
        if r["licence_evidence"].endswith("(NOT_IN_EUROPE_PMC)"):
            notes.append("not in Europe PMC; licence evidence weak")
        exp_layer = {"INCLUDE_TEXT": "TEXT_INCLUDED"}.get(r["proposed_release_decision"])
        if exp_layer and r["_zenodo_text_layer"] != exp_layer:
            notes.append(f"zenodo text layer {r['_zenodo_text_layer']} vs decision {r['proposed_release_decision']}")
        for n in notes:
            unresolved[n.split(" '")[0].split(" vs")[0]] += 1
        reg_rows.append({
            "paper_id": pid, "bioproject": r["bioproject"], "doi": r["doi"], "licence": r["licence"],
            "licence_url": r["licence_url"], "licence_evidence": r["licence_evidence"],
            "proposed_release_decision": r["proposed_release_decision"],
            "needs_legal_confirmation": r["needs_legal_confirmation"], "zenodo_text_layer": r["_zenodo_text_layer"],
            "cdm_license_name": cdm_lic or "", "api_transmission_status": route[pid],
            "licence_scope_verified": "NOT_VERIFIED", "api_processing_conditions_verified": "NOT_VERIFIED",
            "verified_by": "", "verified_on": "", "legal_final_decision": r["final_decision"] or "",
            "n_triple_evidence_sentences": tri_per_paper[pid], "n_sentences_eligible_after_verification": el_per_paper[pid],
            "n_term_mentions": ment_per_paper[pid], "notes": "; ".join(notes)})

    # 9. request and runtime estimates ----------------------------------------------------------------
    api, bt = cfg["api"], cfg["batching"]
    rpm, lat, conc = api["max_rpm"], api["observed_latency_s"], api["max_concurrency"]
    eff_rpm = min(rpm, conc * 60.0 / lat)

    def est(n_items, per):
        req = math.ceil(n_items / per) if n_items else 0
        return {"items": n_items, "items_per_request": per, "requests": req,
                "array_tasks": math.ceil(req / bt["requests_per_array_task"]) if req else 0,
                "minutes_at_rate_limit": round(req / eff_rpm, 1)}
    n_label = term_stats["LABEL_ONLY_ELIGIBLE"]
    n_ctx = term_stats["CONTEXT_CANDIDATE_PENDING_RIGHTS_VERIFICATION"]
    n_tri = tri_stats["SENTENCE_CANDIDATE_PENDING_RIGHTS_VERIFICATION"]
    estimates = {
        "effective_requests_per_minute": eff_rpm,
        "stage_b_terms_label_only": est(n_label, bt["terms_per_request"]),
        "stage_b_terms_with_context_after_rights_verification": est(n_ctx, bt["terms_per_request"]),
        "stage_c_triples_with_sentence_after_rights_verification": est(n_tri, bt["triples_per_request"]),
        "stage_c_triples_not_sent": tri_stats["NO_ELIGIBLE_SENTENCE_REMAINS_GENERIC_OR_UNRESOLVED"],
        "stage_d_mapping": "deterministic first; no request count until Stage D is designed in detail",
    }

    # 10. write ------------------------------------------------------------------------------------
    status = "PASS" if (frozen_ok and recon_ok) else "FAIL"
    inputs = {
        "frozen_manifests": {k: str(rp(cfg["frozen_inputs"][k]["dir"]) / cfg["frozen_inputs"][k]["manifest"]) for k in frozen},
        "files": [db, term_dir / "term_mentions.jsonl", term_dir / "canonical_terms.jsonl"]
                 + [cat_dir / f"{t}.csv" for t in CATALOGUE_TABLES]
                 + [rp(cfg["other_inputs"]["rights_matrix"]), rp(cfg["other_inputs"]["zenodo_licences"]), vsums]
                 + [rp(p) for p in cfg["other_inputs"]["vocabularies"].values() if rp(p).is_file()]
                 + [rp(p) for p in cfg["other_inputs"]["prior_deepseek_outputs"].values() if rp(p).is_file()],
    }
    inv = {
        "stage": "A", "status": status, "started": started, "finished": None,
        "pipeline": cfg["pipeline"], "source_releases": {k: cfg["frozen_inputs"][k]["release"] for k in cfg["frozen_inputs"]},
        "frozen_release_verification": frozen, "reconciliation": recon, "computed": computed,
        "catalogue_table_counts": cat_counts, "distributions": dist, "identifier_integrity": integrity,
        "terminology_routes": dict(term_stats), "triple_routes": dict(tri_stats),
        "evidence_anchor_crosstab_stored_vs_local": {f"{a}|{b}": n for (a, b), n in sorted(anchor_stats.items())},
        "rights": {"papers": len(rights_rows), "routes": dict(Counter(route.values())),
                   "unresolved_case_counts": dict(unresolved)},
        "vocabularies": {"checksums_file": str(vsums.relative_to(ROOT)), "checked": len(vcheck),
                         "ok": sum(v["ok"] for v in vcheck), "failed": [v for v in vcheck if not v["ok"]],
                         "configured": vocab_status},
        "request_estimates": estimates, "model": {k: api[k] for k in ("model", "max_rpm", "max_concurrency", "temperature")},
        "prompt_version": None, "api_calls_made": 0, "software": software_versions(),
    }
    with AtomicOutputDir(final) if status == "PASS" else _FailDir(ws / (args.run_id + ".FAILED")) as out:
        with open(out / "terminology_input.jsonl", "w", encoding="utf-8") as fh:
            for t in terms:
                fh.write(json.dumps(t, ensure_ascii=False) + "\n")
        with open(out / "triple_input.jsonl", "w", encoding="utf-8") as fh:
            for t in triples:
                fh.write(json.dumps(t, ensure_ascii=False) + "\n")
        with open(out / "RIGHTS_ELIGIBILITY_REGISTER.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(reg_rows[0]))
            w.writeheader()
            w.writerows(reg_rows)
        lines = [f"{sha256_file(Path(p))}  {Path(p).relative_to(ROOT)}" for p in inputs["files"]]
        lines += [f"{v['manifest_sha256']}  {Path(inputs['frozen_manifests'][k]).relative_to(ROOT)}" for k, v in frozen.items()]
        (out / "input_manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
        inv["finished"] = now_iso()
        inv["input_hashes"] = dict(reversed(l.split("  ", 1)) for l in lines)
        write_json(out / "baseline_inventory.json", inv)
        import reports  # local module
        reports.baseline_md(out / "BASELINE_INVENTORY.md", inv)
        reports.config_md(out / "PIPELINE_CONFIGURATION_REPORT.md", inv, cfg)
        write_json(out / "run_provenance.json", {"stage": "A", "status": status, "started": started, "finished": inv["finished"],
                                                "code_sha256": code_hashes(), "software": software_versions(),
                                                "api_calls_made": 0, "secrets_read": False})
        write_manifest(out, "stage_a_outputs.sha256", [p for p in out.iterdir() if p.name != "stage_a_outputs.sha256"], out)
    print(f"Stage A {status}: {final if status == 'PASS' else ws / (args.run_id + '.FAILED')}")
    return 0 if status == "PASS" else 2


class _FailDir:
    """On failure, outputs go to <run_id>.FAILED (kept for diagnosis); the run id stays free."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        if self.path.exists():
            self.path.rename(self.path.with_name(self.path.name + "." + now_iso().replace(":", "")))
        self.path.mkdir(parents=True)
        return self.path

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    sys.exit(main())
