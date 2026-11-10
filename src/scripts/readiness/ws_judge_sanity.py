"""Judge sanity check (approved by the project lead 2026-11-05): does the local term judge reject known-wrong items?

Judge: the stage B term judge of the CDM 3.1 candidate repair (Qwen3.5-9B 4-bit, same prompt term_repair_v1.md, same
batching of 25, same sentence per term), run locally on a cluster GPU; nothing leaves the cluster.

Controls (fixed seed 20261105; written to inputs before any model call):
  POS        500 terms whose CDM type is confirmed by an exact vocabulary name (stage B KEEP_TYPE|VOCAB_CONFIRMED),
             with their own type and sentence. Expected: valid, type kept.
  WRONGTYPE  the same 500 terms and sentences, with the type replaced by a different specific CDM type drawn at random.
             Expected: the judge does not keep the injected type (ideally restores the original).
  SPAN       500 fragments: 2-4 consecutive words of the same sentences that start or end with a function word and are
             not a canonical term. Expected: judged not a valid term.
The 1,500 items are shuffled and batched in 25s, so a batch mixes the groups.

Outcome measures (Wilson 95% CIs): POS valid % and type-kept %; WRONGTYPE injected-type-kept %, original-type-restored %;
SPAN invalid %. Writes outputs/results/benchmark/judge_sanity_qwen_2026-11-05/.

    python ws_judge_sanity.py build
    python ws_judge_sanity.py run          # needs a vLLM server (LLM_HOST); see ws_judge_sanity.sbatch
    python ws_judge_sanity.py score
    (add --open-only to every command: all terms, sentences and fragments from CC BY / CC0 papers only, written to
     judge_sanity_open_2026-11-05/; this identical item set can be given to an external judge if approved)
"""
from __future__ import annotations

import csv
import json
import math
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
PIPE = ROOT / "pipelines/cdm_repair"
sys.path.insert(0, str(PIPE))
from common import load_config  # noqa: E402
from local_llm import LocalLLM  # noqa: E402
from repair_runner import fill, load_prompt, run_items  # noqa: E402

OUT = ROOT / "outputs/results/benchmark/judge_sanity_qwen_2026-11-05"
WS = ROOT / "outputs/results/cdm_v3_3.1_deepseek_repair/stage_b_terms_qwen"
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
SPECIFIC = ["ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE", "GENOMICS", "PATHWAY", "LAB_METHOD",
            "DATA_ANALYSIS", "SAMPLE_METHOD", "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN"]
FUNC = {"the", "of", "and", "in", "with", "was", "were", "to", "a", "an", "for", "by", "on", "from", "that", "is", "are",
        "as", "at", "or", "which", "these", "this", "between", "after", "than"}
N, SEED = 500, 20261105
OPEN_ONLY = "--open-only" in sys.argv
if OPEN_ONLY:
    OUT = ROOT / "outputs/results/benchmark/judge_sanity_open_2026-11-05"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
csv.field_size_limit(1 << 30)


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def build():
    rnd = random.Random(SEED)
    mention = {t["term_id"]: t.get("mention_row_id") for b in map(json.loads, open(WS / "inputs/term_batches.jsonl"))
               for t in b["terms"]}
    pos = [r for r in csv.DictReader(open(WS / "validation/TERM_DECISIONS.csv", encoding="utf-8"))
           if r["decision"] == "KEEP_TYPE" and r["evidence_level"] == "VOCAB_CONFIRMED" and mention.get(r["term_id"])]
    con = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    open_papers = {r["paper_id"] for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))
                   if r["proposed_release_decision"] == "INCLUDE_TEXT"}
    canon = {t.lower() for (t,) in con.execute("SELECT term FROM canonical_term")}
    rnd.shuffle(pos)
    items, spans = [], []
    for r in pos:
        if len(items) >= 2 * N and len(spans) >= N:
            break
        s = con.execute("SELECT supporting_sentence, paper_id FROM term_mention WHERE mention_row_id = ?", (mention[r["term_id"]],)).fetchone()
        if OPEN_ONLY and (not s or s[1] not in open_papers):
            continue
        sent = " ".join((s[0] if s else "").split())[:400]
        if not sent:
            continue
        if len(items) < 2 * N:
            wrong = rnd.choice([t for t in SPECIFIC if t != r["type_original"]])
            items.append({"group": "POS", "term": r["term"], "type": r["type_original"], "orig_type": r["type_original"], "sentence": sent})
            items.append({"group": "WRONGTYPE", "term": r["term"], "type": wrong, "orig_type": r["type_original"], "sentence": sent})
        if len(spans) < N:
            w = re.findall(r"[A-Za-z][\w\-]*", sent)
            cands = [" ".join(w[i:i + k]) for k in (2, 3, 4) for i in range(len(w) - k + 1)
                     if (w[i].lower() in FUNC or w[i + k - 1].lower() in FUNC) and " ".join(w[i:i + k]).lower() not in canon
                     and r["term"].lower() not in " ".join(w[i:i + k]).lower()]
            if cands:
                spans.append({"group": "SPAN", "term": rnd.choice(cands), "type": r["type_original"], "orig_type": None, "sentence": sent})
    allit = items + spans
    rnd.shuffle(allit)
    for i, it in enumerate(allit):
        it["id"] = f"S{i:04d}"
    batches = [{"item_id": f"SB{j:03d}", "items": allit[j * 25:(j + 1) * 25]} for j in range((len(allit) + 24) // 25)]
    (OUT / "inputs").mkdir(parents=True, exist_ok=True)
    with open(OUT / "inputs/batches.jsonl", "w", encoding="utf-8") as fh:
        for b in batches:
            fh.write(json.dumps(b, ensure_ascii=False) + "\n")
    print(json.dumps({"items": len(allit), "groups": Counter(i["group"] for i in allit), "batches": len(batches)}))


def run():
    cfg = load_config()
    batches = [json.loads(l) for l in open(OUT / "inputs/batches.jsonl", encoding="utf-8")]
    system, user_t, psha = load_prompt("term_repair_v1.md")
    llm = LocalLLM(cfg, max_tokens=cfg["stage_b"].get("max_tokens"))
    served = llm.served_model()

    def render(b):
        lines = [f'{i}. TERM: "{t["term"]}" | TYPE: {t["type"]} | SENTENCE: {t["sentence"]}' for i, t in enumerate(b["items"], 1)]
        return system, fill(user_t, items="\n".join(lines))
    print(json.dumps(run_items(batches, "item_id", render, llm, OUT / "runs/answers.jsonl", cfg["local_llm"]["parallel"],
                               {"prompt_sha256": psha, "model": served})))


def score():
    batches = {b["item_id"]: b for b in map(json.loads, open(OUT / "inputs/batches.jsonl", encoding="utf-8"))}
    ans = {}
    for l in open(OUT / "runs/answers.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("response"):
            ans[r["item_id"]] = r
    g = {k: Counter() for k in ("POS", "WRONGTYPE", "SPAN")}
    for bid, b in batches.items():
        got = {a.get("n"): a for a in (ans.get(bid, {}).get("response") or {}).get("items", []) if isinstance(a, dict)}
        for i, it in enumerate(b["items"], 1):
            a, c = got.get(i), g[it["group"]]
            c["n"] += 1
            if not a or not isinstance(a.get("valid"), bool):
                c["no_answer"] += 1
                continue
            c["answered"] += 1
            c["valid"] += a["valid"]
            t = a.get("type")
            c["type_is_given"] += t == it["type"]
            if it["orig_type"]:
                c["type_is_original"] += t == it["orig_type"]
    res = {"judge": "Qwen3.5-9B 4-bit, prompt term_repair_v1.md (stage B)", "item_set": "CC BY / CC0 papers only" if OPEN_ONLY else "all papers", "note": "Model behaviour on constructed controls; not accuracy on real terms.", "groups": {}}
    for k, c in g.items():
        n = c["answered"]
        d = {"items": c["n"], "answered": n, "no_answer": c["no_answer"]}
        if k == "POS":
            d |= {"valid_pct": [round(100 * c["valid"] / n, 1), wilson(c["valid"], n)],
                  "type_kept_pct": [round(100 * c["type_is_given"] / n, 1), wilson(c["type_is_given"], n)]}
        elif k == "WRONGTYPE":
            d |= {"injected_type_kept_pct": [round(100 * c["type_is_given"] / n, 1), wilson(c["type_is_given"], n)],
                  "original_type_restored_pct": [round(100 * c["type_is_original"] / n, 1), wilson(c["type_is_original"], n)],
                  "valid_pct": [round(100 * c["valid"] / n, 1), wilson(c["valid"], n)]}
        else:
            inv = n - c["valid"]
            d |= {"judged_invalid_pct": [round(100 * inv / n, 1), wilson(inv, n)]}
        res["groups"][k] = d
    (OUT / "summary.json").write_text(json.dumps(res, indent=1) + "\n")
    G = res["groups"]
    L = ["# Judge sanity check (Qwen3.5-9B term judge), 2026-11-05", "", res["note"], "",
         "| control | n answered | measure | % [95% CI] |", "|---|---:|---|---|",
         f"| POS (vocabulary-confirmed terms) | {G['POS']['answered']} | judged valid | {G['POS']['valid_pct'][0]} {G['POS']['valid_pct'][1]} |",
         f"| POS | {G['POS']['answered']} | type kept | {G['POS']['type_kept_pct'][0]} {G['POS']['type_kept_pct'][1]} |",
         f"| WRONGTYPE (same terms, random wrong type) | {G['WRONGTYPE']['answered']} | injected wrong type kept | {G['WRONGTYPE']['injected_type_kept_pct'][0]} {G['WRONGTYPE']['injected_type_kept_pct'][1]} |",
         f"| WRONGTYPE | {G['WRONGTYPE']['answered']} | original type restored | {G['WRONGTYPE']['original_type_restored_pct'][0]} {G['WRONGTYPE']['original_type_restored_pct'][1]} |",
         f"| SPAN (random fragments) | {G['SPAN']['answered']} | judged not a term | {G['SPAN']['judged_invalid_pct'][0]} {G['SPAN']['judged_invalid_pct'][1]} |"]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    {"build": build, "run": run, "score": score}[sys.argv[1]]()   # flags such as --open-only are read at import
