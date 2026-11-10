"""Cleaned, DeepSeek-curated layer derived from CDM 3.0.3 and the judge verdicts (the frozen CDM is not modified).

Triples
  1. keep triples judged well-formed with valid subject and object (verdicts from judge.py; no API calls);
  2. relabel kept triples whose label was judged generic or wrong: DeepSeek chooses a specific label from the CDM's
     own relation vocabulary (or keeps OTHER_RELATION), and flags reversed direction. The evidence sentence is sent
     only for papers whose licence allows redistribution (CC BY / CC0); otherwise the triple alone is shown.
Terms
  3. a canonical term is kept if most of its mentions (weighted) were judged valid entities; its type becomes the
     type most often given by the judge for those mentions.
Outputs (outputs/results/cleaned_layer_deepseek/): cleaned_triples.csv.gz, cleaned_terms.csv.gz, relabel.jsonl,
CLEANING_REPORT.md. Every row keeps its original id and value next to the cleaned one.

    python clean.py relabel --config config.yml     # API calls (resumable)
    python clean.py build   --config config.yml     # write the cleaned tables + report
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import sqlite3
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import judge as J

OUT = J.ROOT / "outputs/results/cleaned_layer_deepseek"
JUDGE = J.ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash"
RIGHTS = J.ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
BATCH = 40

RELABEL_TASK = """Each item is a relation triple extracted from a human microbiome paper, with its evidence sentence when available:
[n, "subject", "current relation", "object", "sentence or null"].
Allowed relation labels (choose exactly one; prefer the most specific label the evidence supports):
{labels}
For each item answer [n, LABEL, SWAP]:
LABEL: one allowed label, or "OTHER_RELATION" if none fits or the evidence is insufficient (never invent labels).
SWAP: "Y" if the correct reading is object -> subject for the chosen label, else "N".
Without a sentence, change the label only when the relation is evident from the subject and object themselves.
Return {{"r": [[n, LABEL, SWAP], ...]}} with exactly one entry per item, in order."""


def cdm():
    return sqlite3.connect(f"file:{J.CDM}?mode=ro", uri=True)


def triple_verdicts():
    with gzip.open(JUDGE / "triple_verdicts.csv.gz", "rt", encoding="utf-8") as fh:
        return {r["triple_id"]: r for r in csv.DictReader(fh)}


def to_relabel(c, tv):
    ok = {r["paper_id"] for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))
          if r["proposed_release_decision"] == "INCLUDE_TEXT"}
    sent = {}
    for tid, pid, s in c.execute("SELECT canonical_triple_id, paper_id, source_sentence FROM relation_evidence "
                                 "WHERE relation_table='relation' AND source_sentence IS NOT NULL ORDER BY triple_mention_id"):
        if pid in ok and tid not in sent:
            sent[tid] = s[:600]
    items = []
    for tid, su, rel, ob in c.execute("SELECT canonical_triple_id, subject_display_label, relation_normalized, "
                                      "object_display_label FROM relation"):
        v = tv.get(tid)
        if v and v["well_formed"] == "Y" and v["entities_valid"] == "Y" and v["relation_specific"] in ("G", "N"):
            items.append({"id": tid, "subject": su, "relation": rel, "object": ob, "sentence": sent.get(tid)})
    return items


def labels(c):
    rows = c.execute("SELECT relation_normalized, relation_family, COUNT(*) FROM relation "
                     "WHERE relation_normalized != 'OTHER_RELATION' GROUP BY 1, 2 ORDER BY 2, 3 DESC").fetchall()
    return [r[0] for r in rows], "\n".join(f"- {r[0]} ({r[1]})" for r in rows)


def cmd_relabel(cfg):
    OUT.mkdir(parents=True, exist_ok=True)
    c = cdm()
    items = to_relabel(c, triple_verdicts())
    allowed, help_ = labels(c)
    path = OUT / "relabel.jsonl"
    done = {json.loads(l)["id"] for l in open(path, encoding="utf-8")} if path.exists() else set()
    todo = [i for i in items if i["id"] not in done]
    random.Random(1).shuffle(todo)
    bs = [todo[k:k + BATCH] for k in range(0, len(todo), BATCH)]
    print(f"{len(items):,} triples to relabel ({sum(1 for i in items if i['sentence']):,} with a CC BY sentence); "
          f"{len(done):,} done; {len(bs)} requests", flush=True)
    cl, lock, st = J.Client(cfg["api"]), threading.Lock(), Counter()
    task = RELABEL_TASK.format(labels=help_)
    allowed_set = set(allowed) | {"OTHER_RELATION"}

    def run(b):
        rows = [[n, i["subject"], i["relation"], i["object"], i["sentence"]] for n, i in enumerate(b)]
        try:
            content, _, _ = cl.chat(task + "\n\nItems:\n" + json.dumps(rows, ensure_ascii=False))
            got = {r[0]: r[1:] for r in (J.parse(content) or {}).get("r", [])
                   if isinstance(r, list) and len(r) == 3 and isinstance(r[0], int) and 0 <= r[0] < len(b)}
        except Exception:  # noqa: BLE001
            got = {}
        with lock, open(path, "a", encoding="utf-8") as fh:
            for n, i in enumerate(b):
                if n in got:
                    lab, swap = got[n]
                    valid = lab in allowed_set
                    fh.write(json.dumps({"id": i["id"], "label": lab if valid else "OTHER_RELATION",
                                         "swap": swap == "Y" and valid and lab != "OTHER_RELATION",
                                         "invalid_label_returned": None if valid else lab,
                                         "had_sentence": i["sentence"] is not None}, ensure_ascii=False) + "\n")
                    st["ok"] += 1
                else:
                    st["missing"] += 1

    with ThreadPoolExecutor(int(cfg["api"].get("max_concurrency", 24))) as ex:
        for f in as_completed([ex.submit(run, b) for b in bs]):
            f.result()
    print("finished:", dict(st), "- re-run to retry missing")


def cmd_build(cfg):
    c = cdm()
    tv = triple_verdicts()
    rl = {}
    if (OUT / "relabel.jsonl").exists():
        rl = {json.loads(l)["id"]: json.loads(l) for l in open(OUT / "relabel.jsonl", encoding="utf-8")}
    st = Counter()
    with gzip.open(OUT / "cleaned_triples.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["canonical_triple_id", "kept", "drop_reason", "subject", "relation_original", "relation_cleaned",
                    "object", "direction_swapped", "relabel_evidence", "paper_count"])
        for tid, su, rel, ob, pc in c.execute("SELECT canonical_triple_id, subject_display_label, relation_normalized, "
                                              "object_display_label, paper_count FROM relation ORDER BY 1"):
            v = tv.get(tid, {})
            reason = ("not_well_formed" if v.get("well_formed") != "Y" else
                      "invalid_entities" if v.get("entities_valid") != "Y" else "")
            new, swap, ev = rel, False, ""
            if not reason and tid in rl:
                new, swap = rl[tid]["label"], rl[tid]["swap"]
                ev = "sentence" if rl[tid]["had_sentence"] else "triple_only"
            s2, o2 = (ob, su) if swap else (su, ob)
            w.writerow([tid, int(not reason), reason, s2, rel, new, o2, int(swap), ev, pc])
            st["kept" if not reason else f"dropped_{reason}"] += 1
            if not reason:
                st["generic_after"] += new == "OTHER_RELATION"
                st["generic_before"] += rel == "OTHER_RELATION"
                st["relabelled"] += new != rel
    # terms: weighted majority of mention verdicts
    ev = {}
    inv = {code: t for t, code in J.SCHEMES["cdm"].items()}
    with gzip.open(JUDGE / "entity_verdicts.csv.gz", "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["scheme"] == "cdm":
                ev[(r["string"], r["proposed_type"])] = (r["valid"], r["correct_type"])
    votes = defaultdict(Counter)
    types = defaultdict(Counter)
    for tid, s, t, n in c.execute("SELECT canonical_term_id, lower(trim(surface_form)), entity_type, COUNT(*) "
                                  "FROM term_mention WHERE canonical_term_id IS NOT NULL GROUP BY 1, 2, 3"):
        v = ev.get((J.norm(s), t))
        if not v:
            continue
        votes[tid][v[0]] += n
        if v[0] == "Y" and v[1] not in ("", "-"):
            types[tid][inv.get(v[1], v[1])] += n
    ts = Counter()
    with gzip.open(OUT / "cleaned_terms.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["term_id", "term", "type_original", "type_cleaned", "kept", "valid_mention_share", "mentions_judged"])
        for tid, term, typ in c.execute("SELECT term_id, term, cdm_type FROM canonical_term ORDER BY 1"):
            vv = votes.get(tid, Counter())
            tot = sum(vv.values())
            share = vv["Y"] / tot if tot else 0.0
            keep = tot > 0 and share >= 0.5
            new = types[tid].most_common(1)[0][0] if keep and types[tid] else typ
            w.writerow([tid, term, typ, new, int(keep), round(share, 3), tot])
            ts["kept" if keep else "dropped"] += 1
            if keep:
                ts["retyped"] += new != typ
                ts["entity_before"] += typ == "ENTITY"
                ts["entity_after"] += new == "ENTITY"
    md = ["# DeepSeek-curated cleaned layer", "",
          f"*Derived from CDM 3.0.3 (unchanged) and the judge verdicts of `{JUDGE.relative_to(J.ROOT)}`. "
          "Model curation, not human curation; every row keeps its original value next to the cleaned one.*", "",
          "## Triples", "", "| | count |", "|---|---:|",
          *[f"| {k.replace('_', ' ')} | {v:,} |" for k, v in st.items()], "",
          "## Canonical terms", "", "| | count |", "|---|---:|",
          *[f"| {k.replace('_', ' ')} | {v:,} |" for k, v in ts.items()], "",
          "Kept = most mentions (weighted) judged valid entities. Type cleaned = type most often given by the judge."]
    (OUT / "CLEANING_REPORT.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["relabel", "build"])
    ap.add_argument("--config", default=str(J.Path(__file__).with_name("config.yml")))
    a = ap.parse_args()
    cfg = J.load_cfg(a.config, need_key=a.cmd == "relabel")
    cmd_relabel(cfg) if a.cmd == "relabel" else cmd_build(cfg)


if __name__ == "__main__":
    main()
