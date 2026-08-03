# 13 — Session Log: LLM Relationship Judge (Stage 5)

**Date:** 2026-07-09
**Scope:** Refined the stage-5 prompt (docs/05) and ran a one-off labelling
pass over the full 500-row `sample_manifest.parquet` from stage 4. GWAS
Catalog (stage 3) is still delegated/pending, so this is Cooccurrence-only,
same as the stage-4 sample it labels — **this pass will need to be re-run
once GWAS Catalog rows are merged into a larger sample.**

## Prompt design (final)

Iterated with the user through several rounds; final design in
`src/litrex/labelling/prompts.py`:

1. **`relation` is free-text, not a category label.** The original stage-5
   plan (and my first draft) offered five preferred labels
   (positive-upregulation / positive-downregulation / negative / co-mention /
   no-association) as anchors. The user explicitly rejected this: this pass
   should only **describe** the relationship in the model's own words;
   classification into a taxonomy is deferred to a later step (docs/06). The
   final prompt instructs the model not to categorize at all.
2. **Grounding**: explicit instruction to judge only what TEXT states, not
   outside knowledge of the target/disease — this mattered a lot in practice
   (see findings below).
3. **Confidence calibration rubric**: explicit anchor points (0.85+ direct
   and unhedged, 0.5-0.8 hedged/indirect, <0.5 ambiguous) rather than a bare
   "0 to 1" instruction.
4. **`evidence_span`**: an extra field beyond the `LabeledTriple` contract
   (dropped by `Cooccurrence`-style `extra='ignore'` parsing, kept only in
   the raw output parquet) — a verbatim quote grounding the description,
   empty when no relationship is asserted.
5. **Span marking**: `target_span`/`disease_span` (from stage 2's
   `target_start`/`target_end`/`disease_start`/`disease_end` extra columns)
   bracket the exact mention under judgment with `[[...]]`, so the model
   doesn't get confused when the same gene symbol or disease term appears
   more than once in a multi-sentence ("chunk" granularity) span.

## Execution: one-off sub-agent pass, not the API pipeline

**Decision**: the user chose to avoid provisioning a separate Anthropic API
key (cost was trivial, ~$2-4, but they preferred not to) and instead had
this session's own sub-agents do the judging directly, writing structured
JSON output to scratch files that were then merged into the final dataset.

**What this means going forward**: `src/litrex/labelling/llm_client.py`
(the real `anthropic.Anthropic()`-based batched client docs/09 calls for)
was **not built or exercised this session** — it's still the original
`NotImplementedError` stub. This pass produced a real, validated
`LabeledTriple` dataset, but not a rerunnable pipeline. Building
`llm_client.py` for real is still needed before the eventual larger
GWAS-merged rerun, unless that rerun is also done via sub-agents.

**How it worked**: `src/litrex/labelling/entity_names.py` (new) resolved
target Ensembl IDs to gene symbols (Ensembl REST batch lookup, 378/378
resolved) and disease IDs to labels (EBI OLS4 API, reusing
`sampling/therapeutic_area.py`'s `candidate_iris` helper — now public since
shared across both modules; 225/229 resolved, 4 fell back to the raw ID).
500 rows were split into 10 batches of 50, each dispatched to a
`general-purpose` sub-agent in parallel with the system prompt + its batch's
pre-built `build_prompt()` outputs, instructed to judge every row
independently and write results to a batch-specific JSON file. Results were
merged, validated against `LabeledTriple`, and joined back onto the stage-4
manifest.

## Results

500/500 rows judged and validated with zero schema errors — written to
`data/processed/labeled_triples.parquet` (gitignored, like all of `data/`).

- Confidence distribution: mean 0.58, median 0.60. 67 rows <0.3 (mostly
  correctly-identified non-relationships or entity-linking noise, see
  below), 191 rows 0.6-0.85, 82 rows ≥0.85.
- 51/500 rows have an empty `evidence_span` (no relationship asserted, or
  TEXT too undifferentiated to quote).
- Spot-checked high-confidence rows: direct, unhedged, well-grounded
  (`SHANK3` haploinsufficiency → Phelan-McDermid syndrome at 0.97,
  `C9orf72` repeat expansion → ALS/FTD at 0.95).
- Spot-checked low-confidence rows: correctly identified as either plain
  list co-mentions with no asserted relationship, or genuine entity-linking
  noise (see below) — not forced into a fabricated relationship.

## Finding worth flagging: recurring entity-linking noise upstream

Nearly every batch (9 of 10 sub-agents flagged this unprompted) surfaced
rows where the bracketed target/disease mention didn't actually correspond
to the intended entity:

- **Disease-label acronym collisions**: the EFO/MONDO label resolved for a
  `disease` ID happens to share a common acronym with something unrelated
  actually being discussed in TEXT -- e.g. "MS" resolved to a disease whose
  common abbreviation is "multiple sclerosis" but TEXT used "MS" for
  "metabolic syndrome"; "PCa" resolved near "posterior cortical atrophy" but
  TEXT meant "prostate cancer"; "AOM" meant "azoxymethane" not "otitis
  media"; "CIN" meant "chromosomal instability" not the cervical disease
  entry.
- **Bracketed span pointing at the wrong text**: a handful of rows had
  `target_start`/`target_end` (or the disease equivalent) landing on an
  unrelated substring -- e.g. a `TF` bracket landing on the generic phrase
  "transcription factor" rather than the gene symbol, or a target gene not
  appearing in the excerpt at all.

This wasn't systematically counted (each sub-agent flagged specific
instances in its own summary, not a full audit), but it was consistent
enough across independent batches that it looks like real upstream noise --
most likely in stage 2's disease/gene ID→text-offset mapping, or in a
downstream name-resolution collision I introduced this session (resolving
`disease` IDs to full-length EFO labels rather than checking the raw
literature text's own abbreviation). The sub-agents handled it correctly
(described the mismatch, scored low confidence, left `evidence_span` empty)
rather than papering over it, which is exactly the grounding rule doing its
job -- but it's worth a proper audit before stage 6 training, since a
systematic bias here would quietly degrade the classifier's training data.

## Points worth taking forward

- **Build the real `llm_client.py` pipeline** before the next (larger,
  GWAS-merged) rerun — this session's sub-agent approach produced a valid
  one-off dataset but isn't a script anyone can rerun unattended.
- **Audit the entity-linking noise rate.** Not counted precisely this
  session; a systematic count (e.g. sample 50 low-confidence rows and
  manually check whether the bracketed span/resolved name is correct) would
  tell us whether to filter these out, fix upstream, or leave them (the
  low-confidence score may already down-weight them adequately for stage 6).
- **`entity_names.py` caches at `data/cache/ensembl_gene_names.json` and
  `data/cache/efo_disease_names.json`** — gitignored like the rest of
  `data/cache/`, will rebuild on a fresh clone.
- **Manual review pass (docs/05 step 4)** — not done this session. The
  labelled dataset is ready for it: sort by confidence, spot-check the
  low-confidence band for the entity-linking issue above, and decide the
  taxonomy question (still fully open, since this pass deliberately avoided
  categorizing) before stage 6.

## Follow-up: review prep and quantitative audit

**Scope:** a later session that did not re-run labelling, but analyzed the
existing `labeled_triples.parquet` directly and built the tooling/sample
needed for the still-open manual review pass above. No rows were
relabelled and no source data changed.

**CSV exports added** (both gitignored under `/data/`, local-only):

- `data/processed/labeled_triples.csv` — the full 500-row dataset, sorted
  `confidence` ascending then `relation` alphabetically, for anyone who
  wants to browse it outside Python/pandas.
- `data/review/low_confidence_review_sample.csv` — a 50-row stratified
  sample drawn from the 67 rows with `confidence < 0.3`, built for the
  entity-linking audit this doc already called for. Stratified by
  (auto-flagged-mismatch × section), proportional allocation, seed 42.
  Columns include the stage-4 `target_start`/`target_end`/`disease_start`/
  `disease_end` offsets joined back in from `sample_manifest.parquet`, and
  resolved `target_symbol`/`disease_label` from the `entity_names.py`
  caches, so each row can be checked without re-resolving IDs by hand.
- An HTML review page (highlighted target/disease spans, filter/search,
  per-row verdict radio buttons) was built from this sample but **not
  published** — held for the user to decide separately.

**Quantitative confirmation of docs/13's original numbers:** re-derived
directly from the parquet — 500 rows, mean confidence 0.58, median 0.60,
378 unique targets, 229 unique diseases, 423 abstract / 77 title, 51 rows
with empty `evidence_span`. All consistent with the original session's
figures above; recorded here as a second, independently-computed
confirmation rather than a correction.

**Entity-mismatch rate, first rough number:** of the 67 rows scoring
`<0.3`, a naive keyword scan (`does not mention|not actually|unrelated|
mismatch|no relationship|not asserted` against the model's own `relation`
text) matched only **13 rows (~19% of the <0.3 band, ~2.6% of the full
500)**. This is a first quantitative anchor against the original session's
qualitative "9 of 10 sub-agents flagged this unprompted" — it suggests the
*explicitly self-reported* mismatch rate is a small slice of the low-confidence
band, with the rest being other low-confidence reasons (hedged language,
genuine list co-mentions, indirect statements). **Caveat: this was a single
unvalidated regex pass, not a manual audit** — no spot-checking was done on
false positives/negatives, so treat it as a lower bound / rough order of
magnitude, not a settled count. The actual manual check (docs/05 step 4)
is what the 50-row sample above is for.

**Relationship-shape scan, exploratory only:** a separate ad hoc keyword
scan over all 500 `relation` texts found rows matching: risk/association
language (107), therapeutic-target/treatment framing (86),
mutation/variant-driven (38), biomarker/diagnostic framing (41),
up/down-regulation or expression change (33), direct causal language (45).
Categories are not mutually exclusive and this was not validated —
**it should not be read as a candidate taxonomy**, only as a hint that the
relationship space is broader than the original 4-item hypothesis
(positive-up/positive-down/negative/neutral) and includes causal,
risk-association, therapeutic-target, and biomarker framings as apparently
distinct shapes. Settling the actual taxonomy still requires the manual
review pass.

**Still open, updated:** the manual review pass and taxonomy decision are
unchanged as open — this follow-up only prepared sampling/tooling for it,
it did not perform it.
