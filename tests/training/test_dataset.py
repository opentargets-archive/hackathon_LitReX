import json
from datetime import date

import pandas as pd

from litrex.training import dataset


def test_build_input_text_has_typed_markers():
    s = dataset.build_input_text("EGFR", "NSCLC", "EGFR drives NSCLC.")
    assert s == "[TGT] EGFR [/TGT] [DIS] NSCLC [/DIS] EGFR drives NSCLC."


def _classified(n_per_class=22):
    classes = ["no_relationship", "upregulation", "association"]
    rows = []
    i = 0
    for c in classes:
        for _ in range(n_per_class):
            rows.append({
                "target": f"ENSG{i}", "disease": f"EFO_{i}",
                "text": f"sentence {i} about the pair",
                "relation": f"desc {i}", "confidence": 0.2 if i % 20 == 0 else 0.8,
                "publication_id": f"PMID:{i}", "publication_date": date(2025, 1, 1),
                "data_source": "open_targets" if i % 3 else "gwas_catalog",
                "relation_class": c, "class_margin": 0.05,
            })
            i += 1
    return pd.DataFrame(rows)


def test_prepare_splits_no_leak_and_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, "target_names", lambda ids: {i: "GENE" for i in ids})
    monkeypatch.setattr(dataset, "disease_names", lambda ids: {i: "DISEASE" for i in ids})
    in_p = tmp_path / "classified.parquet"
    _classified().to_parquet(in_p)
    out = tmp_path / "splits"

    meta = dataset.prepare(in_p, out, min_confidence=0.3, seed=0, n_splits=10, cv_folds=5)

    assert sum(meta["sizes"].values()) < 66            # low-confidence rows filtered
    assert set(meta["classes"]) == {"no_relationship", "upregulation", "association"}
    for name in ("train", "val", "test"):
        assert (out / f"{name}.parquet").exists()
    assert (out / "dataset_meta.json").exists()

    train = pd.read_parquet(out / "train.parquet")
    val = pd.read_parquet(out / "val.parquet")
    test = pd.read_parquet(out / "test.parquet")
    # grouped: no PMID crosses splits
    assert not (set(train["publication_id"]) & set(test["publication_id"]))
    assert not (set(val["publication_id"]) & set(test["publication_id"]))
    # markers + cv column present
    assert train["input_text"].str.startswith("[TGT]").all()
    assert "cv_fold" in train.columns and set(train["cv_fold"]) <= set(range(5))
    assert json.loads((out / "dataset_meta.json").read_text())["label2id"]
