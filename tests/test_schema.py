from datetime import date

from litrex.schema import Cooccurrence, LabeledTriple, ScoredRelationship


def test_cooccurrence_roundtrip():
    row = Cooccurrence(
        target="ENSG00000146648",
        disease="EFO_0003060",
        text="EGFR mutations were associated with NSCLC.",
        publication_id="PMID:12345",
        publication_date=date(2024, 1, 1),
        section="abstract",
        data_source="open_targets",
    )
    assert row.model_dump()["target"] == "ENSG00000146648"
    assert row.data_source == "open_targets"


def test_labeled_triple_confidence_is_float():
    row = LabeledTriple(
        target="ENSG00000146648",
        disease="EFO_0003060",
        text="...",
        relation="negative",
        confidence=0.82,
        publication_id="PMID:12345",
        publication_date=date(2024, 1, 1),
        data_source="gwas_catalog",
    )
    assert row.confidence == 0.82


def test_scored_relationship_has_model_version():
    row = ScoredRelationship(
        target="ENSG00000146648",
        disease="EFO_0003060",
        text="...",
        relation="negative",
        confidence=0.82,
        publication_id="PMID:12345",
        publication_date=date(2024, 1, 1),
        model_version="v0.1.0",
    )
    assert row.model_version == "v0.1.0"
