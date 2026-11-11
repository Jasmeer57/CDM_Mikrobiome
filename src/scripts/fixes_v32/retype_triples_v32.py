"""Layer 3.2.0-candidate relation typer (Fix A + Fix B) for the CDM triples left NOT_SUPPORTED or
SPECIFIC_LABEL_CUE_NOT_FOUND by the 2026-11-10 layers. Local Qwen3.5-9B AWQ (vLLM, thinking off, schema-enforced).
Model-generated layer; frozen releases unchanged; freeze exception PENDING lead approval (CHANGE_RECORD).

    python src/scripts/fixes_v32/retype_triples_v32.py --check --port P [--db303 PATH]          # constructed gold set
    python src/scripts/fixes_v32/retype_triples_v32.py --out DIR --port P [--sample N] [--shard i --nshards n]

Built on retype_triples_v3.py (v3.1: context window, cue-verbatim check, word-order direction rule, NULL_FINDING negation
check, BAD_ENDPOINT rules, second-pass verifier), which is imported and not changed. What v3.2 adds:
  Fix A  - corpus-derived labels from labels_v32.json (frozen; sha256 checked at start, see PREREGISTRATION.md);
         - an OPEN-CUE option OTHER_STATED_RELATION: allowed only with a verbatim cue found in the context that states
           how THESE two are related; it is verified like a specific label (the verifier sees the cue words as the
           relation) and reported as its own tier (open_cue_verified), never counted as closed-vocabulary typed;
  Fix B  - the frozen syntactic filter (syntax_filter.py) was applied on CPU beforehand (parse/corpus_parse.jsonl):
           triples none of whose evidence sentences passes -> CO_OCCURRENCE_ONLY (no model call); only passing (or
           unassessable, UNLOCATED) evidence sentences are shown to the model.
Exits kept: ASSOCIATION_UNSIGNED, NULL_FINDING, BAD_ENDPOINT, NOT_SUPPORTED. Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
sys.path.insert(0, str(ROOT / "src/scripts/terms"))
import retype_triples_v3 as V3  # noqa: E402
from retype_entity_terms import chat, sized  # noqa: E402

D = ROOT / "outputs/results/fixes_v32_2026-11-11"
LABELS_FILE = D / "labels_v32.json"
LABELS_SHA = "ab9d72d0004d6d2ce95c57bd41f907f4d7200129931a5b7e70e942f5895fb9bb"   # frozen 2026-11-11 (PREREGISTRATION.md section 2)
PARSE = D / "parse/corpus_parse.jsonl"
DB303 = V3.DB303
PV = "retype-v3.2-2026-11-11"
BATCH = V3.BATCH
OPEN = "OTHER_STATED_RELATION"
EXITS = V3.EXITS                  # ASSOCIATION_UNSIGNED, NULL_FINDING, BAD_ENDPOINT, NOT_SUPPORTED


def load_new():
    raw = LABELS_FILE.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    assert LABELS_SHA != "PENDING" and got == LABELS_SHA, f"labels_v32.json not frozen or changed: {got}"
    j = json.loads(raw)
    return {l["label"]: l["definition"] for l in j["labels"]}, {l["label"] for l in j["labels"] if l.get("symmetric")}


NEW32, SYM32 = load_new()
SYMMETRIC = set(V3.SYMMETRIC) | SYM32
GL = {**V3.GL, **NEW32, OPEN: "the context states a relation between these two in words that no other label covers; "
                              "the cue is those verbatim words"}

EXTRA = """Additional rules (v3.2):
- The label list now also has relations derived from how these papers phrase findings ({newlist}). Prefer the label
  whose meaning matches the cue wording; keep the direction the words give.
- {open}: ONLY if the context clearly STATES a relation between THESE two entities in wording that no label covers.
  The cue must be the verbatim connecting words (a verb or verb phrase with its preposition).
  Never use it for mere co-mention, a method sentence, or when an exit (NOT_SUPPORTED, ASSOCIATION_UNSIGNED,
  NULL_FINDING, BAD_ENDPOINT) applies."""


def labels_and_prompt(c303):
    labels, prompt = V3.labels_and_prompt(c303)
    core = [l for l in labels if l not in EXITS]
    labels = core + [k for k in NEW32 if k not in core] + [OPEN] + EXITS
    gloss = "\n".join(f"  {k}: {GL.get(k, '')}" for k in labels if GL.get(k))
    prompt = V3.PROMPT.format(glossary=gloss, allowed=", ".join(labels))
    prompt = prompt.replace("Meaning of the relations:", EXTRA.format(newlist=", ".join(NEW32), open=OPEN) + "\nMeaning of the relations:")
    return labels, prompt


def finalise(r, subject, obj, contexts):
    """V3.finalise plus the v3.2 symmetric set and the open-cue tier."""
    fin = V3.finalise(r, subject, obj, contexts)
    if fin["relation"] in SYMMETRIC:
        fin["direction"] = "SAME"
    if fin["relation"] == OPEN:
        fin["open_cue_verified"] = fin["specific_verified"]
        fin["specific_verified"] = False
    else:
        fin["open_cue_verified"] = False
    return fin


def verify(port, model, rows):
    """Second pass as V3.verify, with the v3.2 glossary; for the open cue the verifier sees the cue words as the relation.
    STATED keeps it; WRONG_DIRECTION flips asymmetric relations; NOT_STATED demotes to NOT_SUPPORTED / BAD_ENDPOINT."""
    for _, _, fin, _ in rows:
        fin.setdefault("verify", None)
    idx = [i for i, (_, _, fin, _) in enumerate(rows) if fin["specific_verified"] or fin["open_cue_verified"]]
    if not idx:
        return
    items = []
    for k, i in enumerate(idx):
        s, o, fin, ctx = rows[i]
        a_, b_ = (o, s) if fin["direction"] == "REVERSED" else (s, o)
        meaning = f'"{fin["cue"]}"' if fin["relation"] == OPEN else GL.get(fin["relation"], "")
        rel = "RELATION_STATED_AS" if fin["relation"] == OPEN else fin["relation"]
        items.append([k, f"{a_} --{rel} ({meaning})--> {b_}", ctx])
    got = {}
    for _ in range(3):
        try:
            p = chat(port, model, V3.VERIFY + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False),
                     sized(V3.VSCHEMA, len(items)), 60 * len(items) + 100)
            got = {r["n"]: r["v"] for r in p.get("r", []) if isinstance(r.get("n"), int) and 0 <= r["n"] < len(items)}
            if len(got) == len(items):
                break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    for k, i in enumerate(idx):
        s, o, fin, _ = rows[i]
        v = got.get(k, "NOT_STATED")
        fin["verify"] = v
        if v == "WRONG_DIRECTION" and fin["relation"] not in SYMMETRIC:
            fin["direction"] = "SAME" if fin["direction"] == "REVERSED" else "REVERSED"
        elif v != "STATED":
            fin["proposed_relation"] = fin["relation"]
            fin["relation"] = "BAD_ENDPOINT" if (V3.vague(s) or V3.vague(o)) else "NOT_SUPPORTED"
            fin["specific_verified"] = False
            fin["open_cue_verified"] = False


# constructed gold cases for the v3.2 labels and the open cue: written from general knowledge (no benchmark data).
# (subject, stype, predicate, object, otype, hints, context, expected "LABEL" or "LABEL|REVERSED")
GOLD32 = [
    ("butyrate producers", "organism", "OTHER_RELATION", "Roseburia", "organism", "POSITIVE",
     "[[Butyrate producers included Roseburia, Faecalibacterium and Eubacterium rectale.]]", "INCLUDES"),
    ("Roseburia", "organism", "OTHER_RELATION", "butyrate producers", "organism", "POSITIVE",
     "[[Roseburia was included among the butyrate producers.]]", "INCLUDES|REVERSED"),
    ("loss of diversity", "measure", "OTHER_RELATION", "antibiotic treatment", "chemical", "NEGATIVE",
     "Diversity fell sharply after week one. [[This loss of diversity was largely due to antibiotic treatment.]]", "ATTRIBUTED_TO"),
    ("community variation", "measure", "OTHER_RELATION", "stool consistency", "clinical", "POSITIVE",
     "[[Stool consistency explained most of the community variation.]]", "ATTRIBUTED_TO|REVERSED"),
    ("dysbiosis", "condition", "OTHER_RELATION", "proinflammatory diet", "chemical", "POSITIVE",
     "[[In this cohort, dysbiosis was driven by a proinflammatory diet.]]", "ATTRIBUTED_TO"),
    ("inflammatory bowel disease", "disease", "OTHER_RELATION", "chronic diarrhoea", "clinical", "POSITIVE",
     "[[Inflammatory bowel disease manifests as chronic diarrhoea and abdominal pain.]]", "CHARACTERIZED_BY"),
    ("the preterm infant gut", "anatomy", "OTHER_RELATION", "Enterobacteriaceae", "organism", "POSITIVE",
     "[[The preterm infant gut was dominated by Enterobacteriaceae during the first weeks.]]", "CHARACTERIZED_BY"),
    ("obesity", "disease", "OTHER_RELATION", "body mass index of 30 or higher", "clinical", "POSITIVE",
     "[[Obesity was defined as a body mass index of 30 or higher.]]", "DEFINED_AS"),
    ("stool samples", "sample", "OTHER_RELATION", "hospitalised children", "population", "POSITIVE",
     "[[Stool samples were collected from 120 hospitalised children.]]", "OBTAINED_FROM"),
    ("genomic DNA", "dna", "OTHER_RELATION", "frozen faecal material", "sample", "POSITIVE",
     "[[Genomic DNA was extracted from frozen faecal material with a bead-beating protocol.]]", "OBTAINED_FROM"),
    ("the intervention group", "population", "OTHER_RELATION", "a daily inulin supplement", "chemical", "POSITIVE",
     "[[The intervention group received a daily inulin supplement for eight weeks.]]", "RECEIVES"),
    ("shotgun metagenomic sequencing", "method", "OTHER_RELATION", "saliva samples", "sample", "POSITIVE",
     "[[Shotgun metagenomic sequencing was performed on all saliva samples.]]", "APPLIED_TO"),
    ("the dietary inflammatory index", "measure", "OTHER_RELATION", "food frequency questionnaires", "method", "POSITIVE",
     "[[The dietary inflammatory index was calculated based on food frequency questionnaires.]]", "BASED_ON"),
    ("participants", "population", "OTHER_RELATION", "three enterotype groups", "other", "POSITIVE",
     "[[Participants were grouped into three enterotype groups by Dirichlet multinomial mixtures.]]", "GROUPED_INTO"),
    ("vancomycin exposure", "chemical", "OTHER_RELATION", "expansion of Enterococcus", "organism", "POSITIVE",
     "[[Vancomycin exposure led to an expansion of Enterococcus in the gut.]]", "RESULTS_IN"),
    ("twelve infants", "population", "OTHER_RELATION", "necrotising enterocolitis", "disease", "NEGATIVE",
     "[[Twelve infants developed necrotising enterocolitis during follow-up.]]", "HAS_CONDITION"),
    ("most patients", "population", "OTHER_RELATION", "recurrent Clostridioides difficile infection", "disease", "NEGATIVE",
     "[[Most patients in the transplant arm suffered from recurrent Clostridioides difficile infection.]]", "HAS_CONDITION"),
    ("enteroendocrine cells", "cell_type", "OTHER_RELATION", "vagal neurons", "cell_type", "POSITIVE",
     "[[Enteroendocrine cells synapse with vagal neurons in the intestinal mucosa.]]", "OTHER_STATED_RELATION"),
    ("phage cocktails", "chemical", "OTHER_RELATION", "Klebsiella pneumoniae", "organism", "POSITIVE",
     "[[Phage cocktails were tested alongside Klebsiella pneumoniae cultures in parallel plates.]]", "NOT_SUPPORTED"),
    ("Bacteroides", "organism", "OTHER_RELATION", "Prevotella", "organism", "POSITIVE",
     "[[Bacteroides, Prevotella and Ruminococcus were the most abundant genera across all samples.]]", "NOT_SUPPORTED"),
]


def type_batch(port, model, prompt, schema, items, subjects_objects, contexts):
    got = V3.ask(port, model, prompt, schema, items, 2200)
    fins = [finalise(got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}, s, o, contexts[n])
            for n, (s, o) in enumerate(subjects_objects)]
    verify(port, model, [(s, o, fins[n], contexts[n]) for n, (s, o) in enumerate(subjects_objects)])
    return fins


def run_check(a, prompt, schema):
    gold = list(V3.GOLD) + GOLD32
    fins = []
    for i in range(0, len(gold), BATCH):
        part = gold[i:i + BATCH]
        items = [[k, g[0], g[1], g[2], g[3], g[4], g[5], [g[6]]] for k, g in enumerate(part)]
        fins += type_batch(a.port, a.model, prompt, schema, items, [(g[0], g[3]) for g in part], [[g[6]] for g in part])
    ok, res = 0, []
    for n, g in enumerate(gold):
        f = fins[n]
        exp = g[7].split("|")
        hit = f["relation"] == exp[0] and (len(exp) == 1 or f["direction"] == exp[1])
        if exp[0] == OPEN:
            hit = hit and f["open_cue_verified"]
        ok += hit
        res.append({"set": "v3" if n < len(V3.GOLD) else "v32_new", "expected": g[7], **f, "correct": hit})
        print(("OK  " if hit else "MISS"), f"{g[7]:30} got {f['relation']}|{f['direction']} verify={f.get('verify')} cue={f['cue']!r}", flush=True)
    nv3 = sum(r["correct"] for r in res if r["set"] == "v3")
    nnew = sum(r["correct"] for r in res if r["set"] == "v32_new")
    print(f"v3.2 constructed test: {ok}/{len(gold)} (v3 cases {nv3}/{len(V3.GOLD)}, new cases {nnew}/{len(GOLD32)})", flush=True)
    out = Path(a.out or D / "gold_check")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"GOLD_CHECK_v32_{a.model.split('/')[-1]}.json").write_text(json.dumps(
        {"correct": ok, "n": len(gold), "v3_cases": [nv3, len(V3.GOLD)], "new_cases": [nnew, len(GOLD32)],
         "prompt_version": PV, "model": a.model, "labels_sha256": LABELS_SHA, "items": res}, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--model", default="cyankiwi/Qwen3.5-9B-AWQ-4bit")
    ap.add_argument("--db303", type=Path, default=DB303)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    c303 = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
    labels, prompt = labels_and_prompt(c303)
    schema = V3.make_schema(labels)
    print(f"{len(labels)} labels ({len(NEW32)} new + open cue); labels sha {LABELS_SHA[:12]}", flush=True)
    if a.check:
        return run_check(a, prompt, schema)
    a.out.mkdir(parents=True, exist_ok=True)
    scope = [r for r in (json.loads(l) for l in open(PARSE, encoding="utf-8")) if r["in_v32_scope"]]
    scope.sort(key=lambda r: r["canonical_triple_id"])
    if a.sample:
        scope = sorted(random.Random(20261111).sample(scope, a.sample), key=lambda r: r["canonical_triple_id"])
    scope = [t for i, t in enumerate(scope) if i % a.nshards == a.shard]
    res = a.out / (f"triples_v32.shard{a.shard}.jsonl" if a.nshards > 1 else "triples_v32.jsonl")
    done = set()
    if res.exists():
        for line in open(res, encoding="utf-8"):
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            if j["relation"] != "UNPARSED":
                done.add(j["canonical_triple_id"])
    todo = [t for t in scope if t["canonical_triple_id"] not in done]
    inv = {}
    for line in open(V3.INV, encoding="utf-8"):
        j = json.loads(line)
        inv[j["canonical_triple_id"]] = j
    print(f"{len(scope):,} triples in scope; {len(todo):,} to do", flush=True)
    lock, local = threading.Lock(), threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def write(recs):
        with lock, open(res, "a", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def common(t):
        return {"canonical_triple_id": t["canonical_triple_id"], "subject": t["subject"], "object": t["object"],
                "bucket_v31": t["bucket_v31"], "relation_v31": t["relation_v31"], "syntax_status": t["syntax_status"],
                "syntax_connected": t["syntax_connected"]}

    def run(batch):
        recs, items, ctxs, keep, so = [], [], [], [], []
        for t in batch:
            if t["syntax_connected"] is False:      # Fix B: no evidence sentence connects the pair
                recs.append({**common(t), "relation": "CO_OCCURRENCE_ONLY", "model_relation": None, "direction": "SAME",
                             "cue": "", "cue_found": False, "specific_verified": False, "open_cue_verified": False,
                             "verify": None, "new_label_v32": False, "provenance": "SYNTAX_FILTER", "model": None,
                             "prompt_version": PV, "labels_sha256": LABELS_SHA})
                continue
            okm = {e["mention_id"] for e in t["evidence"] if e["connected"] is not False}
            rows = db().execute("""SELECT e.source_sentence, e.triple_mention_id, e.paper_id, e.char_start, e.char_end, s.section_text_original
                                   FROM relation_evidence e LEFT JOIN section s USING(section_record_id)
                                   WHERE e.canonical_triple_id=? AND e.source_sentence IS NOT NULL
                                   ORDER BY (e.anchor_status='EXACT') DESC, (e.anchor_status='WHITESPACE') DESC LIMIT 2""",
                                (t["canonical_triple_id"],)).fetchall()
            rows = [r for r in rows if r[1] in okm] or rows
            ctx = []
            for sent, mid, pid, cs, ce, text in rows:
                w = V3.window(text, cs, ce)
                ctx.append(w if w else "[[" + " ".join(sent.split())[:600] + "]]")
            j = inv.get(t["canonical_triple_id"], {})
            hints = "; ".join(x for x in (j.get("polarity_variants", ""), j.get("effect_direction_variants", ""),
                                          j.get("assertion_status_variants", "")) if x)
            items.append([len(items), t["subject"], (j.get("subject") or {}).get("type", ""), j.get("predicate_original", ""),
                          t["object"], (j.get("object") or {}).get("type", ""), hints, ctx])
            ctxs.append(ctx)
            keep.append((t, rows))
            so.append((t["subject"], t["object"]))
        if items:
            fins = type_batch(a.port, a.model, prompt, schema, items, so, ctxs)
            for n, (t, rows) in enumerate(keep):
                fin = fins[n]
                recs.append({**common(t), **fin, "new_label_v32": fin["relation"] in NEW32,
                             "evidence_mention_ids": [r[1] for r in rows], "paper_ids": sorted({r[2] for r in rows}),
                             "provenance": "LLM_RETYPED_FROM_CONTEXT", "model": a.model, "prompt_version": PV,
                             "labels_sha256": LABELS_SHA})
        write(recs)

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
        for k, fu in enumerate(as_completed(futs)):
            fu.result()
            if k % 100 == 0:
                print(f"  {k * BATCH:,}/{len(todo):,} {time.time() - t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
