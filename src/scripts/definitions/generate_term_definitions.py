"""Generate contextual definitions, full forms and synonyms of canonical terms with Qwen3.5-4B on local vLLM.

    python src/scripts/definitions/generate_term_definitions.py --scope sample500|all --out DIR [--port 8017]

MODEL-GENERATED TEXT (provenance "LLM_GENERATED_FROM_CONTEXT"): the model reads up to 3 sentences in which the term
occurs in the corpus papers (from distinct papers, offset-anchored where possible) and writes
  - a definition of the term AS USED in those sentences,
  - the full form if the term is an abbreviation and the sentences or standard usage make it unambiguous,
  - synonyms used for it.
Each row records the mention ids and paper ids of the sentences given. Runs on a local GPU (no external service);
paper text is only read, never written out. Not curated, not accuracy-checked. Reads CDM 3.0.3 read-only; writes only
to --out. Resumable.
  sample500 = the 498 distinct terms of outputs/results/benchmark/human_spotcheck_mappings_2026-11-09/
  all       = all 162,409 canonical terms of CDM 3.0.3
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
SAMPLE_KEY = ROOT / "outputs/results/benchmark/human_spotcheck_mappings_2026-11-09/KEY_model_verdicts.csv"
MODEL = "Qwen/Qwen3.5-4B"
PROMPT_VERSION = "termdef-ctx-v1-2026-11-09"
BATCH, NCTX, MAXCHARS = 8, 3, 450
PROMPT = """You annotate terms from human-microbiome research papers. Each item is
[n, "term", "entity type", ["context sentence 1", "context sentence 2", ...]] where the sentences are from the papers
in which the term occurs. For each item answer [n, status, "definition", "full form", ["synonym", ...]]:
  status DEFINED        the sentences (with general biomedical knowledge) show what the term means here.
         definition     ONE plain sentence, at most 30 words, defining the term AS IT IS USED in these sentences
                        (its sense in this context, e.g. "IBD" in a gut study = inflammatory bowel disease). Do not
                        copy the sentences; do not report study results or numbers.
         full form      if the term is an abbreviation or acronym: its expansion as used here (prefer an expansion
                        written in the sentences); otherwise "".
         synonyms       up to 5 other names for the same concept (spelling variants, the abbreviation if the term is
                        the long form, common alternative names); [] if none. Never list broader or related concepts.
  status NOT_A_CONCEPT  the term is not a scientific concept (a number, statistic, p-value, fragment, figure/table label,
                        author name, generic word such as "group" or "data"): "", "", [].
  status UNKNOWN        the sentences do not make the meaning clear and you are not sure: "", "", []. Do not guess.
Return JSON {"r": [[n, status, "definition", "full form", [synonyms]], ...]}, exactly one entry per item, in order."""
STATUSES = {"DEFINED", "NOT_A_CONCEPT", "UNKNOWN"}
FILL_PROMPT = """You annotate terms from human-microbiome research papers. Each item is
[n, "term", "entity type", ["context sentence", ...]]. Every item MUST get a short description.
Answer [n, kind, "definition", "full form", ["synonym", ...]]:
  kind GENERAL      the term is a scientific concept: ONE plain sentence (max 30 words) giving its general
                    biomedical meaning, in the sense of its entity type; use the sentences if they help.
  kind NON_CONCEPT  the term is not a scientific concept: ONE short sentence saying what the string is, e.g.
                    "An author name cited in the paper.", "A numeric value reported in the results.",
                    "A fragment of the species name Proteus mirabilis.", "A human gene symbol (chromosome 14 ORF 1)."
  full form / synonyms as before ("" and [] when not applicable). Do not invent study results.
Return JSON {"r": [[n, kind, "definition", "full form", [synonyms]], ...]}, one entry per item, in order."""
FILL_KINDS = {"GENERAL", "NON_CONCEPT"}


def chat(port, content, max_tokens=4000):
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def terms_for(scope):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    if scope == "all":
        return list(con.execute("SELECT term_id, term, cdm_type FROM canonical_term ORDER BY term_id"))
    ids = list(dict.fromkeys(r["term_id"] for r in csv.DictReader(open(SAMPLE_KEY, encoding="utf-8"))))
    q = {t: (term, ty) for t, term, ty in con.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    return [(t, *q[t]) for t in ids]


def contexts(con, term_id):
    """Up to NCTX sentences from distinct papers; EXACT offsets first, then moderate length.
    Bounded: reads at most 200 candidate rows per pass (frequent terms have >100k mentions)."""
    cand = []
    for exact in (True, False):
        q = ("SELECT mention_id, paper_id, supporting_sentence FROM term_mention WHERE canonical_term_id=? "
             "AND supporting_sentence IS NOT NULL AND length(supporting_sentence) >= 30 "
             + ("AND offset_status='EXACT' " if exact else "") + "LIMIT 200")
        cand += list(con.execute(q, (term_id,)))
        if len({c[1] for c in cand}) >= NCTX:
            break
    cand.sort(key=lambda c: abs(len(c[2]) - 200))
    out, papers = [], set()
    for mid, pid, s in cand:
        if pid in papers:
            continue
        papers.add(pid)
        out.append((mid, pid, " ".join(s.split())[:MAXCHARS]))
        if len(out) == NCTX:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["sample500", "all"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=8017)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--db", type=Path, default=None, help="read-only copy of the CDM (e.g. node-local)")
    a = ap.parse_args()
    global DB
    if a.db:
        DB = a.db
    a.out.mkdir(parents=True, exist_ok=True)
    res = a.out / "definitions.jsonl"
    done = set()
    if res.exists():                                    # tolerate a line cut off by a cancelled job
        if res.stat().st_size and not res.read_bytes().endswith(b"\n"):
            with open(res, "a", encoding="utf-8") as f:
                f.write("\n")
        for l in open(res, encoding="utf-8"):
            try:
                r = json.loads(l)
                if r.get("status") != "UNPARSED" or r.get("first_pass_status"):
                    done.add(r["term_id"])
            except (ValueError, KeyError):
                pass
    todo = [t for t in terms_for(a.scope) if t[0] not in done]
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    print(f"{len(done):,} done; {len(todo):,} terms in {len(batches):,} requests", flush=True)
    lock, stats, local = threading.Lock(), Counter(), threading.local()

    def db():
        if not hasattr(local, "con"):
            local.con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)
        return local.con

    def run(batch):
        ctx = [contexts(db(), tid) for tid, _, _ in batch]
        rows = [[n, term, ty, [c[2] for c in ctx[n]]] for n, (_, term, ty) in enumerate(batch)]
        got, err = {}, ""
        for attempt in range(3):
            try:
                p = json.loads(chat(a.port, PROMPT + "\n\nItems:\n" + json.dumps(rows, ensure_ascii=False)))
                for r in p.get("r", []):
                    if isinstance(r, list) and len(r) == 5 and isinstance(r[0], int) and 0 <= r[0] < len(batch) \
                            and r[1] in STATUSES:
                        syn = [str(x).strip() for x in (r[4] if isinstance(r[4], list) else []) if str(x).strip()][:5]
                        got[r[0]] = (r[1], str(r[2]).strip(), str(r[3]).strip(), syn)
                if len(got) == len(batch):
                    break
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:200]; time.sleep(2 * (attempt + 1))
        for n in [n for n in range(len(batch)) if n not in got]:      # single-item fallback
            for attempt in range(2):
                try:
                    one = [[0, rows[n][1], rows[n][2], rows[n][3]]]
                    p = json.loads(chat(a.port, PROMPT + "\n\nItems:\n" + json.dumps(one, ensure_ascii=False), 1500))
                    r = (p.get("r") or [None])[0]
                    if isinstance(r, list) and len(r) == 5 and r[1] in STATUSES:
                        syn = [str(x).strip() for x in (r[4] if isinstance(r[4], list) else []) if str(x).strip()][:5]
                        got[n] = (r[1], str(r[2]).strip(), str(r[3]).strip(), syn)
                        break
                    err = "malformed single-item answer"
                except Exception as e:  # noqa: BLE001
                    err = repr(e)[:200]
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, (tid, term, ty) in enumerate(batch):
                st, d, ff, syn = got.get(n, ("UNPARSED", "", "", []))
                if st != "DEFINED":
                    d, ff, syn = "", "", []
                stats[st] += 1
                f.write(json.dumps({"term_id": tid, "term": term, "cdm_type": ty, "status": st, "definition": d,
                                    "full_form": ff, "synonyms": syn,
                                    "context_mention_ids": [c[0] for c in ctx[n]],
                                    "context_paper_ids": [c[1] for c in ctx[n]], "n_context": len(ctx[n]),
                                    "provenance": "LLM_GENERATED_FROM_CONTEXT", "model": MODEL,
                                    "prompt_version": PROMPT_VERSION, "error": err if st == "UNPARSED" else ""},
                                   ensure_ascii=False) + "\n")

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for k, _ in enumerate(as_completed([ex.submit(run, b) for b in batches]), 1):
            if k % 200 == 0 or k == len(batches):
                print(f"{k:,}/{len(batches):,} requests, {time.time() - t0:.0f}s, {dict(stats)}", flush=True)
    # ---- phase 2: every term must end with a description (general definition or what the string is)
    latest = {}
    for l in open(res, encoding="utf-8"):
        try:
            r = json.loads(l); latest[r["term_id"]] = r
        except ValueError:
            pass
    need = [(t, x["term"], x["cdm_type"]) for t, x in latest.items() if x["status"] not in ("DEFINED", "GENERAL", "NON_CONCEPT")]
    fb = [need[i:i + BATCH] for i in range(0, len(need), BATCH)]
    print(f"phase 2: {len(need):,} terms without a contextual definition", flush=True)

    def fill(batch):
        ctx = [contexts(db(), tid) for tid, _, _ in batch]
        rows2 = [[n, term, ty, [c[2] for c in ctx[n]]] for n, (_, term, ty) in enumerate(batch)]
        got = {}
        for attempt in range(3):
            try:
                p = json.loads(chat(a.port, FILL_PROMPT + "\n\nItems:\n" + json.dumps(rows2, ensure_ascii=False)))
                for r in p.get("r", []):
                    if isinstance(r, list) and len(r) == 5 and isinstance(r[0], int) and 0 <= r[0] < len(batch) \
                            and r[1] in FILL_KINDS and str(r[2]).strip():
                        syn = [str(x).strip() for x in (r[4] if isinstance(r[4], list) else []) if str(x).strip()][:5]
                        got[r[0]] = (r[1], str(r[2]).strip(), str(r[3]).strip(), syn)
                if len(got) == len(batch):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        for n in [n for n in range(len(batch)) if n not in got]:
            try:
                one = [[0, rows2[n][1], rows2[n][2], rows2[n][3]]]
                p = json.loads(chat(a.port, FILL_PROMPT + "\n\nItems:\n" + json.dumps(one, ensure_ascii=False), 1500))
                r = (p.get("r") or [None])[0]
                if isinstance(r, list) and len(r) == 5 and r[1] in FILL_KINDS and str(r[2]).strip():
                    got[n] = (r[1], str(r[2]).strip(), str(r[3]).strip(), [str(x).strip() for x in (r[4] if isinstance(r[4], list) else [])][:5])
            except Exception:  # noqa: BLE001
                pass
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, (tid, term, ty) in enumerate(batch):
                kind, d, ff, syn = got.get(n, ("UNPARSED", "", "", []))
                f.write(json.dumps({"term_id": tid, "term": term, "cdm_type": ty, "status": kind, "definition": d,
                                    "full_form": ff, "synonyms": syn,
                                    "first_pass_status": latest[tid]["status"],
                                    "context_mention_ids": [c[0] for c in ctx[n]],
                                    "context_paper_ids": [c[1] for c in ctx[n]], "n_context": len(ctx[n]),
                                    "provenance": "LLM_GENERATED_GENERAL" if kind == "GENERAL" else "LLM_GENERATED_DESCRIPTION",
                                    "model": MODEL, "prompt_version": PROMPT_VERSION + "+fill-v1", "error": ""},
                                   ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(a.workers) as ex:
        list(as_completed([ex.submit(fill, b) for b in fb]))
    rows = []
    for l in open(res, encoding="utf-8"):
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    rows = list({r["term_id"]: r for r in rows}.values())       # a later retry supersedes an UNPARSED row
    summ = Counter(r["status"] for r in rows)
    json.dump({"scope": a.scope, "model": MODEL, "prompt_version": PROMPT_VERSION,
               "provenance": "LLM_GENERATED_FROM_CONTEXT",
               "input": f"term + cdm_type + up to {NCTX} corpus sentences from distinct papers (local GPU)",
               "terms": len(rows), "status": dict(summ),
               "with_full_form": sum(1 for r in rows if r["full_form"]),
               "with_synonyms": sum(1 for r in rows if r["synonyms"]),
               "without_context": sum(1 for r in rows if not r["n_context"]),
               "note": "model-generated; not extracted verbatim, not curated, not accuracy-checked. Definitions may "
                       "paraphrase sentences of papers whose text may not be redistributed: rights-check before release."},
              open(a.out / "summary.json", "w"), indent=1)
    print(json.dumps(dict(summ)))


if __name__ == "__main__":
    main()
