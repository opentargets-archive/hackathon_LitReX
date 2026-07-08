"""Stage 6 fine-tuning loop: docs/06-classifier-training.md."""

from litrex.schema import LabeledTriple

BASE_MODEL = "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext"


def train(
    train_rows: list[LabeledTriple],
    val_rows: list[LabeledTriple],
    base_model: str = BASE_MODEL,
) -> None:
    raise NotImplementedError("Base model choice not yet confirmed (docs/10-open-questions.md).")
