from datetime import date
from litrex_gwas.load import Association
from litrex_gwas.disease_index import DiseaseIndex, DiseaseTerm
from litrex_gwas.cooccurrence import (
    split_sentences, find_target, find_disease, build_cooccurrences,
)


class Cfg:
    min_symbol_len = 2
    min_disease_syn_len = 4


def _assoc(**kw):
    base = dict(pmid="1", date=date(2025, 1, 1), disease_id="EFO_0000270",
                disease_label="asthma", target_ensembl=None,
                target_symbols=["IL6"], target_rsid="rs1800795", snp="rs1800795", p_value="5E-9")
    base.update(kw)
    return Association(**base)


IDX = DiseaseIndex(terms={"EFO_0000270": DiseaseTerm("EFO_0000270", "asthma", ["bronchial asthma"])})


def test_split_sentences():
    s = split_sentences("IL6 is a gene. It affects asthma.")
    assert len(s) == 2


def test_find_target_symbol_cascade():
    mt = find_target("Variants near IL6 were found.", _assoc(target_ensembl="ENSG9"), 2)
    assert mt[0] == "symbol" and mt[1] == "IL6"


def test_find_target_prefers_ensembl():
    mt = find_target("ENSG9 tags IL6 here.", _assoc(target_ensembl="ENSG9"), 2)
    assert mt[0] == "ensembl"


def test_find_disease_phrase():
    md = find_disease("Patients with bronchial asthma improved.", ["asthma", "bronchial asthma"], 4)
    assert md[0] == "bronchial asthma"


def test_build_sentence_level():
    abstract = "IL6 variants are associated with asthma in this cohort. Unrelated sentence."
    rows, drops = build_cooccurrences([_assoc()], abstract, IDX, Cfg())
    assert len(rows) == 1
    r = rows[0]
    assert r.cooccurrence_level == "sentence"
    assert r.match_type == "symbol"
    assert r.disease == "EFO_0000270"
    assert "asthma" in r.text.lower()


def test_build_abstract_level_fallback():
    abstract = "IL6 is studied here. A separate line mentions asthma prevalence."
    rows, drops = build_cooccurrences([_assoc()], abstract, IDX, Cfg())
    assert len(rows) == 1
    assert rows[0].cooccurrence_level == "abstract"


def test_build_drops_when_absent():
    rows, drops = build_cooccurrences([_assoc()], "No relevant terms here.", IDX, Cfg())
    assert rows == []
    assert drops.no_target_in_text + drops.no_disease_in_text + drops.no_cooccurrence >= 1
