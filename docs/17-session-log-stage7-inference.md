# 17 — Session log: stage 7 batch inference

Implements `litrex.inference.batch_score` (docs/07): score the stage-6 model over
a Cooccurrence corpus, matching training-time input construction exactly.

## What was built

- **`RelationScorer`** — loads model + tokenizer once (per process / Spark
  executor), scores in GPU batches, returns predicted class + softmax
  probabilities. `device` auto-detects CUDA.
- **`build_inputs(df, resolve=)`** — rebuilds the marked input
  (`[TGT] name [/TGT] [DIS] name [/DIS] text`) via the *same*
  `training.dataset.build_input_text` + `entity_names` resolution used for the
  fit, so inference == training. `resolve=False` for pre-resolved names.
- **`score_corpus(input, output, model)`** — standalone CLI path (runs on codon):
  read a Cooccurrence parquet (file or dir) → write a **ScoredRelationship**
  parquet: contract columns (target, disease, text, publication_id,
  publication_date, data_source) + `relation`, `confidence`, per-class
  `prob_<class>`, and `model_version` (from the model card, e.g.
  `stage6a-embedding-prototype-v1+weight-sqrt`).
- **`score_partition(text, target, disease)`** — `pandas_udf`-shaped wrapper with
  a process-global scorer (load-once-per-executor) for the upstream PySpark job
  (docs/07). Assumes names pre-resolved upstream (no per-partition network).

## Verified

Torch-free helpers unit-tested (`build_inputs`, `model_version`). Full path
smoke-scored locally (pinned CPU venv + the stage-6 smoke model) on 20 rows of
`sample_manifest.parquet`: loads model, resolves names from cache, writes the
ScoredRelationship parquet with correct schema + label distribution.

## The corpus caveat (important)

The **full merged OT+GWAS pool was deleted in stage 4** (only the 2,374-row
sample survived), and codon has only the splits. To score the *full* corpus it
must be **regenerated**: re-run the OT-EPMC + GWAS ingest → `merge_sources` →
`data/processed/merged/`, then point `batch_score` at that directory. The true
billions-row `Cooccurrence` set lives upstream in Open Targets' PySpark pipeline
(docs/07) — out of scope locally; that's what the `score_partition` UDF is for.

## Next

- Regenerate the merged corpus and run `score_corpus` over it on the A100.
- Compare the scored label distribution against the training eval distribution to
  catch drift / integration bugs (docs/07 step 3).
