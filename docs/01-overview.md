# 01 — Overview & Architecture

## Problem

Given literature evidence that a **target** and a **disease** co-occur in a
piece of text, determine the *relationship* being expressed between them
(e.g. does the text say the target's upregulation is associated with the
disease? Is there no real relationship, just a co-mention?).

This is currently unclassified in the Open Targets Platform. Adding relation
classification unlocks better evidence scoring and a richer front-end
presentation (see [08-product-vision.md](08-product-vision.md)).

## Relation taxonomy (starting hypothesis, expected to expand)

- positive — upregulation
- positive — downregulation
- negative
- neutral

This is **not** a fixed closed set. The LLM labelling step (stage 5) is
allowed to emit novel relation labels beyond this list — the taxonomy is
revised after seeing real output, not hard-coded upfront.

## Architecture

```
[Data sources]
  Open Targets Cooccurrence (already ID-normalized)  ─┐
  GWAS Catalog (needs OnToma normalization)           ─┼─► Cooccurrence(target, disease, text)
  [Expression Atlas — dropped from scope for now]     ─┘
        │
        ▼
[Stage 4] Representative sampling
        │   two-year abstract window, ≥10% disease/target coverage,
        │   ontology-tree spread
        ▼
Sample of Cooccurrence rows
        │
        ▼
[Stage 5] LLM relationship judge (Claude / Anthropic API)
        │   prompt: "In TEXT, what is the relationship between
        │            TARGET and DISEASE?"
        │   output: relation label (open vocab) + confidence
        ▼
Silver-labelled triples: (target, disease, text, relation, confidence)
        │
        ▼
[Stage 6] Fine-tune transformer classifier (PubMedBERT/BioBERT candidate)
        │
        ▼
Trained relation classifier
        │
        ▼
[Stage 7] Scalable batch inference (pandas_udf, pyspark-compatible)
        │   runs over the FULL billions-row dataset
        ▼
Scored relationships: (target, disease, text, relation, confidence) at scale
        │
        ▼
[Stage 8] Downstream product (light plan, revisit later)
    front-end relation breakdown, co-mention stats, evidence-score revision
```

## Key constraints

1. **Language/stack**: Python, `src/` layout, `uv` for dependency management,
   `pytest` for testing.
2. **PySpark-compatible**: this project doesn't need to *use* PySpark itself,
   but schemas/formats and the final inference step must interoperate with
   PySpark DataFrames (Parquet/Arrow interchange, pandas UDFs — no
   pandas-only assumptions in the inference path).
3. **v1 = quick prototype**, but structured enough to evolve into production.
   Don't over-engineer, but don't paint into a corner (e.g. hard-coding the
   4-item taxonomy would be painting into a corner).
4. **Scale**: full dataset is billions of rows. Only stage 7 (inference) needs
   to run at that scale. Stages 4–6 (sampling, labelling, training) operate
   on a small sample by design.

## Non-goals for v1

- Expression Atlas as a data source (dropped from scope).
- A fully-built front-end (stage 8 is a brief plan only, to be revisited).
- A final, shipped evidence-scoring algorithm (direction only, see doc 8).
- Locking the relation taxonomy to the 4 starting categories.
