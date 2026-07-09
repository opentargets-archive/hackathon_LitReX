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
- **Exact upstream Cooccurrence source**: `gs://open-targets-pipeline-runs/ds/26.06.0-dev2/intermediate/literature/cooccurrence`,
  40 flat Parquet part-files, ~11GB, read directly with pyarrow (no Spark
  cluster needed). Ingested end-to-end; see
  [11-session-log-cooccurrence-ingestion.md](11-session-log-cooccurrence-ingestion.md).
- **Section filter values for sampling**: `abstract` + `title` (exact match).
  See [12-session-log-sampling.md](12-session-log-sampling.md).
- **Ontology spread metric**: normalized Shannon entropy over EFO/MONDO
  top-level therapeutic-area buckets, resolved live via the EBI OLS4 API
  (not a downloaded ontology file — see session log for why). See
  [12-session-log-sampling.md](12-session-log-sampling.md).
- **Platform totals**: 47,080 diseases / 78,691 targets, supplied by the
  user, stored in a local (gitignored) `.env`. See
  [12-session-log-sampling.md](12-session-log-sampling.md).
- **LLM output format**: structured JSON (`relation`, `confidence`,
  `evidence_span`) via a fixed schema, not plain text. See
  [13-session-log-llm-labelling.md](13-session-log-llm-labelling.md).
- **Relation taxonomy at labelling time**: stage 5 does **not** classify —
  `relation` is a free-text description in the model's own words;
  classification into a taxonomy is explicitly deferred to stage 6. See
  [13-session-log-llm-labelling.md](13-session-log-llm-labelling.md).

## Still open

- **GWAS Catalog `text` field construction**: GWAS Catalog associations may
  not have a natural free-text field like Cooccurrence does — decide
  whether to synthesize one from study metadata or source it differently
  (see [03-data-source-gwas-catalog.md](03-data-source-gwas-catalog.md)).
- **Stratified sampling**: stage 4's `draw_sample` is uniform random for
  v1 — docs/04 step 3 suggests stratification to boost under-represented
  diseases/targets/branches once a much larger top-up is needed to move the
  coverage percentages meaningfully (see
  [12-session-log-sampling.md](12-session-log-sampling.md)).
- **Base classifier model**: PubMedBERT vs. BioBERT vs. other — decide
  after seeing stage 5's labelled data (see
  [06-classifier-training.md](06-classifier-training.md)).
- **`llm_client.py` (real Anthropic API pipeline)**: not built this
  session — stage 5's 500-row pass was done via a one-off sub-agent labelling
  run instead (user chose to avoid provisioning a separate API key). A real,
  rerunnable client is still needed before the eventual larger GWAS-merged
  rerun. See [13-session-log-llm-labelling.md](13-session-log-llm-labelling.md).
- **Entity-linking noise in labelled rows**: several rows show
  disease-label acronym collisions or bracketed-span mismatches between the
  stage-2 offsets and the actual entity discussed — flagged anecdotally by
  the labelling pass but not yet systematically audited. See
  [13-session-log-llm-labelling.md](13-session-log-llm-labelling.md).
- **Evidence score formula**: not designed yet, deferred until stage 7
  output exists (see [08-product-vision.md](08-product-vision.md)).
