"""GWAS Catalog data source (stage 3, docs/03-data-source-gwas-catalog.md).

Reframed from the original OnToma-normalization stub: builds target-disease
textual co-occurrences from the papers behind recent GWAS associations, as a
silver training set. The implementation lives in the ``.gwas`` subpackage; this
module is the public entry point.

    python -m litrex.data_sources.gwas.build --config config/gwas.yaml --source both
"""
from __future__ import annotations

from .gwas.build import compare_corpora, main, run
from .gwas.cooccurrence import GwasCooccurrence

__all__ = ["run", "compare_corpora", "main", "GwasCooccurrence"]
