#!/usr/bin/env python3
"""Relevance screen of accepted ontology concepts with FhGenie (DeepSeek-V4.1-Flash), in batches.

Question per concept: is it relevant to a microbiome-research common data model?
  K = KEEP          relevant (organisms, host biology, diseases, chemicals/metabolites, genes/proteins,
                    lab/sequencing/analysis methods, study design, clinical/demographic variables, units)
  I = IRRELEVANT    outside the field (e.g. engineering, finance, law, geography trivia, unrelated domains)
  N = NOT_A_CONCEPT  publishing/layout artefacts, fragments, overly generic words (Citation, Email, Figure)
  U = UNSURE

Sent to the service: concept label, ontology prefix, CDM type ONLY. No paper text, no contextual or
ontology definitions (licensed vocabularies such as SNOMED CT / MedDRA / UMLS).
Input: accepted concepts after dedup (outputs/results/concept_dedup_2026-11-09/concepts/dedup_map.tsv).
Output: outputs/results/concept_relevance_2026-11-09/ ; nothing is removed from the CDM - this is a filter
layer (MODEL JUDGEMENTS, not accuracy), pending project-lead approval (CHANGE_RECORD).

  python concept_relevance_fhgenie.py --limit 200   # smoke test
  python concept_relevance_fhgenie.py               # all (resumes)
"""
import argparse
import collections
import concurrent.futures as cf
import json
import sys
import threading
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/ner_llm_judge"))
from judge import Client, load_cfg, parse  # noqa: E402

MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
BATCH = 100
DEDUP = ROOT / "outputs/results/concept_dedup_2026-11-09/concepts/dedup_map.tsv"
CURIE = ROOT / "outputs/results/concept_dedup_2026-11-09/stage_a/concept_curie_map.tsv"
OUT = ROOT / "outputs/results/concept_relevance_2026-11-09"
LABELS = {"K": "KEEP", "I": "IRRELEVANT", "N": "NOT_A_CONCEPT", "U": "UNSURE"}
TERM_DEDUP = ROOT / "outputs/results/concept_dedup_2026-11-09/terms/dedup_map.tsv"

TERM_SYSTEM = """You curate terms extracted from papers for a common data model for HUMAN AND ANIMAL
MICROBIOME RESEARCH (gut, oral, skin, vaginal, respiratory microbiota; 16S/shotgun sequencing;
metabolomics; host-microbe interactions; clinical and epidemiological studies of microbiome and disease).

For each extracted term decide:
K  KEEP: a meaningful concept for this field. This INCLUDES organisms of any rank or form (incl.
   abbreviations like B. fragilis, taxonomy strings like g__Prevotella, uncultured/unclassified groups),
   anatomy and body sites, cells, genes, proteins, pathways, chemicals, metabolites, drugs, diets, foods,
   diseases, symptoms, clinical and demographic variables (age, sex, BMI, country, ethnicity), sample
   types, lab kits and instruments (PowerSoil kit, MiSeq), sequencing, bioinformatics and statistical
   methods and software (QIIME 2, DESeq2, Wilcoxon test), study designs, units, quantities.
I  IRRELEVANT: a real concept but clearly outside biomedical/microbiome research.
N  NOT_A_CONCEPT: author or person names, affiliations and addresses, journal/publisher/licence text,
   figure/table/supplement references (Fig. 2B, Table S1), bare numbers, p-values with symbols, email,
   URLs, PDF garbage, sentence fragments, single stopwords or adjectives without a noun (decreased,
   between), or labels too generic to carry meaning (data, results, group, analysis, method).
U  UNSURE: you cannot tell.
When in doubt between K and anything else, answer K. Never drop an organism, disease, chemical, gene,
protein, method or clinical variable because it seems rare, misspelled or specific.

Answer JSON only: {"r": [[index, "K|I|N|U", "reason in <=6 words"], ...]} with one row per input item."""

SYSTEM = """You curate the vocabulary of a common data model for HUMAN AND ANIMAL MICROBIOME RESEARCH
(gut, oral, skin, vaginal, respiratory microbiota; 16S/shotgun sequencing; metabolomics; host-microbe
interactions; clinical and epidemiological studies of microbiome and disease).

For each ontology concept decide:
K  KEEP: useful in this field. This INCLUDES organisms of any rank (bacteria, archaea, fungi, viruses,
   parasites, hosts, model animals, food plants), anatomy and body sites, cells, genes, proteins,
   enzymes, pathways, chemicals, metabolites, drugs, diets and foods, diseases, symptoms, clinical and
   demographic variables (age, sex, country, ethnicity, BMI, smoking), sample types, lab, sequencing,
   bioinformatics and statistical methods, study designs, measurement units and quantities.
I  IRRELEVANT: clearly outside biomedical/microbiome research (e.g. engineering parts, finance, law,
   music, sports, software products unrelated to bioinformatics, astronomy, unrelated industries).
N  NOT_A_CONCEPT: publishing or layout artefacts and empty words (Citation, Email, Figure, Table,
   Abstract, Author, Page), fragments, or a label too generic to carry meaning (Thing, Entity, Other).
U  UNSURE: you cannot tell.
When in doubt between K and anything else, answer K. Never drop an organism, disease, chemical, gene,
protein, method or clinical variable because it seems rare or specific.

Answer JSON only: {"r": [[index, "K|I|N|U", "reason in <=6 words"], ...]} with one row per input item."""


def load_items():
    canon = {}
    for line in open(DEDUP, encoding="utf-8").read().split("\n")[1:]:
        if line:
            cid, text, cano, ctext, how = line.split("\t")
            canon[cano] = ctext
    accepted_any = set()
    for line in open(CURIE, encoding="utf-8").read().split("\n")[1:]:
        if line:
            cid, cu, acc, *_ = line.split("\t")
            if acc == "1":
                accepted_any.add(cu)
    import sqlite3
    db = sqlite3.connect(f"file:{ROOT / 'releases/cdm_v3/3.0.3/microbiome_cdm_v3.db'}?mode=ro", uri=True)
    cmap = {}
    for line in open(CURIE, encoding="utf-8").read().split("\n")[1:]:
        if line:
            cid, cu, *_ = line.split("\t")
            cmap[cid] = cu
    ctype = collections.defaultdict(collections.Counter)
    for cid, ty in db.execute("""select m.concept_id, t.cdm_type from term_concept_map m join canonical_term t using(term_id)
                                 where m.mapping_disposition_reviewed='ACCEPTED'"""):
        ctype[cmap.get(cid, cid)][ty] += 1
    items = []
    for cu, lab in sorted(canon.items()):
        import re
        onto = ("UMLS" if re.fullmatch(r"C\d{7}", cu) else
                cu.split(":")[0] if ":" in cu and not cu.startswith("http") else cu.split("//")[-1].split("/")[0])
        ty = (ctype[cu].most_common(1) or [("ENTITY", 0)])[0][0]
        items.append({"id": cu, "label": lab, "ontology": onto, "cdm_type": ty, "n_mappings": sum(ctype[cu].values())})
    return items


def load_terms():
    import sqlite3
    db = sqlite3.connect(f"file:{ROOT / 'releases/cdm_v3/3.0.3/microbiome_cdm_v3.db'}?mode=ro", uri=True)
    info = {t: (ty, mc, pc) for t, ty, mc, pc in db.execute(
        "select term_id, cdm_type, coalesce(mention_count,0), coalesce(paper_count,0) from canonical_term")}
    canon = {}
    for line in open(TERM_DEDUP, encoding="utf-8").read().split("\n")[1:]:
        if line:
            tid, text, cano, ctext, how = line.split("\t")
            canon[cano] = ctext
    return [{"id": c, "label": " ".join(t.split())[:200], "ontology": "-", "cdm_type": info[c][0] or "ENTITY",
             "n_mappings": info[c][1], "n_papers": info[c][2]} for c, t in sorted(canon.items())]


def main():
    global OUT, SYSTEM
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--entity", choices=["concepts", "terms"], default="concepts")
    a = ap.parse_args()
    if a.entity == "terms":
        OUT = ROOT / "outputs/results/term_relevance_2026-11-09"
        SYSTEM = TERM_SYSTEM
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_cfg(str(ROOT / "src/scripts/ner_llm_judge/config.yml"))
    cfg["api"]["model"] = MODEL
    cfg["api"]["max_rpm"] = 120
    cl = Client(cfg["api"])

    items = load_items() if a.entity == "concepts" else load_terms()
    if a.limit:
        items = items[: a.limit]
    res_path = OUT / "judgements.jsonl"
    done = {}
    if res_path.is_file():
        for line in open(res_path, encoding="utf-8"):
            r = json.loads(line)
            done[r["id"]] = r
    todo = [it for it in items if it["id"] not in done]
    batches = [todo[k:k + BATCH] for k in range(0, len(todo), BATCH)]
    print(f"{len(items):,} concepts; {len(done):,} done; {len(todo):,} in {len(batches)} requests", flush=True)
    lock, st = threading.Lock(), collections.Counter()

    def run(batch):
        if a.entity == "terms":
            lines = [f'{n}\t{it["label"]}\t{it["cdm_type"]}' for n, it in enumerate(batch)]
            user = "index\tterm\tcdm_type\n" + "\n".join(lines)
        else:
            lines = [f'{n}\t{it["label"]}\t{it["ontology"]}\t{it["cdm_type"]}' for n, it in enumerate(batch)]
            user = "index\tlabel\tontology\tcdm_type\n" + "\n".join(lines)
        body = {"model": MODEL, "temperature": 0, "max_tokens": 6000,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}}
        body.update(cfg["api"].get("extra_body") or {})
        try:
            r = cl.request("/chat/completions", body)
            obj = parse(r["choices"][0]["message"].get("content") or "") or {}
        except Exception as e:  # keep going; failed batches are retried on the next run
            print("batch failed:", e, flush=True)
            return
        got = {}
        for row in obj.get("r", []):
            if isinstance(row, list) and len(row) >= 2 and isinstance(row[0], int) and 0 <= row[0] < len(batch) \
                    and str(row[1]).strip().upper()[:1] in LABELS:
                got[row[0]] = (LABELS[str(row[1]).strip().upper()[:1]], str(row[2]) if len(row) > 2 else "")
        with lock, open(res_path, "a", encoding="utf-8") as f:
            for n, it in enumerate(batch):
                if n in got:
                    f.write(json.dumps({**it, "verdict": got[n][0], "reason": got[n][1], "model": MODEL,
                                        "prompt": f"{a.entity}-relevance-v1-2026-11-09"}, ensure_ascii=False) + "\n")
                    st[got[n][0]] += 1
                else:
                    st["missing"] += 1

    with cf.ThreadPoolExecutor(16) as ex:
        list(ex.map(run, batches))

    allr = [json.loads(l) for l in open(res_path, encoding="utf-8")]
    allr = [r for r in allr if r["id"] in {it["id"] for it in items}]
    c = collections.Counter(r["verdict"] for r in allr)
    summary = {"what": f"relevance screen of {a.entity} (after dedup); MODEL JUDGEMENTS, not accuracy",
               "model": MODEL, "sent": "label + ontology prefix + CDM type only (no paper text, no definitions)",
               "concepts": len(items), "judged": len(allr), "missing_rerun_to_fill": len(items) - len(allr),
               "verdicts": dict(c.most_common()),
               "by_type_dropped": dict(collections.Counter(r["cdm_type"] for r in allr if r["verdict"] in ("IRRELEVANT", "NOT_A_CONCEPT")).most_common()),
               "by_ontology_dropped": dict(collections.Counter(r["ontology"] for r in allr if r["verdict"] in ("IRRELEVANT", "NOT_A_CONCEPT")).most_common(25)),
               "note": "filter layer; nothing removed from CDM 3.0.3; pending project-lead approval (CHANGE_RECORD)"}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    with open(OUT / "dropped.tsv", "w", encoding="utf-8") as f:
        f.write("id\tlabel\tontology\tcdm_type\tn_mappings\tverdict\treason\n")
        for r in sorted(allr, key=lambda r: (r["verdict"], r["ontology"], r["label"])):
            if r["verdict"] != "KEEP":
                f.write(f'{r["id"]}\t{r["label"]}\t{r["ontology"]}\t{r["cdm_type"]}\t{r["n_mappings"]}\t{r["verdict"]}\t{r["reason"]}\n')
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
