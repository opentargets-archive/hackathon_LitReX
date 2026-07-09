# 12 — Session Log: Representative Sampling (Stage 4)

**Date:** 2026-07-09
**Scope:** Implemented and ran stage 4 (docs/04) end-to-end against the real
processed Cooccurrence data from stage 2. GWAS Catalog (stage 3) is still
delegated/pending, so this sample is Cooccurrence-only, as docs/04 allows
("v1 can proceed with Cooccurrence alone").

## Decisions taken this session (user-confirmed)

- **Platform totals**: 47,080 diseases / 78,691 targets, supplied by the
  user (docs/04 leaves these as an external constant, not computed here).
  Stored in a local `.env` (gitignored) as `LITREX_PLATFORM_TOTAL_DISEASES`
  / `LITREX_PLATFORM_TOTAL_TARGETS`, picked up by `config.settings` and used
  as the CLI's defaults. **Not committed** — any future session/clone needs
  to re-create `.env` or pass `--total-diseases`/`--total-targets` on the
  command line.
- **Sample size**: start at 500 rows, but the manifest is **append-only**
  and designed to be topped up later without re-drawing or duplicating rows
  (see "Incremental sampling" below) — this was an explicit requirement
  ("more rows might be appended later so we need to keep track which rows
  have been sampled and which haven't").
- **Section filter**: `abstract` + `title` (exact match against the real
  observed `section` values — body sections and compound tags like
  `results,discuss` are excluded).
- **Ontology data source**: fetch live EFO/MONDO ancestor data via the EBI
  OLS4 REST API rather than a bundled ontology file — see below for why the
  "download a file" option didn't pan out as originally scoped.

## Important finding: the >=10% coverage bar is not reachable at n=500

10% of 47,080 platform diseases is ~4,708 distinct diseases — mathematically
impossible for any 500-row sample to reach, since 500 rows can contain at
most 500 distinct diseases (same logic for the ~7,869-target bar). Confirmed
this isn't a bug: the *candidate pool* (2-year abstract+title window, before
sampling) already has 7,303 distinct diseases (15.5%) and 16,531 distinct
targets (21%), comfortably over 10% — it's a random 500-row draw from that
pool that can't preserve the coverage percentage.

**Resolution**: `coverage()`/`ontology_spread()` are always computed and
recorded in the run metadata (satisfies docs/04's "attached as run metadata,
so representativeness is auditable"), but are **not a hard gate** that
blocks `draw_sample`. The percentages are expected to climb toward the
threshold as the manifest grows via repeated top-ups (using a much larger
`--target-size` later), not to be met by the first small batch. Flag this
if stage 5/6 assumes the *initial* 500-row manifest already satisfies
docs/04's representativeness bar — it doesn't yet, by design.

## Ontology spread: implementation and why it isn't a downloaded file

The original plan (per the user's choice) was to fetch the EFO ontology
release file (e.g. `efo_otar_slim.obo`) and derive therapeutic-area
ancestors locally. In practice:

- EFO's built release artifacts aren't published at a discoverable static
  URL (checked GitHub releases for the latest tag, `v3.91.0` — no
  `.obo`/`.owl` assets attached, `api.github.com` was also rate-limited from
  this environment).
- The EFO *source* repo (`codeload.github.com/EBISPOT/efo/tar.gz/...`) is a
  ~280MB multi-file OWL project (`efo-edit.owl` + many `owl:imports` across
  `src/ontology/imports/*.owl`) that needs a real OWL reasoner to resolve —
  far more than a v1 prototype needs.
- **Switched to the EBI OLS4 REST API** (`/api/ontologies/efo/terms/{iri}/graph`)
  instead: same authoritative, always-current EFO/MONDO ancestor data, no
  local reasoner, at the cost of a network call per novel disease ID —
  mitigated with an on-disk cache (`data/cache/efo_graph_cache.json`,
  gitignored under `/data/`) so repeat runs against overlapping disease sets
  don't re-fetch.

Also discovered along the way: **EFO's own disease root (`EFO_0000408`) is
itself obsolete** in current EFO — the disease branch was migrated to import
MONDO directly, so `MONDO_0000001` ("disease") is the real root. Implemented
in `src/litrex/sampling/therapeutic_area.py`:

- Walks each disease ID's `subClassOf` chain up to `MONDO_0000001`, greedily
  taking the alphabetically-first parent at each step (**not** a full
  multi-parent traversal — a disease with multiple parents may resolve
  differently than a true DAG analysis would pick; acceptable for docs/04's
  "reasonably spread... rather than a single hard threshold" bar, not a
  reproduction of Open Targets' curated ~35-item therapeutic-area list).
- Skips over MONDO's own top-level *grouping axes* (`MONDO_7770006`/7/8,
  "disease by body system", etc. — organizational nodes, not real disease
  categories) by bucketing one hop further down instead.
- `HP_`-prefixed disease IDs (Human Phenotype Ontology — a separate tree,
  not under the MONDO disease root) are bucketed directly as
  `"phenotype (HP)"` without a network call.
- Dead-end resolutions (depth cap of 12 hops exceeded, or neither candidate
  IRI form resolves) bucket as `"unknown"`.
- Spread is summarized as bucket counts/proportions plus **normalized
  Shannon entropy** (0 = one bucket, 1 = uniform across observed buckets) —
  the "concrete metric" docs/10 flagged as missing.

## Incremental sampling design

`draw_sample(candidates, ..., existing=prior_manifest, target_size=N)`:

- Computes a stable `sample_row_id` per candidate row —
  `sha1(target|disease|publication_id|section|text)` — using only fields
  from the shared `Cooccurrence` contract (not Cooccurrence-only extra
  columns), so this keeps working once GWAS Catalog rows (stage 3) are
  folded in.
- Excludes rows already present in `existing` (by `sample_row_id`) and
  exact-duplicate rows within the candidate pool itself (same key) — this
  incidentally resolves the "exact duplicate raw rows" issue flagged in
  docs/11's session log, since duplicates collide to the same ID and only
  the first occurrence is eligible to be drawn.
- Draws only `target_size - len(existing)` new rows (uniform random via
  `random.Random(seed)` — no stratification in v1; flagged below).
- Returns the **combined** table (existing + new) and a metrics dict
  including `new_rows_added`, so repeated CLI runs are safe to re-run with a
  larger `--target-size` to top up, and a no-op if the target is already met.

The CLI (`python -m litrex.sampling.representative_sample`) writes/overwrites
`data/processed/sample_manifest.parquet` with the combined table each run,
and appends a run record (timestamp, filters, full metrics) to
`data/processed/sample_manifest_metadata.json` (a JSON array, one entry per
run) rather than overwriting — so the top-up history is itself auditable.

## Ran it for real

`python -m litrex.sampling.representative_sample --target-size 500 --seed 0`
against the full `data/processed/cooccurrence` (103M rows):

- Predicate-pushdown filter (2-year window: 2024-07-09 to 2026-07-09,
  `section in (abstract, title)`) via `pyarrow.dataset` took ~1s and
  produced 2,565,787 candidate rows.
- Drew 500 rows: disease coverage 0.49% (229/47,080), target coverage 0.48%
  (378/78,691) — as expected, see the coverage finding above.
- Ontology spread: normalized entropy 0.712, 18 disease IDs resolved to
  `unknown`. Dominant bucket by far was "cancer or benign tumor" (196/500,
  ~39%) — consistent with cancer literature dominating biomedical
  co-occurrence data generally, not a bug in the bucketing.
- Wall-clock ~96s, almost all of it sequential OLS API calls to resolve 229
  distinct diseases' therapeutic areas (cached afterward — a second run over
  the same/overlapping diseases would be much faster).

## Points worth taking forward

- **No stratification yet.** `draw_sample` is uniform random. If/when a
  much larger top-up is needed to meaningfully move the coverage
  percentages, docs/04 step 3 suggests stratified sampling to boost
  under-represented diseases/targets/branches — not implemented, flagged as
  a follow-up rather than guessed at now.
- **OLS resolution is sequential and network-bound.** Fine at ~500 rows
  (~230 distinct diseases), but would need batching/concurrency if a much
  bigger top-up (thousands of new distinct diseases) is drawn in one run.
- **`.env` is gitignored** — the platform totals used this session
  (47,080 / 78,691) aren't committed anywhere else. Re-set them (or pass
  `--total-diseases`/`--total-targets`) in any future session/clone.
- **`data/cache/` is gitignored** too (under `/data/`) — the OLS graph cache
  built up this session (458 IRIs) isn't preserved across clones; it'll
  rebuild itself (and get slower on the first run) whenever a fresh clone
  samples again.
