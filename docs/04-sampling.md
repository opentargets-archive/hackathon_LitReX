# 04 — Representative Sampling

## Goal

Draw a sample of `Cooccurrence` rows for the LLM labelling step (stage 5)
that is small enough to be cheap to label, but representative enough of the
full platform that a classifier trained on it will generalize.

## Input

Combined `Cooccurrence` output from stages 2 and 3 (Open Targets Cooccurrence
+ GWAS Catalog, once both are available — v1 can proceed with Cooccurrence
alone and fold in GWAS Catalog rows once stage 3 lands).

## Filters

1. **Time window**: restrict to the most recent two years of abstracts
   (filter on `publication_date`).
2. **Section filter**: restrict to specific paper section(s) (e.g. abstract)
   — exact section value(s) to include is an implementation decision to
   confirm once real `section` values are seen in the data.

## Representativeness metrics (must hold on the final sample)

1. **Disease coverage** ≥ 10% of total diseases in the platform.
2. **Target coverage** ≥ 10% of total targets in the platform.
3. **Ontology spread**: reasonably spread across the disease ontology tree
   (not clustered in one branch) — needs a concrete metric, e.g. distribution
   across top-level EFO therapeutic area nodes, checked for reasonable
   spread rather than a single hard threshold.

Platform totals (denominator for the coverage checks) will be supplied
directly by the user rather than sourced programmatically — treat as a
provided constant/config value per run, not something this pipeline needs to
compute itself.

## Steps

1. Apply time window + section filters to the combined `Cooccurrence` data.
2. Compute disease/target coverage and ontology-tree spread on the filtered
   set.
3. If coverage thresholds aren't met by the filtered set as-is, adjust
   sampling (e.g. stratified sampling to boost under-represented
   diseases/targets/ontology branches) rather than just widening the time
   window, since the two-year window is a fixed requirement.
4. Draw the final sample and write it out with the metrics that justify it
   (coverage %, ontology spread stats) attached as run metadata, so the
   sample's representativeness is auditable later.

## Output

`sample_manifest.parquet` — the sampled `Cooccurrence` rows to be sent to
the LLM labelling step, plus a small metadata record (JSON or a companion
file) capturing:

- total sample size
- % of platform diseases covered
- % of platform targets covered
- ontology spread summary
- filters applied (date range, sections)

This manifest is the input to [05-llm-labelling.md](05-llm-labelling.md).
