# litrex.data_sources.gwas — GWAS Catalog → target–disease co-occurrences

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
# both corpora + comparison (default); or --source abstract | fulltext
uv run python -m litrex.data_sources.gwas.build --config config/gwas.yaml --today 2026-07-09 --source both
```

Writes one Parquet per corpus — `output/gwas_cooccurrence_abstract.parquet` and
`…_fulltext.parquet` — and prints a per-source report plus a `comparison` block.
Edit `config/gwas.yaml` for input paths, the rolling window (`window_years`),
matching thresholds, and disease-cleanup flags. The OT disease index (~7 MB),
abstracts, and full text are cached under `.cache/` so re-runs skip the network.

**Text sources.** `abstract` mines the PMID's abstract (Europe PMC → PubMed
fallback). `fulltext` mines Europe PMC open-access full text (JATS → plain
text), available for the OA subset only (~180/240 papers here). The two are
complementary — full text finds far more, but non-OA papers are abstract-only —
so the recommended training set is the **union** of both outputs.

## Pipeline

1. Read the year-split association TSVs, keep rows with `DATE` within the
   rolling window, explode comma-separated `MAPPED_TRAIT_URI` into one record
   per trait.
2. Disease ID = last path segment of the trait URI; **kept only if it resolves
   to a real disease in the Open Targets disease index** (downloaded from OT
   FTP). No OnToma. Two cleanups applied:
   - **Measurement filter** — terms whose OT `therapeuticAreas` include
     `EFO_0001444` ("measurement") are dropped. This removes OBA molecular/pQTL
     traits *and* EFO measurement traits (body height, BMI, lipid/blood-pressure
     measurements). 0 MONDO diseases carry this tag, so it is disease-safe.
   - **Name reconciliation** — a GWAS trait ID that OT has superseded (e.g. an
     EFO/HP ID canonicalized to MONDO) is recovered when its trait name exactly
     matches an OT disease name/synonym, and the output ID is canonicalized.
     Recovered mappings are logged to `data/efo_to_mondo_namematch.tsv`.
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
| dropped — measurement traits (therapeuticArea filter) | 377,598 (85%) |
| dropped — unresolvable ID | EFO 6,272 · OBA 161 · MONDO 57 · HP 4 |
| reconciled by exact name (EFO/HP → MONDO) | 358 rows (18 distinct IDs) |
| rows kept (real diseases) | 58,652 |
| unique papers (PMIDs) | 240 |
| abstracts found | 390 (cache) |
| **co-occurrences emitted** | **423** |
| by level | sentence 99 · abstract 324 |
| by match tier | symbol 386 · rsid 36 · ensembl 1 |
| output disease prefixes | **MONDO 373 · EFO 29 · HP 21 · OBA 0** |

The measurement filter removes 85% of trait-rows (body height, BMI, lipid and
blood-pressure measurements) but costs almost no co-occurrences (445 → 423) —
those traits rarely co-occurred in abstracts anyway. Output is now disease-only
(0 OBA / 0 measurement). Spot-checked sentence-level rows are correct (e.g.
`rs7529220` + "atrial fibrillation"; `PLEC` + "Alzheimer's disease" — spans land
on the right substrings).

## Abstract vs full text (`--source both`)

| metric | abstract | full text |
|---|--:|--:|
| co-occurrences | 423 | **2,552** |
| unique (target, disease) pairs | 346 | **1,465** |
| sentence-level (high-confidence) | 99 | **568** |
| papers with ≥1 hit | 118 | 146 |
| papers with text available | 390 | 180 (OA only) |

Cross-corpus: **252 pairs shared, 1,213 full-text-only, 94 abstract-only.** Full
text yields ~4× the unique pairs and ~6× the sentence-level co-occurrences, but
the 94 abstract-only pairs come from non-OA papers that have no full text — so
neither source dominates and the union is the right training set. Full-text
sentence-level spot-checks are clean (e.g. `ABCG2` + gout, `APOE` + liver
disease).

## Known limitations / v1 notes

- **The OT disease index is broader than "diseases"** — it includes OBA
  (biological-attribute / pQTL measurement traits; 17k terms) and EFO
  measurements. This is handled by the `drop_measurement` therapeuticArea
  filter (config); set it to `false` to keep measurement traits. Note a raw
  `OBA`-prefix filter is *insufficient* — most EFO terms (7.6k/9.3k) are also
  measurements.
- **Name reconciliation is exact-match only** — it recovers superseded IDs whose
  trait name matches an OT disease name/synonym verbatim (18 IDs this run). IDs
  with no in-index key and no exact-name match are still dropped (8k rows, ~1.5%);
  fuzzy/xref-based mapping is a possible v2 (this is what OnToma would do).
- **GO terms leak (~0.4%)** — 11 full-text co-occurrences map to GO biological
  processes, which sit in the OT disease index and are not measurement-tagged.
  Add `GO` to an ontology-prefix exclusion if disease-only purity matters.
- **Full-text matching is slow** (~30 min for 180 papers) — PySBD sentence
  segmentation over whole papers, ×many pairs. Fine for a one-off silver-set
  build (cached afterwards); would need optimizing (e.g. per-paper alias index)
  for repeated runs.
- **Ensembl IDs essentially never appear in abstract text** (1 match). Symbols
  and rs IDs carry the signal, as expected — the cascade handles this.
- **Abstract-level dominates** (338 vs 107). Only abstracts are mined in v1;
  Europe PMC open-access **full text** would raise both recall and the
  sentence-level share.
- Short gene symbols risk false positives; mitigated by `min_symbol_len` and
  case-sensitive word-boundary matching. Disease matching is literal (no
  morphology / no acronym expansion beyond OT synonyms).
