#!/bin/bash
# Submit the whole GPU gap chain (docs/gpu_gap_plan.md) with afterok dependencies.
# Account limit respected: <= 8 A40 tasks and <= 4 A100 tasks at a time (array %throttles).
# Run from the repo root.
set -euo pipefail
S=src/scripts/vllm_termpop
GPU=$S/gap_gpu.sbatch; CPU=$S/gap_cpu.sbatch
A40="-p mlgpu_medium --gres=gpu:a40:1"
A100="-p sgpu_short --gres=gpu:a100:1"
sub() { sbatch --parsable "$@"; }

# ── chain A: catalogue (A40 x8) ──────────────────────────────────────────────
G2=$(STAGE=G2 NSHARDS=1 sub -J gap-G2 $A40 --array=0 $GPU)
G1=$(STAGE=G1 NSHARDS=7 sub -J gap-G1 $A40 --array=0-6%7 $GPU)
AP1=$(STEP=apply_G1 sub -J gap-apply-G1 --dependency=afterok:$G1:$G2 $CPU)
G3=$(STAGE=G3 NSHARDS=8 sub -J gap-G3 $A40 --array=0-7%8 --dependency=afterok:$AP1 $GPU)
G3B=$(STAGE=G3B NSHARDS=4 sub -J gap-G3B $A40 --array=0-3%4 --dependency=afterok:$G3 $GPU)
AP3=$(STEP=apply_G3 sub -J gap-apply-G3 --dependency=afterok:$G3B $CPU)

# ── chain B: CDM / terminology (A100 x4) ─────────────────────────────────────
G5=$(STAGE=G5 NSHARDS=1 sub -J gap-G5 $A100 --array=0 $GPU)
G8=$(STAGE=G8 NSHARDS=3 sub -J gap-G8 $A100 --array=0-2%3 $GPU)
# E (embedding candidates) ran already if outputs/results/gap_runs/E/g7_candidates.jsonl exists
if [ -s outputs/results/gap_runs/E/g7_candidates.jsonl ]; then EDEP=""; E=done; else
  E=$(KIND=embed sub -J gap-E $A100 $GPU); EDEP="--dependency=afterok:$E"; fi
G9=$(STAGE=G9 NSHARDS=3 sub -J gap-G9 $A100 --array=0-2%3 --dependency=afterany:$G8 $GPU)
G6=$(STAGE=G6 NSHARDS=1 sub -J gap-G6 $A100 --array=0 $EDEP --dependency=afterany:$G5 $GPU)
G7=$(STAGE=G7 NSHARDS=2 sub -J gap-G7 $A100 --array=0-1%2 $EDEP --dependency=afterany:$G5 $GPU)
AP8=$(STEP=apply_G8 sub -J gap-apply-G8 --dependency=afterok:$G8 $CPU)
AP9=$(STEP=apply_G9 sub -J gap-apply-G9 --dependency=afterok:$G9 $CPU)
AP6=$(STEP=apply_G6 sub -J gap-apply-G6 --dependency=afterok:$G6 $CPU)
AP7=$(STEP=apply_G7 sub -J gap-apply-G7 --dependency=afterok:$G7 $CPU)

# ── join: relink (A100) -> finalize v3.1 -> full judge (A40 x8) ──────────────
G4=$(KIND=link STAGE=G4 sub -J gap-G4 $A100 --dependency=afterok:$AP3 $GPU)
FIN=$(STEP=finalize31 G10_PARTS=8 sub -J gap-finalize31 --dependency=afterok:$G4:$G5 $CPU)
G10=$(KIND=judge STAGE=G10 sub -J gap-G10 $A40 --array=0-7%8 --dependency=afterok:$FIN $GPU)
M10=$(STEP=g10merge sub -J gap-merge-G10 --dependency=afterok:$G10 $CPU)

cat <<IDS | tee outputs/logs/gap/chain_jobs.txt
chain A: G2=$G2 G1=$G1 apply_G1=$AP1 G3=$G3 G3B=$G3B apply_G3=$AP3
chain B: G5=$G5 G8=$G8 E=$E G9=$G9 G6=$G6 G7=$G7 apply: G8=$AP8 G9=$AP9 G6=$AP6 G7=$AP7
join:    G4=$G4 finalize31=$FIN G10=$G10 merge_G10=$M10
IDS
