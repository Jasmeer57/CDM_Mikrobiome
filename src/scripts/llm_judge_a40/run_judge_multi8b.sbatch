#!/bin/bash
#SBATCH --job-name=judge-m8b
#SBATCH --output=outputs/logs/llm_judge/multi_judge_%j.out
#SBATCH --error=outputs/logs/llm_judge/multi_judge_%j.err
# Generic GPU + dual-partition: job starts on whichever partition (sgpu_short/A100
# or mlgpu_short/A40) frees a GPU first. AWQ INT4 Marlin kernels run on both.
#SBATCH --partition=sgpu_short,mlgpu_short
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
# 38G (not 64G): mlgpu_short A40 nodes run tight on RAM (free ~40.3GiB on
# mlgpu001/002/004). 38 GiB fits those nodes; ample for an 8B AWQ vLLM server.
#SBATCH --mem=38G
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=07:30:00

# ──────────────────────────────────────────────────────────────────────────
# MULTI-JUDGE AGREEMENT (Anchor 1) — ONE judge per invocation (submit 3×).
# Each invocation runs a single judge on the SAME 2,000-item sample already
# judged by Judge A (google/gemma-4-E4B-it-qat-w4a16-ct).
#
# 4-BIT QUANTIZED PROTOCOL (all five models in the anchor run are 4-bit):
#   Judge A: google/gemma-4-E4B-it-qat-w4a16-ct (done) verdicts: outputs/results/ (RO)
#   Judge B: thesven/Phi-3.5-mini-instruct-awq                (AWQ INT4)
#   Judge C: hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4 (AWQ INT4)
#   Judge D: TechxGenus/Mistral-7B-Instruct-v0.3-AWQ            (AWQ INT4)
#
# UnGated mirrors were chosen because no HF_TOKEN is configured on this
# cluster. AWQ INT4 ≈2.2–5.7 GB per model -- all three fit in GPU memory
# with ease on a single A40 or A100 and were pre-downloaded into
# /home/jkalra_hpc/llm/hf-cache (outputs/scratch/download_awq_judges.sh).
#
# Submit with:  sbatch --export=ALL,JUDGE=B src/scripts/llm_judge_a40/run_judge_multi8b.sbatch
#               sbatch --export=ALL,JUDGE=C ... ; sbatch --export=ALL,JUDGE=D ...
# One job per judge: independent walltime, independent resubmit on retry —
# the 8h mlgpu_short cap covers a single judge (vLLM spin-up + 2,000 items
# × up to 5 sampling attempts) with margin. JUDGE="B C D" runs all three in
# one job (serial, kept for reference; not the default path).
#
# All judge families differ from the extractor (Qwen 3.5:9b) and from each
# other: Gemma / Phi / Llama-3.1 / Mistral. This is multi-judge CONSENSUS,
# not human validation.
#
# Output isolation: each judge writes only to outputs/logs/llm_judge/results_multi/<X>/.
# Judge A's verdicts are never touched.
#
# Sampling: a uniform temp 0.6 / top_p 0.95 across B/C/D, documented as a
# protocol deviation from Judge A (Gemma ran temp 0) in the agreement report.
# ──────────────────────────────────────────────────────────────────────────

# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -euo pipefail
PROJECT_ROOT="$CDM_ROOT"
cd "$PROJECT_ROOT"

# GPU nodes in mlgpu_short host 8 a40s; SLURM may pack multiple one-judge
# jobs onto the SAME node, where a fixed port would collide. Derive the port
# from the job id (each job is a distinct id, so co-located jobs get distinct
# ports). Override with: sbatch --export=ALL,JUDGE=B,JUDGE_PORT_OVERRIDE=8123
# NOTE: sgpu_* nodes host 4 a100s and PACK multiple jobs per node; the
# job-id-derived port survives node packing without collisions.
PORT_BASE=8000
if [ -n "${SLURM_JOB_ID:-}" ]; then
    PORT=$(( PORT_BASE + SLURM_JOB_ID % 200 ))
else
    PORT=$PORT_BASE
fi
if [ -n "${JUDGE_PORT_OVERRIDE:-}" ]; then
    PORT="$JUDGE_PORT_OVERRIDE"
fi

PIPE="$PROJECT_ROOT/src/scripts/llm_judge_a40"
OUTD="$PROJECT_ROOT/outputs/logs/llm_judge"

module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate

export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME="${HF_HOME:-/home/jkalra_hpc/llm/hf-cache}"
export HF_HUB_OFFLINE=0          # download weights inside the job
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export TOKENIZERS_PARALLELISM=false
export VLLM_WORKER_MULTIPROC_METHOD=spawn

echo "HF_HOME=$HF_HOME"
nvidia-smi -L || true

# tag|served-model|temp|top_p|max_tokens|vllm_extra_args
# Judge B: the DeepSeek-R1-distill-llama-8b AWQ judge was ABANDONED (2026-10-29)
# and its weights deleted. Two independent problems made it unusable:
#   (1) its repo ships a byte-level BPE tokenizer with no tokenizer.model, and
#       vLLM emitted undecoded markers -- valid JSON arrived as
#       '{ĠĠ"verdict":Ġ"SUPPORTED"}' (Ġ=space, Ċ=newline). The client now
#       repairs this (repair_bytelevel) but the run was still unreliable;
#   (2) a no-think chat-template prefill (the original protocol ask) destroyed
#       it outright -- R1-distills ramble when forced to skip reasoning, hitting
#       finish_reason=length at 4096 tokens.
# REPLACED by Phi-3.5-mini-instruct-AWQ (4-bit AWQ, gemm, group 128, ungated).
# Phi is the one remaining major family not otherwise used as a judge, so the
# multi-judge set stays family-diverse: Gemma / Phi / Llama-3.1 / Mistral, none
# of which is the Qwen extractor. No reasoning tokens -> max_tokens 1024, and
# no thinking-mode deviation to document for this judge.
JUDGES=(
  "B|thesven/Phi-3.5-mini-instruct-awq|0.6|0.95|1024|"
  "C|hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4|0.6|0.95|1024|"
  "D|TechxGenus/Mistral-7B-Instruct-v0.3-AWQ|0.6|0.95|1024|"
)

# Which judge(s) to run, from the SLURM-exported JUDGE variable.
# Default B; one job per judge keeps each inside the 8h mlgpu_short cap and
# makes a walltime hit lose at most one judge's partial run.
JUDGE="${JUDGE:-B}"

download_weights() {
    local repo="$1"
    # Weights were pre-downloaded to $HF_HOME by outputs/scratch/download_awq_judges.sh;
    # this verifies offline presence (fast, no re-download).
    echo "[$(date +%T)] checking $repo in HF_HOME (offline) ..."
    if HF_HUB_OFFLINE=1 python -c "
from huggingface_hub import snapshot_download
snapshot_download('$repo', local_files_only=True)
print('present: $repo')
"; then
        return 0
    fi
    echo "[$(date +%T)] $repo NOT in cache — downloading ..."
    hf download "$repo" --max-workers 4 2>&1 | tail -2
}

wait_server_ready() {
    # polls the vLLM server; assumes VLLM_PID and $PORT set; returns non-zero on failure
    local logf="$1"
    local ready=""
    for _ in $(seq 1 180); do
        if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
            ready=1
            break
        fi
        if ! kill -0 "$VLLM_PID" 2>/dev/null; then
            echo "SERVER_DIED during startup — see $logf"
            tail -50 "$logf"
            return 1
        fi
        sleep 5
    done
    if [ -z "$ready" ]; then
        echo "SERVER_TIMEOUT (not ready in 15 min) — see $logf"
        tail -50 "$logf"
        return 1
    fi
    echo "SERVER_READY at $(date -u)"
}

run_judge() {
    local tag="$1" model="$2" temp="$3" top_p="$4" maxtok="$5" extra="$6"
    local results_dir="$OUTD/results_multi/$tag"
    local server_log="$results_dir/vllm_server_${tag}.log"
    mkdir -p "$results_dir"

    echo "===================================================================="
    echo "JUDGE $tag :: $model  (temp=$temp top_p=$top_p max_tokens=$maxtok)"
    echo "===================================================================="

    download_weights "$model"

    # AWQ INT4 -> Marlin kernels on A100; dtype half required (fp16
    # activations). CUDA graphs stay ON: hours-long run at client
    # concurrency 32 amortizes the ~1-min capture cost.
    echo "[$(date +%T)] starting vLLM server for $model ${extra:+[$extra]} ..."
    # shellcheck disable=SC2086
    vllm serve "$model" \
        --port "$PORT" \
        --tensor-parallel-size 1 \
        --gpu-memory-utilization 0.90 \
        --max-model-len 8192 \
        --dtype half \
        --trust-remote-code \
        $extra \
        > "$server_log" 2>&1 &
    VLLM_PID=$!

    if ! wait_server_ready "$server_log"; then
        kill "$VLLM_PID" 2>/dev/null || true
        return 1
    fi

    # Smoke: 3 items on C1; aborts this judge (not the job) on failure.
    echo "[$(date +%T)] smoke test (3 items, C1) ..."
    if python "$PIPE/run_judge_client_a40.py" \
            --input "$OUTD/input_C1.jsonl" \
            --output "$results_dir/smoke_C1.jsonl" \
            --model "$model" --port "$PORT" --parallel 3 --limit 3 --retries 5 \
            --temperature "$temp" --top_p "$top_p" --max_tokens "$maxtok" \
            --chat_template_kwargs '{}' \
            --artifact C1 --prompt "$PIPE/prompts/judge_C1.txt"; then
        echo "[$(date +%T)] smoke test PASS for judge $tag"
        head -3 "$results_dir/smoke_C1.jsonl"
    else
        echo "SMOKE_FAIL for judge $tag — skipping its C1-C4 run"
        kill "$VLLM_PID" 2>/dev/null || true
        wait "$VLLM_PID" 2>/dev/null || true
        return 1
    fi

    local rc=0
    for artifact in C1 C2 C3 C4; do
        local outf="$results_dir/${artifact}_verdicts.jsonl"
        if [ -s "$outf" ]; then
            echo "[$(date +%T)] JUDGE $tag :: $artifact already done ($(wc -l < "$outf") lines) — skipping"
            continue
        fi
        echo "----------------------------------------------------------------"
        echo "[$(date +%T)] JUDGE $tag :: $artifact (500 items) ..."
        python "$PIPE/run_judge_client_a40.py" \
            --input "$OUTD/input_${artifact}.jsonl" \
            --output "$results_dir/${artifact}_verdicts.jsonl" \
            --model "$model" --port "$PORT" --parallel 32 --retries 5 \
            --temperature "$temp" --top_p "$top_p" --max_tokens "$maxtok" \
            --chat_template_kwargs '{}' \
            --artifact "$artifact" \
            --prompt "$PIPE/prompts/judge_${artifact}.txt" || rc=1
    done

    echo "[$(date +%T)] stopping vLLM server (pid $VLLM_PID)"
    kill "$VLLM_PID" 2>/dev/null || true
    wait "$VLLM_PID" 2>/dev/null || true
    echo "JUDGE $tag done rc=$rc"
    return "$rc"
}

# ── MAIN ──────────────────────────────────────────────────────────────────
mkdir -p "$OUTD/agreement" "$OUTD/results_multi"

overall=0
selected=""
for cfg in "${JUDGES[@]}"; do
    IFS='|' read -r tag model temp top_p maxtok extra <<< "$cfg"
    case " $JUDGE " in
        *" $tag "*) selected+=" $tag" ;;
        *) continue ;;
    esac
    if run_judge "$tag" "$model" "$temp" "$top_p" "$maxtok" "$extra"; then
        echo "judge $tag OK"
    else
        echo "judge $tag FAILED (continuing with remaining judges)"
        overall=1
    fi
done
if [ -z "$selected" ]; then
    echo "ERROR: JUDGE='$JUDGE' matches no configured judge tag (B|C|D)"
    exit 2
fi

echo "===================================================================="
echo "PAIRWISE AGREEMENT (κ / Krippendorff α) — judges A + [$selected ]"
echo "===================================================================="
python "$PIPE/compute_judge_agreement.py" \
    --baseline "$OUTD/results" \
    --multi_dir "$OUTD/results_multi" \
    --out_dir "$OUTD/agreement" || overall=1

echo "========================================================================"
echo "MULTI-JUDGE RUN DONE at $(date -u)  overall_rc=$overall"
echo "========================================================================"
exit "$overall"
