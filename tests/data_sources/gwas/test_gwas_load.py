from datetime import date
from pathlib import Path

from litrex.data_sources.gwas.load import parse_symbols, read_associations, strip_trait_id

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
    pmids = sorted(r.pmid for r in rows)
    assert pmids == ["111", "111", "333"]
    diseases = {r.disease_id for r in rows if r.pmid == "111"}
    assert diseases == {"EFO_0001360", "MONDO_0011122"}


def test_read_associations_alias_fields():
    rows = [r for r in read_associations([FIX], cutoff=date(2024, 1, 1)) if r.pmid == "333"]
    r = rows[0]
    assert r.target_ensembl is None
    assert r.target_symbols == ["LINC02227", "EBF1"]
    assert r.target_rsid == "rs2914231"
    assert r.disease_label == "asthma"
