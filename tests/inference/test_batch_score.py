import json

import pandas as pd

from litrex.inference import batch_score


def test_build_inputs_resolves_and_marks(monkeypatch):
    monkeypatch.setattr(batch_score, "target_names", lambda ids: {i: "EGFR" for i in ids})
    monkeypatch.setattr(batch_score, "disease_names", lambda ids: {i: "NSCLC" for i in ids})
    df = pd.DataFrame({"target": ["ENSG1"], "disease": ["EFO_1"], "text": ["x drives y"]})
    assert batch_score.build_inputs(df) == ["[TGT] EGFR [/TGT] [DIS] NSCLC [/DIS] x drives y"]


def test_build_inputs_no_resolve_is_passthrough():
    df = pd.DataFrame({"target": ["EGFR"], "disease": ["NSCLC"], "text": ["z"]})
    assert batch_score.build_inputs(df, resolve=False) == ["[TGT] EGFR [/TGT] [DIS] NSCLC [/DIS] z"]


def test_model_version_reads_card(tmp_path):
    (tmp_path / "model_card.json").write_text(json.dumps({
        "taxonomy_version": "stage6a-embedding-prototype-v1",
        "class_weighting": {"scheme": "sqrt"},
    }))
    mdir = tmp_path / "model"
    mdir.mkdir()
    assert batch_score.model_version(mdir) == "stage6a-embedding-prototype-v1+weight-sqrt"


def test_model_version_falls_back_to_dir_name(tmp_path):
    mdir = tmp_path / "model"
    mdir.mkdir()
    assert batch_score.model_version(mdir) == "model"
