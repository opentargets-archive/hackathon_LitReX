# 15 — Data Volume by Pipeline Stage

Row counts observed (or targeted) at each stage of the pipeline, plus a
smaller-scale column for a quick end-to-end prototype run. See
[01-overview.md](01-overview.md) for the pipeline diagram these stages refer
to.

**Superseded numbers, 2026-07-09:** stages 2–4 were re-run on `main` after
this doc's first draft (PR #7/#8, see
[14-session-log-ot-epmc-merge.md](14-session-log-ot-epmc-merge.md)) — new FTP
ingestion path, a GWAS title corpus, and OT+GWAS merged into one pool before
sampling. The "Current row count" column below reflects that newer run, not
the original docs/11–13 session logs.

| Stage | Current row count | Notes | Small-scale target |
|---|---|---|---|
| 2. Cooccurrence ingestion | **2,354,558 rows** (abstract 2,068,134 / title 286,424) | New public-FTP ingestion path (`evidence_europepmc`, exploded from nested `textMiningSentences`), filtered to the 2-year window + `section in (abstract, title)` **during ingest** — so this is already a filtered figure, not a full raw dump. Supersedes the old 103,169,784-row GCS-based ingest (docs/11), which read a different, unfiltered intermediate dataset — [session log](14-session-log-ot-epmc-merge.md) | 2,354,558 rows (unchanged — this is raw ingested data, not scaled down) |
| 3. GWAS Catalog | **431 rows** (423 abstract + 8 title) | GWAS rebuild added a title corpus (from the Catalog's `STUDY` column, no fetch) to balance OT's abstract+title sections; `--source both` now means abstract+title (the earlier full-text path, 2,552 rows, is not part of this balanced rebuild). 57 of the 431 rows are exact-duplicate co-occurrences, collapsed to 374 unique during the stage-4 draw — [session log](14-session-log-ot-epmc-merge.md) | 431 rows (423 abstract + 8 title — all rows taken forward, matches current exactly since GWAS Catalog is already small) |
| 4. Sampling — candidate pool | **2,354,989 rows** | OT (2,354,558) + GWAS (431) merged into one uniform 12-column pool (`merge_sources()`) before sampling — GWAS is now folded into the candidate pool rather than sampled separately. Supersedes the earlier 2,565,787-row OT-only candidate pool (docs/12) | 2,354,989 rows (unchanged) |
| 4. Sampling — drawn sample | **2,374 rows** = 2,000 `open_targets` + 374 `gwas_catalog` | A plain uniform draw from the merged pool is ~100% OT (GWAS is only 0.018% of it), so `draw_sample` gained `--include-all-source`: GWAS rows are taken in full (all 374 unique), OT is downsampled to 2,000 (~5:1 ratio). Disease coverage 1.24% (586/47,080), target coverage 1.73% (1,359/78,691). Supersedes the earlier 500-row OT-only draw (docs/12) | 2,374 rows (same as current — the real `--include-all-source` draw already **is** the small-scale target: all 374 unique GWAS rows + 2,000 downsampled OT rows) |
| 5. LLM labelling | — not yet run | The 2,374-row merged manifest (`data/processed/sample_manifest.parquet`) is ready for labelling but hasn't been judged yet; the earlier 500-row pass (docs/13) was against the old OT-only sample and is now stale. Run instructions and cost estimate (~40–120 min sequential, or `--batch` for the Anthropic Batch API) are in the [session log](14-session-log-ot-epmc-merge.md) | 2,374 rows (labels the stage-4 manifest as-is — GWAS is already included via `--include-all-source`, so it isn't added again on top) |
| 6. Classifier training | — | Not started | 2,374 rows (train/eval split of the stage-5 labelled set) |
| 7. Batch inference | **~2.35M+ rows** (current merged pool; billions eventually once the full unfiltered ingest + future sources are folded in) | Not started | 100,000 rows, drawn from the sampling candidate pool — may scale up to a larger subset if the 100K run finishes in under 30 minutes |

## On the small-scale column

Stages 3–6 no longer carry a separate hand-picked small-scale number: the
real `--include-all-source` draw (all 374 unique GWAS rows + 2,000
downsampled OT rows = 2,374 total) already *is* small-scale relative to the
2.35M-row candidate pool, so it's carried straight through to labelling
(stage 5) and training (stage 6) rather than recomputed with a separate flat
rule. (An earlier draft of this doc used a flat 1,000-row OT draw instead —
that rule has been dropped in favor of matching the pipeline's actual
strategy.) Ingestion (stage 2) and the candidate pool (stage 4) still stay at
their full/current size, since they're upstream raw-data stages, not
something we choose to scale down. Stage 7 keeps its independent 100,000-row
trial-run target.

## On the GWAS Catalog numbers

Stage 3 (GWAS Catalog) was originally implemented on `feat/gwas-cooccurrence`
(authored outside this session) and merged to `main` via PR #5 (`ede2b81`),
then extended with a title corpus and merged into the OT pool via PR #7
(`feat/ot-epmc-ingest-and-merge`). Numbers above are copied from
[14-session-log-ot-epmc-merge.md](14-session-log-ot-epmc-merge.md)'s "Ran it
for real" section — a snapshot from that run, not re-executed here. The root
[`README.md`](../README.md)'s stage-3 status line has been updated to reflect
the merge.
