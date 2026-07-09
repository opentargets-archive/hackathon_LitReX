"""Merge per-source Cooccurrence outputs into one uniform pool for stage 4.

Open Targets EPMC (``data/processed/cooccurrence/``) and GWAS Catalog
(``output/gwas_cooccurrence_{abstract,title}.parquet``) each carry source-specific
extra columns (``evidence_score`` vs ``target_symbol``/``match_type``/…). Stage 4
only needs the shared contract + span/granularity columns, so this normalizes
every input to one common schema (dropping the extras) and writes them into a
single directory the sampler can scan as one dataset.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# The uniform column set for the merged sampling pool: the shared Cooccurrence
# contract (incl. data_source) plus the span/granularity columns both sources
# produce and stage 5 needs. Source-specific extras are intentionally dropped.
MERGE_SCHEMA = pa.schema([
    ("target", pa.string()),
    ("disease", pa.string()),
    ("text", pa.string()),
    ("publication_id", pa.string()),
    ("publication_date", pa.date32()),
    ("section", pa.string()),
    ("data_source", pa.string()),
    ("target_start", pa.int64()),
    ("target_end", pa.int64()),
    ("disease_start", pa.int64()),
    ("disease_end", pa.int64()),
    ("text_granularity", pa.string()),
])
_COLUMNS = [f.name for f in MERGE_SCHEMA]


def normalize(table: pa.Table) -> pa.Table:
    """Select the merge columns from a source table and cast to MERGE_SCHEMA."""
    missing = [c for c in _COLUMNS if c not in table.column_names]
    if missing:
        raise ValueError(f"table missing merge columns: {missing}")
    return table.select(_COLUMNS).cast(MERGE_SCHEMA)


def _expand(path: Path) -> list[Path]:
    """A file -> [file]; a directory -> its sorted *.parquet part-files."""
    return sorted(path.glob("*.parquet")) if path.is_dir() else [path]


def merge_sources(inputs: list[str | Path], output_dir: str | Path) -> dict[str, int]:
    """Normalize each input (file or dir) and write it into ``output_dir``.

    Returns a mapping of written filename -> row count. Output filenames are
    prefixed with the source path's stem so parts from different sources don't
    collide.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    row_counts: dict[str, int] = {}
    for raw in inputs:
        src = Path(raw)
        for part in _expand(src):
            table = normalize(pq.read_table(part))
            name = f"{src.stem}__{part.stem}.parquet" if src.is_dir() else f"{src.stem}.parquet"
            pq.write_table(table, output_dir / name)
            row_counts[name] = table.num_rows
    return row_counts


def _main() -> None:
    parser = argparse.ArgumentParser(description="Merge Cooccurrence sources into one pool.")
    parser.add_argument("--output-dir", default="data/processed/merged")
    parser.add_argument("inputs", nargs="+",
                        help="Source parquet files or directories (OT dir + GWAS files).")
    args = parser.parse_args()
    counts = merge_sources(args.inputs, args.output_dir)
    print(f"merged {sum(counts.values())} rows from {len(counts)} files into {args.output_dir}")


if __name__ == "__main__":
    _main()
