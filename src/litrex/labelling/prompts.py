"""Stage 5 prompt templates: docs/05-llm-labelling.md.

Design notes (see docs/12-session-log-sampling.md's sibling session log for
the full rationale):

- `relation` is a free-text description in the model's own words, not a label
  drawn from the docs/01 starting taxonomy (or any other fixed set) -- this
  pass only describes what TEXT asserts; classifying those descriptions into
  a taxonomy is explicitly deferred to a later step (docs/06), so the prompt
  must not bias the model toward pre-existing categories.
- Plain co-mention (no relationship stated) is called out explicitly as an
  expected, describable outcome -- most co-occurrence text spans are plain
  mentions, not asserted relationships -- so the model states that plainly
  rather than inventing a relationship to fill the field.
- `evidence_span` is requested as an extra field beyond the `LabeledTriple`
  contract (dropped by `Cooccurrence`-style extra='ignore' parsing, kept only
  in the raw output) -- gives the manual review pass (docs/05 step 4)
  something concrete to check the label against.
- Optional character-offset span marking (`target_span`/`disease_span`)
  disambiguates which mention is under judgment when the same gene symbol or
  disease term appears more than once in a multi-sentence ("chunk"
  granularity) text span. Offsets are the `target_start`/`target_end`/
  `disease_start`/`disease_end` extra columns already produced by stage 2.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are a biomedical relation-extraction judge. You will be shown a \
short passage from scientific literature (TEXT) that mentions a specific gene/protein \
(TARGET) and a specific disease (DISEASE). Your job is to describe, in your own words, \
what relationship (if any) TEXT itself asserts between TARGET and DISEASE.

Ground your description only in what TEXT says. Do not rely on outside knowledge of \
TARGET or DISEASE -- a well-known real-world relationship that TEXT does not actually \
state is not a valid basis for your answer.

Write `relation` as a short, free-text description in your own words -- not a label \
drawn from any fixed category. Describe what TEXT actually claims (e.g. direction of \
effect, strength of evidence, type of relationship) as specifically as TEXT supports, \
and no more specifically than that. Do not try to classify or categorize the \
relationship -- a later step will classify these free-text descriptions, so your job \
here is only to describe precisely, not to categorize.

If TARGET and DISEASE merely appear together in TEXT without TEXT asserting any \
relationship between them (e.g. a gene list, a background statement, an unrelated \
comparison), say so plainly -- e.g. "text mentions both but does not state a \
relationship" -- rather than inventing one. If TEXT explicitly states there is no \
relationship, or that an association was tested and not found, describe that instead.

For confidence (0-1), calibrate to how explicit and unambiguous TEXT is: reserve 0.85+ \
for direct, unhedged statements; use 0.5-0.8 for hedged or indirect language ("may be \
associated with", "could contribute to"); use below 0.5 when TEXT is ambiguous about \
whether a relationship is even being claimed.

If TARGET/DISEASE mentions in TEXT are marked with [[double brackets]], those mark the \
specific occurrence you are describing -- TEXT may mention the same gene or disease \
elsewhere without brackets; ignore unbracketed occurrences, they are a different \
mention than the one under judgment. If no brackets appear, TEXT has a single \
unambiguous mention of each entity.

Also return a short evidence_span: a verbatim quote (a few words to one clause, copied \
exactly from TEXT) that supports your description. Leave it empty when TEXT does not \
assert a relationship, or is too undifferentiated to quote a specific span."""

USER_PROMPT_TEMPLATE = """TARGET: {target}
DISEASE: {disease}
TEXT: {text}"""

RELATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "relation": {
            "type": "string",
            "description": (
                "Free-text description, in your own words, of the relationship (if "
                "any) TEXT asserts between TARGET and DISEASE. Not a label from a "
                "fixed set -- describe precisely what TEXT claims; classification "
                "into categories happens in a later step."
            ),
        },
        "confidence": {
            "type": "number",
            "description": (
                "Calibrated confidence 0-1 that `relation` correctly characterizes "
                "what TEXT asserts."
            ),
        },
        "evidence_span": {
            "type": "string",
            "description": "Verbatim quote from TEXT supporting `relation`, or empty string.",
        },
    },
    "required": ["relation", "confidence", "evidence_span"],
    "additionalProperties": False,
}


def _mark_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Wrap each (start, end) char-offset span in `[[...]]`.

    Bails out and returns `text` unmarked if spans overlap or any offset is
    out of bounds -- ambiguous/invalid marking is worse than no marking.
    """
    valid = sorted(spans)
    for i in range(1, len(valid)):
        if valid[i][0] < valid[i - 1][1]:
            return text

    marked = text
    for start, end in sorted(valid, reverse=True):
        if not (0 <= start < end <= len(text)):
            return text
        marked = marked[:start] + "[[" + marked[start:end] + "]]" + marked[end:]
    return marked


def build_prompt(
    target_name: str,
    disease_name: str,
    text: str,
    target_span: tuple[int, int] | None = None,
    disease_span: tuple[int, int] | None = None,
) -> str:
    spans = [s for s in (target_span, disease_span) if s is not None]
    marked_text = _mark_spans(text, spans) if spans else text
    return USER_PROMPT_TEMPLATE.format(target=target_name, disease=disease_name, text=marked_text)
