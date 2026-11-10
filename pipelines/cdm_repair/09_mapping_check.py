"""Stage I: mapping check = deterministic identifier verification + a local Qwen3.5-9B judgement per candidate.

Candidates: for every CDM 3.0.3 term, the mapping rows kept by the guards with candidate_rank <= top_k, plus every
row the two earlier models accepted. Per term, the model sees the term, its type, one sentence from a paper that
uses it, and the candidates (labelled c1, c2, ... so it cannot invent identifiers); it labels each EXACT / BROADER /
NARROWER / RELATED / WRONG / UNSURE.

Independently of the model, every identifier is checked against the local vocabularies (vocab_verify.py: NCBI
Taxonomy, Mondo, HPO, and the OMOP index for MeSH, SNOMED, NCIt and OMOP concepts). Decision per mapping row:

  REJECTED                  identifier NOT_FOUND or OBSOLETE locally, or the model judged it WRONG
  ACCEPTED_COMPUTATIONALLY  model EXACT, identifier VERIFIED, the term itself matches a vocabulary name or synonym,
                            and stage B (if validated) has not flagged the term as not a term
  NOT_VERIFIABLE            model EXACT but no local copy of that vocabulary (UMLS, DOID, other OLS/BioPortal)
  UNRESOLVED                BROADER / NARROWER / RELATED / UNSURE, EXACT where only the stored label (not the term)
                            matches, EXACT for a term flagged by stage B, or no answer

Model agreement is not human approval. Nothing in the CDM is changed.

    python 09_mapping_check.py build [--top-k 3] [--limit-terms N]
    python 09_mapping_check.py run --shard 0 --nshards 8 [--limit 100]     # gated: stage I
    python 09_mapping_check.py validate
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict

import jsonschema

from common import HERE, connect_ro, load_config, now_iso, require_stage, rp, verify_frozen, write_json
from local_llm import LocalLLM
from repair_runner import fill, load_prompt, provenance, run_items, shard_items
from vocab_verify import Verifier, route

PROMPT = "mapping_check_v1.md"


def stage_dir(cfg):
    return rp(cfg["pipeline"]["workspace"]) / "stage_i_mapping_qwen"


def db(cfg):
    fi = cfg["frozen_inputs"]["cdm"]
    return connect_ro(rp(fi["dir"]) / fi["database"])


def cmd_build(cfg, args):
    if not verify_frozen(cfg, ("cdm",))["cdm"]["ok"]:
        sys.exit("CDM 3.0.3 manifest does not verify; stopping")
    con, k = db(cfg), args.top_k or cfg["stage_i"]["top_k"]
    terms = {t: (term, ct) for t, term, ct in con.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    by_term, skipped = defaultdict(list), Counter()
    for mrid, tid, cid, rank, rel, disp, lab, onto, svc in con.execute(
            "SELECT m.mapping_row_id, m.term_id, m.concept_id, m.candidate_rank, m.mapping_relation, "
            "m.mapping_disposition_reviewed, c.concept_label, c.ontology_name, c.source_service "
            "FROM term_concept_map m LEFT JOIN concept c ON c.concept_id = m.concept_id "
            "WHERE m.guard_status = 'kept' AND (m.candidate_rank <= ? OR m.mapping_disposition_reviewed = 'ACCEPTED')", (k,)):
        if tid not in terms:
            skipped["term_not_in_cdm_terms"] += 1
            continue
        if not lab:
            skipped["concept_without_label"] += 1
        by_term[tid].append({"mapping_row_id": mrid, "concept_id": cid, "rank": rank, "relation_original": rel,
                             "disposition_original": disp, "label": lab, "ontology": onto, "service": svc})
    tids = sorted(by_term)
    if args.limit_terms:
        tids = tids[: args.limit_terms]
    # one context sentence per term (anchored mention); stored as a reference, read at run time
    ctx = {}
    for tid, mrid in con.execute("SELECT canonical_term_id, mention_row_id FROM (SELECT canonical_term_id, mention_row_id, "
                                 "ROW_NUMBER() OVER (PARTITION BY canonical_term_id ORDER BY mention_row_id) rn FROM term_mention "
                                 "WHERE canonical_term_id IS NOT NULL AND start_offset IS NOT NULL AND supporting_sentence IS NOT NULL "
                                 "AND supporting_sentence <> '') WHERE rn = 1"):
        ctx[tid] = mrid
    # deterministic verification of every identifier
    needed = defaultdict(set)
    for tid in tids:
        for c in by_term[tid]:
            r, key = route(c["concept_id"], c["service"])
            needed[r].add(key)
    ver = Verifier(cfg, needed)
    items, vstat = [], Counter()
    for tid in tids:
        term, ct = terms[tid]
        cands = []
        for i, c in enumerate(by_term[tid], 1):
            v = ver.verify(c["concept_id"], c["service"], c["label"], term)
            vstat[(v["route"].split(":")[0], v["id_status"])] += 1
            cands.append({**c, "key": f"c{i}", "verify": v})
        items.append({"item_id": tid, "term": term, "cdm_type": ct, "context_mention_row_id": ctx.get(tid), "candidates": cands})
    out = stage_dir(cfg) / "inputs"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "mapping_items.jsonl", "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    summ = {"built": now_iso(), "terms": len(items), "candidates": sum(len(it["candidates"]) for it in items), "top_k": k,
            "terms_without_context_sentence": sum(1 for it in items if not it["context_mention_row_id"]),
            "skipped": dict(skipped), "identifier_verification": {f"{a}|{b}": n for (a, b), n in sorted(vstat.items())},
            "vocab_versions": ver.versions}
    write_json(out / "build_summary.json", summ)
    print(json.dumps(summ, indent=1))


def load_items(cfg):
    with open(stage_dir(cfg) / "inputs" / "mapping_items.jsonl", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh]


def cmd_run(cfg, args):
    require_stage(cfg, "I")
    items = shard_items(load_items(cfg), args.shard, args.nshards)
    if args.limit:
        items = items[: args.limit]
    system, user_t, psha = load_prompt(PROMPT)
    llm = LocalLLM(cfg)
    served = llm.served_model()
    con = db(cfg)

    def render(it):
        s = None
        if it["context_mention_row_id"] is not None:
            r = con.execute("SELECT supporting_sentence FROM term_mention WHERE mention_row_id = ?", (it["context_mention_row_id"],)).fetchone()
            s = r[0] if r else None
        lines = "\n".join(f"- {c['key']}: {c['label'] or '(no label)'} | {c['ontology'] or c['service']} | {c['concept_id']}"
                          for c in it["candidates"])
        return system, fill(user_t, term=it["term"], cdm_type=it["cdm_type"], sentence=s or "(no sentence available)",
                            candidates=lines)

    out = stage_dir(cfg) / "runs" / f"shard_{args.shard:03d}_of_{args.nshards:03d}.jsonl"
    res = run_items(items, "item_id", render, llm, out, cfg["local_llm"]["parallel"], {"prompt_sha256": psha, "model": served})
    write_json(out.with_suffix(".provenance.json"), provenance(cfg, "I", psha, served, {"result": res, "shard": args.shard,
                                                                                         "nshards": args.nshards, "limit": args.limit}))
    print(json.dumps(res))


def cmd_validate(cfg, args):
    sd = stage_dir(cfg)
    schema = json.load(open(HERE / "schemas" / "mapping_judgement.schema.json"))
    val = jsonschema.Draft202012Validator(schema)
    resp = {}
    for f in sorted((sd / "runs").glob("shard_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("response") is not None or r["item_id"] not in resp:
                resp[r["item_id"]] = r
    term_dec = {}   # stage B decisions, when available: a term flagged as not a term cannot carry an accepted mapping
    tpath = rp(cfg["pipeline"]["workspace"]) / "stage_b_terms_qwen" / "validation" / "TERM_DECISIONS.csv"
    if tpath.exists():
        with open(tpath, encoding="utf-8") as fh:
            term_dec = {r["term_id"]: r["decision"] for r in csv.DictReader(fh)}
    rows, dec, flips = [], Counter(), Counter()
    for it in load_items(cfg):
        r = resp.get(it["item_id"])
        judged, problems = {}, []
        if r and r.get("response") is not None:
            p = r["response"]
            errs = list(val.iter_errors(p))
            if errs:
                problems.append("schema:" + errs[0].message[:60])
            else:
                keys = {c["key"] for c in it["candidates"]}
                for j in p["judgements"]:
                    if j["candidate_id"] in keys:
                        judged[j["candidate_id"]] = j
                    else:
                        problems.append("unknown_candidate_id")
        for c in it["candidates"]:
            v, j = c["verify"], judged.get(c["key"])
            rel = j["relation"] if j else None
            if v["id_status"] in ("NOT_FOUND", "OBSOLETE"):
                d, why = "REJECTED", "identifier_" + v["id_status"].lower()
            elif r is None:
                d, why = "NOT_PROCESSED", "no_model_answer_yet"
            elif rel is None:
                d, why = "UNRESOLVED", "no_judgement" + (";" + ";".join(problems) if problems else "")
            elif rel == "WRONG":
                d, why = "REJECTED", "model_wrong"
            elif rel == "EXACT" and v["id_status"] == "VERIFIED":
                if term_dec.get(it["item_id"]) == "FLAG_NOT_A_TERM":
                    d, why = "UNRESOLVED", "exact_but_term_flagged_not_a_term"
                elif v["term_match"] != "NONE":
                    d, why = "ACCEPTED_COMPUTATIONALLY", "exact_verified_term_name_match"
                elif v["label_match"] != "NONE":
                    d, why = "UNRESOLVED", "exact_verified_label_only"   # term itself not a vocabulary name/synonym
                else:
                    d, why = "UNRESOLVED", "exact_but_no_name_match"
            elif rel == "EXACT":
                d, why = "NOT_VERIFIABLE", "exact_vocab_not_local"
            else:
                d, why = "UNRESOLVED", "model_" + rel.lower()
            if c["disposition_original"] == "ACCEPTED":
                flips[d] += 1
            dec[d] += 1
            rows.append({"mapping_row_id": c["mapping_row_id"], "term_id": it["item_id"], "term": it["term"],
                         "cdm_type": it["cdm_type"], "concept_id": c["concept_id"], "concept_label": c["label"],
                         "vocabulary": c["ontology"] or c["service"], "rank": c["rank"],
                         "relation_original": c["relation_original"], "disposition_original": c["disposition_original"],
                         "model_relation": rel, "model_reason": j.get("reason") if j else None,
                         "id_status": v["id_status"], "verify_route": v["route"], "label_match": v["label_match"],
                         "term_match": v["term_match"], "vocab_version": v["vocab_version"], "decision": d, "reason_code": why,
                         "model": r.get("model") if r else None, "prompt_sha256": r.get("prompt_sha256") if r else None})
    out = sd / "validation"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "MAPPING_DECISIONS.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summ = {"validated": now_iso(), "mapping_rows": len(rows), "decisions": dict(dec),
            "previously_two_model_ACCEPTED_now": dict(flips),
            "reason_codes": dict(Counter(r["reason_code"].split(";")[0] for r in rows)),
            "stage_b_decisions_used": len(term_dec),
            "note": "ACCEPTED_COMPUTATIONALLY = model EXACT + identifier verified locally + term name match + term not flagged by stage B. Not human approval."}
    write_json(out / "summary.json", summ)
    print(json.dumps(summ, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--top-k", type=int, default=0)
    b.add_argument("--limit-terms", type=int, default=0)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=1)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--array-task", type=int, default=None)
    sub.add_parser("validate")
    args = ap.parse_args()
    if getattr(args, "array_task", None) is not None:
        args.shard = args.array_task
    cfg = load_config()
    {"build": cmd_build, "run": cmd_run, "validate": cmd_validate}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
