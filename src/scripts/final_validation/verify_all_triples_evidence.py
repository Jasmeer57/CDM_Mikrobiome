#!/usr/bin/env python3
"""Evidence-anchored LLM screen of CDM triples -- LICENCE-SAFE version (2026-11-09).

Derived from outputs/results/evidence_judge_all_2026-11-07/verify_all_triples_evidence.py (kept unchanged as the
record of that run). Difference: only sentences from CC BY / CC0 papers (rights/PAPER_RIGHTS_MATRIX.csv) are sent;
triples whose only evidence comes from other papers are marked licence_blocked and not sent. Writes to
outputs/results/evidence_judge_ccby_only/.

Original description:

For every canonical triple, send subject/relation/object + the pipeline's own anchor
sentence (relation_evidence.source_sentence, EXACT-anchor preferred, ~260 chars, cap 500)
+ source-paper metadata to FhGenie deepseek-ai/DeepSeek-V4.1-Flash, batched 6 items per
request, and ask: SUPPORT / POLARITY_OK / PREDICATE_JUSTIFIED / QUOTE_MATCH + notes.

This IS the substantive check; the string-level W/M/S/E pass (judge.py / judge_all_
triples_v41.py) is only a screen. MODEL JUDGEMENTS - not accuracy, not human validation.
Reads the frozen DB read-only; writes under outputs/results/evidence_judge_all_2026-11-07/.
Resumable per item (one verdict row per triple).
"""
import json
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/ner_llm_judge"))
from judge import Client, load_cfg, parse  # noqa: E402

DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
import csv as _csv
OUT = ROOT / "outputs/results/evidence_judge_ccby_only"  # never the 2026-11-07 run folder
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
OPEN_LICENCES = {"cc by", "cc0"}
OUT.mkdir(parents=True, exist_ok=True)
MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
BATCH = 6                                  # quoted triples per request
MAX_QUOTE = 500

TASK = """Each item is [n, "subject", "relation", "object", types, "anchor sentence", "paper"].
An automated relation-extraction pipeline produced the triple from a human microbiome paper;
the anchor sentence is the paper sentence it was extracted from (possibly whitespace-
normalised). Judge ONLY from that sentence. Reviewer order: be strict and consistent.

Per item answer [n, support, polar, just, qmatch, notes]:
support    SUPPORTED  the sentence states this subject-rel-object claim (this direction);
           PARTIAL    the sentence conveys it only hedged ("may", "suggests", "probably"),
                      or with a qualifier the triple drops, or one endpoint is a broader
                      paraphrase than the sentence supports;
           NOT_SUPPORTED  the sentence does not state this relation;
           CONFLICTS      the sentence states the opposite;
           NO_EVIDENCE   the sentence is empty/unusable.
polar      Y/N/U -- direction (increase/decrease/produces/increases...) matches the triple's
           relation label; U if the label has no inherent direction (associated_with, etc.).
just       Y/N -- the specific relation label is justified by the sentence's own wording
           (e.g. "associated with" wording does NOT justify CAUSES; produce/produces protein
           justifies PRODUCES). N when a weaker or hedged label would be required.
qmatch     EXACT / EMBEDDED / NONE / LOOSE
           EXACT: subject and object appear nearly verbatim in the sentence;
           EMBEDDED: both are present but paraphrased or inside longer phrases;
           LOOSE: only one endpoint matches; NONE: neither does.
           support must be <= PARTIAL when qmatch is LOOSE, and NOT_SUPPORTED when NONE.
notes      <= 25 words; give the decisive phrase (may/associated/produces...).

Examples:
[0,"a bacterium","PRODUCES","butyrate","taxon|pathway","Strain X produces high levels of butyrate","P1"]
 -> [0,"SUPPORTED","Y","Y","EXACT",""]
[1,"gene list","CAUSES","familial similarity","concept|outcome","raises the possibility that shared genes underlie similarity","P2"]
 -> [1,"PARTIAL","U","N","EMBEDDED","'raises the possibility'; hypothetical wording"]"""
PARTICIPANT = """Per item answer [n, support, polar, just, qmatch, notes] - tokens exactly as
defined above; support/polar/just from NO SHORTHAND (use the token names verbatim); notes
<= 25 words. Return {"r": [[n, support, polar, just, qmatch, notes]...]} exactly one entry
per item, in order."""


LICENCE = {r["paper_id"]: r["licence"].lower() for r in _csv.DictReader(open(RIGHTS, encoding="utf-8"))}


def build():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    papers = {r["paper_id"]: (r["title"] or "", r["publication_year"] or "n.d.")
              for r in con.execute("SELECT paper_id, title, publication_year FROM paper")}
    items, stats = [], Counter()
    rows = con.execute("""SELECT r.canonical_triple_id, r.subject_display_label s,
                                 r.subject_entity_type st, r.relation_normalized rel,
                                 r.object_display_label o, r.object_entity_type ot
                          FROM relation r ORDER BY r.canonical_triple_id""")
    for r in rows:
        # LICENCE GATE (2026-11-09): only sentences from CC BY / CC0 papers may leave the cluster.
        ev = None
        for cand in con.execute("""SELECT paper_id, section_record_id, source_sentence, char_start,
                                   char_end, anchor_status
                            FROM relation_evidence WHERE canonical_triple_id=?
                              AND source_sentence IS NOT NULL AND length(source_sentence)>30
                            ORDER BY (anchor_status='EXACT') DESC,
                                     (anchor_status='NORMALISED') DESC,
                                     abs(length(source_sentence)-260) ASC""",
                          (r["canonical_triple_id"],)):
            if LICENCE.get(cand["paper_id"], "") in OPEN_LICENCES:
                ev = cand
                break
        if ev is None and con.execute("SELECT 1 FROM relation_evidence WHERE canonical_triple_id=? AND source_sentence IS NOT NULL",
                                      (r["canonical_triple_id"],)).fetchone():
            items.append({"id": r["canonical_triple_id"], "no_evidence": True, "licence_blocked": True,
                          "subject": r["s"], "relation": r["rel"], "object": r["o"]})
            stats["licence_blocked"] += 1
            continue
        if ev is None:
            items.append({"id": r["canonical_triple_id"], "no_evidence": True,
                          "subject": r["s"], "relation": r["rel"], "object": r["o"]})
            stats["no_evidence"] += 1
            continue
        q = " ".join(ev["source_sentence"].split())[:MAX_QUOTE]
        title, year = papers.get(ev["paper_id"], ("", "n.d."))
        items.append({"id": r["canonical_triple_id"],
                      "subject": r["s"], "st": r["st"], "relation": r["rel"],
                      "object": r["o"], "ot": r["ot"], "quote": q,
                      "paper": f"{title[:80]} ({year})",
                      "paper_id": ev["paper_id"], "section": ev["section_record_id"],
                      "chars": f"{ev['char_start']}-{ev['char_end']}",
                      "anchor": ev["anchor_status"]})
        stats["with_quote"] += 1
    return items, dict(stats)


def main():
    cfg = load_cfg(str(ROOT / "src/scripts/ner_llm_judge/config.yml"))
    cfg["api"]["model"] = MODEL
    cfg["api"]["max_rpm"] = 250
    cfg["api"]["max_concurrency"] = 48
    cl = Client(cfg["api"])
    items, stats = build()
    (OUT / "items.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n"
                                             for i in items))
    print(f"items: {stats['with_quote']:,} with quotes, {stats['no_evidence']:,} without", flush=True)
    res = OUT / "verdicts.jsonl"
    done = {json.loads(l)["id"] for l in open(res, encoding="utf-8")} if res.exists() else set()
    with open(OUT / "no_evidence.jsonl", "w") as fh:
        for it in items:
            if it.get("no_evidence"):
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    todo = [it for it in items if not it.get("no_evidence") and it["id"] not in done]
    batches = [todo[k:k + BATCH] for k in range(0, len(todo), BATCH)]
    print(f"{len(done):,} judged; {len(todo):,} in {len(batches):,} requests "
          f"(~{len(batches)/250:.1f} min at 250 RPM)", flush=True)
    st, wl = Counter(), threading.Lock()
    errlog = OUT / "errors.log"
    VALID_SUPP = {"SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "CONFLICTS", "NO_EVIDENCE"}

    def run(batch):
        rows = [[n, it["subject"], it["relation"], it["object"],
                 f"{it.get('st','')}|{it.get('ot','')}", it.get("quote", ""), it.get("paper", "")]
                for n, it in enumerate(batch)]
        prompt = TASK + "\n\n" + PARTICIPANT + "\n\nItems:\n" + json.dumps(rows, ensure_ascii=False)
        try:
            content, finish, usage = cl.chat(prompt)
            p = parse(content) or {}
        except Exception as e:  # noqa: BLE001
            content, finish, usage, p = "", "error", {}, {}
            with wl, open(errlog, "a") as fh:
                fh.write(f"{time.strftime('%F %T')} {str(e)[:200]}\n")
        got = {}
        for r in p.get("r", []):
            if isinstance(r, list) and len(r) == 6 and isinstance(r[0], int) \
                    and 0 <= r[0] < len(batch):
                got[r[0]] = r[1:]
        with wl:
            with open(res, "a", encoding="utf-8") as fh:
                for n, it in enumerate(batch):
                    base = {"id": it["id"], "model": MODEL, "quote_paper_id": it.get("paper_id"),
                            "quote_section": it.get("section"), "quote_chars": it.get("chars"),
                            "anchor": it.get("anchor")}
                    if n in got:
                        supp, polar, just, qm, notes = got[n]
                        if supp not in VALID_SUPP:              # malformed token -> unusable
                            st["invalid"] += 1
                            continue
                        fh.write(json.dumps({**base, "support": supp, "polarity_ok": polar,
                                             "predicate_justified": just, "quote_match": qm,
                                             "notes": notes, "finish": finish},
                                            ensure_ascii=False) + "\n")
                        st["ok"] += 1
                    else:
                        st["missing"] += 1
            st["tok_in"] += usage.get("prompt_tokens", 0)
            st["tok_out"] += usage.get("completion_tokens", 0)
            if finish == "length":
                st["trunc_batches"] += 1
        return len(batch)

    n, t0 = 0, time.time()
    with ThreadPoolExecutor(48) as ex:
        futs = [ex.submit(run, b) for b in batches]
        for f in as_completed(futs):
            n += f.result()
            if n % 3600 < BATCH:
                rate = n / max(1e-9, time.time() - t0) * 60
                print(f"  {n:,} | {dict(st)} | {rate:,.0f} items/min", flush=True)
    print("finished:", dict(st), "- re-run to retry missing items", flush=True)


if __name__ == "__main__":
    main()
