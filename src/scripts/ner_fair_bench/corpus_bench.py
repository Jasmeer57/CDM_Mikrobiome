"""Corpus NER benchmark without a gold standard: all models over all 453 papers, judged by external references.

Every model runs on the same chunks of the 453-paper corpus (all sections except References and
Acknowledgements, packed into <= 4,000-character chunks on paragraph / sentence boundaries) with the
BioRED type schema and the settings of the public benchmark (fairbench.py: same prompts, same few-shot
examples, GLiNER thresholds chosen on the BioRED dev split). Outputs are then judged against
references no model has seen:

  ground  terminology grounding — share of each model's unique entity strings that resolve in a reference
          vocabulary of the predicted type (NCBI Gene, CTD/MeSH diseases + Mondo/HPO, CTD/MeSH chemicals,
          NCBI Taxonomy, variant patterns); strings resolving only under another type count as type errors.
  kg      knowledge-graph support — grounded entity pairs co-occurring in a sentence (gene-disease,
          chemical-disease, chemical-gene, microbe-disease), checked against CTD curated associations and
          Disbiome. Reported: pairs, KG-supported pairs, support rate, distinct known associations recovered.
          The CDM relation triples are checked with the same machinery.

    python corpus_bench.py chunks
    python corpus_bench.py classic --models ...      python corpus_bench.py llm --model qwen --mode zs --host ...
    python corpus_bench.py lexicon                   python corpus_bench.py score
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fairbench as FB  # noqa: E402

ROOT = FB.ROOT
csv.field_size_limit(sys.maxsize)
SECTIONS = ROOT / "pipelines/corpus_v2/data/sections.jsonl"
REF = ROOT / "data/reference_kg/raw"
OUT = ROOT / "outputs/results/ner_corpus_bench"
PRED = OUT / "preds"
LEX = OUT / "lexicon"
DS = "biored"                       # type schema and settings borrowed from the public BioRED run
SKIP_SECTIONS = {"References", "Acknowledgements"}
CHUNK = 4000


# ── chunks ───────────────────────────────────────────────────────────────────
def pack(text, limit=CHUNK):
    """[(start, end)] chunks <= limit on paragraph, then sentence, then hard boundaries."""
    units, pos = [], 0
    for para in re.split(r"(\n\s*\n)", text):
        if len(para) <= limit:
            units.append((pos, pos + len(para)))
        else:
            s = pos
            for m in re.finditer(r"(?<=[.!?])\s+", para):
                if pos + m.end() - s > limit:
                    units.append((s, pos + m.end()))
                    s = pos + m.end()
            while pos + len(para) - s > limit:
                units.append((s, s + limit))
                s += limit
            units.append((s, pos + len(para)))
        pos += len(para)
    out, cur = [], None
    for a, b in units:
        if cur and b - cur[0] <= limit:
            cur[1] = b
        else:
            if cur:
                out.append(tuple(cur))
            cur = [a, b]
    if cur:
        out.append(tuple(cur))
    return [(a, b) for a, b in out if text[a:b].strip()]


def chunks():
    p = OUT / "chunks.jsonl"
    if p.exists():
        return [json.loads(l) for l in open(p, encoding="utf-8")]
    rows = []
    for line in open(SECTIONS, encoding="utf-8"):
        s = json.loads(line)
        if s.get("section_type") in SKIP_SECTIONS:
            continue
        text = s.get("section_text_original") or ""
        for i, (a, b) in enumerate(pack(text)):
            rows.append({"chunk_id": f"{s['section_record_id']}#{i}", "paper_id": s["paper_id"],
                         "section_type": s.get("section_type"), "start": a, "text": text[a:b]})
    OUT.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def docs():
    return [(c["chunk_id"], c["text"], []) for c in chunks()]


# ── model runs (same code paths as fairbench) ────────────────────────────────
def public_threshold(name):
    meta, _ = FB.read_preds(FB.PRED / f"{DS}__{name}.jsonl")
    return meta["threshold"]


def run_classic(args):
    from cdm_pipeline.ner.registry import get_model
    D = docs()
    for name in args.models:
        out = PRED / f"{name}.jsonl"
        if out.exists() and not args.force:
            print(f"skip {name}")
            continue
        key = {"scispacy_lg": "scispacy"}.get(name, name)
        meta = {"model": name, "kind": "zero-shot NER" if name in FB.ZERO_SHOT else "trained NER", "device": args.device}
        if name in FB.ZERO_SHOT:
            labels = sorted({FB.GLINER_LABEL[t] for t in FB.TYPES[DS]})
            thr = public_threshold(name)
            m = get_model(key, entity_types=labels, threshold=thr)
            m._ensure_loaded()
            t0 = time.time()
            raw = [(c, FB.gliner_scored(m, name, t, labels, thr)) for c, t, _ in D]
            meta["threshold"] = thr
        else:
            m = get_model(key)
            if hasattr(m, "_label_map"):
                m._label_map = {}
            m._ensure_loaded()
            t0 = time.time()
            raw = []
            for i, (c, t, _) in enumerate(D):
                raw.append((c, m.predict_text(t)))
                if i % 1000 == 0:
                    print(f"  {name} {i}/{len(D)}", flush=True)
        el = time.time() - t0
        meta.update(seconds=round(el, 1), chunks=len(D), chars=sum(len(t) for _, t, _ in D),
                    raw_labels=dict(Counter(x["label"] for _, ps in raw for x in ps)))
        save(out, raw, meta)
        print(f"{name}: {sum(len(ps) for _, ps in raw)} raw preds in {el:.0f}s", flush=True)
        del m


def save(path, raw, meta):
    PRED.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": meta}) + "\n")
        for c, ps in raw:
            fh.write(json.dumps({"chunk_id": c, "preds": [{k: x[k] for k in ("start", "end", "text", "label")
                                                             if k in x} for x in ps]}, ensure_ascii=False) + "\n")


def run_llm(args):
    model, label = FB.LLMS[args.model]
    reasoning = args.model == "deepseek"
    name = f"llm_{args.model}_{args.mode}"
    out = PRED / f"{name}.jsonl"
    if out.exists() and not args.force:
        print(f"skip {name}")
        return
    D = docs()
    system = FB.llm_system(DS)
    shots, shot_ids = FB.fewshot(DS) if args.mode == "fs" else ([], [])
    PRED.mkdir(parents=True, exist_ok=True)
    part = PRED / f"{name}.partial.jsonl"            # resumable: one line per finished chunk
    done = {}
    if part.exists():
        for line in open(part, encoding="utf-8"):
            r = json.loads(line)
            done[r["chunk_id"]] = r
    todo = [d for d in D if d[0] not in done]
    print(f"{name}: {len(done)} cached, {len(todo)} to run", flush=True)

    def messages(text):
        msgs = [*shots, {"role": "user", "content": f"Text:\n{text}"}]
        if args.model in FB.NO_SYSTEM_ROLE:
            return [{"role": msgs[0]["role"], "content": system + "\n\n" + msgs[0]["content"]}] + msgs[1:]
        return [{"role": "system", "content": system}] + msgs

    def ask(doc):
        cid, text, _ = doc
        body = {"model": model, "temperature": 0.6 if reasoning else 0, "seed": 0,
                "max_tokens": 6000 if reasoning else 4000, "messages": messages(text)}
        if not reasoning:
            body["response_format"] = {"type": "json_object"}
        if args.model in ("qwen", "gemma"):
            body["chat_template_kwargs"] = {"enable_thinking": False}
        err = None
        for _ in range(3):
            try:
                req = urllib.request.Request(args.host.rstrip("/") + "/v1/chat/completions",
                                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=1800).read())
                c = re.sub(r"(?s)^.*</think>", "", r["choices"][0]["message"].get("content") or "").strip()
                ents, salvaged = FB.parse_entities(c)
                return {"chunk_id": cid, "ents": ents if isinstance(ents, list) else [],
                        "finish": r["choices"][0].get("finish_reason"), "salvaged": salvaged}
            except Exception as ex:  # noqa: BLE001
                err = repr(ex)[:300]
        return {"chunk_id": cid, "ents": [], "error": err}

    t0 = time.time()
    with open(part, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.parallel) as pool:
        for i, r in enumerate(pool.map(ask, todo)):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            done[r["chunk_id"]] = r
            if i % 500 == 0:
                fh.flush()
                print(f"  {i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    el = time.time() - t0
    txt = {c: t for c, t, _ in D}
    raw, st = [], Counter()
    for c, _, _ in D:
        r = done[c]
        st["failed_chunks"] += "error" in r
        st["truncated_chunks"] += r.get("finish") == "length"
        st["salvaged_chunks"] += bool(r.get("salvaged"))
        ps = []
        for e in r.get("ents", []):
            if not isinstance(e, dict) or e.get("type") not in FB.TYPES[DS]:
                st["invalid_type"] += isinstance(e, dict)
                continue
            hits = FB.occurrences(txt[c], str(e.get("text") or ""))
            st["strings"] += 1
            st["strings_not_in_text"] += not hits
            ps += [{"start": a, "end": b, "text": txt[c][a:b], "label": e["type"]} for a, b in hits]
        raw.append((c, ps))
    meta = {"model": name, "llm": label, "kind": "LLM " + {"zs": "zero-shot", "fs": "3-shot"}[args.mode],
            "seconds_this_run": round(el, 1), "chunks": len(D), "device": "1x A40 (vLLM)",
            "fewshot_train_pmids": shot_ids, **dict(st)}
    save(out, raw, meta)
    part.unlink()
    print(f"{name}: {json.dumps(dict(st))}, {el:.0f}s", flush=True)


# ── reference lexicons ───────────────────────────────────────────────────────
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "κ": "kappa", "ω": "omega", "μ": "mu"}


def norm(s):
    s = (s or "").strip().lower()
    for k, v in GREEK.items():
        s = s.replace(k, v)
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"\s+", " ", s).strip(" .,;:()[]{}'\"")
    return s


def variants(s):
    n = norm(s)
    out = {n}
    if len(n) > 4 and n.endswith("s"):
        out.add(n[:-1])
    if n.endswith(" spp") or n.endswith(" sp"):
        out.add(n.rsplit(" ", 1)[0])
    out.add(n.replace("-", " "))
    return {x for x in out if x}


def build_lexicon(args):
    """name -> id lexicons per type and curated KG pairs, from the downloaded references only."""
    LEX.mkdir(parents=True, exist_ok=True)
    lex = {t: defaultdict(set) for t in ("GeneOrGeneProduct", "DiseaseOrPhenotypicFeature", "ChemicalEntity",
                                          "OrganismTaxon")}
    gene_sym_case = defaultdict(set)    # short symbols are matched case-sensitively

    def tsv_gz(path):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.startswith("#"):
                    yield line.rstrip("\n").split("\t")

    for sp in ("Homo_sapiens", "Mus_musculus"):
        for r in tsv_gz(REF / f"{sp}.gene_info.gz"):
            gid = f"NCBIGene:{r[1]}"
            names = [r[2]] + [x for x in r[4].split("|") if x != "-"] + ([r[8]] if r[8] != "-" else [])
            if len(r) > 11 and r[11] != "-":
                names.append(r[11])
            for nm in names:
                # short alphabetic names collide with English words (REST, MAX, SET): exact case only
                if len(nm) <= 3 or (len(nm) <= 5 and nm.isalpha()):
                    gene_sym_case[nm].add(gid)
                else:
                    for v in variants(nm):
                        lex["GeneOrGeneProduct"][v].add(gid)
    for r in tsv_gz(REF / "CTD_diseases.tsv.gz"):       # MEDIC: MeSH + OMIM, with synonyms
        for nm in [r[0]] + [x for x in r[7].split("|") if x] if len(r) > 7 else [r[0]]:
            for v in variants(nm):
                lex["DiseaseOrPhenotypicFeature"][v].add(r[1])
    for r in tsv_gz(REF / "CTD_chemicals.tsv.gz"):      # MeSH chemicals; MESHSynonyms + CTDCuratedSynonyms
        syn = [x for col in r[11:13] for x in col.split("|") if x]
        for nm in [r[0]] + syn:
            for v in variants(nm):
                lex["ChemicalEntity"][v].add(r[1])
    omop = ROOT / "outputs/results/omop_vocab"
    keep = {"Mondo": "DiseaseOrPhenotypicFeature", "HPO": "DiseaseOrPhenotypicFeature"}
    cid_type = {}
    with open(omop / "CONCEPT.csv", encoding="utf-8") as fh:
        for r in csv.reader(fh, delimiter="\t"):
            if len(r) > 6 and r[3] in keep:
                cid_type[r[0]] = (keep[r[3]], f"{r[3]}:{r[6]}")
                for v in variants(r[1]):
                    lex[keep[r[3]]][v].add(f"{r[3]}:{r[6]}")
    with open(omop / "CONCEPT_SYNONYM.csv", encoding="utf-8") as fh:
        for r in csv.reader(fh, delimiter="\t"):
            if len(r) > 1 and r[0] in cid_type:
                t, i = cid_type[r[0]]
                for v in variants(r[1]):
                    lex[t][v].add(i)
    with open(REF / "names.dmp", encoding="utf-8") as fh:
        for line in fh:
            p = [x.strip() for x in line.split("|")]
            if p[3] in ("scientific name", "synonym", "genbank common name", "common name", "equivalent name",
                        "genbank synonym", "includes"):
                for v in variants(p[1]):
                    lex["OrganismTaxon"][v].add(f"NCBITaxon:{p[0]}")
    sizes = {t: len(d) for t, d in lex.items()}
    print(sizes, "names", flush=True)
    # knowledge graphs
    kg = {"gene_disease": set(), "chem_disease": set(), "chem_gene": set(), "microbe_disease": set()}
    for r in tsv_gz(REF / "CTD_curated_genes_diseases.tsv.gz"):
        if len(r) > 3:
            kg["gene_disease"].add((f"NCBIGene:{r[1]}", r[3]))
    for r in tsv_gz(REF / "CTD_chemicals_diseases.tsv.gz"):
        if len(r) > 5 and r[5]:                           # DirectEvidence present = curated
            kg["chem_disease"].add((f"MESH:{r[1]}", r[4]))
    for r in tsv_gz(REF / "CTD_chem_gene_ixns.tsv.gz"):
        if len(r) > 4:
            kg["chem_gene"].add((f"MESH:{r[1]}", f"NCBIGene:{r[4]}"))
    dis = json.load(open(REF / "disbiome_experiment.json"))
    unmatched = Counter()
    for e in dis:
        if not e.get("organism_ncbi_id"):
            continue
        ids = set()
        for v in variants(e.get("disease_name") or ""):
            ids |= lex["DiseaseOrPhenotypicFeature"].get(v, set())
        if not ids:
            unmatched[e.get("disease_name")] += 1
        for i in ids:
            kg["microbe_disease"].add((f"NCBITaxon:{e['organism_ncbi_id']}", i))
    print({k: len(v) for k, v in kg.items()}, "Disbiome disease names unmatched:", len(unmatched), flush=True)
    (LEX / "reference_sizes.json").write_text(json.dumps(
        {"lexicon_names": sizes, "gene_symbols_case_sensitive": len(gene_sym_case),
         "kg_associations": {k: len(v) for k, v in kg.items()},
         "disbiome_experiments": len(dis), "disbiome_disease_names_unmatched": len(unmatched)}, indent=1) + "\n")
    (LEX / "disbiome_unmatched_diseases.json").write_text(json.dumps(unmatched.most_common(), indent=0))
    return lex, gene_sym_case, kg


def taxon_parents():
    par = {}
    with open(REF / "nodes.dmp", encoding="utf-8") as fh:
        for line in fh:
            p = line.split("\t|\t")
            par[f"NCBITaxon:{p[0]}"] = (f"NCBITaxon:{p[1]}", p[2])
    return par


# ── scoring ──────────────────────────────────────────────────────────────────
PAIRS = {"gene_disease": ("GeneOrGeneProduct", "DiseaseOrPhenotypicFeature"),
         "chem_disease": ("ChemicalEntity", "DiseaseOrPhenotypicFeature"),
         "chem_gene": ("ChemicalEntity", "GeneOrGeneProduct"),
         "microbe_disease": ("OrganismTaxon", "DiseaseOrPhenotypicFeature")}
VARIANT_RE = re.compile(r"^(rs\d+|[cgpmn]\.\S+|[A-Z]\d+[A-Z*]|[ACDEFGHIKLMNPQRSTVWY][a-z]{0,2}\d+[A-Za-z]{1,3}|\d+[ACGT]>[ACGT])$")


def score(args):
    lex, gene_case, kg = build_lexicon(args)     # rebuilt each run: the taxonomy alone is ~4M names
    par = taxon_parents()
    # Disbiome mostly records genera: a species / strain mention is also credited at its genus
    genus_of = {}

    def lift(tid):
        if tid in genus_of:
            return genus_of[tid]
        seen, cur, out = 0, tid, {tid}
        while cur in par and seen < 30:
            nxt, rank = par[cur]
            if cur == nxt:
                break
            out.add(nxt)
            if rank in ("genus", "family"):
                break
            cur, seen = nxt, seen + 1
        genus_of[tid] = out
        return out

    def ground(t, s):
        if t == "SequenceVariant":
            return {"PATTERN"} if VARIANT_RE.match(s.strip()) else set()
        if t == "CellLine":
            return set()
        ids = set()
        if t == "GeneOrGeneProduct" and (len(s.strip()) <= 3 or (len(s.strip()) <= 5 and s.strip().isalpha())):
            return set(gene_case.get(s.strip(), []))
        for v in variants(s):
            ids |= lex[t].get(v, set())
        return ids

    C = {c["chunk_id"]: c for c in chunks()}
    res = {}
    for path in sorted(PRED.glob("*.jsonl")):
        if path.name.endswith(".partial.jsonl"):
            continue
        name = path.stem
        meta, raw = read(path)
        pr = FB.project(list(raw.items()), name, DS)
        sup = FB.supported(name, DS)
        uniq = defaultdict(dict)       # type -> normalised string -> first surface form (grounding needs case)
        mentions = Counter()
        pairs = {k: set() for k in PAIRS}
        for cid, ps in pr:
            text = C[cid]["text"]
            sent_bounds = [0] + [m.end() for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z(])", text)] + [len(text) + 1]
            by_sent = defaultdict(lambda: defaultdict(set))
            for s, e, t in ps:
                surf = text[s:e]
                uniq[t].setdefault(norm(surf), surf)
                mentions[t] += 1
                ids = ground(t, surf)
                if ids and t in ("GeneOrGeneProduct", "DiseaseOrPhenotypicFeature", "ChemicalEntity", "OrganismTaxon"):
                    k = next(i for i in range(len(sent_bounds) - 1) if sent_bounds[i] <= s < sent_bounds[i + 1])
                    if t == "OrganismTaxon":
                        ids = set().union(*(lift(i) for i in ids))
                    by_sent[k][t] |= ids
            for sent in by_sent.values():
                for kname, (ta, tb) in PAIRS.items():
                    for a in sent.get(ta, ()):
                        for b in sent.get(tb, ()):
                            pairs[kname].add((C[cid]["paper_id"], a, b))
        g = {}
        for t in sup:
            strings = set(uniq[t].values())
            ok = {s for s in strings if ground(t, s)}
            other = {s for s in strings - ok
                     if any(ground(t2, s) for t2 in lex if t2 != t)} if t in lex else set()
            g[t] = {"unique": len(strings), "mentions": mentions[t], "grounded": len(ok),
                    "grounded_pct": round(100 * len(ok) / len(strings), 1) if strings else None,
                    "other_type_pct": round(100 * len(other) / len(strings), 1) if strings else None}
        k = {}
        for kname, ps in pairs.items():
            if not all(t in sup for t in PAIRS[kname]):
                continue
            hit = {p for p in ps if (p[1], p[2]) in kg[kname]}
            k[kname] = {"pairs": len(ps), "kg_supported": len(hit),
                        "support_pct": round(100 * len(hit) / len(ps), 2) if ps else None,
                        "distinct_known_associations": len({(a, b) for _, a, b in hit}),
                        "_known": sorted({f"{a}|{b}" for _, a, b in hit})}
        res[name] = {"meta": meta, "supported_types": sup, "grounding": g, "kg": k,
                     "papers_with_entities": len({C[c]["paper_id"] for c, ps in pr if ps})}
    # recall-like coverage: share of the union of KG associations found by any model
    for kname in PAIRS:
        union = set().union(*(set(v["kg"][kname]["_known"]) for v in res.values() if kname in v["kg"]))
        for v in res.values():
            if kname in v["kg"]:
                v["kg"][kname]["share_of_union_pct"] = round(100 * len(v["kg"][kname]["_known"]) / len(union), 1) if union else None
    cdm = cdm_triples(ground, lift, kg)
    OUT.mkdir(parents=True, exist_ok=True)
    slim = {n: {**v, "kg": {k: {kk: vv for kk, vv in d.items() if kk != "_known"} for k, d in v["kg"].items()}}
            for n, v in res.items()}
    (OUT / "corpus_metrics.json").write_text(json.dumps({"models": slim, "cdm_triples": cdm}, indent=1) + "\n")
    report(slim, cdm)


def read(path):
    meta, out = {}, {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if "_meta" in r:
            meta = r["_meta"]
        else:
            out[r["chunk_id"]] = r["preds"]
    return meta, out


def cdm_triples(ground, lift, kg):
    """The CDM 3.0.3 relation table, checked with the same lexicons / KGs (subject x object either order)."""
    import sqlite3
    db = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
    if not db.exists():
        return {}
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    # corpus-v2 triple domain types (pipelines/corpus_v2/schema/triple_domains.json); no domain is purely chemical
    # (drug_intervention also covers probiotics, diets, procedures), so chemical pairs are not checked
    tmap = {"MICROORGANISM_TAXON": "OrganismTaxon", "DISEASE_PHENOTYPE": "DiseaseOrPhenotypicFeature",
            "GENE_PROTEIN_PRODUCT": "GeneOrGeneProduct"}
    st, n_typed = Counter(), Counter()
    for sl, st_, ol, ot in c.execute("SELECT subject_display_label, subject_entity_type, object_display_label, "
                                     "object_entity_type FROM relation"):
        a, b = tmap.get((st_ or "").upper()), tmap.get((ot or "").upper())
        if not a or not b:
            continue
        for kname, (ta, tb) in PAIRS.items():
            if {a, b} != {ta, tb}:
                continue
            x, y = (sl, ol) if a == ta else (ol, sl)
            ia, ib = ground(ta, x), ground(tb, y)
            if ta == "OrganismTaxon":
                ia = set().union(*(lift(i) for i in ia)) if ia else set()
            n_typed[kname] += 1
            if ia and ib:
                st[kname + ":grounded"] += 1
                if any((p, q) in kg[kname] for p in ia for q in ib):
                    st[kname + ":kg_supported"] += 1
    return {k: {"triples": n_typed[k], "both_grounded": st[k + ":grounded"], "kg_supported": st[k + ":kg_supported"],
                "support_pct_of_grounded": round(100 * st[k + ":kg_supported"] / st[k + ":grounded"], 1)
                if st[k + ":grounded"] else None} for k in PAIRS}


def report(res, cdm):
    T = ["GeneOrGeneProduct", "DiseaseOrPhenotypicFeature", "ChemicalEntity", "OrganismTaxon", "SequenceVariant"]
    L = ["# Corpus NER benchmark — 453 papers, judged by external references", "",
         "All models on the same chunks of the 453-paper corpus (References/Acknowledgements excluded), BioRED type "
         "schema and settings. No gold standard: grounding = share of a model's unique strings found in a reference "
         "vocabulary of the predicted type (NCBI Gene; CTD-MEDIC/MeSH, Mondo, HPO; CTD/MeSH chemicals; NCBI Taxonomy; "
         "variant syntax). KG support = grounded pairs in one sentence that are curated associations in CTD "
         "(gene–disease, chemical–disease, chemical–gene) or Disbiome (microbe–disease). Grounding is a precision "
         "proxy: real entities can be missing from the vocabularies and junk can match a synonym.", "",
         "## Terminology grounding (% of unique strings; n/a = type not emitted)", "",
         "| model | kind | papers | " + " | ".join(T) + " | unique strings |", "|---|---|---:|" + "---:|" * (len(T) + 1)]
    for n, v in sorted(res.items()):
        g = v["grounding"]
        L.append(f"| {n} | {v['meta'].get('kind', '')} | {v['papers_with_entities']} | " +
                 " | ".join(f"{g[t]['grounded_pct']}" if t in g and g[t]['grounded_pct'] is not None else "n/a" for t in T) +
                 f" | {sum(x['unique'] for x in g.values()):,} |")
    L += ["", "## Knowledge-graph support of co-occurring grounded pairs", "",
          "| model | " + " | ".join(f"{k}: pairs / supported % / known assoc. / % of union" for k in PAIRS) + " |",
          "|---|" + "---:|" * len(PAIRS)]
    for n, v in sorted(res.items()):
        L.append(f"| {n} | " + " | ".join(
            f"{d['pairs']:,} / {d['support_pct']} / {d['distinct_known_associations']:,} / {d.get('share_of_union_pct')}"
            if (d := v["kg"].get(k)) else "n/a" for k in PAIRS) + " |")
    L += ["", "## CDM 3.0.3 relation triples against the same KGs (chemical pairs not checked: no purely chemical triple domain)", "",
          "| pair type | typed triples | both entities grounded | KG-supported | % of grounded |", "|---|---:|---:|---:|---:|"]
    for k, d in cdm.items():
        L.append(f"| {k} | {d['triples']:,} | {d['both_grounded']:,} | {d['kg_supported']:,} | {d['support_pct_of_grounded']} |")
    (OUT / "CORPUS_NER_BENCHMARK.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["chunks", "classic", "llm", "lexicon", "score"])
    ap.add_argument("--models", nargs="+", default=[])
    ap.add_argument("--model")
    ap.add_argument("--mode", default="zs", choices=["zs", "fs"])
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--parallel", type=int, default=64)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "chunks":
        c = chunks()
        print(len(c), "chunks,", len({x["paper_id"] for x in c}), "papers,", sum(len(x["text"]) for x in c), "chars")
        return 0
    if a.cmd == "lexicon":
        build_lexicon(a)
        return 0
    return {"classic": run_classic, "llm": run_llm, "score": score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
