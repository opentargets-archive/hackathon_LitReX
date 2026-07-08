"""Stage 5 prompt templates: docs/05-llm-labelling.md."""

JUDGE_PROMPT_TEMPLATE = """In the following text, what is the relationship between \
{target} and {disease}?

Text: {text}

Respond with a relation label and a confidence score between 0 and 1."""


def build_prompt(target_name: str, disease_name: str, text: str) -> str:
    return JUDGE_PROMPT_TEMPLATE.format(target=target_name, disease=disease_name, text=text)
