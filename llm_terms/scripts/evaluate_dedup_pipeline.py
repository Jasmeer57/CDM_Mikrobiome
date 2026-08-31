#!/usr/bin/env python3
"""
Evaluates the FULL dedup pipeline decision (embedding/fuzzy gate -> LLM
contextual judgment -> organism taxonomic guard) against the hand-labeled
gold sample, reporting pairwise precision/recall/F1 - the actual §2.10
metric, as opposed to threshold_sweep.py's raw-signal-only sweep.

Usage:
    python scripts/evaluate_dedup_pipeline.py --gold <gold_sample_final.json> --output <eval_results.json>
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--gold", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--embedding_prefilter", type=float, default=0.70)
    p.add_argument("--fuzzy_prefilter", type=float, default=0.85)
    p.add_argument("--biomistral_threshold", type=float, default=0.75)
    return p.parse_args()


def main():
    args = parse_args()
    from core.llm_client import LLMClient
    from core.biomedical_deduplicator import BioMistralDeduplicator

    SAFE_TAXONOMY_QUALIFIERS = {"sp", "spp", "ssp", "genus", "species", "strain",
                                 "isolate", "group", "complex", "sample", "samples"}

    def organism_core_tokens(name):
        tokens = re.findall(r"[a-zA-Z0-9]+", name.lower())
        core = []
        for t in tokens:
            if t in SAFE_TAXONOMY_QUALIFIERS:
                continue
            if len(t) == 1 and t.isalpha():
                continue
            core.append(t)
        return core

    from rapidfuzz import fuzz as rf_fuzz

    def _tokens_match(core1, core2, thr=85):
        remaining = list(core2)
        for t1 in core1:
            best = None
            for t2 in remaining:
                r = rf_fuzz.ratio(t1, t2)
                if r >= thr and (best is None or r > best[1]):
                    best = (t2, r)
            if best is None:
                return False
            remaining.remove(best[0])
        return True

    def organism_merge_is_safe(name1, name2, thr=85):
        core1, core2 = organism_core_tokens(name1), organism_core_tokens(name2)
        if len(core1) == len(core2):
            return _tokens_match(core1, core2, thr)
        if abs(len(core1) - len(core2)) != 1:
            return False
        shorter, longer = (core1, core2) if len(core1) < len(core2) else (core2, core1)
        if len(shorter) != 1 or len(longer) < 2:
            return False
        return rf_fuzz.ratio(shorter[0], longer[-1]) >= thr

    with open(args.gold, "r", encoding="utf-8") as f:
        gold = json.load(f)

    client = LLMClient(model="qwen3.5:9b")
    dedup = BioMistralDeduplicator.__new__(BioMistralDeduplicator)
    dedup.llm_client = client
    dedup.biomistral_model = "qwen3.5:9b"

    predictions = []
    for i, row in enumerate(gold, 1):
        a, b, etype = row["term_a"], row["term_b"], row["entity_type"]
        emb, fuzzy = row["embedding_score"], row["fuzzy_score"]

        if emb < args.embedding_prefilter and fuzzy < args.fuzzy_prefilter:
            pred = 0
            reason = "gate_reject"
        else:
            bio_score = dedup._get_bio_contextual_similarity(a, b, etype)
            if bio_score < args.biomistral_threshold:
                pred = 0
                reason = f"llm_reject(score={bio_score:.2f})"
            elif etype == "ORGANISM" and not organism_merge_is_safe(a, b):
                pred = 0
                reason = f"guard_blocked(llm_score={bio_score:.2f})"
            else:
                pred = 1
                reason = f"merged(llm_score={bio_score:.2f})"

        predictions.append(pred)
        status = "OK  " if pred == row["gold_label"] else "WRONG"
        print(f"[{i}/{len(gold)}] {status} gold={row['gold_label']} pred={pred} ({reason})  "
              f"{a!r} vs {b!r}")

    gold_labels = [row["gold_label"] for row in gold]
    tp = sum(1 for g, p in zip(gold_labels, predictions) if g == 1 and p == 1)
    fp = sum(1 for g, p in zip(gold_labels, predictions) if g == 0 and p == 1)
    fn = sum(1 for g, p in zip(gold_labels, predictions) if g == 1 and p == 0)
    tn = sum(1 for g, p in zip(gold_labels, predictions) if g == 0 and p == 0)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(gold_labels)

    print(f"\n=== FULL PIPELINE (gate + LLM + guard) vs gold ({len(gold)} pairs) ===")
    print(f"TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"Precision={precision:.3f} Recall={recall:.3f} F1={f1:.3f} Accuracy={accuracy:.3f}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision,
                    "recall": recall, "f1": f1, "accuracy": accuracy,
                    "predictions": predictions, "gold_labels": gold_labels}, f, indent=2)


if __name__ == "__main__":
    main()
