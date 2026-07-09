import datetime

import pyarrow as pa
import pytest

from litrex.data_sources import cooccurrence
from litrex.schema import Cooccurrence

_TMS_TYPE = pa.list_(pa.struct([
    ("dEnd", pa.int64()), ("dStart", pa.int64()), ("section", pa.string()),
    ("tEnd", pa.int64()), ("tStart", pa.int64()), ("text", pa.string()),
]))


def _epmc_raw() -> pa.Table:
    """Synthetic evidence_europepmc part-table (nested textMiningSentences)."""
    tms = pa.array(
        [
            [
                {"dEnd": 20, "dStart": 15, "section": "abstract",
                 "tEnd": 4, "tStart": 0, "text": "EGFR drives NSCLC in this cohort."},
                {"dEnd": 3, "dStart": 0, "section": "intro",
                 "tEnd": 3, "tStart": 0, "text": "Background discussion sentence."},
            ],
            [{"dEnd": 5, "dStart": 0, "section": "title",
              "tEnd": 20, "tStart": 16, "text": "NSCLC linked to BRAF variants."}],
            [{"dEnd": 5, "dStart": 0, "section": "abstract",
              "tEnd": 4, "tStart": 0, "text": "old paper text here."}],
        ],
        type=_TMS_TYPE,
    )
    return pa.table({
        "targetId": ["ENSG1", "ENSG2", "ENSG3"],
        "diseaseId": ["EFO_1", "EFO_2", "EFO_3"],
        "literature": pa.array([["111"], ["222"], ["333"]], pa.list_(pa.string())),
        "publicationDate": ["2025-01-01", "2024-12-31", "2019-01-01"],
        "resourceScore": [3.0, 4.0, 5.0],
        "textMiningSentences": tms,
    })


def test_to_cooccurrence_epmc_explodes_filters_and_tags():
    out = cooccurrence.to_cooccurrence_epmc(
        _epmc_raw(), start_date=datetime.date(2024, 7, 9), sections=["abstract", "title"]
    )
    df = out.to_pandas()
    # 2019 row dropped by date; 'intro' sentence dropped by section
    assert set(df["publication_id"]) == {"PMID:111", "PMID:222"}
    assert set(df["section"]) <= {"abstract", "title"}
    assert set(df["data_source"]) == {"open_targets"}
    assert len(df) == 2
    row = df[df["publication_id"] == "PMID:111"].iloc[0]
    assert row["target"] == "ENSG1" and row["disease"] == "EFO_1"
    assert row["text"][int(row["target_start"]):int(row["target_end"])] == "EGFR"
    for r in df.to_dict("records"):
        Cooccurrence(**r)  # conforms to the shared contract (extras ignored)


def _raw_table(**overrides: list) -> pa.Table:
    columns = {
        "mappedId1": ["ENSG00000108924", "ENSG00000117984"],
        "type1": ["GP", "GP"],
        "mappedId2": ["MONDO_0004947", "MONDO_0004989"],
        "type2": ["DS", "DS"],
        "isMapped": [True, True],
        "text": ["gene one text", "gene two text"],
        "pmid": ["10023025", "10070889"],
        "date": [datetime.date(1999, 2, 1), datetime.date(1999, 3, 1)],
        "section": ["abstract", "title"],
        "evidenceScore": [3.0, 10.0],
        "start1": [23, 11],
        "end1": [26, 14],
        "start2": [58, 42],
        "end2": [61, 45],
    }
    columns.update(overrides)
    return pa.table(columns)


def test_write_read_roundtrip(tmp_path):
    table = pa.table({"a": [1, 2, 3]})
    destination = tmp_path / "out.parquet"
    cooccurrence.write(table, destination)
    result = cooccurrence.read_raw(destination)
    assert result.to_pydict() == {"a": [1, 2, 3]}


def test_to_cooccurrence_maps_gene_disease_rows():
    mapped = cooccurrence.to_cooccurrence(_raw_table())

    assert mapped.column_names == [
        "target",
        "disease",
        "text",
        "publication_id",
        "publication_date",
        "section",
        "data_source",
        "evidence_score",
        "target_start",
        "target_end",
        "disease_start",
        "disease_end",
        "text_granularity",
    ]
    assert mapped.num_rows == 2
    for row in mapped.to_pylist():
        Cooccurrence(**row)  # extra text_granularity key is ignored by the shared contract
    assert mapped.column("target").to_pylist() == ["ENSG00000108924", "ENSG00000117984"]
    assert mapped.column("disease").to_pylist() == ["MONDO_0004947", "MONDO_0004989"]
    assert mapped.column("publication_id").to_pylist() == ["PMID:10023025", "PMID:10070889"]
    assert set(mapped.column("data_source").to_pylist()) == {"open_targets"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("This is a single sentence.", "sentence"),
        ("This is a single sentence with no terminal punctuation", "sentence"),
        ("This is sentence one. This is sentence two.", "chunk"),
        ("<h4>Conclusions</h4>The keratin 8 antibody stains normal cervical smears.", "chunk"),
        ("Terfenadine dose was 2.7% and 3.4%, respectively over the study period.", "sentence"),
    ],
)
def test_to_cooccurrence_classifies_text_granularity(text, expected):
    raw = _raw_table(text=[text, "gene two text"])

    mapped = cooccurrence.to_cooccurrence(raw)

    assert mapped.column("text_granularity").to_pylist()[0] == expected


def test_to_cooccurrence_filters_non_gene_disease_and_unmapped_rows():
    raw = _raw_table(
        type2=["DS", "GP"],
        isMapped=[False, True],
    )

    mapped = cooccurrence.to_cooccurrence(raw)

    assert mapped.num_rows == 0


def test_to_cooccurrence_missing_column_raises():
    raw = _raw_table()
    raw = raw.drop_columns(["pmid"])

    with pytest.raises(ValueError, match="missing expected upstream columns"):
        cooccurrence.to_cooccurrence(raw)


def test_to_cooccurrence_null_required_field_raises():
    raw = _raw_table(text=["gene one text", None])

    with pytest.raises(ValueError, match="null values found in required column 'text'"):
        cooccurrence.to_cooccurrence(raw)


def test_ingest_maps_and_writes_each_part_file(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    raw_dir.mkdir()
    cooccurrence.write(_raw_table(), raw_dir / "part-00000.parquet")

    row_counts = cooccurrence.ingest(raw_dir, output_dir)

    assert row_counts == {"part-00000.parquet": 2}
    result = cooccurrence.read_raw(output_dir / "part-00000.parquet")
    assert result.num_rows == 2
    assert result.column_names == [
        "target",
        "disease",
        "text",
        "publication_id",
        "publication_date",
        "section",
        "data_source",
        "evidence_score",
        "target_start",
        "target_end",
        "disease_start",
        "disease_end",
        "text_granularity",
    ]
