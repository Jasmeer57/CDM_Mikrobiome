"""Resolve triples that only state an unsigned association (retype-v2.5 ASSOCIATION_UNSIGNED, 1,708) by reading more of
the paper. Model-generated layer; frozen releases unchanged. Freeze exception (new model run, external processing for
CC BY / CC0 text): PENDING project-lead approval (CHANGE_RECORD; B24 external-processing inventory).

    # CC BY / CC0 evidence only -> DeepSeek-V4.1-Flash via the Fraunhofer Genie gateway (hard licence filter below)
    python src/scripts/triples/resolve_unsigned_associations.py --backend genie --out DIR
    # every other triple -> local model on our GPU (never leaves the cluster)
    python src/scripts/triples/resolve_unsigned_associations.py --backend local --port P --model Qwen/Qwen3-32B-AWQ --out DIR

Two steps per triple (user request 2026-11-10: "if it still finds nothing check the specific section of the paper"):
  A. CONTEXT: the evidence sentence(s) marked [[ ]] with the sentence before and after (as retype-v3);
  B. SECTION: if A still gives no sign or direction, the full section that holds the evidence sentence (up to 14,000
     characters centred on it), asking whether the paper states the sign / direction of THIS association anywhere.
Labels: retype-v3 label set. Checks done by code on every answer:
  - the cue must be found verbatim in the text that was given (window in A, section in B);
  - SIGNED labels (positive / negative / increase / decrease / promotes / suppresses / risk ...) need sign wording in
    the cue (higher, lower, increase, decrease, positive, negative, inverse, risk, odds/hazard ratio, enriched,
    depleted, ...); without it the answer stays ASSOCIATION_UNSIGNED (no invented signs);
  - NULL_FINDING needs negation wording; vague / fragment endpoints -> BAD_ENDPOINT; direction rules as retype-v3;
  - a second yes/no verification of each specific answer by the same backend (STATED / WRONG_DIRECTION / NOT_STATED).
Licence rule: --backend genie selects ONLY triples whose every evidence paper is CC BY or CC0
(paper/publication/rights/PAPER_RIGHTS_MATRIX.csv) and asserts it again before each request; --backend local takes the
rest. Output DIR/unsigned_resolved.<backend>.jsonl (resumable). Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
for p in ("src/scripts/triples", "src/scripts/terms", "src/scripts/ner_llm_judge"):
    sys.path.insert(0, str(ROOT / p))
import retype_triples_v3 as V3  # noqa: E402
from retype_entity_terms import chat, sized  # noqa: E402
from retype_generic_triples import norm  # noqa: E402

DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
OPEN = {"cc by", "cc0"}
GENIE_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
PV = "unsigned-resolve-v1.0-2026-11-10"
BATCH = 4
SECTION_CHARS = 14000
SIGNED = {"POSITIVELY_ASSOCIATED_WITH", "NEGATIVELY_ASSOCIATED_WITH", "INCREASED_IN", "DECREASED_IN", "PROMOTES",
          "SUPPRESSES", "UPREGULATES", "DOWNREGULATES", "INCREASES_RISK_OF", "PROTECTIVE_AGAINST", "MORE_ABUNDANT_THAN",
          "LESS_ABUNDANT_THAN", "INCREASES_OVER_TIME", "DECREASES_OVER_TIME", "IMPROVES", "IMPAIRS", "ALLEVIATES",
          "EXACERBATES", "INHIBITS"}
SIGN = re.compile(r"(increas|decreas|higher|lower|greater|less\b|fewer|more\b|positiv|negativ|invers|elevat|reduc|enrich|"
                  r"deplet|rais|risk|odds ratio|hazard ratio|\bor\s*=|\bhr\b|protect|improv|impair|worsen|inhibit|promot|"
                  r"suppress|up-?regulat|down-?regulat|declin|rise|rose|gain|loss|drop|↑|↓|r\s*=\s*-?\d|rho|β|beta)")
EXTRA_A = """
These triples were previously typed ASSOCIATION_UNSIGNED: the marked sentence says the two are associated / correlated /
linked. Look in the marked sentence AND its neighbours for the SIGN or DIRECTION of this specific association (higher /
lower, positive / inverse, increase / decrease, risk, an effect estimate with a sign). If found, use the signed label and
quote that wording as the cue. If no sign or direction is stated for THESE two, answer ASSOCIATION_UNSIGNED. Never guess
a sign."""
SECTION_PROMPT = """You read one section of a human-microbiome paper. Each item is
[n, "subject", "object", "the sentence that links them", "section text"]. The sentence only says that subject and
object are associated / correlated / linked, without a sign. Read the WHOLE section and decide whether the paper states
the SIGN or DIRECTION of THIS association between THESE two (e.g. "X was higher in Y", "positively correlated",
"inversely associated", "increased risk", an effect estimate with a sign, a stated decrease or increase).
- If it does, give the relation and copy the exact words (max 20, verbatim from the section) as the cue.
- If the section never states a sign or direction for these two, answer ASSOCIATION_UNSIGNED with cue "".
- Statements about other entities do not count. Never guess a sign; never use background knowledge.
direction: SAME if the relation reads subject -> object, REVERSED if object -> subject.
Allowed: {allowed}
Return JSON {{"r": [{{"n": 0, "cue": "...", "relation": "...", "direction": "SAME"}}, ...]}}, one object per item."""


class Backend:
    def __init__(self, kind, port=None, model=None):
        self.kind, self.port, self.model = kind, port, model
        if kind == "genie":
            from judge import Client, load_cfg, parse
            cfg = load_cfg(str(ROOT / "src/scripts/ner_llm_judge/config.yml"))
            cfg["api"]["model"] = GENIE_MODEL
            cfg["api"]["max_rpm"] = 45
            self.api, self.cl, self.parse, self.model = cfg["api"], Client(cfg["api"]), parse, GENIE_MODEL

    def __call__(self, content, schema, k, max_tokens):
        if self.kind == "local":
            return chat(self.port, self.model, content, sized(schema, k), max_tokens)
        body = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}], "response_format": {"type": "json_object"}}
        body.update(self.api.get("extra_body") or {})
        r = self.cl.request("/chat/completions", body)
        return self.parse(r["choices"][0]["message"].get("content") or "") or {}


def ask(be, prompt, schema, items, nmax):
    got = {}
    for _ in range(3):
        try:
            p = be(prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), schema, len(items), nmax)
            for r in (p.get("r") or []):
                if isinstance(r, dict) and isinstance(r.get("n"), int) and 0 <= r["n"] < len(items) and r.get("relation"):
                    got[r["n"]] = r
            if len(got) == len(items):
                break
        except Exception as e:  # noqa: BLE001
            print("request failed:", repr(e)[:160], flush=True)
            time.sleep(3)
    return got


def gate(fin, labels):
    """Sign gate on top of retype-v3 finalise(): a signed label needs sign wording in its verbatim cue."""
    if fin["relation"] not in labels:
        fin.update(relation="ASSOCIATION_UNSIGNED", specific_verified=False)
    if fin["relation"] in SIGNED and not SIGN.search(fin["cue"].lower()):
        fin["sign_gate"] = "NO_SIGN_WORDING"
        fin["proposed_relation"] = fin["relation"]
        fin.update(relation="ASSOCIATION_UNSIGNED", specific_verified=False)
    return fin


def verify(be, rows):
    """Same decomposed check as retype-v3, through this backend. rows: (subject, object, fin, contexts)."""
    idx = [i for i, (_, _, fin, _) in enumerate(rows) if fin["specific_verified"]]
    if not idx:
        return
    items = []
    for k, i in enumerate(idx):
        s, o, fin, ctx = rows[i]
        a_, b_ = (o, s) if fin["direction"] == "REVERSED" else (s, o)
        items.append([k, f"{a_} --{fin['relation']} ({V3.GL.get(fin['relation'], '')})--> {b_}", ctx])
    got = {}
    for _ in range(3):
        try:
            p = be(V3.VERIFY + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), V3.VSCHEMA, len(items), 80 * len(items) + 200)
            got = {r["n"]: r["v"] for r in (p.get("r") or []) if isinstance(r, dict) and isinstance(r.get("n"), int)}
            if all(k in got for k in range(len(items))):
                break
        except Exception as e:  # noqa: BLE001
            print("verify failed:", repr(e)[:160], flush=True)
            time.sleep(3)
    for k, i in enumerate(idx):
        s, o, fin, _ = rows[i]
        v = got.get(k, "NOT_STATED")
        fin["verify"] = v
        if v == "WRONG_DIRECTION" and fin["relation"] not in V3.SYMMETRIC:
            fin["direction"] = "SAME" if fin["direction"] == "REVERSED" else "REVERSED"
        elif v not in ("STATED", "WRONG_DIRECTION"):
            fin["proposed_relation"] = fin["relation"]
            fin.update(relation="ASSOCIATION_UNSIGNED", specific_verified=False)


def section_slice(text, cs, ce):
    if text is None:
        return None
    t = text
    if cs is not None and ce is not None and len(t) > SECTION_CHARS:
        mid = (cs + ce) // 2
        lo = max(0, min(len(t) - SECTION_CHARS, mid - SECTION_CHARS // 2))
        t = t[lo:lo + SECTION_CHARS]
    return " ".join(t[:SECTION_CHARS].split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["genie", "local"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int)
    ap.add_argument("--model", default="Qwen/Qwen3-32B-AWQ")
    ap.add_argument("--db303", type=Path, default=DB303)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    lic = {r["paper_id"]: r["licence"].strip().lower() for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))}
    c303 = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
    labels, prompt = V3.labels_and_prompt(c303)
    prompt = prompt.replace("Return JSON", EXTRA_A.strip() + "\nReturn JSON", 1)
    schema = V3.make_schema(labels)
    sprompt = SECTION_PROMPT.format(allowed=", ".join(labels))
    inv = {json.loads(l)["canonical_triple_id"]: json.loads(l) for l in open(V3.INV, encoding="utf-8")}
    v25 = [json.loads(l) for f in sorted(glob.glob(str(V3.V25 / "*.jsonl"))) for l in open(f, encoding="utf-8")]
    scope = sorted((r for r in v25 if r["relation"] == "ASSOCIATION_UNSIGNED"), key=lambda r: r["canonical_triple_id"])

    def papers(tid):
        return {p for (p,) in c303.execute("SELECT DISTINCT paper_id FROM relation_evidence WHERE canonical_triple_id=? "
                                          "AND source_sentence IS NOT NULL", (tid,))}

    def eligible(tid):
        ps = papers(tid)
        return bool(ps) and all(lic.get(p, "") in OPEN for p in ps)

    elig = {t["canonical_triple_id"]: eligible(t["canonical_triple_id"]) for t in scope}   # computed once, main thread
    scope = [t for t in scope if elig[t["canonical_triple_id"]] == (a.backend == "genie")]
    if a.limit:
        scope = scope[:a.limit]
    # each run writes its own part file (2026-11-10: appending to a file left by a cancelled job hung in NFS error
    # recovery); resume reads every part. Merge with: cat unsigned_resolved.<backend>*.jsonl
    import os
    res = a.out / f"unsigned_resolved.{a.backend}.part{os.environ.get('SLURM_JOB_ID') or int(time.time())}.jsonl"
    done = set()
    for part in sorted(a.out.glob(f"unsigned_resolved.{a.backend}*.jsonl")):
        for line in open(part, encoding="utf-8"):
            if line.strip():
                done.add(json.loads(line)["canonical_triple_id"])
    todo = [t for t in scope if t["canonical_triple_id"] not in done]
    be = Backend(a.backend, a.port, a.model)
    print(f"{len(scope):,} unsigned triples for backend {a.backend} ({be.model}); {len(todo):,} to do", flush=True)
    lock, local = threading.Lock(), threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def run(batch):
        if a.backend == "genie":                       # licence assertion before any text leaves the cluster
            for t in batch:
                assert elig[t["canonical_triple_id"]] is True, t["canonical_triple_id"]
        items, ctxs, secs = [], [], []
        for n, t in enumerate(batch):
            rows = db().execute("""SELECT e.source_sentence, e.char_start, e.char_end, s.section_text_original, e.paper_id
                                   FROM relation_evidence e LEFT JOIN section s USING(section_record_id)
                                   WHERE e.canonical_triple_id=? AND e.source_sentence IS NOT NULL
                                   ORDER BY (e.anchor_status='EXACT') DESC, (e.anchor_status='WHITESPACE') DESC LIMIT 2""",
                                (t["canonical_triple_id"],)).fetchall()
            ctx = [V3.window(text, cs, ce) or "[[" + " ".join(sent.split())[:600] + "]]" for sent, cs, ce, text, _ in rows]
            sec = next((section_slice(text, cs, ce) for sent, cs, ce, text, _ in rows if text), None)
            j = inv.get(t["canonical_triple_id"], {})
            hints = "; ".join(x for x in (j.get("polarity_variants", ""), j.get("effect_direction_variants", "")) if x)
            items.append([n, t["subject"], (j.get("subject") or {}).get("type", ""), j.get("predicate_original", ""),
                          t["object"], (j.get("object") or {}).get("type", ""), hints, ctx])
            ctxs.append(ctx)
            secs.append((sec, rows[0][0] if rows else ""))
        got = ask(be, prompt, schema, items, 2400)
        fins = [gate(V3.finalise(got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}, t["subject"], t["object"], ctxs[n]), labels)
                for n, t in enumerate(batch)]
        for f in fins:
            f["step"] = "CONTEXT"
        # step B: the whole section for those still unsigned
        need = [n for n, f in enumerate(fins) if f["relation"] in ("ASSOCIATION_UNSIGNED", "UNPARSED") and secs[n][0]]
        if need:
            sitems = [[k, batch[n]["subject"], batch[n]["object"], " ".join((secs[n][1] or "").split())[:600], secs[n][0]]
                      for k, n in enumerate(need)]
            sgot = ask(be, sprompt, schema, sitems, 1200)
            for k, n in enumerate(need):
                r = sgot.get(k)
                if not r:
                    continue
                f = gate(V3.finalise(r, batch[n]["subject"], batch[n]["object"], ["[[" + secs[n][0] + "]]"]), labels)
                if f["specific_verified"] or f["relation"] == "NULL_FINDING":
                    f["step"] = "SECTION"
                    fins[n] = f
                    ctxs[n] = ["[[" + secs[n][0] + "]]"]
        verify(be, [(t["subject"], t["object"], fins[n], ctxs[n]) for n, t in enumerate(batch)])
        with lock:                                   # one handle for the whole run (2026-11-10: re-opening the file per
            fh = out_fh                              # batch hung in an NFS error-recovery call on a compute node)
            for n, t in enumerate(batch):
                fh.write(json.dumps({"canonical_triple_id": t["canonical_triple_id"], "subject": t["subject"],
                                     "object": t["object"], "v25_relation": t["relation"], **fins[n],
                                     "backend": a.backend, "model": be.model, "licence_route": "CC_BY_OR_CC0" if a.backend == "genie" else "LOCAL_ONLY",
                                     "provenance": "LLM_RESOLVED_FROM_CONTEXT_AND_SECTION", "prompt_version": PV},
                                    ensure_ascii=False) + "\n")
            fh.flush()

    out_fh = open(res, "a", encoding="utf-8")
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
        for k, fu in enumerate(as_completed(futs)):
            fu.result()
            if k % 25 == 0:
                print(f"  {k * BATCH:,}/{len(todo):,} {time.time() - t0:.0f}s", flush=True)
    out_fh.close()
    print("done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
