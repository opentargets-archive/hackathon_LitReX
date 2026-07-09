"""The GWAS Catalog stub is now implemented in litrex.data_sources.gwas.

Behavioural tests live in tests/data_sources/gwas/. This module only checks the
public entry point is wired up.
"""
from litrex.data_sources import gwas_catalog


def test_public_api_exposed():
    assert callable(gwas_catalog.run)
    assert callable(gwas_catalog.compare_corpora)
    assert callable(gwas_catalog.main)
