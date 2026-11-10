"""Stage H: context-grounded definition repair with a local Qwen3.5-9B (vLLM on a cluster GPU).

For every definition in CDM 3.0.3 (term_definition, 6,773 rows) the model sees the term, its type, the stored
definition and an excerpt of the source section around it, and proposes a definition of the term AS USED IN THAT
PAPER plus a verbatim evidence quote. Deterministic validators (not the model) decide:

  ACCEPTED_COMPUTATIONALLY  basis EXPLICIT/ABBREVIATION, quote found verbatim in the section, the term occurs in or
                            next to the quote, and the definition's content words are grounded in the excerpt
  UNRESOLVED                no grounded definition possible (basis NONE), inferred only, inconsistent, or failed
  REJECTED                  quote not in the section, term not near the quote, ungrounded, or invalid output

Nothing in the CDM is changed. The original definition is kept beside every proposal. The model runs locally, so
no paper text leaves the cluster; every output row carries the paper's rights route so a public build can redact.

    python 08_definition_repair.py build [--include-undefined --types CHEMICAL,DISEASE]
    python 08_definition_repair.py run --shard 0 --nshards 4 [--limit 100]      # gated: stage H
    python 08_definition_repair.py validate
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter

import jsonschema

from common import (HERE, connect_ro, load_config, now_iso, require_stage, rp, verify_frozen, write_json)
from local_llm import LocalLLM
from repair_runner import fill, load_prompt, provenance, run_items, shard_items
from vocab_verify import norm

PROMPT = "definition_repair_v1.md"
STOP = set("the a an of and or in on to for with by from as at is are was were be been this that these those which "
           "its their into than such also other used using use based between within".split())


def stage_dir(cfg):
    return rp(cfg["pipeline"]["workspace"]) / "stage_h_definitions_qwen"


def rights_routes(cfg):
    with open(rp(cfg["other_inputs"]["rights_matrix"]), encoding="utf-8") as fh:
        return {r["paper_id"]: r["proposed_release_decision"] for r in csv.DictReader(fh)}


def db(cfg):
    fi = cfg["frozen_inputs"]["cdm"]
    return connect_ro(rp(fi["dir"]) / fi["database"])


# --------------------------------------------------------------------------------------------- build
def cmd_build(cfg, args):
    fr = verify_frozen(cfg, ("cdm",))
    if not fr["cdm"]["ok"]:
        sys.exit("CDM 3.0.3 manifest does not verify; stopping")
    con, W = db(cfg), cfg["stage_h"]["context_chars"]
    rights = rights_routes(cfg)
    sec = {(p, s): (rid, n) for rid, p, s, n in con.execute(
        "SELECT section_record_id, paper_id, section_id_original, character_count FROM section")}
    items, unmatched = [], 0
    for did, tid, term, ctype, pid, sid, a, b, src in con.execute(
            "SELECT d.definition_id, d.term_id, t.term, t.cdm_type, d.paper_id, d.section_id, d.definition_char_start, "
            "d.definition_char_end, d.definition_source FROM term_definition d LEFT JOIN canonical_term t ON t.term_id = d.term_id"):
        s = sec.get((pid, sid))
        if s is None or a is None:
            unmatched += 1
            continue
        lo, hi = max(0, a - W), min(s[1] or b + W, b + W)
        items.append({"item_id": f"{did}|{tid}", "definition_id": did, "kind": "EXISTING", "term_id": tid, "term": term, "cdm_type": ctype,
                      "paper_id": pid, "section_record_id": s[0], "def_start": a, "def_end": b,
                      "ctx_start": lo, "ctx_end": hi, "definition_source": src, "rights_route": rights.get(pid)})
    n_existing = len(items)
    if args.include_undefined:
        types = set(args.types.split(",")) if args.types else set(cfg["cdm_types"])
        have = {it["term_id"] for it in items}
        q = ("SELECT term_id, term, cdm_type FROM canonical_term WHERE cdm_type IN (%s) AND length(term) BETWEEN 2 AND 49"
             % ",".join("?" * len(types)))
        cand = {t: (term, ct) for t, term, ct in con.execute(q, sorted(types)) if t not in have}
        for tid, pid, sid, so, eo in con.execute(
                "SELECT canonical_term_id, paper_id, section_id, start_offset, end_offset FROM ("
                " SELECT canonical_term_id, paper_id, section_id, start_offset, end_offset, ROW_NUMBER() OVER "
                " (PARTITION BY canonical_term_id ORDER BY mention_row_id) rn FROM term_mention WHERE start_offset IS NOT NULL"
                " AND canonical_term_id IS NOT NULL) WHERE rn = 1"):
            if tid not in cand:
                continue
            s = sec.get((pid, sid))
            if s is None:
                continue
            term, ct = cand[tid]
            items.append({"item_id": "NEW_" + tid, "kind": "NEW", "term_id": tid, "term": term, "cdm_type": ct,
                          "paper_id": pid, "section_record_id": s[0], "def_start": None, "def_end": None,
                          "ctx_start": max(0, so - W), "ctx_end": eo + W, "definition_source": None,
                          "rights_route": rights.get(pid)})
    out = stage_dir(cfg) / "inputs"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "definition_items.jsonl", "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    summ = {"built": now_iso(), "existing_definitions": n_existing, "unmatched_section": unmatched,
            "new_terms": len(items) - n_existing, "total_items": len(items),
            "rights_routes": dict(Counter(it["rights_route"] for it in items)), "context_chars": W,
            "note": "items hold offsets only; the excerpt text is read from the read-only CDM at run time"}
    write_json(out / "build_summary.json", summ)
    print(json.dumps(summ, indent=1))


def term_in_window(term: str, window: str) -> bool:
    """Punctuation- and plural-tolerant match (' SEM', 's.e.m', '± SD', "SCFA's", 'OTUs'). Terms of <= 3 letters or
    digits must match a whole alphanumeric token; longer ones may match the window with non-alphanumerics removed."""
    t = re.sub(r"[^0-9a-z]", "", (term or "").lower())
    if not t:
        return False
    cands = {t, t[:-1]} if len(t) > 3 and t.endswith("s") else {t}
    if len(t) <= 3:
        return bool(cands & set(re.findall(r"[0-9a-z]+", window.lower())))
    squashed = re.sub(r"[^0-9a-z]", "", window.lower())
    return any(c in squashed for c in cands)


def load_items(cfg):
    with open(stage_dir(cfg) / "inputs" / "definition_items.jsonl", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh]


class TextSource:
    def __init__(self, con):
        self.con, self.cache = con, {}

    def section(self, rid):
        if rid not in self.cache:
            self.cache[rid] = self.con.execute("SELECT section_text_original FROM section WHERE section_record_id = ?", (rid,)).fetchone()[0] or ""
        return self.cache[rid]

    def stored_definition(self, did):
        r = self.con.execute("SELECT definition_text FROM term_definition WHERE definition_id = ?", (did,)).fetchone()
        return r[0] if r else None


# --------------------------------------------------------------------------------------------- run
def cmd_run(cfg, args):
    require_stage(cfg, "H")
    items = shard_items(load_items(cfg), args.shard, args.nshards)
    if args.limit:
        items = items[: args.limit]
    system, user_t, psha = load_prompt(PROMPT)
    llm = LocalLLM(cfg)
    served = llm.served_model()
    src = TextSource(db(cfg))
    lock = __import__("threading").Lock()

    def render(it):
        with lock:  # sqlite connection is shared between threads
            text = src.section(it["section_record_id"])
            stored = src.stored_definition(it["definition_id"]) if it["kind"] == "EXISTING" else "(none)"
        return system, fill(user_t, term=it["term"], cdm_type=it["cdm_type"], stored_definition=stored,
                            context=text[it["ctx_start"]: it["ctx_end"]])

    out = stage_dir(cfg) / "runs" / f"shard_{args.shard:03d}_of_{args.nshards:03d}.jsonl"
    meta = {"prompt_sha256": psha, "model": served}
    res = run_items(items, "item_id", render, llm, out, cfg["local_llm"]["parallel"], meta)
    write_json(out.with_suffix(".provenance.json"), provenance(cfg, "H", psha, served, {"result": res, "shard": args.shard,
                                                                                         "nshards": args.nshards, "limit": args.limit}))
    print(json.dumps(res))


# --------------------------------------------------------------------------------------------- validate
def content_tokens(s):
    return [w for w in re.findall(r"[a-z0-9]+", norm(s)) if len(w) >= 4 and w not in STOP]


def find_quote(section_text, quote):
    """Return (start, end) of quote in section text, tolerant to whitespace differences only."""
    i = section_text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    parts = [re.escape(p) for p in quote.split()]
    if not parts:
        return None
    m = re.search(r"\s+".join(parts), section_text)
    return (m.start(), m.end()) if m else None


def cmd_validate(cfg, args):
    sd = stage_dir(cfg)
    items = {it["item_id"]: it for it in load_items(cfg)}
    schema = json.load(open(HERE / "schemas" / "definition_proposal.schema.json"))
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
    src = TextSource(db(cfg))
    thr, near = cfg["stage_h"]["min_grounding"], cfg["stage_h"]["term_near_quote_chars"]
    rows, dec = [], Counter()
    for iid, it in items.items():
        r = resp.get(iid)
        row = {"item_id": iid, "kind": it["kind"], "term_id": it["term_id"], "term": it["term"], "cdm_type": it["cdm_type"],
               "paper_id": it["paper_id"], "rights_route": it["rights_route"],
               "original_definition": src.stored_definition(it["definition_id"]) if it["kind"] == "EXISTING" else None,
               "stored_verdict": None, "proposed_definition": None, "basis": None, "evidence_quote": None,
               "quote_start": None, "quote_end": None, "grounding": None, "checks_failed": "", "decision": "", "action": "",
               "model": r.get("model") if r else None, "prompt_sha256": r.get("prompt_sha256") if r else None}
        failed = []
        if r is None:
            row["decision"], row["action"], failed = "NOT_PROCESSED", "KEEP_ORIGINAL", ["no_model_answer_yet"]
        elif r.get("response") is None:
            row["decision"], row["action"], failed = "UNRESOLVED", "KEEP_ORIGINAL", ["model_call_failed"]
        else:
            p = r["response"]
            errs = list(val.iter_errors(p))
            if errs:
                failed.append("schema:" + errs[0].message[:80])
            row.update(stored_verdict=p.get("stored_verdict"), proposed_definition=p.get("definition"),
                       basis=p.get("basis"), evidence_quote=p.get("evidence_quote"))
            text = src.section(it["section_record_id"])
            excerpt = text[it["ctx_start"]: it["ctx_end"]]
            if not errs and p["basis"] != "NONE":
                pos = find_quote(text, p["evidence_quote"] or "")
                if pos is None:
                    failed.append("quote_not_in_section")
                else:
                    row["quote_start"], row["quote_end"] = pos
                    win = norm(text[max(0, pos[0] - near): pos[1] + near])
                    if norm(it["term"]) not in win and not term_in_window(it["term"], win):
                        failed.append("term_not_near_quote")
                toks = content_tokens(p["definition"] or "")
                ground = (sum(t in norm(excerpt) for t in toks) / len(toks)) if toks else 0.0
                row["grounding"] = round(ground, 2)
                if ground < thr:
                    failed.append(f"grounding_below_{thr}")
                if norm(p["definition"] or "") == norm(it["term"]):
                    failed.append("definition_repeats_term")
            if errs or failed:
                row["decision"], row["action"] = "REJECTED", "KEEP_ORIGINAL"
            elif p["basis"] == "NONE":
                row["decision"] = "UNRESOLVED"
                row["action"] = "FLAG_ORIGINAL_NOT_A_DEFINITION" if p["stored_verdict"] in ("NOT_A_DEFINITION", "WRONG_TERM") else "KEEP_ORIGINAL"
                failed.append("no_grounded_definition")
            elif p["basis"] == "INFERRED_FROM_CONTEXT":
                row["decision"], row["action"] = "UNRESOLVED", "REVIEW_INFERRED_PROPOSAL"
                failed.append("inferred_not_stated")
            else:
                row["decision"] = "ACCEPTED_COMPUTATIONALLY"
                row["action"] = "KEEP_ORIGINAL" if p["stored_verdict"] == "CORRECT" else "REPLACE_WITH_PROPOSED"
        row["checks_failed"] = ";".join(failed)
        dec[(row["kind"], row["decision"], row["action"])] += 1
        rows.append(row)
    out = sd / "validation"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "DEFINITION_DECISIONS.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    stored = Counter(r["stored_verdict"] for r in rows if r["kind"] == "EXISTING" and r["stored_verdict"])
    summ = {"validated": now_iso(), "items": len(rows), "answered": sum(1 for r in rows if r["decision"] != "NOT_PROCESSED"),
            "decisions": {"|".join(k): v for k, v in sorted(dec.items())},
            "stored_definition_verdicts_by_model": dict(stored),
            "checks_failed": dict(Counter(c for r in rows for c in r["checks_failed"].split(";") if c)),
            "note": "ACCEPTED_COMPUTATIONALLY means the implemented checks passed, not that the definition is correct."}
    write_json(out / "summary.json", summ)
    print(json.dumps(summ, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--include-undefined", action="store_true", help="also propose definitions for typed terms without one")
    b.add_argument("--types", default="", help="comma-separated CDM types for --include-undefined")
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=1)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--array-task", type=int, default=None, help="alias for --shard (SLURM)")
    sub.add_parser("validate")
    args = ap.parse_args()
    if getattr(args, "array_task", None) is not None:
        args.shard = args.array_task
    cfg = load_config()
    {"build": cmd_build, "run": cmd_run, "validate": cmd_validate}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
