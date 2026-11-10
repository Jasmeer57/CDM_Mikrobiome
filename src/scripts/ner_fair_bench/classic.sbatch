#!/bin/bash
#SBATCH --job-name=nerbench-classic
#SBATCH --output=outputs/logs/ner_bench/%x_%j.out
#SBATCH --error=outputs/logs/ner_bench/%x_%j.err
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
# Classic NER models of the fair benchmark (fairbench.py).
#   GROUP=gpu -> GLiNER family + BERT variants (vllm venv + gliner overlay), submit with an A40
#   GROUP=cpu -> scispaCy (5 models) + HunFlair2 (ner_variants venv + scispaCy model overlay)
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
export PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_VERBOSITY=error
B=src/scripts/ner_fair_bench/${BENCH:-fairbench}.py   # BENCH=corpus_bench: the 453-paper corpus run
case "${GROUP:?}" in
    gpu)
        module load CUDA/12.9.1
        source /home/jkalra_hpc/venvs/vllm/bin/activate
        export PYTHONPATH="/home/jkalra_hpc/venvs/gliner_overlay:$CDM_ROOT/src:${PYTHONPATH:-}"
        nvidia-smi --query-gpu=name --format=csv,noheader
        HF_HOME=/home/jkalra_hpc/llm/hf-cache-gliner python $B classic --device "A40 GPU" \
            --models gliner_v25_medium gliner_v25_biomed gliner2_base gliner2_large
        HF_HOME=/home/jkalra_hpc/.cache/huggingface python $B classic --device "A40 GPU" \
            --models bert_disease bert_chemical bert_genetic scibert_jnlpba ;;
    cpu)
        source /home/jkalra_hpc/venvs/ner_variants/bin/activate
        export PYTHONPATH="/home/jkalra_hpc/venvs/scispacy_models_overlay:$CDM_ROOT/src:${PYTHONPATH:-}"
        python $B classic --device "CPU (8 cores)" \
            --models scispacy_bc5cdr scispacy_craft scispacy_jnlpba scispacy_bionlp13cg scispacy_lg hunflair2 ;;
esac
