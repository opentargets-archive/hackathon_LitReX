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
    is_measurement: bool = False


@dataclass
class DiseaseIndex:
    terms: dict[str, DiseaseTerm]
    name_to_id: dict[str, str] = field(default_factory=dict)

    def contains(self, disease_id: str) -> bool:
        return disease_id in self.terms

    def is_measurement(self, disease_id: str) -> bool:
        """True if the term is a measurement/biological-attribute trait, not a disease."""
        term = self.terms.get(disease_id)
        return bool(term and term.is_measurement)

    def resolve_name(self, label: str) -> str | None:
        """Return the canonical OT disease ID for an exact (case-insensitive) name/synonym.

        Used to reconcile GWAS trait IDs that OT has superseded (e.g. an EFO ID
        canonicalized to a MONDO ID) when the trait name is identical.
        """
        if not label:
            return None
        return self.name_to_id.get(label.strip().lower())

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


def _contains_ta(cell, ta_id: str) -> bool:
    """True if an OT therapeuticAreas cell contains ta_id (handles list/ndarray/None)."""
    if cell is None:
        return False
    try:
        return ta_id in list(cell)
    except TypeError:
        return cell == ta_id


def load_disease_index(parquet_path: Path, measurement_ta_id: str = "EFO_0001444") -> DiseaseIndex:
    """Load the OT disease parquet into a DiseaseIndex keyed by ontology ID.

    Terms whose therapeuticAreas include ``measurement_ta_id`` are flagged as
    measurement traits (not diseases). A name/synonym -> canonical-ID map is
    built for reconciling superseded IDs, preferring MONDO on collision.
    """
    df = pd.read_parquet(parquet_path, columns=["id", "name", "synonyms", "therapeuticAreas"])
    terms: dict[str, DiseaseTerm] = {}
    name_to_id: dict[str, str] = {}

    def _register_name(label: str, ident: str) -> None:
        if not label:
            return
        key = str(label).strip().lower()
        if not key:
            return
        prior = name_to_id.get(key)
        if prior is None or (ident.startswith("MONDO_") and not prior.startswith("MONDO_")):
            name_to_id[key] = ident

    for rec in df.itertuples(index=False):
        syns = _flatten_synonyms(rec.synonyms)
        terms[rec.id] = DiseaseTerm(
            id=rec.id, name=str(rec.name), synonyms=syns,
            is_measurement=_contains_ta(rec.therapeuticAreas, measurement_ta_id),
        )
        _register_name(rec.name, rec.id)
        for s in syns:
            _register_name(s, rec.id)

    logger.info("loaded %d disease terms (%d measurement-tagged)",
                len(terms), sum(t.is_measurement for t in terms.values()))
    return DiseaseIndex(terms=terms, name_to_id=name_to_id)
