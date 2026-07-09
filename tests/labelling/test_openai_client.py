import json
from datetime import date
from types import SimpleNamespace

import pandas as pd

from litrex.labelling import _common, openai_client


def _manifest(tmp_path, n=2):
    rows = [{
        "target": f"ENSG{i}", "disease": f"EFO_{i}", "text": "EGFR drives NSCLC.",
        "publication_id": f"PMID:{i}", "publication_date": date(2024, 1, 1),
        "section": "abstract", "data_source": "open_targets" if i % 2 == 0 else "gwas_catalog",
        "target_start": 0, "target_end": 4, "disease_start": 12, "disease_end": 17,
    } for i in range(n)]
    p = tmp_path / "sample.parquet"
    pd.DataFrame(rows).to_parquet(p)
    return p


def _stub_names(monkeypatch):
    monkeypatch.setattr(_common, "target_names", lambda ids: {i: "EGFR" for i in ids})
    monkeypatch.setattr(_common, "disease_names", lambda ids: {i: "NSCLC" for i in ids})


_JUDGMENT_JSON = json.dumps({"relation": "association", "confidence": 0.7, "evidence_span": "q"})


class _FakeCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=_JUDGMENT_JSON))]
        )


class FakeOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_run_sync_openai(tmp_path, monkeypatch):
    _stub_names(monkeypatch)
    client = FakeOpenAI()
    out = tmp_path / "labeled.parquet"
    rep = openai_client.run(_manifest(tmp_path, 1), out, client=client, model="gpt-4.1")

    assert rep.rows == rep.labeled == 1
    df = pd.read_parquet(out)
    assert df.iloc[0]["relation"] == "association"
    assert df.iloc[0]["judge_model"] == "gpt-4.1"       # provenance recorded
    assert df.iloc[0]["data_source"] == "open_targets"
    # structured output was requested via a strict json_schema response_format
    fmt = client.chat.completions.last_kwargs["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True


# --- Batch API path ---

class _FakeFiles:
    def __init__(self, output_text):
        self._out = output_text

    def create(self, file, purpose):
        return SimpleNamespace(id="file_in")

    def content(self, file_id):
        return SimpleNamespace(text=self._out)


class _FakeBatches:
    def create(self, input_file_id, endpoint, completion_window):
        return SimpleNamespace(id="batch_1", status="completed", output_file_id="file_out")

    def retrieve(self, batch_id):
        return SimpleNamespace(id="batch_1", status="completed", output_file_id="file_out")


class FakeOpenAIBatch:
    def __init__(self, output_text):
        self.files = _FakeFiles(output_text)
        self.batches = _FakeBatches()


def _result_line(custom_id):
    body = {"choices": [{"message": {"content": _JUDGMENT_JSON}}]}
    return json.dumps({"custom_id": custom_id, "response": {"status_code": 200, "body": body}})


def test_run_batch_openai(tmp_path, monkeypatch):
    _stub_names(monkeypatch)
    output_text = "\n".join(_result_line(f"row-{i}") for i in range(2))
    client = FakeOpenAIBatch(output_text)
    out = tmp_path / "labeled.parquet"
    rep = openai_client.run_batch(_manifest(tmp_path, 2), out, client=client,
                                  model="gpt-4.1", poll_interval=0)

    assert rep.rows == rep.labeled == 2
    assert rep.errors == 0
    df = pd.read_parquet(out)
    assert set(df["judge_model"]) == {"gpt-4.1"}
    assert set(df["data_source"]) == {"open_targets", "gwas_catalog"}
