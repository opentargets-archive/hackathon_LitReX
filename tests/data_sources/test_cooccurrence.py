import pyarrow as pa
import pytest

from litrex.data_sources import cooccurrence


def test_write_read_roundtrip(tmp_path):
    table = pa.table({"a": [1, 2, 3]})
    destination = tmp_path / "out.parquet"
    cooccurrence.write(table, destination)
    result = cooccurrence.read_raw(destination)
    assert result.to_pydict() == {"a": [1, 2, 3]}


def test_to_cooccurrence_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        cooccurrence.to_cooccurrence(pa.table({"a": [1]}))
