"""Schema-constrained repair of ALL 25,788 CDM 3.0.3 triples with Qwen3.5-4B (local vLLM). Model-generated layer.

    python src/scripts/triples/repair_triples.py --out DIR --port P [--db PATH] [--limit N]

Per triple the model reads subject, relation, object, types and up to 2 anchor sentences, and returns
  relation   a SPECIFIC relation from the CDM vocabulary (generic labels excluded by the JSON schema) that the sentence
             states, or NO_SPECIFIC_RELATION_STATED, NULL_FINDING (sentence states no effect/association) or
             NOT_SUPPORTED (the sentence does not relate these two at all). For already-specific triples this checks
             the existing label (keep it, or replace it).
  direction  SAME / REVERSED relative to the triple.
  cue        the words of the sentence that justify the relation (verbatim, <= 12 words).
  subject_fix / object_fix  "" if the endpoint is a clean entity; otherwise a cleaner entity phrase COPIED VERBATIM
             from the sentence (fragments, clauses, lists, citation numbers, pronouns are not clean).
Deterministic checks record cue_found and whether each fix occurs verbatim in a sentence (fixes that do not are
discarded). The frozen CDM is not modified. Resumable.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
from retype_generic_triples import DB, GENERIC, MODEL, chat, norm  # noqa: E402

PV = "repair-v3-2026-11-09"
GLOSS = {
    "INCREASED_IN": "subject is higher/enriched IN the object group or condition (e.g. taxon INCREASED_IN patients)",
    "DECREASED_IN": "subject is lower/depleted IN the object group or condition",
    "MORE_ABUNDANT_THAN": "subject more abundant than object", "LESS_ABUNDANT_THAN": "subject less abundant than object",
    "PRESENT_IN": "subject is detected/present in object (sample, site, group)", "FOUND_IN": "subject found in object",
    "PROMOTES": "subject increases/stimulates/promotes object (e.g. fibre PROMOTES Bifidobacterium)",
    "UPREGULATES": "subject raises the level/expression of object", "ENHANCES_BARRIER": "subject strengthens the barrier",
    "SUPPRESSES": "subject reduces/suppresses object", "DOWNREGULATES": "subject lowers the level/expression of object",
    "INHIBITS": "subject inhibits object", "PREVENTS": "subject prevents object", "PROTECTIVE_AGAINST": "subject lowers risk/severity of object",
    "CAUSES": "subject causes object (causal wording required)", "INCREASES_RISK_OF": "subject raises the risk of object",
    "CONTRIBUTES_TO": "subject contributes to object", "EXACERBATES": "subject worsens object", "ALLEVIATES": "subject improves/relieves object",
    "TREATS": "subject is a treatment for object", "ALTERS_MICROBIOME": "subject changes the microbiota/composition named in object",
    "MODULATES": "subject changes object without a stated direction", "PRODUCES": "subject produces/synthesises object",
    "METABOLIZES": "subject metabolises object", "DEGRADES": "subject degrades object", "CONSUMES": "subject consumes object",
    "COLONIZES": "subject colonises object", "MEASURED_BY": "subject is measured/quantified by method or measure object",
    "DETECTED_BY": "subject detected by method object", "COMPARED_WITH": "subject compared with object",
    "HAS_RELATIVE_ABUNDANCE": "subject has the relative abundance value object", "HAS_P_VALUE": "subject has p-value object",
    "IS_A": "subject is a kind of object", "PART_OF": "subject is part of object", "DERIVED_FROM": "subject derived from object",
    "PRECEDES": "subject happens before object", "RESISTANT_TO": "subject resists object", "SENSITIVE_TO": "subject is sensitive to object"}

BATCH = 8
EXITS = ["NO_SPECIFIC_RELATION_STATED", "NULL_FINDING", "NOT_SUPPORTED"]
PROMPT = """You repair relation triples extracted from human-microbiome papers. Each item is
[n, "subject", "subject type", "current relation", "object", "object type", ["anchor sentence", ...]].
Using ONLY the sentences:
1. relation: the most specific relation the sentence STATES from subject to object, from the allowed list.
   - Keep the current relation if the sentence supports it and it is specific; replace it if a different specific
     relation fits the wording better.
   - Only linked/associated/correlated/related wording -> NO_SPECIFIC_RELATION_STATED.
   - The sentence says no difference / no association / no effect -> NULL_FINDING.
   - The sentence does not relate these two at all -> NOT_SUPPORTED.
   - Never use background knowledge.
2. direction: SAME if the relation reads subject -> object, REVERSED if object -> subject.
3. cue: the exact words of the sentence justifying the relation (max 12 words, verbatim); "" for the exits.
   Counter-examples: "X was associated with decreased richness" -> NO_SPECIFIC_RELATION_STATED (association
   wording), not DECREASED_IN; "decreased with age / over time" -> DECREASES_OVER_TIME, not DECREASED_IN;
   "supplementation increased Bifidobacterium" -> PROMOTES (subject raises object), not INCREASED_IN.
4. subject_fix / object_fix: NEVER move the object into the subject or vice versa (use direction REVERSED for that).
   "" if the endpoint is already a clean entity (a taxon, chemical, disease, gene, method,
   measure, population...). If it is a fragment, clause, list, carries citation numbers or is a pronoun, give a
   cleaner entity phrase COPIED VERBATIM from the sentence. Never invent words.
Meaning of the main relations (direction matters):
{glossary}
Allowed relations: {allowed}
Return JSON {{"r": [{{"n": 0, "relation": "...", "direction": "SAME", "cue": "...", "subject_fix": "", "object_fix": ""}}, ...]}}."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="random sample of N triples (seed 20261109), for smoke tests")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    specific = sorted(r for (r,) in con.execute("SELECT DISTINCT relation_normalized FROM relation") if r not in GENERIC)
    labels = specific + EXITS
    item = {"type": "object", "additionalProperties": False,
            "required": ["n", "relation", "direction", "cue", "subject_fix", "object_fix"],
            "properties": {"n": {"type": "integer"}, "relation": {"type": "string", "enum": labels},
                           "direction": {"type": "string", "enum": ["SAME", "REVERSED"]}, "cue": {"type": "string"},
                           "subject_fix": {"type": "string"}, "object_fix": {"type": "string"}}}
    schema = {"type": "object", "additionalProperties": False, "required": ["r"],
              "properties": {"r": {"type": "array", "items": item}}}
    glossary = "\n".join(f"  {k}: {v}" for k, v in GLOSS.items() if k in labels)
    prompt = PROMPT.format(allowed=", ".join(labels), glossary=glossary)
    triples = list(con.execute("""SELECT canonical_triple_id, subject_display_label, subject_entity_type, relation_normalized,
                                         object_display_label, object_entity_type FROM relation ORDER BY canonical_triple_id"""))
    if a.sample:
        import random
        triples = random.Random(20261109).sample(triples, a.sample)
    elif a.limit:
        triples = triples[:a.limit]
    res = a.out / "repaired.jsonl"
    done = set()
    if res.exists():
        for l in open(res, encoding="utf-8"):
            try:
                r = json.loads(l)
                if r["relation"] != "UNPARSED":
                    done.add(r["canonical_triple_id"])
            except (ValueError, KeyError):
                pass
    todo = [t for t in triples if t[0] not in done]
    print(f"{len(triples):,} triples; {len(done):,} done; {len(todo):,} to repair", flush=True)
    lock, local = threading.Lock(), threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def run(batch):
        ev = []
        for t in batch:
            rows = db().execute("""SELECT source_sentence, triple_mention_id, paper_id, anchor_status FROM relation_evidence
                                   WHERE canonical_triple_id=? AND source_sentence IS NOT NULL
                                   ORDER BY (anchor_status='EXACT') DESC LIMIT 2""", (t[0],)).fetchall()
            ev.append([(" ".join(s.split())[:500], m, p, an) for s, m, p, an in rows])
        items = [[n, t[1], t[2], t[3], t[4], t[5], [e[0] for e in ev[n]]] for n, t in enumerate(batch)]
        got = {}
        for attempt in range(3):
            try:
                p = chat(a.port, prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), schema, 3000)
                for r in p.get("r", []):
                    if isinstance(r.get("n"), int) and 0 <= r["n"] < len(batch):
                        got[r["n"]] = r
                if len(got) == len(batch):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        for n in [n for n in range(len(batch)) if n not in got]:
            try:
                p = chat(a.port, prompt + "\n\nItems:\n" + json.dumps([[0] + items[n][1:]], ensure_ascii=False), schema, 700)
                if p.get("r"):
                    got[n] = p["r"][0]
            except Exception:  # noqa: BLE001
                pass
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                r = got.get(n) or {"relation": "UNPARSED"}
                sents = [norm(e[0]) for e in ev[n]]
                inside = lambda x: bool(x) and any(norm(x) in s for s in sents)  # noqa: E731
                cue = (r.get("cue") or "").strip()
                sf, of = (r.get("subject_fix") or "").strip(), (r.get("object_fix") or "").strip()
                swapped = (sf and norm(sf) == norm(t[4])) or (of and norm(of) == norm(t[1]))
                if swapped:                                   # model swapped endpoints: record as reversal
                    sf, of = "", ""
                    r["direction"] = "REVERSED" if r.get("direction") != "REVERSED" else "SAME"
                f.write(json.dumps({
                    "canonical_triple_id": t[0], "subject": t[1], "subject_type": t[2], "old_relation": t[3],
                    "object": t[4], "object_type": t[5], "relation": r["relation"], "direction": r.get("direction", ""),
                    "cue": cue, "cue_found": inside(cue),
                    "subject_fix": sf if inside(sf) and norm(sf) != norm(t[1]) else "",
                    "object_fix": of if inside(of) and norm(of) != norm(t[4]) else "",
                    "subject_fix_rejected": sf if sf and not inside(sf) else "", "swap_corrected": bool(swapped),
                    "object_fix_rejected": of if of and not inside(of) else "",
                    "anchor_status": [e[3] for e in ev[n]], "evidence_mention_ids": [e[1] for e in ev[n]],
                    "paper_ids": [e[2] for e in ev[n]], "provenance": "LLM_REPAIRED_FROM_SENTENCE",
                    "model": MODEL, "prompt_version": PV}, ensure_ascii=False) + "\n")

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
        for k, _ in enumerate(as_completed(futs), 1):
            if k % 100 == 0 or k == len(futs):
                print(f"{k:,}/{len(futs):,} requests, {time.time() - t0:.0f}s", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
