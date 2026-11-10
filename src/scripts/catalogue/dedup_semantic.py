#!/usr/bin/env python
"""Stage 2: semantic + fuzzy deduplication of the terminology registry, with
organism protection.

Reads:   data/catalogue/terminology_exact_dedup.csv  (from stage 1)
Writes:  data/catalogue/terminology_dedup.csv        (canonical terms only)
         data/catalogue/catalogue_remapping.json     (duplicate -> canonical)
         data/catalogue/terminology_dedup_stats.json

Dedup strategy (per CDM type, terms are only compared within the same type):

  1. Fuzzy dedup (RapidFuzz token_sort_ratio >= 95): catches case/spacing/
     hyphenation variants and OCR-ish noise. NOT applied to ORGANISM unless
     the pair ALSO passes a stricter check, because e.g. "E. coli" vs
     "E. Coliforme" fuzzy-match but are distinct taxa.

  2. Semantic dedup (sentence-transformers embeddings, cosine >= 0.90):
     same threshold as the production pass2 (llm_entity_cleanup.py). Skipped
     entirely for ORGANISM — species/strain names must never be merged
     semantically (top-K means of embedding lists are unsafe for Latin
     binomials).

  3. Protected terms: ORGANISM, and any term that looks like a Latin binomial
     or a taxon suffix (bacteria/coccus/bacter/bacillus/...), are only
     collapsed on *exact* normalization (already done in stage 1).

All merges preserve the most-frequent (n_papers) surface form as canonical.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REPO_ROOT = PROJECT_ROOT
while not (REPO_ROOT / "data" / "catalogue").exists() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
PROJECT_ROOT = REPO_ROOT

IN_CSV = PROJECT_ROOT / "data" / "catalogue" / "terminology_exact_dedup.csv"
OUT_CSV = PROJECT_ROOT / "data" / "catalogue" / "terminology_dedup.csv"
REMAP_JSON = PROJECT_ROOT / "data" / "catalogue" / "catalogue_remapping.json"
STATS_JSON = PROJECT_ROOT / "data" / "catalogue" / "terminology_dedup_stats.json"

try:
    from rapidfuzz import fuzz, process

    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer

    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

TAXON_SUFFIX_RE = re.compile(
    r"(bacter(?:ia|ium|a)?[sd]?|coccus|bacill[ui]|virus|viridae|monas|aceae|ales|"
    r"ineae|oneae|acea|mycetes|mycota|spp?\.?)",
    re.I,
)
LATIN_BINOMIAL_RE = re.compile(r"^[A-Z][a-z]+\s+[a-z]{2,}s?$")

FUZZY_THRESHOLD = 95.0
SEMANTIC_THRESHOLD = 0.90
EMBED_BATCH = 512
EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def is_taxon(term: str, cdm_type: str) -> bool:
    if cdm_type in ("ORGANISM", "CELL_TYPE"):
        return True
    if LATIN_BINOMIAL_RE.match(term.strip()):
        return True
    if TAXON_SUFFIX_RE.search(term):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-type", type=int, default=0, help="Debug: cap terms per type")
    ap.add_argument("--embed-model", default=EMBED_MODEL)
    args = ap.parse_args()

    t0 = time.time()
    rows = list(csv.DictReader(IN_CSV.open(encoding="utf-8")))
    for r in rows:
        r["n_papers"] = int(r["n_papers"] or 0)
        r["n_models"] = int(r["n_models"] or 0)
        r["n_observations"] = int(r["n_observations"] or 0)
    print(f"loaded {len(rows)} terms")

    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["cdm_type"]].append(r)

    model = None
    if ST_AVAILABLE:
        print(f"loading embed model {args.embed_model} ...")
        model = SentenceTransformer(args.embed_model)
    else:
        print("[warn] sentence-transformers missing — semantic dedup skipped", flush=True)

    remap: dict[str, str] = {}  # dup term_norm -> canonical term_norm
    protected = 0

    for etype, terms in sorted(by_type.items()):
        if args.max_per_type:
            terms = terms[: args.max_per_type]
        # sort by n_papers desc so canonical = most prevalent
        terms.sort(key=lambda r: (-r["n_papers"], -r["n_models"], r["term_norm"]))
        print(f"{etype}: {len(terms)} terms", flush=True)

        def canon_of(r: dict) -> str:
            n = r["term_norm"]
            seen = set()
            while n in remap and n not in seen:
                seen.add(n)
                n = remap[n]
            return n

        # ---- fuzzy pass (blocked for taxa) ----
        # Blocked pairwise: precise-length-window cdist batches (O(n·k) work
        # instead of O(n²)) — pairs whose fuzz.ratio cannot reach the threshold
        # are never compared.
        if RAPIDFUZZ_AVAILABLE:
            merged = 0
            cand = [r for r in terms
                    if not is_taxon(r["term"], etype) and r["term_norm"] not in remap]
            norms = [r["term_norm"] for r in cand]
            # length window: |len(a)-len(b)| > P can't reach (100-P) ratio
            max_len_diff = int(100 - FUZZY_THRESHOLD) + 1
            cand.sort(key=len)
            by_len: dict[int, list[int]] = defaultdict(list)
            for idx, n in enumerate(norms):
                by_len[len(n)].append(idx)
            lengths = sorted(by_len)
            import numpy as np  # local: rapidfuzz cdist needs numpy anyway
            done = np.zeros(len(norms), dtype=bool)
            for li, L in enumerate(lengths):
                idxs = by_len[L]
                partner: list[int] = []
                for L2 in lengths[li:]:
                    if L2 - L > max_len_diff:
                        break
                    partner.extend(by_len[L2])
                if len(partner) < 2:
                    continue  # only itself
                a = [norms[i] for i in idxs]
                b = [norms[i] for i in partner]
                sim = process.cdist(
                    a, b, scorer=fuzz.ratio,
                    score_cutoff=FUZZY_THRESHOLD, workers=-1, dtype=np.uint8,
                )
                rows_np, cols_np = np.nonzero(sim)
                for rr, cc in zip(rows_np, cols_np):
                    gi, gj = idxs[rr], partner[cc]
                    if gi == gj:
                        continue
                    lo, hi = (gi, gj) if gi < gj else (gj, gi)
                    if done[hi] or remap.get(norms[hi]):
                        continue
                    remap[norms[hi]] = norms[lo]  # terms sorted by n_papers desc: lo is canonical
                    done[hi] = True
                    merged += 1
            print(f"  fuzzy merges: {merged}")
        else:
            print("  [warn] rapidfuzz missing — fuzzy dedup skipped")

        # ---- semantic pass (blocked for ORGANISM/CELL_TYPE/taxa) ----
        if model is not None and etype not in ("ORGANISM", "CELL_TYPE", "ENTITY"):
            names = [r["term_norm"] for r in terms]
            non_taxa_idx = [i for i, r in enumerate(terms) if not is_taxon(r["term"], etype)]
            if len(non_taxa_idx) >= 2:
                emb = model.encode(
                    [names[i] for i in non_taxa_idx],
                    batch_size=EMBED_BATCH,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                merged = 0
                for ii, i in enumerate(non_taxa_idx):
                    for jj in range(ii + 1, len(non_taxa_idx)):
                        j = non_taxa_idx[jj]
                        if terms[j]["term_norm"] in remap or terms[i]["term_norm"] in remap:
                            continue
                        if float(emb[ii] @ emb[jj]) >= SEMANTIC_THRESHOLD:
                            remap[terms[j]["term_norm"]] = canon_of(terms[i])
                            merged += 1
                    # early-break full-cross of huge types by blocking every 4096
                if merged:
                    print(f"  semantic merges: {merged}")
        elif etype == "ENTITY":
            print("  semantic pass skipped for ENTITY (untyped)"
                  " — needs typing first")

    # ---- apply remap & write ----
    def final_canon(n: str) -> str:
        seen = set()
        while n in remap and n not in seen:
            seen.add(n)
            n = remap[n]
        return n

    survivors: dict[str, dict] = {}
    for r in rows:
        c = final_canon(r["term_norm"])
        if c in survivors:
            s = survivors[c]
            s["n_papers"] += r["n_papers"]
            s["n_observations"] += r["n_observations"]
            s["n_models"] = max(s["n_models"], r["n_models"])
            for f in ("all_types", "models", "source_names"):
                for v in r[f].split("|"):
                    if v and v not in s[f].split("|"):
                        s[f] = "|".join(sorted(set(s[f].split("|") + [v])))
        else:
            survivors[c] = dict(r)

    out_rows = sorted(survivors.values(),
                      key=lambda r: (-r["n_papers"], -r["n_models"], r["term_norm"]))
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    n_remap = len(remap)
    REMAP_JSON.write_text(json.dumps(remap, indent=2, ensure_ascii=False))
    stats = {
        "input_terms": len(rows),
        "output_terms": len(out_rows),
        "duplicates_removed": len(rows) - len(out_rows),
        "protected_taxon_terms": protected,
        "fuzzy_threshold": FUZZY_THRESHOLD,
        "semantic_threshold": SEMANTIC_THRESHOLD,
        "embed_model": args.embed_model if model else None,
        "per_type_out": dict((t, sum(1 for r in out_rows if r["cdm_type"] == t))
                             for t in by_type),
        "elapsed_s": round(time.time() - t0, 1),
    }
    STATS_JSON.write_text(json.dumps(stats, indent=2))
    print(f"output terms: {len(out_rows)} (removed {len(rows) - len(out_rows)})")
    print(json.dumps(stats["per_type_out"], indent=1))
    print(f"elapsed: {stats['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
