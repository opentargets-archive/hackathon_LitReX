from datetime import date
from pathlib import Path

import pandas as pd

import litrex.data_sources.gwas.build as build
from litrex.data_sources.gwas.config import Config
from litrex.data_sources.gwas.disease_index import DiseaseIndex, DiseaseTerm

FIX = Path(__file__).parent / "fixtures"


def _cfg(tmp_path):
    return Config(
        assoc_dir=FIX, assoc_glob="mini_assoc.tsv", window_years=2,
        disease_index_url="http://x", cache_dir=tmp_path / "cache",
        output_path=tmp_path / "out.parquet",
        europepmc_base="http://e", pubmed_efetch_base="http://p",
        max_req_per_sec=1000.0, min_symbol_len=2, min_disease_syn_len=4,
        reconciliation_log=tmp_path / "recon.tsv",
    )


def test_run_end_to_end(tmp_path, monkeypatch):
    # MONDO_0011122 (obesity) is flagged measurement -> dropped.
    # EFO_0000270 (asthma) is NOT a key but reconciles by name to MONDO_0004979.
    idx = DiseaseIndex(
        terms={
            "EFO_0001360": DiseaseTerm("EFO_0001360", "type 2 diabetes", []),
            "MONDO_0004979": DiseaseTerm("MONDO_0004979", "asthma", []),
            "MONDO_0011122": DiseaseTerm("MONDO_0011122", "obesity", [], is_measurement=True),
        },
        name_to_id={"asthma": "MONDO_0004979"},
    )
    monkeypatch.setattr(build, "_prepare_disease_index", lambda cfg: idx)
    abstracts = {
        "111": "IL6 variants are associated with type 2 diabetes in this study.",
        "333": "EBF1 near-variants show a link to asthma risk.",
    }
    # `both` now = abstract + title; title text comes from the STUDY column
    # (build's _prepare_texts derives it from by_pmid, no fetch), but we stub
    # abstract fetching here.
    monkeypatch.setattr(build, "load_or_fetch_abstracts",
                        lambda pmids, cfg, path: abstracts)

    reports = build.run(_cfg(tmp_path), today=date(2026, 7, 9), source="both")
    assert set(reports) == {"abstract", "title"}

    rep = reports["abstract"]
    df = pd.read_parquet(tmp_path / "out_abstract.parquet")
    assert rep.cooccurrences == len(df) >= 2
    assert set(df["disease"]) <= {"EFO_0001360", "MONDO_0004979"}   # canonicalized
    assert rep.dropped_measurement == 1                              # obesity dropped
    assert rep.reconciled == 1                                       # asthma EFO->MONDO
    assert (df["text_source"] == "abstract").all()
    assert (df["section"] == "abstract").all()
    assert (df["data_source"] == "gwas_catalog").all()
    assert df["publication_id"].str.startswith("PMID:").all()

    # title corpus: mined from the STUDY column, section='title'
    tdf = pd.read_parquet(tmp_path / "out_title.parquet")
    assert (tdf["section"] == "title").all()
    assert len(tdf) >= 1   # e.g. "IL6 variants associated with type 2 diabetes and obesity"

    # per-source breakdowns must not alias: each sums to its own cooccurrences
    for r in reports.values():
        assert sum(r.by_level.values()) == r.cooccurrences
        assert sum(r.by_match_type.values()) == r.cooccurrences
    assert reports["abstract"].by_level is not reports["title"].by_level

    comp = build.compare_corpora(_cfg(tmp_path))
    assert "cooccurrences" in comp and set(comp["cooccurrences"]) == {"abstract", "title"}
