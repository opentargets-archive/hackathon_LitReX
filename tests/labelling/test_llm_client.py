import json
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
        data_source="open_targets",
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
    assert triple.data_source == "open_targets"        # provenance carried through
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
        "section": "abstract", "data_source": "open_targets",
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
        "publication_id", "publication_date", "data_source", "evidence_span",
    ]
    assert df.iloc[0]["data_source"] == "open_targets"
    assert df.iloc[0]["evidence_span"] == "EGFR is amplified in NSCLC"
    # the span offsets marked the mentions in the prompt sent to the client
    assert "[[EGFR]]" in client.messages.last_kwargs["messages"][0]["content"]


class FakeBatches:
    """Mimics client.messages.batches for the Batch API path."""

    def __init__(self, judgment: RelationJudgment):
        self._j = judgment
        self.created_requests = None

    def create(self, requests):
        self.created_requests = list(requests)
        return SimpleNamespace(id="batch_test")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended")

    def results(self, batch_id):
        text = json.dumps({
            "relation": self._j.relation,
            "confidence": self._j.confidence,
            "evidence_span": self._j.evidence_span,
        })
        # results come back in arbitrary order — key by custom_id
        for req in reversed(self.created_requests):
            yield SimpleNamespace(
                custom_id=req["custom_id"],
                result=SimpleNamespace(
                    type="succeeded",
                    message=SimpleNamespace(
                        content=[SimpleNamespace(type="text", text=text)]),
                ),
            )


class FakeBatchClient:
    def __init__(self, judgment: RelationJudgment):
        self.messages = SimpleNamespace(batches=FakeBatches(judgment))


def test_run_batch_submits_and_reconciles(tmp_path, monkeypatch):
    manifest = pd.DataFrame([
        {"target": "ENSG1", "disease": "EFO_1", "text": "EGFR in NSCLC.",
         "publication_id": "PMID:1", "publication_date": date(2024, 1, 1),
         "section": "abstract", "data_source": "open_targets",
         "target_start": 0, "target_end": 4, "disease_start": 8, "disease_end": 13},
        {"target": "ENSG2", "disease": "MONDO_2", "text": "BRAF and melanoma.",
         "publication_id": "PMID:2", "publication_date": date(2025, 1, 1),
         "section": "title", "data_source": "gwas_catalog",
         "target_start": 0, "target_end": 4, "disease_start": 9, "disease_end": 17},
    ])
    in_path = tmp_path / "sample.parquet"
    manifest.to_parquet(in_path)
    monkeypatch.setattr(llm_client, "target_names", lambda ids: {i: "GENE" for i in ids})
    monkeypatch.setattr(llm_client, "disease_names", lambda ids: {i: "DISEASE" for i in ids})
    judgment = RelationJudgment(relation="association", confidence=0.7, evidence_span="q")
    client = FakeBatchClient(judgment)

    out_path = tmp_path / "labeled.parquet"
    rep = llm_client.run_batch(in_path, out_path, client=client, poll_interval=0)

    assert rep.rows == rep.labeled == 2
    assert rep.errors == 0
    df = pd.read_parquet(out_path).sort_values("publication_id").reset_index(drop=True)
    assert list(df["data_source"]) == ["open_targets", "gwas_catalog"]  # provenance kept per row
    assert set(df["relation"]) == {"association"}
    # each request used structured output
    for req in client.messages.batches.created_requests:
        assert req["params"]["output_config"]["format"]["type"] == "json_schema"
