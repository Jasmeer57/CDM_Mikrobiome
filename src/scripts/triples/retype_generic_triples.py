"""Re-type the 17,717 generic (OTHER_RELATION) triples of CDM 3.0.3 with Qwen3.5-4B (local vLLM), schema-constrained.

    python src/scripts/triples/retype_generic_triples.py --out DIR --port P [--db PATH] [--limit N]

For each generic triple the model reads subject, object, their types and up to 2 anchor sentences
(relation_evidence.source_sentence, EXACT anchors first) and must choose ONE of:
  - a SPECIFIC relation from the CDM's own vocabulary (generic labels are excluded by the JSON schema), or
  - NO_SPECIFIC_RELATION_STATED (the sentence only links the two), or NULL_FINDING (the sentence says no effect).
It also returns the direction (SAME / REVERSED w.r.t. the triple) and a short cue phrase copied from the sentence;
a deterministic check records whether the cue occurs in the sentence (cue_found). MODEL-GENERATED layer; the frozen
CDM is not modified. Resumable.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
MODEL = "Qwen/Qwen3.5-4B"
PV = "retype-v1-2026-11-09"
BATCH = 10
GENERIC = {"OTHER_RELATION", "ASSOCIATED_WITH", "ASSOCIATED_WITH_DISEASE", "ASSOCIATED_WITH_PHENOTYPE",
           "ASSOCIATED_WITH_HOST", "ASSOCIATED_WITH_BODY_SITE", "INTERACTS_WITH", "REPORTED_IN"}
ABSTAIN = ["NO_SPECIFIC_RELATION_STATED", "NULL_FINDING"]
PROMPT = """You re-type relations extracted from human-microbiome papers. Each item is
[n, "subject", "subject type", "object", "object type", ["anchor sentence", ...]]. The current label is a generic
'other relation'. Using ONLY the sentences, choose the most specific relation the sentences STATE between subject and
object, from the allowed list. Rules:
- Choose a specific relation only if the sentence's own wording expresses it (e.g. "was enriched in" -> INCREASED_IN,
  "produces" -> PRODUCES, "reduced the risk of" -> PROTECTIVE_AGAINST). Hedged wording ("may", "suggests") still
  counts if the relation itself is stated.
- If the sentence only says the two are linked/associated/correlated/related, answer NO_SPECIFIC_RELATION_STATED.
- If the sentence says there is NO difference / no association / no effect, answer NULL_FINDING.
- Never guess from background knowledge.
- direction: SAME if the relation reads subject -> object; REVERSED if it reads object -> subject.
- cue: the exact words from the sentence that justify your choice (max 12 words), copied verbatim; "" for
  NO_SPECIFIC_RELATION_STATED.
Allowed relations: {allowed}
Return JSON {{"r": [{{"n": 0, "relation": "...", "direction": "SAME", "cue": "..."}}, ...]}}, one object per item."""


def chat(port, content, schema, max_tokens=2500):
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "retype", "schema": schema, "strict": True}},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%.-]", " ", (s or "").lower())).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    specific = sorted(r for (r,) in con.execute("SELECT DISTINCT relation_normalized FROM relation") if r not in GENERIC)
    labels = specific + ABSTAIN
    item = {"type": "object", "additionalProperties": False, "required": ["n", "relation", "direction", "cue"],
            "properties": {"n": {"type": "integer"}, "relation": {"type": "string", "enum": labels},
                           "direction": {"type": "string", "enum": ["SAME", "REVERSED"]}, "cue": {"type": "string"}}}
    schema = {"type": "object", "additionalProperties": False, "required": ["r"],
              "properties": {"r": {"type": "array", "items": item}}}
    prompt = PROMPT.format(allowed=", ".join(labels))
    triples = list(con.execute("""SELECT canonical_triple_id, subject_display_label, subject_entity_type,
                                         object_display_label, object_entity_type FROM relation
                                  WHERE relation_normalized='OTHER_RELATION' ORDER BY canonical_triple_id"""))
    if a.limit:
        triples = triples[:a.limit]
    res = a.out / "retyped.jsonl"
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
    print(f"{len(triples):,} generic triples; {len(done):,} done; {len(todo):,} to re-type; {len(specific)} specific labels", flush=True)
    lock, local, stats = threading.Lock(), threading.local(), Counter()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def run(batch):
        ev = []
        for t in batch:
            rows = db().execute("""SELECT source_sentence, triple_mention_id, paper_id FROM relation_evidence
                                   WHERE canonical_triple_id=? AND source_sentence IS NOT NULL
                                   ORDER BY (anchor_status='EXACT') DESC LIMIT 2""", (t[0],)).fetchall()
            ev.append([(" ".join(s.split())[:500], m, p) for s, m, p in rows])
        items = [[n, t[1], t[2], t[3], t[4], [e[0] for e in ev[n]]] for n, t in enumerate(batch)]
        got = {}
        for attempt in range(3):
            try:
                p = chat(a.port, prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), schema)
                for r in p.get("r", []):
                    if isinstance(r.get("n"), int) and 0 <= r["n"] < len(batch):
                        got[r["n"]] = r
                if len(got) == len(batch):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        for n in [n for n in range(len(batch)) if n not in got]:
            try:
                p = chat(a.port, prompt + "\n\nItems:\n" + json.dumps([[0] + items[n][1:]], ensure_ascii=False), schema, 600)
                if p.get("r"):
                    got[n] = p["r"][0]
            except Exception:  # noqa: BLE001
                pass
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                r = got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}
                cue = (r.get("cue") or "").strip()
                found = bool(cue) and any(norm(cue) in norm(e[0]) for e in ev[n])
                stats[r["relation"]] += 1
                f.write(json.dumps({"canonical_triple_id": t[0], "subject": t[1], "object": t[3],
                                    "old_relation": "OTHER_RELATION", "relation": r["relation"],
                                    "direction": r.get("direction", ""), "cue": cue, "cue_found": found,
                                    "evidence_mention_ids": [e[1] for e in ev[n]], "paper_ids": [e[2] for e in ev[n]],
                                    "provenance": "LLM_RETYPED_FROM_SENTENCE", "model": MODEL, "prompt_version": PV},
                                   ensure_ascii=False) + "\n")

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
        for k, _ in enumerate(as_completed(futs), 1):
            if k % 100 == 0 or k == len(futs):
                print(f"{k:,}/{len(futs):,} requests, {time.time() - t0:.0f}s", flush=True)
    rows = {}
    for l in open(res, encoding="utf-8"):
        try:
            r = json.loads(l); rows[r["canonical_triple_id"]] = r
        except ValueError:
            pass
    c = Counter(r["relation"] for r in rows.values())
    spec = [r for r in rows.values() if r["relation"] not in ABSTAIN + ["UNPARSED"]]
    json.dump({"triples": len(rows), "relations": dict(c.most_common()),
               "specific": len(spec), "specific_with_cue_found": sum(1 for r in spec if r["cue_found"]),
               "reversed": sum(1 for r in spec if r["direction"] == "REVERSED"),
               "no_specific_relation_stated": c["NO_SPECIFIC_RELATION_STATED"], "null_finding": c["NULL_FINDING"],
               "model": MODEL, "prompt_version": PV,
               "note": "model-generated re-typing of generic triples; frozen CDM unchanged; specific labels with "
                       "cue_found=false should not be used without review"},
              open(a.out / "summary.json", "w"), indent=1)
    print(json.dumps({"specific": len(spec), "abstain": c["NO_SPECIFIC_RELATION_STATED"], "null": c["NULL_FINDING"],
                      "unparsed": c["UNPARSED"]}))


if __name__ == "__main__":
    main()
