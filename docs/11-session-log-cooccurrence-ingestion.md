# 11 — Session Log: Cooccurrence Ingestion (Stage 2)

**Date:** 2026-07-09
**Scope:** Implemented and ran stage 2 (docs/02) end-to-end against the real
Open Targets Cooccurrence release. This resolves the "exact upstream
Cooccurrence source" item in [10-open-questions.md](10-open-questions.md).

## What was achieved

- **Resolved the upstream source.** Confirmed release, path, and schema:
  `gs://open-targets-pipeline-runs/ds/26.06.0-dev2/intermediate/literature/cooccurrence`
  — 40 flat `part-NNNNN-*.snappy.parquet` files, no Hive partitioning,
  ~11GB total, Spark/Parquet, verified readable with plain pyarrow (no
  Spark cluster needed).
- **Decided download vs. server-side subsetting**: downloaded the full
  dataset directly (11GB is small enough; there's no partitioning to
  exploit for a cheaper server-side filter, and stage 2's job is to ingest
  the full dataset anyway — sampling is stage 4).
- **Implemented `src/litrex/data_sources/cooccurrence.py`:**
  - `download()` — pyarrow's native `GcsFileSystem` (no `gcsfs`/`gsutil`
    dependency needed), resumable (skips files already present locally
    with a matching size).
  - `to_cooccurrence()` — real column mapping, filtering defensively to
    `type1='GP'`/`type2='DS'`/`isMapped=True` rows (100% of sampled rows
    matched this, but a future release could mix in other entity-pair
    types).
  - `ingest()` — orchestrates raw → mapped parquet, one output file per
    source file.
  - CLI (`python -m litrex.data_sources.cooccurrence`) with
    `--skip-download` to re-run just the transform against already-downloaded
    raw files.
  - Tests in `tests/data_sources/test_cooccurrence.py` (11 passing).
- **Ran it for real**: `data/raw/cooccurrence/` (11GB, gitignored) and
  `data/processed/cooccurrence/` (7.5GB, gitignored) — **103,169,784 rows**,
  spot-checked against the `Cooccurrence` pydantic model.
- **Added a `text_granularity` column** (`sentence` vs `chunk`) to flag rows
  where the `text` span is more than one sentence — caused by unstripped
  HTML tags from structured abstracts (e.g. `<h4>Conclusions</h4>`) or
  otherwise-bundled multi-sentence spans. Result: **83.83% sentence /
  16.17% chunk**. The classifier is a plain regex heuristic (tag detection
  + punctuation-boundary split), not a real sentence tokenizer — see
  caveats below.
- **Added extra columns beyond the core contract**: `evidence_score`
  (from `evidenceScore`), `target_start`/`target_end`/`disease_start`/`disease_end`
  (entity character offsets within `text`, renamed from raw `start1/end1/start2/end2`
  to match the `target`/`disease` naming already used elsewhere).

## Key design decision: extra columns vs. the shared contract

`schema.py`'s `Cooccurrence` model is the **fixed interface** the delegated
GWAS Catalog work (stage 3) is being built against — adding required fields
there would break that contract. All the new fields above
(`text_granularity`, `evidence_score`, `target_start`, `target_end`,
`disease_start`, `disease_end`) were added as **extra output columns only**,
not added to the pydantic model. Pydantic v2's default `extra='ignore'`
means `Cooccurrence(**row)` silently drops them — verified this behavior
before relying on it. GWAS Catalog rows won't have these columns and
downstream code that validates through `Cooccurrence` won't see them either;
anything that wants them needs to read the Parquet columns directly.

## Points worth taking forward

- **`text_granularity` is approximate, not exact.** Arrow's regex engine
  (RE2) has no lookaround, so the sentence-boundary heuristic is a blunt
  `[.!?]+\s+` split — it overcounts on abbreviations ("Dr. Smith", "et al.").
  The real "genuinely multi-sentence" rate is likely lower than 16.17%. If
  stage 4/5 needs a tighter number, swap in a real sentence tokenizer
  (`pysbd` or `nltk` punkt) — not currently a dependency.
- **`pmcid` was not added**, despite docs/02 flagging it as needed for
  stage 8's "found in other datasources" cross-reference. Only `pmid` is
  currently mapped to `publication_id`. Worth adding as another extra
  column when stage 8 work starts.
- **`label1`/`label2`** (raw surface-form entity mentions, e.g. "HLF" vs.
  the canonical `mappedId1`) were considered but not added — lower
  priority, useful mainly for QA-ing the entity-normalization mapping.
- **No date-based partitioning.** docs/02 suggested partitioning by
  `publication_date` year "or at least ensure it's a filterable column."
  Went with the latter — output files mirror the raw `part-NNNNN` layout,
  and `publication_date` is a plain column with parquet row-group stats for
  predicate pushdown, but there's no directory-level year partitioning.
  Revisit if stage 4's date-range filter turns out to be slow at 103M rows.
- **Exact duplicate rows exist in the raw data** (same `pmid`, `text`, and
  entity pair appearing twice within a file) — observed during initial
  schema exploration, not deduplicated in `to_cooccurrence()`. Flag for
  stage 4 (sampling) to consider, since duplicates could skew coverage
  metrics.
- **`data/` is gitignored** (raw + processed, ~18.5GB combined). Any future
  session needs to re-run `python -m litrex.data_sources.cooccurrence`
  (or `--skip-download` if `data/raw/cooccurrence/` still exists locally)
  to regenerate it — nothing under `data/` is committed.
- **`evidence_score` is now available** but not yet used anywhere — it's a
  natural input to stage 8's "evidence score formula" (still an open
  question in docs/10) once that stage starts.

## Backgrounding gotcha (process note, not a design issue)

Early in the session, a background download command was structured as
`cmd_a && python long_running_job & && echo done` with the Bash tool's own
`run_in_background: true` — the outer wrapper reported "completed" as soon
as `echo` ran (near-instantly), not when the download actually finished.
The download was still correctly running, just unmonitored/orphaned from
the tool's perspective. Caught it by checking `ps aux` for the pid and
re-attached a proper monitor (`until ! kill -0 $pid; do sleep 10; done`).
Lesson: don't nest a shell `&` inside a Bash tool call that's already
`run_in_background: true` — pick one backgrounding mechanism, not both.
