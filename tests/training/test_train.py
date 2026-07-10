from litrex.training.train import BASE_MODEL, compute_metrics_from_preds, smoke_preset


def test_smoke_preset_fills_defaults():
    p = smoke_preset(smoke=True, epochs=4, limit=None, output_dir="models/stage6")
    assert p == {"epochs": 1, "limit": 100, "use_cpu": True,
                 "output_dir": "models/stage6_smoke"}


def test_smoke_preset_respects_explicit_flags():
    p = smoke_preset(smoke=True, epochs=2, limit=50, output_dir="models/custom")
    assert p == {"epochs": 2, "limit": 50, "use_cpu": True, "output_dir": "models/custom"}


def test_smoke_preset_noop_when_disabled():
    p = smoke_preset(smoke=False, epochs=4, limit=None, output_dir="models/stage6")
    assert p == {"epochs": 4, "limit": None, "use_cpu": False, "output_dir": "models/stage6"}


def test_base_model_is_biomedical():
    assert "BiomedBERT" in BASE_MODEL or "PubMedBERT" in BASE_MODEL


def test_compute_metrics_from_preds():
    classes = ["a", "b", "c"]
    labels = [0, 0, 1, 1, 2, 2]
    preds = [0, 0, 1, 2, 2, 2]  # one b misclassified as c
    m = compute_metrics_from_preds(labels, preds, classes)
    assert m["accuracy"] == 5 / 6
    assert 0.0 <= m["macro_f1"] <= 1.0
    assert set(m["per_class_f1"]) == {"a", "b", "c"}
    assert m["per_class_f1"]["a"] == 1.0            # a perfectly predicted
    assert len(m["confusion_matrix"]) == 3          # 3x3
