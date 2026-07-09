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
