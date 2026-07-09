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

## Ran it for real (final numbers)

- **OT-EPMC FTP ingest** → `data/processed/cooccurrence/` (125 part-files, 264 MB,
  gitignored): **2,354,558 rows** for the 2-yr window — abstract 2,068,134 /
  title 286,424. (A handful of OT rows carry garbage future `publicationDate`s,
  max 2096-06-01; stage-4's `end-date <= today` filter drops them.)
- **Network robustness fix:** the first run died at 121/125 on a transient FTP
  `ReadTimeoutError`. Added retry-with-backoff **and resume** (skip part-files
  already in the output dir) to `ingest_epmc_ftp`; the rerun skipped the 121 and
  fetched the last 4 cleanly.
- **Merge** (`merge_sources`) → `data/processed/merged/` (127 files):
  **2,354,989 rows** = OT 2,354,558 + GWAS abstract 423 + GWAS title 8, one
  uniform 12-column schema.
- **Stage 4** over the merged pool (500 rows, seed 0, totals 47,080 / 78,691):
  2,354,972 candidates → **500-row `sample_manifest.parquet`** carrying
  `data_source`; disease coverage 0.48% (226/47,080), target coverage 0.46%
  (359/78,691), ontology spread entropy 0.710. Sections: abstract 419 / title 81.
  All `publication_id`s `PMID:`-prefixed.

## ⚠️ Finding: a proportional random sample is ~100% Open Targets

The merged pool is 2.35M rows, of which GWAS is only **431 (0.018%)**. A uniform
500-row draw therefore expects ~0.09 GWAS rows — and indeed the manifest is
**500 `open_targets`, 0 `gwas_catalog`**. The two sources are correctly *together*
in one pool / schema / manifest with `data_source` provenance, but GWAS will not
appear in a plain random sample.

**Resolution (user-confirmed): downsample OT + always-include all GWAS.**
`draw_sample` gained an `include_all_sources` option (CLI `--include-all-source`):
rows of the named `data_source`(s) are added in **full**, and `--target-size`
then counts only the *poolable* (other) sources. Ratio chosen: **OT 2,000 +
all GWAS** (~5:1) — enough OT for relation-language diversity and disease
coverage, GWAS a strong ~16% minority (avoids the tiny-set / GWAS-overweight
problems of a 1:1 split). Uniform draw for v1; stratification remains a
follow-up (docs/12).

### Final labelled-sample manifest (`data/processed/sample_manifest.parquet`)

- **2,374 rows** = **2,000 `open_targets` + 374 `gwas_catalog`** (all unique GWAS;
  57 of the 431 GWAS rows were exact-duplicate co-occurrences — multiple rsids
  for the same gene→disease→sentence — and collapsed by `sample_row_id`).
- Sections: abstract 2,072 / title 302 (OT 1,705/295, GWAS 367/7).
- Disease coverage 1.24% (586/47,080), target coverage 1.73% (1,359/78,691),
  ontology spread entropy 0.737 — all up from the 500-row OT-only draw.
- Every `publication_id` is `PMID:`-prefixed; `data_source` carried through.
- **Ready for stage 5**: both sources are together in one manifest with
  provenance.

### Disk cleanup

The full OT pool (`data/processed/cooccurrence/`, 264 MB) and the merged pool
(`data/processed/merged/`, 262 MB) were **deleted** after sampling — they are
reproducible from FTP (`--from-ftp`) and not needed for stage 5 (labelling reads
the manifest) or stage 6 (training reads the labelled manifest). Freed ~526 MB;
kept the manifest + the small GWAS source parquets. Re-run the ingest → merge →
sample chain to regenerate if a re-draw or top-up is needed.

## Integration to main

Both branches were merged to `main` this session:

- **PR #7** (`feat/ot-epmc-ingest-and-merge`) — OT-EPMC FTP ingest, GWAS
  title corpus, `data_source`, merge, `--include-all-source` sampling.
- **PR #8** (`feat/stage5-llm-client`) — the real stage-5 `llm_client`
  (docs/13's rerunnable pipeline). Reconciled against PR #7: `label_row` now
  sets `LabeledTriple.data_source` from the manifest row, and `run()`
  authenticates via `settings.anthropic_api_key` (`LITREX_ANTHROPIC_API_KEY`),
  falling back to the SDK's own env/profile resolution. `data_source` provenance
  therefore flows all the way into the labelled triples.

`main` now runs stages 2–5 end to end; 70 tests pass, ruff clean.

## Running stage 5 (labelling the merged manifest)

Local is the right place (API/network-bound, no GPU/RAM need; HPC compute-node
egress is the main risk on SLURM). The CLI supports two providers and a batch
path — the prompt/schema/output are identical; only the judge model differs, and
a **`judge_model`** column records which model labelled each row.

```bash
# Anthropic (default, on-design). Key: LITREX_ANTHROPIC_API_KEY in .env
uv run python -m litrex.labelling.llm_client \
  --input data/processed/sample_manifest.parquet \
  --output data/processed/labeled_triples.parquet --batch --limit 20   # smoke first

# OpenAI alternative. Key: OPENAI_API_KEY in .env; default model gpt-4.1
uv run python -m litrex.labelling.llm_client --provider openai \
  --input data/processed/sample_manifest.parquet \
  --output data/processed/labeled_triples.parquet --batch --limit 20
```

Drop `--limit` for the full 2,374 rows. `--batch` uses the provider's Batch API
(~50% cheaper, async submit-and-poll); omit it for synchronous per-row calls
(~40–120 min). The first run resolves ~1,359 targets (Ensembl REST) + ~586
diseases (OLS4) to display names and caches them under `data/cache/`.

**On provider choice:** the pipeline is *designed* as a Claude judge (docs/01,
docs/05) and docs/13's pass used Claude, so Anthropic is the on-design default.
The OpenAI path exists for when only an OpenAI key is available; because the
`judge_model` column is recorded per row, a mixed or GPT-labelled set stays
auditable and a later Claude rerun is directly comparable.

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
