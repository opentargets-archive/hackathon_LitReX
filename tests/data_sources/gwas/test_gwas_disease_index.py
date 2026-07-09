from pathlib import Path

import pandas as pd

from litrex.data_sources.gwas.disease_index import load_disease_index


def _make_fixture(p: Path):
    df = pd.DataFrame([
        {"id": "MONDO_0004979", "name": "asthma",
         "synonyms": {"hasExactSynonym": ["bronchial asthma"], "hasRelatedSynonym": []},
         "therapeuticAreas": ["EFO_0000684"]},                       # respiratory disease
        {"id": "EFO_0001360", "name": "type 2 diabetes mellitus",
         "synonyms": {"hasExactSynonym": ["type 2 diabetes"], "hasRelatedSynonym": ["T2DM"]},
         "therapeuticAreas": ["EFO_0000651"]},
        {"id": "OBA_2050609", "name": "level of enoyl-CoA hydratase in blood",
         "synonyms": {"hasExactSynonym": [], "hasRelatedSynonym": []},
         "therapeuticAreas": ["EFO_0001444"]},                       # measurement
    ])
    df.to_parquet(p)


def test_load_and_contains(tmp_path):
    fx = tmp_path / "d.parquet"
    _make_fixture(fx)
    idx = load_disease_index(fx)
    assert idx.contains("MONDO_0004979")
    assert not idx.contains("EFO_0000270")   # superseded EFO id, absent


def test_synonyms_include_name(tmp_path):
    fx = tmp_path / "d.parquet"
    _make_fixture(fx)
    idx = load_disease_index(fx)
    syns = idx.synonyms("EFO_0001360")
    assert "type 2 diabetes mellitus" in syns
    assert "type 2 diabetes" in syns
    assert "T2DM" in syns


def test_is_measurement_flag(tmp_path):
    fx = tmp_path / "d.parquet"
    _make_fixture(fx)
    idx = load_disease_index(fx)                 # default measurement_ta_id=EFO_0001444
    assert idx.is_measurement("OBA_2050609")     # tagged measurement
    assert not idx.is_measurement("MONDO_0004979")


def test_resolve_name_recovers_superseded_id(tmp_path):
    fx = tmp_path / "d.parquet"
    _make_fixture(fx)
    idx = load_disease_index(fx)
    # GWAS uses EFO_0000270 "asthma"; OT canonicalized to MONDO_0004979.
    assert idx.resolve_name("asthma") == "MONDO_0004979"
    assert idx.resolve_name("bronchial asthma") == "MONDO_0004979"   # via synonym
    assert idx.resolve_name("no such disease") is None
