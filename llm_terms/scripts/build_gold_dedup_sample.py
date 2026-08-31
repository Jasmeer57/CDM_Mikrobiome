#!/usr/bin/env python3
"""
Builds a stratified sample of entity pairs for gold-standard dedup annotation.

Samples across the embedding-similarity score range (not just top matches) so
the resulting gold set has real signal for a threshold sweep - a sample of
only "obviously the same" pairs would make every threshold look perfect.

Usage:
    python scripts/build_gold_dedup_sample.py --corpus <unified_entity_corpus.json> --output <gold_sample.json> --n_per_type 15
"""
import argparse
import json
import random
from collections import defaultdict

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import process as rf_process, fuzz as rf_fuzz


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--n_per_type", type=int, default=15,
                   help="Pairs sampled per score band per entity type.")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    args = parse_args()
    random.seed(args.seed)

    with open(args.corpus, "r", encoding="utf-8") as f:
        entities = json.load(f)["entities"]

    by_type = defaultdict(list)
    for e in entities:
        by_type[e["entity_type"]].append(e)

    encoder = SentenceTransformer("all-MiniLM-L6-v2")

    # Score bands to stratify over - deliberately includes the decision boundary
    # (0.6-0.8) where threshold choice actually matters, not just the extremes.
    bands = [(0.9, 1.01), (0.75, 0.9), (0.6, 0.75), (0.4, 0.6)]

    sample = []
    for etype, ents in by_type.items():
        if len(ents) < 5:
            continue
        names = [e["entity"] for e in ents]
        embeddings = encoder.encode(names, show_progress_bar=False)
        sim_matrix = cosine_similarity(embeddings)
        fuzzy_matrix = rf_process.cdist(names, names, scorer=rf_fuzz.ratio) / 100.0

        n = len(names)
        pairs_by_band = defaultdict(list)
        for i in range(n):
            for j in range(i + 1, n):
                emb = float(sim_matrix[i][j])
                for lo, hi in bands:
                    if lo <= emb < hi:
                        pairs_by_band[(lo, hi)].append((i, j, emb, float(fuzzy_matrix[i][j])))
                        break

        for band, pairs in pairs_by_band.items():
            k = min(args.n_per_type, len(pairs))
            picked = random.sample(pairs, k)
            for i, j, emb, fuzzy in picked:
                sample.append({
                    "entity_type": etype,
                    "term_a": ents[i]["entity"],
                    "term_b": ents[j]["entity"],
                    "embedding_score": round(emb, 3),
                    "fuzzy_score": round(fuzzy, 3),
                    "band": f"{band[0]}-{band[1]}",
                    "gold_label": None,  # to be filled in by annotation
                })

    random.shuffle(sample)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(sample)} candidate pairs to {args.output}")
    from collections import Counter
    print("By type:", dict(Counter(s["entity_type"] for s in sample)))
    print("By band:", dict(Counter(s["band"] for s in sample)))


if __name__ == "__main__":
    main()
