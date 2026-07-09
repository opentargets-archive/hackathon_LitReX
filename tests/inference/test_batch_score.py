import pandas as pd
import pytest

from litrex.inference.batch_score import score_partition


def test_score_partition_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        score_partition(
            text=pd.Series(["some text"]),
            target=pd.Series(["EGFR"]),
            disease=pd.Series(["NSCLC"]),
        )
