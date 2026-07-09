# 16 — Session Log: Stage 6 Classifier Training (design + build)

**Date:** 2026-07-09
**Scope:** Fine-tune a biomedical transformer on the stage-5 silver labels
(docs/06). Live-updating log; decisions first, then build/run notes.

## Decisions (user-confirmed)

1. **Taxonomy = derived, not assumed.** Stage 5 produced free-text `relation`
   descriptions (2,373 of 2,374 unique), so the first step is to **derive a
   closed taxonomy**: embed the relation texts, cluster them, and have an LLM
   name/organise the clusters into ~5–7 classes. This "closes" the label set for
   this model version while the upstream judge stays open-vocab (docs/06 step 2).
2. **Base model: PubMedBERT** (`microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext`,
   already the stub's `BASE_MODEL`) with **typed entity markers** — the stage-5
   `[[...]]` spans become `[TGT]…[/TGT]` / `[DIS]…[/DIS]` so the model knows which
   mention pair to judge.
3. **Evaluation: stratified + grouped 80/10/10 fixed test, plus stratified
   5-fold CV** for robust minority-class metrics (small data). Report macro-F1,
   per-class F1, confusion matrix, and calibration vs the stage-5 confidence.
4. **Confidence use: filter + weight.** Drop the ~117 rows with confidence < 0.3,
   and weight each example's training loss by its stage-5 confidence.
5. **Runs on SLURM/GPU.** Fine-tuning is GPU-bound (unlike stage 5). Single GPU
   is plenty for ~2.3k rows. **Offline gotcha:** codon compute nodes may lack
   internet — pre-download PubMedBERT on a login node and set
   `HF_HOME`/`TRANSFORMERS_OFFLINE=1`.

## Label / leakage structure (from the labelled set)

- Natural classes (heuristic): co-mention/no-relationship 785 (33%, mean conf
  0.58), association 432, positive-up 340, positive-down 165, causal 159,
  "other" 486, negative **7** (too small — will merge). Heavy imbalance → macro-F1
  + class weights.
- Leakage risk is **low**: 1.1 rows/PMID (only 92 PMIDs have >1 row), 2,159/2,374
  target–disease pairs unique. So partitioning = **stratify by class + balance
  `data_source` (OT/GWAS) + group by `publication_id`** (`StratifiedGroupKFold`).

## Planned module layout (`src/litrex/training/`)

- `taxonomy.py` (new) — derive the closed taxonomy (embed → cluster → LLM-name),
  write `taxonomy.json` + a `relation_class` column onto the labelled set.
- `dataset.py` (fill stub) — entity markers, confidence filter, stratified+grouped
  splits (80/10/10 + CV folds).
- `train.py` (fill stub) — PubMedBERT + HF `Trainer`, confidence-weighted loss,
  metrics.
- `scripts/` — a SLURM job script (`--gres=gpu:1`, offline HF cache) for codon.

## Build / run notes

### Taxonomy (stage 6a) — `training/taxonomy.py`

Cluster-then-LLM-name (the chosen method) was tried twice (k=12, k=24) and
**failed to separate direction**: KMeans clusters don't align with the
up/down/association axes, so whole-cluster→class mapping collapsed opposite
directions into one muddy "positive_directional_effect" bucket and left
`downregulation`/`negative_finding` empty. **Switched to embedding
nearest-prototype**: a fixed docs/01-aligned taxonomy (5 classes with rich
prototype definitions), each stage-5 relation embedded (OpenAI
`text-embedding-3-small`) and assigned to its nearest class by cosine. This is
still an embedding method, deterministic, free per row, and it separates the
classes cleanly. A `class_margin` (top-1 minus top-2 cosine) is stored per row.

Result on the 2,374-row set (`labeled_triples_classified.parquet` + `taxonomy.json`):

| class | rows | GWAS | OT |
|---|--:|--:|--:|
| no_relationship | 1,222 (51%) | 139 | 1,083 |
| association | 410 (17%) | 222 | 188 |
| downregulation | 301 (13%) | 6 | 295 |
| upregulation | 289 (12%) | 0 | 289 |
| negative_finding | 152 (6%) | 7 | 145 |

Coherent by source: **GWAS → association + no_relationship** (association-flavoured
"locus associated with trait"), **OT → the directional/mechanistic classes**.
Caveat: mean `class_margin` is 0.056 — embedding classification is soft, so
borderline rows are approximate; the margin lets us down-weight/review them, and
an LLM per-row pass is a possible v2 upgrade if the taxonomy needs to be crisper.

### Dataset (stage 6b) — `training/dataset.py`

Built + run locally (names cached from stage 5). Filters confidence < 0.3
(2,374 → 2,257), marks input as `[TGT] {gene} [/TGT] [DIS] {disease} [/DIS]
{text}`, adds `sample_weight = confidence` and inverse-frequency `class_weights`,
and writes grouped+stratified 80/10/10 splits + a 5-fold `cv_fold` column.

Result (`data/processed/splits/`): **train 1,805 / val 226 / test 226**, class
balance preserved in every split (e.g. no_relationship 890/111/112), **no PMID
crosses splits**. class_weights up-weight the rare classes (negative_finding
2.97) and down-weight no_relationship (0.41).

### Training (stage 6c) — `training/train.py` + `scripts/train_stage6.slurm`

PubMedBERT (`BiomedBERT-base-uncased-abstract-fulltext`) sequence classifier;
entity markers added as special tokens (`resize_token_embeddings`); a
`WeightedTrainer` applies class-weighted **and** per-sample confidence-weighted
cross-entropy; eval = macro/weighted/per-class F1 + confusion matrix; saves
model + `metrics.json` + `model_card.json`. Heavy deps are lazy-imported so the
module imports without torch; the metric helper is unit-tested. **Runs on codon
GPU** via the SLURM script (offline HF cache pre-downloaded on a login node,
`--gres=gpu:1`). 76 tests pass, ruff clean.

### Pending (on the GPU node)

- Run `scripts/train_stage6.slurm`; record test macro-F1 / per-class F1 /
  confusion matrix + the model card here.
