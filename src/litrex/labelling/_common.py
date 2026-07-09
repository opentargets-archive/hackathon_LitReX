"""Provider-neutral core for stage-5 labelling (shared by the Anthropic and
OpenAI clients).

Holds everything that does not depend on a specific LLM SDK: the structured
judge schema (`RelationJudgment`), manifest row preparation (`prepare`), the
LabeledTriple assembly (`triple_record`), the output writer (`finalize`), and a
generic synchronous runner (`run_sync`) parameterised by a judge callable.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from litrex.labelling.entity_names import disease_names, target_names
from litrex.labelling.prompts import build_prompt
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


@dataclass
class LabelReport:
    rows: int = 0
    labeled: int = 0
    errors: int = 0
    mean_confidence: float = 0.0
    empty_evidence: int = 0


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


def prepare(df: pd.DataFrame) -> list[tuple[str, Cooccurrence, str]]:
    """Resolve names and build the judge prompt per row.

    Returns (custom_id, row, user_prompt) tuples. ``custom_id`` is stable
    (``row-<i>``) so batch results can be keyed back to their manifest row.
    """
    id_to_target = target_names(sorted(df["target"].astype(str).unique()))
    id_to_disease = disease_names(sorted(df["disease"].astype(str).unique()))
    prepared: list[tuple[str, Cooccurrence, str]] = []
    for i, raw in enumerate(df.to_dict("records")):
        tspan = _span(raw, "target_start", "target_end")
        dspan = _span(raw, "disease_start", "disease_end")
        row = Cooccurrence(**raw)  # extra span columns dropped by extra='ignore'
        prompt = build_prompt(
            id_to_target[row.target], id_to_disease[row.disease], row.text, tspan, dspan
        )
        prepared.append((f"row-{i}", row, prompt))
    return prepared


def triple_record(row: Cooccurrence, result: RelationJudgment, judge_model: str) -> dict:
    """Build the output record: LabeledTriple fields + judge_model + evidence_span."""
    triple = LabeledTriple(
        target=row.target, disease=row.disease, text=row.text,
        relation=result.relation, confidence=result.confidence,
        publication_id=row.publication_id, publication_date=row.publication_date,
        data_source=row.data_source,
    )
    record = triple.model_dump()
    record["judge_model"] = judge_model      # provenance: which LLM produced the label
    record["evidence_span"] = result.evidence_span
    return record


def finalize(rep: LabelReport, out_rows: list[dict], output_path: str | Path) -> LabelReport:
    """Write the labelled parquet and fill the report's summary metrics."""
    out = pd.DataFrame(out_rows)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False)
    logger.info("wrote %d labeled triples to %s", len(out), output_path)
    if rep.labeled:
        rep.mean_confidence = round(float(out["confidence"].mean()), 3)
        rep.empty_evidence = int((out["evidence_span"] == "").sum())
    return rep


def run_sync(
    input_path: str | Path,
    output_path: str | Path,
    judge: Callable[[str], RelationJudgment],
    judge_model: str,
    limit: int | None = None,
) -> LabelReport:
    """Synchronous per-row labelling: call ``judge(prompt)`` for each manifest row.

    Provider-agnostic — the caller supplies a ``judge`` that turns a prompt into
    a ``RelationJudgment`` (Anthropic or OpenAI). One bad row is logged and
    skipped rather than aborting the run.
    """
    df = pd.read_parquet(input_path)
    if limit is not None:
        df = df.head(limit)

    rep = LabelReport(rows=len(df))
    out_rows: list[dict] = []
    for _cid, row, prompt in prepare(df):
        try:
            result = judge(prompt)
        except Exception as exc:  # keep going; one bad row shouldn't abort the run
            logger.error("judge failed target=%s disease=%s pmid=%s: %s",
                         row.target, row.disease, row.publication_id, exc)
            rep.errors += 1
            continue
        out_rows.append(triple_record(row, result, judge_model))
        rep.labeled += 1
        if rep.labeled % 25 == 0:
            logger.info("labeled %d/%d", rep.labeled, rep.rows)
    return finalize(rep, out_rows, output_path)
