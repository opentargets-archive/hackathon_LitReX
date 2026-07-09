"""Stage 2: docs/02-data-source-cooccurrence.md.

Upstream schema (Open Targets literature cooccurrence, Spark/Parquet,
verified against release 26.06.0-dev2): one row per co-occurring entity
pair per text span. Every row observed so far has type1='GP' (gene/protein,
mappedId1=Ensembl gene ID), type2='DS' (disease, mappedId2=EFO/MONDO/HP ID)
and isMapped=True; `to_cooccurrence` filters defensively on those fields
in case a future release mixes in other entity-pair types (e.g. GP-GP).
"""

import argparse
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.fs as pafs
import pyarrow.parquet as pq
import requests

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

# Provenance tag for every row this module emits (schema.Cooccurrence.data_source).
DATA_SOURCE = "open_targets"


def _prefix_pmid(pmid: pa.Array) -> pa.Array:
    """Turn a bare PMID array into canonical ``PMID:<id>`` identifiers."""
    return pc.binary_join_element_wise(
        pa.scalar("PMID:"), pc.cast(pmid, pa.string()), pa.scalar("")
    )

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
            "publication_id": _prefix_pmid(gene_disease["pmid"]),
            "publication_date": gene_disease["date"],
            "section": gene_disease["section"],
            "data_source": pa.array([DATA_SOURCE] * gene_disease.num_rows, pa.string()),
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


# --- Public FTP path: Open Targets `evidence_europepmc` -------------------
# The flat intermediate `literature/cooccurrence` dataset (used by the GCS
# path above) is NOT published on the public FTP. Its co-occurrence content
# lives in the `evidence_europepmc` output as a nested `textMiningSentences`
# array, one row per (target, disease, publication). We explode that array
# back into one Cooccurrence row per sentence.

DEFAULT_FTP_EPMC_URL = (
    "https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/26.06/output/evidence_europepmc/"
)
_EPMC_REQUIRED_COLUMNS = (
    "targetId", "diseaseId", "literature", "publicationDate", "resourceScore",
    "textMiningSentences",
)
_TAG_RE = re.compile(r"</?[A-Za-z][^<>]{0,40}>")
_SENT_RE = re.compile(r"[.!?]+\s+")


def _granularity(text: str) -> str:
    if not isinstance(text, str):
        return "chunk"
    if _TAG_RE.search(text) or len(_SENT_RE.split(text)) > 1:
        return "chunk"
    return "sentence"


def to_cooccurrence_epmc(raw: pa.Table, start_date: date, sections: list[str]) -> pa.Table:
    """Map an `evidence_europepmc` part-table to the Cooccurrence contract.

    Explodes `textMiningSentences` into one row per sentence, keeps only rows
    whose publication is on/after ``start_date`` and whose sentence ``section``
    is in ``sections``, and tags every row ``data_source='open_targets'`` with a
    ``PMID:``-prefixed ``publication_id``.
    """
    missing = [c for c in _EPMC_REQUIRED_COLUMNS if c not in raw.column_names]
    if missing:
        raise ValueError(f"raw epmc table missing expected columns: {missing}")

    df = raw.select(list(_EPMC_REQUIRED_COLUMNS)).to_pandas()
    start_str = start_date.isoformat()
    df = df[df["publicationDate"].notna()]
    df = df[df["publicationDate"].astype(str).str.slice(0, 10) >= start_str]
    df["publication_id"] = df["literature"].map(
        lambda lit: f"PMID:{lit[0]}" if lit is not None and len(lit) else None
    )
    df = df[df["publication_id"].notna()]
    if df.empty:
        return _empty_epmc_table()

    df = df.explode("textMiningSentences")
    df = df[df["textMiningSentences"].notna()]
    if df.empty:
        return _empty_epmc_table()
    sent = pd.DataFrame(list(df["textMiningSentences"]), index=df.index)

    out = pd.DataFrame({
        "target": df["targetId"].to_numpy(),
        "disease": df["diseaseId"].to_numpy(),
        "text": sent["text"].to_numpy(),
        "publication_id": df["publication_id"].to_numpy(),
        "publication_date": pd.to_datetime(
            df["publicationDate"].astype(str).str.slice(0, 10), errors="coerce"
        ).dt.date.to_numpy(),
        "section": sent["section"].to_numpy(),
        "data_source": DATA_SOURCE,
        "evidence_score": df["resourceScore"].to_numpy(),
        "target_start": sent["tStart"].to_numpy(),
        "target_end": sent["tEnd"].to_numpy(),
        "disease_start": sent["dStart"].to_numpy(),
        "disease_end": sent["dEnd"].to_numpy(),
    })
    out = out[out["section"].isin(sections)]
    out = out.dropna(subset=["target", "disease", "text", "publication_date"])
    if out.empty:
        return _empty_epmc_table()
    out["text_granularity"] = out["text"].map(_granularity)
    return pa.Table.from_pandas(out, preserve_index=False)


def _empty_epmc_table() -> pa.Table:
    cols = ["target", "disease", "text", "publication_id", "publication_date", "section",
            "data_source", "evidence_score", "target_start", "target_end",
            "disease_start", "disease_end", "text_granularity"]
    return pa.table({c: pa.array([], pa.string()) for c in cols})


def list_ftp_parts(base_url: str = DEFAULT_FTP_EPMC_URL) -> list[str]:
    """List `part-*.parquet` filenames under an Open Targets FTP dataset URL."""
    resp = requests.get(base_url, timeout=60)
    resp.raise_for_status()
    return sorted(set(re.findall(r'href="(part-[^"?]+\.parquet)"', resp.text)))


def ingest_epmc_ftp(
    output_dir: str | Path,
    base_url: str = DEFAULT_FTP_EPMC_URL,
    start_date: date | None = None,
    sections: list[str] | None = None,
    tmp_dir: str | Path = "data/raw/epmc_tmp",
    limit_files: int | None = None,
) -> dict[str, int]:
    """Download `evidence_europepmc` part-files from FTP and ingest them.

    Each file is downloaded, exploded/filtered to the 2-year + section window,
    written to ``output_dir``, then the raw file is deleted — so peak disk is
    one raw part-file (~90MB) plus the (small, filtered) processed output.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    sections = sections or ["abstract", "title"]

    parts = list_ftp_parts(base_url)
    if limit_files is not None:
        parts = parts[:limit_files]

    row_counts: dict[str, int] = {}
    for name in parts:
        raw_path = tmp_dir / name
        with requests.get(base_url + name, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(raw_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        mapped = to_cooccurrence_epmc(read_raw(raw_path), start_date, sections)
        write(mapped, output_dir / name)
        raw_path.unlink()
        row_counts[name] = mapped.num_rows
    return row_counts


def _default_start_date() -> date:
    """Two years before today (stage-4 window lower bound)."""
    today = date.today()
    try:
        return today.replace(year=today.year - 2)
    except ValueError:
        return date(today.year - 2, 3, 1)


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest the Open Targets literature cooccurrence dataset."
    )
    parser.add_argument("--from-ftp", action="store_true",
                        help="Ingest evidence_europepmc from the public FTP (no GCS auth).")
    parser.add_argument("--raw-dir", default="data/raw/cooccurrence")
    parser.add_argument("--output-dir", default="data/processed/cooccurrence")
    parser.add_argument("--source-uri", default=DEFAULT_SOURCE_URI)
    parser.add_argument("--ftp-url", default=DEFAULT_FTP_EPMC_URL)
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD; default 2 years ago")
    parser.add_argument("--sections", nargs="+", default=["abstract", "title"])
    parser.add_argument("--limit-files", type=int, default=None)
    parser.add_argument("--skip-download", action="store_true", help="reuse an existing raw dir")
    args = parser.parse_args()

    if args.from_ftp:
        start = date.fromisoformat(args.start_date) if args.start_date else _default_start_date()
        row_counts = ingest_epmc_ftp(
            args.output_dir, base_url=args.ftp_url, start_date=start,
            sections=args.sections, limit_files=args.limit_files,
        )
        total_rows = sum(row_counts.values())
        print(f"wrote {total_rows} rows across {len(row_counts)} files to {args.output_dir} "
              f"(FTP evidence_europepmc, >= {start}, sections={args.sections})")
        return

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
    "ingest_epmc_ftp",
    "list_ftp_parts",
    "read_raw",
    "to_cooccurrence",
    "to_cooccurrence_epmc",
    "write",
]
