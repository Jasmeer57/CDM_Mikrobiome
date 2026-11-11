"""Layer 3.2.0-candidate, Fix A step 1 (deterministic, no model): derive candidate relation labels FROM THE CORPUS ONLY.

    python src/scripts/fixes_v32/derive_vocab.py

Population: CDM triples whose final bucket (triples_final_summary.py logic) is NOT_SUPPORTED or
SPECIFIC_LABEL_CUE_NOT_FOUND (in_v32_scope in parse/corpus_parse.jsonl). For each triple one evidence sentence (the first
whose subject-object pair passes the frozen syntactic filter, else the first where both are located) gives the
CONNECTING PHRASE between subject and object:
  - surface route (subject and object at most 12 tokens apart): ReVerb-style relation phrase from the tokens between the
    two mentions: from the first predicate token (verb, or "be" + adjective / noun) to the last preposition / particle,
    lemmatised; determiners, numbers, pronouns and hedging / degree adverbs dropped, "not" kept;
  - path route (otherwise): verb / adjective lemmas on the dependency path plus the prepositions attached to the path.
Clustering: phrases are grouped by (head predicate lemma, final preposition) -- the head predicate is the last verb of the
phrase, or the adjective / noun after "be"; clusters are listed with triple counts, their phrase variants and two example
sentences. No benchmark data (DiMB-RE, MiDRED, MINERVA) is read. Labels are chosen by hand from this file and frozen in
labels_v32.json (sha256 in PREREGISTRATION.md) before any model run.
Output: outputs/results/fixes_v32_2026-11-11/vocab_derivation/{DERIVATION.json, DERIVATION.md}. Written with Claude Code (declare).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
D = ROOT / "outputs/results/fixes_v32_2026-11-11"
DROP_ADV = {"significantly", "also", "further", "only", "both", "strongly", "highly", "slightly", "statistically", "mainly",
            "mostly", "largely", "primarily", "often", "usually", "generally", "frequently", "potentially", "possibly",
            "likely", "directly", "indirectly", "partially", "partly", "markedly", "substantially", "consistently",
            "previously", "particularly", "especially", "even", "still", "commonly", "widely", "well", "however", "thus",
            "therefore", "then", "here", "now", "first", "finally", "moreover", "notably", "interestingly", "respectively"}
PRED_POS = {"VERB", "ADJ", "NOUN", "AUX"}


def surface_phrase(between):
    toks = [(l, p, t) for l, p, t in between if p not in ("DET", "NUM", "PRON", "SYM", "X", "PUNCT", "CCONJ", "SCONJ")
            and l not in DROP_ADV]
    start = None
    for i, (l, p, _) in enumerate(toks):
        if p == "VERB" or (p == "AUX" and i + 1 < len(toks) and toks[i + 1][1] in ("ADJ", "NOUN", "VERB")):
            start = i
            break
    if start is None:
        for i, (l, p, _) in enumerate(toks):
            if p in ("ADJ", "NOUN"):
                start = i
                break
    if start is None:
        return None
    end = None
    for i in range(len(toks) - 1, start - 1, -1):
        if toks[i][1] in ("ADP", "PART") and toks[i][0] != "not":
            end = i
            break
    seg = toks[start:(end + 1 if end is not None else len(toks))]
    if len(seg) > 7:
        return None
    return seg


def head_of(seg):
    """(head predicate lemma, final preposition) of a relation phrase."""
    prep = seg[-1][0] if seg and seg[-1][1] in ("ADP", "PART") else ""
    verbs = [l for l, p, _ in seg if p == "VERB" and l not in ("be", "have")]
    if verbs:
        return verbs[-1], prep
    content = [l for l, p, _ in seg if p in ("ADJ", "NOUN")]
    if content:
        return content[-1], prep
    return (seg[0][0] if seg else ""), prep


def path_phrase(ph):
    toks = [t for t in ph["path"] if t["pos"] in PRED_POS and t["lemma"] not in DROP_ADV]
    verbs = [t for t in toks if t["pos"] == "VERB" and t["lemma"] not in ("be", "have")]
    main = verbs[-1] if verbs else (toks[0] if toks else None)
    if main is None:
        return None
    prep = ph["preps"][-1] if ph["preps"] else ""
    return main["lemma"], prep, ("not " if main["neg"] else "") + main["lemma"] + (" (passive)" if main["passive"] else "")


def main():
    rows = [json.loads(l) for l in open(D / "parse/corpus_parse.jsonl", encoding="utf-8")]
    scope = [r for r in rows if r["in_v32_scope"]]
    by_bucket = Counter(r["bucket_v31"] for r in scope)
    clusters = defaultdict(lambda: {"n": 0, "phrases": Counter(), "routes": Counter(), "examples": [], "buckets": Counter()})
    route = Counter()
    for r in scope:
        evs = [e for e in r["evidence"] if e.get("phrase")]
        evs.sort(key=lambda e: (not e["connected"],))
        if not evs:
            route["no_located_pair"] += 1
            continue
        e = evs[0]
        ph = e["phrase"]
        key = text = None
        if ph["between"] is not None and ph["subject_first"]:
            seg = surface_phrase(ph["between"])
            if seg:
                h, p = head_of(seg)
                key, text, rt = (h, p), " ".join(l for l, _, _ in seg), "surface_subject_first"
        if key is None and ph["between"] is not None and not ph["subject_first"]:
            seg = surface_phrase(ph["between"])
            if seg:
                h, p = head_of(seg)
                key, text, rt = (h, p), " ".join(l for l, _, _ in seg), "surface_object_first"
        if key is None:
            pp = path_phrase(ph)
            if pp:
                key, text, rt = (pp[0], pp[1]), pp[2] + (" ... " + pp[1] if pp[1] else ""), "dependency_path"
        if key is None:
            route["no_phrase"] += 1
            continue
        route[rt] += 1
        c = clusters[f"{key[0]}|{key[1]}"]
        c["n"] += 1
        c["phrases"][text] += 1
        c["routes"][rt] += 1
        c["buckets"][r["bucket_v31"]] += 1
        if len(c["examples"]) < 2:
            c["examples"].append({"triple": r["canonical_triple_id"], "subject": r["subject"], "object": r["object"],
                                  "sentence": e["sentence"][:300], "connected": e["connected"]})
    lemma_tot = Counter()
    for k, c in clusters.items():
        lemma_tot[k.split("|")[0]] += c["n"]
    ranked = sorted(clusters.items(), key=lambda kv: -kv[1]["n"])
    out = {"population": len(scope), "by_bucket": dict(by_bucket), "routes": dict(route), "n_clusters": len(clusters),
           "head_lemma_totals": dict(lemma_tot.most_common(400)),
           "clusters": [{"key": k, "n": c["n"], "buckets": dict(c["buckets"]), "routes": dict(c["routes"]),
                         "phrases": dict(c["phrases"].most_common(8)), "examples": c["examples"]} for k, c in ranked]}
    o = D / "vocab_derivation"
    o.mkdir(parents=True, exist_ok=True)
    (o / "DERIVATION.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [f"# Corpus-derived connecting phrases ({len(scope):,} triples: {dict(by_bucket)})", "",
          f"Routes: {dict(route)}; {len(clusters):,} clusters (head predicate lemma | final preposition).", "",
          "| rank | cluster | n | top phrases | example |", "|---|---|---|---|---|"]
    for i, (k, c) in enumerate(ranked[:300], 1):
        ex = c["examples"][0]
        md.append(f"| {i} | `{k}` | {c['n']} | {'; '.join(f'{p} ({n})' for p, n in c['phrases'].most_common(4))} | "
                  f"{ex['subject'][:40]} / {ex['object'][:40]}: {ex['sentence'][:160].replace('|', '/')} |")
    md += ["", "## Head-lemma totals (all prepositions)", ""] + [f"- {k}: {v}" for k, v in lemma_tot.most_common(150)]
    (o / "DERIVATION.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("population", "by_bucket", "routes", "n_clusters")}, indent=1))


if __name__ == "__main__":
    main()
