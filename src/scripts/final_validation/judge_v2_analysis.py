"""Agreement analysis of the rubric-v2 catalogue judges (deterministic; reads model outputs only).

    python src/scripts/final_validation/judge_v2_analysis.py --split dev|test

Per field, each judge's answer becomes a verdict PASS / FAIL / UNC:
  classification fields (blind answer vs stored value): MATCH -> PASS, MISMATCH -> FAIL, CANNOT_TELL -> UNC
     (stored REVIEW or missing codes -> not scored for verdicts; their blind answers still count for answer agreement);
  stated fields: SUPPORTED with a verified evidence span -> PASS; SUPPORTED whose span is not in the text or does not
     contain the value -> UNVERIFIED (reported; counted as UNC in the verified view, PASS in the raw view);
     NOT_SUPPORTED / CONTRADICTED / WRONG_FIELD -> FAIL; UNCERTAIN -> UNC.
Reports: pairwise Cohen kappa, PABAK, Gwet AC1 and per-label agreement; Fleiss kappa for the three judges; majority
verdicts; blind-answer agreement on classification fields; and, on the same records and fields, the 2026-11-09
constrained Llama x Mistral pair for comparison. Output: outputs/results/benchmark/judge_v2_2026-11-10/<split>/
ANALYSIS.json. Agreement between models, not accuracy. Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
import evidence_judge_v2 as E  # noqa: E402
from judge_agreement_extended import stats  # noqa: E402

V1DIR = ROOT / "outputs/results/benchmark/evidence_judge_constrained_2026-11-09"
L = ["PASS", "FAIL", "UNC"]
RANKMAP = [("strain", "strain"), ("subspecies", "strain"), ("species", "species"), ("sp.", "species"), ("genus", "genus"),
           ("genera", "genus"), ("generic", "genus"), ("family", "family"), ("families", "family"), ("order", "order"),
           ("class", "class"), ("phylum", "phylum"), ("phyla", "phylum"), ("kingdom", "kingdom_or_domain"),
           ("domain", "kingdom_or_domain"), ("otu", "OTU_or_ASV"), ("asv", "OTU_or_ASV"), ("operational taxonomic", "OTU_or_ASV"),
           ("amplicon sequence variant", "OTU_or_ASV"), ("zotu", "OTU_or_ASV"), ("esv", "OTU_or_ASV"),
           ("community", "community_or_diversity"), ("diversity", "community_or_diversity"), ("shannon", "community_or_diversity"),
           ("simpson", "community_or_diversity"), ("richness", "community_or_diversity"), ("enterotype", "community_or_diversity"),
           ("microbiota", "community_or_diversity"), ("microbiome", "community_or_diversity"), ("unifrac", "community_or_diversity"),
           ("metabolite", "metabolite_or_molecule"), ("molecule", "metabolite_or_molecule"), ("scfa", "metabolite_or_molecule"),
           ("acid", "metabolite_or_molecule"), ("compound", "metabolite_or_molecule"), ("chemical", "metabolite_or_molecule"),
           ("lipid", "metabolite_or_molecule"), ("gene", "gene_or_pathway"), ("pathway", "gene_or_pathway"),
           ("kegg", "gene_or_pathway"), ("enzyme", "gene_or_pathway"), ("function", "gene_or_pathway"),
           ("cytokine", "host_or_clinical_measure"), ("clinical", "host_or_clinical_measure"), ("cell", "host_or_clinical_measure")]


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def ranks(v):
    parts = [p.strip().lower() for p in re.split(r"[,;/]| and | or ", str(v)) if p.strip()]
    out = set()
    for p in parts:
        out.add(next((r for k, r in RANKMAP if k in p), "other"))
    return out


def classify_verdict(table, field, answer, stored):
    if answer == "CANNOT_TELL":
        return "UNC"
    if stored in (None, "", "REVIEW") or stored in E.V1.MISSING:
        return None
    if field == "taxonomic_rank":
        rs = ranks(stored)
        ok = (answer == "multiple_levels" and len(rs) > 1) or answer in rs
    else:
        ok = str(answer).upper() == str(stored).strip().upper()
    return "PASS" if ok else "FAIL"


def stems(text):
    return {t[:5] for t in norm(text).split() if len(t) > 2}


def covered(value, text, share):
    """True if the value's numbers all occur in text and >= share of its content words (5-letter stems) do."""
    nv, nt = norm(value), norm(text)
    if nv and nv in nt:
        return True
    nums = re.findall(r"\d+(?:\.\d+)?", nv)
    if nums and not all(n in nt.split() for n in nums):
        return False
    vs = stems(value)
    return bool(vs) and len(vs & stems(text)) / len(vs) >= share if vs else bool(nums)


def stated_verdict(item, value, source):
    """(raw, verified). SUPPORTED is verified when the quoted span is in the text and covers the value, or when the value
    itself is found in the text (models often quote the value instead of the text; the value is then still checkable)."""
    v, e = item.get("v"), item.get("e") or ""
    if v == "SUPPORTED":
        ne = norm(e)
        span_ok = len(ne) >= 3 and ne in source and covered(value, e, 0.5)
        value_in_text = covered(value, source, 0.8)
        return ("PASS", "PASS") if span_ok or value_in_text else ("PASS", "UNC")
    if v in ("NOT_SUPPORTED", "CONTRADICTED", "WRONG_FIELD"):
        return ("FAIL", "FAIL")
    if v == "UNCERTAIN":
        return ("UNC", "UNC")
    return (None, None)


def fleiss(rows):
    """rows: list of label lists (one per item, equal raters)."""
    if not rows:
        return None
    n = len(rows[0])
    cats = sorted({x for r in rows for x in r})
    P = [(sum(r.count(c) ** 2 for c in cats) - n) / (n * (n - 1)) for r in rows]
    p = {c: sum(r.count(c) for r in rows) / (len(rows) * n) for c in cats}
    pe = sum(v * v for v in p.values())
    pbar = sum(P) / len(P)
    return round((pbar - pe) / (1 - pe), 3) if pe < 1 else None


def pair_stats(pairs):
    t = {a: {b: 0 for b in L} for a in L}
    for a, b in pairs:
        t[a][b] += 1
    s = stats(t, L)
    return {k: s[k] for k in ("n", "observed", "kappa", "pabak", "gwet_ac1", "specific_agreement")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    a = ap.parse_args()
    d = E.OUT / a.split
    recs = {(r["table"], r["record_id"]): r for r in E.V1.records() if r["values"] and E.split_of(r["record_id"]) == a.split}
    judges = {}
    for m in E.MODELS:
        out = {}
        for f in glob.glob(str(d / f"{m}.shard*.jsonl")):
            for line in open(f, encoding="utf-8"):
                j = json.loads(line)
                if "error" not in j:
                    out[(j["table"], j["record_id"])] = j
        if out:
            judges[m] = out
    print({m: len(v) for m, v in judges.items()}, flush=True)
    raw, ver, answers, unverified, dist = (defaultdict(dict) for _ in range(5))
    kinds = {}
    for m, out in judges.items():
        cnt = Counter()
        for k, j in out.items():
            rec = recs.get(k)
            if not rec:
                continue
            src = norm(rec["passage"] + " " + " ".join(rec["field_quotes"].values()))
            stored_all = {**rec["values"], **rec.get("missing_codes", {})}
            for f, ans in (j.get("classify") or {}).items():
                fk = (k[0], k[1], f)
                kinds[fk] = "classify"
                answers[fk][m] = ans
                v = classify_verdict(k[0], f, ans, stored_all.get(f))
                if v:
                    raw[fk][m] = ver[fk][m] = v
                    cnt[v] += 1
            for f, lv in (j.get("label") or {}).items():
                fk = (k[0], k[1], f)
                kinds[fk] = "label"
                vv = {"FAIR": "PASS", "UNFAIR": "FAIL", "CANNOT_TELL": "UNC"}.get(lv)
                if vv:
                    raw[fk][m] = ver[fk][m] = vv
                    cnt["label_" + lv] += 1
            for f, it in (j.get("stated") or {}).items():
                fk = (k[0], k[1], f)
                kinds[fk] = "stated"
                r_, v_ = stated_verdict(it or {}, rec["values"].get(f, ""), src)
                if r_:
                    raw[fk][m], ver[fk][m] = r_, v_
                    cnt[it.get("v")] += 1
                    if r_ == "PASS" and v_ == "UNC":
                        unverified[m][fk] = 1
        dist[m] = dict(cnt)
    ms = sorted(judges)
    res = {"split": a.split, "prompt_sha256": E.PROMPT_SHA256, "judges": ms, "records_judged": {m: len(judges[m]) for m in ms},
           "verdict_counts": dict(dist),
           "supported_unverified": {m: len(unverified[m]) for m in ms}}
    for view, V in (("verified", ver), ("raw", raw)):
        block = {}
        for kind in ("all", "classify", "stated", "label"):
            keys = [k for k in V if (kind == "all" or kinds[k] == kind) and all(m in V[k] for m in ms)]
            block[kind] = {"fields": len(keys),
                           "pairwise": {f"{x}|{y}": pair_stats([(V[k][x], V[k][y]) for k in keys]) for x, y in combinations(ms, 2)},
                           "fleiss_kappa": fleiss([[V[k][m] for m in ms] for k in keys]) if len(ms) >= 3 else None,
                           "majority": dict(Counter(Counter(V[k][m] for m in ms).most_common(1)[0][0]
                                                    if Counter(V[k][m] for m in ms).most_common(1)[0][1] >= 2 else "NO_MAJORITY"
                                                    for k in keys))}
        res[view] = block
    mf, mt = Counter(), Counter()                                   # majority FAIL per stated field (verified view)
    for k in ver:
        if kinds[k] == "stated" and all(m in ver[k] for m in ms):
            mt[f"{k[0]}.{k[2]}"] += 1
            mf[f"{k[0]}.{k[2]}"] += sum(ver[k][m] == "FAIL" for m in ms) >= 2
    res["stated_majority_fail_by_field"] = {f: {"fail": mf[f], "n": mt[f], "pct": round(100 * mf[f] / mt[f], 1)}
                                            for f, _ in mf.most_common()}
    keys = [k for k in answers if all(m in answers[k] for m in ms)]
    res["classify_blind_answers"] = {"fields": len(keys), "fleiss_kappa": fleiss([[answers[k][m] for m in ms] for k in keys]),
                                     "all_judges_same_answer_pct": round(100 * sum(len({answers[k][m] for m in ms}) == 1 for k in keys) / max(1, len(keys)), 1)}
    byf = defaultdict(list)
    for k in keys:
        byf[f"{k[0]}.{k[2]}"].append(len({answers[k][m] for m in ms}) == 1)
    res["classify_all_same_by_field_pct"] = {f: round(100 * sum(v) / len(v), 1) for f, v in sorted(byf.items())}
    # v1 comparison on the same records and the same non-link fields
    v1 = {}
    for m in ("llama", "mistral"):
        for f in glob.glob(str(V1DIR / f"{m}.shard*.jsonl")):
            for line in open(f, encoding="utf-8"):
                j = json.loads(line)
                if (j.get("table"), j.get("record_id")) in recs:
                    for fld, v in (j.get("fields") or {}).items():
                        n = "PASS" if v == "PASS" else ("FAIL" if str(v).startswith("FAIL") else ("UNC" if v == "UNCERTAIN" else None))
                        if n and fld not in E.V1.LINKS:
                            v1.setdefault((j["table"], j["record_id"], fld), {})[m] = n
    pk = [k for k, v in v1.items() if len(v) == 2]
    res["v1_constrained_same_records"] = pair_stats([(v1[k]["llama"], v1[k]["mistral"]) for k in pk])
    out = d / "ANALYSIS.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1)[:6000])


if __name__ == "__main__":
    main()
