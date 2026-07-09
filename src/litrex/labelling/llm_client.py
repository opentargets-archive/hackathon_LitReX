"""Stage 5 batched LLM calls: docs/05-llm-labelling.md."""

from anthropic import Anthropic

from litrex.config import settings
from litrex.schema import Cooccurrence, LabeledTriple


def label_row(
    client: Anthropic, row: Cooccurrence, target_name: str, disease_name: str
) -> LabeledTriple:
    raise NotImplementedError("Structured output parsing not yet implemented.")


def label_batch(rows: list[Cooccurrence]) -> list[LabeledTriple]:
    Anthropic(api_key=settings.anthropic_api_key)
    raise NotImplementedError("Target/disease name lookup not yet implemented.")
