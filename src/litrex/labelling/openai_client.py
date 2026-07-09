"""Stage 5 LLM relationship-judge client — OpenAI (alternative provider).

Same prompt, schema, and output as the Anthropic client (`llm_client`), but the
judge is an OpenAI chat-completions call with a JSON-schema `response_format`
(structured outputs), plus the OpenAI Batch API for the async path. Selected via
`--provider openai`. The `judge_model` output column records the exact model, so
labels from a GPT run stay distinguishable from a Claude run.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import openai
import pandas as pd

from litrex.labelling._common import (
    LabelReport,
    RelationJudgment,
    finalize,
    prepare,
    run_sync,
    triple_record,
)
from litrex.labelling.prompts import RELATION_OUTPUT_SCHEMA, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4.1"

# OpenAI structured-outputs response format (strict json_schema). The schema
# already has additionalProperties=false and all fields required, as strict mode
# requires.
_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "relation_judgment", "schema": RELATION_OUTPUT_SCHEMA, "strict": True},
}


def _judge_prompt(client: openai.OpenAI, user_prompt: str, model: str) -> RelationJudgment:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=_RESPONSE_FORMAT,
        max_tokens=1024,
    )
    return RelationJudgment(**json.loads(response.choices[0].message.content))


def run(
    input_path: str | Path,
    output_path: str | Path,
    client: openai.OpenAI | None = None,
    limit: int | None = None,
    model: str | None = None,
) -> LabelReport:
    """Label the sample synchronously via the OpenAI API."""
    client = client or openai.OpenAI()  # reads OPENAI_API_KEY
    model = model or DEFAULT_MODEL
    return run_sync(
        input_path, output_path, lambda p: _judge_prompt(client, p, model), model, limit
    )


def _batch_line(custom_id: str, prompt: str, model: str) -> str:
    return json.dumps({
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": _RESPONSE_FORMAT,
            "max_tokens": 1024,
        },
    })


def run_batch(
    input_path: str | Path,
    output_path: str | Path,
    client: openai.OpenAI | None = None,
    limit: int | None = None,
    model: str | None = None,
    poll_interval: float = 30.0,
) -> LabelReport:
    """Label the sample via the OpenAI Batch API (50% cheaper, async)."""
    client = client or openai.OpenAI()
    model = model or DEFAULT_MODEL
    df = pd.read_parquet(input_path)
    if limit is not None:
        df = df.head(limit)

    prepared = prepare(df)
    rows_by_id = {cid: row for cid, row, _ in prepared}
    payload = "\n".join(_batch_line(cid, prompt, model) for cid, _, prompt in prepared).encode()

    upload = client.files.create(file=("batch_requests.jsonl", payload), purpose="batch")
    batch = client.batches.create(
        input_file_id=upload.id, endpoint="/v1/chat/completions", completion_window="24h"
    )
    logger.info("submitted openai batch %s (%d requests)", batch.id, len(rows_by_id))

    terminal = {"completed", "failed", "expired", "cancelled"}
    while True:
        batch = client.batches.retrieve(batch.id)
        if batch.status in terminal:
            break
        logger.info("openai batch %s: %s (poll %.0fs)", batch.id, batch.status, poll_interval)
        time.sleep(poll_interval)

    rep = LabelReport(rows=len(df))
    out_rows: list[dict] = []
    if batch.status != "completed" or not batch.output_file_id:
        logger.error("openai batch %s ended non-complete: %s", batch.id, batch.status)
        return finalize(rep, out_rows, output_path)

    content = client.files.content(batch.output_file_id).text
    for line in content.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        row = rows_by_id.get(obj.get("custom_id"))
        if row is None:
            continue
        resp = obj.get("response") or {}
        if resp.get("status_code") != 200:
            logger.error("openai batch item %s: status %s", obj.get("custom_id"),
                         resp.get("status_code"))
            rep.errors += 1
            continue
        try:
            text = resp["body"]["choices"][0]["message"]["content"]
            judgment = RelationJudgment(**json.loads(text))
        except Exception as exc:
            logger.error("openai batch item %s parse failed: %s", obj.get("custom_id"), exc)
            rep.errors += 1
            continue
        out_rows.append(triple_record(row, judgment, model))
        rep.labeled += 1
    return finalize(rep, out_rows, output_path)
