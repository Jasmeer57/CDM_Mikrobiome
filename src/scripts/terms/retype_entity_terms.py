"""Re-type generic ENTITY terms into specific types (local LLM, schema-enforced). Model-generated layer; the frozen
CDM releases are not modified. Freeze exception: new model run, PENDING project-lead approval (CHANGE_RECORD).

    python src/scripts/terms/retype_entity_terms.py --out DIR --port P [--model M] [--db303 PATH] [--shard i --nshards n]
                                                    [--limit N] [--sample N]

Scope: terms kept in CDM 3.1.0 (term_curation.kept = True) whose cdm_type is ENTITY (53,780).
Per term the model reads: the term, its merged variants, the model definition (CDM 3.1.0 term_curation.definition)
and up to 3 corpus sentences from distinct papers (CDM 3.0.3 term_mention). It returns
  type   one of the 14 CDM types, or a PROPOSED extension type for things the 14 cannot hold (ANATOMY_OR_BODY_SITE,
         POPULATION_OR_HOST_GROUP, MEASURE_OR_UNIT, GEOGRAPHY), or NOT_A_CONCEPT (ordinary words, verbs, fragments,
         numbers, names of people or journals);
  basis  CONTEXT (the sentences show the sense) or NAME_ONLY (decided from the term alone).
Output: DIR/entity_retyped.jsonl (resumable). Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/definitions"))
import generate_term_definitions as G  # noqa: E402  (contexts(): up to 3 sentences from distinct papers)

DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
PV = "entity-retype-v1.1-2026-11-10"
BATCH = 12
TYPES = {
    "ORGANISM": "a microorganism, virus, plant or animal taxon, strain or named organism group (e.g. Bacteroides, E. coli, mice)",
    "CHEMICAL": "a chemical, metabolite, drug, nutrient, food compound (e.g. butyrate, metformin, fibre)",
    "DISEASE": "a disease, disorder, symptom or pathological state (e.g. IBD, obesity, diarrhoea, inflammation)",
    "PROTEIN": "a protein, enzyme, antibody, cytokine, receptor (e.g. IL-6, lipase)",
    "DNA_RNA": "a gene, genetic element, nucleic-acid molecule or marker (e.g. 16S rRNA gene, V4 region, plasmid)",
    "CELL_TYPE": "a cell type or cell population (e.g. T cells, macrophages, epithelial cells)",
    "GENOMICS": "a genomic or community feature/measure (e.g. alpha diversity, genome, metagenome, OTU, ASV)",
    "PATHWAY": "a biological pathway or process (e.g. glycolysis, bile acid metabolism, KEGG pathway)",
    "LAB_METHOD": "a laboratory method, kit, instrument or reagent (e.g. DNA extraction, MiSeq, QIAamp kit, PCR)",
    "DATA_ANALYSIS": "a computational/statistical method, software, database or metric (e.g. QIIME, LEfSe, PERMANOVA, SILVA)",
    "SAMPLE_METHOD": "a specimen type or sample collection/handling method (e.g. stool sample, rectal swab, freezing at -80 C)",
    "CLINICAL": "a clinical variable, treatment, procedure, measurement of a person (e.g. BMI, age, caesarean section, antibiotic use)",
    "EXPERIMENTAL_METHOD": "an experimental intervention or model (e.g. gavage, germ-free model, fecal microbiota transplantation)",
    "STUDY_DESIGN": "a study design or design element (e.g. cohort study, randomized controlled trial, cross-sectional)",
    "ANATOMY_OR_BODY_SITE": "PROPOSED: an organ, tissue or body site (e.g. gut, colon, oral cavity, skin, vagina)",
    "POPULATION_OR_HOST_GROUP": "PROPOSED: a group of people or hosts (e.g. infants, women, healthy subjects, patients, controls)",
    "MEASURE_OR_UNIT": "PROPOSED: a quantity, unit, time span or statistic not covered above (e.g. months, median, concentration, p-value)",
    "GEOGRAPHY": "PROPOSED: a country, region, city or setting (e.g. China, rural, Germany)",
    "NOT_A_CONCEPT": "an ordinary word, verb, adjective, fragment, number, phrase, person/journal/company name (e.g. analyzed, positive, authors, Qiagen as a company)",
}
PROMPT = """You assign one specific type to terms extracted from human-microbiome research papers. Each item is
[n, "term", ["variant", ...], "definition", ["sentence from a paper", ...]]. The definition was written by a model and
may be wrong; the sentences are from the papers and decide the sense used. Types:
{types}
Rules: choose the type of the term in the sense the sentences use it. Prefer one of the first 14 types when it fits;
use a PROPOSED type only when none of the 14 fits. A brand or company name used for a kit or instrument is LAB_METHOD;
used as a company it is NOT_A_CONCEPT. General classes keep their type: a group of organisms (e.g. "double-stranded DNA virus", "Gram-negative bacteria") is ORGANISM; a drug or compound class (e.g. "antilipemic agent", "polyphenols") is CHEMICAL; a class of diseases is DISEASE. NOT_A_CONCEPT is only for words that name no scientific thing. basis = CONTEXT if the sentences show the sense, NAME_ONLY if you decided from
the term alone. Return JSON {{"r": [{{"n": 0, "type": "...", "basis": "CONTEXT"}}, ...]}}, one object per item."""


def chat(port, model, content, schema, max_tokens):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "types", "schema": schema, "strict": True}},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://{os.environ.get('CDM_LLM_HOST', '127.0.0.1')}:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def sized(schema, k):
    """Copy of the schema whose array "r" must hold exactly k entries (whitespace-free decoding returned empty arrays)."""
    s = json.loads(json.dumps(schema))
    s["properties"]["r"].update({"minItems": k, "maxItems": k})
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--model", default="cyankiwi/Qwen3.5-9B-AWQ-4bit")
    ap.add_argument("--db303", type=Path, default=DB303)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="random sample (seed 20261110) for smoke tests")
    ap.add_argument("--workers", type=int, default=32)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    c310 = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    terms = list(c310.execute("SELECT term_id, term, variants, definition FROM term_curation "
                              "WHERE kept='True' AND cdm_type='ENTITY' ORDER BY term_id"))
    if a.sample:
        terms = sorted(random.Random(20261110).sample(terms, a.sample))
    elif a.limit:
        terms = terms[:a.limit]
    terms = [t for i, t in enumerate(terms) if i % a.nshards == a.shard]
    res = a.out / (f"entity_retyped.shard{a.shard}.jsonl" if a.nshards > 1 else "entity_retyped.jsonl")
    done = set()
    if res.exists():
        for line in open(res, encoding="utf-8"):
            r = json.loads(line)
            if r["type"] != "UNPARSED":
                done.add(r["term_id"])
    todo = [t for t in terms if t[0] not in done]
    print(f"{len(terms):,} ENTITY terms in scope; {len(todo):,} to type; model {a.model}", flush=True)
    item = {"type": "object", "additionalProperties": False, "required": ["n", "type", "basis"],
            "properties": {"n": {"type": "integer"}, "type": {"type": "string", "enum": list(TYPES)},
                           "basis": {"type": "string", "enum": ["CONTEXT", "NAME_ONLY"]}}}
    schema = {"type": "object", "additionalProperties": False, "required": ["r"],
              "properties": {"r": {"type": "array", "items": item}}}
    prompt = PROMPT.format(types="\n".join(f"  {k}: {v}" for k, v in TYPES.items()))
    lock, local = threading.Lock(), threading.local()

    def db():
        if not hasattr(local, "c"):
            local.c = sqlite3.connect(f"file:{a.db303}?mode=ro", uri=True, check_same_thread=False)
        return local.c

    def run(batch):
        ctx = [G.contexts(db(), t[0]) for t in batch]
        items = []
        for n, (tid, term, variants, definition) in enumerate(batch):
            var = [v for v in (variants or "").split("|") if v and v != term][:4]
            items.append([n, term, var, (definition or "")[:300], [x[2] for x in ctx[n]]])
        got = {}
        for _ in range(3):
            try:
                p = chat(a.port, a.model, prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False), sized(schema, len(items)), 1500)
                for r in p.get("r", []):
                    if isinstance(r.get("n"), int) and 0 <= r["n"] < len(batch):
                        got[r["n"]] = r
                if len(got) == len(batch):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        for n in [n for n in range(len(batch)) if n not in got]:     # single-item fallback
            try:
                p = chat(a.port, a.model, prompt + "\n\nItems:\n" + json.dumps([[0] + items[n][1:]], ensure_ascii=False), sized(schema, 1), 300)
                if p.get("r"):
                    got[n] = p["r"][0]
            except Exception:  # noqa: BLE001
                pass
        with lock, open(res, "a", encoding="utf-8") as f:
            for n, t in enumerate(batch):
                r = got.get(n) or {"type": "UNPARSED", "basis": ""}
                f.write(json.dumps({"term_id": t[0], "term": t[1], "old_type": "ENTITY", "type": r["type"],
                                    "proposed_extension_type": r["type"] in ("ANATOMY_OR_BODY_SITE", "POPULATION_OR_HOST_GROUP",
                                                                             "MEASURE_OR_UNIT", "GEOGRAPHY"),
                                    "basis": r["basis"], "n_context_sentences": len(ctx[n]),
                                    "context_mention_ids": [x[0] for x in ctx[n]], "provenance": "LLM_TYPED_FROM_CONTEXT",
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
