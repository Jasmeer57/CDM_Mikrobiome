"""WS-4: "remove one source" ablation of the terminology layer, from the existing CDM 3.0.3 mentions (no new runs).

Sources (term_mention.extraction_run_id): NER ensemble (cpu_ensemble_v1), small open LLM (Qwen3.5-4B, two runs:
qwen35_vllm_body_v1 + qwen_ollama_cell7c_v1), MeSH gazetteer (mesh_gazetteer_2026).
Unit: canonical terms linked to at least one mention, and mentions. Quality: model judgements only --
DeepSeek-V4-Flash (valid; valid and correctly typed) and, as a second judge, Qwen3.5-9B stage B (valid). Agreement
between judges is modest (judge_agreement_2026-11-05), so both are shown; neither is accuracy.

For the full system and for each variant with one source removed: terms, mentions, terms judged valid, and the terms
only that source contributes (unique contribution). Also the overlap of the three sources (UpSet-style counts).
Writes outputs/results/benchmark/source_ablation_2026-11-05/{summary.json,REPORT.md}.
"""
from __future__ import annotations

import csv
import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DS = ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/entity_verdicts.csv.gz"
QW = ROOT / "outputs/results/cdm_v3_3.1_deepseek_repair/stage_b_terms_qwen/validation/TERM_DECISIONS.csv"
OUT = ROOT / "outputs/results/benchmark/source_ablation_2026-11-05"
SRC = {"cpu_ensemble_v1": "NER", "qwen35_vllm_body_v1": "LLM", "qwen_ollama_cell7c_v1": "LLM", "mesh_gazetteer_2026": "GAZ"}
NAMES = {"NER": "NER ensemble", "LLM": "small open LLM (Qwen3.5-4B, 2 runs)", "GAZ": "MeSH gazetteer"}
csv.field_size_limit(1 << 30)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    terms = {t: (s, ty) for t, s, ty in c.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    src_terms, mentions = defaultdict(set), Counter()
    for tid, run, n in c.execute("SELECT canonical_term_id, extraction_run_id, COUNT(*) FROM term_mention "
                                 "WHERE canonical_term_id IS NOT NULL GROUP BY 1, 2"):
        if tid in terms and run in SRC:
            src_terms[tid].add(SRC[run])
            mentions[(tid, SRC[run])] += n
    c.close()
    ds = {}
    with gzip.open(DS, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["scheme"] == "cdm":
                ds[(r["string"].lower(), r["proposed_type"])] = (r["valid"] == "Y", r["valid"] == "Y" and r["type_correct"] == "Y")
    qw = {r["term_id"]: r["valid"] == "True" for r in csv.DictReader(open(QW, encoding="utf-8")) if r["valid"] in ("True", "False")}
    judged = {t: ds.get((terms[t][0].lower(), terms[t][1])) for t in src_terms}

    def measure(keep: set[str]):
        ts = [t for t, s in src_terms.items() if s & keep]
        dj = [judged[t] for t in ts if judged[t] is not None]
        qj = [qw[t] for t in ts if t in qw]
        return {"terms": len(ts), "mentions": sum(n for (t, s), n in mentions.items() if s in keep),
                "deepseek_judged": len(dj), "deepseek_valid": sum(v for v, _ in dj), "deepseek_valid_typed": sum(vt for _, vt in dj),
                "deepseek_valid_pct": round(100 * sum(v for v, _ in dj) / len(dj), 1) if dj else None,
                "qwen_judged": len(qj), "qwen_valid": sum(qj), "qwen_valid_pct": round(100 * sum(qj) / len(qj), 1) if qj else None}
    full = {"NER", "LLM", "GAZ"}
    variants = {"full system": measure(full)}
    for s in sorted(full):
        variants[f"without {NAMES[s]}"] = measure(full - {s})
    for s in sorted(full):
        variants[f"{NAMES[s]} only"] = measure({s})
    unique = {}
    for s in sorted(full):
        ts = [t for t, x in src_terms.items() if x == {s}]
        dj = [judged[t] for t in ts if judged[t] is not None]
        qj = [qw[t] for t in ts if t in qw]
        unique[NAMES[s]] = {"terms_only_from_this_source": len(ts), "deepseek_valid": sum(v for v, _ in dj),
                            "deepseek_valid_typed": sum(vt for _, vt in dj), "deepseek_judged": len(dj),
                            "qwen_valid": sum(qj), "qwen_judged": len(qj)}
    overlap = Counter("+".join(sorted(s)) for s in src_terms.values())
    res = {"note": "Existing mentions only; quality = model judgements (DeepSeek-V4-Flash, Qwen3.5-9B), not accuracy.",
           "linked_terms": len(src_terms), "variants": variants, "unique_contribution": unique,
           "overlap_sets": dict(overlap.most_common())}
    (OUT / "summary.json").write_text(json.dumps(res, indent=1) + "\n")
    f = variants["full system"]
    L = ["# Source ablation of the terminology layer (WS-4), 2026-11-05", "",
         "Existing CDM 3.0.3 mentions; validity is model-judged (DeepSeek-V4-Flash; Qwen3.5-9B as second judge).", "",
         "| variant | canonical terms | % of full | mentions | DeepSeek valid (n) | DeepSeek valid % | DeepSeek valid lost vs full | Qwen valid % |",
         "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k, v in variants.items():
        L.append(f"| {k} | {v['terms']:,} | {round(100 * v['terms'] / f['terms'], 1)} | {v['mentions']:,} | {v['deepseek_valid']:,} | "
                 f"{v['deepseek_valid_pct']} | {f['deepseek_valid'] - v['deepseek_valid']:,} | {v['qwen_valid_pct']} |")
    L += ["", "## Unique contribution (terms found by one source only)", "",
          "| source | terms only from it | DeepSeek valid | DeepSeek valid and typed | Qwen valid |", "|---|---:|---:|---:|---:|"]
    for k, v in unique.items():
        L.append(f"| {k} | {v['terms_only_from_this_source']:,} | {v['deepseek_valid']:,} of {v['deepseek_judged']:,} | "
                 f"{v['deepseek_valid_typed']:,} | {v['qwen_valid']:,} of {v['qwen_judged']:,} |")
    L += ["", "## Overlap of sources (canonical terms)", "", "| sources | terms |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in overlap.most_common()]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
