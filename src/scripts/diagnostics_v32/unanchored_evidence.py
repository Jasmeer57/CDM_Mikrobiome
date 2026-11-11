"""Unanchored evidence (diagnostics 2026-11-11, item 3): classify every catalogue evidence quote that is NOT counted as
verbatim in register K08 (anchor status FUZZY / UNANCHORED / NO_EVIDENCE; CDM 3.0.3) and every triple evidence
sentence with relation_evidence.anchor_status = UNANCHORED (CDM 3.1.0). Deterministic string matching only (no model);
reads the frozen releases read-only; writes outputs/results/diagnostics_2026-11-11/unanchored_evidence/.

    python src/scripts/diagnostics_v32/unanchored_evidence.py [--workers 8]

Classes (first that applies, in this order):
  NO_QUOTE            no quote stored (NO_EVIDENCE)
  NO_SECTION_TEXT     the section the record points to is missing
  SAME_SECTION_EXACT  exact / whitespace / alphanumeric match in its own section (status would now be verbatim)
  NORMALISATION       matches in its own section only after Unicode normalisation (NFKC + case-fold + accents
                      stripped + Greek letters spelled out + micro sign -> u), punctuation / whitespace ignored
  OTHER_SECTION       quote found verbatim (exact / whitespace / alphanumeric / Unicode-normalised) in ANOTHER section
                      of the same paper: section locator / offset error, the text exists in the paper
  VERBATIM_WITH_INSERTIONS  >= 95% of the quote's words occur IN ORDER, in runs of >= 3 words, inside a source span of
                      at most 2 x the quote length + 40 words: the quote is verbatim but the extracted section text is
                      interrupted (line numbers, page headers / footers, citation superscripts, headings, table cells)
  STITCHED            quote joined from several verbatim fragments that are NOT adjacent in the source (split at ellipses, or at sentence breaks when
                      each fragment of >= 4 words is found verbatim in the paper)
  NEAR_VERBATIM       best fuzzy window (rapidfuzz partial_ratio on normalised word strings) >= 90 in the paper
  PARAPHRASE          best fuzzy window 80 <= score < 90
  NOT_FOUND           best fuzzy window < 80 (possible hallucination or a quote assembled from tables / figures)
Thresholds are stated in SUMMARY.json; scores are also kept per row so other cut-offs can be applied.
Written with Claude Code (declare)."""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import difflib

from rapidfuzz import fuzz

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
OUT = ROOT / "outputs/results/diagnostics_2026-11-11/unanchored_evidence"
CAT_TABLES = ("claim", "cohort", "sample", "assay", "dataset", "data_asset")
NEAR, PARA = 90, 80
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "κ": "kappa", "λ": "lambda",
         "μ": "u", "µ": "u", "σ": "sigma", "τ": "tau", "ω": "omega", "χ": "chi", "ρ": "rho", "θ": "theta", "π": "pi"}
SEC: dict = {}
PAPER: dict = {}


def alnum(x):
    return "".join(ch.lower() for ch in x if ch.isalnum())


def uninorm(x):
    x = unicodedata.normalize("NFKC", x).casefold()
    x = "".join(GREEK.get(ch, ch) for ch in x)
    x = "".join(ch for ch in unicodedata.normalize("NFKD", x) if not unicodedata.combining(ch))
    return x


def ualnum(x):
    return "".join(ch for ch in uninorm(x) if ch.isalnum())


def words(x):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", uninorm(x)).split())


def verbatim_in(q, text):
    """exact / whitespace / alphanumeric (as the anchoring code) -> label, else None."""
    if q in text:
        return "exact"
    if " ".join(q.split()) in " ".join(text.split()):
        return "whitespace"
    a = alnum(q)
    if a and a in alnum(text):
        return "alnum"
    return None


def fragments(q):
    parts = re.split(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*", q)
    if len(parts) < 2:
        parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(])", q)
    return [p for p in parts if len(p.split()) >= 4]


def in_order_coverage(q, text):
    """Share of quote words matched in order (difflib blocks of >= 3 words) inside the best source span of at most
    2 x len(q) + 40 words."""
    qt, st = q.split(), text.split()
    if not qt or not st:
        return 0.0
    sm = difflib.SequenceMatcher(None, qt, st, autojunk=False)
    bl = sorted((b for b in sm.get_matching_blocks() if b.size >= 3), key=lambda b: b.b)
    best, lo, acc, lim = 0, 0, 0, 2 * len(qt) + 40
    for hi in range(len(bl)):
        acc += bl[hi].size
        while bl[hi].b + bl[hi].size - bl[lo].b > lim:
            acc -= bl[lo].size
            lo += 1
        best = max(best, acc)
    return min(1.0, best / len(qt))


def classify(item):
    q, pid, sid = item["quote"], item["paper_id"], item["section_key"]
    out = {"len_words": len((q or "").split())}
    if not q or not q.strip():
        return {**out, "class": "NO_QUOTE"}
    sec = SEC.get(sid)
    if sec is None:
        return {**out, "class": "NO_SECTION_TEXT"}
    v = verbatim_in(q, sec)
    if v:
        return {**out, "class": "SAME_SECTION_EXACT", "how": v}
    uq = ualnum(q)
    if uq and uq in ualnum(sec):
        return {**out, "class": "NORMALISATION"}
    others = [(k, t) for k, t in PAPER.get(pid, []) if k != sid]
    for k, t in others:
        v = verbatim_in(q, t) or ("unicode" if uq and uq in ualnum(t) else None)
        if v:
            return {**out, "class": "OTHER_SECTION", "how": v, "found_in": k}
    paper = " ".join(t for _, t in PAPER.get(pid, [])) or sec
    wq, ws, wp = words(q), words(sec), words(paper)
    cov_sec = in_order_coverage(wq, ws)
    if cov_sec >= 0.95:
        return {**out, "class": "VERBATIM_WITH_INSERTIONS", "in_order_coverage": round(cov_sec, 3), "where": "section"}
    cov_pap = max(cov_sec, in_order_coverage(wq, wp)) if others else cov_sec
    if cov_pap >= 0.95:
        return {**out, "class": "VERBATIM_WITH_INSERTIONS", "in_order_coverage": round(cov_pap, 3), "where": "paper"}
    fr = fragments(q)
    if len(fr) >= 2:
        ua = ualnum(paper)
        if all(ualnum(f) and ualnum(f) in ua for f in fr):
            return {**out, "class": "STITCHED", "n_fragments": len(fr)}
    s_sec = fuzz.partial_ratio(wq, ws) if wq and ws else 0.0
    s_pap = s_sec if len(others) == 0 else max(s_sec, fuzz.partial_ratio(wq, wp) if wq and wp else 0.0)
    qt = {w for w in wq.split() if len(w) >= 4}
    pt = set(wp.split())
    cov = round(len(qt & pt) / len(qt), 3) if qt else None
    cls = "NEAR_VERBATIM" if s_pap >= NEAR else "PARAPHRASE" if s_pap >= PARA else "NOT_FOUND"
    return {**out, "class": cls, "fuzzy_section": round(s_sec, 1), "fuzzy_paper": round(s_pap, 1), "content_word_coverage": cov,
            "in_order_coverage": round(cov_pap, 3)}


def init(sec, paper):
    global SEC, PAPER
    SEC, PAPER = sec, paper


def load_sections(db, key):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sec, paper = {}, defaultdict(list)
    for rid, pid, sid, txt, h in c.execute("SELECT section_record_id, paper_id, section_id_original, section_text_original, "
                                           "text_hash_sha256 FROM section ORDER BY paper_id, section_order"):
        k = (pid, sid) if key == "orig" else rid
        sec[k] = txt or ""
        paper[pid].append((k, txt or ""))
    return sec, dict(paper)


def wilson(k, n, z=1.959964):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def run(items, sec, paper, workers):
    with ProcessPoolExecutor(workers, initializer=init, initargs=(sec, paper)) as ex:
        res = list(ex.map(classify, items, chunksize=16))
    for it, r in zip(items, res):
        it.update(r)
    return items


def tab(items, key="class"):
    n = len(items)
    cnt = Counter(i[key] for i in items)
    return {k: {"n": v, "pct": round(100 * v / n, 1), "wilson95": wilson(v, n)} for k, v in cnt.most_common()}, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    # ---- catalogue (3.0.3)
    c = sqlite3.connect(f"file:{DB303}?mode=ro", uri=True)
    total, cat = Counter(), []
    sec_hash = {(p, s): h for p, s, h in c.execute("SELECT paper_id, section_id_original, text_hash_sha256 FROM section")}
    for t in CAT_TABLES:
        w = " WHERE claim_source='catalogue_v3_1'" if t == "claim" else ""
        idc = {"claim": "finding_id", "cohort": "cohort_id", "sample": "sample_id", "assay": "assay_id", "dataset": "dataset_id",
               "data_asset": "data_asset_id"}[t]
        cols = {r[1] for r in c.execute(f'PRAGMA table_info("{t}")')}
        idc = idc if idc in cols else "rowid"
        for rid, pid, sid, q, st, cs, ce, sh in c.execute(
                f'SELECT "{idc}", paper_id, section_id, evidence_text, evidence_anchor_status, char_start, char_end, '
                f'section_text_sha256 FROM "{t}"{w}'):
            total[st] += 1
            if st in ("FUZZY", "UNANCHORED", "NO_EVIDENCE"):
                cat.append({"layer": "catalogue", "table": t, "record_id": rid, "paper_id": pid, "section_key": (pid, sid),
                            "anchor_status": st, "quote": q, "char_start": cs, "char_end": ce,
                            "section_hash_differs": bool(sh and sec_hash.get((pid, sid)) and sh != sec_hash[(pid, sid)])})
    # ---- triples (3.1.0)
    c3 = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    tri_total = Counter(dict(c3.execute("SELECT anchor_status, COUNT(*) FROM relation_evidence GROUP BY 1").fetchall()))
    tri = [{"layer": "triple", "triple_mention_id": m, "canonical_triple_id": t, "paper_id": p, "section_key": s,
            "anchor_status": "UNANCHORED", "quote": q}
           for m, t, p, s, q in c3.execute("SELECT triple_mention_id, canonical_triple_id, paper_id, section_record_id, "
                                           "source_sentence FROM relation_evidence WHERE anchor_status='UNANCHORED' ORDER BY 1")]
    if a.limit:
        cat, tri = random.Random(1).sample(cat, a.limit), random.Random(1).sample(tri, a.limit)
    s1, p1 = load_sections(DB303, "orig")
    cat = run(cat, s1, p1, a.workers)
    s3, p3 = load_sections(DB310, "rid")
    tri = run(tri, s3, p3, a.workers)
    for it in cat + tri:
        it["section_key"] = list(it["section_key"]) if isinstance(it["section_key"], tuple) else it["section_key"]
    with open(OUT / "classified_rows.jsonl", "w", encoding="utf-8") as f:
        for it in cat + tri:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    N = sum(total.values())
    verb = sum(total[k] for k in ("EXACT", "WHITESPACE", "RELOCATED", "NORMALISED"))
    cat_tab, ncat = tab(cat)
    by_status = {st: tab([i for i in cat if i["anchor_status"] == st])[0] for st in ("FUZZY", "UNANCHORED", "NO_EVIDENCE")}
    by_table = {t: dict(Counter(i["class"] for i in cat if i["table"] == t)) for t in CAT_TABLES}
    tri_tab, ntri = tab(tri)
    fz = lambda L: [i.get("fuzzy_paper") for i in L if i.get("fuzzy_paper") is not None]
    nf = [i for i in cat + tri if i["class"] == "NOT_FOUND"]
    summ = {
        "date": "2026-11-11", "method": __doc__.split("\n\n")[1].strip(), "thresholds": {"near_verbatim": NEAR, "paraphrase": PARA,
                                                                                        "scorer": "rapidfuzz.fuzz.partial_ratio on normalised word strings"},
        "catalogue": {
            "source": "CDM 3.0.3: claim (catalogue_v3_1), cohort, sample, assay, dataset, data_asset",
            "records": N, "anchor_status": dict(total),
            "k08_verbatim": {"n": verb, "pct": round(100 * verb / N, 2), "wilson95": wilson(verb, N),
                             "of_which_at_stored_offsets_EXACT_WHITESPACE": {"n": total["EXACT"] + total["WHITESPACE"],
                                                                            "pct_of_all": round(100 * (total["EXACT"] + total["WHITESPACE"]) / N, 2)},
                             "RELOCATED_same_section_elsewhere": total["RELOCATED"], "NORMALISED_punctuation_case": total["NORMALISED"]},
            "non_verbatim": {"n": ncat, "pct": round(100 * ncat / N, 2), "classes": cat_tab, "by_anchor_status": by_status,
                             "by_table": by_table,
                             "section_hash_differs": sum(i["section_hash_differs"] for i in cat)},
        },
        "triples": {"source": "CDM 3.1.0 relation_evidence", "anchor_status": dict(tri_total),
                    "unanchored": {"n": ntri, "pct_of_evidence_rows": round(100 * ntri / sum(tri_total.values()), 2), "classes": tri_tab}},
        "not_found_content_word_coverage": {
            "n": len(nf), ">=0.8": sum((i.get("content_word_coverage") or 0) >= 0.8 for i in nf),
            "<0.5": sum((i.get("content_word_coverage") or 0) < 0.5 for i in nf)},
        "fuzzy_score_quantiles": {L: (lambda v: {q: sorted(v)[int(q * (len(v) - 1))] for q in (0.1, 0.25, 0.5, 0.75, 0.9)} if v else None)(fz(X))
                                  for L, X in (("catalogue", cat), ("triples", tri))},
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summ, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: summ[k] for k in ("catalogue", "triples", "not_found_content_word_coverage")}, indent=1, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
