"""Stage 3 (delegated): docs/03-data-source-gwas-catalog.md."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def read_raw(source_path: str | Path) -> pa.Table:
    return pq.read_table(source_path)


def normalize_target(gene_symbol: str) -> str | None:
    """Gene symbol -> Ensembl ID via OnToma. Returns None if unresolved."""
    raise NotImplementedError


def normalize_disease(trait: str) -> str | None:
    """Free-text trait -> EFO ID via OnToma. Returns None if unresolved."""
    raise NotImplementedError


def build_text(association_row: dict) -> str:
    """Construct a text field from GWAS association metadata.

    Open design decision -- see docs/03-data-source-gwas-catalog.md.
    """
    raise NotImplementedError


def to_cooccurrence(raw: pa.Table) -> pa.Table:
    raise NotImplementedError


def write(table: pa.Table, destination: str | Path) -> None:
    pq.write_table(table, destination)
