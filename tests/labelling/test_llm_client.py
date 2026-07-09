from datetime import date
from types import SimpleNamespace

import pandas as pd

from litrex.labelling import llm_client
from litrex.labelling.llm_client import RelationJudgment
from litrex.schema import Cooccurrence


class FakeMessages:
    """Records the request and returns a canned parsed judgment."""

    def __init__(self, judgment: RelationJudgment):
        self._judgment = judgment
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._judgment)


class FakeClient:
    def __init__(self, judgment: RelationJudgment):
        self.messages = FakeMessages(judgment)


def _row():
    return Cooccurrence(
        target="ENSG00000146648",
        disease="EFO_0003060",
        text="EGFR amplification drives NSCLC progression.",
        publication_id="PMID:12345",
        publication_date=date(2024, 1, 1),
        section="abstract",
    )


def test_label_row_maps_judgment_to_labeled_triple():
    judgment = RelationJudgment(
        relation="EGFR amplification is described as driving disease progression",
        confidence=0.9,
        evidence_span="EGFR amplification drives NSCLC progression",
    )
    client = FakeClient(judgment)
    triple, evidence = llm_client.label_row(client, _row(), "EGFR", "NSCLC")
    assert triple.relation == judgment.relation
    assert triple.confidence == 0.9
    assert triple.target == "ENSG00000146648"          # carried from the row
    assert triple.publication_id == "PMID:12345"
    assert evidence == judgment.evidence_span           # kept as raw extra
    # names + span-marked text reach the prompt
    sent = client.messages.last_kwargs
    assert sent["output_format"] is RelationJudgment
    assert "EGFR" in sent["messages"][0]["content"]
    assert "NSCLC" in sent["messages"][0]["content"]


def test_run_writes_labeled_triples_with_evidence(tmp_path, monkeypatch):
    manifest = pd.DataFrame([{
        "target": "ENSG00000146648", "disease": "EFO_0003060",
        "text": "EGFR is amplified in NSCLC.",
        "publication_id": "PMID:1", "publication_date": date(2024, 1, 1),
        "section": "abstract",
        "target_start": 0, "target_end": 4, "disease_start": 21, "disease_end": 26,
    }])
    in_path = tmp_path / "sample.parquet"
    manifest.to_parquet(in_path)

    # stub the network name lookups
    monkeypatch.setattr(llm_client, "target_names", lambda ids: {i: "EGFR" for i in ids})
    monkeypatch.setattr(llm_client, "disease_names", lambda ids: {i: "NSCLC" for i in ids})
    judgment = RelationJudgment(relation="amplification association", confidence=0.8,
                                evidence_span="EGFR is amplified in NSCLC")
    client = FakeClient(judgment)

    out_path = tmp_path / "labeled.parquet"
    rep = llm_client.run(in_path, out_path, client=client)

    assert rep.rows == rep.labeled == 1
    assert rep.errors == 0
    assert rep.mean_confidence == 0.8
    df = pd.read_parquet(out_path)
    assert list(df.columns) == [
        "target", "disease", "text", "relation", "confidence",
        "publication_id", "publication_date", "evidence_span",
    ]
    assert df.iloc[0]["evidence_span"] == "EGFR is amplified in NSCLC"
    # the span offsets marked the mentions in the prompt sent to the client
    assert "[[EGFR]]" in client.messages.last_kwargs["messages"][0]["content"]
