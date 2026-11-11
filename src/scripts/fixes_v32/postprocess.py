"""Verify, normalise and deduplicate block findings -> catalogue tier 3.2.0-candidate.

  * evidence_text must occur in the block (exact, or whitespace-reflow tolerant via the catalogue's own
    locate_evidence); records whose quote is not found are dropped and counted.
  * source_type = the block span (TABLE / TABLE_CAPTION / FIGURE_CAPTION) holding the quote; section offsets kept.
  * normalisation re-uses src/scripts/vllm_termpop/normalize_catalogue_vocab.py (same vocab.yaml rules, same NCBI
    exact-name lookup and rank rule). The NCBI cache is COPIED into the output folder; the shipped cache is not touched.
  * dedup against catalogue_v3_1 in CDM 3.0.3 (read-only): same paper + shared NCBI taxon (or same normalised
    taxon string when unlinked) + same direction + compatible comparison -> DUPLICATE; same paper/taxon/direction but
    a different comparison -> NEW_COMPARISON; else NEW. Within-tier repeats are collapsed first.

    python src/scripts/fixes_v32/postprocess.py --raw DIR [--offline]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "src/scripts/vllm_termpop")]
import catalogue_ner as CN  # noqa: E402
import normalize_catalogue_vocab as NV  # noqa: E402

OUT = ROOT / "outputs/results/catalogue_tables_captions_v32_2026-11-11"
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
TIER = "3.2.0-candidate"
CLAIM_SOURCE = "catalogue_v3_2_blocks_candidate"
STOP = set("the a an of in and or with vs versus between to for from at on by group groups patients subjects "
           "individuals participants compared control controls healthy".split())


def toks(s):
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP and len(t) > 1}


def comparable(a, b):
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return True  # an unstated comparison cannot contradict one that is stated
    return len(ta & tb) / len(ta | tb) >= 0.5 or ta <= tb or tb <= ta


def norm_taxon(s):
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(OUT / "extract"))
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--spot", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20261111)
    a = ap.parse_args()
    units = {u["unit_id"]: u for u in map(json.loads, open(OUT / "units.jsonl", encoding="utf-8"))}
    raws = [json.loads(l) for p in sorted(Path(a.raw).glob("raw_*.jsonl")) for l in open(p, encoding="utf-8")]
    raws = list({r["unit_id"]: r for r in raws}.values())
    stats = Counter()
    stats["units_total"] = len(units)
    stats["units_answered"] = len(raws)
    stats["units_failed"] = sum(r["status"] != "OK" for r in raws)

    vocab = NV.Vocab(NV.VOCAB_DIR / "vocab.yaml")
    cache = OUT / "ncbi_taxon_cache_v32.json"
    if not cache.exists():
        shutil.copy(NV.VOCAB_DIR / "ncbi_taxon_cache.json", cache)
    ncbi = NV.NCBITaxonomy(cache, offline=a.offline, renamed=vocab.raw.get("renamed_taxa", {}))

    recs = []
    for r in raws:
        u = units[r["unit_id"]]
        # unit text -> section offsets
        pieces, pos = [], 0
        for k, (s, e, typ) in enumerate(u["spans"]):
            pieces.append((pos, pos + (e - s), s, typ))
            pos += (e - s) + (1 if k < len(u["spans"]) - 1 else 0)
        for f in r["records"]:
            stats["records_raw"] += 1
            q = (f.get("evidence_text") or "").strip()
            p, exact, ln = CN.locate_evidence(u["text"], q)
            if p is None:
                stats["dropped_evidence_not_in_block"] += 1
                continue
            piece = next((x for x in pieces if x[0] <= p < x[1]), pieces[-1])
            cs = piece[2] + (p - piece[0])
            tax = f.get("taxon_or_feature", "")
            rec = {"tier": TIER, "claim_source": CLAIM_SOURCE, "paper_id": u["paper_id"], "section_id": u["section_id"],
                   "block_id": u["block_id"], "unit_id": u["unit_id"], "source_type": piece[3],
                   "block_label": u["label"], "supplementary_block": u["supplementary"],
                   "char_start": cs, "char_end": cs + ln,
                   "evidence_match": "EXACT" if exact else "WHITESPACE_NORMALISED",
                   "taxon_in_block": bool(tax) and norm_taxon(tax) in norm_taxon(u["text"]),
                   **{k: f.get(k, "") for k in CN.ENTITY_SPECS["findings"][3]},
                   "extraction_model": r["model"], "extractor_prompt_version": r["prompt_version"]}
            if not rec["direction"]:
                rec["direction"] = "NOT_STATED"
            label, oid, status = vocab.body_site(rec.get("body_site"))
            rec.update(body_site_normalized=label, body_site_ontology_id=oid, body_site_status=status)
            rec["finding_domain_normalized"] = vocab.simple("finding_domain", rec.get("finding_domain"))
            rec["taxonomic_rank_normalized"] = vocab.simple("taxonomic_rank", rec.get("taxonomic_rank"))
            if rec["taxonomic_rank_normalized"] in NV.TAXON_RANKS:
                ids, names, st = NV.link_taxa(rec, ncbi)
            else:
                ids, names, st = "", "", "NOT_A_TAXON_RANK"
            rec.update(taxon_ncbi_ids=ids, taxon_ncbi_names=names, taxon_link_status=st)
            recs.append(rec)
    ncbi.save()
    stats["records_evidence_verified"] = len(recs)

    # within-tier collapse
    seen, tier = {}, []
    for rec in recs:
        k = (rec["paper_id"], rec["taxon_ncbi_ids"] or norm_taxon(rec["taxon_or_feature"]), rec["direction"],
             " ".join(sorted(toks(rec["comparison_or_exposure"]))), norm_taxon(rec["outcome"]))
        if k in seen:
            seen[k]["merged_repeats"] += 1
            continue
        rec["merged_repeats"] = 0
        seen[k] = rec
        tier.append(rec)
    stats["records_after_within_tier_collapse"] = len(tier)

    # dedup against catalogue_v3_1
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    old = defaultdict(list)
    for fid, pid, ids, tax, d, comp in c.execute(
            "SELECT finding_id, paper_id, taxon_ncbi_ids, taxon_or_feature, direction, comparison_or_exposure "
            "FROM claim WHERE claim_source = 'catalogue_v3_1'"):
        old[pid].append((fid, set(re.findall(r"NCBITaxon:\d+", ids or "")), norm_taxon(tax), d or "", comp or ""))
    for i, rec in enumerate(tier, 1):
        rec["finding_id"] = f"HMFINDING_V32B_{i:06d}"
        mine = set(re.findall(r"NCBITaxon:\d+", rec["taxon_ncbi_ids"]))
        nt = norm_taxon(rec["taxon_or_feature"])
        same_tax = [o for o in old[rec["paper_id"]] if (mine & o[1]) or (not mine and nt and nt == o[2])]
        same_dir = [o for o in same_tax if o[3] == rec["direction"]]
        dup = [o for o in same_dir if comparable(rec["comparison_or_exposure"], o[4])]
        rec["dedup_status"] = "DUPLICATE" if dup else "NEW_COMPARISON" if same_dir else "NEW"
        rec["duplicate_of"] = "; ".join(o[0] for o in (dup or same_dir)[:5])
        rec["taxon_already_in_paper_catalogue"] = bool(same_tax)

    with open(OUT / "findings_v32_candidate.jsonl", "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in tier))

    def tab(rows, key):
        return dict(Counter(r[key] for r in rows))
    linked = [r for r in tier if r["taxon_ncbi_ids"]]
    summ = {"tier": TIER, "claim_source": CLAIM_SOURCE, "stats": dict(stats),
            "findings": len(tier), "by_source_type": tab(tier, "source_type"),
            "dedup_status": tab(tier, "dedup_status"),
            "dedup_by_source_type": {s: tab([r for r in tier if r["source_type"] == s], "dedup_status")
                                     for s in sorted({r["source_type"] for r in tier})},
            "evidence_match": tab(tier, "evidence_match"), "direction": tab(tier, "direction"),
            "taxon_link_status": tab(tier, "taxon_link_status"),
            "with_ncbi_taxon": len(linked),
            "with_ncbi_taxon_by_dedup": tab(linked, "dedup_status"),
            "with_ncbi_taxon_new_paper_taxon_pair": sum(not r["taxon_already_in_paper_catalogue"] for r in linked),
            "taxon_string_in_block": sum(r["taxon_in_block"] for r in tier),
            "papers_with_findings": len({r["paper_id"] for r in tier}),
            "ncbi_new_lookups": ncbi.new}
    (OUT / "SUMMARY_postprocess.json").write_text(json.dumps(summ, indent=2) + "\n")
    print(json.dumps(summ, indent=2))

    # hand spot-check sheet: 50 random NEW / NEW_COMPARISON findings
    rng = random.Random(a.seed)
    pool = [r for r in tier if r["dedup_status"] != "DUPLICATE"]
    sample = rng.sample(pool, min(a.spot, len(pool)))
    with open(OUT / "spotcheck_new_findings.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["finding_id", "paper_id", "source_type", "dedup_status", "taxon_or_feature", "taxon_ncbi_names",
                    "direction", "comparison_or_exposure", "outcome", "evidence_text", "verdict", "note"])
        for r in sample:
            w.writerow([r["finding_id"], r["paper_id"], r["source_type"], r["dedup_status"], r["taxon_or_feature"],
                        r["taxon_ncbi_names"], r["direction"], r["comparison_or_exposure"], r["outcome"],
                        r["evidence_text"], "", ""])


if __name__ == "__main__":
    main()
