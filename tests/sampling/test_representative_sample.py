from datetime import date

import pyarrow as pa
import pytest

from litrex.sampling import representative_sample as rs


def _table(n=4):
    base = {
        "target": ["T1", "T1", "T2", "T3"],
        "disease": ["D1", "D2", "D2", "D3"],
        "text": ["t1", "t2", "t3", "t4"],
        "publication_id": ["P1", "P2", "P3", "P4"],
        "publication_date": [
            date(2023, 1, 1),
            date(2020, 1, 1),
            date(2023, 6, 1),
            date(2023, 6, 1),
        ],
        "section": ["abstract", "abstract", "results", "abstract"],
    }
    return pa.table(base)


_STUB_SPREAD = {
    "n_buckets": 1,
    "bucket_counts": {},
    "bucket_proportions": {},
    "normalized_entropy": 0.0,
}


@pytest.fixture(autouse=True)
def _stub_ontology_spread(monkeypatch):
    monkeypatch.setattr(rs, "ontology_spread", lambda table: _STUB_SPREAD)


def test_filter_window():
    filtered = rs.filter_window(
        _table(), start=date(2022, 1, 1), end=date(2024, 1, 1), sections=["abstract"]
    )
    assert filtered.num_rows == 2


def test_coverage():
    result = rs.coverage(_table(), total_diseases=10, total_targets=10)
    assert result["disease_coverage"] == 0.3
    assert result["target_coverage"] == 0.3
    assert result["n_diseases"] == 3
    assert result["n_targets"] == 3


def test_draw_sample_first_run_draws_up_to_target_size():
    sample, metrics = rs.draw_sample(
        _table(), total_diseases=10, total_targets=10, target_size=2, seed=0
    )
    assert sample.num_rows == 2
    assert metrics["new_rows_added"] == 2
    assert metrics["sample_size"] == 2
    assert len(set(sample["sample_row_id"].to_pylist())) == 2


def test_draw_sample_tops_up_without_redrawing_existing_rows():
    first, _ = rs.draw_sample(_table(), total_diseases=10, total_targets=10, target_size=2, seed=0)
    second, metrics = rs.draw_sample(
        _table(), total_diseases=10, total_targets=10, target_size=4, existing=first, seed=1
    )
    assert second.num_rows == 4
    assert metrics["new_rows_added"] == 2
    first_ids = set(first["sample_row_id"].to_pylist())
    second_ids = set(second["sample_row_id"].to_pylist())
    assert first_ids <= second_ids


def test_draw_sample_is_idempotent_when_target_already_met():
    first, _ = rs.draw_sample(_table(), total_diseases=10, total_targets=10, target_size=4, seed=0)
    second, metrics = rs.draw_sample(
        _table(), total_diseases=10, total_targets=10, target_size=4, existing=first, seed=1
    )
    assert metrics["new_rows_added"] == 0
    assert set(first["sample_row_id"].to_pylist()) == set(second["sample_row_id"].to_pylist())


def test_draw_sample_deduplicates_exact_duplicate_rows():
    dup = pa.concat_tables([_table(), _table()])
    sample, metrics = rs.draw_sample(
        dup, total_diseases=10, total_targets=10, target_size=10, seed=0
    )
    assert sample.num_rows == 4
    assert metrics["rows_available_to_draw_from"] == 4
