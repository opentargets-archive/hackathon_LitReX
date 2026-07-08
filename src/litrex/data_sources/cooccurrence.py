"""Stage 2: docs/02-data-source-cooccurrence.md."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from litrex.schema import Cooccurrence


def read_raw(source_path: str | Path) -> pa.Table:
    return pq.read_table(source_path)


def to_cooccurrence(raw: pa.Table) -> pa.Table:
    raise NotImplementedError(
        "Upstream column mapping not yet confirmed (docs/10-open-questions.md)."
    )


def write(table: pa.Table, destination: str | Path) -> None:
    pq.write_table(table, destination)


__all__ = ["Cooccurrence", "read_raw", "to_cooccurrence", "write"]
