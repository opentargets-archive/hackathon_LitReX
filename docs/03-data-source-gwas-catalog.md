# 03 — Data Source: GWAS Catalog Normalization

**Owner:** delegated to a separate agent/session. This doc is written to be
self-contained — read this file plus [README.md](README.md) (for the target
contract) and you should have everything needed to implement this
independently, without needing the rest of the project's planning history.

## Context

LitReX classifies target-disease relationships from literature text. Its
primary data source is the Open Targets Cooccurrence dataset, which already
has targets/diseases normalized to IDs (see
[02-data-source-cooccurrence.md](02-data-source-cooccurrence.md)). GWAS
Catalog is a secondary source that expands the sample's coverage, but its
target/disease fields are **not** pre-normalized to the same ID space and
need mapping via **OnToma** (a Python package — see
https://github.com/opentargets/OnToma) before they can be used.

(Expression Atlas was considered as a third source and has been dropped from
scope for now — don't build for it.)

## Goal

Given the raw GWAS Catalog dataset, produce rows in the same shape as
`Cooccurrence` (see contract below), with target normalized to Ensembl gene
ID and disease normalized to EFO ID, using OnToma.

## Input

Raw GWAS Catalog data (e.g. the GWAS Catalog association/study export).
Relevant raw fields typically include:

- reported gene(s)/mapped gene(s) for each association (free text / gene
  symbols, not Ensembl IDs)
- reported trait/disease (free text, not EFO IDs — though GWAS Catalog does
  sometimes ship its own EFO mappings; check whether those are usable
  directly or still need OnToma reconciliation against Open Targets' EFO
  version)
- some form of source text/context (this needs investigation — GWAS Catalog
  associations may not have a natural language "text" field the way
  Cooccurrence does; may need to construct one from study metadata, e.g.
  "GWAS study {study_id} found association between {gene} and {trait}
  (p={p_value})", or treat the row as text-free and flag it for the
  labelling step to handle appropriately)
- publication identifier (PMID) and publication date

## Output contract

Must match the core contract from [README.md](README.md), plus the same
extra fields used by the Cooccurrence source so downstream sampling/stage 4
logic doesn't need source-specific branches:

```
Cooccurrence:
  target:           str   # Ensembl gene ID (normalized via OnToma)
  disease:          str   # EFO ID (normalized via OnToma)
  text:             str   # literature/context text — see open question above
  publication_id:   str   # PMID or equivalent
  publication_date: date
  section:          str   # if not meaningful for GWAS Catalog, use a fixed
                          # sentinel value (e.g. "gwas_association") rather
                          # than leaving null, so downstream filters don't
                          # need null-handling for source
```

Rows that fail to normalize (no confident OnToma mapping) should be dropped
and logged/counted, not silently included with a null ID.

## Steps

1. Get the raw GWAS Catalog export (identify exact source/format/version).
2. For each association, run gene symbol → Ensembl ID and trait → EFO ID
   through OnToma. Handle: no match, ambiguous/multiple matches, low
   confidence matches — define a threshold and log everything below it.
3. Resolve the `text` field question above (construct a synthetic sentence
   vs. sourcing something more natural) — this is the one open design
   decision in this doc; make a call, document the reasoning in this file
   once resolved (or note it in [10-open-questions.md](10-open-questions.md)
   if it needs sign-off before proceeding).
4. Assemble into the output contract shape, write as Parquet.
5. Validate: normalization hit rate (% of rows successfully mapped), spot
   check a sample of mappings for correctness, row count sanity check
   against the raw source.
6. Report back: hit rate, row count, any systematic mapping failures (e.g.
   a gene symbol format OnToma consistently can't resolve).

## Acceptance criteria

- Output Parquet file(s) conform exactly to the contract above.
- Every row's `target`/`disease` are valid, resolvable Ensembl/EFO IDs (no
  raw gene symbols or free-text trait names leaking through).
- A short report (numbers, not prose) on normalization coverage/hit rate.
- No dependency on any other part of the LitReX pipeline — this module's
  only job is producing the Parquet output; it does not need to know about
  sampling, labelling, or training.
