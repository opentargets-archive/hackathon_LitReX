"""Stage 4: docs/04-sampling.md.

Draws a sample of `Cooccurrence` rows for the LLM labelling step (stage 5).
The sample is append-only: each run reads the existing `sample_manifest`
(if any), only draws enough *new* rows to top it up to `--target-size`, and
never re-draws or drops a previously-sampled row (docs/04's coverage/spread
metrics are computed on the full accumulated manifest and recorded in a
metadata file after every run, so growth over time is auditable).

Coverage against the platform totals (docs/04's >=10% disease/target
coverage bar) is always computed and recorded, but not enforced as a hard
gate: 10% of a ~47k-disease platform is ~4.7k distinct diseases, which no
sample smaller than that could ever reach regardless of sampling strategy.
It's expected to climb towards the threshold as the manifest grows via
repeated top-ups, not to be met by a single small batch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from litrex.config import settings
from litrex.sampling import therapeutic_area as ta

DEFAULT_INPUT_DIR = "data/processed/cooccurrence"
DEFAULT_MANIFEST_PATH = "data/processed/sample_manifest.parquet"
DEFAULT_METADATA_PATH = "data/processed/sample_manifest_metadata.json"
DEFAULT_SECTIONS = ["abstract", "title"]
DEFAULT_TARGET_SIZE = 500

_ROW_ID_KEY_COLUMNS = ("target", "disease", "publication_id", "section", "text")


def filter_window(table: pa.Table, start: date, end: date, sections: list[str]) -> pa.Table:
    mask = pc.and_(
        pc.and_(
            pc.greater_equal(table["publication_date"], pa.scalar(start)),
            pc.less_equal(table["publication_date"], pa.scalar(end)),
        ),
        pc.is_in(table["section"], value_set=pa.array(sections)),
    )
    return table.filter(mask)


def load_candidates(
    input_dir: str | Path, start: date, end: date, sections: list[str]
) -> pa.Table:
    """Scan `input_dir`'s Cooccurrence parquet files with the window/section
    filter pushed down, so this stays cheap at the full ~100M-row scale."""
    dataset = ds.dataset(input_dir, format="parquet")
    expr = (
        (ds.field("publication_date") >= start)
        & (ds.field("publication_date") <= end)
        & (ds.field("section").isin(sections))
    )
    return dataset.to_table(filter=expr)


def coverage(table: pa.Table, total_diseases: int, total_targets: int) -> dict[str, float]:
    n_diseases = pc.count_distinct(table["disease"]).as_py()
    n_targets = pc.count_distinct(table["target"]).as_py()
    return {
        "disease_coverage": n_diseases / total_diseases,
        "target_coverage": n_targets / total_targets,
        "n_diseases": n_diseases,
        "n_targets": n_targets,
    }


def ontology_spread(table: pa.Table) -> dict:
    return ta.spread_summary(table["disease"].to_pylist())


def _row_ids(table: pa.Table) -> list[str]:
    columns = [table[c].to_pylist() for c in _ROW_ID_KEY_COLUMNS]
    ids = []
    for values in zip(*columns):
        key = "|".join(str(v) for v in values)
        ids.append(hashlib.sha1(key.encode("utf-8")).hexdigest())
    return ids


def draw_sample(
    table: pa.Table,
    total_diseases: int,
    total_targets: int,
    target_size: int = DEFAULT_TARGET_SIZE,
    existing: pa.Table | None = None,
    seed: int = 0,
) -> tuple[pa.Table, dict]:
    """Top up `existing` (a prior manifest, or None for a first run) with
    randomly-drawn rows from `table` until it has `target_size` rows,
    skipping rows already present in `existing` and exact-duplicate rows
    within `table` itself (same target/disease/publication/section/text --
    see docs/11 session log's note on duplicate raw rows).
    """
    row_ids = _row_ids(table)
    table = table.append_column("sample_row_id", pa.array(row_ids))

    existing_ids: set[str] = set()
    if existing is not None and existing.num_rows > 0:
        existing_ids = set(existing["sample_row_id"].to_pylist())

    seen: set[str] = set(existing_ids)
    candidate_indices = []
    for i, row_id in enumerate(row_ids):
        if row_id in seen:
            continue
        seen.add(row_id)
        candidate_indices.append(i)

    n_needed = max(target_size - len(existing_ids), 0)
    n_draw = min(n_needed, len(candidate_indices))

    rng = random.Random(seed)
    drawn_indices = sorted(rng.sample(candidate_indices, n_draw))
    new_rows = table.take(pa.array(drawn_indices, type=pa.int64()))

    if existing is not None and existing.num_rows > 0:
        combined = pa.concat_tables([existing, new_rows], promote_options="default")
    else:
        combined = new_rows

    metrics = coverage(combined, total_diseases, total_targets)
    metrics["ontology_spread"] = ontology_spread(combined)
    metrics["sample_size"] = combined.num_rows
    metrics["new_rows_added"] = new_rows.num_rows
    metrics["requested_target_size"] = target_size
    metrics["rows_available_to_draw_from"] = len(candidate_indices)

    return combined, metrics


def write_manifest(table: pa.Table, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def append_metadata(metrics: dict, filters: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = json.loads(path.read_text()) if path.exists() else []
    runs.append(
        {
            "run_at": datetime.now(UTC).isoformat(),
            "filters": filters,
            "metrics": metrics,
        }
    )
    path.write_text(json.dumps(runs, indent=2, sort_keys=True, default=str))


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw/top-up a representative sample of Cooccurrence rows (docs/04)."
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--manifest-path", default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--metadata-path", default=DEFAULT_METADATA_PATH)
    parser.add_argument("--target-size", type=int, default=DEFAULT_TARGET_SIZE)
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD, default: 2 years ago")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD, default: today")
    parser.add_argument("--sections", nargs="+", default=DEFAULT_SECTIONS)
    parser.add_argument("--total-diseases", type=int, default=settings.platform_total_diseases)
    parser.add_argument("--total-targets", type=int, default=settings.platform_total_targets)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.total_diseases is None or args.total_targets is None:
        parser.error(
            "--total-diseases/--total-targets required "
            "(or set LITREX_PLATFORM_TOTAL_DISEASES/LITREX_PLATFORM_TOTAL_TARGETS)"
        )

    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    start = (
        date.fromisoformat(args.start_date)
        if args.start_date
        else end.replace(year=end.year - 2)
    )

    candidates = load_candidates(args.input_dir, start, end, args.sections)
    print(f"loaded {candidates.num_rows} candidate rows from {args.input_dir}")

    existing = None
    manifest_path = Path(args.manifest_path)
    if manifest_path.exists():
        existing = pq.read_table(manifest_path)
        print(f"found existing manifest with {existing.num_rows} rows at {manifest_path}")

    sample, metrics = draw_sample(
        candidates,
        total_diseases=args.total_diseases,
        total_targets=args.total_targets,
        target_size=args.target_size,
        existing=existing,
        seed=args.seed,
    )
    write_manifest(sample, manifest_path)
    append_metadata(
        metrics,
        filters={
            "start_date": str(start),
            "end_date": str(end),
            "sections": args.sections,
        },
        path=args.metadata_path,
    )

    print(
        f"manifest now has {sample.num_rows} rows "
        f"({metrics['new_rows_added']} new) at {manifest_path}"
    )
    print(
        f"disease coverage: {metrics['disease_coverage']:.2%} "
        f"({metrics['n_diseases']}/{args.total_diseases}), "
        f"target coverage: {metrics['target_coverage']:.2%} "
        f"({metrics['n_targets']}/{args.total_targets})"
    )
    entropy = metrics["ontology_spread"]["normalized_entropy"]
    print(f"ontology spread (normalized entropy): {entropy:.3f}")


if __name__ == "__main__":
    _main()


__all__ = [
    "coverage",
    "draw_sample",
    "filter_window",
    "load_candidates",
    "ontology_spread",
    "write_manifest",
]
