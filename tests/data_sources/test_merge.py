import datetime

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from litrex.data_sources import merge


def _ot_table():
    # OT-shaped: merge columns + evidence_score extra
    return pa.table({
        "target": ["ENSG1"], "disease": ["EFO_1"], "text": ["EGFR in NSCLC"],
        "publication_id": ["PMID:1"], "publication_date": [datetime.date(2025, 1, 1)],
        "section": ["abstract"], "data_source": ["open_targets"],
        "target_start": [0], "target_end": [4], "disease_start": [8], "disease_end": [13],
        "text_granularity": ["sentence"], "evidence_score": [3.0],
    })


def _gwas_table():
    # GWAS-shaped: merge columns + gwas extras
    return pa.table({
        "target": ["ENSG2"], "disease": ["MONDO_2"], "text": ["BRAF and melanoma"],
        "publication_id": ["PMID:2"], "publication_date": [datetime.date(2025, 6, 1)],
        "section": ["title"], "data_source": ["gwas_catalog"],
        "target_start": [0], "target_end": [4], "disease_start": [9], "disease_end": [17],
        "text_granularity": ["sentence"], "target_rsid": ["rs99"], "match_type": ["symbol"],
    })


def test_normalize_drops_extras_and_casts():
    out = merge.normalize(_gwas_table())
    assert out.schema == merge.MERGE_SCHEMA
    assert "target_rsid" not in out.column_names


def test_normalize_missing_column_raises():
    bad = _ot_table().drop_columns(["section"])
    with pytest.raises(ValueError, match="missing merge columns"):
        merge.normalize(bad)


def test_merge_sources_unifies_schema_and_is_scannable(tmp_path):
    ot_dir = tmp_path / "ot"
    ot_dir.mkdir()
    pq.write_table(_ot_table(), ot_dir / "part-0.parquet")
    gwas_file = tmp_path / "gwas_cooccurrence_abstract.parquet"
    pq.write_table(_gwas_table(), gwas_file)

    out_dir = tmp_path / "merged"
    counts = merge.merge_sources([ot_dir, gwas_file], out_dir)
    assert sum(counts.values()) == 2

    # the merged directory must scan as ONE dataset with a single schema
    dataset = ds.dataset(out_dir, format="parquet")
    table = dataset.to_table()
    assert table.num_rows == 2
    assert set(table.column_names) == set(merge.MERGE_SCHEMA.names)
    assert set(table.column("data_source").to_pylist()) == {"open_targets", "gwas_catalog"}
