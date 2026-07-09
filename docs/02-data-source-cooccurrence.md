# 02 — Data Source: Open Targets Cooccurrence

**Owner:** main track (this repo, built first).

## Goal

Produce `Cooccurrence` rows from the Open Targets Cooccurrence dataset,
already ID-normalized, ready to feed into sampling (stage 4).

## Input

Open Targets Cooccurrence dataset (upstream, produced by Open Targets'
PySpark pipelines). Already contains:

- target, normalized to Ensembl gene ID
- disease, normalized to EFO ID
- literature text span where the pair co-occurs
- publication metadata: publication date, section of the paper the text
  came from (needed for stage 4's two-year/section filter)
- (likely) PMID/PMCID or similar publication identifier — needed later for
  the "found in other datasources" cross-reference in stage 8

Resolved: `gs://open-targets-pipeline-runs/ds/26.06.0-dev2/intermediate/literature/cooccurrence`
— 40 flat Parquet part-files (no Hive partitioning), ~11GB. See
[11-session-log-cooccurrence-ingestion.md](11-session-log-cooccurrence-ingestion.md)
for the implementation and what's been run.

## Output contract

Parquet file(s) conforming to:

```
Cooccurrence:
  target:           str   # Ensembl gene ID
  disease:          str   # EFO ID
  text:             str   # literature text span
  publication_id:   str   # PMID/PMCID or equivalent
  publication_date: date
  section:          str   # e.g. abstract, title, results
```

This is a superset of the core `target/disease/text` contract from the
README — the extra fields (`publication_id`, `publication_date`, `section`)
are required by stage 4 (sampling) and stage 8 (cross-datasource flag), so
they're part of the contract every source must eventually supply.

## Steps

1. Identify the exact upstream Cooccurrence release to read from (path,
   version, access method — Spark/Parquet read).
2. Read with PySpark (or plain Arrow/Parquet reader — no PySpark cluster
   needed for prototyping) and select/rename columns to the contract above.
3. Write out as Parquet, partitioned in a way that supports stage 4's
   date-range and section filters efficiently (e.g. partition by
   `publication_date` year, or at least ensure it's a filterable column).
4. Validate: row count, null checks on `target`/`disease`/`text`, spot-check
   a handful of rows against the source.

## Output

A Parquet dataset of `Cooccurrence` rows (full dataset, not yet sampled —
sampling happens in stage 4), readable by both plain Python/Arrow tooling
and PySpark.
