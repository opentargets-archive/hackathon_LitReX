import pytest

from litrex.training.train import BASE_MODEL, train


def test_base_model_is_biomedical():
    assert "PubMedBERT" in BASE_MODEL


def test_train_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        train([], [])
