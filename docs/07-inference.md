# 07 — Scalable Batch Inference

## Goal

Run the trained classifier (stage 6) over the **full** billions-row
`Cooccurrence` dataset — this is the one stage that must operate at full
scale, not on a sample.

## Input

- Trained classifier + label mapping + model card (stage 6).
- Full `Cooccurrence` dataset (stages 2 + 3 combined, unsampled — this is
  the big one, produced upstream in PySpark).

## PySpark compatibility requirement

This is the stage the project's "PySpark-compatible" constraint bites
hardest:

- The classifier's inference function must be wrappable as a **pandas UDF**
  (`pandas_udf` / Arrow-based Spark UDF) so it can run as a column
  transform inside the upstream PySpark job, batched per-partition rather
  than row-by-row.
- Model loading must work per-executor (broadcast the model or load once
  per worker process, not once per row).
- No pandas-only assumptions bleeding into this function — inputs/outputs
  should be Arrow/pandas Series that Spark can serialize back and forth.

## Steps

1. Wrap the trained model + tokenizer in a scoring function with signature
   suitable for `pandas_udf` (input: Series of text/target/disease columns,
   output: Series of relation label + confidence).
2. Batch inference within the UDF (don't score one row at a time inside the
   partition — batch to use the GPU/CPU efficiently, if applicable).
3. Validate correctness first on a **larger pyspark sample** (bigger than
   the labelling sample, but not the full billions-row set) — compare
   output distribution against the training-time eval to catch drift or
   integration bugs before running at full scale.
4. Run at full scale as a column-add step in the upstream PySpark pipeline
   (or a standalone Spark job reading the full `Cooccurrence` Parquet and
   writing out scored rows).
5. Monitor: throughput, any rows that fail to score (and why), output label
   distribution vs. the sample-scale validation run.

## Output contract

```
ScoredRelationship:
  target:           str
  disease:          str
  text:             str
  relation:         str    # from the fixed label set of the deployed model version
  confidence:       float
  publication_id:   str
  publication_date: date
  model_version:    str    # ties back to the model card from stage 6
```

## Output

Scored relationships over the full dataset, at whatever storage layer the
upstream Open Targets pipeline expects (Parquet, likely landing back into
the same kind of storage the input Cooccurrence dataset came from). This is
the input to [08-product-vision.md](08-product-vision.md).
