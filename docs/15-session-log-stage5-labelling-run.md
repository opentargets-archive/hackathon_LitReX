# 15 — Session Log: Stage 5 Labelling Run (OpenAI) + Manual-Review Analysis

**Date:** 2026-07-09
**Scope:** Ran stage 5 (LLM relationship judge) end-to-end over the merged
OT+GWAS `sample_manifest.parquet` (docs/14) with the real client, and did the
docs/05 step-4 manual-review pass — quantifying the entity-linking noise
docs/13 flagged but never counted.

## Run

- **Provider: OpenAI** (`--provider openai`, model `gpt-4.1`) via the **Batch
  API** (`--batch`). The Anthropic key wasn't available locally this session;
  the OpenAI path (added this session — see the branch history) was used
  instead. Every row records a **`judge_model`** column, so these GPT labels
  stay distinguishable from a future Claude rerun.
- Keys were kept out of the repo entirely — exported in `~/.zshenv`, read by the
  SDKs at runtime, never committed. `caffeinate` held the machine awake for the
  ~2h batch.
- **Result:** `data/processed/labeled_triples.parquet` (gitignored) —
  **2,374 / 2,374 labelled, 0 errors**, mean confidence 0.751.

### Distribution

| confidence band | rows |
|---|---|
| ≥ 0.85 | 1,392 (59%) |
| 0.5–0.85 | 537 |
| 0.3–0.5 | 328 |
| < 0.3 | 117 |

| source | n | mean conf | empty-evidence |
|---|---|---|---|
| open_targets | 2,000 | 0.76 | 29% |
| gwas_catalog | 374 | 0.72 | 39% |

High-confidence rows are directional and well-grounded (e.g. TNF-α upregulated
in IBD quoting the bracketed span; MFGE8 reduced in asthma sputum). Low-confidence
rows are correctly identified as non-relationships rather than fabricated ones.

## Manual-review pass (docs/05 step 4): quantifying entity-linking noise

docs/13 flagged recurring entity-linking noise (the bracketed/resolved
target or disease not actually corresponding to the text) but never counted it.
Using the judge's own free-text `relation` descriptions — which explicitly say
when an entity is absent ("mentions X but does not mention Y") — the 445
low-confidence rows (conf < 0.5) break down as:

| bucket | rows | share |
|---|---|---|
| clean co-mention (both entities present, no relationship asserted) | 328 | 74% |
| hedged / uncertain relationship | 86 | 19% |
| **entity-linking noise (an entity not in the text)** | **31** | **7%** |

By source (share of that source's low-conf rows): entity-absent **10% GWAS /
6% OT**. So the noise rate is **~7% of the low-confidence band ≈ 1.3% of the
full 2,374-row set** — and every one is already scored low-confidence, so it
self-filters for training.

**Where the noise comes from** (from the flagged examples, both sources):

- **OT:** the disease/gene resolved from the ID isn't in the co-occurring span
  — e.g. `GCG → type 1 diabetes` ("mentions Type 1 Diabetes but does not mention
  GCG"), `MLH1 → hyperinsulinemic hypoglycemia` (gene present, disease absent).
  Points at stage-2's ID→text-offset mapping surfacing a pair whose span doesn't
  contain both entities.
- **GWAS:** the rsID is in the abstract but the *mapped gene* (and any
  relationship) isn't — e.g. "mentions the SNP rs3888777, but does not state
  that the SNP is in PRR3". Inherent to rsID-based matching against
  association-style GWAS abstracts.

## Points worth taking forward

- **The silver set is ready for stage 6** (training) and is well-labelled. The
  low-confidence co-mentions are useful **negative/neutral** examples the
  classifier needs — don't discard the whole low band.
- **Filter (don't fix) the ~31 entity-absent rows** for training — they're
  mislabelled at the *input* (wrong entity), not the judgment. A `confidence`
  threshold plus an "entity present in text" check would remove them cheaply.
- **GWAS's mechanistic-relationship yield via abstracts is low** — most GWAS
  co-occurrences are co-mentions (39% empty-evidence, mean conf 0.72). GWAS is
  pulling its weight as a source of negatives and association-style statements,
  not mechanism. Full-text GWAS (the `fulltext` corpus, currently excluded by
  the abstract/title section filter) might raise the mechanistic share if that
  becomes a goal.
- **Provider provenance is recorded** (`judge_model = gpt-4.1`). If the team
  standardises on Claude, a rerun on the same manifest is directly comparable
  row-by-row.
