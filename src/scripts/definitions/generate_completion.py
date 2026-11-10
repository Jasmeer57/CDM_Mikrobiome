"""Model completion of the review fields: abbreviation full forms and synonyms from context, and descriptions of
concepts whose ontology gives no definition (Qwen3.5-4B, local vLLM). All output is MODEL-GENERATED and labelled.

    python src/scripts/definitions/generate_completion.py --scope sample500|accepted --out DIR --port P [--db PATH]

Per term  (term + type + up to 3 corpus sentences): is_abbreviation Y/N, full form (from the context when it is an
          abbreviation), synonyms. -> term_completion.jsonl
Per concept without an ontology definition (label + ontology + id; cache
          outputs/results/ontology_definitions_2026-11-09/concept_ontology_info.jsonl): one-sentence description.
          -> concept_descriptions.jsonl
Resumable; reads CDM 3.0.3 read-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/definitions"))
import generate_term_definitions as G  # noqa: E402  (chat(), contexts(), MODEL)

SAMPLE_KEY = ROOT / "outputs/results/benchmark/human_spotcheck_mappings_2026-11-09/KEY_model_verdicts.csv"
ONTO = ROOT / "outputs/results/ontology_definitions_2026-11-09/concept_ontology_info.jsonl"
PV = "completion-v1-2026-11-09"
TERM_PROMPT = """You annotate terms from human-microbiome research papers. Each item is
[n, "term", "entity type", ["context sentence", ...]] (sentences from the papers where the term occurs).
Answer [n, is_abbreviation, "full form", ["synonym", ...]]:
  is_abbreviation  "Y" if the term is an abbreviation, acronym, gene/protein symbol or short code; otherwise "N".
  full form        if Y: the expansion AS USED in the sentences (prefer one written in the sentences; for gene and
                   protein symbols the official full name). If N: "". Never repeat the term itself.
  synonyms         2 to 5 other names for exactly the same concept (spelling variants, abbreviation <-> long form,
                   common alternative names), in the sense used in the sentences. Never broader or related concepts.
                   If the term is not a scientific concept (number, author name, fragment), give [].
Return JSON {"r": [[n, "Y"|"N", "full form", [synonyms]], ...]}, exactly one entry per item, in order."""
CONCEPT_PROMPT = """Each item is [n, "concept label", "ontology", "concept id"] from a biomedical ontology that gives
no textual definition for it. Answer [n, "description"]: ONE plain sentence (max 30 words) describing what the concept
is, in general biomedical terms. If it is an organism, give its rank and broad group. Do not invent specifics.
Return JSON {"r": [[n, "description"], ...]}, exactly one entry per item, in order."""


def ask(port, prompt, items, width, valid, max_tokens=3000):
    got = {}
    for attempt in range(3):
        try:
            p = json.loads(G.chat(port, prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), max_tokens))
            for r in p.get("r", []):
                if isinstance(r, list) and len(r) == width and isinstance(r[0], int) and 0 <= r[0] < len(items) and valid(r):
                    got[r[0]] = r
            if len(got) == len(items):
                return got
        except Exception:  # noqa: BLE001
            pass
    for n in [n for n in range(len(items)) if n not in got]:          # single-item fallback
        try:
            p = json.loads(G.chat(port, prompt + "\n\nItems:\n" + json.dumps([[0] + items[n][1:]], ensure_ascii=False), 1200))
            r = (p.get("r") or [None])[0]
            if isinstance(r, list) and len(r) == width and valid(r):
                got[n] = [n] + r[1:]
        except Exception:  # noqa: BLE001
            pass
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["sample500", "accepted"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--db", type=Path, default=G.DB)
    ap.add_argument("--workers", type=int, default=32)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    if a.scope == "sample500":
        key = list(csv.DictReader(open(SAMPLE_KEY, encoding="utf-8")))
        term_ids = list(dict.fromkeys(r["term_id"] for r in key))
        concept_ids = list(dict.fromkeys(r["concept_id"] for r in key))
    else:
        term_ids = [t for (t,) in con.execute("SELECT DISTINCT term_id FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'")]
        concept_ids = [c for (c,) in con.execute("SELECT DISTINCT concept_id FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'")]
    terms = {t: (term, ty) for t, term, ty in con.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    labels = {c: (l, s, o) for c, l, s, o in con.execute("SELECT concept_id, concept_label, source_service, ontology_name FROM concept")}
    onto = {}
    if ONTO.exists():
        for l in open(ONTO, encoding="utf-8"):
            r = json.loads(l); onto[r["concept_id"]] = r
    lock = threading.Lock()
    local = threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def done_ids(path, k):
        s = set()
        if path.exists():
            for l in open(path, encoding="utf-8"):
                try:
                    r = json.loads(l)
                    if r.get("status") != "UNPARSED":
                        s.add(r[k])
                except (ValueError, KeyError):
                    pass
        return s

    # ---- terms: abbreviation + full form + synonyms
    tout = a.out / "term_completion.jsonl"
    todo = [t for t in term_ids if t not in done_ids(tout, "term_id")]
    print(f"terms: {len(todo):,} to complete", flush=True)

    def run_terms(batch):
        ctx = [G.contexts(db(), t) for t in batch]
        items = [[n, terms[t][0], terms[t][1], [c[2] for c in ctx[n]]] for n, t in enumerate(batch)]
        got = ask(a.port, TERM_PROMPT, items, 4, lambda r: r[1] in ("Y", "N"))
        with lock, open(tout, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                r = got.get(n)
                ab, ff = (r[1], str(r[2]).strip()) if r else ("", "")
                if ff.lower() == terms[t][0].lower():
                    ff = ""
                syn = [str(x).strip() for x in (r[3] if r and isinstance(r[3], list) else []) if str(x).strip()
                       and str(x).strip().lower() != terms[t][0].lower()][:5]
                f.write(json.dumps({"term_id": t, "term": terms[t][0], "is_abbreviation": ab, "full_form": ff,
                                    "synonyms": syn, "status": "OK" if r else "UNPARSED",
                                    "context_mention_ids": [c[0] for c in ctx[n]],
                                    "provenance": "LLM_GENERATED_FROM_CONTEXT", "model": G.MODEL, "prompt_version": PV},
                                   ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(a.workers) as ex:
        list(as_completed([ex.submit(run_terms, todo[i:i + 8]) for i in range(0, len(todo), 8)]))

    # ---- concepts without an ontology definition: description
    cout = a.out / "concept_descriptions.jsonl"
    need = [c for c in concept_ids if not (onto.get(c) or {}).get("definition") and c not in done_ids(cout, "concept_id")]
    print(f"concepts without ontology definition: {len(need):,}", flush=True)

    def run_concepts(batch):
        items = [[n, labels.get(c, ("", "", ""))[0], (labels.get(c, ("", "", ""))[2] or labels.get(c, ("", "", ""))[1] or ""), c]
                 for n, c in enumerate(batch)]
        got = ask(a.port, CONCEPT_PROMPT, items, 2, lambda r: bool(str(r[1]).strip()), 2000)
        with lock, open(cout, "a", encoding="utf-8") as f:
            for n, c in enumerate(batch):
                r = got.get(n)
                f.write(json.dumps({"concept_id": c, "concept_label": items[n][1], "description": str(r[1]).strip() if r else "",
                                    "status": "OK" if r else "UNPARSED", "provenance": "LLM_GENERATED_FROM_LABEL",
                                    "model": G.MODEL, "prompt_version": PV}, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(a.workers) as ex:
        list(as_completed([ex.submit(run_concepts, need[i:i + 10]) for i in range(0, len(need), 10)]))
    print("done", flush=True)


if __name__ == "__main__":
    main()
