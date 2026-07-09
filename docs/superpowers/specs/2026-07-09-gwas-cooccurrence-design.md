# GWAS Catalog → Target–Disease Co-occurrence Module — Design

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan
**Scope:** LitReX data source module `litrex_gwas`. Implements the GWAS Catalog
branch of the pipeline described in [`docs/03-data-source-gwas-catalog.md`](../../03-data-source-gwas-catalog.md).

## 1. Summary & reframing

Doc 03 framed this module as "normalize GWAS rows to Ensembl/EFO via OnToma."
After inspecting the actual GWAS Catalog export, the framing is revised:

- The GWAS Catalog **already ships** Ensembl gene IDs (`SNP_GENE_IDS`), gene
  symbols (`MAPPED_GENE`), rs IDs (`SNPS`), and trait ontology URIs
  (`MAPPED_TRAIT_URI`). **OnToma is not needed.**
- The real deliverable for LitReX is not normalized rows but **target–disease
  textual co-occurrences** drawn from the papers behind recent GWAS
  associations: a silver training set for the downstream relation classifier
  (stages 5–6).

**This module produces co-occurrence + text. It does NOT assign the relation
label / directionality** — that is stage 5 (the LLM judge). We only preserve
enough context for that step to run.

## 2. Inputs (as downloaded, release r2026-06-22)

- Associations, year-split TSVs (`gwas-catalog-download-associations-alt.<year>.tsv`):
  `2024` (179,682 rows), `2025` (273,265), `2026` (36,355).
- The studies file is **not** used — only associations carry gene/SNP per row.

Recon facts driving the design (2024–2026 slice, 489,299 association rows):

- **~624 unique PMIDs.** Biobank-scale studies each contribute thousands of
  associations. Abstract fetching is trivial and fully cacheable — no scale
  concern.
- **Trait ontology mix** (`MAPPED_TRAIT_URI`, comma-split): EFO 62%, OBA 27%
  (molecular/pQTL "level of X in blood" — not diseases), MONDO 11%, HP 1%,
  trace GO/Orphanet/MP.
- **Target alias fill:** rs ID 100%, gene symbol 77%, Ensembl 54%,
  `REPORTED GENE(S)` empty in this alt export. Ensembl alone is thin.

## 3. Output contract (Parquet, pyarrow → PySpark-compatible)

One row per unique co-occurring `(pmid, target, disease, text, section)`.

| field | type | notes |
|---|---|---|
| `target` | str \| null | Ensembl gene ID when available, else null |
| `target_ensembl` | str \| null | from `SNP_GENE_IDS` |
| `target_symbol` | list[str] | from `MAPPED_GENE`; intergenic `A - B` → `[A, B]` |
| `target_rsid` | str | from `SNPS` (`rs\d+`) |
| `match_type` | str | tier that hit in text: `ensembl` \| `symbol` \| `rsid` |
| `matched_alias` | str | exact string matched in text |
| `disease` | str | ontology ID after index filter (EFO/MONDO/HP/…) |
| `disease_label` | str | GWAS `MAPPED_TRAIT` |
| `text` | str | the co-occurring **sentence** (tight context) |
| `abstract` | str | full abstract (broader context; target for abstract-level rows) |
| `cooccurrence_level` | str | `sentence` (stronger) \| `abstract` (weaker) |
| `target_span` | struct{start,end} | char offsets of matched target in `text` |
| `disease_span` | struct{start,end} | char offsets of matched disease in `text` |
| `section` | str | **document** section the co-occurrence sits in — always `"abstract"` in v1 (we only fetch abstracts). Fills the doc-03 contract's `section` field; distinct from `cooccurrence_level`. |
| `publication_id` | str | PMID |
| `publication_date` | date | GWAS `DATE` |
| `source` | str | sentinel `"gwas_catalog"` |
| `snp` | str | GWAS provenance (`SNPS`) |
| `p_value` | str | GWAS provenance (`P-VALUE`) |

Rows where the pair never co-occurs (not even at abstract level) are **not
emitted** but are counted in the report.

## 4. Data flow

```
associations TSVs (2024–26)
  │  filter DATE ≥ rolling 24 months (≥ 2026-07-09 minus 2yr)
  │  explode multi-trait MAPPED_TRAIT_URI on comma
  ▼
per-association record {disease_id, disease_label, target aliases, pmid, date, snp, pval}
  │  disease_id = strip ID from MAPPED_TRAIT_URI
  │  KEEP iff disease_id ∈ OT disease index   (drops OBA/GO/measurement traits)
  ▼
dedup → unique (pmid, disease_id, target) pairs
  │
  ├─ fetch abstract by PMID: Europe PMC → PubMed efetch fallback; cache to parquet
  ▼
co-occurrence matcher (per paper, over that paper's own GWAS pairs):
  sentence-split abstract (PySBD)
  for each pair:
    target: cascade Ensembl → symbol (word boundary; intergenic split) → rsid (exact)
    disease: label + OT-index synonyms, case-insensitive phrase match
    if both hit same sentence → level=sentence, text=sentence, record spans + match_type
    elif both appear anywhere in abstract → level=abstract, text=abstract
    else → drop (counted)
  ▼
Parquet output + numeric report (hit rates, tier breakdown, dropped counts)
```

## 5. Module layout (`src/` layout, `uv`, `pytest`)

```
src/litrex_gwas/
  config.py         # YAML-driven: input paths, date cutoff, match thresholds, output path
  load.py           # read association TSVs, date filter, explode traits, extract target aliases
  disease_index.py  # download + cache OT disease index; build id→{label, synonyms}; membership filter
  abstracts.py      # Europe PMC + PubMed efetch, retry/backoff (3 req/s), parquet cache
  cooccurrence.py   # PySBD sentence split, target alias cascade, disease synonym match, span offsets
  build.py          # orchestrate → write Parquet + report; entry: python -m litrex_gwas.build
tests/
  test_load.py, test_disease_index.py, test_cooccurrence.py, test_abstracts.py
```

## 6. Key design decisions

1. **Disease "is-a-disease" filter = membership in the OT disease index**
   (downloaded from OT FTP `diseases` parquet for the current platform
   release, cached locally). No OnToma. The report states how many trait IDs
   were dropped and their ontology-prefix breakdown.
2. **Disease text matching** uses the disease label plus all synonyms from the
   OT disease index, case-insensitive, on word/phrase boundaries.
3. **Target matching cascade:** Ensembl exact token → gene symbol on word
   boundaries (intergenic `A - B` → both symbols) → rs ID exact. First tier
   that hits wins; the tier is recorded in `match_type`. Nothing is dropped for
   lacking an Ensembl ID — this is a training set and we want to learn which
   alias tier yields usable co-occurrences.
4. **Sentence splitter: PySBD** (light, biomedical-abbreviation aware).
   scispaCy is a documented optional upgrade if sentence segmentation proves
   weak.
5. **Abstracts:** Europe PMC REST primary (EBI, no key, exposes full text /
   annotations), NCBI PubMed efetch fallback. Cached to parquet keyed by PMID.
6. **Window = rolling 24 months on publication `DATE`** (not calendar-year
   files). The 2024 file's Jan–Jun rows fall outside and are excluded.
7. **Dedup** to unique `(pmid, target, disease, text, section)` collapses the
   SNP-level rows (many SNPs → same gene→trait) massively.
8. **Directionality / relation label is OUT of scope** (stage 5). We preserve
   the sentence, the full abstract, and the matched-span offsets so the LLM
   judge has complete context without re-fetching.

## 7. Acceptance criteria

- `python -m litrex_gwas.build` produces Parquet conforming to §3.
- Every emitted row has a non-null `disease` (valid ontology ID in the OT
  disease index) and at least one populated target alias with a recorded
  `match_type`.
- No raw free-text trait names or unresolved URIs leak into `disease`.
- A numeric report: input rows, rows after date filter, rows after disease
  filter (+ dropped-by-ontology breakdown), unique PMIDs, abstracts fetched
  (Europe PMC vs fallback vs missing), co-occurrence counts by
  `cooccurrence_level` and `match_type`, pairs dropped for no co-occurrence.
- Module has no dependency on other LitReX stages; its only job is the Parquet
  output.

## 8. Non-goals

- OnToma normalization (unnecessary — catalog ships the IDs).
- Relation/directionality labelling (stage 5).
- Studies file, Expression Atlas, PySpark as a runtime dependency (output must
  be PySpark-*compatible*, not PySpark-*based*).
- Full-text mining beyond abstracts in v1 (Europe PMC full text is available as
  a later upgrade).
