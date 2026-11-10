"""Component I amendment probe — BioRED OrganismTaxon non-host subset recall.

Reproduces `diagnostics/results/ner_organism_transfer.json` from the shipped prediction files, and
reports both an exact-span match (any predicted type) and an exact-span+type match, so the reader can
see which convention the amended table uses.

The host lexicon is listed explicitly below; it is a closed list of the 13 host-generic surface forms
observed in the BioRED test gold, not a heuristic pattern.

Writes: diagnostics/results/ner_organism_probe.json
Run:    python3 paper/publication/component_quality_audit/diagnostics/cqa_ner_organism_probe.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
ROOT = next(p for p in AUDIT.parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))
import fairbench as fb  # noqa: E402

fb.RAW = ROOT / "data/benchmarks_ner/raw"
fb.PRED = ROOT / "outputs/results/benchmark/ner_fair_bench/preds"

HOST = {
    "patients", "patient", "inpatient", "mice", "mouse", "rats", "rat", "human", "humans",
    "women", "woman", "men", "man",
}
VIRAL = {
    "rsv", "hcv", "hbv", "hiv", "hepatitis c virus", "respiratory syncytial virus",
}
MODELS = [
    "hunflair2", "pubtator3", "scispacy_bionlp13cg", "gliner_v25_biomed",
    "gliner_v25_medium", "llm_qwen_fs", "llm_gemma_zs", "llm_deepseek_fs",
]


def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def main() -> int:
    docs = fb.load("biored")
    host = viral = other = 0
    nonhost_keys = set()
    all_gold = 0
    for p, text, gold in docs:
        for s, e, ty, _m in gold:
            if ty != "OrganismTaxon":
                continue
            all_gold += 1
            surf = text[s:e].lower()
            if surf in HOST:
                host += 1
            else:
                if surf in VIRAL:
                    viral += 1
                else:
                    other += 1
                nonhost_keys.add((p, s, e))

    out = {
        "probe": "BioRED test OrganismTaxon gold restricted to non-host-generic mentions",
        "host_lexicon": sorted(HOST),
        "viral_lexicon": sorted(VIRAL),
        "gold_all_organismtaxon": all_gold,
        "gold_host": host,
        "gold_viral": viral,
        "gold_other_nonhost": other,
        "gold_nonhost_mentions": len(nonhost_keys),
        "match_conventions": {
            "span_exact_any_type": "predicted span equals gold span, predicted label ignored",
            "span_exact_and_type": "predicted span equals gold span AND label == OrganismTaxon",
        },
        "results": {},
    }

    for name in MODELS:
        _meta, raw = fb.read_preds(fb.PRED / f"biored__{name}.jsonl")
        pred = dict(fb.project([(p, raw.get(p, [])) for p, _, _ in docs], name, "biored"))
        span_hit = type_hit = 0
        for p, s, e in nonhost_keys:
            got = pred.get(p, [])
            if any(ps == s and pe == e for ps, pe, _ty in got):
                span_hit += 1
                if any(ps == s and pe == e and ty == "OrganismTaxon" for ps, pe, ty in got):
                    type_hit += 1
        n = len(nonhost_keys)
        out["results"][name] = {
            "span_exact_any_type": {"tp": span_hit, "gold": n, "recall": round(span_hit / n, 4),
                                    "wilson95": wilson(span_hit, n)},
            "span_exact_and_type": {"tp": type_hit, "gold": n, "recall": round(type_hit / n, 4),
                                    "wilson95": wilson(type_hit, n)},
        }

    dest = AUDIT / "diagnostics/results/ner_organism_probe.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")

    print(f"gold OrganismTaxon {all_gold}: host {host} / viral {viral} / other {other} "
          f"-> non-host {len(nonhost_keys)}")
    print(f"{'model':22s} {'span-any':>10s} {'span+type':>10s}  wilson(span+type)")
    for name, r in out["results"].items():
        a, b = r["span_exact_any_type"], r["span_exact_and_type"]
        print(f"{name:22s} {a['tp']:3d}/{a['gold']:<3d}{a['recall']:6.3f} "
              f"{b['tp']:3d}/{b['gold']:<3d}{b['recall']:6.3f}  {b['wilson95']}")
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
