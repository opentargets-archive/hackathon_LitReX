"""Stage 5 LLM relationship-judge client — Anthropic (docs/05-llm-labelling.md).

The default, on-design judge: asks Claude to describe the relationship each
sampled row's TEXT asserts (structured output: relation + confidence +
evidence_span) and writes validated ``LabeledTriple`` rows plus the raw
``evidence_span`` and a ``judge_model`` provenance column. Provider-neutral
plumbing (prompt build, record assembly, output) lives in ``_common``; an
alternative OpenAI judge lives in ``openai_client``.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

import anthropic
import pandas as pd
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from litrex.config import settings
from litrex.labelling._common import (
    LabelReport,
    RelationJudgment,
    finalize,
    prepare,
    run_sync,
    triple_record,
)
from litrex.labelling.prompts import RELATION_OUTPUT_SCHEMA, SYSTEM_PROMPT, build_prompt
from litrex.schema import Cooccurrence, LabeledTriple

logger = logging.getLogger(__name__)

__all__ = [
    "RelationJudgment", "LabelReport", "judge", "label_row", "run", "run_batch", "main",
]


def _judge_prompt(client: anthropic.Anthropic, user_prompt: str, model: str) -> RelationJudgment:
    response = client.messages.parse(
        model=model, max_tokens=1024, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=RelationJudgment,
    )
    return response.parsed_output


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
    prompt = build_prompt(target_name, disease_name, text, target_span, disease_span)
    return _judge_prompt(client, prompt, model or settings.anthropic_model)


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
        target=row.target, disease=row.disease, text=row.text,
        relation=result.relation, confidence=result.confidence,
        publication_id=row.publication_id, publication_date=row.publication_date,
        data_source=row.data_source,
    )
    return triple, result.evidence_span


def run(
    input_path: str | Path,
    output_path: str | Path,
    client: anthropic.Anthropic | None = None,
    limit: int | None = None,
    model: str | None = None,
) -> LabelReport:
    """Label the sample synchronously via the Anthropic API."""
    # settings.anthropic_api_key comes from LITREX_ANTHROPIC_API_KEY; passing None
    # falls back to the SDK's own resolution (ANTHROPIC_API_KEY / ant profile).
    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = model or settings.anthropic_model
    return run_sync(
        input_path, output_path, lambda p: _judge_prompt(client, p, model), model, limit
    )


def run_batch(
    input_path: str | Path,
    output_path: str | Path,
    client: anthropic.Anthropic | None = None,
    limit: int | None = None,
    model: str | None = None,
    poll_interval: float = 30.0,
) -> LabelReport:
    """Label the sample via the Anthropic Batch API (50% cheaper, async)."""
    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = model or settings.anthropic_model
    df = pd.read_parquet(input_path)
    if limit is not None:
        df = df.head(limit)

    prepared = prepare(df)
    rows_by_id = {cid: row for cid, row, _ in prepared}
    requests = [
        Request(
            custom_id=cid,
            params=MessageCreateParamsNonStreaming(
                model=model, max_tokens=1024, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": RELATION_OUTPUT_SCHEMA}},
            ),
        )
        for cid, _, prompt in prepared
    ]

    batch = client.messages.batches.create(requests=requests)
    logger.info("submitted batch %s (%d requests)", batch.id, len(requests))
    while True:
        status = client.messages.batches.retrieve(batch.id).processing_status
        if status == "ended":
            break
        logger.info("batch %s: %s (poll %.0fs)", batch.id, status, poll_interval)
        time.sleep(poll_interval)

    rep = LabelReport(rows=len(df))
    out_rows: list[dict] = []
    for result in client.messages.batches.results(batch.id):
        row = rows_by_id.get(result.custom_id)
        if row is None:
            continue
        if result.result.type != "succeeded":
            logger.error("batch item %s failed: %s", result.custom_id, result.result.type)
            rep.errors += 1
            continue
        try:
            text = next(b.text for b in result.result.message.content if b.type == "text")
            judgment = RelationJudgment(**json.loads(text))
        except Exception as exc:
            logger.error("batch item %s parse failed: %s", result.custom_id, exc)
            rep.errors += 1
            continue
        out_rows.append(triple_record(row, judgment, model))
        rep.labeled += 1
    return finalize(rep, out_rows, output_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 5: LLM relationship-judge labelling.")
    parser.add_argument("--input", type=Path,
                        default=Path("data/processed/sample_manifest.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("data/processed/labeled_triples.parquet"))
    parser.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    parser.add_argument("--limit", type=int, default=None, help="Label only the first N rows.")
    parser.add_argument("--model", type=str, default=None, help="Override the provider's model.")
    parser.add_argument("--batch", action="store_true",
                        help="Use the provider's Batch API (async, ~50%% cheaper).")
    parser.add_argument("--poll-interval", type=float, default=30.0,
                        help="Seconds between batch status polls (with --batch).")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.provider == "openai":
        from litrex.labelling import openai_client as impl
    else:
        import litrex.labelling.llm_client as impl

    runner = impl.run_batch if args.batch else impl.run
    kwargs = {"limit": args.limit, "model": args.model}
    if args.batch:
        kwargs["poll_interval"] = args.poll_interval
    rep = runner(args.input, args.output, **kwargs)
    print(json.dumps(asdict(rep), indent=2))


if __name__ == "__main__":
    main()
