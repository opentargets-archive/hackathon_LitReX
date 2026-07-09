# LitReX — Project Docs

Biomedical relation extraction from literature: classify the relationship
between a **target** and a **disease** as expressed in a piece of literature
text, starting from co-occurrence data, at a scale of billions of rows.

This folder is the plan. No code exists yet — see [`09-repo-structure.md`](09-repo-structure.md)
for the scaffolding that will be created once this plan is agreed.

## Reading order / pipeline stages

| # | Doc | Stage | Output |
|---|-----|-------|--------|
| 1 | [01-overview.md](01-overview.md) | Vision & architecture | Shared understanding, non-goals |
| 2 | [02-data-source-cooccurrence.md](02-data-source-cooccurrence.md) | Primary data source | Normalized `Cooccurrence` rows (Parquet) |
| 3 | [03-data-source-gwas-catalog.md](03-data-source-gwas-catalog.md) | Secondary data source (delegated) | `Cooccurrence`-shaped rows from GWAS Catalog |
| 4 | [04-sampling.md](04-sampling.md) | Representative sampling | `sample_manifest.parquet` for labelling |
| 5 | [05-llm-labelling.md](05-llm-labelling.md) | LLM relationship judge | Silver-labelled triples |
| 6 | [06-classifier-training.md](06-classifier-training.md) | Fine-tuning | Trained relation classifier + eval report |
| 7 | [07-inference.md](07-inference.md) | Scalable batch inference | Scored relationships over full dataset |
| 8 | [08-product-vision.md](08-product-vision.md) | Downstream product (light plan) | Front-end/evidence-score direction (revisit later) |
| 9 | [09-repo-structure.md](09-repo-structure.md) | Scaffolding plan | Repo layout to create |
| 10 | [10-open-questions.md](10-open-questions.md) | Tracking | Outstanding decisions |
| 11 | [11-session-log-cooccurrence-ingestion.md](11-session-log-cooccurrence-ingestion.md) | Session log | What's been implemented/run for stage 2, and follow-ups |
| 12 | [12-session-log-sampling.md](12-session-log-sampling.md) | Session log | What's been implemented/run for stage 4, and follow-ups |

## Ownership split

- **Cooccurrence pipeline (stage 2), sampling, LLM labelling, training, inference,
  repo scaffolding** — built in this main track.
- **GWAS Catalog normalization (stage 3)** — delegated to a separate
  agent/session. Doc 3 is written to be self-contained (own contract, own
  acceptance criteria) so it can be picked up without this conversation's
  context.

## Core data contract

Every data source must ultimately produce rows of this shape before entering
the sampling stage:

```
Cooccurrence:
  target:  str   # normalized target ID (Ensembl gene ID)
  disease: str   # normalized disease ID (EFO ID)
  text:    str   # literature text span (sentence/passage) mentioning both
```

Anything downstream of stage 4 (sampling) only ever consumes this shape,
regardless of which source it came from.
