"""Shared data contracts. See docs/README.md for the pipeline-wide contract."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Cooccurrence(BaseModel):
    """Output contract for every data source (docs/02, docs/03).

    ``data_source`` records provenance of the co-occurrence so the merged
    dataset (Open Targets EPMC + GWAS Catalog) stays traceable through
    sampling and labelling. ``publication_id`` is a prefixed identifier
    (``PMID:12345``), not a bare accession.
    """

    target: str
    disease: str
    text: str
    publication_id: str
    publication_date: date
    section: str
    data_source: str


class LabeledTriple(BaseModel):
    """Silver-label output of the LLM judge (docs/05-llm-labelling.md)."""

    target: str
    disease: str
    text: str
    relation: str
    confidence: float
    publication_id: str
    publication_date: date
    data_source: str


class ScoredRelationship(BaseModel):
    """Output of the trained classifier at inference time (docs/07-inference.md)."""

    target: str
    disease: str
    text: str
    relation: str
    confidence: float
    publication_id: str
    publication_date: date
    model_version: str
