# GWAS Catalog Co-occurrence Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `litrex_gwas` module that turns recent GWAS Catalog associations into target–disease textual co-occurrences (sentence-first, abstract-fallback), written to Parquet as a silver training set.

**Architecture:** Read year-split association TSVs → date-filter + explode multi-trait → keep disease IDs that are in the Open Targets disease index → fetch each paper's abstract (Europe PMC, PubMed fallback) → per paper, match its own (target, disease) pairs in text using a target alias cascade (Ensembl→symbol→rsid) and disease label+synonyms → emit sentence/abstract-level co-occurrence rows.

**Tech Stack:** Python 3.12, `uv`, `pandas`, `pyarrow`, `requests`, `pysbd`, `pytest`. Output Parquet is PySpark-compatible (Arrow), no PySpark runtime dependency.

## Global Constraints

- Python ≥ 3.10; developed on 3.12. `src/` layout, `uv` for deps, `pytest` for tests.
- Config via YAML (`config/gwas.yaml`), never hardcoded paths in logic. Use `pathlib.Path`.
- `logging` module, not `print`, in library code. Type hints on all signatures. NumPy-style docstrings.
- API calls: retry with exponential backoff, ≤ 3 req/sec, cache results locally (parquet) to avoid re-querying. Log every API error with URL + status.
- Output Parquet only; schema is the §3 contract of the design spec. Rows that fail to normalize (disease not in OT index) are dropped and counted, never emitted with nulls.
- Relation/directionality labelling is OUT of scope (stage 5). Preserve sentence, full abstract, and matched-span offsets only.
- Disease index source (pinned): `https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/latest/output/disease/disease.parquet` (OT platform 26.06; columns `id`, `name`, `synonyms`).
- Association input (pinned): `/Users/soria/Downloads/gwas_catalog_v1.0.2-associations_e116_r2026-06-22_split/gwas-catalog-download-associations-alt.<year>.tsv`. Relevant columns (1-based): PUBMEDID=2, DATE=4, MAPPED_GENE=15, SNP_GENE_IDS=18, SNPS=22, P-VALUE=28, MAPPED_TRAIT=35, MAPPED_TRAIT_URI=36. Read by header name, not index.
- Window: rolling 24 months on publication `DATE`; cutoff is injectable (`compute_cutoff(today, window_years=2)`) for testability.

---

## File Structure

```
config/gwas.yaml               # runtime config
src/litrex_gwas/
  __init__.py
  config.py         # Config dataclass + YAML loader + compute_cutoff
  load.py           # TSV parse, date filter, trait explode, alias extraction -> Association
  disease_index.py  # download+cache OT disease parquet -> DiseaseIndex (contains/synonyms)
  abstracts.py      # Europe PMC + PubMed fallback, rate-limited, parquet cache
  cooccurrence.py   # sentence split, target cascade + disease match, spans -> Cooccurrence
  build.py          # orchestrate -> Parquet + Report; argparse CLI
tests/
  test_config.py test_load.py test_disease_index.py test_abstracts.py test_cooccurrence.py test_build.py
  fixtures/mini_assoc.tsv  fixtures/mini_disease.parquet
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/litrex_gwas/__init__.py`, `config/gwas.yaml`, `tests/__init__.py`

**Interfaces:**
- Produces: installable package `litrex_gwas`; `pytest` runs green (no tests yet is fine — add a trivial import test).

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "litrex-gwas"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "pandas>=2.0",
    "pyarrow>=14",
    "requests>=2.31",
    "pysbd>=0.3.4",
    "pyyaml>=6",
    "defusedxml>=0.7",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/litrex_gwas"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package + config files**

`src/litrex_gwas/__init__.py`:
```python
"""LitReX GWAS Catalog co-occurrence module."""
__all__ = ["config", "load", "disease_index", "abstracts", "cooccurrence", "build"]
```

`config/gwas.yaml`:
```yaml
assoc_dir: /Users/soria/Downloads/gwas_catalog_v1.0.2-associations_e116_r2026-06-22_split
assoc_glob: "gwas-catalog-download-associations-alt.20[0-9][0-9].tsv"
window_years: 2
disease_index_url: https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/latest/output/disease/disease.parquet
cache_dir: .cache
output_path: output/gwas_cooccurrence.parquet
europepmc_base: https://www.ebi.ac.uk/europepmc/webservices/rest
pubmed_efetch_base: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
max_req_per_sec: 3.0
min_symbol_len: 2
min_disease_syn_len: 4
```

`tests/__init__.py`: empty.

- [ ] **Step 3: Sync env**

Run: `cd /Users/soria/code/hackathon_LitReX && uv sync --extra dev`
Expected: resolves and installs pandas/pyarrow/requests/pysbd/pyyaml/pytest.

- [ ] **Step 4: Smoke test**

`tests/test_config.py` (import-only for now):
```python
def test_package_imports():
    import litrex_gwas
    assert "load" in litrex_gwas.__all__
```
Run: `uv run pytest tests/test_config.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/litrex_gwas/__init__.py config/gwas.yaml tests/
git commit -m "feat: scaffold litrex_gwas package"
```

---

### Task 2: Config loader

**Files:**
- Create: `src/litrex_gwas/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass Config` with fields: `assoc_dir: Path, assoc_glob: str, window_years: int, disease_index_url: str, cache_dir: Path, output_path: Path, europepmc_base: str, pubmed_efetch_base: str, max_req_per_sec: float, min_symbol_len: int, min_disease_syn_len: int`
  - `load_config(path: Path) -> Config`
  - `compute_cutoff(today: date, window_years: int) -> date`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config.py`:
```python
from datetime import date
from pathlib import Path
from litrex_gwas.config import load_config, compute_cutoff

def test_compute_cutoff_subtracts_years():
    assert compute_cutoff(date(2026, 7, 9), 2) == date(2024, 7, 9)

def test_compute_cutoff_leap_day():
    assert compute_cutoff(date(2028, 2, 29), 2) == date(2026, 3, 1)

def test_load_config_parses_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "assoc_dir: /data\nassoc_glob: '*.tsv'\nwindow_years: 2\n"
        "disease_index_url: http://x\ncache_dir: .cache\noutput_path: out.parquet\n"
        "europepmc_base: http://e\npubmed_efetch_base: http://p\nmax_req_per_sec: 3.0\n"
        "min_symbol_len: 2\nmin_disease_syn_len: 4\n"
    )
    cfg = load_config(p)
    assert cfg.assoc_dir == Path("/data")
    assert cfg.window_years == 2
    assert cfg.max_req_per_sec == 3.0
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError: litrex_gwas.config`). `uv run pytest tests/test_config.py -v`

- [ ] **Step 3: Implement `src/litrex_gwas/config.py`**

```python
"""Configuration loading for the GWAS co-occurrence module."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import yaml


@dataclass
class Config:
    assoc_dir: Path
    assoc_glob: str
    window_years: int
    disease_index_url: str
    cache_dir: Path
    output_path: Path
    europepmc_base: str
    pubmed_efetch_base: str
    max_req_per_sec: float
    min_symbol_len: int
    min_disease_syn_len: int


def load_config(path: Path) -> Config:
    """Load a Config from a YAML file."""
    data = yaml.safe_load(Path(path).read_text())
    return Config(
        assoc_dir=Path(data["assoc_dir"]),
        assoc_glob=data["assoc_glob"],
        window_years=int(data["window_years"]),
        disease_index_url=data["disease_index_url"],
        cache_dir=Path(data["cache_dir"]),
        output_path=Path(data["output_path"]),
        europepmc_base=data["europepmc_base"],
        pubmed_efetch_base=data["pubmed_efetch_base"],
        max_req_per_sec=float(data["max_req_per_sec"]),
        min_symbol_len=int(data["min_symbol_len"]),
        min_disease_syn_len=int(data["min_disease_syn_len"]),
    )


def compute_cutoff(today: date, window_years: int) -> date:
    """Return the earliest publication date to keep (today minus window_years).

    Guards the Feb-29 case by rolling to Mar-1 when the target year has no
    Feb-29.
    """
    try:
        return today.replace(year=today.year - window_years)
    except ValueError:
        # today is Feb 29 and target year is not a leap year
        return date(today.year - window_years, 3, 1)
```

- [ ] **Step 4: Run → PASS.** `uv run pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/litrex_gwas/config.py tests/test_config.py
git commit -m "feat: config loader and date-cutoff helper"
```

---

### Task 3: Association loading

**Files:**
- Create: `src/litrex_gwas/load.py`, `tests/fixtures/mini_assoc.tsv`
- Test: `tests/test_load.py`

**Interfaces:**
- Consumes: `Config`, `compute_cutoff` (Task 2).
- Produces:
  - `@dataclass Association` with fields: `pmid: str, date: date, disease_id: str, disease_label: str, target_ensembl: str | None, target_symbols: list[str], target_rsid: str, snp: str, p_value: str`
  - `strip_trait_id(uri: str) -> str` — last path segment of a URI.
  - `parse_symbols(mapped_gene: str) -> list[str]` — split on `,` and ` - `, strip, drop empties.
  - `read_associations(paths: list[Path], cutoff: date) -> Iterator[Association]` — one Association per (row, trait); explodes aligned `MAPPED_TRAIT` / `MAPPED_TRAIT_URI` comma lists; skips rows with empty PMID or date < cutoff.

- [ ] **Step 1: Create fixture `tests/fixtures/mini_assoc.tsv`**

Tab-separated. Header must contain the real column names; include only the columns the loader reads plus a couple of ignored ones. Three data rows: one recent multi-trait row, one old row (filtered out), one recent single-trait row with an intergenic gene pair.

```
PUBMEDID	DATE	MAPPED_GENE	SNP_GENE_IDS	SNPS	P-VALUE	MAPPED_TRAIT	MAPPED_TRAIT_URI
111	2025-03-01	IL6	ENSG00000136244	rs1800795	5E-9	type 2 diabetes, obesity	http://www.ebi.ac.uk/efo/EFO_0001360, http://purl.obolibrary.org/obo/MONDO_0011122
222	2010-01-01	TCF7L2	ENSG00000148737	rs7903146	1E-30	type 2 diabetes	http://www.ebi.ac.uk/efo/EFO_0001360
333	2025-06-15	LINC02227 - EBF1		rs2914231	3E-8	asthma	http://www.ebi.ac.uk/efo/EFO_0000270
```

(Note: use real tab characters. Row 333 has an empty `SNP_GENE_IDS`.)

- [ ] **Step 2: Write failing tests `tests/test_load.py`**

```python
from datetime import date
from pathlib import Path
from litrex_gwas.load import strip_trait_id, parse_symbols, read_associations

FIX = Path(__file__).parent / "fixtures" / "mini_assoc.tsv"

def test_strip_trait_id():
    assert strip_trait_id("http://www.ebi.ac.uk/efo/EFO_0001360") == "EFO_0001360"
    assert strip_trait_id("http://purl.obolibrary.org/obo/MONDO_0011122") == "MONDO_0011122"

def test_parse_symbols_intergenic():
    assert parse_symbols("LINC02227 - EBF1") == ["LINC02227", "EBF1"]
    assert parse_symbols("IL6") == ["IL6"]
    assert parse_symbols("") == []

def test_read_associations_explodes_and_filters():
    rows = list(read_associations([FIX], cutoff=date(2024, 1, 1)))
    # old row (222, 2010) filtered; row 111 explodes into 2 traits; row 333 -> 1
    pmids = sorted(r.pmid for r in rows)
    assert pmids == ["111", "111", "333"]
    diseases = {r.disease_id for r in rows if r.pmid == "111"}
    assert diseases == {"EFO_0001360", "MONDO_0011122"}

def test_read_associations_alias_fields():
    rows = [r for r in read_associations([FIX], cutoff=date(2024, 1, 1)) if r.pmid == "333"]
    r = rows[0]
    assert r.target_ensembl is None          # empty SNP_GENE_IDS
    assert r.target_symbols == ["LINC02227", "EBF1"]
    assert r.target_rsid == "rs2914231"
    assert r.disease_label == "asthma"
```

- [ ] **Step 3: Run → FAIL.** `uv run pytest tests/test_load.py -v`

- [ ] **Step 4: Implement `src/litrex_gwas/load.py`**

```python
"""Load and normalize GWAS Catalog association rows into Association records."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator
import logging
import pandas as pd

logger = logging.getLogger(__name__)

_COLS = ["PUBMEDID", "DATE", "MAPPED_GENE", "SNP_GENE_IDS", "SNPS",
         "P-VALUE", "MAPPED_TRAIT", "MAPPED_TRAIT_URI"]


@dataclass
class Association:
    pmid: str
    date: date
    disease_id: str
    disease_label: str
    target_ensembl: str | None
    target_symbols: list[str]
    target_rsid: str
    snp: str
    p_value: str


def strip_trait_id(uri: str) -> str:
    """Return the ontology term ID (last URI path segment)."""
    return uri.rstrip("/").rsplit("/", 1)[-1].strip()


def parse_symbols(mapped_gene: str) -> list[str]:
    """Split a MAPPED_GENE cell into individual gene symbols.

    Handles intergenic pairs ('A - B') and comma-separated lists.
    """
    if not mapped_gene or not str(mapped_gene).strip():
        return []
    parts: list[str] = []
    for chunk in str(mapped_gene).split(","):
        for sym in chunk.split(" - "):
            sym = sym.strip()
            if sym:
                parts.append(sym)
    return parts


def _parse_date(raw: str) -> date | None:
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def read_associations(paths: list[Path], cutoff: date) -> Iterator[Association]:
    """Yield one Association per (row, mapped trait), filtering by date.

    Rows with empty PMID, unparseable/old date, or empty trait URI are skipped.
    MAPPED_TRAIT and MAPPED_TRAIT_URI are comma-aligned and exploded together.
    """
    for path in paths:
        df = pd.read_csv(path, sep="\t", dtype=str, usecols=lambda c: c in _COLS,
                         keep_default_na=False)
        for _, row in df.iterrows():
            pmid = row.get("PUBMEDID", "").strip()
            if not pmid:
                continue
            d = _parse_date(row.get("DATE", ""))
            if d is None or d < cutoff:
                continue
            uris = [u.strip() for u in row.get("MAPPED_TRAIT_URI", "").split(",") if u.strip()]
            labels = [t.strip() for t in row.get("MAPPED_TRAIT", "").split(",")]
            if not uris:
                continue
            ens = row.get("SNP_GENE_IDS", "").strip() or None
            symbols = parse_symbols(row.get("MAPPED_GENE", ""))
            rsid = row.get("SNPS", "").strip()
            snp = rsid
            pval = row.get("P-VALUE", "").strip()
            for i, uri in enumerate(uris):
                label = labels[i] if i < len(labels) else ""
                yield Association(
                    pmid=pmid, date=d,
                    disease_id=strip_trait_id(uri), disease_label=label,
                    target_ensembl=ens, target_symbols=symbols,
                    target_rsid=rsid, snp=snp, p_value=pval,
                )
```

- [ ] **Step 5: Run → PASS.** `uv run pytest tests/test_load.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/litrex_gwas/load.py tests/test_load.py tests/fixtures/mini_assoc.tsv
git commit -m "feat: association loader with trait explode and alias extraction"
```

---

### Task 4: OT disease index

**Files:**
- Create: `src/litrex_gwas/disease_index.py`, `tests/fixtures/mini_disease.parquet` (built by a helper in the test)
- Test: `tests/test_disease_index.py`

**Interfaces:**
- Produces:
  - `@dataclass DiseaseTerm(id: str, name: str, synonyms: list[str])`
  - `class DiseaseIndex` with `terms: dict[str, DiseaseTerm]`, `.contains(disease_id) -> bool`, `.synonyms(disease_id) -> list[str]` (name + synonyms, deduped).
  - `download_disease_index(url: str, cache_path: Path) -> Path` — download parquet once; skip if cache exists.
  - `load_disease_index(parquet_path: Path) -> DiseaseIndex` — flatten OT `synonyms` struct (`hasExactSynonym` + `hasRelatedSynonym`).

- [ ] **Step 1: Write failing tests `tests/test_disease_index.py`**

```python
from pathlib import Path
import pandas as pd
from litrex_gwas.disease_index import load_disease_index

def _make_fixture(p: Path):
    df = pd.DataFrame([
        {"id": "EFO_0001360", "name": "type 2 diabetes mellitus",
         "synonyms": {"hasExactSynonym": ["type 2 diabetes"], "hasRelatedSynonym": ["T2DM"]}},
        {"id": "EFO_0000270", "name": "asthma",
         "synonyms": {"hasExactSynonym": [], "hasRelatedSynonym": []}},
    ])
    df.to_parquet(p)

def test_load_and_contains(tmp_path):
    fx = tmp_path / "d.parquet"; _make_fixture(fx)
    idx = load_disease_index(fx)
    assert idx.contains("EFO_0001360")
    assert not idx.contains("OBA_2050609")   # molecular trait, absent

def test_synonyms_include_name(tmp_path):
    fx = tmp_path / "d.parquet"; _make_fixture(fx)
    idx = load_disease_index(fx)
    syns = idx.synonyms("EFO_0001360")
    assert "type 2 diabetes mellitus" in syns   # name included
    assert "type 2 diabetes" in syns            # exact synonym
    assert "T2DM" in syns                        # related synonym
```

- [ ] **Step 2: Run → FAIL.** `uv run pytest tests/test_disease_index.py -v`

- [ ] **Step 3: Implement `src/litrex_gwas/disease_index.py`**

```python
"""Open Targets disease index: download, load, and membership/synonym lookup."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import logging
import pandas as pd
import requests

logger = logging.getLogger(__name__)


@dataclass
class DiseaseTerm:
    id: str
    name: str
    synonyms: list[str] = field(default_factory=list)


@dataclass
class DiseaseIndex:
    terms: dict[str, DiseaseTerm]

    def contains(self, disease_id: str) -> bool:
        return disease_id in self.terms

    def synonyms(self, disease_id: str) -> list[str]:
        """Return name + all synonyms for a disease, deduped, order-preserving."""
        term = self.terms.get(disease_id)
        if term is None:
            return []
        seen: dict[str, None] = {}
        for s in [term.name, *term.synonyms]:
            if s and s not in seen:
                seen[s] = None
        return list(seen)


def download_disease_index(url: str, cache_path: Path) -> Path:
    """Download the OT disease parquet to cache_path if not already present."""
    cache_path = Path(cache_path)
    if cache_path.exists():
        logger.info("disease index cache hit: %s", cache_path)
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("downloading disease index: %s", url)
    resp = requests.get(url, timeout=300, stream=True)
    if resp.status_code != 200:
        logger.error("disease index download failed url=%s status=%s", url, resp.status_code)
        resp.raise_for_status()
    with open(cache_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
    return cache_path


def _flatten_synonyms(cell) -> list[str]:
    """Flatten an OT synonyms struct into a flat list of strings."""
    out: list[str] = []
    if cell is None:
        return out
    if isinstance(cell, dict):
        for key in ("hasExactSynonym", "hasRelatedSynonym", "hasBroadSynonym", "hasNarrowSynonym"):
            vals = cell.get(key)
            if vals is not None:
                out.extend(str(v) for v in vals)
    return out


def load_disease_index(parquet_path: Path) -> DiseaseIndex:
    """Load the OT disease parquet into a DiseaseIndex keyed by ontology ID."""
    df = pd.read_parquet(parquet_path, columns=["id", "name", "synonyms"])
    terms: dict[str, DiseaseTerm] = {}
    for rec in df.itertuples(index=False):
        terms[rec.id] = DiseaseTerm(
            id=rec.id, name=str(rec.name), synonyms=_flatten_synonyms(rec.synonyms),
        )
    logger.info("loaded %d disease terms", len(terms))
    return DiseaseIndex(terms=terms)
```

- [ ] **Step 4: Run → PASS.** `uv run pytest tests/test_disease_index.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/litrex_gwas/disease_index.py tests/test_disease_index.py
git commit -m "feat: OT disease index download, load, membership/synonyms"
```

---

### Task 5: Abstract fetching

**Files:**
- Create: `src/litrex_gwas/abstracts.py`
- Test: `tests/test_abstracts.py`

**Interfaces:**
- Produces:
  - `fetch_abstract_europepmc(pmid: str, base: str, session: requests.Session) -> str | None`
  - `fetch_abstract_pubmed(pmid: str, base: str, session: requests.Session) -> str | None`
  - `fetch_abstract(pmid, cfg, session) -> tuple[str | None, str]` — returns `(abstract, source)` where source ∈ `{"europepmc","pubmed","missing"}`; Europe PMC first, PubMed fallback.
  - `load_or_fetch_abstracts(pmids: list[str], cfg, cache_path: Path) -> dict[str, str]` — parquet cache keyed by pmid; only fetches missing; rate-limited to `cfg.max_req_per_sec`; retries with exponential backoff.

- [ ] **Step 1: Write failing tests `tests/test_abstracts.py`** (network mocked)

```python
from pathlib import Path
import requests
from litrex_gwas.abstracts import fetch_abstract_europepmc, fetch_abstract

class FakeResp:
    def __init__(self, status, json_data=None, text=""):
        self.status_code = status; self._json = json_data; self.text = text
    def json(self): return self._json
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError(str(self.status_code))

class FakeSession:
    def __init__(self, resp): self._resp = resp
    def get(self, url, **kw): return self._resp

def test_europepmc_parses_abstract():
    payload = {"resultList": {"result": [{"abstractText": "TCF7L2 is linked to type 2 diabetes."}]}}
    s = FakeSession(FakeResp(200, payload))
    assert fetch_abstract_europepmc("222", "http://e", s) == "TCF7L2 is linked to type 2 diabetes."

def test_europepmc_missing_returns_none():
    s = FakeSession(FakeResp(200, {"resultList": {"result": []}}))
    assert fetch_abstract_europepmc("999", "http://e", s) is None
```

- [ ] **Step 2: Run → FAIL.** `uv run pytest tests/test_abstracts.py -v`

- [ ] **Step 3: Implement `src/litrex_gwas/abstracts.py`**

```python
"""Fetch and cache paper abstracts by PMID (Europe PMC + PubMed fallback)."""
from __future__ import annotations
from pathlib import Path
import logging
import time
import pandas as pd
import requests
# defusedxml guards against XXE / billion-laughs in the external PubMed XML.
from defusedxml import ElementTree as ET

logger = logging.getLogger(__name__)


def fetch_abstract_europepmc(pmid: str, base: str, session: requests.Session) -> str | None:
    """Fetch an abstract from Europe PMC. Returns None if not found."""
    url = f"{base}/search"
    params = {"query": f"EXT_ID:{pmid} AND SRC:MED", "resultType": "core",
              "format": "json", "pageSize": 1}
    resp = session.get(url, params=params, timeout=60)
    if resp.status_code != 200:
        logger.error("europepmc error pmid=%s url=%s status=%s", pmid, url, resp.status_code)
        return None
    results = resp.json().get("resultList", {}).get("result", [])
    if not results:
        return None
    text = results[0].get("abstractText")
    return text or None


def fetch_abstract_pubmed(pmid: str, base: str, session: requests.Session) -> str | None:
    """Fetch an abstract from NCBI PubMed efetch (XML). Returns None if not found."""
    params = {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"}
    resp = session.get(base, params=params, timeout=60)
    if resp.status_code != 200:
        logger.error("pubmed error pmid=%s status=%s", pmid, resp.status_code)
        return None
    try:
        root = ET.fromstring(resp.text)
    except Exception as exc:  # defusedxml raises on malformed/unsafe XML
        logger.error("pubmed xml parse failed pmid=%s err=%s", pmid, exc)
        return None
    parts = [el.text or "" for el in root.iter("AbstractText")]
    text = " ".join(p.strip() for p in parts if p.strip())
    return text or None


def fetch_abstract(pmid: str, cfg, session: requests.Session) -> tuple[str | None, str]:
    """Europe PMC first, PubMed fallback. Returns (abstract, source)."""
    text = fetch_abstract_europepmc(pmid, cfg.europepmc_base, session)
    if text:
        return text, "europepmc"
    text = fetch_abstract_pubmed(pmid, cfg.pubmed_efetch_base, session)
    if text:
        return text, "pubmed"
    return None, "missing"


def _fetch_with_retry(pmid: str, cfg, session: requests.Session,
                      max_tries: int = 4) -> tuple[str | None, str]:
    delay = 1.0
    for attempt in range(1, max_tries + 1):
        try:
            return fetch_abstract(pmid, cfg, session)
        except requests.RequestException as exc:
            logger.warning("fetch retry pmid=%s attempt=%d err=%s", pmid, attempt, exc)
            if attempt == max_tries:
                return None, "missing"
            time.sleep(delay)
            delay *= 2
    return None, "missing"


def load_or_fetch_abstracts(pmids: list[str], cfg, cache_path: Path) -> dict[str, str]:
    """Return {pmid: abstract} for all pmids, using a parquet cache.

    Only PMIDs absent from cache are fetched, rate-limited to cfg.max_req_per_sec.
    Missing abstracts are cached as empty strings so they are not re-fetched.
    """
    cache_path = Path(cache_path)
    cached: dict[str, str] = {}
    if cache_path.exists():
        cdf = pd.read_parquet(cache_path)
        cached = dict(zip(cdf["pmid"].astype(str), cdf["abstract"].astype(str)))
    todo = [p for p in dict.fromkeys(pmids) if p not in cached]
    logger.info("abstracts: %d cached, %d to fetch", len(cached), len(todo))
    if todo:
        session = requests.Session()
        min_interval = 1.0 / cfg.max_req_per_sec
        for pmid in todo:
            t0 = time.monotonic()
            text, source = _fetch_with_retry(pmid, cfg, session)
            cached[pmid] = text or ""
            logger.debug("fetched pmid=%s source=%s len=%d", pmid, source, len(text or ""))
            elapsed = time.monotonic() - t0
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        out = pd.DataFrame({"pmid": list(cached), "abstract": list(cached.values())})
        out.to_parquet(cache_path, index=False)
    return {p: t for p, t in cached.items() if t}
```

- [ ] **Step 4: Run → PASS.** `uv run pytest tests/test_abstracts.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/litrex_gwas/abstracts.py tests/test_abstracts.py
git commit -m "feat: abstract fetching with Europe PMC + PubMed fallback and parquet cache"
```

---

### Task 6: Co-occurrence matching

**Files:**
- Create: `src/litrex_gwas/cooccurrence.py`
- Test: `tests/test_cooccurrence.py`

**Interfaces:**
- Consumes: `Association` (Task 3), `DiseaseIndex` (Task 4).
- Produces:
  - `split_sentences(text: str) -> list[str]` — PySBD segmentation.
  - `find_target(text: str, assoc: Association, min_symbol_len: int) -> tuple[str, str, tuple[int, int]] | None` — cascade Ensembl→symbol→rsid; returns `(match_type, matched_alias, (start, end))` or None.
  - `find_disease(text: str, synonyms: list[str], min_len: int) -> tuple[str, tuple[int, int]] | None` — longest-synonym-first phrase match; returns `(matched_alias, span)` or None.
  - `@dataclass Cooccurrence` — the output row (fields = §3 schema).
  - `@dataclass DropStats(no_disease_syn: int, no_disease_in_text: int, no_target_in_text: int, no_cooccurrence: int)`
  - `build_cooccurrences(assocs: list[Association], abstract: str, idx: DiseaseIndex, cfg) -> tuple[list[Cooccurrence], DropStats]` — dedups pairs, matches sentence-first then abstract-level.

- [ ] **Step 1: Write failing tests `tests/test_cooccurrence.py`**

```python
from datetime import date
from litrex_gwas.load import Association
from litrex_gwas.disease_index import DiseaseIndex, DiseaseTerm
from litrex_gwas.cooccurrence import (
    split_sentences, find_target, find_disease, build_cooccurrences,
)

class Cfg:  # minimal stand-in for Config
    min_symbol_len = 2
    min_disease_syn_len = 4

def _assoc(**kw):
    base = dict(pmid="1", date=date(2025, 1, 1), disease_id="EFO_0000270",
                disease_label="asthma", target_ensembl=None,
                target_symbols=["IL6"], target_rsid="rs1800795", snp="rs1800795", p_value="5E-9")
    base.update(kw); return Association(**base)

IDX = DiseaseIndex(terms={"EFO_0000270": DiseaseTerm("EFO_0000270", "asthma", ["bronchial asthma"])})

def test_split_sentences():
    s = split_sentences("IL6 is a gene. It affects asthma.")
    assert len(s) == 2

def test_find_target_symbol_cascade():
    mt = find_target("Variants near IL6 were found.", _assoc(target_ensembl="ENSG9"), 2)
    assert mt[0] == "symbol" and mt[1] == "IL6"

def test_find_target_prefers_ensembl():
    mt = find_target("ENSG9 tags IL6 here.", _assoc(target_ensembl="ENSG9"), 2)
    assert mt[0] == "ensembl"

def test_find_disease_phrase():
    md = find_disease("Patients with bronchial asthma improved.", ["asthma", "bronchial asthma"], 4)
    assert md[0] == "bronchial asthma"   # longest-first

def test_build_sentence_level():
    abstract = "IL6 variants are associated with asthma in this cohort. Unrelated sentence."
    rows, drops = build_cooccurrences([_assoc()], abstract, IDX, Cfg())
    assert len(rows) == 1
    r = rows[0]
    assert r.cooccurrence_level == "sentence"
    assert r.match_type == "symbol"
    assert r.disease == "EFO_0000270"
    assert "asthma" in r.text.lower()

def test_build_abstract_level_fallback():
    abstract = "IL6 is studied here. A separate line mentions asthma prevalence."
    rows, drops = build_cooccurrences([_assoc()], abstract, IDX, Cfg())
    assert len(rows) == 1
    assert rows[0].cooccurrence_level == "abstract"

def test_build_drops_when_absent():
    rows, drops = build_cooccurrences([_assoc()], "No relevant terms here.", IDX, Cfg())
    assert rows == []
    assert drops.no_target_in_text + drops.no_disease_in_text + drops.no_cooccurrence >= 1
```

- [ ] **Step 2: Run → FAIL.** `uv run pytest tests/test_cooccurrence.py -v`

- [ ] **Step 3: Implement `src/litrex_gwas/cooccurrence.py`**

```python
"""Match GWAS (target, disease) pairs against paper text to emit co-occurrences."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import logging
import re
import pysbd

from .load import Association
from .disease_index import DiseaseIndex

logger = logging.getLogger(__name__)
_SEG = pysbd.Segmenter(language="en", clean=False)


def split_sentences(text: str) -> list[str]:
    """Segment text into sentences (PySBD)."""
    if not text:
        return []
    return [s.strip() for s in _SEG.segment(text) if s.strip()]


def _word_span(text: str, token: str, ignore_case: bool) -> tuple[int, int] | None:
    flags = re.IGNORECASE if ignore_case else 0
    pat = r"(?<![A-Za-z0-9-])" + re.escape(token) + r"(?![A-Za-z0-9-])"
    m = re.search(pat, text, flags)
    return (m.start(), m.end()) if m else None


def find_target(text: str, assoc: Association, min_symbol_len: int):
    """Cascade-match a target alias in text: Ensembl → symbol → rsid.

    Returns (match_type, matched_alias, (start, end)) or None.
    """
    if assoc.target_ensembl:
        sp = _word_span(text, assoc.target_ensembl, ignore_case=True)
        if sp:
            return "ensembl", assoc.target_ensembl, sp
    for sym in assoc.target_symbols:
        if len(sym) < min_symbol_len:
            continue
        sp = _word_span(text, sym, ignore_case=False)
        if sp:
            return "symbol", sym, sp
    if assoc.target_rsid:
        sp = _word_span(text, assoc.target_rsid, ignore_case=True)
        if sp:
            return "rsid", assoc.target_rsid, sp
    return None


def find_disease(text: str, synonyms: list[str], min_len: int):
    """Phrase-match the longest qualifying disease synonym in text.

    Returns (matched_alias, (start, end)) or None.
    """
    for syn in sorted((s for s in synonyms if len(s) >= min_len), key=len, reverse=True):
        sp = _word_span(text, syn, ignore_case=True)
        if sp:
            return syn, sp
    return None


@dataclass
class Cooccurrence:
    target: str | None
    target_ensembl: str | None
    target_symbol: list[str]
    target_rsid: str
    match_type: str
    matched_alias: str
    disease: str
    disease_label: str
    text: str
    abstract: str
    cooccurrence_level: str
    target_span: tuple[int, int]
    disease_span: tuple[int, int]
    section: str
    publication_id: str
    publication_date: date
    source: str
    snp: str
    p_value: str


@dataclass
class DropStats:
    no_disease_syn: int = 0
    no_disease_in_text: int = 0
    no_target_in_text: int = 0
    no_cooccurrence: int = 0


def _pair_key(a: Association) -> tuple:
    return (a.disease_id, a.target_ensembl, tuple(a.target_symbols), a.target_rsid)


def build_cooccurrences(assocs: list[Association], abstract: str,
                        idx: DiseaseIndex, cfg) -> tuple[list[Cooccurrence], DropStats]:
    """Emit co-occurrence rows for a paper's unique (target, disease) pairs.

    Sentence-level match preferred; abstract-level fallback; else dropped/counted.
    """
    drops = DropStats()
    out: list[Cooccurrence] = []
    seen: set[tuple] = set()
    sentences = split_sentences(abstract)
    for a in assocs:
        key = _pair_key(a)
        if key in seen:
            continue
        seen.add(key)
        syns = idx.synonyms(a.disease_id)
        if not syns:
            drops.no_disease_syn += 1
            continue
        # sentence-level
        hit = None
        for sent in sentences:
            mt = find_target(sent, a, cfg.min_symbol_len)
            md = find_disease(sent, syns, cfg.min_disease_syn_len)
            if mt and md:
                hit = (sent, mt, md, "sentence")
                break
        if hit is None:
            # abstract-level fallback
            mt = find_target(abstract, a, cfg.min_symbol_len)
            md = find_disease(abstract, syns, cfg.min_disease_syn_len)
            if not mt and not md:
                drops.no_cooccurrence += 1; continue
            if not mt:
                drops.no_target_in_text += 1; continue
            if not md:
                drops.no_disease_in_text += 1; continue
            hit = (abstract, mt, md, "abstract")
        text, (mtype, malias, tspan), (dalias, dspan), level = hit
        out.append(Cooccurrence(
            target=a.target_ensembl, target_ensembl=a.target_ensembl,
            target_symbol=a.target_symbols, target_rsid=a.target_rsid,
            match_type=mtype, matched_alias=malias,
            disease=a.disease_id, disease_label=a.disease_label,
            text=text, abstract=abstract, cooccurrence_level=level,
            target_span=tspan, disease_span=dspan, section="abstract",
            publication_id=a.pmid, publication_date=a.date, source="gwas_catalog",
            snp=a.snp, p_value=a.p_value,
        ))
    return out, drops
```

- [ ] **Step 4: Run → PASS.** `uv run pytest tests/test_cooccurrence.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/litrex_gwas/cooccurrence.py tests/test_cooccurrence.py
git commit -m "feat: sentence/abstract co-occurrence matching with alias cascade"
```

---

### Task 7: Build orchestration + CLI + report

**Files:**
- Create: `src/litrex_gwas/build.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: all prior modules.
- Produces:
  - `@dataclass Report` — counts: `assoc_rows, after_date, after_disease_filter, dropped_by_ontology: dict[str,int], unique_pmids, abstracts_found, cooccurrences, by_level: dict[str,int], by_match_type: dict[str,int], drops: DropStats`.
  - `cooccurrences_to_frame(rows: list[Cooccurrence]) -> pd.DataFrame`
  - `run(cfg: Config, today: date) -> Report` — full pipeline; writes Parquet to `cfg.output_path`.
  - `main(argv: list[str] | None = None) -> None` — argparse CLI (`--config`, `--today` optional override).

- [ ] **Step 1: Write failing test `tests/test_build.py`** (end-to-end with fixtures, network stubbed via monkeypatch)

```python
from datetime import date
from pathlib import Path
import pandas as pd
import litrex_gwas.build as build
from litrex_gwas.config import Config
from litrex_gwas.disease_index import DiseaseIndex, DiseaseTerm

FIX = Path(__file__).parent / "fixtures"

def _cfg(tmp_path):
    return Config(
        assoc_dir=FIX, assoc_glob="mini_assoc.tsv", window_years=2,
        disease_index_url="http://x", cache_dir=tmp_path / "cache",
        output_path=tmp_path / "out.parquet",
        europepmc_base="http://e", pubmed_efetch_base="http://p",
        max_req_per_sec=1000.0, min_symbol_len=2, min_disease_syn_len=4,
    )

def test_run_end_to_end(tmp_path, monkeypatch):
    idx = DiseaseIndex(terms={
        "EFO_0001360": DiseaseTerm("EFO_0001360", "type 2 diabetes", []),
        "EFO_0000270": DiseaseTerm("EFO_0000270", "asthma", []),
        # MONDO_0011122 intentionally absent -> dropped
    })
    monkeypatch.setattr(build, "_prepare_disease_index", lambda cfg: idx)
    abstracts = {
        "111": "IL6 variants are associated with type 2 diabetes in this study.",
        "333": "EBF1 near-variants show a link to asthma risk.",
    }
    monkeypatch.setattr(build, "_prepare_abstracts", lambda cfg, pmids: abstracts)

    rep = build.run(_cfg(tmp_path), today=date(2026, 7, 9))
    df = pd.read_parquet(tmp_path / "out.parquet")
    assert rep.cooccurrences == len(df) >= 2
    assert set(df["disease"]) <= {"EFO_0001360", "EFO_0000270"}   # MONDO dropped
    assert "MONDO_0011122" in rep.dropped_by_ontology
    assert rep.by_level.get("sentence", 0) >= 2
```

- [ ] **Step 2: Run → FAIL.** `uv run pytest tests/test_build.py -v`

- [ ] **Step 3: Implement `src/litrex_gwas/build.py`**

```python
"""Orchestrate the GWAS co-occurrence pipeline and write Parquet output."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
import argparse
import json
import logging
import pandas as pd

from .config import Config, load_config, compute_cutoff
from .load import read_associations, Association
from .disease_index import download_disease_index, load_disease_index, DiseaseIndex
from .abstracts import load_or_fetch_abstracts
from .cooccurrence import build_cooccurrences, Cooccurrence, DropStats

logger = logging.getLogger(__name__)


@dataclass
class Report:
    assoc_rows: int = 0
    after_date: int = 0
    after_disease_filter: int = 0
    dropped_by_ontology: dict[str, int] = field(default_factory=dict)
    unique_pmids: int = 0
    abstracts_found: int = 0
    cooccurrences: int = 0
    by_level: dict[str, int] = field(default_factory=dict)
    by_match_type: dict[str, int] = field(default_factory=dict)
    drops: dict[str, int] = field(default_factory=dict)


def _prepare_disease_index(cfg: Config) -> DiseaseIndex:
    path = download_disease_index(cfg.disease_index_url, cfg.cache_dir / "disease.parquet")
    return load_disease_index(path)


def _prepare_abstracts(cfg: Config, pmids: list[str]) -> dict[str, str]:
    return load_or_fetch_abstracts(pmids, cfg, cfg.cache_dir / "abstracts.parquet")


def _ontology_prefix(disease_id: str) -> str:
    return disease_id.split("_", 1)[0] if disease_id else "?"


def cooccurrences_to_frame(rows: list[Cooccurrence]) -> pd.DataFrame:
    records = []
    for r in rows:
        d = asdict(r)
        d["target_span"] = list(r.target_span)
        d["disease_span"] = list(r.disease_span)
        records.append(d)
    return pd.DataFrame.from_records(records)


def run(cfg: Config, today: date) -> Report:
    """Run the full pipeline and write Parquet output. Returns a Report."""
    rep = Report()
    cutoff = compute_cutoff(today, cfg.window_years)
    paths = sorted(cfg.assoc_dir.glob(cfg.assoc_glob))
    logger.info("reading %d association files (cutoff=%s)", len(paths), cutoff)

    idx = _prepare_disease_index(cfg)

    # load + date filter + disease filter, grouped by pmid
    by_pmid: dict[str, list[Association]] = {}
    for a in read_associations(paths, cutoff):
        rep.after_date += 1
        if not idx.contains(a.disease_id):
            rep.dropped_by_ontology[_ontology_prefix(a.disease_id)] = \
                rep.dropped_by_ontology.get(_ontology_prefix(a.disease_id), 0) + 1
            continue
        rep.after_disease_filter += 1
        by_pmid.setdefault(a.pmid, []).append(a)

    rep.unique_pmids = len(by_pmid)
    abstracts = _prepare_abstracts(cfg, list(by_pmid))
    rep.abstracts_found = len(abstracts)

    all_rows: list[Cooccurrence] = []
    totals = DropStats()
    for pmid, assocs in by_pmid.items():
        abstract = abstracts.get(pmid)
        if not abstract:
            continue
        rows, drops = build_cooccurrences(assocs, abstract, idx, cfg)
        all_rows.extend(rows)
        for k in vars(drops):
            setattr(totals, k, getattr(totals, k) + getattr(drops, k))

    rep.cooccurrences = len(all_rows)
    for r in all_rows:
        rep.by_level[r.cooccurrence_level] = rep.by_level.get(r.cooccurrence_level, 0) + 1
        rep.by_match_type[r.match_type] = rep.by_match_type.get(r.match_type, 0) + 1
    rep.drops = vars(totals)

    cfg.output_path.parent.mkdir(parents=True, exist_ok=True)
    df = cooccurrences_to_frame(all_rows)
    df.to_parquet(cfg.output_path, index=False)
    logger.info("wrote %d co-occurrences to %s", len(df), cfg.output_path)
    return rep


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build GWAS target-disease co-occurrences.")
    parser.add_argument("--config", type=Path, default=Path("config/gwas.yaml"))
    parser.add_argument("--today", type=lambda s: date.fromisoformat(s), default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    today = args.today or date.today()
    rep = run(cfg, today)
    print(json.dumps(asdict(rep), indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run → PASS.** `uv run pytest tests/test_build.py -v`

- [ ] **Step 5: Full suite green.** `uv run pytest -v`

- [ ] **Step 6: Commit**

```bash
git add src/litrex_gwas/build.py tests/test_build.py
git commit -m "feat: pipeline orchestration, CLI, and numeric report"
```

---

### Task 8: Live end-to-end run + README

**Files:**
- Create: `src/litrex_gwas/README.md` (usage + reported numbers)

**Interfaces:** none new — this task validates the real pipeline and documents observed numbers.

- [ ] **Step 1: Run against the real data** (downloads OT disease parquet ~; fetches ~624 abstracts — one-time, cached)

Run: `cd /Users/soria/code/hackathon_LitReX && uv run python -m litrex_gwas.build --config config/gwas.yaml --today 2026-07-09`
Expected: JSON report to stdout; `output/gwas_cooccurrence.parquet` written. Capture the report numbers.

- [ ] **Step 2: Sanity-check output**

Run: `uv run python -c "import pandas as pd; df=pd.read_parquet('output/gwas_cooccurrence.parquet'); print(df.shape); print(df[['disease','disease_label','match_type','cooccurrence_level']].head(10).to_string()); print(df['match_type'].value_counts()); print(df['cooccurrence_level'].value_counts())"`
Expected: non-empty; every `disease` is an ontology ID; `match_type` ∈ {ensembl,symbol,rsid}; both levels present.

- [ ] **Step 3: Spot-check 5 rows** — read `text`, confirm the `matched_alias` target and disease phrase genuinely co-occur in the sentence. Note any false positives in the README.

- [ ] **Step 4: Write `src/litrex_gwas/README.md`** — how to configure/run, the output schema (§3), and the observed report numbers from Step 1 (hit rates, tier breakdown, dropped-by-ontology).

- [ ] **Step 5: Commit**

```bash
git add src/litrex_gwas/README.md output/.gitkeep 2>/dev/null; git add src/litrex_gwas/README.md
git commit -m "docs: usage README and observed co-occurrence run numbers"
```

---

## Self-Review Notes

- **Spec coverage:** §3 schema → Task 6 `Cooccurrence` + Task 7 frame; disease-index filter → Task 4 + Task 7 `run`; alias cascade → Task 6 `find_target`; abstracts EuropePMC+PubMed → Task 5; rolling-24mo → Task 2 `compute_cutoff` + Task 7; report → Task 7 `Report`; out-of-scope directionality → preserved via `text`/`abstract`/spans in Task 6.
- **Type consistency:** `Association`, `DiseaseIndex.contains/synonyms`, `Cooccurrence`, `DropStats`, `Config` field names are referenced identically across tasks.
- **Known v1 limitations to note in README:** short gene symbols (e.g. `AR`) risk false positives (mitigated by `min_symbol_len` + case-sensitive word-boundary match); disease synonym matching is literal (no morphology); `.cache/` and `output/` should be gitignored (verify `.gitignore`).
