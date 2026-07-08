# 10 — Open Questions

Tracked decisions not yet resolved. Update this file as answers land —
delete resolved items or move their resolution into the relevant stage doc.

## Resolved (recorded here for traceability)

- **LLM task shape**: directed relationship judge on known target/disease
  pairs, not open-domain triple extraction. See
  [05-llm-labelling.md](05-llm-labelling.md).
- **v1 data sources**: Open Targets Cooccurrence + GWAS Catalog. Expression
  Atlas dropped from scope.
- **Ownership split**: Cooccurrence pipeline built in main track; GWAS
  Catalog normalization delegated to a separate agent against the spec in
  [03-data-source-gwas-catalog.md](03-data-source-gwas-catalog.md).
- **Product/evidence-score work**: in scope for this repo long-term, but
  only a brief directional plan for now — see
  [08-product-vision.md](08-product-vision.md).
- **Sampling methodology**: two-year window + ≥10% disease/target coverage
  + ontology spread, as described in [04-sampling.md](04-sampling.md).
- **Platform totals** (denominator for coverage %): will be supplied
  directly by the user as a constant per run — not sourced
  programmatically.
- **LLM provider**: Claude via the Anthropic API.
- **Repo structure**: separate `data_sources/` modules per source (see
  [09-repo-structure.md](09-repo-structure.md)).

## Still open

- **Exact upstream Cooccurrence source**: precise path/version/access
  method for the Open Targets Cooccurrence dataset (see
  [02-data-source-cooccurrence.md](02-data-source-cooccurrence.md)).
- **GWAS Catalog `text` field construction**: GWAS Catalog associations may
  not have a natural free-text field like Cooccurrence does — decide
  whether to synthesize one from study metadata or source it differently
  (see [03-data-source-gwas-catalog.md](03-data-source-gwas-catalog.md)).
- **Section filter values for sampling**: which exact `section` value(s)
  count once real data is inspected (see
  [04-sampling.md](04-sampling.md)).
- **Ontology spread metric**: concrete definition/threshold beyond
  "reasonably spread" (see [04-sampling.md](04-sampling.md)).
- **Base classifier model**: PubMedBERT vs. BioBERT vs. other — decide
  after seeing stage 5's labelled data (see
  [06-classifier-training.md](06-classifier-training.md)).
- **LLM output format**: plain text vs. structured/tool-call output for
  parsing `relation`/`confidence` reliably (see
  [05-llm-labelling.md](05-llm-labelling.md)).
- **Evidence score formula**: not designed yet, deferred until stage 7
  output exists (see [08-product-vision.md](08-product-vision.md)).
