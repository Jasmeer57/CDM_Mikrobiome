"""Second re-typing pass for triples still without a specific relation (CDM 3.1.0 triple_tier relation =
NO_SPECIFIC_RELATION_STATED; 14,867). Model-generated layer; frozen releases unchanged. Freeze exception: new model
run, PENDING project-lead approval (CHANGE_RECORD).

    python src/scripts/triples/retype_triples_v2.py --out DIR --port P [--model M] [--shard i --nshards n] [--sample N]

Why a second pass: the 2026-11-09 closed list had no label for SIGNED association wording, so sentences such as
"X was positively correlated with Y" or "X was associated with higher Y" had to be NO_SPECIFIC_RELATION_STATED.
This pass (a) adds signed, still-truthful labels (NEW below), (b) uses a stronger local model (Qwen3.5-9B AWQ by
default) and (c) gives up to 3 evidence sentences instead of 2. Every specific label needs a verbatim cue; the script
checks that the cue is in a sentence (cue_found). If the sentences only say "associated / linked / related" with no
sign, the answer stays ASSOCIATION_UNSIGNED (renamed exit, same meaning as before); no relation is invented.
Output DIR/triples_retyped_v2.jsonl (resumable). Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
sys.path.insert(0, str(ROOT / "src/scripts/terms"))
from repair_triples import GLOSS  # noqa: E402
from retype_generic_triples import GENERIC, norm  # noqa: E402
from retype_entity_terms import chat, sized  # noqa: E402  (schema-enforced chat; exact-length arrays)

DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
PV = "retype-v2.5-2026-11-10"
BATCH = 8
NEW = {"POSITIVELY_ASSOCIATED_WITH": "the sentence states a positive correlation/association (higher subject goes with higher object)",
       "NEGATIVELY_ASSOCIATED_WITH": "the sentence states a negative/inverse correlation/association",
       "DIFFERENTIALLY_ABUNDANT_IN": "ONLY abundance/level of subject differs between named groups or conditions (object), no direction stated; NOT for affects/influences/impacts (use MODULATES)",
       "BIOMARKER_OF": "subject is reported as a marker/predictor/discriminator of object",
       "PREDICTS": "subject predicts object (prediction or classification wording)",
       "INCREASES_OVER_TIME": "ONLY with time/age/development wording: subject rises over time or with age (object = the time or age)",
       "DECREASES_OVER_TIME": "ONLY with time/age/development wording: subject falls over time or with age (object = the time or age)"}
EXITS = ["ASSOCIATION_UNSIGNED", "NULL_FINDING", "NOT_SUPPORTED"]
NEG = re.compile(r"\b(no|not|none|neither|nor|without|unchanged|similar|comparable|did not|was not|were not|n\.s\.|non-significant|nonsignificant|insignificant)\b")
SYMMETRIC = {"ASSOCIATION_UNSIGNED", "POSITIVELY_ASSOCIATED_WITH", "NEGATIVELY_ASSOCIATED_WITH", "COMPARED_WITH",
             "SAME_AS", "COOPERATES_WITH", "COMPETES_WITH", "NULL_FINDING", "NOT_SUPPORTED", "UNPARSED"}
PASSIVE = re.compile(r"\bby\s*$")


def order_direction(subject, obj, cue, sents):
    """Direction read from word order in the sentence that holds the cue (v2.5). Subject before the cue and object after
    -> SAME; object before and subject after -> REVERSED; a passive cue ending in "by" ("was produced by") flips it.
    None if the order is not clear. Used one way only (see main): on the 2026-11-10 run, word order was right on all 8
    rows where it said SAME against a model REVERSED, but only about half of the 41 rows where it said REVERSED against
    a model SAME ("B has high levels of A", "altered through"), so it may undo a REVERSED but never create one."""
    c, a, b = norm(cue), norm(subject), norm(obj)
    if not (c and a and b):
        return None
    for s in sents:
        k = s.find(c)
        if k < 0:
            continue
        ia, ib = s.find(a), s.find(b)
        if ia < 0 or ib < 0 or a in b or b in a:
            return None
        before, after = range(0, k), range(k + len(c), len(s) + 1)
        if ia in before and ib in after:
            d = "SAME"
        elif ib in before and ia in after:
            d = "REVERSED"
        else:
            return None
        if PASSIVE.search(c):
            d = "REVERSED" if d == "SAME" else "SAME"
        return d
    return None
PROMPT = """You re-type relation triples from human-microbiome papers that so far have NO specific relation. Each item is
[n, "subject", "subject type", "object", "object type", ["sentence", ...]]. Using ONLY the sentences, choose the most
specific relation the sentences STATE from subject to object:
- A specific relation needs the sentence's own wording ("was enriched in" -> INCREASED_IN; "positively correlated
  with" -> POSITIVELY_ASSOCIATED_WITH; "inversely associated" -> NEGATIVELY_ASSOCIATED_WITH; "associated with lower
  Y" -> NEGATIVELY_ASSOCIATED_WITH; "differed between" -> DIFFERENTIALLY_ABUNDANT_IN).
- Only "associated / linked / related / correlated" with NO sign or direction -> ASSOCIATION_UNSIGNED.
- NULL_FINDING ONLY if the sentence explicitly says there is NO difference / no association / no effect between these two
  (negation wording such as "did not differ", "no significant", "was not associated"); give that wording as the cue.
  Background statements, opinions, methods or descriptions are NOT null findings -> NOT_SUPPORTED.
- The sentence does not relate the two -> NOT_SUPPORTED.
- INCREASED_IN / DECREASED_IN only when the object is a group, condition or sample type the subject is higher/lower IN.
  If the subject CHANGES the object ("X increased Y", "X reduced Y"), use PROMOTES / UPREGULATES or SUPPRESSES / DOWNREGULATES.
- "affects / influences / impacts / shapes" with no direction -> MODULATES.
- "X resulted in / led to reduced or lower Y" -> SUPPRESSES (or DOWNREGULATES for levels/expression); "... increased or higher Y"
  -> PROMOTES (or UPREGULATES). A comparison of the two ("more similar than", "compared with") -> COMPARED_WITH.
- A stated finding about the two is never NOT_SUPPORTED just because it is phrased as a result of an intervention.
- Check that the cue connects THESE two entities; if the sentence relates other things, answer NOT_SUPPORTED.
- Never use background knowledge.
direction: SAME if the relation reads subject -> object, REVERSED if object -> subject. Example: subject "healthy group",
object "Bifidobacterium", sentence "Bifidobacterium was higher in the healthy group" -> INCREASED_IN, direction REVERSED
(Bifidobacterium is higher IN the group).
cue: the exact words from the sentence justifying the relation (max 12 words, verbatim); for NULL_FINDING the negation
wording; "" for ASSOCIATION_UNSIGNED and NOT_SUPPORTED.
Meaning of the relations:
{glossary}
Allowed: {allowed}
For each item FIRST copy the cue (the sentence words that state how the two are related, or "" if none), THEN choose
the relation that those words express, THEN the direction.
Return JSON {{"r": [{{"n": 0, "cue": "...", "relation": "...", "direction": "SAME"}}, ...]}}, one object per item."""


def make_schema(labels):
    """Evidence first: the model copies the cue BEFORE choosing the relation (v2.4; thinking stays off)."""
    item = {"type": "object", "additionalProperties": False, "required": ["n", "cue", "relation", "direction"],
            "properties": {"n": {"type": "integer"}, "cue": {"type": "string", "maxLength": 200},
                           "relation": {"type": "string", "enum": labels},
                           "direction": {"type": "string", "enum": ["SAME", "REVERSED"]}}}
    return {"type": "object", "additionalProperties": False, "required": ["r"],
            "properties": {"r": {"type": "array", "items": item}}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--model", default="cyankiwi/Qwen3.5-9B-AWQ-4bit")
    ap.add_argument("--db303", type=Path, default=DB303)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    c303 = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
    specific = sorted(r for (r,) in c303.execute("SELECT DISTINCT relation_normalized FROM relation") if r not in GENERIC)
    labels = specific + [k for k in NEW if k not in specific] + EXITS
    gloss = {**GLOSS, **NEW}
    prompt = PROMPT.format(glossary="\n".join(f"  {k}: {v}" for k, v in gloss.items() if k in labels),
                           allowed=", ".join(labels))
    c310 = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    trip = list(c310.execute("SELECT t.canonical_triple_id, t.subject, r.subject_type, t.object, r.object_type "
                             "FROM triple_tier t JOIN triple_repair r USING(canonical_triple_id) "
                             "WHERE t.relation='NO_SPECIFIC_RELATION_STATED' ORDER BY 1"))
    if a.sample:
        trip = sorted(random.Random(20261110).sample(trip, a.sample))
    trip = [t for i, t in enumerate(trip) if i % a.nshards == a.shard]
    res = a.out / (f"triples_retyped_v2.shard{a.shard}.jsonl" if a.nshards > 1 else "triples_retyped_v2.jsonl")
    done = set()
    if res.exists():
        done = {json.loads(l)["canonical_triple_id"] for l in open(res, encoding="utf-8")
                if json.loads(l)["relation"] != "UNPARSED"}
    todo = [t for t in trip if t[0] not in done]
    print(f"{len(trip):,} triples in scope; {len(todo):,} to re-type; model {a.model}", flush=True)
    schema = make_schema(labels)
    lock, local = threading.Lock(), threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def run(batch):
        ev = []
        for t in batch:
            rows = db().execute("""SELECT source_sentence, triple_mention_id, paper_id FROM relation_evidence
                                   WHERE canonical_triple_id=? AND source_sentence IS NOT NULL
                                   ORDER BY (anchor_status='EXACT') DESC LIMIT 3""", (t[0],)).fetchall()
            ev.append([(" ".join(s.split())[:500], m, p) for s, m, p in rows])
        items = [[n, t[1], t[2], t[3], t[4], [e[0] for e in ev[n]]] for n, t in enumerate(batch)]
        got = {}
        for _ in range(3):
            try:
                p = chat(a.port, a.model, prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), sized(schema, len(items)), 2000)
                for r in p.get("r", []):
                    if isinstance(r.get("n"), int) and 0 <= r["n"] < len(batch):
                        got[r["n"]] = r
                if len(got) == len(batch):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        for n in [n for n in range(len(batch)) if n not in got]:
            try:
                p = chat(a.port, a.model, prompt + "\n\nItems:\n" + json.dumps([[0] + items[n][1:]], ensure_ascii=False), sized(schema, 1), 400)
                if p.get("r"):
                    got[n] = p["r"][0]
            except Exception:  # noqa: BLE001
                pass
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                r = got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}
                sents = [norm(e[0]) for e in ev[n]]
                cue = (r.get("cue") or "").strip()
                found = bool(cue) and any(norm(cue) in s for s in sents)
                rel = r["relation"]
                null_ok = rel != "NULL_FINDING" or (found and bool(NEG.search(cue.lower())))
                if not null_ok:                               # NULL_FINDING needs verbatim negation wording
                    rel = "NOT_SUPPORTED"
                d_model = r.get("direction", "")
                d_order = order_direction(t[1], t[3], cue, sents) if found else None
                direction = "SAME" if rel in SYMMETRIC or (d_model == "REVERSED" and d_order == "SAME") else d_model
                f.write(json.dumps({"canonical_triple_id": t[0], "subject": t[1], "object": t[3],
                                    "old_relation": "NO_SPECIFIC_RELATION_STATED", "relation": rel, "model_relation": r["relation"],
                                    "direction": direction, "direction_model": d_model, "direction_word_order": d_order, "direction_confirmed": d_order == direction, "cue": cue, "cue_found": found,
                                    "specific_verified": rel not in EXITS + ["UNPARSED"] and found,
                                    "new_label": rel in NEW, "evidence_mention_ids": [e[1] for e in ev[n]],
                                    "paper_ids": [e[2] for e in ev[n]], "provenance": "LLM_RETYPED_FROM_SENTENCE",
                                    "model": a.model, "prompt_version": PV}, ensure_ascii=False) + "\n")

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
        for k, fu in enumerate(as_completed(futs)):
            fu.result()
            if k % 200 == 0:
                print(f"  {k * BATCH:,}/{len(todo):,} {time.time() - t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
