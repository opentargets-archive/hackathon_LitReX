# 09 — Repo Structure (Scaffolding Plan)

**Status:** plan only — nothing below has been created yet. This is what
gets scaffolded once the docs in this folder are agreed.

## Conventions

- `src/` layout.
- Dependency management via `uv`.
- Testing via `pytest`, tests mirror `src/`.
- Linting via `ruff` (assumed default; confirm if a different tool is
  preferred).

## Layout

```
LitReX/
├── pyproject.toml                  # uv-managed, ruff + pytest config
├── docs/                           # this folder
├── src/litrex/
│   ├── schema.py                   # Cooccurrence, LabeledTriple, ScoredRelationship
│   │                                # (pydantic models, Arrow-friendly)
│   ├── data_sources/
│   │   ├── cooccurrence.py         # stage 2 — Open Targets Cooccurrence ingestion
│   │   └── gwas_catalog.py         # stage 3 — GWAS Catalog + OnToma normalization
│   │                                # (delegated implementation, same output contract)
│   ├── sampling/
│   │   └── representative_sample.py # stage 4 — filters + coverage metrics
│   ├── labelling/
│   │   ├── prompts.py              # stage 5 — OpenIE-judge prompt templates
│   │   └── llm_client.py           # stage 5 — batched Claude calls, retry/rate-limit
│   ├── training/
│   │   ├── dataset.py              # stage 6 — silver dataset, splits
│   │   └── train.py                # stage 6 — fine-tuning loop (HF Trainer)
│   ├── inference/
│   │   └── batch_score.py          # stage 7 — pandas_udf-wrappable scoring fn
│   └── config.py                   # pydantic-settings, env-driven
└── tests/                          # mirrors src/litrex
```

## Module boundary rationale

`data_sources/cooccurrence.py` and `data_sources/gwas_catalog.py` are kept
as separate, independent modules — each only needs to produce the shared
`Cooccurrence` contract (see [README.md](README.md)). This lets the GWAS
Catalog module (stage 3) be implemented independently, by a different
agent/session, against a fixed interface, without touching or needing to
understand the rest of the pipeline.

## Sequencing

Scaffold in the order the pipeline stages are built:

1. `pyproject.toml`, `schema.py`, empty package skeleton, pytest wired up.
2. `data_sources/cooccurrence.py` (stage 2).
3. `sampling/` (stage 4) — can be stubbed/tested against a small fixture
   before `data_sources/gwas_catalog.py` (stage 3) lands, since v1 sampling
   can run on Cooccurrence alone.
4. `labelling/` (stage 5).
5. `training/` (stage 6).
6. `inference/` (stage 7).
7. `data_sources/gwas_catalog.py` (stage 3) — can slot in whenever the
   delegated work completes; combined with step 3's sampling once ready.
