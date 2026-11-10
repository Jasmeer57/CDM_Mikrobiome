"""Copy every output the manuscript and its supplement rest on into paper/publication/all_frozen_outputs/.

    python src/scripts/final_validation/collect_frozen_outputs.py [--dry-run]

Copies (never moves): sources keep their paths, manifests and scripts keep working. Writes MANIFEST.sha256 over the
copy and INVENTORY.tsv (group, destination, source, bytes, rights note). Refuses to overwrite an existing
destination file whose content differs. The copy holds paper text and quotes from non-CC-BY papers: it is for the
authors, not for upload, and is git-ignored.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DEST = ROOT / "paper/publication/all_frozen_outputs"
B = "outputs/results/benchmark/"
TEXT = "CONTAINS PAPER TEXT/QUOTES: release only the 274 CC BY/CC0 papers' text (rights matrix)"
NOTEXT = "no paper text"

# working files that may change after the freeze (logged in CHANGE_RECORD.md); every other file must match exactly
LIVING = {"CHANGE_RECORD.md", "MANUSCRIPT_CLAIMS_REGISTER.csv", "MANUSCRIPT_NUMBER_AUDIT.csv"}
LIVING_PREFIX = ("MANUSCRIPT_CLAIMS_REGISTER_CORRECTIONS_", "PAPER_NUMBERS_")

# (group/destination, source relative to ROOT, rights note)
ITEMS = [
    # 01 frozen releases (the resource) = releases/CURRENT_FROZEN_SET_2026-11-02
    ("01_releases/corpus_2.2.0", "pipelines/corpus_v2/releases/2.2.0", TEXT),
    ("01_releases/corpus_2.2.0_segmented", "releases/frozen_output/01_corpus/data", TEXT),
    ("01_releases/corpus_2.2.0_markdown", "releases/frozen_output/01_corpus/segmented_sections_markdown", TEXT),
    ("01_releases/ner_per_model", "releases/frozen_output/04_ner", TEXT + " (mention contexts)"),
    ("01_releases/cdm_3.0.3", "releases/cdm_v3/3.0.3", TEXT),
    ("01_releases/data_catalogue_3.1.1", "releases/data_catalogue_v3/3.1.1", TEXT),
    ("01_releases/terminology_1.0.1", "releases/terminology/1.0.1", TEXT),
    # 02 table exports of CDM 3.0.3
    ("02_exports/cdm_3.0.3_parquet_xlsx", "outputs/exports/cdm_v3_3.0.3_parquet", TEXT),
    ("02_exports/export_tools/README.md", "outputs/exports/README.md", NOTEXT),
    ("02_exports/export_tools/export_cdm_parquet.py", "outputs/exports/export_cdm_parquet.py", NOTEXT),
    ("02_exports/export_tools/verify_cdm_parquet.py", "outputs/exports/verify_cdm_parquet.py", NOTEXT),
    ("02_exports/export_tools/export_run.log", "outputs/exports/export_run.log", NOTEXT),
    # 03 claims register and validation reports (numbers of the paper)
    ("03_claims_and_validation/final_validation", "paper/publication/final_validation", "quotes in evidence_judge/*.jsonl"),
    # 04 evaluation results behind the register
    ("04_evaluation/ner_public_benchmark", B + "ner_fair_bench", NOTEXT + " (public corpora)"),
    ("04_evaluation/ner_species_s1000", B + "ner_species_s1000", NOTEXT + " (public corpus); NOT registered"),
    ("04_evaluation/ner_corpus_benchmark", B + "ner_corpus_bench", TEXT + " (chunks.jsonl, preds)"),
    ("04_evaluation/ner_quality_quantity", B + "ner_quality_quantity_2026-11-03", NOTEXT),
    ("04_evaluation/llm_judge_terms_triples_v4", B + "llm_judge_deepseek_v4_flash", "term/triple strings only"),
    ("04_evaluation/bugsigdb_comparison", B + "bugsigdb_comparison_2026-11-03", "BugSigDB is CC BY 4.0"),
    ("04_evaluation/triple_reference_check", B + "triple_reference_check_2026-11-03", NOTEXT),
    ("04_evaluation/triple_evidence_ccby", B + "triple_evidence_ccby_2026-11-07", NOTEXT + "; W01-W05, use needs lead approval"),
    ("04_evaluation/knowledge_graph", "outputs/results/kg_2026-11-04", "evidence_check quotes are CC BY/CC0 only"),
    ("04_evaluation/decision_guide", B + "decision_guide_facts_2026-11-06", NOTEXT),
    ("04_evaluation/judge_agreement", B + "judge_agreement_2026-11-05", NOTEXT),
    ("04_evaluation/judge_matrix_s6", B + "s6_judge_matrix_2026-11-06", NOTEXT),
    ("04_evaluation/judge_sanity_open", B + "judge_sanity_open_2026-11-05", "check inputs/ for quotes"),
    ("04_evaluation/judge_sanity_qwen", B + "judge_sanity_qwen_2026-11-05", "check inputs/ for quotes"),
    ("04_evaluation/significance", B + "significance_2026-11-05", NOTEXT),
    ("04_evaluation/source_ablation", B + "source_ablation_2026-11-05", NOTEXT),
    ("04_evaluation/runtime_facts", B + "runtime_facts_2026-11-06", NOTEXT),
    ("04_evaluation/use_case_ibd", B + "use_case_ibd_2026-11-05", NOTEXT),
    # 05 manuscript figures and tables
    ("05_manuscript_assets/figures", "paper/publication/manuscript_bib/figures", NOTEXT),
    ("05_manuscript_assets/tables", "paper/publication/manuscript_bib/tables", NOTEXT),
    ("05_manuscript_assets/pipeline_flowchart.md", "docs/reports/pipeline_flowchart.md", NOTEXT),
    # 07 corrections after the freeze
    ("07_corrections/non_english_scan_2026-11-08", "outputs/results/non_english_scan_2026-11-08", "Korean strings of a withheld paper in summary/strings"),
    # 06 rights
    ("06_rights/paper_rights", "paper/publication/rights", NOTEXT),
    ("06_rights/external_processing", "outputs/results/rights", NOTEXT),
    # internal only: not for the supplement
    ("internal_do_not_publish/evidence_judge_all_licences_2026-11-07", "outputs/results/evidence_judge_all_2026-11-07",
     "DO_NOT_CITE: rights incident run (9,629 non-CC-BY sentences sent)"),
    ("internal_do_not_publish/llm_judge_v41_triples", B + "llm_judge_deepseek_v41_triples", "superseded run"),
    ("internal_do_not_publish/term_spotcheck_claude", B + "term_spotcheck_claude_2026-11-05",
     "Claude-judged spot check: model judgement, not human annotation"),
    ("internal_do_not_publish/triple_spotcheck_claude", B + "triple_spotcheck_claude_2026-11-05",
     "Claude-judged spot check: model judgement, not human annotation"),
]


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def files_of(src: Path):
    if src.is_file():
        yield src, Path()
    else:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                yield p, p.relative_to(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    inv, total, missing = [], 0, []
    for dest, src, note in ITEMS:
        s = ROOT / src
        if not s.exists():
            missing.append(src)
            continue
        for f, rel in files_of(s):
            d = DEST / dest / rel if rel != Path() else DEST / dest
            n = f.stat().st_size
            total += n
            inv.append((dest.split("/")[0], str(d.relative_to(DEST)), str(f.relative_to(ROOT)), n, note))
            if a.dry_run:
                continue
            d.parent.mkdir(parents=True, exist_ok=True)
            if d.exists():
                if d.stat().st_size == n and sha(d) == sha(f):
                    continue
                if f.name not in LIVING and not f.name.startswith(LIVING_PREFIX):
                    raise SystemExit(f"refusing to overwrite differing file: {d}")
            shutil.copy2(f, d)
    print(f"{len(inv)} files, {total / 1e9:.2f} GB" + (" (dry run)" if a.dry_run else ""))
    if missing:
        print("missing sources:", missing)
    if a.dry_run:
        return
    with open(DEST / "INVENTORY.tsv", "w", encoding="utf-8") as f:
        f.write("group\tpath\tsource\tbytes\trights_note\n")
        for row in inv:
            f.write("\t".join(map(str, row)) + "\n")
    with open(DEST / "MANIFEST.sha256", "w", encoding="utf-8") as f:
        for _, p, *_ in inv:
            f.write(f"{sha(DEST / p)}  {p}\n")
    print("wrote INVENTORY.tsv and MANIFEST.sha256")


if __name__ == "__main__":
    main()
