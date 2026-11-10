"""Fair NER benchmark: LLMs vs trained / zero-shot NER tools on BC5CDR and BioRED.

Protocol (fixed before any test-set result was seen):
  * Data: official NCBI test splits (BC5CDR CDR_TestSet, 500 abstracts; BioRED Test, 100 abstracts),
    whole title+abstract text, gold offsets verified against the text. Dev/train splits are used only
    for GLiNER threshold selection and the LLM few-shot examples.
  * Labels: every model is scored in each dataset's own type space. Trained models keep their own
    label set through a fixed raw-label map (RAW_MAP); zero-shot models (GLiNER family, LLMs) receive
    the same type names / definitions (TYPE_DEFS). Types a model cannot emit are reported as n/a in
    per-type tables and as misses in the full-schema score.
  * Scores: exact and relaxed (overlap, same type) span match; per-type F1; micro-F1 over the full
    schema; micro-F1 over Chemical+Disease (the types nearly every model supports); type-agnostic span
    F1. 95% CIs by document bootstrap (2,000 resamples); paired bootstrap p-values against the best model.
  * LLM spans: the model lists entity strings; every word-bounded occurrence in the text is marked
    (BC5CDR / BioRED annotate every mention). Strings not found verbatim are dropped and counted.

    python fairbench.py check
    python fairbench.py classic --models scispacy_bc5cdr gliner_biomed ...
    python fairbench.py llm --model qwen --host http://127.0.0.1:8000 --mode zs|fs
    python fairbench.py pubtator
    python fairbench.py score
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src"))
RAW = ROOT / "data/benchmarks_ner/raw"
OUT = ROOT / "outputs/results/ner_fair_bench"
PRED = OUT / "preds"

FILES = {"bc5cdr": {"test": "CDR_TestSet.PubTator.txt", "dev": "CDR_DevelopmentSet.PubTator.txt",
                    "train": "CDR_TrainingSet.PubTator.txt"},
         "biored": {"test": "BioRED_Test.PubTator", "dev": "BioRED_Dev.PubTator", "train": "BioRED_Train.PubTator"}}
TYPES = {"bc5cdr": ["Chemical", "Disease"],
         "biored": ["GeneOrGeneProduct", "DiseaseOrPhenotypicFeature", "ChemicalEntity", "OrganismTaxon",
                    "SequenceVariant", "CellLine"]}
# one-line definitions paraphrased from the official annotation guidelines; identical for every LLM
TYPE_DEFS = {
    "Chemical": "chemicals and drugs, including abbreviations and specific chemical classes",
    "Disease": "diseases, disorders, syndromes, signs and symptoms, including abbreviations",
    "GeneOrGeneProduct": "genes, proteins, mRNAs and other gene products, including families and complexes",
    "DiseaseOrPhenotypicFeature": "diseases, disorders, signs, symptoms and phenotypic features",
    "ChemicalEntity": "chemicals and drugs, including abbreviations",
    "OrganismTaxon": "organisms and species, including common names such as human, mouse or patients",
    "SequenceVariant": "genomic or protein sequence variants such as mutations, SNPs and rs identifiers",
    "CellLine": "named cell lines such as HeLa or HEK293",
}
# natural-language label given to GLiNER-family zero-shot models
GLINER_LABEL = {"Chemical": "chemical", "Disease": "disease", "GeneOrGeneProduct": "gene or gene product",
                "DiseaseOrPhenotypicFeature": "disease or phenotypic feature", "ChemicalEntity": "chemical",
                "OrganismTaxon": "organism", "SequenceVariant": "sequence variant", "CellLine": "cell line"}

# raw label emitted by a trained model -> dataset type (missing = cannot be scored as that type).
# Decided from label semantics only (sequence ontology != variant, cell type != cell line).
RAW_MAP = {
    "scispacy_bc5cdr": {"bc5cdr": {"CHEMICAL": "Chemical", "DISEASE": "Disease"},
                        "biored": {"CHEMICAL": "ChemicalEntity", "DISEASE": "DiseaseOrPhenotypicFeature"}},
    "scispacy_craft": {"bc5cdr": {"CHEBI": "Chemical"},
                       "biored": {"CHEBI": "ChemicalEntity", "GGP": "GeneOrGeneProduct", "TAXON": "OrganismTaxon"}},
    "scispacy_jnlpba": {"bc5cdr": {},
                        "biored": {"PROTEIN": "GeneOrGeneProduct", "DNA": "GeneOrGeneProduct",
                                   "RNA": "GeneOrGeneProduct", "CELL_LINE": "CellLine"}},
    "scispacy_bionlp13cg": {"bc5cdr": {"SIMPLE_CHEMICAL": "Chemical", "CANCER": "Disease"},
                            "biored": {"SIMPLE_CHEMICAL": "ChemicalEntity", "CANCER": "DiseaseOrPhenotypicFeature",
                                       "GENE_OR_GENE_PRODUCT": "GeneOrGeneProduct", "ORGANISM": "OrganismTaxon"}},
    "scispacy_lg": {"bc5cdr": {}, "biored": {}},          # untyped ENTITY: span-only score
    "pubmedbert": {"bc5cdr": {"DISEASE": "Disease"}, "biored": {"DISEASE": "DiseaseOrPhenotypicFeature"}},
    # same BioBERT disease checkpoint as pubmedbert, via the spaCy-free word-window wrapper
    "bert_disease": {"bc5cdr": {"DISEASE": "Disease"}, "biored": {"DISEASE": "DiseaseOrPhenotypicFeature"}},
    "bert_chemical": {"bc5cdr": {"CHEMICAL": "Chemical"}, "biored": {"CHEMICAL": "ChemicalEntity"}},
    "bert_genetic": {"bc5cdr": {}, "biored": {"GENETIC": "GeneOrGeneProduct"}},
    "scibert_jnlpba": {"bc5cdr": {},
                       "biored": {"PROTEIN": "GeneOrGeneProduct", "DNA": "GeneOrGeneProduct",
                                  "RNA": "GeneOrGeneProduct", "CELL_LINE": "CellLine"}},
    # the HunFlair2 wrapper already folds its tags (Chemical, Gene, Disease, Species, CellLine) to CDM names;
    # CELL_TYPE comes only from its CellLine tag
    "hunflair2": {"bc5cdr": {"CHEMICAL": "Chemical", "DISEASE": "Disease"},
                  "biored": {"CHEMICAL": "ChemicalEntity", "DISEASE": "DiseaseOrPhenotypicFeature",
                             "PROTEIN": "GeneOrGeneProduct", "ORGANISM": "OrganismTaxon", "CELL_TYPE": "CellLine"}},
    "pubtator3": {"bc5cdr": {"Chemical": "Chemical", "Disease": "Disease"},
                  "biored": {"Chemical": "ChemicalEntity", "Disease": "DiseaseOrPhenotypicFeature",
                             "Gene": "GeneOrGeneProduct", "Species": "OrganismTaxon", "CellLine": "CellLine",
                             "Mutation": "SequenceVariant", "DNAMutation": "SequenceVariant",
                             "ProteinMutation": "SequenceVariant", "SNP": "SequenceVariant", "Variant": "SequenceVariant"}},
}
ZERO_SHOT = ["gliner", "gliner_biomed", "gliner_v25_medium", "gliner_v25_biomed", "gliner2_base", "gliner2_large"]
# trained on (a split of) the benchmark corpus itself, per model cards / papers: an in-domain advantage
IN_DOMAIN = {"scispacy_bc5cdr": ["bc5cdr"], "bert_chemical": ["bc5cdr"], "pubmedbert": ["bc5cdr"], "bert_disease": ["bc5cdr"],
             "hunflair2": ["bc5cdr"], "pubtator3": ["bc5cdr", "biored"], "gliner_biomed": ["bc5cdr"],
             "gliner_v25_biomed": ["bc5cdr"]}
LLMS = {"qwen": ("Qwen/Qwen3.5-4B", "Qwen3.5-4B"),
        "gemma": ("google/gemma-4-E4B-it-qat-w4a16-ct", "Gemma-4-E4B (w4a16)"),
        "llama": ("hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4", "Llama-3.1-8B-Instruct (AWQ)"),
        "mistral": ("TechxGenus/Mistral-7B-Instruct-v0.3-AWQ", "Mistral-7B-Instruct-v0.3 (AWQ)"),
        "phi": ("thesven/Phi-3.5-mini-instruct-awq", "Phi-3.5-mini-instruct (AWQ)"),
        "deepseek": ("casperhansen/deepseek-r1-distill-qwen-7b-awq", "DeepSeek-R1-Distill-Qwen-7B (AWQ)")}
NO_SYSTEM_ROLE = {"mistral"}   # chat template rejects a system message: it is prepended to the first user turn


# ── data ─────────────────────────────────────────────────────────────────────
def load(ds, split="test"):
    """PubTator -> [(pmid, text, [(start, end, type, mention)])]; text = title + ' ' + abstract."""
    docs, cur = [], None
    for line in open(RAW / FILES[ds][split], encoding="utf-8"):
        line = line.rstrip("\n")
        if "|t|" in line[:30]:
            if cur:
                docs.append(cur)
            pmid, title = line.split("|t|", 1)
            cur = [pmid, title, []]
        elif "|a|" in line[:30]:
            cur[1] = cur[1] + " " + line.split("|a|", 1)[1]
        elif cur and line.count("\t") >= 4:
            p = line.split("\t")
            if p[1].isdigit() and p[2].isdigit() and p[4] in TYPES[ds]:
                cur[2].append((int(p[1]), int(p[2]), p[4], p[3]))
    if cur:
        docs.append(cur)
    bad = sum(1 for _, t, g in docs for s, e, _, m in g if t[s:e] != m)
    if bad:
        raise SystemExit(f"{ds}/{split}: {bad} gold offsets do not match the text")
    return [tuple(d) for d in docs]


def write_preds(name, ds, preds, meta):
    PRED.mkdir(parents=True, exist_ok=True)
    with open(PRED / f"{ds}__{name}.jsonl", "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": meta}) + "\n")
        for pmid, ps in preds:
            fh.write(json.dumps({"pmid": pmid, "preds": ps}, ensure_ascii=False) + "\n")


def read_preds(path):
    meta, out = {}, {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if "_meta" in r:
            meta = r["_meta"]
        else:
            out[r["pmid"]] = r["preds"]
    return meta, out


# ── classic models ───────────────────────────────────────────────────────────
def gliner_scored(m, name, text, labels, thr):
    """GLiNER / GLiNER2 predictions with scores (the registry wrappers drop the score)."""
    from cdm_pipeline.ner.chunking import token_chunks
    spans = (token_chunks(text, m._ntokens_fn, m.max_chars, m.max_tokens) if name.startswith("gliner2")
             else m._chunk_spans(text))
    out = []
    for lo, hi in spans:
        chunk = text[lo:hi]
        if not chunk.strip():
            continue
        if name.startswith("gliner2"):
            res = m.model.extract_entities(chunk, labels, threshold=thr, include_confidence=True, include_spans=True)
            for lab, vals in (res.get("entities") or {}).items():
                for v in vals:
                    if isinstance(v, dict) and v.get("start") is not None:
                        out.append({"start": lo + v["start"], "end": lo + v["end"], "text": v.get("text"),
                                    "label": lab, "score": v.get("confidence", 1.0)})
        else:
            for e in m.model.predict_entities(chunk, labels, threshold=thr):
                out.append({"start": lo + e["start"], "end": lo + e["end"], "text": e["text"],
                            "label": e["label"], "score": e.get("score", 1.0)})
    return out


def run_classic(args):
    from cdm_pipeline.ner.registry import get_model
    for name in args.models:
        key = {"scispacy_lg": "scispacy"}.get(name, name)
        for ds in args.datasets:
            if (PRED / f"{ds}__{name}.jsonl").exists() and not args.force:
                print(f"skip {ds}/{name} (exists)")
                continue
            docs = load(ds)
            meta = {"model": name, "dataset": ds, "kind": "zero-shot NER" if name in ZERO_SHOT else "trained NER",
                    "device": args.device}
            if name in ZERO_SHOT:
                labels = sorted({GLINER_LABEL[t] for t in TYPES[ds]})
                m = get_model(key, entity_types=labels, threshold=0.3)
                m._ensure_loaded()
                # threshold chosen on the dev split (full-schema exact F1), never on test
                dev = load(ds, "dev")
                dev_raw = [(p, gliner_scored(m, name, t, labels, 0.3)) for p, t, _ in dev]
                grid = (0.3, 0.4, 0.5, 0.6, 0.7)
                dev_f1 = {thr: micro(dev, project(dev_raw, name, ds, thr), TYPES[ds])["exact"]["F1"] for thr in grid}
                best = max(grid, key=lambda thr: dev_f1[thr])
                t0 = time.time()
                raw = [(p, gliner_scored(m, name, t, labels, best)) for p, t, _ in docs]
                meta.update(threshold=best, dev_f1_by_threshold=dev_f1, threshold_split="dev")
            else:
                m = get_model(key)
                if hasattr(m, "_label_map"):
                    m._label_map = {}          # raw labels; mapped by RAW_MAP at scoring time
                m._ensure_loaded()
                t0 = time.time()
                raw = [(p, m.predict_text(t)) for p, t, _ in docs]
            el = time.time() - t0
            meta.update(seconds=round(el, 2), docs=len(docs), sec_per_doc=round(el / len(docs), 4),
                        raw_labels=dict(Counter(x["label"] for _, ps in raw for x in ps)))
            write_preds(name, ds, raw, meta)
            print(f"{ds}/{name}: {sum(len(ps) for _, ps in raw)} raw preds, {el:.0f}s, "
                  f"labels {meta['raw_labels']}, thr {meta.get('threshold', '-')}", flush=True)
            del m


def project(raw, name, ds, thr=None):
    """Raw model output -> [(pmid, [(s, e, type)])] in the dataset's type space."""
    if name in ZERO_SHOT:
        mp = {}
        for t in TYPES[ds]:
            mp.setdefault(GLINER_LABEL[t], t)
    elif name.startswith("llm_"):
        mp = {t: t for t in TYPES[ds]}
    else:
        mp = RAW_MAP[name][ds]
    out = []
    for pmid, ps in raw:
        keep = set()
        for x in ps:
            if thr is not None and x.get("score", 1.0) < thr:
                continue
            t = mp.get(x["label"])
            if t:
                keep.add((int(x["start"]), int(x["end"]), t))
        out.append((pmid, sorted(keep)))
    return out


def supported(name, ds):
    if name in ZERO_SHOT or name.startswith("llm_"):
        return list(TYPES[ds])
    return sorted(set(RAW_MAP[name][ds].values()))


# ── PubTator3 (precomputed annotations by PMID; reference only) ──────────────
def run_pubtator(args):
    api = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson?pmids="
    for ds in args.datasets:
        docs = load(ds)
        by = {}
        t0 = time.time()
        for i in range(0, len(docs), 50):
            ids = ",".join(p for p, _, _ in docs[i:i + 50])
            data = json.loads(urllib.request.urlopen(api + ids, timeout=120).read())
            for d in data.get("PubTator3", []) if isinstance(data, dict) else data:
                ps = []
                for psg in d.get("passages", []):
                    for a in psg.get("annotations", []):
                        for loc in a.get("locations", []):
                            ps.append({"start": loc["offset"], "end": loc["offset"] + loc["length"],
                                       "text": a.get("text"), "label": (a.get("infons") or {}).get("type")})
                by[str(d.get("pmid") or d.get("id"))] = ps
            time.sleep(1)
        raw = [(p, by.get(p, [])) for p, _, _ in docs]
        txt = {p: t for p, t, _ in docs}
        ok = sum(1 for p, ps in raw for x in ps if txt[p][x["start"]:x["end"]] == x["text"])
        n = sum(len(ps) for _, ps in raw)
        write_preds("pubtator3", ds, raw, {"model": "pubtator3", "dataset": ds, "kind": "precomputed (PubTator3 API)",
                                           "docs_found": len(by), "offset_match": f"{ok}/{n}",
                                           "seconds": round(time.time() - t0, 1), "docs": len(docs),
                                           "raw_labels": dict(Counter(x["label"] for _, ps in raw for x in ps))})
        print(f"{ds}/pubtator3: {len(by)}/{len(docs)} docs, offsets match {ok}/{n}")


# ── LLMs ─────────────────────────────────────────────────────────────────────
def llm_system(ds):
    defs = "\n".join(f"- {t}: {TYPE_DEFS[t]}" for t in TYPES[ds])
    return ("You are an expert biomedical named-entity annotator. Find every entity of the types below in the "
            "text. Copy each entity string EXACTLY as it appears (same spelling, case and spacing); do not "
            "expand abbreviations - an abbreviation is its own entity. List each distinct string once per type.\n"
            f"Types:\n{defs}\n"
            'Return ONLY JSON: {"entities": [{"text": "...", "type": "<one of the types>"}]}')


def fewshot(ds, k=3, seed=0):
    """k annotated TRAIN abstracts (fixed seed), the same for every LLM."""
    tr = load(ds, "train")
    ex = random.Random(seed).sample([d for d in tr if 600 < len(d[1]) < 1400], k)
    msgs = []
    for _, text, gold in ex:
        ents = sorted({(m, t) for _, _, t, m in gold}, key=lambda x: text.find(x[0]))
        msgs += [{"role": "user", "content": f"Text:\n{text}"},
                 {"role": "assistant", "content": json.dumps({"entities": [{"text": m, "type": t} for m, t in ents]},
                                                             ensure_ascii=False)}]
    return msgs, [p for p, _, _ in ex]


def occurrences(text, s):
    """Word-bounded occurrences of s in text (exact case first, case-insensitive fallback)."""
    s = (s or "").strip()
    if not s:
        return []
    for flags in (0, re.I):
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])", flags)
        hits = [(m.start(), m.end()) for m in pat.finditer(text)]
        if hits:
            return hits
    return []


ENT_RE = re.compile(r'\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"type"\s*:\s*"([^"]*)"\s*\}')


def parse_entities(content):
    """Entities from the model's JSON; if the JSON is cut off or malformed, keep every complete
    {"text", "type"} object (same rule for every LLM). Returns (entities, salvaged?)."""
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            return json.loads(m.group(0)).get("entities", []), False
        except (json.JSONDecodeError, AttributeError):
            pass
    ents = [{"text": json.loads(f'"{t}"'), "type": ty} for t, ty in ENT_RE.findall(content)]
    return ents, True


def run_llm(args):
    model, label = LLMS[args.model]
    reasoning = args.model == "deepseek"
    for ds in args.datasets:
        name = f"llm_{args.model}_{args.mode}"
        if (PRED / f"{ds}__{name}.jsonl").exists() and not args.force:
            print(f"skip {ds}/{name}")
            continue
        docs = load(ds)
        system = llm_system(ds)
        shots, shot_ids = fewshot(ds) if args.mode == "fs" else ([], [])

        def messages(text):
            msgs = [*shots, {"role": "user", "content": f"Text:\n{text}"}]
            if args.model in NO_SYSTEM_ROLE:
                return [{"role": msgs[0]["role"], "content": system + "\n\n" + msgs[0]["content"]}] + msgs[1:]
            return [{"role": "system", "content": system}] + msgs

        def ask(doc):
            pmid, text, _ = doc
            body = {"model": model, "temperature": 0.6 if reasoning else 0, "seed": 0,
                    "max_tokens": 10000 if reasoning else 8000, "messages": messages(text)}
            if not reasoning:
                body["response_format"] = {"type": "json_object"}
            if args.model in ("qwen", "gemma"):
                body["chat_template_kwargs"] = {"enable_thinking": False}
            err = None
            for _ in range(3):
                try:
                    req = urllib.request.Request(args.host.rstrip("/") + "/v1/chat/completions",
                                                 data=json.dumps(body).encode(),
                                                 headers={"Content-Type": "application/json"})
                    r = json.loads(urllib.request.urlopen(req, timeout=1200).read())
                    c = r["choices"][0]["message"].get("content") or ""
                    c = re.sub(r"(?s)^.*</think>", "", c).strip()
                    ents, salvaged = parse_entities(c)
                    return pmid, ents, (r["choices"][0].get("finish_reason"), salvaged), None
                except Exception as ex:  # noqa: BLE001
                    err = repr(ex)[:300]
            return pmid, [], None, err

        t0 = time.time()
        with ThreadPoolExecutor(args.parallel) as pool:
            res = list(pool.map(ask, docs))
        el = time.time() - t0
        txt = {p: t for p, t, _ in docs}
        raw, st = [], Counter()
        for pmid, ents, finish, err in res:
            st["failed_docs"] += bool(err)
            st["truncated_docs"] += bool(finish) and finish[0] == "length"
            st["salvaged_docs"] += bool(finish) and finish[1]
            ps = []
            for e in ents if isinstance(ents, list) else []:
                if not isinstance(e, dict):
                    continue
                typ, s = e.get("type"), str(e.get("text") or "")
                if typ not in TYPES[ds]:
                    st["invalid_type"] += 1
                    continue
                hits = occurrences(txt[pmid], s)
                st["strings"] += 1
                st["strings_not_in_text"] += not hits
                ps += [{"start": a, "end": b, "text": txt[pmid][a:b], "label": typ} for a, b in hits]
            raw.append((pmid, ps))
        meta = {"model": name, "llm": label, "hf_id": model, "dataset": ds,
                "kind": "LLM " + {"zs": "zero-shot", "fs": "3-shot"}[args.mode],
                "seconds": round(el, 2), "docs": len(docs), "sec_per_doc": round(el / len(docs), 4),
                "parallel": args.parallel, "device": "1x A40 (vLLM)", "temperature": 0.6 if reasoning else 0,
                "fewshot_train_pmids": shot_ids,
                "errors": sorted({e for *_, e in res if e})[:3], **dict(st)}
        write_preds(name, ds, raw, meta)
        print(f"{ds}/{name}: {json.dumps(dict(st))}, {el:.0f}s", flush=True)


# ── scoring ──────────────────────────────────────────────────────────────────
def counts(gold, pred, types):
    """Per-doc [tp, fp, fn] exact + [tp, fp, fn] relaxed (overlap, same type, one-to-one) per type."""
    c = {}
    for t in types:
        g = [(s, e) for s, e, ty in gold if ty == t]
        p = [(s, e) for s, e, ty in pred if ty == t]
        gs, ps = set(g), set(p)
        tp = len(gs & ps)
        used, rtp = set(), 0
        for a, b in p:
            for i, (x, y) in enumerate(g):
                if i not in used and a < y and b > x:
                    used.add(i)
                    rtp += 1
                    break
        c[t] = [tp, len(ps) - tp, len(gs) - tp, rtp, len(p) - rtp, len(g) - rtp]
    return c


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"P": p, "R": r, "F1": 2 * p * r / (p + r) if p + r else 0.0, "tp": tp, "fp": fp, "fn": fn}


def micro(docs, pred, types, per_doc=False):
    pm = dict(pred)
    rows = [counts([(s, e, t) for s, e, t, _ in gold], pm.get(pmid, []), types) for pmid, _, gold in docs]
    return rows if per_doc else agg(rows, types)


def agg(rows, types):
    tot = [0] * 6
    for r in rows:
        for t in types:
            tot = [a + b for a, b in zip(tot, r[t])]
    return {"exact": prf(*tot[:3]), "relaxed": prf(*tot[3:])}


def _resample(rows, types, n, seed):
    rnd, k = random.Random(seed), len(rows)
    for _ in range(n):
        idx = [rnd.randrange(k) for _ in range(k)]
        yield idx


def boot(rows, types, n=2000, seed=0):
    f = sorted(agg([rows[i] for i in idx], types)["exact"]["F1"] for idx in _resample(rows, types, n, seed))
    return [f[int(0.025 * n)], f[int(0.975 * n) - 1]]


def paired_p(best_rows, rows, types, n=2000, seed=0):
    """One-sided paired bootstrap: share of resamples where `rows` scores >= the best model."""
    worse = 0
    for idx in _resample(rows, types, n, seed):
        fb = agg([best_rows[i] for i in idx], types)["exact"]["F1"]
        fa = agg([rows[i] for i in idx], types)["exact"]["F1"]
        worse += fa >= fb
    return worse / n


def score(args):
    res = {}
    for ds in ("bc5cdr", "biored"):
        docs = load(ds)
        span_docs = [(p, t, [(s, e, "SPAN", m) for s, e, _, m in g]) for p, t, g in docs]
        rows_by = {}
        for path in sorted(PRED.glob(f"{ds}__*.jsonl")):
            name = path.stem.split("__", 1)[1]
            meta, raw = read_preds(path)
            raw = [(p, raw.get(p, [])) for p, _, _ in docs]
            pred = project(raw, name, ds)
            sup = supported(name, ds)
            full = micro(docs, pred, TYPES[ds], per_doc=True)
            spans = [(p, sorted({(int(x["start"]), int(x["end"]), "SPAN") for x in ps
                                 if name == "scispacy_lg" or project([(p, [x])], name, ds)[0][1]}))
                     for p, ps in raw]
            r = {"meta": meta, "supported_types": sup, "in_domain_training": ds in IN_DOMAIN.get(name, []),
                 "full_schema": agg(full, TYPES[ds]), "full_schema_ci": boot(full, TYPES[ds]),
                 "span_only": micro(span_docs, spans, ["SPAN"]), "per_type": {}}
            for t in sup:
                r["per_type"][t] = {**agg(full, [t]), "ci": boot(full, [t], n=1000)}
            common = [t for t in TYPES[ds] if "Chemical" in t or "Disease" in t]
            if all(t in sup for t in common):
                r["chem_dis"] = agg(full, common)
                r["chem_dis_ci"] = boot(full, common)
            rows_by[name] = full
            res[f"{ds}__{name}"] = r
        typed = [n for n in rows_by if n != "scispacy_lg"]
        if typed:
            best = max(typed, key=lambda n: res[f"{ds}__{n}"]["full_schema"]["exact"]["F1"])
            for n in typed:
                res[f"{ds}__{n}"]["best_on_dataset"] = best
                if n != best:
                    res[f"{ds}__{n}"]["p_vs_best"] = paired_p(rows_by[best], rows_by[n], TYPES[ds])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fair_ner_metrics.json").write_text(json.dumps(res, indent=1) + "\n")
    report(res)


def report(res):
    def f(x):
        return f"{100 * x:.1f}"

    L = ["# Fair NER benchmark — LLMs vs NER tools", "",
         "Official test splits (BC5CDR: 500 abstracts, 9,809 entities; BioRED: 100 abstracts, 3,535 entities), "
         "whole title+abstract, each dataset's own types. Exact = same span and type; relaxed = overlapping span, "
         "same type. Full-schema F1 counts types a model cannot emit as misses. 95% CI by document bootstrap. "
         "† = trained on this corpus (in-domain advantage). Protocol: `src/scripts/ner_fair_bench/fairbench.py`.", ""]
    for ds, title in (("bc5cdr", "BC5CDR (Chemical, Disease)"), ("biored", "BioRED (6 types)")):
        rows = sorted(((k.split("__", 1)[1], v) for k, v in res.items() if k.startswith(ds + "__")),
                      key=lambda kv: -kv[1]["full_schema"]["exact"]["F1"])
        L += [f"## {title}", "",
              "| model | kind | full-schema exact F1 [95% CI] | relaxed F1 | P | R | Chem+Dis exact F1 | "
              "span-only F1 | p vs best | s/doc |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for n, v in rows:
            fs, m = v["full_schema"], v["meta"]
            lo, hi = v["full_schema_ci"]
            cd = v.get("chem_dis")
            pv = "best" if n == v.get("best_on_dataset") else (f"{v['p_vs_best']:.3f}" if "p_vs_best" in v else "")
            L.append(f"| {n}{' †' if v['in_domain_training'] else ''} | {m.get('kind', '')} | "
                     f"{f(fs['exact']['F1'])} [{f(lo)}–{f(hi)}] | {f(fs['relaxed']['F1'])} | {f(fs['exact']['P'])} | "
                     f"{f(fs['exact']['R'])} | {f(cd['exact']['F1']) if cd else 'n/a'} | "
                     f"{f(v['span_only']['exact']['F1'])} | {pv} | {m.get('sec_per_doc', '')} |")
        L += ["", f"Per-type exact F1 — {ds} (n/a = the model cannot emit the type):", "",
              "| model | " + " | ".join(TYPES[ds]) + " |", "|---|" + "---:|" * len(TYPES[ds])]
        for n, v in rows:
            L.append(f"| {n} | " + " | ".join(f(v["per_type"][t]["exact"]["F1"]) if t in v["per_type"] else "n/a"
                                             for t in TYPES[ds]) + " |")
        L.append("")
    (OUT / "FAIR_NER_BENCHMARK.md").write_text("\n".join(L))
    print("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["classic", "llm", "pubtator", "score", "check"])
    ap.add_argument("--models", nargs="+", default=[])
    ap.add_argument("--model")
    ap.add_argument("--mode", default="zs", choices=["zs", "fs"])
    ap.add_argument("--datasets", nargs="+", default=["bc5cdr", "biored"])
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--parallel", type=int, default=64)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        for ds in ("bc5cdr", "biored"):
            for sp in ("test", "dev", "train"):
                d = load(ds, sp)
                print(ds, sp, len(d), "docs", dict(Counter(t for _, _, g in d for _, _, t, _ in g)))
        return 0
    return {"classic": run_classic, "llm": run_llm, "pubtator": run_pubtator, "score": score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
