from datetime import date

import pyarrow as pa
import pytest

from litrex.sampling import representative_sample as rs


def _table():
    return pa.table(
        {
            "target": ["T1", "T1", "T2", "T3"],
            "disease": ["D1", "D2", "D2", "D3"],
            "publication_date": [
                date(2023, 1, 1),
                date(2020, 1, 1),
                date(2023, 6, 1),
                date(2023, 6, 1),
            ],
            "section": ["abstract", "abstract", "results", "abstract"],
        }
    )


def test_filter_window():
    filtered = rs.filter_window(
        _table(), start=date(2022, 1, 1), end=date(2024, 1, 1), sections=["abstract"]
    )
    assert filtered.num_rows == 2


def test_coverage():
    result = rs.coverage(_table(), total_diseases=10, total_targets=10)
    assert result["disease_coverage"] == 0.3
    assert result["target_coverage"] == 0.3


def test_ontology_spread_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        rs.ontology_spread(_table())
