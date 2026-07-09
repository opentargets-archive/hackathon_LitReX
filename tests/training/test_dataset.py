import pytest

from litrex.training.dataset import build_splits


def test_build_splits_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        build_splits([])
