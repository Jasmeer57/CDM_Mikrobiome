#!/bin/bash
# Run component-quality-audit diagnostics on a CPU node and capture logs.
#
# Usage:
#   DIAGS="d15_entity_extraction" sbatch --export=ALL cqa_diagnostics.sbatch
#   DIAGS="d15 d16" ...            # short names accepted, .py appended
#
# Everything is read-only against the frozen releases. No output outside
# paper/publication/component_quality_audit/.
#SBATCH --job-name=cqa_diag
#SBATCH --partition=intelsr_medium
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=outputs/logs/%x_%j.out
#SBATCH --error=outputs/logs/%x_%j.err

set -uo pipefail

PROJECT_ROOT="/home/jkalra_hpc/Microbiome-CDM"
cd "$PROJECT_ROOT" || { echo "FATAL: no project root"; exit 2; }

AUDIT_DIR="$PROJECT_ROOT/paper/publication/component_quality_audit"
DIAG_DIR="$AUDIT_DIR/diagnostics"
LOG_DIR="$AUDIT_DIR/logs"
mkdir -p "$LOG_DIR" "$PROJECT_ROOT/outputs/logs"

# Working CPU interpreter (see AGENTS.md: no microbiome-cdm-env exists here).
PY="$HOME/venvs/vllm/bin/python"
if [ ! -x "$PY" ]; then
    echo "FATAL: interpreter missing: $PY"
    exit 2
fi

export PYTHONPATH="$DIAG_DIR:$PROJECT_ROOT/src"
export MPLBACKEND=Agg
export PYTHONUNBUFFERED=1

# stdlib-only diagnostics: no pandas/numpy, no network.
DIAGS="${DIAGS:-d15_entity_extraction}"

echo "== job        : ${SLURM_JOB_ID:-local}"
echo "== host       : $(hostname)"
echo "== python     : $PY"
echo "== started    : $(date -Is)"
echo "== diagnostics: $DIAGS"
echo

rc=0
for d in $DIAGS; do
    case "$d" in
        *.py) script="$DIAG_DIR/$(basename "$d")" ;;
        *)    script="$DIAG_DIR/${d}.py" ;;
    esac

    if [ ! -f "$script" ]; then
        echo "!! SKIP missing script: $script"
        rc=1
        continue
    fi

    stem="$(basename "$script" .py)"
    echo "------------------------------------------------------------"
    echo ">> $stem  ($(date -Is))"
    echo "------------------------------------------------------------"
    log="$LOG_DIR/${stem}.log"
    : > "$log"
    if ( cd "$DIAG_DIR" && "$PY" "$script" ) >> "$log" 2>&1; then
        # mirror to stdout so the .out file carries the same record
        cat "$log"
        echo ">> OK   $stem  ($(date -Is))"
    else
        cat "$log"
        echo ">> FAIL $stem  exit=$?  ($(date -Is))"
        rc=1
    fi
    echo
done

echo "== finished   : $(date -Is)"
echo "== results    : $DIAG_DIR/results"
ls -la "$DIAG_DIR/results" 2>/dev/null | tail -n 25

exit "$rc"
