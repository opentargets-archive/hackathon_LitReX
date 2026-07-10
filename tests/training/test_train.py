import pytest

from litrex.training.train import (
    BASE_MODEL,
    class_weight_vector,
    compute_metrics_from_preds,
    resolve_alpha,
    smoke_preset,
)


def test_resolve_alpha_scheme_and_override():
    assert resolve_alpha("inverse", None) == 1.0
    assert resolve_alpha("sqrt", None) == 0.5
    assert resolve_alpha("uniform", None) == 0.0
    assert resolve_alpha("inverse", 0.7) == 0.7   # raw alpha wins
    with pytest.raises(ValueError):
        resolve_alpha("bogus", None)


def test_class_weight_vector_alpha_extremes():
    counts = {0: 100, 1: 25, 2: 25}   # imbalanced: class 0 is 4x the others
    # uniform (alpha=0): all weights 1.0
    assert class_weight_vector(counts, 3, alpha=0.0) == {0: 1.0, 1: 1.0, 2: 1.0}
    # normalised to mean 1 => weights sum to num_classes
    inv = class_weight_vector(counts, 3, alpha=1.0)
    assert sum(inv.values()) == pytest.approx(3.0)
    assert inv[1] > inv[0]                          # rare class up-weighted
    # sqrt is gentler than inverse: closer to uniform for the rare class
    sqrt = class_weight_vector(counts, 3, alpha=0.5)
    assert 1.0 < sqrt[1] < inv[1]


def test_class_weight_vector_absent_class_no_div0():
    w = class_weight_vector({0: 10}, 3, alpha=1.0)   # classes 1,2 absent
    assert set(w) == {0, 1, 2} and all(v > 0 for v in w.values())


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
