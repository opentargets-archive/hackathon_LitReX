"""Load and normalize GWAS Catalog association rows into Association records."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_COLS = ["PUBMEDID", "DATE", "STUDY", "MAPPED_GENE", "SNP_GENE_IDS", "SNPS",
         "P-VALUE", "MAPPED_TRAIT", "MAPPED_TRAIT_URI"]


@dataclass
class Association:
    pmid: str
    date: date
    title: str            # paper title (GWAS `STUDY` column) — the title-corpus text
    disease_id: str
    disease_label: str
    target_ensembl: str | None
    target_symbols: list[str]
    target_rsid: str
    snp: str
    p_value: str


def strip_trait_id(uri: str) -> str:
    """Return the ontology term ID (last URI path segment)."""
    return uri.rstrip("/").rsplit("/", 1)[-1].strip()


def parse_symbols(mapped_gene: str) -> list[str]:
    """Split a MAPPED_GENE cell into individual gene symbols.

    Handles intergenic pairs ('A - B') and comma-separated lists.
    """
    if not mapped_gene or not str(mapped_gene).strip():
        return []
    parts: list[str] = []
    for chunk in str(mapped_gene).split(","):
        for sym in chunk.split(" - "):
            sym = sym.strip()
            if sym:
                parts.append(sym)
    return parts


def _parse_date(raw: str) -> date | None:
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def read_associations(paths: list[Path], cutoff: date) -> Iterator[Association]:
    """Yield one Association per (row, mapped trait), filtering by date.

    Rows with empty PMID, unparseable/old date, or empty trait URI are skipped.
    MAPPED_TRAIT and MAPPED_TRAIT_URI are comma-aligned and exploded together.
    """
    for path in paths:
        df = pd.read_csv(path, sep="\t", dtype=str, usecols=lambda c: c in _COLS,
                         keep_default_na=False)
        for _, row in df.iterrows():
            pmid = row.get("PUBMEDID", "").strip()
            if not pmid:
                continue
            d = _parse_date(row.get("DATE", ""))
            if d is None or d < cutoff:
                continue
            uris = [u.strip() for u in row.get("MAPPED_TRAIT_URI", "").split(",") if u.strip()]
            labels = [t.strip() for t in row.get("MAPPED_TRAIT", "").split(",")]
            if not uris:
                continue
            ens = row.get("SNP_GENE_IDS", "").strip() or None
            symbols = parse_symbols(row.get("MAPPED_GENE", ""))
            rsid = row.get("SNPS", "").strip()
            snp = rsid
            pval = row.get("P-VALUE", "").strip()
            title = row.get("STUDY", "").strip()
            for i, uri in enumerate(uris):
                label = labels[i] if i < len(labels) else ""
                yield Association(
                    pmid=pmid, date=d, title=title,
                    disease_id=strip_trait_id(uri), disease_label=label,
                    target_ensembl=ens, target_symbols=symbols,
                    target_rsid=rsid, snp=snp, p_value=pval,
                )
