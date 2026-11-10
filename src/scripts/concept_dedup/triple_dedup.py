#!/usr/bin/env python3
"""Deduplicate triples: the same (subject, relation, object, polarity) is kept once, with all evidence.

Endpoints are resolved to CANONICAL terms (term dedup of 2026-11-09/10: exact, fuzzy, genus abbreviation,
embedding), so "B. fragilis -INCREASED_IN-> IBD" and "Bacteroides fragilis -INCREASED_IN-> IBD" merge.
Relation = the repaired relation (triple_repair_2026-11-09); REVERSED triples are flipped to their real
direction; endpoint fixes from the repair are used; symmetric relations ignore endpoint order.
Polarity (CDM polarity_variants) is part of the key, so a negated claim never merges with a positive one.

Inputs (read-only): CDM 3.0.3 relation table, triple_repair_2026-11-09/{repaired.jsonl,tiers.csv},
clean_vocabulary_2026-11-10/{term_id_map.csv,terms_all.jsonl}
Output: outputs/results/triple_dedup_2026-11-10/
  triples_dedup_all.{csv,jsonl}    one row per distinct triple, with merged ids, evidence, best tier, flags
  triples_dedup_clean.{csv,jsonl}  both endpoints kept by the relevance screen, no self-loops
  triple_id_map.{csv,json}         every original canonical_triple_id -> dedup_triple_id
  summary.json
Frozen CDM unchanged; new labelled layer pending lead approval (CHANGE_RECORD).
"""
import collections
import csv
import json
import sqlite3
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).parent))
from dedup_three_pass import exact_key  # noqa: E402

R = ROOT / "outputs/results"
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = R / "triple_dedup_2026-11-10"
SYMMETRIC = {"COMPARED_WITH", "SAME_AS", "COMPETES_WITH", "COOPERATES_WITH", "BINDS_TO", "SHARES_SOURCE_WITH"}


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rel = {r[0]: r for r in db.execute("""select canonical_triple_id, subject_term_id, object_term_id,
              subject_display_label, object_display_label, polarity_variants, mention_count, paper_count
              from relation""")}
    rep = {r["canonical_triple_id"]: r for r in jl(R / "triple_repair_2026-11-09/repaired.jsonl")}
    tiers = {r["canonical_triple_id"]: r for r in csv.DictReader(open(R / "triple_repair_2026-11-09/tiers.csv", encoding="utf-8"))}

    tmap = {r["term_id"]: r["canonical_term_id"] for r in csv.DictReader(open(R / "clean_vocabulary_2026-11-10/term_id_map.csv", encoding="utf-8"))}
    terms = {t["term_id"]: t for t in jl(R / "clean_vocabulary_2026-11-10/terms_all.jsonl")}
    key2canon = collections.defaultdict(set)  # normalised string -> canonical term ids
    for t in terms.values():
        key2canon[exact_key(t["term"], False)].add(t["term_id"])
        for v in t["variants"]:
            key2canon[exact_key(v, False)].add(t["term_id"])

    def endpoint(term_id, text, fix):
        """-> (endpoint key, canonical term id or '', label)"""
        if not fix and term_id and term_id in tmap:
            c = tmap[term_id]
            return c, c, terms[c]["term"]
        s = fix or text or ""
        k = exact_key(s, False)
        c = key2canon.get(k, set())
        if len(c) == 1:
            c = next(iter(c))
            return c, c, terms[c]["term"]
        return "str:" + k, "", s

    groups = collections.OrderedDict()
    pol_index = {}
    resolved = collections.Counter()
    for tid in sorted(rel):
        sid, oid, sdisp, odisp, pol, mc, pc = rel[tid][1:]
        r = rep.get(tid, {})
        relation = r.get("relation") or "UNKNOWN"
        sk, sc, sl = endpoint(sid, sdisp, r.get("subject_fix", ""))
        ok, oc, ol = endpoint(oid, odisp, r.get("object_fix", ""))
        resolved["subject_" + ("term" if sc else "string")] += 1
        resolved["object_" + ("term" if oc else "string")] += 1
        if r.get("direction") == "REVERSED":
            (sk, sc, sl), (ok, oc, ol) = (ok, oc, ol), (sk, sc, sl)
        if relation in SYMMETRIC and ok < sk:
            (sk, sc, sl), (ok, oc, ol) = (ok, oc, ol), (sk, sc, sl)
        definite = sorted(set(json.loads(pol or "[]")) - {"UNKNOWN"})
        polarity = "|".join(definite) or "UNKNOWN"
        # UNKNOWN never conflicts: such a triple joins the group of the same claim; POSITIVE vs NEGATIVE stay apart
        key = (sk, relation, ok, polarity)
        if polarity == "UNKNOWN":
            known = [k2 for k2 in pol_index.get((sk, relation, ok), []) if k2[3] != "UNKNOWN"]
            if len(known) == 1:
                key = known[0]
        pol_index.setdefault((sk, relation, ok), [])
        if key not in pol_index[(sk, relation, ok)]:
            pol_index[(sk, relation, ok)].append(key)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"subject": sl, "subject_term_id": sc, "relation": relation, "object": ol,
                               "object_term_id": oc, "polarity": polarity, "members": [], "old_relations": set(),
                               "evidence_mention_ids": set(), "paper_ids": set(), "tiers": []}
        g["members"].append(tid)
        g["old_relations"].add(r.get("old_relation", ""))
        g["evidence_mention_ids"].update(r.get("evidence_mention_ids") or [])
        g["paper_ids"].update(r.get("paper_ids") or [])
        if tid in tiers:
            g["tiers"].append(int(tiers[tid]["tier"]))

    for k in [k for k in groups if k[3] == "UNKNOWN"]:
        known = [k2 for k2 in pol_index.get(k[:3], []) if k2[3] != "UNKNOWN" and k2 in groups]
        if len(known) == 1:
            g, h = groups.pop(k), groups[known[0]]
            h["members"] += g["members"]; h["old_relations"] |= g["old_relations"]
            h["evidence_mention_ids"] |= g["evidence_mention_ids"]; h["paper_ids"] |= g["paper_ids"]; h["tiers"] += g["tiers"]

    rows, idmap = [], []
    for g in groups.values():
        did = "DEDUP-" + sorted(g["members"])[0]
        sk = terms.get(g["subject_term_id"], {}).get("kept", True)
        okk = terms.get(g["object_term_id"], {}).get("kept", True)
        row = {"dedup_triple_id": did, "subject": g["subject"], "subject_term_id": g["subject_term_id"],
               "relation": g["relation"], "object": g["object"], "object_term_id": g["object_term_id"],
               "polarity": g["polarity"], "n_merged": len(g["members"]), "merged_triple_ids": sorted(g["members"]),
               "old_relations": sorted(x for x in g["old_relations"] if x),
               "mention_count": len(g["evidence_mention_ids"]), "paper_count": len(g["paper_ids"]),
               "paper_ids": sorted(g["paper_ids"]), "evidence_mention_ids": sorted(g["evidence_mention_ids"]),
               "best_tier": min(g["tiers"]) if g["tiers"] else "", "tiers": sorted(g["tiers"]),
               "subject_kept": sk, "object_kept": okk,
               "self_loop": bool(g["subject_term_id"]) and g["subject_term_id"] == g["object_term_id"]}
        rows.append(row)
        for m in g["members"]:
            idmap.append({"canonical_triple_id": m, "dedup_triple_id": did})

    cols = ["dedup_triple_id", "subject", "subject_term_id", "relation", "object", "object_term_id", "polarity",
            "n_merged", "merged_triple_ids", "old_relations", "mention_count", "paper_count", "paper_ids",
            "evidence_mention_ids", "best_tier", "tiers", "subject_kept", "object_kept", "self_loop"]

    def write(name, rs):
        with open(OUT / f"{name}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rs:
                w.writerow({k: "|".join(map(str, v)) if isinstance(v, list) else v for k, v in r.items()})
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    clean = [r for r in rows if r["subject_kept"] and r["object_kept"] and not r["self_loop"]]
    write("triples_dedup_all", rows)
    write("triples_dedup_clean", clean)
    with open(OUT / "triple_id_map.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["canonical_triple_id", "dedup_triple_id"])
        w.writeheader()
        w.writerows(idmap)
    (OUT / "triple_id_map.json").write_text(json.dumps({r["canonical_triple_id"]: r["dedup_triple_id"] for r in idmap}, indent=0))

    specific = lambda r: r["relation"] not in ("NO_SPECIFIC_RELATION_STATED", "NOT_SUPPORTED", "UNKNOWN")
    summary = {
        "what": "triple deduplication on canonical endpoints + repaired relation + polarity; frozen CDM unchanged",
        "triples_in": len(rel), "distinct_triples": len(rows), "merged_away": len(rel) - len(rows),
        "groups_with_duplicates": sum(1 for r in rows if r["n_merged"] > 1),
        "largest_group": max(r["n_merged"] for r in rows),
        "endpoint_resolution": dict(resolved),
        "clean": {"triples": len(clean), "dropped_junk_endpoint": sum(1 for r in rows if not (r["subject_kept"] and r["object_kept"])),
                  "dropped_self_loop": sum(1 for r in rows if r["self_loop"])},
        "specific_relation": {"all": sum(map(specific, rows)), "clean": sum(map(specific, clean))},
        "clean_by_best_tier": dict(collections.Counter(r["best_tier"] for r in clean)),
        "symmetric_relations": sorted(SYMMETRIC),
        "note": "model-assisted layers (term dedup, relation repair, relevance screen); not accuracy; pending lead approval",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
