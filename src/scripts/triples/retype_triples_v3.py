"""Third re-typing pass for triples still without a verified specific relation after retype-v2.5 (local LLM,
schema-enforced). Model-generated layer; frozen releases unchanged. Freeze exception: new model run, PENDING
project-lead approval (CHANGE_RECORD).

    python src/scripts/triples/retype_triples_v3.py --out DIR --port P [--db303 PATH] [--shard i --nshards n] [--sample N]
    python src/scripts/triples/retype_triples_v3.py --check --port P [--db303 PATH]     # constructed test set

Scope: rows of outputs/results/triple_retype_v2_2026-11-10/all_v25/ with specific_verified = false (NOT_SUPPORTED,
ASSOCIATION_UNSIGNED, NULL_FINDING and specific labels whose cue was not found).
What v3 adds over v2.5 (user request 2026-11-10: "expand the types ... read the subject and predicate and the context
... no generic connections"):
  - the model reads the subject and object with their types, the ORIGINAL extracted predicate and its polarity /
    direction hints (stage_a_inventory/triple_input.jsonl), and a CONTEXT WINDOW: each evidence sentence (marked with
    [[ ]]) plus the sentence before and after it, taken from the section text at the evidence offsets (CDM 3.0.3);
  - EXPANDED specific relations (NEW3 below) for statements v2.5 could only call unsupported or unsigned;
  - ASSOCIATION_UNSIGNED only when neither the sentence nor its neighbours give a sign or direction; the model must look
    for the sign in the context first;
  - a BAD_ENDPOINT exit for triples whose subject or object is not a concept (fragments, "findings", "these markers"),
    separating extraction errors in the endpoints from sentences that relate nothing.
Every specific relation needs a verbatim cue found in the context window (cue_found); NULL_FINDING needs negation
wording; a model REVERSED is undone when the cue sentence reads subject, cue, object in active voice (as v2.5).
Output DIR/triples_retyped_v3[.shardN].jsonl (resumable). Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import glob
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
from retype_triples_v2 import NEW, NEG, order_direction  # noqa: E402
from retype_entity_terms import chat, sized  # noqa: E402

DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
V25 = ROOT / "outputs/results/triple_retype_v2_2026-11-10/all_v25"
INV = ROOT / "outputs/results/cdm_v3_3.1_deepseek_repair/stage_a_inventory/triple_input.jsonl"
PV = "retype-v3.1-2026-11-10"
BATCH = 6
NEW3 = {"INVOLVED_IN": "subject is stated to take part in / play a role in / be implicated in object (a process, function or disease), no direction",
        "IMPROVES": "subject is stated to improve / benefit / restore object (health, a function, an outcome)",
        "IMPAIRS": "subject is stated to damage / worsen / impair / disrupt object (a function, barrier, health; for a disease use EXACERBATES)",
        "SIMILAR_TO": "subject is stated to resemble / match / be a proxy for / cluster with object",
        "DIFFERS_FROM": "subject is stated to differ from object (two compared entities, groups or samples), no direction",
        "ANALYSED_WITH": "subject (a measure, sample or data) is stated to be analysed / assessed / tested / modelled with object (a method, test or software)",
        "USED_FOR": "subject (a method, tool, kit, compound, model) is stated to be used for / to do object",
        "TARGETS": "subject (a primer, probe, drug, antibody, therapy) is stated to target / bind / act on object",
        "REQUIRED_FOR": "subject is stated to be needed / essential / necessary for object",
        "HAS_PROPERTY": "object is stated to be a feature / attribute / characteristic of subject (e.g. Gram-negative, butyrate-producing, anaerobic)",
        "TRANSPORTED_TO": "subject is stated to move / be secreted / be transported / translocate to object (a site)",
        "STABLE_UNDER": "subject is stated to stay stable / resist change / not change under object (an exposure, treatment, time)",
        "RESPONDS_TO": "subject is stated to respond / change in response to object, no direction"}
EXITS = ["ASSOCIATION_UNSIGNED", "NULL_FINDING", "BAD_ENDPOINT", "NOT_SUPPORTED"]
SYMMETRIC = {"ASSOCIATION_UNSIGNED", "POSITIVELY_ASSOCIATED_WITH", "NEGATIVELY_ASSOCIATED_WITH", "COMPARED_WITH", "SAME_AS",
             "COOPERATES_WITH", "COMPETES_WITH", "SIMILAR_TO", "DIFFERS_FROM", "NULL_FINDING", "NOT_SUPPORTED",
             "BAD_ENDPOINT", "UNPARSED"}
IN_CUE = re.compile(r"\b(higher|lower|enriched|depleted|increased|decreased|elevated|reduced|more abundant|less abundant|"
                    r"abundant|prevalent|overrepresented|underrepresented)\b.*\b(in|among|within)\b")
VAGUE_HEAD = {"findings", "finding", "results", "result", "data", "factors", "factor", "markers", "study", "analysis",
              "analyses", "effects", "effect", "changes", "differences", "levels", "values", "patterns", "samples", "group",
              "groups", "parameters", "variables", "outcomes", "it", "they", "them"}


def vague(s):
    """Endpoint that names no concept: a bare number / table fragment, or a determiner + generic noun ("our findings")."""
    w = norm(s).split()
    if not w or all(re.fullmatch(r"[\d.]+", x) for x in w):
        return True
    if w[0] in {"these", "this", "those", "such", "our", "their", "its", "the"} and len(w) <= 3 and w[-1] in VAGUE_HEAD:
        return True
    return len(w) == 1 and w[0] in VAGUE_HEAD


def fragment(s):
    """Endpoint that is a phrase fragment rather than a thing: starts with a preposition / conjunction / "one"."""
    w = norm(s).split()
    return bool(w) and w[0] in {"with", "for", "by", "to", "in", "of", "on", "one", "from", "at", "as", "and", "or", "than", "between"}


def abundance_order(subject, obj, sents):
    """SAME if the subject comes before an in-group abundance cue and the object after it; REVERSED if the opposite;
    None if unclear (either endpoint missing, endpoints nested, or no cue between them)."""
    a, b = norm(subject), norm(obj)
    if not a or not b or a in b or b in a:
        return None
    for s in sents:
        ia, ib = s.find(a), s.find(b)
        if ia < 0 or ib < 0:
            continue
        lo, hi = sorted((ia, ib))
        if IN_CUE.search(s[lo:hi + max(len(a), len(b))]):
            return "SAME" if ia < ib else "REVERSED"
    return None


SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")

PROMPT = """You type relation triples from human-microbiome papers. Each item is
[n, "subject", "subject type", "original predicate", "object", "object type", "extraction hints", ["context", ...]].
Each context is an evidence sentence marked with [[ ]] plus the sentence before and after it. The original predicate
and hints come from an earlier automatic extraction and may be wrong or vague; the context decides.
Choose the MOST SPECIFIC relation the context STATES from subject to object. Generic answers are a last resort:
- Read the marked sentence AND its neighbours. If "associated / linked / correlated" appears but a neighbour or the
  sentence gives the sign ("positively", "higher", "lower", "inversely", "increase", "decrease"), use the signed label
  (POSITIVELY_ASSOCIATED_WITH, NEGATIVELY_ASSOCIATED_WITH, INCREASED_IN, DECREASED_IN, PROMOTES, SUPPRESSES ...).
- ASSOCIATION_UNSIGNED only if the context states a link between THESE two and nowhere gives a sign or direction.
- Role, use, property, similarity, difference, transport, stability and response statements have their own labels
  (INVOLVED_IN, USED_FOR, HAS_PROPERTY, SIMILAR_TO, DIFFERS_FROM, TRANSPORTED_TO, STABLE_UNDER, RESPONDS_TO ...).
  "plays a role in" -> INVOLVED_IN; "was assessed by / analysed using" -> ANALYSED_WITH; "has damaging consequences on" ->
  IMPAIRS; "is a good proxy of" -> SIMILAR_TO; "is resistant to change with" -> STABLE_UNDER.
- NULL_FINDING ONLY with explicit negation about these two ("did not differ", "no significant difference", "was not
  associated", "showed no significant difference"); give that wording as the cue.
- BAD_ENDPOINT if the subject or object is not a real concept: a sentence fragment, a number or table fragment, or a
  vague word such as "findings", "results", "these markers", "factors", "this study".
- NOT_SUPPORTED if both are real concepts but the context does not relate them (only mentions them together, describes
  a method or background unrelated to their link).
- INCREASED_IN / DECREASED_IN only when the object is a group, condition or sample type the subject is higher/lower IN;
  if the subject CHANGES the object use PROMOTES / UPREGULATES / SUPPRESSES / DOWNREGULATES.
- Never use background knowledge; never invent a sign.
direction: SAME if the relation reads subject -> object, REVERSED if object -> subject. Example: subject "healthy group",
object "Bifidobacterium", context "[[Bifidobacterium was higher in the healthy group.]]" -> INCREASED_IN, REVERSED.
cue: the exact words from the context (max 15 words, verbatim, may come from a neighbouring sentence) that state the
relation; for NULL_FINDING the negation wording; "" for BAD_ENDPOINT and NOT_SUPPORTED.
Meaning of the relations:
{glossary}
Allowed: {allowed}
For each item FIRST copy the cue, THEN choose the relation those words express, THEN the direction.
Return JSON {{"r": [{{"n": 0, "cue": "...", "relation": "...", "direction": "SAME"}}, ...]}}, one object per item."""

# constructed test set: (subject, stype, predicate, object, otype, hints, context, expected "LABEL" or "LABEL|REVERSED")
GOLD = [
    ("gut microbiota", "community", "OTHER_RELATION", "human health", "clinical", "POSITIVE",
     "Microbes live in the gut. [[The gut microbiota plays a crucial role in human health.]] It is shaped by diet.", "INVOLVED_IN"),
    ("antibiotics", "chemical", "OTHER_RELATION", "host well-being", "clinical", "NEGATIVE",
     "[[Studies have reported the damaging consequences of the use of antibiotics on host well-being.]]", "IMPAIRS"),
    ("stool microbiota community", "community", "OTHER_RELATION", "large intestinal lumen", "anatomy", "POSITIVE",
     "[[The stool microbiota community is a good proxy of the large intestinal lumen.]]", "SIMILAR_TO"),
    ("stool enterotypes", "community", "OTHER_RELATION", "diet", "chemical", "POSITIVE",
     "[[Stool enterotypes are resistant to change with diet.]] Transient changes occur in the first days.", "STABLE_UNDER"),
    ("Bacteroidetes", "organism", "ASSOCIATED_WITH", "hepatic fat fraction", "clinical", "POSITIVE",
     "[[Bacteroidetes was associated with hepatic fat fraction.]] Higher Bacteroidetes abundance went with lower hepatic fat fraction.",
     "NEGATIVELY_ASSOCIATED_WITH"),
    ("Shannon diversity", "measure", "OTHER_RELATION", "PERMANOVA", "method", "UNKNOWN",
     "[[Shannon diversity between groups was assessed by PERMANOVA.]]", "ANALYSED_WITH"),
    ("bile acids", "chemical", "OTHER_RELATION", "liver", "anatomy", "POSITIVE",
     "[[Bile acids are re-absorbed in the terminal ileum and transported back to the liver.]]", "TRANSPORTED_TO"),
    ("IgA-binding ability", "measure", "OTHER_RELATION", "infants and adults", "population", "NEGATIVE",
     "[[The IgA-binding ability showed no significant difference between infants and adults.]]", "NULL_FINDING"),
    ("findings", "other", "OTHER_RELATION", "non-LTACH patients", "population", "POSITIVE",
     "[[These factors may limit the generalizability of our findings to non-LTACH patients.]]", "BAD_ENDPOINT"),
    ("Akkermansia muciniphila", "organism", "OTHER_RELATION", "mucin degradation", "pathway", "POSITIVE",
     "[[Akkermansia muciniphila is a mucin-degrading bacterium.]]", "HAS_PROPERTY"),
    ("16S rRNA gene primers 515F/806R", "method", "OTHER_RELATION", "V4 region", "dna", "POSITIVE",
     "[[Primers 515F/806R targeting the V4 region of the 16S rRNA gene were used.]]", "TARGETS"),
    ("QIIME 2", "software", "OTHER_RELATION", "taxonomic assignment", "analysis", "POSITIVE",
     "[[QIIME 2 was used for taxonomic assignment.]]", "USED_FOR"),
    ("Prevotella", "organism", "OTHER_RELATION", "fibre intake", "chemical", "POSITIVE",
     "Diet was recorded. [[Prevotella was linked to fibre intake.]] Its abundance rose with higher fibre intake.",
     "POSITIVELY_ASSOCIATED_WITH"),
    ("Faecalibacterium", "organism", "OTHER_RELATION", "Crohn's disease", "disease", "NEGATIVE",
     "[[Faecalibacterium was depleted in patients with Crohn's disease.]]", "DECREASED_IN"),
    ("healthy controls", "population", "OTHER_RELATION", "Bifidobacterium", "organism", "POSITIVE",
     "[[Bifidobacterium was higher in healthy controls than in patients.]]", "INCREASED_IN|REVERSED"),
    ("butyrate", "chemical", "OTHER_RELATION", "intestinal barrier function", "pathway", "POSITIVE",
     "[[Butyrate improves intestinal barrier function.]]", "IMPROVES"),
    ("Escherichia coli", "organism", "OTHER_RELATION", "rural cohort", "population", "POSITIVE",
     "[[Escherichia coli and rural cohort samples were both sequenced on the MiSeq platform.]]", "NOT_SUPPORTED"),
    ("disease activity", "clinical", "ASSOCIATED_WITH", "gut microbiota", "community", "UNKNOWN",
     "[[Disease activity was associated with the gut microbiota.]] Details are in Table 2.", "ASSOCIATION_UNSIGNED"),
    # regression cases from the 2026-11-10 v3.0 smoke spot check (forced labels)
    ("oral dysbiosis", "condition", "OTHER_RELATION", "periodontitis", "disease", "POSITIVE",
     "[[Patients with IBD display oral dysbiosis likely caused by oral conditions, including periodontitis.]]", "CAUSES|REVERSED"),
    ("rectal swabs", "sample", "OTHER_RELATION", "with minimal instruction", "other", "POSITIVE",
     "[[With healthier subjects, swabs can be self-collected with minimal instruction.]]", "BAD_ENDPOINT"),
]


def labels_and_prompt(c303):
    specific = sorted(r for (r,) in c303.execute("SELECT DISTINCT relation_normalized FROM relation") if r not in GENERIC)
    labels = specific + [k for k in list(NEW) + list(NEW3) if k not in specific] + EXITS
    gloss = {**GLOSS, **NEW, **NEW3}
    prompt = PROMPT.format(glossary="\n".join(f"  {k}: {v}" for k, v in gloss.items() if k in labels), allowed=", ".join(labels))
    return labels, prompt


def make_schema(labels):
    item = {"type": "object", "additionalProperties": False, "required": ["n", "cue", "relation", "direction"],
            "properties": {"n": {"type": "integer"}, "cue": {"type": "string", "maxLength": 240},
                           "relation": {"type": "string", "enum": labels},
                           "direction": {"type": "string", "enum": ["SAME", "REVERSED"]}}}
    return {"type": "object", "additionalProperties": False, "required": ["r"], "properties": {"r": {"type": "array", "items": item}}}


def window(text, cs, ce):
    """Evidence span marked [[ ]] with one sentence before and after (sentence ends found by punctuation)."""
    if text is None or cs is None or ce is None or not (0 <= cs < ce <= len(text)):
        return None
    before = SENT_END.split(text[max(0, cs - 600):cs])
    after = SENT_END.split(text[ce:ce + 600])
    pre = before[-2] + " " + before[-1] if len(before) >= 2 else before[-1]
    post = after[0] + (" " + after[1] if len(after) >= 2 and len(after[0].strip()) < 40 else "")   # span end + next sentence when only a citation follows
    w = f"{pre.strip()} [[{text[cs:ce].strip()}]] {post.strip()}"
    return " ".join(w.split())[:1400]


def ask(port, model, prompt, schema, items, nmax):
    got = {}
    for _ in range(3):
        try:
            p = chat(port, model, prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), sized(schema, len(items)), nmax)
            for r in p.get("r", []):
                if isinstance(r.get("n"), int) and 0 <= r["n"] < len(items):
                    got[r["n"]] = r
            if len(got) == len(items):
                break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    for n in [n for n in range(len(items)) if n not in got]:
        try:
            p = chat(port, model, prompt + "\n\nItems:\n" + json.dumps([[0] + items[n][1:]], ensure_ascii=False), sized(schema, 1), 500)
            if p.get("r"):
                got[n] = p["r"][0]
        except Exception:  # noqa: BLE001
            pass
    return got


def finalise(r, subject, obj, contexts):
    """Deterministic checks on one model answer -> output fields."""
    ctx = [norm(x.replace("[[", " ").replace("]]", " ")) for x in contexts]
    cue = (r.get("cue") or "").strip()
    found = bool(cue) and any(norm(cue) in s for s in ctx)
    rel = r["relation"]
    if rel == "NULL_FINDING" and not (found and NEG.search(cue.lower())):
        rel = "NOT_SUPPORTED"
    if (rel == "NOT_SUPPORTED" and (vague(subject) or vague(obj))) or fragment(subject) or fragment(obj):
        rel = "BAD_ENDPOINT"          # endpoint error (vague word or a phrase fragment), not a relation
    d_model = r.get("direction", "")
    marked = [norm(m) for x in contexts for m in re.findall(r"\[\[(.*?)\]\]", x)]
    d_order = order_direction(subject, obj, cue, marked + ctx) if found else None
    if rel in SYMMETRIC:
        direction = "SAME"
    elif rel in ("INCREASED_IN", "DECREASED_IN") and IN_CUE.search(cue.lower()) and abundance_order(subject, obj, marked + ctx):
        # "A was higher in B": the entity before "higher ... in" is the one that is higher; reliable both ways
        direction = abundance_order(subject, obj, marked + ctx)
    elif d_model == "REVERSED" and d_order == "SAME":
        direction = "SAME"           # v2.5 rule: word order may undo a REVERSED, never create one
    else:
        direction = d_model
    return {"relation": rel, "model_relation": r["relation"], "direction": direction, "direction_model": d_model,
            "direction_word_order": d_order, "cue": cue, "cue_found": found,
            "specific_verified": rel not in EXITS + ["UNPARSED"] and found}


GL = {**GLOSS, **NEW, **NEW3}
VERIFY = """Each item is [n, "statement", ["context", ...]]. The statement claims a relation between two things, written
as SUBJECT --RELATION (meaning)--> OBJECT. Using ONLY the context (the [[ ]] sentence and its neighbours), answer:
  STATED          the context states exactly this relation, in this direction, between these two things;
  WRONG_DIRECTION the context states this relation between them but the other way round (OBJECT -> SUBJECT);
  NOT_STATED      the context does not state it: a different relation, the two are only mentioned together, a method
                  or background sentence, or one side is not a real thing (a fragment or vague word).
Be strict: a plausible relation that the words do not say is NOT_STATED.
Return JSON {"r": [{"n": 0, "v": "STATED"}, ...]}, one object per item."""
VSCHEMA = {"type": "object", "additionalProperties": False, "required": ["r"],
           "properties": {"r": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["n", "v"],
                                "properties": {"n": {"type": "integer"},
                                               "v": {"type": "string", "enum": ["STATED", "WRONG_DIRECTION", "NOT_STATED"]}}}}}}


def verify(port, model, rows):
    """Second, decomposed check of every specific answer (v3.1). rows: list of (subject, object, fin, contexts); fin is
    updated in place: STATED keeps it, WRONG_DIRECTION flips the direction (asymmetric relations), NOT_STATED demotes it
    to NOT_SUPPORTED (BAD_ENDPOINT if an endpoint is vague) and keeps the proposal in proposed_relation."""
    idx = [i for i, (_, _, fin, _) in enumerate(rows) if fin["specific_verified"]]
    for i, (_, _, fin, _) in enumerate(rows):
        fin.setdefault("verify", None)
    if not idx:
        return
    items = []
    for k, i in enumerate(idx):
        s, o, fin, ctx = rows[i]
        a_, b_ = (o, s) if fin["direction"] == "REVERSED" else (s, o)
        items.append([k, f"{a_} --{fin['relation']} ({GL.get(fin['relation'], '')})--> {b_}", ctx])
    got = {}
    for _ in range(3):
        try:
            p = chat(port, model, VERIFY + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), sized(VSCHEMA, len(items)), 60 * len(items) + 100)
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
            fin["relation"] = "BAD_ENDPOINT" if (vague(s) or vague(o)) else "NOT_SUPPORTED"
            fin["specific_verified"] = False


CLAIMS = ROOT / "outputs/results/claim_triples_2026-11-10/claim_triples.jsonl"


def claims_mode(a, labels, prompt, schema):
    """Catalogue-derived candidates: the catalogue direction is given as the predicate (it refers to the comparison as a
    whole, so the model re-reads the quote in its section context and picks the relation; same checks as above)."""
    a.out.mkdir(parents=True, exist_ok=True)
    cand = [json.loads(line) for line in open(CLAIMS, encoding="utf-8")]
    cand = sorted((r for r in cand if not r["duplicate_of_existing"]), key=lambda r: r["finding_id"])
    if a.sample:
        cand = sorted(random.Random(20261110).sample(cand, a.sample), key=lambda r: r["finding_id"])
    cand = [t for i, t in enumerate(cand) if i % a.nshards == a.shard]
    res = a.out / (f"claim_triples_v3.shard{a.shard}.jsonl" if a.nshards > 1 else "claim_triples_v3.jsonl")
    done = set()
    if res.exists():
        done = {json.loads(l)["finding_id"] for l in open(res, encoding="utf-8") if json.loads(l)["relation"] != "UNPARSED"}
    todo = [t for t in cand if t["finding_id"] not in done]
    print(f"{len(cand):,} catalogue-derived candidates; {len(todo):,} to type; model {a.model}", flush=True)
    lock, local = threading.Lock(), threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def context(t):
        ev = " ".join((t["evidence_text"] or "").split())
        # catalogue section_id is the paper-local id (section.section_id_original); try it first, then every section
        rows = db().execute("SELECT section_text_original FROM section WHERE paper_id=? "
                            "ORDER BY (section_id_original=?) DESC", (t["paper_id"], t["section_id"] or "")).fetchall()
        for (raw,) in rows:
            text = " ".join((raw or "").split())
            k = text.find(ev) if ev else -1
            if k >= 0:
                w = window(text, k, k + len(ev))
                if w:
                    return w, True
        return "[[" + ev[:900] + "]]", False

    def run(batch):
        items, ctxs, win = [], [], []
        for n, t in enumerate(batch):
            w, ok = context(t)
            hint = {"INCREASED_IN": "catalogue direction: INCREASE", "DECREASED_IN": "catalogue direction: DECREASE",
                    "NULL_FINDING": "catalogue direction: NO_ASSOCIATION"}[t["relation"]]
            items.append([n, t["subject"], "taxon or feature", t["relation"], t["object"], "comparison or exposure", hint, [w]])
            ctxs.append([w])
            win.append(ok)
        got = ask(a.port, a.model, prompt, schema, items, 2200)
        fins = [finalise(got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}, t["subject"], t["object"], ctxs[n])
                for n, t in enumerate(batch)]
        verify(a.port, a.model, [(t["subject"], t["object"], fins[n], ctxs[n]) for n, t in enumerate(batch)])
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                fin = fins[n]
                f.write(json.dumps({"finding_id": t["finding_id"], "paper_id": t["paper_id"], "subject": t["subject"],
                                    "object": t["object"], "candidate_relation": t["relation"], **fin,
                                    "new_label_v3": fin["relation"] in NEW3, "context_window": win[n],
                                    "evidence_text": t["evidence_text"], "provenance": "LLM_TYPED_FROM_CATALOGUE_FINDING",
                                    "model": a.model, "prompt_version": PV}, ensure_ascii=False) + "\n")

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
        for k, fu in enumerate(as_completed(futs)):
            fu.result()
            if k % 200 == 0:
                print(f"  {k * BATCH:,}/{len(todo):,} {time.time() - t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), flush=True)


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
    ap.add_argument("--check", action="store_true", help="run the constructed test set only")
    ap.add_argument("--claims", action="store_true",
                    help="type the new catalogue-derived candidates (claim_triples_2026-11-10) instead of the v2.5 scope")
    a = ap.parse_args()
    c303 = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
    labels, prompt = labels_and_prompt(c303)
    schema = make_schema(labels)
    if a.claims:
        return claims_mode(a, labels, prompt, schema)
    if a.check:
        items = [[n, g[0], g[1], g[2], g[3], g[4], g[5], [g[6]]] for n, g in enumerate(GOLD)]
        got = {}
        for i in range(0, len(items), BATCH):
            part = [[k] + it[1:] for k, it in enumerate(items[i:i + BATCH])]
            for k, r in ask(a.port, a.model, prompt, schema, part, 2000).items():
                got[i + k] = r
        ok, res = 0, []
        fins = [finalise(got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}, g[0], g[3], [g[6]]) for n, g in enumerate(GOLD)]
        for i in range(0, len(GOLD), BATCH):
            verify(a.port, a.model, [(g[0], g[3], fins[n], [g[6]]) for n, g in list(enumerate(GOLD))[i:i + BATCH]])
        for n, g in enumerate(GOLD):
            f = fins[n]
            exp = g[7].split("|")
            hit = f["relation"] == exp[0] and (len(exp) == 1 or f["direction"] == exp[1])
            ok += hit
            res.append({"expected": g[7], **f, "correct": hit})
            print(("OK  " if hit else "MISS"), f"{g[7]:28} got {f['relation']}|{f['direction']}  cue={f['cue']!r}", flush=True)
        print(f"v3 constructed test: {ok}/{len(GOLD)} correct", flush=True)
        out = ROOT / f"outputs/results/triple_retype_v3_2026-11-10/GOLD_CHECK_v3_{a.model.split('/')[-1]}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"correct": ok, "n": len(GOLD), "prompt_version": PV, "model": a.model, "items": res}, indent=1) + "\n")
        return
    a.out.mkdir(parents=True, exist_ok=True)
    v25 = [json.loads(line) for f in sorted(glob.glob(str(V25 / "*.jsonl"))) for line in open(f, encoding="utf-8")]
    scope = sorted((r for r in v25 if not r["specific_verified"]), key=lambda r: r["canonical_triple_id"])
    inv = {}
    for line in open(INV, encoding="utf-8"):
        j = json.loads(line)
        inv[j["canonical_triple_id"]] = j
    if a.sample:
        scope = sorted(random.Random(20261110).sample(scope, a.sample), key=lambda r: r["canonical_triple_id"])
    scope = [t for i, t in enumerate(scope) if i % a.nshards == a.shard]
    res = a.out / (f"triples_retyped_v3.shard{a.shard}.jsonl" if a.nshards > 1 else "triples_retyped_v3.jsonl")
    done = set()
    if res.exists():
        done = {json.loads(l)["canonical_triple_id"] for l in open(res, encoding="utf-8") if json.loads(l)["relation"] != "UNPARSED"}
    todo = [t for t in scope if t["canonical_triple_id"] not in done]
    print(f"{len(scope):,} triples in scope; {len(todo):,} to re-type; model {a.model}; {len(labels)} labels", flush=True)
    lock, local = threading.Lock(), threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def run(batch):
        items, ctxs, evs = [], [], []
        for n, t in enumerate(batch):
            tid = t["canonical_triple_id"]
            rows = db().execute("""SELECT e.source_sentence, e.triple_mention_id, e.paper_id, e.char_start, e.char_end, s.section_text_original
                                   FROM relation_evidence e LEFT JOIN section s USING(section_record_id)
                                   WHERE e.canonical_triple_id=? AND e.source_sentence IS NOT NULL
                                   ORDER BY (e.anchor_status='EXACT') DESC, (e.anchor_status='WHITESPACE') DESC LIMIT 2""", (tid,)).fetchall()
            ctx = []
            for sent, mid, pid, cs, ce, text in rows:
                w = window(text, cs, ce)
                ctx.append(w if w else "[[" + " ".join(sent.split())[:600] + "]]")
            j = inv.get(tid, {})
            hints = "; ".join(x for x in (j.get("polarity_variants", ""), j.get("effect_direction_variants", ""),
                                          j.get("assertion_status_variants", "")) if x)
            items.append([n, t["subject"], (j.get("subject") or {}).get("type", ""), j.get("predicate_original", ""),
                          t["object"], (j.get("object") or {}).get("type", ""), hints, ctx])
            ctxs.append(ctx)
            evs.append(rows)
        got = ask(a.port, a.model, prompt, schema, items, 2200)
        fins = [finalise(got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}, t["subject"], t["object"], ctxs[n])
                for n, t in enumerate(batch)]
        verify(a.port, a.model, [(t["subject"], t["object"], fins[n], ctxs[n]) for n, t in enumerate(batch)])
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                fin = fins[n]
                f.write(json.dumps({"canonical_triple_id": t["canonical_triple_id"], "subject": t["subject"], "object": t["object"],
                                    "predicate_original": items[n][3], "v25_relation": t["relation"], **fin,
                                    "new_label_v3": fin["relation"] in NEW3, "n_contexts": len(ctxs[n]),
                                    "context_window": any("[[" in x and not x.startswith("[[") for x in ctxs[n]),
                                    "evidence_mention_ids": [e[1] for e in evs[n]], "paper_ids": sorted({e[2] for e in evs[n]}),
                                    "provenance": "LLM_RETYPED_FROM_CONTEXT", "model": a.model, "prompt_version": PV},
                                   ensure_ascii=False) + "\n")

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
