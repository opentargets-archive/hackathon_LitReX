# litrex_gwas — GWAS Catalog → target–disease co-occurrences

Builds a silver training set of **target–disease textual co-occurrences** from
the papers behind recent GWAS Catalog associations, for LitReX's downstream
relation classifier. Sentence-level co-occurrence is preferred; abstract-level
is kept as a weaker signal. **This module does not assign the relation label /
directionality** — that is stage 5 (the LLM judge). It only produces the
co-occurrence + text substrate.

See the design spec: `docs/superpowers/specs/2026-07-09-gwas-cooccurrence-design.md`.

## Run

```bash
uv sync --extra dev
uv run python -m litrex_gwas.build --config config/gwas.yaml --today 2026-07-09
```

Edit `config/gwas.yaml` for input paths, the rolling window (`window_years`),
matching thresholds, and the output path. The OT disease index (~7 MB) and the
fetched abstracts are cached under `.cache/` so re-runs skip the network.

## Pipeline

1. Read the year-split association TSVs, keep rows with `DATE` within the
   rolling window, explode comma-separated `MAPPED_TRAIT_URI` into one record
   per trait.
2. Disease ID = last path segment of the trait URI; **kept only if it is in the
   Open Targets disease index** (downloaded from OT FTP). No OnToma.
3. Fetch each paper's abstract by PMID (Europe PMC primary, PubMed efetch
   fallback), cached.
4. Per paper, match its own (target, disease) pairs in text: target via an
   **alias cascade** Ensembl → gene symbol → rs ID (first tier that hits wins,
   recorded in `match_type`); disease via its label + OT synonyms. Sentence
   first, abstract fallback.
5. Write Parquet (`output/gwas_cooccurrence.parquet`, Arrow / PySpark-compatible)
   and print a numeric report.

## Output schema

One row per unique co-occurring `(pmid, target, disease, text, level)`. Columns:
`target` (Ensembl or null), `target_ensembl`, `target_symbol` (list),
`target_rsid`, `match_type`, `matched_alias`, `disease` (ontology ID),
`disease_label`, `text` (co-occurring sentence), `abstract` (full abstract),
`cooccurrence_level` (`sentence` | `abstract`), `target_span`, `disease_span`
(char offsets into `text`), `section` (`"abstract"` in v1), `publication_id`,
`publication_date`, `source` (`"gwas_catalog"`), `snp`, `p_value`.

## Observed run (release r2026-06-22, `--today 2026-07-09`)

| metric | value |
|---|---|
| association rows in window (≥ 2024-07-09) | 442,744 |
| rows kept (disease in OT index) | 435,892 |
| dropped by ontology | EFO 6,280 · HP 354 · OBA 161 · MONDO 57 |
| unique papers (PMIDs) | 391 |
| abstracts found | 389 (2 missing) |
| **co-occurrences emitted** | **445** |
| by level | sentence 107 · abstract 338 |
| by match tier | symbol 407 · rsid 37 · ensembl 1 |
| output disease prefixes | MONDO 360 · EFO 56 · HP 21 · OBA 8 |

Spot-checked sentence-level rows are correct (e.g. `rs7529220` + "atrial
fibrillation"; `PLEC` + "Alzheimer's disease" — spans land on the right
substrings).

## Known limitations / v1 notes

- **The OT disease index is broader than "diseases."** It includes OBA
  (biological-attribute / pQTL measurement traits; 17k terms) and GO, so
  membership does **not** exclude molecular/measurement traits. In this run
  only 161 OBA rows dropped, and 8 OBA co-occurrences reached the output
  (e.g. "glomerular filtration rate"). To get disease-only output, additionally
  exclude ID prefixes `OBA`/`GO` (or filter on `therapeuticAreas`) — left as a
  config decision, not hard-coded.
- **Ensembl IDs essentially never appear in abstract text** (1 match). Symbols
  and rs IDs carry the signal, as expected — the cascade handles this.
- **Abstract-level dominates** (338 vs 107). Only abstracts are mined in v1;
  Europe PMC open-access **full text** would raise both recall and the
  sentence-level share.
- Short gene symbols risk false positives; mitigated by `min_symbol_len` and
  case-sensitive word-boundary matching. Disease matching is literal (no
  morphology / no acronym expansion beyond OT synonyms).
