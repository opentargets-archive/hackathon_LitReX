"""Stage 7 scoring function, wrappable as a Spark pandas UDF: docs/07-inference.md."""

import pandas as pd


def score_partition(
    text: pd.Series, target: pd.Series, disease: pd.Series
) -> pd.DataFrame:
    """Batch-score one partition. Signature matches a Spark pandas_udf.

    Returns a DataFrame with columns: relation, confidence, model_version.
    """
    raise NotImplementedError("Model loading/broadcast strategy not yet implemented.")
