import pytest

from litrex.data_sources import gwas_catalog


def test_normalize_target_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        gwas_catalog.normalize_target("EGFR")


def test_normalize_disease_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        gwas_catalog.normalize_disease("lung cancer")


def test_build_text_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        gwas_catalog.build_text({})
