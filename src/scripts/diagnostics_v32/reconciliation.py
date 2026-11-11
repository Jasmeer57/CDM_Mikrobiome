"""Figure / number reconciliation (diagnostics 2026-11-11, item 5). Report only: no figure, register or manuscript file is
changed. Recomputes from the frozen sources the values behind manuscript Fig. 3 (label fig:results, fig4_results.pdf,
src/scripts/figures/make_bib_figures.py fig4()) and the related text, the configuration counts, the mapping-row delta and
the G9 adjudicator identity. The Crossref record for davis2026ctd is read from crossref_davis2026ctd.json (fetched
2026-11-11; DOI metadata only).

    python src/scripts/diagnostics_v32/reconciliation.py
Written with Claude Code (declare)."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OUT = ROOT / "outputs/results/diagnostics_2026-11-11/reconciliation"
LJ = ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/summary.json"
BS = ROOT / "outputs/results/benchmark/bugsigdb_comparison_2026-11-03/summary.json"
FAIR = ROOT / "outputs/results/ner_fair_bench/fair_ner_metrics.json"
CORP = ROOT / "outputs/results/ner_corpus_bench/corpus_metrics.json"
DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
G9LOGS = sorted((ROOT / "outputs/logs/gap").glob("vllm_G9_*.log")) + sorted((ROOT / "outputs/logs/gap").glob("gap-G9_*.out"))


def pct(d, f):
    return round(100 * d[f] / d["d"], 1)


def main():
    lj = json.load(open(LJ))
    a = {}
    a["fig3a_bars_benchmark_valid_and_typed_distinct"] = {k: {"pct": pct(v["distinct"], "valid_type"), "distinct_strings": v["distinct"]["d"]}
                                                          for k, v in sorted(lj["benchmark"].items(), key=lambda kv: -kv[1]["distinct"]["valid_type"] / kv[1]["distinct"]["d"])}
    a["cdm_production_runs_not_in_fig3a"] = {k: {"distinct_strings": v["distinct"]["d"], "valid_any_type_pct": pct(v["distinct"], "valid"),
                                                 "valid_and_typed_pct": pct(v["distinct"], "valid_type"),
                                                 "mention_weighted_valid_pct": pct(v["mentions"], "valid"),
                                                 "mention_weighted_valid_and_typed_pct": pct(v["mentions"], "valid_type")}
                                             for k, v in lj["cdm_models"].items()}
    bs = json.load(open(BS))
    a["fig3b_fields_drawn"] = ["region_16s", "country", "condition", "statistical_test", "group_size", "group_name"]
    b_site = bs["fields"]["body_site"]
    a["body_site"] = {"items": b_site["items"], "lexical_match_pct": round(100 * b_site["lexical_match"], 1),
                      "lexical_match_k": round(b_site["lexical_match"] * b_site["items"]),
                      "preregistered_sapbert_concordance_pct": round(100 * b_site["concordance"], 1),
                      "sapbert_k": b_site["verdicts"]["MATCH"], "sapbert_wilson95": [round(100 * x, 1) for x in b_site["concordance_wilson"]],
                      "sapbert_threshold": b_site["threshold"], "chance_pct": 100 * b_site["chance"],
                      "minilm_sensitivity_pct": round(100 * b_site["sensitivity_minilm"]["concordance"], 1)}
    fair = json.load(open(FAIR))
    corp = json.load(open(CORP))["models"]
    cfg = sorted({k.split("__", 1)[1] for k in fair})
    llm = [c for c in cfg if c.startswith("llm_")]
    systems = sorted({c.rsplit("_", 1)[0] if c in llm else c for c in cfg})
    a["counts"] = {"public_benchmark_configurations": len(cfg), "public_benchmark_systems": len(systems),
                   "llm_systems": sorted({c.rsplit("_", 1)[0] for c in llm}), "non_llm_systems": sorted(set(cfg) - set(llm)),
                   "corpus_benchmark_configurations": len(corp), "public_not_in_corpus": sorted(set(cfg) - set(corp)),
                   "fig3a_configurations": len(lj["benchmark"]), "corpus_not_in_fig3a": sorted(set(corp) - set(lj["benchmark"]))}
    c = sqlite3.connect(f"file:{DB303}?mode=ro", uri=True)
    a["mapping_rows"] = {"term_concept_map_rows": c.execute("SELECT COUNT(*) FROM term_concept_map").fetchone()[0],
                         "by_guard_status": dict(c.execute("SELECT guard_status, COUNT(*) FROM term_concept_map GROUP BY 1").fetchall()),
                         "register_P01_candidates": 334231, "register_P04_demoted": 2837,
                         "g9_rows": c.execute("SELECT COUNT(*) FROM term_concept_map WHERE g9_run_id IS NOT NULL AND g9_run_id<>''").fetchone()[0]}
    a["mapping_rows"]["delta"] = 334231 - a["mapping_rows"]["term_concept_map_rows"]
    run = c.execute("SELECT * FROM extraction_run WHERE extraction_run_id='gap G9 apply'").fetchone()
    models = set()
    for p in G9LOGS:
        models |= set(re.findall(r"model[= ]+'?([\w./-]*gemma[\w./-]*)", p.read_text(errors="ignore")))
    snap = set()
    for p in G9LOGS:
        snap |= set(re.findall(r"gemma-4-E4B-it-qat-w4a16-ct/snapshots/([0-9a-f]{40})", p.read_text(errors="ignore")))
    adj = {json.loads(l).get("adjudicator") for l in open(ROOT / "outputs/results/gap_runs/G9/mapping_adjudication.jsonl", encoding="utf-8")}
    a["g9"] = {"extraction_run_row": run, "models_in_logs": sorted(models), "hf_snapshot": sorted(snap), "adjudicator_field": sorted(adj),
               "logs": [str(p.relative_to(ROOT)) for p in G9LOGS]}
    a["crossref_davis2026ctd"] = json.load(open(OUT / "crossref_davis2026ctd.json"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SUMMARY.json").write_text(json.dumps({"date": "2026-11-11", **a, "status": "report only; PENDING lead approval"}, indent=1, default=str) + "\n")
    print(json.dumps({k: a[k] for k in ("body_site", "counts", "mapping_rows", "g9")}, indent=1, default=str))


if __name__ == "__main__":
    main()
