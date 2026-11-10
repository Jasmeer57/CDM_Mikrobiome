#!/bin/bash
# Build an isolated CPU venv for the NER variants that the vllm venv lacks:
#   * en_ner_bionlp13cg_md  (5th sciSpaCy NER model — Cell 7)
#   * HunFlair2             (flair SequenceTagger — Cell 6)
#
# Rationale (AGENTS.md "Python envs"): no microbiome-cdm-env conda env exists on
# this cluster, and venvs/vllm has neither spacy nor flair. A separate venv keeps
# the numpy<2 / spacy 3.7 pin from colliding with the torch 2.13 / transformers 5.x
# stack that the BERT-variant job uses.
#
# NOTE ON PINS: requirements.lock's torch==2.1.1+cpu and scipy==1.10.1 have no
# cp312 wheels (they predate Python 3.12). This script therefore pins the nearest
# cp312-compatible releases instead and flags the divergence in the run manifest.
# scispacy itself is NOT installed: the notebooks only use it for the UMLS linker
# (cui/score), which the section CSV schema does not carry. The NER model package
# is installed directly from the AllenAI release bucket with --no-deps.
#
# Usage:  bash src/scripts/setup_ner_variants_venv.sh
# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -uo pipefail

REPO="$CDM_ROOT"
VENV="$HOME/venvs/ner_variants"
PY="$VENV/bin/python"
export TMPDIR=/tmp
export PIP_DISABLE_PIP_VERSION_CHECK=1

if [ "${REBUILD:-0}" = "1" ] && [ -d "$VENV" ]; then
    echo "=== rebuilding: removing $VENV ==="
    rm -rf "$VENV"
fi

echo "=== [1/6] base venv ==="
if [ ! -x "$PY" ]; then
    /home/jkalra_hpc/venvs/vllm/bin/python -m venv "$VENV" || exit 1
fi
"$PY" -V

echo "=== [2/6] pip / setuptools / wheel ==="
"$PY" -m pip install -q --upgrade pip setuptools wheel 2>&1 | tail -3

echo "=== [3/6] numpy 1.26 + torch CPU (cp312-compatible pin) ==="
"$PY" -m pip install -q "numpy==1.26.4" 2>&1 | tail -3
"$PY" -m pip install -q "torch==2.2.2+cpu" --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -3

echo "=== [4/6] spacy 3.7.5 ==="
"$PY" -m pip install -q "spacy==3.7.5" 2>&1 | tail -5

echo "=== [5/6] en_ner_bionlp13cg_md (scispaCy model, --no-deps) ==="
"$PY" -m pip install -q --no-deps \
  "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bionlp13cg_md-0.5.4.tar.gz" 2>&1 | tail -5

echo "=== [6/6] flair 0.13.1 ==="
"$PY" -m pip install -q "flair==0.13.1" 2>&1 | tail -5

echo "=== [7/7] re-pin numpy<2 (torch/flair pull numpy 2.x) ==="
"$PY" -m pip install -q "numpy==1.26.4" 2>&1 | tail -5

echo "=== verify ==="
"$PY" - <<'EOF'
import importlib
for m in ("spacy", "flair", "torch", "numpy"):
    try:
        mod = importlib.import_module(m)
        print(m, getattr(mod, "__version__", "?"))
    except Exception as e:
        print(m, "FAILED", repr(e)[:200])
try:
    import spacy
    nlp = spacy.load("en_ner_bionlp13cg_md")
    print("en_ner_bionlp13cg_md loaded; labels:", sorted(nlp.get_pipe("ner").labels))
except Exception as e:
    print("bionlp13cg FAILED", repr(e)[:300])
EOF

echo "=== done: $VENV ==="
