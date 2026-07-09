from litrex.sampling import therapeutic_area as ta


def _fake_fetch(graph: dict[str, list[str]]):
    def fetch(iri: str) -> list[str]:
        return graph.get(iri, [])

    return fetch


def test_resolve_therapeutic_area_walks_to_bucket_below_root():
    # disease -> respiratory disorder -> lung disease -> root
    graph = {
        "http://purl.obolibrary.org/obo/MONDO_1000001": [
            "http://purl.obolibrary.org/obo/MONDO_1000002"
        ],
        "http://purl.obolibrary.org/obo/MONDO_1000002": [ta._DISEASE_ROOT],
    }
    cache: dict[str, list[str]] = {}
    bucket = ta.resolve_therapeutic_area("MONDO_1000001", cache, fetch=_fake_fetch(graph))
    assert bucket == "http://purl.obolibrary.org/obo/MONDO_1000002"


def test_resolve_therapeutic_area_skips_grouping_axis():
    grouping_axis = next(iter(ta._GROUPING_AXES))
    graph = {
        "http://purl.obolibrary.org/obo/MONDO_2000001": [grouping_axis],
        grouping_axis: [ta._DISEASE_ROOT],
    }
    cache: dict[str, list[str]] = {}
    bucket = ta.resolve_therapeutic_area("MONDO_2000001", cache, fetch=_fake_fetch(graph))
    assert bucket == "http://purl.obolibrary.org/obo/MONDO_2000001"


def test_resolve_therapeutic_area_hp_prefix_short_circuits_without_network():
    def fetch(iri: str) -> list[str]:
        raise AssertionError("HP-prefixed IDs must not hit the network")

    cache: dict[str, list[str]] = {}
    assert ta.resolve_therapeutic_area("HP_0002960", cache, fetch=fetch) == ta.PHENOTYPE_HP


def test_resolve_therapeutic_area_dead_end_returns_unknown():
    cache: dict[str, list[str]] = {}
    bucket = ta.resolve_therapeutic_area("MONDO_9999999", cache, fetch=_fake_fetch({}))
    assert bucket == ta.UNKNOWN


def test_resolve_therapeutic_area_uses_cache_not_fetch_on_repeat():
    calls = []

    def fetch(iri: str) -> list[str]:
        calls.append(iri)
        return [ta._DISEASE_ROOT]

    cache: dict[str, list[str]] = {}
    ta.resolve_therapeutic_area("MONDO_3000001", cache, fetch=fetch)
    ta.resolve_therapeutic_area("MONDO_3000001", cache, fetch=fetch)
    assert calls == ["http://purl.obolibrary.org/obo/MONDO_3000001"]


def test_normalized_entropy_uniform_is_one():
    assert ta.normalized_entropy([10, 10, 10, 10]) == 1.0


def test_normalized_entropy_single_bucket_is_zero():
    assert ta.normalized_entropy([42]) == 0.0


def test_spread_summary_buckets_rows_not_distinct_diseases(monkeypatch):
    def fake_resolve_all(disease_ids, cache_path=ta.DEFAULT_CACHE_PATH, fetch=ta.fetch_parents):
        return {d: d[:4] for d in disease_ids}

    monkeypatch.setattr(ta, "resolve_all", fake_resolve_all)
    summary = ta.spread_summary(["AAAA1", "AAAA2", "BBBB1"])
    assert summary["bucket_counts"] == {"AAAA": 2, "BBBB": 1}
    assert summary["n_buckets"] == 2
