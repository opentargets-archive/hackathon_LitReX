"""Stage 2: docs/02-data-source-cooccurrence.md.

Upstream schema (Open Targets literature cooccurrence, Spark/Parquet,
verified against release 26.06.0-dev2): one row per co-occurring entity
pair per text span. Every row observed so far has type1='GP' (gene/protein,
mappedId1=Ensembl gene ID), type2='DS' (disease, mappedId2=EFO/MONDO/HP ID)
and isMapped=True; `to_cooccurrence` filters defensively on those fields
in case a future release mixes in other entity-pair types (e.g. GP-GP).
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from litrex.schema import Cooccurrence

DEFAULT_SOURCE_URI = (
    "gs://open-targets-pipeline-runs/ds/26.06.0-dev2/intermediate/literature/cooccurrence"
)

_REQUIRED_RAW_COLUMNS = (
    "mappedId1",
    "type1",
    "mappedId2",
    "type2",
    "isMapped",
    "text",
    "pmid",
    "date",
    "section",
    "evidenceScore",
    "start1",
    "end1",
    "start2",
    "end2",
)

_REQUIRED_OUTPUT_COLUMNS = ("target", "disease", "text", "publication_id", "publication_date")

# Some upstream text spans are meant to be a single sentence but retain
# unstripped HTML tags (e.g. structured-abstract headers like <h4>) or
# otherwise bundle several sentences into one span. `_TAG_PATTERN` catches
# the tag case directly. RE2 (Arrow's regex engine) has no lookaround, so
# `_SENTENCE_BOUNDARY_PATTERN` is a plain punctuation+whitespace split used
# as a fallback signal -- it overcounts on abbreviations like "Dr. Smith",
# so `text_granularity` is an approximate label, not an exact sentence count.
_TAG_PATTERN = r"</?[A-Za-z][^<>]{0,40}>"
_SENTENCE_BOUNDARY_PATTERN = r"[.!?]+\s+"


def _text_granularity(text: pa.Array) -> pa.Array:
    has_tag = pc.match_substring_regex(text, _TAG_PATTERN)
    sentence_count = pc.list_value_length(
        pc.split_pattern_regex(text, pattern=_SENTENCE_BOUNDARY_PATTERN)
    )
    is_chunk = pc.or_(has_tag, pc.greater(sentence_count, 1))
    return pc.if_else(is_chunk, "chunk", "sentence")


def _split_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"expected a gs:// URI, got {uri!r}")
    bucket, _, prefix = uri.removeprefix("gs://").partition("/")
    return bucket, prefix


def download(destination: str | Path, source_uri: str = DEFAULT_SOURCE_URI) -> list[Path]:
    """Download every cooccurrence part-file from `source_uri` into `destination`.

    Files already present locally with a matching size are left alone, so a
    partial/interrupted download can be safely re-run.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    bucket, prefix = _split_gcs_uri(source_uri)
    gcs = pafs.GcsFileSystem()
    selector = pafs.FileSelector(f"{bucket}/{prefix}", recursive=False)
    remote_files = sorted(
        (
            info
            for info in gcs.get_file_info(selector)
            if info.type == pafs.FileType.File and info.path.endswith(".parquet")
        ),
        key=lambda info: info.path,
    )
    if not remote_files:
        raise FileNotFoundError(f"no parquet files found under {source_uri}")

    local_paths = []
    for info in remote_files:
        local_path = destination / Path(info.path).name
        if not (local_path.exists() and local_path.stat().st_size == info.size):
            pafs.copy_files(info.path, str(local_path), source_filesystem=gcs)
        local_paths.append(local_path)
    return local_paths


def read_raw(source_path: str | Path) -> pa.Table:
    return pq.read_table(source_path)


def to_cooccurrence(raw: pa.Table) -> pa.Table:
    missing = [c for c in _REQUIRED_RAW_COLUMNS if c not in raw.column_names]
    if missing:
        raise ValueError(f"raw table missing expected upstream columns: {missing}")

    is_gene_disease_pair = pc.and_(
        pc.and_(pc.equal(raw["type1"], "GP"), pc.equal(raw["type2"], "DS")),
        raw["isMapped"],
    )
    gene_disease = raw.filter(is_gene_disease_pair)

    table = pa.table(
        {
            "target": gene_disease["mappedId1"],
            "disease": gene_disease["mappedId2"],
            "text": gene_disease["text"],
            "publication_id": gene_disease["pmid"],
            "publication_date": gene_disease["date"],
            "section": gene_disease["section"],
            "evidence_score": gene_disease["evidenceScore"],
            "target_start": gene_disease["start1"],
            "target_end": gene_disease["end1"],
            "disease_start": gene_disease["start2"],
            "disease_end": gene_disease["end2"],
        }
    )
    table = table.append_column("text_granularity", _text_granularity(table["text"]))

    for column in _REQUIRED_OUTPUT_COLUMNS:
        if pc.any(pc.is_null(table[column])).as_py():
            raise ValueError(f"null values found in required column {column!r} after mapping")

    return table


def write(table: pa.Table, destination: str | Path) -> None:
    pq.write_table(table, destination)


def ingest(raw_dir: str | Path, output_dir: str | Path) -> dict[str, int]:
    """Map every downloaded raw part-file to the Cooccurrence contract.

    Returns a mapping of source filename -> row count written, for a basic
    row-count sanity check (docs/02 step 4).
    """
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    row_counts: dict[str, int] = {}
    for source_path in sorted(raw_dir.glob("*.parquet")):
        mapped = to_cooccurrence(read_raw(source_path))
        write(mapped, output_dir / source_path.name)
        row_counts[source_path.name] = mapped.num_rows
    return row_counts


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and ingest the Open Targets literature cooccurrence dataset."
    )
    parser.add_argument("--raw-dir", default="data/raw/cooccurrence")
    parser.add_argument("--output-dir", default="data/processed/cooccurrence")
    parser.add_argument("--source-uri", default=DEFAULT_SOURCE_URI)
    parser.add_argument("--skip-download", action="store_true", help="reuse an existing raw dir")
    args = parser.parse_args()

    if not args.skip_download:
        local_paths = download(args.raw_dir, args.source_uri)
        print(f"downloaded {len(local_paths)} files to {args.raw_dir}")

    row_counts = ingest(args.raw_dir, args.output_dir)
    total_rows = sum(row_counts.values())
    print(f"wrote {total_rows} rows across {len(row_counts)} files to {args.output_dir}")


if __name__ == "__main__":
    _main()


__all__ = [
    "Cooccurrence",
    "download",
    "ingest",
    "read_raw",
    "to_cooccurrence",
    "write",
]
