#!/usr/bin/env bash
# Local CPU smoke-train (stage 6c): proves the whole train loop end-to-end on a
# tiny subset before spending a GPU slot on codon. Takes ~1 min on CPU.
#
# Why a dedicated venv: the [training] extra pins a modern torch that has NO
# macOS x86_64 (Intel) wheel — so on an Intel Mac we install the last
# Intel-compatible stack (torch 2.2.2 / transformers 4.44) in an isolated venv.
# On the GPU node use the real path instead:
#     uv run --extra training python -m litrex.training.train --smoke
#
# Prereq: splits built  ->  uv run python -m litrex.training.dataset
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".venv-smoke"                      # gitignored
HF_HOME="${HF_HOME:-$PWD/.hf_cache}"    # cache the model locally
export HF_HOME TOKENIZERS_PARALLELISM=false

if [ ! -x "$VENV/bin/python" ]; then
  echo ">> creating pinned smoke venv ($VENV)"
  uv venv "$VENV" --python 3.11
  uv pip install --python "$VENV" \
    "torch==2.2.2" "transformers==4.44.2" datasets accelerate \
    scikit-learn pandas pyarrow "numpy<2"
fi

echo ">> running smoke-train (100 rows/split, 1 epoch, CPU)"
PYTHONPATH=src "$VENV/bin/python" -m litrex.training.train --smoke "$@"
echo ">> done -> models/stage6_smoke/{model,metrics.json,model_card.json}"
