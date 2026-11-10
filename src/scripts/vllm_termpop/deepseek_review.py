"""DeepSeek-R1-Distill-Qwen-7B (unsloth bnb 4-bit) review of the terminology layer:
terms, ontology mappings, definitions and knowledge triples.

A third, reasoning model (different family from Qwen3.5 and Gemma) reviews each
item and proposes keep / correct / remove. Nothing existing is modified: inputs
are read-only and every output is a NEW file under
outputs/results/deepseek_review/:

    <stage>/responses.shard*.jsonl        raw model answers (resumable cache)
    corrected/canonical_terms.reviewed.jsonl
    corrected/term_concept_map.reviewed.jsonl
    corrected/term_definitions.reviewed.jsonl
    corrected/canonical_triples.reviewed.jsonl
    corrected/REMOVED_*.jsonl              everything removed, with the reason
    corrected/DEEPSEEK_REVIEW.md           counts and the removal rules

Removal is two-signal: an item is removed only when DeepSeek AND an independent
signal agree (Gemma G9 / C4 verdicts, the quote check, or a deterministic junk
pattern). DeepSeek alone -> REVIEW_REQUIRED, never removal.

    python deepseek_review.py build                       # request counts
    python deepseek_review.py run --shard 0 --nshards 12 --host http://127.0.0.1:8000
    python deepseek_review.py apply
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import gaplib as G

ROOT = G.REPO_ROOT
OUT = G.RESULTS / "deepseek_review"
MODEL = "casperhansen/deepseek-r1-distill-qwen-7b-awq"  # DeepSeek-R1-Distill-Qwen-7B, 4-bit AWQ (vLLM 0.32 cannot load the unsloth bnb-4bit build)
TERMS = ROOT / "releases/frozen_output/02_data_catalogue/terminology/canonical_terms.jsonl"
MAPS = ROOT / "releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2/mapping_remapped.jsonl"
DEFS_REL = ROOT / "releases/terminology/1.0.0/term_definitions.jsonl"
DEFS_G8 = G.GAP_DIR / "G8/term_definitions_llm.jsonl"
G9 = G.GAP_DIR / "G9/mapping_adjudication.jsonl"
G7 = G.GAP_DIR / "G7/type_harmonization.jsonl"
TRIPLES = ROOT / "pipelines/corpus_v2/data/canonical_triples.jsonl"
TMENTIONS = ROOT / "pipelines/corpus_v2/data/triple_mentions.jsonl"
C4 = ROOT / "releases/frozen_output/02_data_catalogue/judge/C4_full_verdicts.jsonl"
CDM_TYPES = ["ORGANISM", "PROTEIN", "CHEMICAL", "DISEASE", "DNA_RNA", "CELL_TYPE", "SAMPLE_METHOD", "LAB_METHOD",
             "DATA_ANALYSIS", "PATHWAY", "EXPERIMENTAL_METHOD", "STUDY_DESIGN", "GENOMICS", "CLINICAL"]
JUNK = re.compile(r"^[\W\d_]+$|^\W|p\s*[<=>]|\d+\.\d+e[-+]?\d|^\d|^(fig|table|supplementary)\b|"
                  r"\b(et al|doi|http)\b|[=<>]{1}\s*\d", re.I)

TAIL = ("Think step by step but briefly, then output ONLY the JSON object as your final answer "
        "(no markdown fence).")
SYS = {
    "terms": f"""You curate a terminology of human-microbiome research terms. For each ITEM (a canonical term,
its current entity type, alternative types seen, and paper count) decide:
- "keep": false if it is NOT a scientific concept term — numbers, statistics, p-values, figure/table
  labels, sentence fragments, author names, generic words ("group", "level", "data"), formatting debris;
  true otherwise.
- "type": the correct entity type, one of {CDM_TYPES}, or "UNRESOLVED".
- "reason": a few words.
Return {{"results": [{{"id": "...", "keep": true, "type": "...", "reason": "..."}}]}}. {TAIL}""",
    "maps": f"""You audit ontology mappings for human-microbiome terms. For each ITEM decide how the concept relates
to the term (used as the given entity type): EXACT (same concept), BROADER, NARROWER, RELATED (associated but
different), or WRONG (unrelated or wrong sense, e.g. a moth genus for a bacterium, a person name).
Return {{"results": [{{"id": "...", "relation": "EXACT|BROADER|NARROWER|RELATED|WRONG", "reason": "..."}}]}}. {TAIL}""",
    "defs": f"""You check definitions extracted verbatim from scientific papers. For each ITEM (term + the text claimed
to define it) decide "verdict": DEFINITION (the text defines or expands the term), MENTION (the term only appears,
the text does not define it), or WRONG_TERM (the text defines a different term). Give "reason".
Return {{"results": [{{"id": "...", "verdict": "...", "reason": "..."}}]}}. {TAIL}""",
    "triples": f"""You check knowledge triples (subject - relation - object) extracted from human-microbiome papers against
the sentence they came from. For each ITEM decide "verdict": SUPPORTED (the sentence states this relation),
PARTIAL (right entities, relation or polarity wrong), NOT_SUPPORTED (the sentence does not state it, or the
entities are not real entities). If PARTIAL, give "corrected_relation" and/or "corrected_polarity"
(POSITIVE|NEGATIVE). Give "reason".
Return {{"results": [{{"id": "...", "verdict": "...", "corrected_relation": "", "corrected_polarity": "", "reason": "..."}}]}}. {TAIL}""",
}
BATCH = {"terms": 25, "maps": 20, "defs": 15, "triples": 10}


def jl(p):
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


# ── items ────────────────────────────────────────────────────────────────────
def term_scope():
    """Terms that matter downstream: in >=2 papers, flagged non-concept, or referenced by
    a primary mapping, a definition or a linked triple."""
    ref = {m["term_id"] for m in jl(MAPS) if m.get("is_canonical_candidate")}
    for p in (DEFS_REL, DEFS_G8):
        if p.exists():
            for d in jl(p):
                ref.update(d.get("canonical_term_ids") or [d.get("term_id")])
    for p in (G.GAP_DIR / "E/g6_direct.jsonl", G.GAP_DIR / "G6/triple_entity_links.jsonl"):
        if p.exists():
            ref.update(r.get("term_id") or r.get("term_id_llm") for r in jl(p))
    return ref


def items_terms():
    ref = term_scope()
    out = []
    for t in jl(TERMS):
        if t.get("n_papers", 0) >= 2 or t.get("is_non_concept_surface") or t["term_id"] in ref:
            out.append({"id": t["term_id"], "term": t["term"][:120], "type": t["cdm_type"],
                        "alternatives": (t.get("alternative_types") or [])[:5], "n_papers": t.get("n_papers")})
    return out


def items_maps():
    return [{"id": m["mapping_id"], "term": m["term"][:120], "type": m.get("cdm_type"),
             "concept": str(m.get("concept_label") or "")[:120], "source": m.get("source_service")}
            for m in jl(MAPS) if m.get("is_canonical_candidate")]


def items_defs():
    out = []
    for d in jl(DEFS_REL):
        out.append({"id": d["definition_id"], "term": d.get("term"), "text": str(d.get("definition_text"))[:400]})
    if DEFS_G8.exists():
        for i, d in enumerate(jl(DEFS_G8)):
            out.append({"id": f"G8_{i:07d}", "term": d["term"], "text": d["definition_text"][:400]})
    return out


def items_triples():
    sent = {}
    for m in jl(TMENTIONS):
        s = m.get("source_sentence")
        if s and m["canonical_triple_id"] not in sent:
            sent[m["canonical_triple_id"]] = (s[:500], m.get("polarity"))
    out = []
    for t in jl(TRIPLES):
        s, pol = sent.get(t["canonical_triple_id"], ("", ""))
        out.append({"id": t["canonical_triple_id"], "subject": t["subject_display_label"][:100],
                    "relation": t["relation_normalized"], "object": t["object_display_label"][:100],
                    "polarity": pol, "sentence": s})
    return out


ITEMS = {"terms": items_terms, "maps": items_maps, "defs": items_defs, "triples": items_triples}


def build():
    reqs = []
    for st, fn in ITEMS.items():
        items = sorted(fn(), key=lambda x: x["id"])
        for j in range(0, len(items), BATCH[st]):
            reqs.append({"key": f"{st}|{items[j]['id']}", "stage": st, "items": items[j:j + BATCH[st]]})
    return reqs


# ── client: reasoning model, JSON taken from the final answer ────────────────
def parse_json(text):
    text = re.sub(r"(?s)^.*</think>", "", text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object in answer")
    return json.loads(text[a:b + 1])


def ask(host, stage, items, timeout=1800):
    body = {"model": MODEL, "temperature": 0.6, "top_p": 0.95, "max_tokens": 8192,
            "messages": [{"role": "system", "content": SYS[stage]},
                         {"role": "user", "content": "ITEMS:\n" + json.dumps(items, ensure_ascii=False)}]}
    req = urllib.request.Request(host.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ch = json.loads(resp.read())["choices"][0]
    if ch.get("finish_reason") == "length":
        raise ValueError("finish_reason=length")
    return parse_json((ch.get("message") or {}).get("content") or "")


def run(shard, nshards, host, parallel):
    reqs = [r for r in build() if G.shard_of(r["key"], nshards) == shard]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"responses.shard{shard}.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(l)["key"] for l in open(path) if '"answer"' in l}
    todo = [r for r in reqs if r["key"] not in done]
    log = G.log_to(OUT / f"run.shard{shard}.log")
    log(f"shard {shard}/{nshards}: {len(reqs)} requests, {len(todo)} to run "
        f"({Counter(r['stage'] for r in todo)})")

    def work(r, items=None, depth=0):
        items = r["items"] if items is None else items
        last = None
        for _ in range(2):  # sampled decoding (R1 recommendation): one retry on bad JSON
            try:
                return ask(host, r["stage"], items), None
            except Exception as ex:  # noqa: BLE001
                last = repr(ex)
        if len(items) > 1 and depth < 4:  # too long or unparseable: halve
            h = len(items) // 2
            a, ea = work(r, items[:h], depth + 1)
            b, eb = work(r, items[h:], depth + 1)
            if ea or eb:
                return None, ea or eb
            return {"results": (a or {}).get("results", []) + (b or {}).get("results", [])}, None
        return None, last

    n = err = 0
    t0 = time.time()
    with open(path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(parallel) as pool:
        futs = {pool.submit(work, r): r for r in todo}
        for f in as_completed(futs):
            r = futs[f]
            ans, e = f.result()
            fh.write(json.dumps({"key": r["key"], "stage": r["stage"],
                                 **({"error": e} if e else {"answer": ans})}, ensure_ascii=False) + "\n")
            n += 1
            err += bool(e)
            if n % 100 == 0 or n == len(todo):
                fh.flush()
                log(f"  {n}/{len(todo)} done, {err} errors, {n / max(time.time() - t0, 1):.2f} req/s")
    return 1 if err else 0


# ── apply: two-signal rules, new files only ──────────────────────────────────
def _norm_answer(x):
    """The 7B reasoning model is loose with formats (smoke test): "keep": "false",
    lower-case enums, invalid types. Normalise; invalid values become None."""
    k = x.get("keep")
    if isinstance(k, str):
        x["keep"] = {"true": True, "false": False}.get(k.strip().lower())
    for f in ("relation", "verdict", "type", "corrected_polarity"):
        if isinstance(x.get(f), str):
            x[f] = x[f].strip().upper().replace(" ", "_")
    if x.get("type") and x["type"] not in CDM_TYPES + ["UNRESOLVED"]:
        x["type"] = None
    return x


def answers(stage):
    """{item id: answer}. Each answer is matched to an id of ITS OWN batch; ids the
    model mangled (dropped prefix) are matched by suffix within that batch only."""
    batches = {r["key"]: [it["id"] for it in r["items"]] for r in build() if r["stage"] == stage}
    out = {}
    for p in sorted(OUT.glob("responses.shard*.jsonl")):
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            if r.get("stage") != stage or "answer" not in r:
                continue
            ids = batches.get(r["key"], [])
            for x in G.flatten(r["answer"], "results"):
                rid = str(x.get("id"))
                if rid not in ids:
                    cand = [i for i in ids if rid and (i.endswith(rid) or rid.endswith(i))]
                    if len(cand) != 1:
                        continue
                    rid = cand[0]
                out[rid] = _norm_answer(x)
    return out


def apply():
    C = OUT / "corrected"
    C.mkdir(parents=True, exist_ok=True)
    rep = {}

    # terms
    A = answers("terms")
    g7 = {}
    if G7.exists():
        for r in jl(G7):
            if r.get("canonical_term_id") and r.get("type_llm") in CDM_TYPES:
                g7[r["canonical_term_id"]] = r["type_llm"]
    kept, removed, s = [], [], Counter()
    for t in jl(TERMS):
        a = A.get(t["term_id"])
        row = dict(t, ds_reviewed=bool(a))
        if a:
            junk = bool(JUNK.search(t["term"])) or bool(t.get("is_non_concept_surface"))
            if a.get("keep") is False and (junk or t.get("n_papers", 0) <= 1):
                removed.append(dict(row, removal_reason=f"deepseek_not_a_concept+{'pattern' if junk else 'single_paper'}: {a.get('reason', '')}"))
                s["removed"] += 1
                continue
            if a.get("keep") is False:
                row["review_status"], row["ds_flag"] = "REVIEW_REQUIRED", "deepseek_not_a_concept_only"
                s["flagged_not_concept_only"] += 1
            ty = a.get("type")
            if ty in CDM_TYPES and ty != t["cdm_type"]:
                if g7.get(t["term_id"]) == ty or ty in (t.get("alternative_types") or []):
                    row["cdm_type_original"], row["cdm_type"] = t["cdm_type"], ty
                    row["type_source"] = "deepseek+gemma" if g7.get(t["term_id"]) == ty else "deepseek+alternative_seen"
                    s["type_corrected"] += 1
                else:
                    row["cdm_type_ds_suggestion"] = ty
                    s["type_suggestion_only"] += 1
        kept.append(row)
    G.write_jsonl(C / "canonical_terms.reviewed.jsonl", kept)
    G.write_jsonl(C / "REMOVED_terms.jsonl", removed)
    s["reviewed"] = sum(r["ds_reviewed"] for r in kept) + len(removed)
    rep["terms"] = dict(s)
    removed_terms = {r["term_id"] for r in removed}

    # mappings (primary candidates), joined with Gemma G9
    A = answers("maps")
    g9 = {r["mapping_id"]: r.get("relation_llm") for r in jl(G9)} if G9.exists() else {}
    kept, removed, s = [], [], Counter()
    for m in jl(MAPS):
        if not m.get("is_canonical_candidate"):
            continue
        a = A.get(m["mapping_id"], {})
        ds, gm = a.get("relation"), g9.get(m["mapping_id"])
        row = {"mapping_id": m["mapping_id"], "term_id": m["term_id"], "term": m["term"], "concept_id": m.get("concept_id"),
               "concept_label": m.get("concept_label"), "relation_gemma_g9": gm, "relation_deepseek": ds,
               "mapping_disposition_original": m.get("mapping_disposition")}
        if m["term_id"] in removed_terms:
            removed.append(dict(row, removal_reason="term_removed"))
            s["removed_with_term"] += 1
            continue
        if ds == "WRONG" and gm == "WRONG":
            removed.append(dict(row, removal_reason=f"deepseek+gemma WRONG: {a.get('reason', '')}"))
            s["removed_both_wrong"] += 1
            continue
        if ds == gm == "EXACT":
            row["mapping_disposition"], row["mapping_relation"] = "ACCEPTED", "EXACT"
            s["accepted_both_exact"] += 1
        elif ds and gm and ds == gm:
            row["mapping_disposition"], row["mapping_relation"] = "ACCEPTED", ds
            s[f"accepted_both_{ds.lower()}"] += 1
        else:
            row["mapping_disposition"] = "REVIEW_REQUIRED"
            s["review_disagreement_or_missing"] += 1
        kept.append(row)
    G.write_jsonl(C / "term_concept_map.reviewed.jsonl", kept)
    G.write_jsonl(C / "REMOVED_mappings.jsonl", removed)
    rep["mappings"] = dict(s)

    # definitions (already exact-quote verified; DeepSeek checks it is a definition)
    A = answers("defs")
    kept, removed, s = [], [], Counter()
    rows = [dict(d, _id=d["definition_id"], _src="terminology_1.0.0") for d in jl(DEFS_REL)]
    if DEFS_G8.exists():
        rows += [dict(d, _id=f"G8_{i:07d}", _src="G8_qwen") for i, d in enumerate(jl(DEFS_G8))]
    for d in rows:
        a = A.get(d["_id"], {})
        v = a.get("verdict")
        d["verdict_deepseek"] = v
        ids = d.get("canonical_term_ids") or [d.get("term_id")]
        if ids and all(i in removed_terms for i in ids if i):
            removed.append(dict(d, removal_reason="term_removed"))
            s["removed_with_term"] += 1
        elif v in ("MENTION", "WRONG_TERM"):
            removed.append(dict(d, removal_reason=f"deepseek {v}: {a.get('reason', '')}"))
            s[f"removed_{v.lower()}"] += 1
        else:
            kept.append(d)
            s["kept" if v == "DEFINITION" else "kept_unreviewed"] += 1
    G.write_jsonl(C / "term_definitions.reviewed.jsonl", kept)
    G.write_jsonl(C / "REMOVED_definitions.jsonl", removed)
    rep["definitions"] = dict(s)

    # triples, joined with Gemma C4 sensibility
    A = answers("triples")
    c4 = {r["item_id"].split("|", 1)[1]: r.get("verdict") for r in jl(C4)} if C4.exists() else {}
    kept, removed, s = [], [], Counter()
    for t in jl(TRIPLES):
        a = A.get(t["canonical_triple_id"], {})
        v, g = a.get("verdict"), c4.get(t["canonical_triple_id"])
        row = dict(t, verdict_deepseek=v, verdict_gemma_c4=g)
        if v == "NOT_SUPPORTED" and g and g != "SENSIBLE":
            removed.append(dict(row, removal_reason=f"deepseek NOT_SUPPORTED + gemma {g}: {a.get('reason', '')}"))
            s["removed_both"] += 1
            continue
        if v == "PARTIAL":
            if a.get("corrected_relation"):
                row["relation_corrected_ds"] = a["corrected_relation"]
            if a.get("corrected_polarity") in ("POSITIVE", "NEGATIVE"):
                row["polarity_corrected_ds"] = a["corrected_polarity"]
            row["review_status"] = "REVIEW_REQUIRED"
            s["partial_correction_proposed"] += 1
        elif v == "NOT_SUPPORTED":
            row["review_status"] = "REVIEW_REQUIRED"
            s["flagged_deepseek_only"] += 1
        else:
            s["supported" if v == "SUPPORTED" else "unreviewed"] += 1
        kept.append(row)
    G.write_jsonl(C / "canonical_triples.reviewed.jsonl", kept)
    G.write_jsonl(C / "REMOVED_triples.jsonl", removed)
    rep["triples"] = dict(s)

    (C / "_deepseek_review_report.json").write_text(json.dumps(rep, indent=2) + "\n")
    L = ["# DeepSeek-R1-Distill-Qwen-7B review — terms, mappings, definitions, triples", "",
         f"Model `{MODEL}` (4-bit, vLLM, reasoning). Inputs untouched; all outputs are new files in this folder.", "",
         "Removal needs two signals; DeepSeek alone only flags `REVIEW_REQUIRED`:", "",
         "- **terms:** DeepSeek says not a concept AND (junk pattern / non-concept flag, or the term occurs in one paper only). "
         "Type corrected only if Gemma (G7) agrees or the type was already seen for the term.",
         "- **mappings:** removed if DeepSeek AND Gemma (G9) both say WRONG; ACCEPTED if both agree on the relation; else REVIEW_REQUIRED.",
         "- **definitions:** text is an exact source quote already; removed if DeepSeek says it only mentions the term or defines another.",
         "- **triples:** removed if DeepSeek NOT_SUPPORTED AND Gemma C4 not SENSIBLE; PARTIAL gets proposed corrections + REVIEW_REQUIRED.",
         "- anything attached to a removed term is removed with it.", ""]
    for k, v in rep.items():
        L += [f"## {k}", "", *[f"- {a}: {b:,}" for a, b in sorted(v.items())], ""]
    (C / "DEEPSEEK_REVIEW.md").write_text("\n".join(L))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "apply"])
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--parallel", type=int, default=96)
    ap.add_argument("--limit", type=int, default=0, help="smoke: first N requests of the shard")
    a = ap.parse_args()
    if a.cmd == "build":
        rs = build()
        print(Counter(r["stage"] for r in rs), "items:", Counter({st: sum(len(r["items"]) for r in rs if r["stage"] == st) for st in BATCH}))
    elif a.cmd == "apply":
        apply()
    else:
        if a.limit:
            _b = build
            build = lambda: [r for r in _b() if G.shard_of(r["key"], a.nshards) == a.shard][:a.limit]  # noqa: E731
        raise SystemExit(run(a.shard, a.nshards, a.host, a.parallel))
