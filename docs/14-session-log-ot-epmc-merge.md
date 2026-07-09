# 14 — Session Log: OT-EPMC FTP Ingestion, GWAS Title Corpus & Source Merge

**Date:** 2026-07-09
**Scope:** Regenerate the Open Targets co-occurrence data **locally from the
public FTP** (the docs/11 run used a private GCS bucket on another machine),
balance the GWAS Catalog source with an abstract+title corpus, add a
`data_source` provenance column, normalize `publication_id` to `PMID:<id>`, and
**merge OT + GWAS into one pool for stage 4** so both sources are together by
stage 5.

This is a live-updating log — committed with the code and appended as the run
completes.

## Key finding: the intermediate cooccurrence dataset is not on the public FTP

docs/11's stage 2 read
`gs://open-targets-pipeline-runs/ds/26.06.0-dev2/intermediate/literature/cooccurrence`
— an **intermediate** pipeline dataset in a private GCS bucket. The public
Open Targets FTP (`.../platform/26.06/output/`) does **not** publish that flat,
exploded cooccurrence dataset. Its content instead lives in the
**`evidence_europepmc`** output (125 part-files, ~11.6 GB) as a **nested**
array, one row per (target, disease, publication):

```
targetId (Ensembl) · diseaseId (EFO/MONDO/HP) · literature [pmid…] · publicationDate · resourceScore
textMiningSentences: list<struct{ text, section, tStart, tEnd, dStart, dEnd }>
```

So the co-occurrence rows are reconstructed by **exploding
`textMiningSentences`** — a new FTP ingestion path, distinct from the GCS code.

## Decisions taken this session (user-confirmed)

- **Filter during ingest** (not a faithful full ingest): keep only the 2-year
  window (`publicationDate >= 2024-07-09`) and `section in {abstract, title}` —
  which is exactly what stage 4 samples — so the output is a few million rows,
  not ~100M. Laptop-friendly, incremental (download → explode → write → delete
  raw, so peak disk is one ~90 MB part-file).
- **Balance the two sources on abstract + title.** OT EPMC contributes both
  `abstract` and `title` sentences. GWAS previously mined only the abstract (and
  an experimental full-text body). Added a **title corpus** for GWAS from the
  Catalog's `STUDY` column (the paper title — local, no fetch), emitted with
  `section="title"`. `--source both` now means abstract + title.
- **`data_source` column** added to `schema.Cooccurrence` **and**
  `LabeledTriple` (provenance reaches stage 5): `open_targets` for the EPMC
  co-occurrences, `gwas_catalog` for GWAS.
- **`publication_id` normalized to `PMID:<id>`** in both sources (was a bare
  PMID in OT and GWAS; docs/13's labelling already assumed the `PMID:` form).

## What was implemented

- **`src/litrex/data_sources/cooccurrence.py`** — new FTP path:
  `list_ftp_parts()`, `to_cooccurrence_epmc()` (explode + filter + map +
  `data_source` + `PMID:`), `ingest_epmc_ftp()` (incremental), CLI `--from-ftp`.
  The existing GCS `to_cooccurrence()` also gained `data_source`/`PMID:` for
  contract consistency.
- **`src/litrex/data_sources/gwas/`** — `load.py` reads `STUDY` → `Association.title`;
  `cooccurrence.py` sets `data_source="gwas_catalog"`, `PMID:` prefix, and
  `section` maps `abstract|title|body`; `build.py` adds the `title` corpus
  (from `STUDY`, no fetch) and makes `both` = abstract+title.
- **`src/litrex/data_sources/merge.py`** (new) — normalizes each source's output
  to one uniform 12-column schema (contract + `data_source` + spans +
  `text_granularity`; source-specific extras dropped) and writes them into a
  single directory the stage-4 sampler scans as one dataset.
- **`schema.py`** — `data_source` added to `Cooccurrence` and `LabeledTriple`.
- Tests updated/added across schema, cooccurrence (incl. a synthetic EPMC
  explode test), merge, and the GWAS suite. Full suite green (68), ruff clean.

## Verified so far

- EPMC transform on one real part-file: 262,903 evidence rows → **23,868**
  co-occurrence rows for the 2-yr abstract/title window; both sections present
  (abstract 20,941 / title 2,927); `data_source=open_targets`; spans correct
  (`Mcl-1`/`AML`); `PMID:` prefixed.
- GWAS rebuild (`--source both`): **abstract 423**, **title 8** co-occurrences
  (`data_source=gwas_catalog`, `PMID:` prefixed). Title co-occurrences are
  sparse — GWAS study titles usually name the trait plus a locus/rsid rather
  than a gene symbol — but present, balancing OT's title section.

## In progress / next (to append)

- **OT-EPMC FTP ingest** running (`data/processed/cooccurrence/`, gitignored) —
  ~60/125 part-files at time of writing.
- **Merge** OT + GWAS(abstract+title) → `data/processed/merged/`.
- **Stage 4** over the merged pool (totals 47,080 / 78,691) → a
  `sample_manifest.parquet` spanning both sources, carrying `data_source`.
- Final row counts + coverage/spread numbers to be recorded here once done.

## Points worth taking forward

- **`evidence_europepmc` ≠ the intermediate cooccurrence.** It is already
  target/disease **evidence** (aggregated per publication), so a row is only
  present when OT scored it as evidence — slightly narrower than the raw
  cooccurrence dataset. Acceptable for a public-FTP-only rebuild; note it if
  numbers differ from the docs/11 GCS run.
- **`sample_row_id` does not include `data_source`.** A pair found by both OT
  and GWAS with identical `(target, disease, pmid, section, text)` dedups to one
  row (keeping whichever source is drawn first). Fine for now; revisit if we
  want to preserve both provenances.
- **The stage-5 client** (`feat/stage5-llm-client`) already validated
  `PMID:`-form ids and reads `data_source` through the `LabeledTriple` contract;
  the two branches converge at merge to main.
