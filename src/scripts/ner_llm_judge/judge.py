"""Judge EVERY extracted entity and triple with a large LLM (OpenAI-compatible endpoint), batch by batch.

Each unique (string, type) is judged once from the string alone (no paper text is sent), then mapped back to every
benchmark configuration, CDM extraction model, canonical term and mention. Per entity the judge answers:
  V  valid entity: a real, specific, well-formed entity/concept name (not a fragment, generic word, author, number)
  M  relevant to human microbiome research
  T  proposed type correct;  C  correct type code
Per triple: is it a well-formed biomedical claim (W), relevant to human microbiome research (M), is the relation label
specific (S), and are subject/object valid entities (E).
Results are MODEL JUDGEMENTS (not accuracy, not human validation).

    python judge.py models --config config.yml    # list endpoint models
    python judge.py test   --config config.yml    # one request
    python judge.py build  --config config.yml    # items.jsonl (all unique entities + all triples); no API calls
    python judge.py judge  --config config.yml    # rate-limited, resumable; re-run to retry failures
    python judge.py report --config config.yml    # REPORT.md, summary.json, full verdict tables
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import re
import sqlite3
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))
BENCH = ROOT / "outputs/results/benchmark/ner_corpus_bench"
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
PROMPT_VERSION = "entity-triple-judge-v2-tailored-nothink"

SCHEMES = {
    "biored": {"GeneOrGeneProduct": "G", "DiseaseOrPhenotypicFeature": "D", "ChemicalEntity": "C",
               "OrganismTaxon": "O", "SequenceVariant": "V", "CellLine": "L"},
    "cdm": {"ORGANISM": "O", "PROTEIN": "P", "CHEMICAL": "C", "DISEASE": "D", "DNA_RNA": "N", "CELL_TYPE": "CT",
            "SAMPLE_METHOD": "SM", "LAB_METHOD": "LM", "DATA_ANALYSIS": "DA", "PATHWAY": "PW",
            "EXPERIMENTAL_METHOD": "EM", "STUDY_DESIGN": "SD", "GENOMICS": "GX", "CLINICAL": "CL", "ENTITY": "E"},
}
TYPE_HELP = {
    "biored": "G gene/gene product/protein; D disease/phenotype/symptom; C chemical/drug/metabolite; "
              "O organism/taxon (any rank, incl. host species); V sequence variant; L cell line",
    "cdm": "O organism/taxon; P protein/enzyme; C chemical/metabolite/drug; D disease/phenotype; N DNA/RNA entity "
           "(gene, rRNA, sequence); CT cell type; SM sample collection/handling method; LM laboratory method; "
           "DA data-analysis method/software; PW pathway; EM experimental method/assay; SD study design; "
           "GX genomics/sequencing concept; CL clinical concept/measure/procedure; E generic entity (no specific type)",
}
SYSTEM = ("You are an expert curator of human gut and human microbiome research literature. You check strings that "
          "automated NER models and LLMs extracted from microbiome papers (methods, results, discussion). Most errors are "
          "junk spans, not subtle type confusions. Be strict, consistent and fast. Answer with JSON only.")
ENTITY_TASK = """Each item is [n, "string", "proposed type code"]. The string was extracted (lower-cased) from a human microbiome paper.
Type codes: {types}.

Answer [n, V, M, T, C] per item:
V valid entity: "Y" if the string is a real, specific name or concept a curator would keep. "N" for:
  generic nouns or roles (patients, participants, samples, subjects, group, controls, levels, data, analysis, study, effect);
  numbers, statistics, p-values, doses, units, temperatures or conditions ("-80 °c", "p < 0.05", "10 mg/kg");
  person names, affiliations, cities, journals, citations, figure/table labels ("fig. 2", "table s1");
  sentence fragments, clauses or findings ("increased abundance of bacteria in the"), truncated or garbled text;
  accession numbers, URLs, file names.
  Standard abbreviations are valid (ibd, scfa, crp, bmi, otu, asv). "U" only if truly undecidable.
M microbiome-relevant: "Y" if V is "Y" and the entity matters in human microbiome research: microbes and taxa at any rank,
  host diseases and phenotypes, diet, drugs and antibiotics, metabolites (scfa, bile acids, tmao), host genes and immune
  markers, microbial genes and pathways, sample types (stool, saliva), lab, sequencing and analysis methods (16s rrna
  sequencing, shotgun metagenomics, qiime 2, dada2, permanova), study designs (cohort study, randomized controlled trial). Else "N".
T type correct: "Y" or "N"; "-" if V is "N".
C correct type code from the list; "-" if V is "N".

Examples:
[0,"faecalibacterium prausnitzii","O"] -> [0,"Y","Y","Y","O"]
[1,"patients","D"] -> [1,"N","N","-","-"]
[2,"butyrate","P"] -> [2,"Y","Y","N","C"]
[3,"-80 °c","C"] -> [3,"N","N","-","-"]
[4,"inflammatory bowel disease","D"] -> [4,"Y","Y","Y","D"]
[5,"increased abundance of","O"] -> [5,"N","N","-","-"]
[6,"16s rrna gene sequencing","{seq}"] -> [6,"Y","Y","{seq_ok}","{seq}"]
[7,"smith et al","O"] -> [7,"N","N","-","-"]

Return {{"r": [[n, V, M, T, C], ...]}} with exactly one entry per item, in order."""
TRIPLE_TASK = """Each item is [n, "subject", "relation", "object"], a relation triple extracted from a human microbiome paper.
Answer [n, W, M, S, E] per item:
W well-formed: "Y" if subject - relation - object reads as a plausible, meaningful biomedical claim; "N" if it is garbled,
  circular, a method/condition rather than a claim ("bacteria" - "related_to" - "room temperature"), or pairs non-entities; "U" if undecidable.
M microbiome-relevant: "Y" if the claim concerns microbes, the host-microbiome interaction, or factors studied with the microbiome; else "N".
S relation label: "Y" if specific and appropriate; "G" if too generic (other_relation / related_to / associated_with where a
  direction or mechanism such as increases, decreases, produces, inhibits is evident); "N" if wrong.
E entities: "Y" if subject and object are both valid, specific entities (not generic nouns, fragments or conditions); else "N".

Examples:
[0,"faecalibacterium prausnitzii","DECREASED_IN","crohn's disease"] -> [0,"Y","Y","Y","Y"]
[1,"microbiota composition","OTHER_RELATION","healthy aging"] -> [1,"Y","Y","G","Y"]
[2,"ants","OTHER_RELATION","-80 °c"] -> [2,"N","N","N","N"]

Return {"r": [[n, W, M, S, E], ...]} with exactly one entry per item, in order."""


def norm(s):
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", s or "")   # control characters from PDF extraction
    return " ".join(s.split()).lower()


# ---------------------------------------------------------------- config & client
def load_cfg(path, need_key=True):
    cfg = yaml.safe_load(open(path))
    api = cfg["api"]
    out = Path(cfg.get("output_dir", "outputs/results/benchmark/llm_judge"))
    cfg["_out"] = out if out.is_absolute() else ROOT / out
    cfg["_out"].mkdir(parents=True, exist_ok=True)
    if not need_key:
        return cfg
    p = Path(os.path.expanduser(api["secrets_file"]))
    if not p.is_file():
        sys.exit(f"secrets file not found: {p}")
    if p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        sys.exit(f"{p} is readable by group/others; run: chmod 600 {p}")
    sec = yaml.safe_load(open(p)) or {}
    api["_key"], api["_base"] = sec.get("api_key", ""), str(sec.get("base_url", "")).rstrip("/")
    if not api["_key"] or not api["_base"]:
        sys.exit(f"{p} must contain api_key and base_url")
    return cfg


class Client:
    def __init__(self, api):
        self.api, self.lock, self.next_t = api, threading.Lock(), 0.0
        self.gap = 60.0 / float(api.get("max_rpm", 90))

    def _slot(self):
        with self.lock:
            t = max(time.monotonic(), self.next_t)
            self.next_t = t + self.gap
        time.sleep(max(0.0, t - time.monotonic()))

    def request(self, path, body=None):
        req = urllib.request.Request(self.api["_base"] + path, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": f"Bearer {self.api['_key']}",
                                              "Content-Type": "application/json"})
        delay, tries = 5.0, int(self.api.get("max_retries", 6))
        for attempt in range(tries + 1):
            self._slot()
            try:
                with urllib.request.urlopen(req, timeout=float(self.api.get("timeout_s", 300))) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < tries:
                    ra = e.headers.get("Retry-After")
                    time.sleep(float(ra) if ra and ra.replace(".", "").isdigit() else delay)
                    delay = min(delay * 2, 120)
                    continue
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < tries:
                    time.sleep(delay)
                    delay = min(delay * 2, 120)
                    continue
                raise RuntimeError(f"network error: {e}") from None

    def chat(self, user):
        body = {"model": self.api["model"], "temperature": self.api.get("temperature", 0),
                "max_tokens": self.api.get("max_tokens", 8000),
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
        if self.api.get("json_mode", True):
            body["response_format"] = {"type": "json_object"}
        body.update(self.api.get("extra_body") or {})
        r = self.request("/chat/completions", body)
        ch = r["choices"][0]
        return ch["message"].get("content") or "", ch.get("finish_reason"), r.get("usage", {})


def parse(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except ValueError:
            return None


# ---------------------------------------------------------------- build items (no API calls)
def bench_mentions():
    """(config, chunk_id, norm string, type) for every typed mention of every corpus-benchmark configuration."""
    import fairbench as FB
    text = {json.loads(l)["chunk_id"]: json.loads(l)["text"] for l in open(BENCH / "chunks.jsonl", encoding="utf-8")}
    for p in sorted((BENCH / "preds").glob("*.jsonl")):
        if p.name.endswith(".partial.jsonl"):
            continue
        raw = {}
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            if "chunk_id" in r:
                raw[r["chunk_id"]] = r["preds"]
        for cid, ps in FB.project(list(raw.items()), p.stem, "biored"):
            for s, e, t in ps:
                yield p.stem, norm(text[cid][s:e]), t


def cmd_build(cfg):
    path = cfg["_out"] / "items.jsonl"
    if path.exists():
        sys.exit(f"{path} exists; delete it deliberately to rebuild")
    ents = {}
    for _, s, t in bench_mentions():
        if s:
            ents.setdefault(("biored", s, t), None)
    nb = len(ents)
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    for s, t in c.execute("SELECT DISTINCT lower(trim(surface_form)), entity_type FROM term_mention"):
        s = norm(s)
        if s and t:
            ents.setdefault(("cdm", s, t), None)
    with open(path, "w", encoding="utf-8") as fh:
        for i, (sch, s, t) in enumerate(sorted(ents)):
            fh.write(json.dumps({"id": f"e{i}", "task": "entity", "scheme": sch, "string": s, "type": t},
                                ensure_ascii=False) + "\n")
        for tid, su, rel, ob in c.execute("SELECT canonical_triple_id, subject_display_label, relation_normalized, "
                                          "object_display_label FROM relation ORDER BY canonical_triple_id"):
            fh.write(json.dumps({"id": f"t{tid}", "task": "triple", "triple_id": tid, "subject": su, "relation": rel,
                                 "object": ob}, ensure_ascii=False) + "\n")
        nt = c.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    eb, tb = int(cfg["batch"].get("entities", 100)), int(cfg["batch"].get("triples", 50))
    req = math.ceil(nb / eb) + math.ceil((len(ents) - nb) / eb) + math.ceil(nt / tb)
    print(f"entities: {nb:,} benchmark + {len(ents) - nb:,} CDM; triples: {nt:,}; ~{req:,} requests "
          f"(~{req / float(cfg['api'].get('max_rpm', 90)) / 60:.1f} h at {cfg['api'].get('max_rpm', 90)} RPM)")


# ---------------------------------------------------------------- judging
def make_batches(cfg, items, done):
    eb, tb = int(cfg["batch"].get("entities", 100)), int(cfg["batch"].get("triples", 50))
    groups = defaultdict(list)
    for it in items:
        if it["id"] not in done:
            groups[it["task"] if it["task"] == "triple" else it["scheme"]].append(it)
    out = []
    for g, lst in groups.items():
        b = tb if g == "triple" else eb
        out += [lst[k:k + b] for k in range(0, len(lst), b)]
    return out


def prompt(batch):
    if batch[0]["task"] == "triple":
        rows = [[n, it["subject"], it["relation"], it["object"]] for n, it in enumerate(batch)]
        return TRIPLE_TASK + "\n\nItems:\n" + json.dumps(rows, ensure_ascii=False)
    sch = batch[0]["scheme"]
    rows = [[n, it["string"], SCHEMES[sch].get(it["type"], it["type"])] for n, it in enumerate(batch)]
    seq = "GX" if sch == "cdm" else "G"
    ok = "Y" if sch == "cdm" else "N"
    task = ENTITY_TASK.format(types=TYPE_HELP[sch], seq=seq, seq_ok=ok)
    if sch == "biored":   # BioRED has no method type: a valid method gets T "N" and C "-"
        task = task.replace('-> [6,"Y","Y","N","G"]', '-> [6,"Y","Y","N","-"]')
    return task + "\n\nItems:\n" + json.dumps(rows, ensure_ascii=False)


def cmd_judge(cfg):
    items = [json.loads(l) for l in open(cfg["_out"] / "items.jsonl", encoding="utf-8")]
    res = cfg["_out"] / "verdicts.jsonl"
    done = set()
    if res.exists():
        done = {json.loads(l)["id"] for l in open(res, encoding="utf-8")}
    bs = make_batches(cfg, items, done)
    print(f"{len(done):,} judged; {sum(map(len, bs)):,} items in {len(bs):,} requests to go", flush=True)
    cl, wl, st = Client(cfg["api"]), threading.Lock(), Counter()
    errlog = cfg["_out"] / "errors.log"

    def run(batch):
        try:
            content, finish, usage = cl.chat(prompt(batch))
            p = parse(content) or {}
            got = {}
            for r in p.get("r", []):
                if isinstance(r, list) and len(r) == 5 and isinstance(r[0], int) and 0 <= r[0] < len(batch):
                    got[r[0]] = r[1:]
        except Exception as e:  # noqa: BLE001
            got, finish, usage = {}, "error", {}
            with wl, open(errlog, "a") as fh:
                fh.write(f"{time.strftime('%F %T')} {str(e)[:300]}\n")
        with wl, open(res, "a", encoding="utf-8") as fh:
            for n, it in enumerate(batch):
                if n in got:
                    fh.write(json.dumps({"id": it["id"], "v": got[n]}, ensure_ascii=False) + "\n")
                    st["judged"] += 1
                else:
                    st["missing"] += 1
            st["tokens_in"] += usage.get("prompt_tokens", 0)
            st["tokens_out"] += usage.get("completion_tokens", 0)
            if finish == "length":
                st["truncated_batches"] += 1
        return len(batch)

    n, t0 = 0, time.time()
    with ThreadPoolExecutor(int(cfg["api"].get("max_concurrency", 24))) as ex:
        futs = [ex.submit(run, b) for b in bs]
        for f in as_completed(futs):
            n += f.result()
            if n % 5000 < int(cfg["batch"].get("entities", 100)):
                rate = n / max(1e-9, time.time() - t0) * 60
                print(f"  {n:,} items | {dict(st)} | {rate:,.0f} items/min", flush=True)
    print("finished:", dict(st), "- re-run `judge` to retry missing items")


# ---------------------------------------------------------------- report
def wilson(k, n, z=1.96):
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{100 * p:.1f} [{100 * (c - h):.1f}–{100 * (c + h):.1f}]"


def cmd_report(cfg):
    out = cfg["_out"]
    items = {}
    for l in open(out / "items.jsonl", encoding="utf-8"):
        it = json.loads(l)
        items[it["id"]] = it
    v = {}
    for l in open(out / "verdicts.jsonl", encoding="utf-8"):
        r = json.loads(l)
        v[r["id"]] = r["v"]
    key = {(it["scheme"], it["string"], it["type"]): i for i, it in items.items() if it["task"] == "entity"}
    inv = {s: {c: t for t, c in m.items()} for s, m in SCHEMES.items()}

    def ok(vv, sch, t):
        """(valid, microbiome, type_ok) booleans or None when undecided/missing."""
        if not vv or vv[0] not in ("Y", "N"):
            return None
        val, mic = vv[0] == "Y", vv[1] == "Y"
        tok = val and (vv[2] == "Y" or (sch == "cdm" and t == "ENTITY"))
        return val, mic, tok

    def tally(rows):                      # rows: iterable of (weight, verdict-tuple or None)
        c = Counter()
        for w, r in rows:
            c["n"] += w
            if r is None:
                c["undecided"] += w
                continue
            c["d"] += w
            c["valid"] += w * r[0]
            c["valid_micro"] += w * (r[0] and r[1])
            c["valid_type"] += w * r[2]
        return c

    md = [f"# Model-judged validity of all extracted entities and triples ({cfg['api']['model']})", "",
          "**Model judgements, not accuracy and not human validation.** Every unique (string, type) was judged once "
          "from the string alone (no paper text sent) and mapped back to each system. *Valid* = a real, specific "
          "entity; *microbiome* = valid and relevant to human microbiome research; *type* = valid with the proposed "
          "type correct. Percentages over decided items with 95% Wilson intervals. Disclosure: a DeepSeek-family model "
          "was used in the pipeline (term review, mapping adjudication) and DeepSeek-R1-Distill is a benchmarked system.",
          ""]
    summary = {"model": cfg["api"]["model"], "prompt_version": PROMPT_VERSION,
               "items": len(items), "judged": len(v)}
    # benchmark configurations: distinct strings and mention-weighted
    per_cfg_d, per_cfg_m = defaultdict(set), defaultdict(Counter)
    for conf, s, t in bench_mentions():
        k = key.get(("biored", s, t))
        per_cfg_d[conf].add(k)
        per_cfg_m[conf][k] += 1
    md += ["## Corpus-benchmark NER configurations (BioRED types)", "",
           "| configuration | distinct entities | valid % | microbiome-relevant % | type correct % | mention-weighted valid % | undecided |",
           "|---|---:|---|---|---|---|---:|"]
    summary["benchmark"] = {}
    rows = []
    for conf in per_cfg_d:
        cd = tally((1, ok(v.get(k), "biored", items[k]["type"]) if k in items else None) for k in per_cfg_d[conf])
        cm = tally((w, ok(v.get(k), "biored", items[k]["type"]) if k in items else None) for k, w in per_cfg_m[conf].items())
        rows.append((cd["valid_type"] / max(1, cd["d"]), conf, cd, cm))
    for _, conf, cd, cm in sorted(rows, reverse=True):
        md.append(f"| {conf} | {cd['n']:,} | {wilson(cd['valid'], cd['d'])} | {wilson(cd['valid_micro'], cd['d'])} | "
                  f"{wilson(cd['valid_type'], cd['d'])} | {wilson(cm['valid'], cm['d'])} | {cd['undecided']:,} |")
        summary["benchmark"][conf] = {"distinct": dict(cd), "mentions": dict(cm)}
    # CDM extraction models
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    per_mod = defaultdict(Counter)
    for mod, s, t, n in c.execute("SELECT extraction_model, lower(trim(surface_form)), entity_type, COUNT(*) "
                                  "FROM term_mention GROUP BY 1, 2, 3"):
        per_mod[mod][key.get(("cdm", norm(s), t))] += n
    md += ["", "## CDM terminology sources (CDM types)", "",
           "| extraction model | distinct entities | valid % | microbiome-relevant % | type correct % | mention-weighted valid % | mention-weighted microbiome % |",
           "|---|---:|---|---|---|---|---|"]
    summary["cdm_models"] = {}
    rows = []
    for mod, ks in per_mod.items():
        cd = tally((1, ok(v.get(k), "cdm", items[k]["type"]) if k in items else None) for k in ks)
        cm = tally((w, ok(v.get(k), "cdm", items[k]["type"]) if k in items else None) for k, w in ks.items())
        rows.append((cd["valid_type"] / max(1, cd["d"]), mod, cd, cm))
    for _, mod, cd, cm in sorted(rows, reverse=True):
        md.append(f"| {mod} | {cd['n']:,} | {wilson(cd['valid'], cd['d'])} | {wilson(cd['valid_micro'], cd['d'])} | "
                  f"{wilson(cd['valid_type'], cd['d'])} | {wilson(cm['valid'], cm['d'])} | {wilson(cm['valid_micro'], cm['d'])} |")
        summary["cdm_models"][mod] = {"distinct": dict(cd), "mentions": dict(cm)}
    # by CDM type (all sources)
    by_type = defaultdict(list)
    for k, it in items.items():
        if it["task"] == "entity" and it["scheme"] == "cdm":
            by_type[it["type"]].append((1, ok(v.get(k), "cdm", it["type"])))
    md += ["", "## CDM entity types (distinct strings, all sources)", "",
           "| CDM type | distinct | valid % | microbiome-relevant % | type correct % |", "|---|---:|---|---|---|"]
    for t, lst in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        cd = tally(lst)
        md.append(f"| {t} | {cd['n']:,} | {wilson(cd['valid'], cd['d'])} | {wilson(cd['valid_micro'], cd['d'])} | "
                  f"{wilson(cd['valid_type'], cd['d'])} |")
    # triples
    tri = Counter()
    for k, it in items.items():
        if it["task"] == "triple" and k in v:
            r = v[k]
            tri["n"] += 1
            tri[f"W{r[0]}"] += 1
            tri[f"M{r[1]}"] += 1
            tri[f"S{r[2]}"] += 1
            tri[f"E{r[3]}"] += 1
    n = tri["n"] or 1
    md += ["", "## CDM triples (all)", "", f"Judged: {tri['n']:,}", "",
           "| criterion | share |", "|---|---:|",
           f"| well-formed, plausible claim | {wilson(tri['WY'], n)} |",
           f"| relevant to human microbiome research | {wilson(tri['MY'], n)} |",
           f"| relation label specific | {wilson(tri['SY'], n)} |",
           f"| relation label too generic | {wilson(tri['SG'], n)} |",
           f"| subject and object valid entities | {wilson(tri['EY'], n)} |"]
    summary["triples"] = dict(tri)
    # full verdict tables
    with gzip.open(out / "entity_verdicts.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["scheme", "string", "proposed_type", "valid", "microbiome_relevant", "type_correct", "correct_type"])
        for k, it in items.items():
            if it["task"] == "entity":
                r = v.get(k) or ["", "", "", ""]
                ct = inv[it["scheme"]].get(r[3], r[3]) if r[3] not in ("", "-") else r[3]
                w.writerow([it["scheme"], it["string"], it["type"], r[0], r[1], r[2], ct])
    with gzip.open(out / "triple_verdicts.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["triple_id", "subject", "relation", "object", "well_formed", "microbiome_relevant",
                    "relation_specific", "entities_valid"])
        for k, it in items.items():
            if it["task"] == "triple":
                w.writerow([it["triple_id"], it["subject"], it["relation"], it["object"], *(v.get(k) or ["", "", "", ""])])
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n")
    (out / "REPORT.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["models", "test", "build", "judge", "report"])
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yml")))
    a = ap.parse_args()
    cfg = load_cfg(a.config, need_key=a.cmd in ("models", "test", "judge"))
    if a.cmd == "models":
        for m in Client(cfg["api"]).request("/models").get("data", []):
            print(m.get("id"))
    elif a.cmd == "test":
        content, finish, usage = Client(cfg["api"]).chat(
            ENTITY_TASK.format(types=TYPE_HELP["cdm"], seq="GX", seq_ok="Y") + '\n\nItems:\n[[0, "faecalibacterium prausnitzii", "O"], [1, "patients", "D"]]')
        print("finish:", finish, "| usage:", usage, "| parsed:", parse(content))
    elif a.cmd == "build":
        cmd_build(cfg)
    elif a.cmd == "judge":
        cmd_judge(cfg)
    else:
        cmd_report(cfg)


if __name__ == "__main__":
    main()
