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
    fx = tmp_path / "d.parquet"
    _make_fixture(fx)
    idx = load_disease_index(fx)
    assert idx.contains("EFO_0001360")
    assert not idx.contains("OBA_2050609")


def test_synonyms_include_name(tmp_path):
    fx = tmp_path / "d.parquet"
    _make_fixture(fx)
    idx = load_disease_index(fx)
    syns = idx.synonyms("EFO_0001360")
    assert "type 2 diabetes mellitus" in syns
    assert "type 2 diabetes" in syns
    assert "T2DM" in syns
