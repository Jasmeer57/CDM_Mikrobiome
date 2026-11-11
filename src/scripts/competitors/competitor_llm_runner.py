"""Run the Microbiome-CDM LLM steps (Qwen3.5-9B AWQ on a local vLLM server, thinking off, schema-enforced) on
competitor gold corpora and curated metadata. Model-generated predictions only; scoring is done by the per-competitor
scripts (dimb_re_compare.py, midred_compare.py, minerva_compare.py, gutbiomedb_compare.py).

Tasks (--task):
  rel   relation typing with the CDM retype-v3.1 pipeline UNCHANGED (prompt, 89-label set from CDM 3.0.3, cue check,
        word-order direction rule, second-pass verifier; imported from src/scripts/triples/retype_triples_v3.py) on
        gold entity pairs taken from
          - DiMB-RE (Hong et al. 2025): every unordered pair of gold entities inside one sentence, all splits
            (zero-shot, so train/dev/test are all usable as evaluation data); context = previous sentence +
            [[sentence]] + next sentence;
          - MiDRED (Hogan et al. 2024): every annotated microbe-disease pair, all splits; context = [[sentence]];
          - MINERVA gold (1,100 manually labelled sentences, Karkera et al., corrected by the MINERVA authors);
            context = [[evidence sentence]].
        Gold labels are NOT shown to the model; only mention text, a coarse entity type and the sentence(s).
  ner   CDM entity extraction prompt (SYSTEM_PROMPT of src/cdm_pipeline/ner/qwen_sections.py, 14 CDM types, 1,500-char
        chunks) on DiMB-RE documents (tokens joined by single spaces).
  gbdb  for BioProjects in both GutBiomeDB and the CDM: does our free-text health-condition field cover each
        GutBiomeDB-curated disease label, and is each of our condition phrases covered by their list (LLM matcher).

Inputs : outputs/scratch/competitors/{dimb_re,midred,minerva,gutbiomedb}/ (downloaded by the compare scripts / manually,
         see MANIFEST files), CDM 3.0.3 (labels only, read-only), CDM 3.1.0 study table (gbdb, read-only).
Outputs: outputs/results/competitor_compare_2026-11-11/llm_runs/{rel,ner,gbdb}/*.shardN.jsonl (resumable).
Usage  : run inside src/scripts/competitors/competitor_llm.sbatch (starts vLLM, passes --port).
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
sys.path.insert(0, str(ROOT / "src/scripts/terms"))
sys.path.insert(0, str(ROOT / "src"))
import retype_triples_v3 as V3  # noqa: E402

SCR = ROOT / "outputs/scratch/competitors"
OUT = ROOT / "outputs/results/competitor_compare_2026-11-11/llm_runs"
DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
DIMB = SCR / "dimb_re/raw"
MIDRED = SCR / "midred/dec"
MINERVA_GOLD = SCR / "minerva/raw/gold_data_corrected.csv"
GBDB = SCR / "gutbiomedb/data"
BATCH = V3.BATCH


def dimb_docs():
    for sp in ("train", "dev", "test"):
        for line in open(DIMB / f"data_DiMB-RE_ner_reduced_v6.1_trg_abs_{sp}.json", encoding="utf-8"):
            yield sp, json.loads(line)


def doc_tokens(d):
    toks = [t for s in d["sentences"] for t in s]
    starts, k = [], 0
    for s in d["sentences"]:
        starts.append(k)
        k += len(s)
    return toks, starts


def read_jsonl(path):
    """Rows of a (possibly partially written) jsonl file; a truncated last line is skipped."""
    out = []
    if path.exists():
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def rel_items():
    """(item_id, dataset, subject, stype, object, otype, context, gold) for all three gold sets."""
    items = []
    for sp, d in dimb_docs():
        toks, starts = doc_tokens(d)
        sents = [" ".join(s) for s in d["sentences"]]
        for si, (ents, rels) in enumerate(zip(d["ner"], d["relations"])):
            ents = sorted(ents, key=lambda e: (e[0], e[1]))
            ctx = (sents[si - 1] + " " if si else "") + "[[" + sents[si] + "]]" + (" " + sents[si + 1] if si + 1 < len(sents) else "")
            gold = {}
            for r in rels:
                gold.setdefault(((r[0], r[1]), (r[2], r[3])), []).append((r[4], r[5] if len(r) > 5 else "Factual"))
            for i in range(len(ents)):
                for j in range(i + 1, len(ents)):
                    a, b = ents[i], ents[j]
                    sa, sb = (a[0], a[1]), (b[0], b[1])
                    g = [{"label": l, "fact": f, "dir": "SAME"} for l, f in gold.get((sa, sb), [])] + \
                        [{"label": l, "fact": f, "dir": "REVERSED"} for l, f in gold.get((sb, sa), [])]
                    items.append({"id": f"dimb:{sp}:{d['doc_key']}:{si}:{a[0]}-{a[1]}:{b[0]}-{b[1]}", "ds": "dimb", "split": sp,
                                  "doc": d["doc_key"], "sent": si, "subject": " ".join(toks[a[0]:a[1] + 1]), "stype": a[2].lower(),
                                  "object": " ".join(toks[b[0]:b[1] + 1]), "otype": b[2].lower(), "ctx": ctx, "gold": g})
    for sp in ("train", "dev", "test"):
        for n, line in enumerate(open(MIDRED / f"decrypted_{sp}.json", encoding="utf-8")):
            if not line.strip():
                continue
            r = json.loads(line)
            toks, typ = r["text"], {(e[0], e[1]): e[2] for e in r["entities"]}
            for k, rel in enumerate(r["relations"]):
                h, t = (rel[0], rel[1]), (rel[2], rel[3])
                if typ.get(h) != "Bacteria" and typ.get(t) == "Bacteria":
                    h, t = t, h
                items.append({"id": f"midred:{sp}:{n}:{k}", "ds": "midred", "split": sp, "doc": r["pmid"], "sent": n,
                              "subject": " ".join(toks[h[0]:h[1] + 1]), "stype": "organism", "object": " ".join(toks[t[0]:t[1] + 1]),
                              "otype": "disease", "ctx": "[[" + " ".join(toks) + "]]", "gold": [{"label": rel[4]}]})
    with open(MINERVA_GOLD, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            items.append({"id": f"minerva:{r['']}", "ds": "minerva", "split": "all", "doc": r[""], "sent": 0,
                          "subject": r["MICROBE"], "stype": "organism", "object": r["DISEASE"], "otype": "disease",
                          "ctx": "[[" + " ".join(r["EVIDENCE"].split()) + "]]", "gold": [{"label": r["RELATION"]}]})
    return items


def run_rel(a):
    c303 = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True)
    labels, prompt = V3.labels_and_prompt(c303)
    schema = V3.make_schema(labels)
    items = rel_items()
    if a.datasets:
        items = [t for t in items if t["ds"] in a.datasets.split(",")]
    if a.sample:
        import random
        items = sorted(random.Random(20261111).sample(items, a.sample), key=lambda t: t["id"])
    items = [t for i, t in enumerate(items) if i % a.nshards == a.shard]
    out = a.outdir / "rel"
    out.mkdir(parents=True, exist_ok=True)
    res = out / f"rel.shard{a.shard}.jsonl"
    done = {r["id"] for r in read_jsonl(res) if r["relation"] != "UNPARSED"}
    todo = [t for t in items if t["id"] not in done]
    print(f"rel: {len(items):,} items in shard; {len(todo):,} to run; {len(labels)} labels; model {a.model}", flush=True)
    lock = threading.Lock()

    def run(batch):
        its = [[n, t["subject"], t["stype"], "OTHER_RELATION", t["object"], t["otype"], "UNKNOWN", [t["ctx"]]] for n, t in enumerate(batch)]
        got = V3.ask(a.port, a.model, prompt, schema, its, 2200)
        fins = [V3.finalise(got.get(n) or {"relation": "UNPARSED", "direction": "", "cue": ""}, t["subject"], t["object"], [t["ctx"]])
                for n, t in enumerate(batch)]
        V3.verify(a.port, a.model, [(t["subject"], t["object"], fins[n], [t["ctx"]]) for n, t in enumerate(batch)])
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                f.write(json.dumps({**{k: t[k] for k in ("id", "ds", "split", "doc", "sent", "subject", "stype", "object", "otype", "gold")},
                                    **fins[n], "model": a.model, "prompt_version": V3.PV}, ensure_ascii=False) + "\n")

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
        for k, fu in enumerate(as_completed(futs)):
            fu.result()
            if k % 100 == 0:
                print(f"  {k * BATCH:,}/{len(todo):,} {time.time() - t0:.0f}s", flush=True)
    print("rel done", round(time.time() - t0), flush=True)


def chat_sys(port, model, system, user, schema, max_tokens):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": schema, "strict": True}},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


NER_FORMAT = '\nReturn only JSON: {"entities": [{"text": "...", "type": "..."}, ...]}.'


def chat_free(port, model, system, user, max_tokens):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def parse_entities(raw):
    t = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no JSON object")
    ents = json.loads(t[i:j + 1]).get("entities", [])
    return [e for e in ents if isinstance(e, dict) and isinstance(e.get("text"), str)]


def run_ner(a):
    from cdm_pipeline.ner.qwen_sections import SYSTEM_PROMPT, LLM_SCHEMA, LLM_CHUNK_CHARS, LLM_PROMPT_VERSION
    chunks = []
    for sp, d in dimb_docs():
        k0, buf, start = 0, [], 0
        for si, s in enumerate(d["sentences"]):
            txt = " ".join(s)
            if buf and len(" ".join(buf)) + 1 + len(txt) > LLM_CHUNK_CHARS:
                chunks.append({"id": f"{sp}:{d['doc_key']}:{start}", "split": sp, "doc": d["doc_key"], "sent0": start, "text": " ".join(buf)})
                buf, start = [], si
            buf.append(txt)
        if buf:
            chunks.append({"id": f"{sp}:{d['doc_key']}:{start}", "split": sp, "doc": d["doc_key"], "sent0": start, "text": " ".join(buf)})
    chunks = [c for i, c in enumerate(chunks) if i % a.nshards == a.shard]
    out = a.outdir / "ner"
    out.mkdir(parents=True, exist_ok=True)
    res = out / f"ner.shard{a.shard}.jsonl"
    done = {r["id"] for r in read_jsonl(res)}
    todo = [c for c in chunks if c["id"] not in done]
    print(f"ner: {len(chunks)} chunks; {len(todo)} to run", flush=True)
    lock = threading.Lock()

    types = set(LLM_SCHEMA["properties"]["entities"]["items"]["properties"]["type"]["enum"])

    def run(c):
        ents, err = [], None
        for _ in range(3):
            try:
                # Production ran this prompt through Ollama's JSON-schema "format". vLLM's whitespace-free xgrammar decoding
                # returned an empty list for every chunk with this schema (first run, job 28788928), so the JSON shape is
                # requested in text instead and parsed; entries with a type outside the 14 CDM types are dropped.
                raw = chat_free(a.port, a.model, SYSTEM_PROMPT + NER_FORMAT, c["text"], 2048)
                ents = [e for e in parse_entities(raw) if e.get("type") in types]
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:200]
                time.sleep(2)
        with lock, open(res, "a", encoding="utf-8") as f:
            f.write(json.dumps({**c, "entities": ents, "error": err, "model": a.model, "prompt_version": LLM_PROMPT_VERSION + "+json-in-text"},
                               ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(run, todo))
    print("ner done", flush=True)


GBDB_PROMPT = """You compare two descriptions of the health conditions studied in ONE microbiome study (BioProject).
A = condition labels curated by database curators (short codes such as "IBD", "c_difficile_infection", "asd").
B = condition phrases extracted from the paper text.
For every A label answer whether B mentions that condition or a narrower/equivalent one (e.g. A "IBD" is covered by
B "Crohn's disease"; A "diabetes" by B "type 2 diabetes"). For every B phrase answer whether some A label is the same
condition, a broader one, or a narrower one. "healthy", "control" and non-disease words are not conditions: answer
NOT_A_CONDITION for such B phrases. Use only the two lists, no background facts about the study.
Return JSON {"a": [{"n": 0, "covered": true}, ...], "b": [{"n": 0, "match": "MATCH"|"NO_MATCH"|"NOT_A_CONDITION"}, ...]}."""


def run_gbdb(a):
    pairs = [json.loads(l) for l in open(GBDB / "gbdb_condition_pairs.jsonl", encoding="utf-8")]
    out = a.outdir / "gbdb"
    out.mkdir(parents=True, exist_ok=True)
    res = out / f"gbdb.shard{a.shard}.jsonl"
    pairs = [p for i, p in enumerate(pairs) if i % a.nshards == a.shard]
    done = {r["key"] for r in read_jsonl(res)}
    todo = [p for p in pairs if p["key"] not in done]
    print(f"gbdb: {len(pairs)} pairs; {len(todo)} to run", flush=True)
    lock = threading.Lock()

    def run(p):
        A, B = p["gbdb_labels"], p["cdm_phrases"]
        schema = {"type": "object", "additionalProperties": False, "required": ["a", "b"], "properties": {
            "a": {"type": "array", "minItems": len(A), "maxItems": len(A), "items": {"type": "object", "additionalProperties": False,
                  "required": ["n", "covered"], "properties": {"n": {"type": "integer"}, "covered": {"type": "boolean"}}}},
            "b": {"type": "array", "minItems": len(B), "maxItems": len(B), "items": {"type": "object", "additionalProperties": False,
                  "required": ["n", "match"], "properties": {"n": {"type": "integer"},
                                                             "match": {"type": "string", "enum": ["MATCH", "NO_MATCH", "NOT_A_CONDITION"]}}}}}}
        user = "A:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(A)) + "\nB:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(B))
        ans, err = None, None
        for _ in range(3):
            try:
                ans = chat_sys(a.port, a.model, GBDB_PROMPT, user, schema, 60 * (len(A) + len(B)) + 200)
                break
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:200]
                time.sleep(2)
        with lock, open(res, "a", encoding="utf-8") as f:
            f.write(json.dumps({**p, "answer": ans, "error": err, "model": a.model}, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(run, todo))
    print("gbdb done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["rel", "ner", "gbdb", "count"], required=True)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--model", default="cyankiwi/Qwen3.5-9B-AWQ-4bit")
    ap.add_argument("--db303", type=Path, default=DB303)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--datasets", default="")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--outdir", type=Path, default=OUT)
    a = ap.parse_args()
    if a.task == "count":
        from collections import Counter
        its = rel_items()
        print(Counter(t["ds"] for t in its), Counter((t["ds"], bool(t["gold"])) for t in its))
        return
    {"rel": run_rel, "ner": run_ner, "gbdb": run_gbdb}[a.task](a)


if __name__ == "__main__":
    main()
