"""Licence-group model comparability (diagnostics 2026-11-11, item 1).

Unsigned associations (retype-v2.5 ASSOCIATION_UNSIGNED, 1,708) were resolved by DeepSeek-V4.1-Flash for triples whose
evidence papers are all CC BY / CC0 (959) and by local Qwen3.5-9B for the rest (749). This script
  A. compares DeepSeek with local Qwen3.5-9B on the SAME 959 CC BY / CC0 triples (Qwen run by unsigned_local_open.py,
     same prompts, batching, gates and verification; regate v1.1 re-applied with the code of unsigned_regate.py):
     agreement on the final relation, on resolved-vs-unsigned, Cohen's kappa (bootstrap 95% CI), resolution rates with
     Wilson 95% CIs, exact McNemar test for the paired resolution rates, sign agreement where both are signed;
  B. compares paper / evidence characteristics of the two licence groups (selection bias): publication year, journal,
     publisher (DOI prefix), evidence section types, evidence sentence length, triples per paper, evidence papers per
     triple (Mann-Whitney U / chi-square).
Reads only; writes outputs/results/diagnostics_2026-11-11/licence_comparability/{SUMMARY.json, REPORT.md, pairs.jsonl}.

    python src/scripts/diagnostics_v32/licence_comparability.py
Written with Claude Code (declare)."""
from __future__ import annotations

import csv
import glob
import json
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scipy import stats

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/diagnostics_v32"))
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
from stats_util import kappa_with_ci, prop  # noqa: E402
import unsigned_regate as RG  # noqa: E402  (SIGN, SIGNED, mentions: regate v1.1 rules, unchanged)

FROZEN = ROOT / "outputs/results/unsigned_resolve_2026-11-10/all"
NEW = ROOT / "outputs/results/diagnostics_2026-11-11/licence_comparability/local_on_open"
OUT = ROOT / "outputs/results/diagnostics_2026-11-11/licence_comparability"
DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
POS = {"POSITIVELY_ASSOCIATED_WITH", "INCREASED_IN", "PROMOTES", "UPREGULATES", "INCREASES_RISK_OF", "MORE_ABUNDANT_THAN",
       "INCREASES_OVER_TIME", "EXACERBATES", "IMPAIRS"}
NEG = {"NEGATIVELY_ASSOCIATED_WITH", "DECREASED_IN", "SUPPRESSES", "DOWNREGULATES", "PROTECTIVE_AGAINST", "LESS_ABUNDANT_THAN",
       "DECREASES_OVER_TIME", "IMPROVES", "ALLEVIATES", "INHIBITS"}


def regate(r):
    """regate v1.1, identical rules to unsigned_regate.main() (applied to a copy)."""
    r = dict(r)
    if not r["specific_verified"]:
        return r
    reason = None
    if r["relation"] in RG.SIGNED and not RG.SIGN.search(r["cue"].lower()):
        reason = "SIGN_WORD_ONLY_RISK"
    elif r["step"] == "SECTION":
        ms, mo = RG.mentions(r["cue"], r["subject"]), RG.mentions(r["cue"], r["object"])
        if not (ms or mo):
            reason = "SECTION_CUE_MENTIONS_NEITHER_ENDPOINT"
    if reason:
        r.update(proposed_relation=r["relation"], relation="ASSOCIATION_UNSIGNED", specific_verified=False, regate_reason=reason)
    return r


def sign(rel):
    return "POS" if rel in POS else "NEG" if rel in NEG else None


def outcome(r):
    return "RESOLVED" if r["specific_verified"] else r["relation"] if r["relation"] in ("NULL_FINDING", "BAD_ENDPOINT", "NOT_SUPPORTED") else "UNSIGNED"


def mcnemar_exact(b, c):
    n = b + c
    return None if n == 0 else round(float(stats.binomtest(b, n, 0.5).pvalue), 4)


def compare(ds, qw):
    ids = sorted(set(ds) & set(qw))
    A, B = [ds[i] for i in ids], [qw[i] for i in ids]
    rel_a, rel_b = [a["relation"] for a in A], [b["relation"] for b in B]
    res_a, res_b = [a["specific_verified"] for a in A], [b["specific_verified"] for b in B]
    out_a, out_b = [outcome(a) for a in A], [outcome(b) for b in B]
    both = [(a, b) for a, b in zip(A, B) if a["specific_verified"] and b["specific_verified"]]
    signed = [(a, b) for a, b in both if sign(a["relation"]) and sign(b["relation"])]
    n = len(ids)
    b_only_ds = sum(x and not y for x, y in zip(res_a, res_b))
    c_only_qw = sum(y and not x for x, y in zip(res_a, res_b))
    return {
        "n_common": n,
        "resolution_rate": {"deepseek": prop(sum(res_a), n), "qwen9b_local": prop(sum(res_b), n)},
        "resolved_vs_not": {"agreement": prop(sum(x == y for x, y in zip(res_a, res_b)), n),
                            "both_resolved": sum(x and y for x, y in zip(res_a, res_b)), "deepseek_only": b_only_ds,
                            "qwen_only": c_only_qw, "neither": sum(not x and not y for x, y in zip(res_a, res_b)),
                            "kappa": kappa_with_ci(res_a, res_b), "mcnemar_exact_p": mcnemar_exact(b_only_ds, c_only_qw)},
        "final_relation": {"agreement": prop(sum(x == y for x, y in zip(rel_a, rel_b)), n), "kappa": kappa_with_ci(rel_a, rel_b)},
        "outcome_class": {"agreement": prop(sum(x == y for x, y in zip(out_a, out_b)), n), "kappa": kappa_with_ci(out_a, out_b),
                          "deepseek": dict(Counter(out_a)), "qwen9b_local": dict(Counter(out_b))},
        "among_both_resolved": {"n": len(both), "same_relation": prop(sum(a["relation"] == b["relation"] for a, b in both), len(both)),
                                "same_relation_and_direction": prop(sum(a["relation"] == b["relation"] and a.get("direction") == b.get("direction")
                                                                        for a, b in both), len(both)),
                                "both_signed": len(signed),
                                "same_sign": prop(sum(sign(a["relation"]) == sign(b["relation"]) for a, b in signed), len(signed))},
        "step": {"deepseek_section_step_among_resolved": sum(a["step"] == "SECTION" for a in A if a["specific_verified"]),
                 "qwen_section_step_among_resolved": sum(b["step"] == "SECTION" for b in B if b["specific_verified"])},
    }


def load_jsonl(paths):
    return [json.loads(l) for p in paths for l in open(p, encoding="utf-8") if l.strip()]


def part_a():
    final = {r["canonical_triple_id"]: r for r in load_jsonl([FROZEN / "final.jsonl"])}
    ds_raw = {r["canonical_triple_id"]: r for r in load_jsonl([FROZEN / "unsigned_resolved.genie.jsonl"])}
    qw_rest = [r for r in final.values() if r["backend"] == "local"]
    parts = sorted(glob.glob(str(NEW / "unsigned_resolved.*.jsonl")))
    if not parts:
        return None, None
    qw_raw = {}
    for r in load_jsonl(parts):
        r = dict(r, backend="local_on_open", licence_route="CC_BY_OR_CC0_RUN_LOCALLY")
        qw_raw[r["canonical_triple_id"]] = r
    qw = {k: regate(v) for k, v in qw_raw.items()}
    ds = {k: final[k] for k in ds_raw}          # DeepSeek after the frozen regate v1.1
    assert all(final[k]["backend"] == "genie" for k in ds)
    # check: re-applying regate to the frozen DeepSeek raw rows reproduces final.jsonl
    repro = sum(regate(ds_raw[k])["relation"] == ds[k]["relation"] for k in ds)
    res = {"n_deepseek": len(ds), "n_qwen_on_open": len(qw), "missing_in_qwen": sorted(set(ds) - set(qw))[:20],
           "regate_reproduces_frozen_deepseek": f"{repro}/{len(ds)}",
           "qwen_unparsed": sum(r["relation"] == "UNPARSED" for r in qw.values()),
           "after_regate_v1_1": compare(ds, qw),
           "before_regate_raw": compare(ds_raw, qw_raw),
           "qwen_on_rest_749_frozen": {"resolution_rate": prop(sum(r["specific_verified"] for r in qw_rest), len(qw_rest))}}
    q_open = res["after_regate_v1_1"]["resolution_rate"]["qwen9b_local"]
    k1, n1, k2, n2 = q_open["k"], q_open["n"], res["qwen_on_rest_749_frozen"]["resolution_rate"]["k"], len(qw_rest)
    res["qwen_open_vs_rest"] = {"fisher_p": round(float(stats.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])[1]), 4)}
    with open(OUT / "pairs.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(set(ds) & set(qw)):
            a, b = ds[k], qw[k]
            f.write(json.dumps({"canonical_triple_id": k, "subject": a["subject"], "object": a["object"],
                                "deepseek": {x: a.get(x) for x in ("relation", "direction", "cue", "step", "verify", "specific_verified", "regate_reason")},
                                "qwen9b": {x: b.get(x) for x in ("relation", "direction", "cue", "step", "verify", "specific_verified", "regate_reason")}},
                               ensure_ascii=False) + "\n")
    return res, (ds, qw)


def part_b():
    final = load_jsonl([FROZEN / "final.jsonl"])
    grp = {r["canonical_triple_id"]: ("open" if r["backend"] == "genie" else "rest") for r in final}
    lic = {r["paper_id"]: r for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))}
    c = sqlite3.connect(f"file:{DB303}?mode=ro", uri=True)
    paper = {r[0]: {"year": int(r[1]) if str(r[1] or "").strip().isdigit() else None, "journal": (r[2] or "").strip().lower()} for r in c.execute("SELECT paper_id, publication_year, journal FROM paper")}
    ev = defaultdict(list)
    for tid, pid, sent, stype in c.execute(
            "SELECT e.canonical_triple_id, e.paper_id, e.source_sentence, s.section_type FROM relation_evidence e "
            "LEFT JOIN section s USING(section_record_id) WHERE e.source_sentence IS NOT NULL"):
        if tid in grp:
            ev[tid].append((pid, sent, stype))
    G = {"open": defaultdict(list), "rest": defaultdict(list)}
    tri_per_paper = {"open": Counter(), "rest": Counter()}
    for tid, g in grp.items():
        rows = ev.get(tid, [])
        G[g]["n_evidence_papers"].append(len({p for p, _, _ in rows}))
        G[g]["no_evidence_sentence"].append(int(not rows))
        for p, s, t in rows:
            G[g]["sentence_words"].append(len(s.split()))
            G[g]["section_type"].append(t or "NONE")
        for p in {p for p, _, _ in rows}:
            tri_per_paper[g][p] += 1
            G[g]["year_by_triple"].append(paper.get(p, {}).get("year"))
    out = {"n_triples": {g: sum(1 for x in grp.values() if x == g) for g in G}}
    def num(name, a, b):
        a, b = [x for x in a if isinstance(x, (int, float))], [x for x in b if isinstance(x, (int, float))]
        u = stats.mannwhitneyu(a, b) if a and b else None
        return {"open": {"n": len(a), "median": st.median(a) if a else None, "mean": round(st.mean(a), 2) if a else None},
                "rest": {"n": len(b), "median": st.median(b) if b else None, "mean": round(st.mean(b), 2) if b else None},
                "mannwhitney_p": None if u is None else float(f"{u.pvalue:.3g}")}
    def cat(name, a, b, top=8):
        ca, cb = Counter(a), Counter(b)
        keys = [k for k, _ in (ca + cb).most_common(top)]
        tab = [[ca[k] for k in keys] + [sum(ca.values()) - sum(ca[k] for k in keys)],
               [cb[k] for k in keys] + [sum(cb.values()) - sum(cb[k] for k in keys)]]
        tab = [[x for x, keep in zip(row, [True] * len(keys) + [tab[0][-1] + tab[1][-1] > 0]) if keep] for row in tab]
        chi = stats.chi2_contingency(tab)
        na, nb = sum(ca.values()), sum(cb.values())
        return {"categories": {k: {"open_pct": round(100 * ca[k] / na, 1), "rest_pct": round(100 * cb[k] / nb, 1)} for k in keys},
                "n_open": na, "n_rest": nb, "chi2_p": float(f"{chi.pvalue:.3g}"),
                "cramers_v": round((chi.statistic / ((na + nb) * (min(len(tab), len(tab[0])) - 1))) ** 0.5, 3)}
    papers = {g: set(tri_per_paper[g]) for g in G}
    out["papers"] = {g: len(papers[g]) for g in G}
    out["papers_in_both_groups"] = len(papers["open"] & papers["rest"])
    out["triple_level"] = {
        "sentence_words": num("sentence_words", G["open"]["sentence_words"], G["rest"]["sentence_words"]),
        "n_evidence_papers": num("n_evidence_papers", G["open"]["n_evidence_papers"], G["rest"]["n_evidence_papers"]),
        "no_evidence_sentence": {g: sum(G[g]["no_evidence_sentence"]) for g in G},
        "section_type": cat("section_type", G["open"]["section_type"], G["rest"]["section_type"]),
    }
    po, pr = sorted(papers["open"]), sorted(papers["rest"] - papers["open"])
    out["paper_level"] = {
        "note": "open = papers contributing evidence to the 959 CC BY / CC0 triples; rest = papers contributing only to the 749 others",
        "year": num("year", [paper[p]["year"] for p in po if p in paper], [paper[p]["year"] for p in pr if p in paper]),
        "unsigned_triples_per_paper": num("tpp", [tri_per_paper["open"][p] for p in po], [tri_per_paper["rest"][p] for p in pr]),
        "journal": cat("journal", [paper.get(p, {}).get("journal", "") for p in po], [paper.get(p, {}).get("journal", "") for p in pr], 10),
        "doi_prefix": cat("doi_prefix", [lic.get(p, {}).get("doi_prefix", "") for p in po], [lic.get(p, {}).get("doi_prefix", "") for p in pr], 10),
        "licence_of_rest": dict(Counter(lic.get(p, {}).get("licence", "") for p in pr).most_common()),
    }
    # all CDM triples of these papers (not just unsigned): overall extraction density
    allc = Counter(p for (p,) in c.execute("SELECT paper_id FROM relation_evidence"))
    out["paper_level"]["all_triple_mentions_per_paper"] = num("all", [allc[p] for p in po], [allc[p] for p in pr])
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    a, _ = part_a()
    b = part_b()
    s = {"date": "2026-11-11", "item": "licence-group model comparability (unsigned-association resolution)",
         "models": {"deepseek": "deepseek-ai/DeepSeek-V4.1-Flash (frozen 2026-11-10 run)",
                    "qwen": "cyankiwi/Qwen3.5-9B-AWQ-4bit rev e4d2d39 (vLLM, temperature 0, thinking off)"},
         "prompt_version": "unsigned-resolve-v1.0-2026-11-10", "regate": "v1.1 (unsigned_regate.py rules)",
         "model_comparison": a, "selection_bias": b,
         "status": "diagnostic; model judgements, not accuracy; PENDING lead approval"}
    (OUT / "SUMMARY.json").write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(s, indent=1, ensure_ascii=False)[:9000])


if __name__ == "__main__":
    main()
