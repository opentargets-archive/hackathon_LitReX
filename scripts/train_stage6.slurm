#!/bin/bash
# Stage 6 (docs/06) — fine-tune PubMedBERT on the silver labels, on codon GPU.
#
# Prereqs (run ONCE on a login node, which has internet — compute nodes may not):
#   1) build the splits:   python -m litrex.training.dataset
#   2) pre-download the base model into the HF cache (offline on the node):
#        export HF_HOME="$PWD/.hf_cache"
#        uv run --extra training python - <<'PY'
#        from transformers import AutoTokenizer, AutoModelForSequenceClassification
#        m="microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext"
#        AutoTokenizer.from_pretrained(m); AutoModelForSequenceClassification.from_pretrained(m, num_labels=5)
#        PY
#   3) submit:  sbatch scripts/train_stage6.slurm
#
# CONFIRM for your cluster: the GPU partition name (--partition) and that
# `uv --extra training` installs a torch build matching the node's CUDA.

#SBATCH --job-name=litrex-stage6
#SBATCH --partition=gpu            # <-- confirm codon's GPU partition name
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --mail-type=FAIL
#SBATCH --mail-user=soria@ebi.ac.uk
#SBATCH --output=logs/stage6_%j.out
#SBATCH --error=logs/stage6_%j.err

set -euo pipefail
mkdir -p logs

# Use the model pre-downloaded into the HF cache on the login node; stay offline.
export HF_HOME="${HF_HOME:-$PWD/.hf_cache}"
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

echo "node: $(hostname) | gpu: ${CUDA_VISIBLE_DEVICES:-none}"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

uv run --extra training python -m litrex.training.train \
  --data-dir data/processed/splits \
  --output-dir models/stage6 \
  --epochs 4 --batch-size 16 --lr 2e-5

echo "done — model + metrics + model_card in models/stage6/"
