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
    assert set(df["disease"]) <= {"EFO_0001360", "EFO_0000270"}
    assert rep.dropped_by_ontology.get("MONDO") == 1   # MONDO_0011122 not in index
    assert rep.by_level.get("sentence", 0) >= 2
