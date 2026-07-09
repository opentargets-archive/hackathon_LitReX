"""Stage 5 LLM relationship-judge client (docs/05-llm-labelling.md).

The real ``anthropic.Anthropic()``-based labelling pipeline that docs/13 flagged
as still-needed (the prior pass used one-off sub-agents, not a rerunnable
script). It reads the stage-4 sample, resolves target/disease IDs to display
names, asks Claude to describe the relationship each row's TEXT asserts —
structured output of ``relation`` + ``confidence`` + ``evidence_span`` — and
writes validated ``LabeledTriple`` rows plus the raw ``evidence_span``.

Uses the prompt design frozen in ``prompts.py`` (free-text ``relation``, explicit
grounding, confidence rubric, ``[[...]]`` span marking) unchanged.
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic
import pandas as pd
from pydantic import BaseModel

from litrex.config import settings
from litrex.labelling.entity_names import disease_names, target_names
from litrex.labelling.prompts import SYSTEM_PROMPT, build_prompt
from litrex.schema import Cooccurrence, LabeledTriple

logger = logging.getLogger(__name__)

# Span columns produced by stage 2 / stage 3 (dropped by the Cooccurrence
# contract's extra='ignore' parsing, so read them off the raw row).
_SPAN_COLUMNS = ("target_start", "target_end", "disease_start", "disease_end")


class RelationJudgment(BaseModel):
    """Structured judge output.

    ``evidence_span`` is an extra field beyond the ``LabeledTriple`` contract —
    retained only in the raw output parquet for the manual-review pass.
    """

    relation: str
    confidence: float
    evidence_span: str


def _span(row: dict, start_key: str, end_key: str) -> tuple[int, int] | None:
    """Read a (start, end) char-offset span off a raw manifest row, or None."""
    start, end = row.get(start_key), row.get(end_key)
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        return None
    return (start, end) if 0 <= start < end else None


def judge(
    client: anthropic.Anthropic,
    target_name: str,
    disease_name: str,
    text: str,
    target_span: tuple[int, int] | None = None,
    disease_span: tuple[int, int] | None = None,
    model: str | None = None,
) -> RelationJudgment:
    """Ask Claude to describe the relationship TEXT asserts (structured output)."""
    user_prompt = build_prompt(target_name, disease_name, text, target_span, disease_span)
    response = client.messages.parse(
        model=model or settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=RelationJudgment,
    )
    return response.parsed_output


def label_row(
    client: anthropic.Anthropic,
    row: Cooccurrence,
    target_name: str,
    disease_name: str,
    target_span: tuple[int, int] | None = None,
    disease_span: tuple[int, int] | None = None,
    model: str | None = None,
) -> tuple[LabeledTriple, str]:
    """Judge one row. Returns (LabeledTriple, evidence_span)."""
    result = judge(client, target_name, disease_name, row.text, target_span, disease_span, model)
    triple = LabeledTriple(
        target=row.target,
        disease=row.disease,
        text=row.text,
        relation=result.relation,
        confidence=result.confidence,
        publication_id=row.publication_id,
        publication_date=row.publication_date,
    )
    return triple, result.evidence_span


@dataclass
class LabelReport:
    rows: int = 0
    labeled: int = 0
    errors: int = 0
    mean_confidence: float = 0.0
    empty_evidence: int = 0


def run(
    input_path: str | Path,
    output_path: str | Path,
    client: anthropic.Anthropic | None = None,
    limit: int | None = None,
    model: str | None = None,
) -> LabelReport:
    """Label every row of the stage-4 sample and write a LabeledTriple parquet.

    The output carries the six LabeledTriple contract fields plus the raw
    ``evidence_span`` column (kept for the manual-review pass, docs/05 step 4).
    """
    client = client or anthropic.Anthropic()
    df = pd.read_parquet(input_path)
    if limit is not None:
        df = df.head(limit)

    id_to_target = target_names(sorted(df["target"].astype(str).unique()))
    id_to_disease = disease_names(sorted(df["disease"].astype(str).unique()))

    rep = LabelReport(rows=len(df))
    out_rows: list[dict] = []
    for raw in df.to_dict("records"):
        tspan = _span(raw, "target_start", "target_end")
        dspan = _span(raw, "disease_start", "disease_end")
        row = Cooccurrence(**raw)  # extra span columns dropped by extra='ignore'
        try:
            triple, evidence = label_row(
                client, row, id_to_target[row.target], id_to_disease[row.disease],
                tspan, dspan, model,
            )
        except Exception as exc:  # keep going; one bad row shouldn't abort the run
            logger.error("judge failed target=%s disease=%s pmid=%s: %s",
                         row.target, row.disease, row.publication_id, exc)
            rep.errors += 1
            continue
        record = triple.model_dump()
        record["evidence_span"] = evidence
        out_rows.append(record)
        rep.labeled += 1
        if rep.labeled % 25 == 0:
            logger.info("labeled %d/%d", rep.labeled, rep.rows)

    out = pd.DataFrame(out_rows)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False)
    logger.info("wrote %d labeled triples to %s", len(out), output_path)
    if rep.labeled:
        rep.mean_confidence = round(float(out["confidence"].mean()), 3)
        rep.empty_evidence = int((out["evidence_span"] == "").sum())
    return rep


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 5: LLM relationship-judge labelling.")
    parser.add_argument("--input", type=Path,
                        default=Path("data/processed/sample_manifest.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("data/processed/labeled_triples.parquet"))
    parser.add_argument("--limit", type=int, default=None, help="Label only the first N rows.")
    parser.add_argument("--model", type=str, default=None,
                        help="Override settings.anthropic_model.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rep = run(args.input, args.output, limit=args.limit, model=args.model)
    print(json.dumps(asdict(rep), indent=2))


if __name__ == "__main__":
    main()
