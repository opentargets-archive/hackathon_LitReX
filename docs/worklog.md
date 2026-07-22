# LitReX — Hackathon Worklog (Jul 8–10 2026)

Reconstructed from git history, `dataset_meta.json`, and shell/SLURM records.
Authoritative timeline = git commit timestamps.

## Where each part ran

| Part | Machine | Why |
| --- | --- | --- |
| Stages 1–5 (ingest → co-occurrence → sample → **labelling**) | **Local (Mac)** | API-bound; OpenAI/Anthropic labelling needs no GPU. Keys env-driven (`.env` / `~/.zshenv`), never in repo. |
| Stage 6a taxonomy + Stage 6b **train/val/test splits** | **Local (Mac)** | Plain CPU pandas; splits built here (Jul 9 23:00) then `rsync`'d up. |
| Stage 6 **training** (PubMedBERT) | **codon A100** | GPU-only; needs cu128 torch. |
| Stage 7 **batch inference** | **codon A100** | Runs against trained model. |

**Boundary: local = data → labelling → splits;  GPU = train → infer.**
The splits were built **locally** (contrary to first recollection) — file mtimes Jul 9 23:00, commit `037d31a` at 23:03, then pushed to `codon-gpu-015`.

## Timeline (from git)

### Tue Jul 8 — setup
- `dfd4da3` initial commit · `84d91d6` project plans · `33d7286` scaffold `litrex` package

### Wed Jul 9 — build day (whole pipeline)
- 10:31–11:50  GWAS co-occurrence module: design → scaffold → association loader, OT disease index, abstract fetch (EPMC + PubMed fallback + parquet cache), co-occurrence matching, CLI
- 12:17  measurement-trait filter + EFO/HP→MONDO name reconciliation
- 13:28  **Stage 4** representative sampling (2374 rows)
- 14:37  Europe PMC full-text corpus (abstract vs fulltext)
- 15:32  **Stage 5** LLM judge client
- 16:29–17:44  OT-EPMC FTP ingest + GWAS title corpus + PMID merge (retry/resume)
- 19:17–20:01  sampling `--include-all-source`, OpenAI provider, Batch API path
- 22:54  **Stage 6a** taxonomy (embedding nearest-prototype)
- 23:00  **Stage 6b** train/val/test splits written locally
- 23:03  `037d31a` splits + PubMedBERT trainer + SLURM job committed

### Thu Jul 10 — GPU training + tuning + presentation
- 06:45  interactive A100 `code-server` session opens (SLURM job `486902`)
- 06:50  CPU smoke-train + Intel-mac helper (`0803f0f`)
- 07:04  fix transformers-5 `save_safetensors` · 07:07 add `accelerate`
- 07:11  **fix cu128 torch so training uses the A100** (`7a3d45a`)
- 07:19  relocate uv+HF cache off home quota in SLURM script (`a39add2`)
- 07:23  A100 baseline macro-F1 0.515
- 07:32–07:48  K-fold CV + class-weight sweep → **sqrt wins** (baseline 0.472)
- 07:58  **Stage 7** batch inference scorer
- 08:02  final sqrt model metrics (**acc 0.628 / weighted-F1 0.619 / macro-F1 0.531**)
- 08:08  final session log · 09:18–11:05 outreach docs + logo

## Dataset (from `data/processed/splits/dataset_meta.json`)

- 5 classes; sizes train/val/test = **1805 / 226 / 226**, grouped by `publication_id`, stratified.
- Class balance: `no_relationship` dominates (890 train); `negative_finding` rarest (121, weight 2.97).
- Source mix ≈ 86% Open Targets / 14% GWAS Catalog.
- Entity markers `[TGT]…[/TGT] [DIS]…[/DIS]`; `min_confidence` 0.3; 5 CV folds.

## Commands — annotated for replication

Every default path below is relative to the repo root. The pipeline chains by
convention: each stage's default **output** is the next stage's default **input**,
so with defaults you can run them in order with no flags. Flags shown are the ones
that matter for reproducing *this* run.

**Prereqs**
- `uv sync` — build the env from `uv.lock` (add `--extra training` on the GPU node).
- Config is env-driven — copy `.env` (gitignored) or export in `~/.zshenv`:
  `LITREX_ANTHROPIC_API_KEY`, `LITREX_ANTHROPIC_MODEL` (e.g. `claude-sonnet-5`),
  `OPENAI_API_KEY`, `LITREX_PLATFORM_TOTAL_DISEASES`, `LITREX_PLATFORM_TOTAL_TARGETS`.
- **Stage 2 needs GCS access** (`gcloud`/`gsutil`) to read the `gs://` source — or
  use `--from-ftp` to pull the EPMC evidence dump over HTTPS instead.

### Local (Mac) — data → labelling → splits

```bash
cd ~/code/hackathon_LitReX
uv sync

# ── Stage 2: Open Targets literature co-occurrence ingest ────────────────────
#   reads : gs://open-targets-pipeline-runs/ds/26.06.0-dev2/intermediate/literature/cooccurrence
#           (GP×DS pairs, isMapped=True)  — OR the EPMC FTP dump with --from-ftp
#   writes: data/processed/cooccurrence/   (raw cached under data/raw/cooccurrence/)
uv run python -m litrex.data_sources.cooccurrence \
  --output-dir data/processed/cooccurrence \
  --sections abstract title \
  --start-date 2024-07-01            # default = 2 years ago
#   alt source (no GCS): add  --from-ftp  --ftp-url <EPMC evidence url>
#   reuse an existing download:  --skip-download

# ── Stage 3: GWAS Catalog co-occurrence corpus ───────────────────────────────
#   config: config/gwas.yaml   (source paths + output_path live here)
#   writes: output/gwas_cooccurrence_{abstract,title}.parquet
uv run python -m litrex.data_sources.gwas.build \
  --config config/gwas.yaml \
  --source both                       # {open_targets|gwas_catalog|both}

# ── Merge OT + GWAS into one uniform pool (normalises to shared schema) ───────
#   reads : the two sources below (positional)
#   writes: data/processed/merged/
uv run python -m litrex.data_sources.merge \
  data/processed/cooccurrence output/gwas_cooccurrence_abstract.parquet \
  output/gwas_cooccurrence_title.parquet \
  --output-dir data/processed/merged

# ── Stage 4: representative sample (append-only; tops up to --target-size) ────
#   reads : --input-dir (point at data/processed/merged to include GWAS)
#   writes: data/processed/sample_manifest.parquet (+ _metadata.json)
#   THIS RUN: 2000 OT rows + ALL GWAS rows via --include-all-source
uv run python -m litrex.sampling.representative_sample \
  --input-dir data/processed/merged \
  --target-size 2000 \
  --include-all-source gwas_catalog \
  --sections abstract title --seed 0
#   (--total-diseases/--total-targets default to the LITREX_PLATFORM_TOTAL_* env vars)

# ── Stage 5: LLM relationship labelling  [API calls, no GPU] ──────────────────
#   reads : data/processed/sample_manifest.parquet
#   writes: data/processed/labeled_triples.parquet  (adds judge_model provenance col)
uv run python -m litrex.labelling.llm_client  --provider anthropic   # Claude (default judge)
uv run python -m litrex.labelling.openai_client                      # OpenAI gpt-4.1 (alt judge)
#   async/cheaper:  add --batch  (uses the provider Batch API, polls every --poll-interval s)
#   smoke a few:    --limit 20        override model: --model <id>

# ── Stage 6a: close free-text relations into the fixed 5-class taxonomy ───────
#   reads : data/processed/labeled_triples.parquet
#   writes: data/processed/labeled_triples_classified.parquet + taxonomy.json
uv run python -m litrex.training.taxonomy

# ── Stage 6b: build train/val/test splits (grouped by publication_id) ─────────
#   reads : data/processed/labeled_triples_classified.parquet
#   writes: data/processed/splits/{train,val,test}.parquet + dataset_meta.json
#   min_confidence 0.3 → 1805/226/226 (this run's dataset_meta.json)
uv run python -m litrex.training.dataset --min-confidence 0.3 --seed 0

# ── CPU smoke-train: prove the whole loop before spending a GPU slot ──────────
#   writes: models/stage6_smoke/{model,metrics.json,model_card.json}
bash scripts/smoke_train_local.sh
```

### Transfer splits to the GPU node (verbatim from shell history)

```bash
rsync -av data/processed/splits/ \
  soria@codon-gpu-015:/hps/nobackup/emcdonagh/hackathon-litrex/hackathon_LitReX/data/processed/splits/
```

### codon A100 — train + infer

```bash
cd /hps/nobackup/emcdonagh/hackathon-litrex/hackathon_LitReX
uv sync --extra training           # pulls cu128 torch + accelerate (A100 / CUDA 12.8)

# ── Stage 6c: fine-tune PubMedBERT on the silver labels ───────────────────────
#   reads : data/processed/splits/
#   writes: models/stage6/{model, metrics.json, model_card.json}  (gitignored, codon-only)
#   THIS RUN's winning config: sqrt class weighting (beat uniform/inverse in CV)
uv run --extra training python -m litrex.training.train \
  --data-dir data/processed/splits --output-dir models/stage6 \
  --epochs 4 --batch-size 16 --lr 2e-5 --weight-scheme sqrt --seed 0
#   to reproduce the sweep that chose sqrt:  add --cv   (5-fold, per dataset_meta.json)
#   final test: accuracy 0.628 / weighted-F1 0.619 / macro-F1 0.531

# ── Stage 7: batch-score the trained model over a Cooccurrence corpus ─────────
#   reads : --input (required) + --model models/stage6/model
#   writes: data/processed/scored_relationships.parquet
uv run --extra training python -m litrex.inference.batch_score \
  --input data/processed/cooccurrence \
  --model models/stage6/model --batch-size 64
```

> The training also has a committed SLURM script (`037d31a`, with cache/cu128 fixes in
> `a39add2`/`7a3d45a`) — see `scripts/`. It ran inside the interactive A100
> `code-server` session (SLURM job `486902`, Jul 10), which is why `sacct` shows the
> session but no separately-named `litrex` batch job.

### Defaults chain (run with no flags, in order)

Because each stage defaults its output to the next stage's input, the minimal
replication is just the module list in order — flags above are only needed to
reproduce *this run's* specific choices (merged input, target-size 2000,
`--include-all-source`, sqrt weighting):

```
cooccurrence → gwas.build → merge → representative_sample → llm_client
→ taxonomy → dataset → [rsync] → train → batch_score
```

> ⚠️ One non-default to remember: Stage 4's default `--input-dir` is
> `data/processed/cooccurrence` (OT only). To include GWAS you must point it at
> `data/processed/merged`, as above.

## Data inventory (verified on local Mac)

| Stage | Artifact | Present? |
| --- | --- | --- |
| 2 | `data/processed/cooccurrence/` (OT ingest) | ❌ consumed/deleted at Stage 4 |
| merge | `data/processed/merged/` | ❌ consumed/deleted at Stage 4 |
| 3 | `output/gwas_cooccurrence_{abstract,title,fulltext}.parquet` | ✅ 76K / 16K / 292K |
| 4 | `data/processed/sample_manifest.parquet` (+ `_metadata.json`) | ✅ 460K — the surviving 2374-row sample |
| 5 | `data/processed/labeled_triples.parquet` | ✅ 652K |
| 6a | `labeled_triples_classified.parquet` + `taxonomy.json` | ✅ |
| 6b | `splits/{train,val,test}.parquet` + `dataset_meta.json` | ✅ |
| 6c | `models/stage6/` | ❌ codon-only |
| 7 | `data/processed/scored_relationships.parquet` | ❌ not run locally |
| — | caches: `efo_to_mondo_namematch.tsv`, `data/cache/{ensembl_gene_names,efo_disease_names,efo_graph_cache}.json` | ✅ |

**Replication consequence:** the chain is intact **from Stage 4 onward** (the surviving
`sample_manifest` is the 2374-row sample). Stages 2 + merge **cannot** be re-run from local
data — the OT co-occurrence pool and merged pool were consumed at sampling time; rebuilding
them needs GCS access (`gs://open-targets-pipeline-runs/ds/26.06.0-dev2/...`) or the EPMC FTP
`--from-ftp` path + that OT release. GWAS Stage 3 outputs survive, so that source is present.

## Not in the repo / not in the tarball

- `models/stage6/` — trained model, **codon-only** (gitignored). Copy from
  `/hps/nobackup/emcdonagh/hackathon-litrex/hackathon_LitReX/models/stage6/` if needed.
- `data/` and `output/` are gitignored artifacts — present locally, shipped only via the
  hand-packaged tarball, not via `git clone`.

**Handoff note:** the tarball bundles the labelled + split data (`sample_manifest`,
`labeled_triples`, `labeled_triples_classified`, `splits/`), so a colleague can resume
from **Stage 5 (or Stage 6b → training)** with **no GCS/gcloud access required** — the
GCS-dependent Stage 2 only matters if rebuilding the co-occurrence pool from scratch.

## Verification note

Stage 2 and Stage 4 commands are README-verified. Stages 3/5/6a and the merge are
reconstructed from module paths (`src/litrex/...`) + commit history — module names are
exact, but exact flags/args may have varied. Confirm against `--help` before rerunning.
