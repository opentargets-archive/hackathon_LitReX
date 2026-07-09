"""Target/disease ID -> display-name lookup for prompt construction (docs/05 step 2).

`target` values are Ensembl gene IDs (docs/02); `disease` values are EFO/MONDO/HP
IDs. Both are resolved live from public reference APIs rather than a bundled
dataset -- same rationale as `sampling/therapeutic_area.py` (docs/12 session
log): no discoverable static file, small lookup volume for a labelling sample,
results cached to disk so repeat runs don't re-fetch.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from litrex.sampling.therapeutic_area import candidate_iris

_ENSEMBL_LOOKUP_URL = "https://rest.ensembl.org/lookup/id"
_OLS_TERMS_URL = "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms"
_ENSEMBL_BATCH_SIZE = 1000

DEFAULT_TARGET_CACHE_PATH = Path("data/cache/ensembl_gene_names.json")
DEFAULT_DISEASE_CACHE_PATH = Path("data/cache/efo_disease_names.json")


def _load_cache(path: str | Path) -> dict[str, str]:
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else {}


def _save_cache(path: str | Path, cache: dict[str, str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _fetch_ensembl_batch(ids: list[str]) -> dict[str, str]:
    body = json.dumps({"ids": ids}).encode("utf-8")
    request = urllib.request.Request(
        _ENSEMBL_LOOKUP_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {}
    return {
        gene_id: info["display_name"]
        for gene_id, info in data.items()
        if info and "display_name" in info
    }


def target_names(
    gene_ids: list[str], cache_path: str | Path = DEFAULT_TARGET_CACHE_PATH
) -> dict[str, str]:
    """Resolve Ensembl gene IDs to display names (gene symbols) via Ensembl REST."""
    cache = _load_cache(cache_path)
    missing = sorted({g for g in gene_ids if g not in cache})
    for i in range(0, len(missing), _ENSEMBL_BATCH_SIZE):
        batch = missing[i : i + _ENSEMBL_BATCH_SIZE]
        cache.update(_fetch_ensembl_batch(batch))
        for gene_id in batch:
            cache.setdefault(gene_id, gene_id)
    if missing:
        _save_cache(cache_path, cache)
    return {g: cache.get(g, g) for g in gene_ids}


def _fetch_ols_label(disease_id: str) -> str | None:
    for iri in candidate_iris(disease_id):
        encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
        url = f"{_OLS_TERMS_URL}/{encoded}"
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError):
            continue
        label = data.get("label")
        if label and not label.startswith("obsolete_"):
            return label
    return None


def disease_names(
    disease_ids: list[str], cache_path: str | Path = DEFAULT_DISEASE_CACHE_PATH
) -> dict[str, str]:
    """Resolve EFO/MONDO/HP IDs to disease labels via the EBI OLS4 API."""
    cache = _load_cache(cache_path)
    missing = sorted({d for d in disease_ids if d not in cache})
    for disease_id in missing:
        cache[disease_id] = _fetch_ols_label(disease_id) or disease_id
    if missing:
        _save_cache(cache_path, cache)
    return {d: cache.get(d, d) for d in disease_ids}
