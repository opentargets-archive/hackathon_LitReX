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
