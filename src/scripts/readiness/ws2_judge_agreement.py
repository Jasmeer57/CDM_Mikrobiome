"""WS-2: agreement between model judges (no human annotation; agreement is not accuracy).

Terms (CDM 3.0.3 canonical terms):
  * Qwen3.5-9B 4-bit (stage B of the 3.1 candidate repair, 2026-11-05; sees the term, its type and one sentence)
    vs DeepSeek-V4-Flash (benchmark judge, 2026-11-03; scheme "cdm", keyed by string + proposed type).
    Joined on (lower-cased term, CDM type); DeepSeek strings are lower case. Only Qwen *model* answers are used (rule flags and missing answers excluded).
    Validity and relevance: Cohen's kappa overall and per CDM type, bootstrap 95% CI (1,000 resamples).
    Type: among terms both judges call valid, agreement of Qwen's proposed type with DeepSeek's correct type.
  * The 3,000-term AI-model spot check (Claude, 2026-11-05): pairwise kappa with each judge and Fleiss' kappa for
    the three judges on validity.
Triples: the 499 spot-checked triples, Claude vs the DeepSeek evidence check (sentence-support code Y/P/R/N), per
relation type, and the binary "label supported (Y) vs not" collapse.

Writes outputs/results/benchmark/judge_agreement_2026-11-05/{summary.json,REPORT.md}.
"""
from __future__ import annotations

import csv
import gzip
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
B = ROOT / "outputs/results/benchmark"
QWEN = ROOT / "outputs/results/cdm_v3_3.1_deepseek_repair/stage_b_terms_qwen/validation/TERM_DECISIONS.csv"
DS_ENT = B / "llm_judge_deepseek_v4_flash/entity_verdicts.csv.gz"
TSC = B / "term_spotcheck_claude_2026-11-05"
TRC = B / "triple_spotcheck_claude_2026-11-05"
DS_EVID = ROOT / "outputs/results/kg_2026-11-04/evidence_check/evidence_verdicts.csv.gz"
OUT = B / "judge_agreement_2026-11-05"
csv.field_size_limit(1 << 30)
random.seed(20261105)


def kappa(pairs):
    pairs = list(pairs)
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return None if pe == 1 else (po - pe) / (1 - pe)


def boot(pairs, reps=1000):
    pairs = list(pairs)
    if len(pairs) < 20:
        return None
    ks = sorted(k for k in (kappa(random.choices(pairs, k=len(pairs))) for _ in range(reps)) if k is not None)
    return [round(ks[int(0.025 * len(ks))], 3), round(ks[int(0.975 * len(ks)) - 1], 3)]


def stat(pairs, ci=True):
    pairs = list(pairs)
    k = kappa(pairs)
    binary = bool(pairs) and all(isinstance(a, bool) and isinstance(b, bool) for a, b in pairs)
    return {"n": len(pairs), "agreement_pct": round(100 * sum(a == b for a, b in pairs) / len(pairs), 1) if pairs else None,
            "kappa": None if k is None else round(k, 3), "kappa_ci95": boot(pairs) if ci else None,
            "positive_rate_a_pct": round(100 * sum(a is True for a, _ in pairs) / len(pairs), 1) if binary else None,
            "positive_rate_b_pct": round(100 * sum(b is True for _, b in pairs) / len(pairs), 1) if binary else None}


def fleiss(rows):
    """rows: list of tuples of category labels, one per rater."""
    n, m = len(rows), len(rows[0])
    cats = sorted({x for r in rows for x in r}, key=str)
    p = {c: sum(r.count(c) for r in rows) / (n * m) for c in cats}
    pi = [(sum(r.count(c) ** 2 for c in cats) - m) / (m * (m - 1)) for r in rows]
    pbar, pe = sum(pi) / n, sum(v * v for v in p.values())
    return round((pbar - pe) / (1 - pe), 3)


def yn(v):
    return {"Y": True, "N": False, "True": True, "False": False}.get(v)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ds = {}
    with gzip.open(DS_ENT, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["scheme"] == "cdm":
                ds[(r["string"].lower(), r["proposed_type"])] = r   # DeepSeek strings are lower-cased
    qwen, joined = {}, []
    for r in csv.DictReader(open(QWEN, encoding="utf-8")):
        if r["evidence_level"] == "RULE" or r["valid"] == "" or r["decision"] in ("NOT_PROCESSED",) or \
                r["reason"] == "no_valid_answer_for_item":
            continue
        qwen[r["term_id"]] = r
        d = ds.get((r["term"].lower(), r["type_original"]))
        if d:
            joined.append((r, d))
    res = {"note": "Agreement between model judges is not accuracy. No human annotation.",
           "terms": {"qwen_model_answers": len(qwen), "deepseek_cdm_items": len(ds), "joined": len(joined)}}
    v = [(yn(q["valid"]), yn(d["valid"])) for q, d in joined]
    rel = [(yn(q["relevant"]), yn(d["microbiome_relevant"])) for q, d in joined
           if yn(q["relevant"]) is not None and yn(d["microbiome_relevant"]) is not None]
    res["terms"]["validity_qwen_vs_deepseek"] = stat(v)
    res["terms"]["relevance_qwen_vs_deepseek"] = stat(rel)
    res["terms"]["relevance_note"] = ("definitions differ: Qwen 'relevant to the human microbiome' (broad), DeepSeek "
                                      "'microbiome-relevant'")
    by = defaultdict(list)
    for q, d in joined:
        by[q["type_original"]].append((yn(q["valid"]), yn(d["valid"])))
    res["terms"]["validity_by_cdm_type"] = {t: stat(p) for t, p in sorted(by.items(), key=lambda x: -len(x[1]))}
    both = [(q["type_proposed"], d["correct_type"]) for q, d in joined
            if yn(q["valid"]) and yn(d["valid"]) and d["correct_type"] not in ("", "-") and q["type_proposed"]]
    res["terms"]["type_among_both_valid"] = stat(both, ci=False) | {"note": "multi-class; kappa over CDM types"}

    # three judges on the 3,000-term spot check
    samp = {json.loads(l)["n"]: json.loads(l) for l in open(TSC / "sample.jsonl", encoding="utf-8")}
    cl = {int(r["n"]): r for r in csv.DictReader(open(TSC / "verdicts.tsv", encoding="utf-8"), delimiter="\t")}
    tri, pc_ds, pc_q = [], [], []
    for n, s in samp.items():
        c = yn(cl.get(n, {}).get("V"))
        d = ds.get((s["term"].lower(), s["cdm_type"]))
        q = qwen.get(s["term_id"])
        dv, qv = (yn(d["valid"]) if d else None), (yn(q["valid"]) if q else None)
        if c is not None and dv is not None:
            pc_ds.append((c, dv))
        if c is not None and qv is not None:
            pc_q.append((c, qv))
        if None not in (c, dv, qv):
            tri.append((c, dv, qv))
    res["spot_check_3000"] = {
        "claude_vs_deepseek_validity": stat(pc_ds), "claude_vs_qwen_validity": stat(pc_q),
        "three_judges_n": len(tri), "fleiss_kappa_validity": fleiss(tri) if tri else None,
        "all_three_agree_pct": round(100 * sum(len(set(t)) == 1 for t in tri) / len(tri), 1) if tri else None,
        "note": "Claude = AI-model spot check (2026-11-05), not a human or author check"}

    # triples: Claude vs DeepSeek evidence check, per relation type
    ev = {}
    with gzip.open(DS_EVID, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ev.setdefault(r["canonical_triple_id"], r)
    ts = {json.loads(l)["n"]: json.loads(l) for l in open(TRC / "sample.jsonl", encoding="utf-8")}
    tc = {int(r["n"]): r for r in csv.DictReader(open(TRC / "verdicts.tsv", encoding="utf-8"), delimiter="\t")}
    pairs, byrel = [], defaultdict(list)
    for n, s in ts.items():
        c, d = tc.get(n, {}).get("A"), ev.get(s["canonical_triple_id"], {}).get("A")
        if c and d and d != "-":
            pairs.append((c, d))
            byrel[s["predicate"]].append((c, d))
    res["triples_500"] = {
        "support_code_4class": stat(pairs),
        "supported_vs_not_binary": stat([(a == "Y", b == "Y") for a, b in pairs]),
        "confusion_claude_by_deepseek": dict(Counter(f"{a}|{b}" for a, b in pairs)),
        "by_relation": {k: stat(p, ci=False) for k, p in sorted(byrel.items(), key=lambda x: -len(x[1])) if len(p) >= 10},
        "codes": "Y supported as labelled; P related but label not supported; R reversed; N not supported"}
    (OUT / "summary.json").write_text(json.dumps(res, indent=1) + "\n")
    t = res["terms"]
    L = ["# Agreement between model judges (WS-2), 2026-11-05", "",
         "Model judges only; agreement is not accuracy. Claude = AI-model spot check, not a human check.", "",
         f"Terms: {t['joined']:,} canonical terms judged by both Qwen3.5-9B (stage B) and DeepSeek-V4-Flash.", "",
         "| Comparison | n | agreement % | κ [95% CI] | positive rate A / B % |", "|---|---:|---:|---|---|"]

    def row(name, s):
        ci = f" [{s['kappa_ci95'][0]}–{s['kappa_ci95'][1]}]" if s.get("kappa_ci95") else ""
        pr = f"{s['positive_rate_a_pct']} / {s['positive_rate_b_pct']}" if s['positive_rate_a_pct'] is not None else "—"
        return f"| {name} | {s['n']:,} | {s['agreement_pct']} | {s['kappa']}{ci} | {pr} |"
    L += [row("Validity, Qwen vs DeepSeek", t["validity_qwen_vs_deepseek"]),
          row("Relevance, Qwen vs DeepSeek (definitions differ)", t["relevance_qwen_vs_deepseek"]),
          row("Validity, Claude vs DeepSeek (3,000 sample)", res["spot_check_3000"]["claude_vs_deepseek_validity"]),
          row("Validity, Claude vs Qwen (3,000 sample)", res["spot_check_3000"]["claude_vs_qwen_validity"]),
          row("Triple support Y/P/R/N, Claude vs DeepSeek", res["triples_500"]["support_code_4class"]),
          row("Triple supported vs not, Claude vs DeepSeek", res["triples_500"]["supported_vs_not_binary"]), "",
          f"Fleiss' κ, three judges, validity (n = {res['spot_check_3000']['three_judges_n']:,}): "
          f"{res['spot_check_3000']['fleiss_kappa_validity']}; all three agree on "
          f"{res['spot_check_3000']['all_three_agree_pct']}%.", "",
          f"Type agreement among terms both call valid: {t['type_among_both_valid']['agreement_pct']}% "
          f"(κ {t['type_among_both_valid']['kappa']}, n = {t['type_among_both_valid']['n']:,}).", "",
          "## Validity κ by CDM type (Qwen vs DeepSeek)", "", "| CDM type | n | agreement % | κ [95% CI] |", "|---|---:|---:|---|"]
    for k, s in t["validity_by_cdm_type"].items():
        ci = f" [{s['kappa_ci95'][0]}–{s['kappa_ci95'][1]}]" if s.get("kappa_ci95") else ""
        L.append(f"| {k} | {s['n']:,} | {s['agreement_pct']} | {s['kappa']}{ci} |")
    L += ["", "## Triple support κ by relation (Claude vs DeepSeek, n ≥ 10)", "", "| relation | n | agreement % | κ |", "|---|---:|---:|---:|"]
    for k, s in res["triples_500"]["by_relation"].items():
        L.append(f"| {k} | {s['n']} | {s['agreement_pct']} | {s['kappa']} |")
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:16]))


if __name__ == "__main__":
    main()
