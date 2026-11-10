#!/bin/bash
#SBATCH --job-name=gap-cpu
#SBATCH --output=outputs/logs/gap/%x_%j.out
#SBATCH --error=outputs/logs/gap/%x_%j.err
#SBATCH --partition=intelsr_short
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00

# CPU step of the gap chain: STEP=<apply stage> | finalize31 | g10merge
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
export PYTHONPATH="$CDM_ROOT/src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1
S=src/scripts/vllm_termpop
echo "== gap cpu step: $STEP $(date)"
case "$STEP" in
    apply_*) python $S/gap_stages.py apply --stage "${STEP#apply_}" ;;
    finalize31)
        python $S/gap_stages.py finalize
        python $S/normalize_catalogue_vocab.py --offline \
            --input_dir outputs/results/catalogue_v3_1_pre_vocab --output_dir outputs/results/catalogue_v3_1
        python $S/qa_catalogue_v3.py --catalogue_dir outputs/results/catalogue_v3_1
        python $S/build_catalogue_release.py --catalogue_dir outputs/results/catalogue_v3_1 --version 3.1.0
        (cd releases/data_catalogue_v3/3.1.0 && sha256sum -c MANIFEST.sha256 --quiet && echo manifest verified)
        python $S/gap_g10.py inputs --nparts "${G10_PARTS:-8}" ;;
    finalize_release)  # rebuild v3.1 + freeze VERSION without regenerating G10 inputs
        python $S/gap_stages.py finalize
        python $S/normalize_catalogue_vocab.py --offline \
            --input_dir outputs/results/catalogue_v3_1_pre_vocab --output_dir outputs/results/catalogue_v3_1
        python $S/qa_catalogue_v3.py --catalogue_dir outputs/results/catalogue_v3_1
        python $S/build_catalogue_release.py --catalogue_dir outputs/results/catalogue_v3_1 --version "$VERSION"
        (cd releases/data_catalogue_v3/$VERSION && sha256sum -c MANIFEST.sha256 --quiet && echo manifest verified) ;;
    g10merge) python $S/gap_g10.py merge ;;
    ds_apply) python $S/deepseek_review.py apply ;;
    term101)
        python $S/fix_terminology_offsets.py --dst releases/terminology/1.0.1
        (cd releases/terminology/1.0.1 && find . -type f ! -name MANIFEST.sha256 | sort | xargs sha256sum > MANIFEST.sha256 \
            && sha256sum -c MANIFEST.sha256 --quiet && echo manifest verified)
        chmod -R a-w releases/terminology/1.0.1 ;;
    cdm3)
        V="${CDM_VERSION:-3.0.1}"
        python $S/build_cdm_v3.py --version "$V" --out outputs/results/cdm_v3_$V/microbiome_cdm_v3.db
        REL=releases/cdm_v3/$V
        [ -e "$REL" ] && { echo "$REL exists (frozen); bump the version"; exit 1; }
        mkdir -p "$REL"
        cp outputs/results/cdm_v3_$V/microbiome_cdm_v3.db outputs/results/cdm_v3_$V/cdm_v3_counts.json "$REL/"
        python - "$REL" "$V" <<'PY'
import json, sqlite3, sys
rel, ver = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"{rel}/microbiome_cdm_v3.db")
rows = c.execute("SELECT entity, module, \"table\", rows, status FROM cdm_entity_status").fetchall()
L = [f"# Human Microbiome Research CDM — {ver}", "",
     "Template-shaped build (src/template/cdm 0.1.0, modules M1–M10) over the 453-paper corpus, the v3.1 "
     "data catalogue, terminology 1.0.0, the GPU gap stages (docs/gpu_gap_plan.md) and the compendium "
     "samples for the corpus BioProjects. All rows are machine-derived; `review_status` is UNVERIFIED / "
     "REVIEW_REQUIRED everywhere — no human review exists yet (`human_review` is empty by design).", "",
     "| entity | module | table | rows | status |", "|---|---|---|---:|---|"]
L += [f"| {e} | {m} | `{t}` | {'' if n is None else f'{n:,}'} | {s} |" for e, m, t, n, s in rows]
L += ["", "Extra tables: `publication`/`paper_publication` (453 BioProject papers → distinct publications; "
      "shared publications flagged CONFLICTING), `compendium_sample`, `compendium_sample_tag`, "
      "`compendium_project`, `type_harmonization`, `term_concept_map.relation_llm_g9`, `load_audit` "
      "(rows offered vs kept per table).", "",
     "3.0.1 vs 3.0.0: `term_mention` is keyed by `mention_row_id` = mention_id|extraction_model, so mentions "
     "of the same span by different models are all kept (3.0.0 kept one per mention_id); "
     "`canonical_term_status` / `term_status` flag rows pointing at a removed (REMOVED) or unknown "
      "(NOT_IN_TERMINOLOGY) term; `term_concept_map` keeps all 331,394 guard rows under `mapping_row_id` "
      "(upstream `mapping_id` is missing on 11,477 rows and shared on 7,603; reviews attach on mapping_id + "
      "term_id + concept_id); catalogue tables and `term_definition` carry `evidence_anchor_status` and the "
      "exact source `evidence_span` (EXACT / WHITESPACE / RELOCATED / NORMALISED: verbatim; FUZZY: approximate "
      "location, review needed; UNANCHORED: quote not found). QA: `qa_cdm_report.json`, `QA_CDM.md`.", "",
     "3.0.2 vs 3.0.1: built on terminology 1.0.1 (mention offsets corrected in 75 shifted sections; "
     "`term_mention.canonical_term_id` linked by term_norm, `term_link_status`); `taxonomy_annotation` filled by "
     "two independent classifiers (G11 Qwen3.5-4B, G11B Gemma-4-E4B) against terminology_taxonomy.json 1.0.0 — "
     "`category`/`subcategory` set only where they agree (`agreement_status`), all REVIEW_REQUIRED.", "",
      "Verify: `sha256sum -c MANIFEST.sha256`", ""]
open(f"{rel}/README.md", "w").write("\n".join(L))
PY
        python $S/qa_cdm_v3.py --db "$REL/microbiome_cdm_v3.db" --out "$REL"
        (cd "$REL" && sha256sum microbiome_cdm_v3.db cdm_v3_counts.json README.md qa_cdm_report.json QA_CDM.md > MANIFEST.sha256 && sha256sum -c MANIFEST.sha256 --quiet && echo manifest verified)
        chmod -R a-w "$REL" ;;
    *) echo "unknown STEP"; exit 2 ;;
esac
echo "== done $(date)"
