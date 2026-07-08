"""Stage 6 dataset construction: docs/06-classifier-training.md."""

from litrex.schema import LabeledTriple


def build_splits(
    rows: list[LabeledTriple], val_frac: float = 0.1, test_frac: float = 0.1
) -> tuple[list[LabeledTriple], list[LabeledTriple], list[LabeledTriple]]:
    raise NotImplementedError("Stratify by relation label and target/disease pair.")
