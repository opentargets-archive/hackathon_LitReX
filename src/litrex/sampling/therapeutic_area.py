"""Disease -> top-level therapeutic-area bucketing for the ontology-spread
metric (docs/04-sampling.md).

`disease` values in the `Cooccurrence` contract are EFO/MONDO/HP IDs
(docs/02). Rather than shipping a local copy of the EFO ontology, buckets are
resolved by walking the live `subClassOf` graph via the EBI OLS4 API:

- EFO's own disease root (`EFO_0000408`) is itself obsolete in current EFO
  releases -- the disease branch was migrated to import MONDO directly, so
  `MONDO_0000001` ("disease") is the real root diseases climb to.
- EFO's built release artifacts (e.g. `efo_otar_slim.obo`) are not published
  at a discoverable static URL, and the source repo is a ~280MB multi-file
  OWL project that needs a reasoner to resolve `owl:imports` -- both
  impractical for a v1 prototype. OLS4's `/graph` endpoint gives the same
  ancestor data on demand, authoritative and always current, at the cost of
  a network call per novel disease ID (mitigated by the on-disk cache below).
- HP-prefixed IDs (Human Phenotype Ontology) sit under a separate root
  entirely and are bucketed directly as `"phenotype (HP)"` without a network
  call.

Ancestor walk is a *single-parent greedy walk* (always the alphabetically
first `subClassOf` parent), not a full multi-parent traversal -- diseases
with multiple parents may resolve to a different bucket than a "true" DAG
analysis would pick. This is a soft diversity metric (docs/04: "reasonably
spread... rather than a single hard threshold"), not a precise reproduction
of Open Targets' curated therapeutic-area list -- see docs session log for
the full rationale.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path

_OLS_BASE = "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms"
_DISEASE_ROOT = "http://purl.obolibrary.org/obo/MONDO_0000001"

# MONDO's own top-level grouping axes -- not real disease categories (e.g.
# "disease by body system or component"), so a disease landing on one of
# these is bucketed one hop further down instead.
_GROUPING_AXES = {
    "http://purl.obolibrary.org/obo/MONDO_7770006",  # disease by body system or component
    "http://purl.obolibrary.org/obo/MONDO_7770007",  # disease by dev'l/physiological process
    "http://purl.obolibrary.org/obo/MONDO_7770008",  # disease by etiologic mechanism
    "http://purl.obolibrary.org/obo/MONDO_0005583",  # non-human animal disease
    "http://purl.obolibrary.org/obo/MONDO_0020683",  # acute disease
}

_MAX_DEPTH = 12
UNKNOWN = "unknown"
PHENOTYPE_HP = "phenotype (HP)"

DEFAULT_CACHE_PATH = Path("data/cache/efo_graph_cache.json")

GraphFetcher = Callable[[str], list[str]]


def candidate_iris(disease_id: str) -> list[str]:
    if disease_id.startswith("EFO_"):
        return [
            f"http://www.ebi.ac.uk/efo/{disease_id}",
            f"http://purl.obolibrary.org/obo/{disease_id}",
        ]
    return [f"http://purl.obolibrary.org/obo/{disease_id}"]


def fetch_parents(iri: str) -> list[str]:
    """Look up `iri`'s direct `subClassOf` parents via the OLS4 API.

    Returns an empty list on any network/parse failure or if the term has no
    `subClassOf` parents (e.g. it's obsolete) -- callers treat both cases the
    same way (dead end, try the next candidate IRI or give up).
    """
    encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
    url = f"{_OLS_BASE}/{encoded}/graph"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    return sorted(
        {
            edge["target"]
            for edge in data.get("edges", [])
            if edge.get("source") == iri and edge.get("label") == "subClassOf"
        }
    )


def load_cache(path: str | Path) -> dict[str, list[str]]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_cache(path: str | Path, cache: dict[str, list[str]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _parents(iri: str, cache: dict[str, list[str]], fetch: GraphFetcher) -> list[str]:
    if iri not in cache:
        cache[iri] = fetch(iri)
    return cache[iri]


def resolve_therapeutic_area(
    disease_id: str,
    cache: dict[str, list[str]],
    fetch: GraphFetcher = fetch_parents,
) -> str:
    """Resolve a single disease ID to its top-level therapeutic-area bucket.

    `cache` is mutated in place (iri -> parent iris) so repeated calls across
    a run, or across runs via `load_cache`/`save_cache`, avoid re-fetching.
    """
    if disease_id.startswith("HP_"):
        return PHENOTYPE_HP

    for start_iri in candidate_iris(disease_id):
        path = [start_iri]
        node = start_iri
        reached_root = False
        for _ in range(_MAX_DEPTH):
            parents = _parents(node, cache, fetch)
            if not parents:
                break
            parent = parents[0]
            path.append(parent)
            if parent == _DISEASE_ROOT:
                reached_root = True
                break
            node = parent

        if not reached_root:
            continue

        bucket = path[-2]
        if bucket in _GROUPING_AXES and len(path) >= 3:
            bucket = path[-3]
        return bucket

    return UNKNOWN


def resolve_all(
    disease_ids: list[str],
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    fetch: GraphFetcher = fetch_parents,
) -> dict[str, str]:
    """Resolve every distinct `disease_id` to a bucket, persisting the cache."""
    cache = load_cache(cache_path)
    buckets = {d: resolve_therapeutic_area(d, cache, fetch) for d in disease_ids}
    save_cache(cache_path, cache)
    return buckets


def normalized_entropy(counts: list[int]) -> float:
    """Shannon entropy over bucket counts, normalized to [0, 1] by the max
    possible entropy for the observed number of buckets (0 = everything in
    one bucket, 1 = perfectly uniform across the buckets actually seen)."""
    counts = [c for c in counts if c > 0]
    if len(counts) <= 1:
        return 0.0
    total = sum(counts)
    entropy = -sum((c / total) * math.log(c / total) for c in counts)
    return entropy / math.log(len(counts))


def spread_summary(disease_ids: list[str], cache_path: str | Path = DEFAULT_CACHE_PATH) -> dict:
    """Bucket every row's disease ID and summarize the resulting spread.

    `disease_ids` is the per-row disease column (duplicates expected/wanted --
    the distribution is over rows, not distinct diseases).
    """
    distinct = sorted(set(disease_ids))
    buckets = resolve_all(distinct)
    bucket_per_row = [buckets[d] for d in disease_ids]
    counts = Counter(bucket_per_row)
    total = sum(counts.values())
    return {
        "n_buckets": len(counts),
        "bucket_counts": dict(counts),
        "bucket_proportions": {k: v / total for k, v in counts.items()},
        "normalized_entropy": normalized_entropy(list(counts.values())),
    }
