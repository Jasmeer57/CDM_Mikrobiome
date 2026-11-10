"""Component I correction — retrospective SHA-256 seal over the public-benchmark artefact set.

This is provenance sealing performed AFTER the fact by the audit. It is NOT a preregistration: it
cannot constrain a result that already exists. It establishes only that the files hashed here are the
files that the recomputation and the deployability analysis read, at the seal date.

Writes:
  NER_RETROSPECTIVE_SEAL.sha256   sha256sum-compatible, paths relative to the repository root
  diagnostics/results/ner_environment.json
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
ROOT = next(p for p in AUDIT.parents if (p / ".cdm_root").is_file())

TARGETS = []
for p in sorted((ROOT / "outputs/results/benchmark/ner_fair_bench").rglob("*")):
    if p.is_file():
        TARGETS.append(p)
for p in sorted((ROOT / "outputs/results/benchmark/ner_corpus_bench").rglob("*")):
    if p.is_file():
        TARGETS.append(p)
for p in sorted((ROOT / "outputs/results/benchmark/ner_quality_quantity_2026-11-03").rglob("*")):
    if p.is_file():
        TARGETS.append(p)
for rel in ("src/scripts/ner_fair_bench/fairbench.py", "src/scripts/ner_fair_bench/corpus_bench.py",
            "src/scripts/ner_fair_bench/classic.sbatch", "src/scripts/ner_fair_bench/llm.sbatch",
            "src/scripts/ner_fair_bench/corpus_score.sbatch"):
    TARGETS.append(ROOT / rel)
for p in sorted((ROOT / "data/benchmarks_ner/raw").rglob("*")):
    if p.is_file():
        TARGETS.append(p)
for p in (AUDIT / "NER_RECOVERED_PROMPTS.md",
          AUDIT / "diagnostics/results/ner_recovered_prompts.json",
          AUDIT / "NER_RECOMPUTATION_CHECK.csv",
          AUDIT / "diagnostics/results/ner_recompute_summary.json",
          AUDIT / "diagnostics/results/ner_llm_run_diagnostics.csv",
          AUDIT / "diagnostics/results/ner_organism_transfer.json",
          AUDIT / "NER_TYPE_COVERAGE_MATRIX.csv",
          AUDIT / "NER_MODEL_DEPLOYABILITY.csv",
          AUDIT / "NER_RECOVERED_PROMPTS.md"):
    if p.exists():
        TARGETS.append(p)

# Corpus-side reference inputs (≈2.1 GB): the exact files corpus_bench.py reads to build its lexicons
# and KG association sets. They were NOT hash-pinned when the corpus benchmark was scored.
for rel in ("CTD_diseases.tsv.gz", "CTD_chemicals.tsv.gz", "CTD_curated_genes_diseases.tsv.gz",
            "CTD_chemicals_diseases.tsv.gz", "CTD_chem_gene_ixns.tsv.gz", "names.dmp", "nodes.dmp",
            "Homo_sapiens.gene_info.gz", "Mus_musculus.gene_info.gz", "disbiome_experiment.json"):
    TARGETS.append(ROOT / "data/reference_kg/raw" / rel)
for rel in ("outputs/results/omop_vocab/CONCEPT.csv", "outputs/results/omop_vocab/CONCEPT_SYNONYM.csv",
            "pipelines/corpus_v2/data/sections.jsonl"):
    TARGETS.append(ROOT / rel)

seen, lines = set(), []
for p in TARGETS:
    if p in seen:
        continue
    seen.add(p)
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    lines.append((h.hexdigest(), p.relative_to(ROOT).as_posix(), p.stat().st_size))

import time  # noqa: E402
sealed = time.strftime("%Y-%m-%dT%H:%M:%S%z")
body = "\n".join(f"{h}  {rel}" for h, rel, _ in lines) + "\n"
(AUDIT / "NER_RETROSPECTIVE_SEAL.sha256").write_text(body)

env = {
    "seal_date": sealed,
    "seal_kind": "retrospective provenance seal — NOT a preregistration",
    "files_sealed": len(lines),
    "bytes_sealed": sum(s for _, _, s in lines),
    "base_directory": str(ROOT),
    "path_convention": "paths are relative to the repository root; verify with `sha256sum -c` from the root",
    "not_sealed": ("the three audit narratives that describe this seal (NER_BENCHMARK_CORRECTIONS.md, "
                   "NER_REPRODUCIBILITY_GAPS.md, 09_NER_BENCHMARK_QUALITY.md) are deliberately excluded: "
                   "hashing a document that quotes the manifest byte count is self-referential"),
    "coverage": {
        "predictions": len([1 for _, r, _ in lines
                            if '/preds/' in r and r.endswith('.jsonl')]),
        "corpus_chunks": len([1 for _, r, _ in lines if r.endswith('corpus_bench/chunks.jsonl')]),
        "metrics_and_reports": len([1 for _, r, _ in lines if r.endswith(('.json', '.md', '.csv'))]),
        "scripts": len([1 for _, r, _ in lines if r.endswith(('.py', '.sbatch', '.sh'))]),
        "gold_data": len([1 for _, r, _ in lines if r.startswith('data/benchmarks_ner/raw')]),
        "prompts_and_recomputation": len([1 for _, r, _ in lines if r.startswith('paper/publication')]),
        "reference_inputs": len([1 for _, r, _ in lines
                                 if r.startswith('data/reference_kg/raw') or 'omop_vocab/CONCEPT' in r]),
        "corpus_sections": len([1 for _, r, _ in lines if r.endswith('corpus_v2/data/sections.jsonl')]),
    },
    "host": {"platform": platform.platform(), "machine": platform.machine(),
             "python": sys.version.split()[0], "python_executable": sys.executable},
    "environment_as_recorded_in_artefacts": {
        "fair_bench_llm_device": "1x A40 (vLLM) — the only device record in any prediction _meta",
        "fair_bench_classic_device": "args.device (default 'cuda'); not recorded per prediction file",
        "corpus_bench_device": sorted({json.loads(open(ROOT / 'outputs/results/benchmark/ner_corpus_bench/corpus_metrics.json').read())
                                       ['models'][k]['meta'].get('device', '')
                                       for k in json.loads(open(ROOT / 'outputs/results/benchmark/ner_corpus_bench/corpus_metrics.json').read())
                                       ['models']}),
        "vllm_version": "NOT RECORDED",
        "transformers_version": "NOT RECORDED",
        "torch_version": "NOT RECORDED",
        "gpu_driver": "NOT RECORDED",
        "requirement_lock_referenced": "requirements.lock exists in the repo but no bench-specific lock ships",
    },
    "gold_data": {
        "bc5cdr": {"test": 500, "source": "NCBI BioCreative V CDR corpus (public domain, NLM)"},
        "biored": {"test": 100, "source": "BioRED (NCBI)"},
        "integrity_file_present": (ROOT / "data/benchmarks_ner/raw/SHA256SUMS").exists(),
    },
}
(AUDIT / "diagnostics/results/ner_environment.json").write_text(json.dumps(env, indent=1) + "\n")
print(json.dumps({"sealed": sealed, "files": len(lines), "bytes": env["bytes_sealed"],
                  "coverage": env["coverage"]}, indent=1))
