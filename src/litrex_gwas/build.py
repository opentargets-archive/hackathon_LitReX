"""Orchestrate the GWAS co-occurrence pipeline and write Parquet output."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
import argparse
import json
import logging
import pandas as pd

from .config import Config, load_config, compute_cutoff
from .load import read_associations, Association
from .disease_index import download_disease_index, load_disease_index, DiseaseIndex
from .abstracts import load_or_fetch_abstracts
from .cooccurrence import build_cooccurrences, Cooccurrence, DropStats

logger = logging.getLogger(__name__)


@dataclass
class Report:
    after_date: int = 0
    after_disease_filter: int = 0
    dropped_by_ontology: dict[str, int] = field(default_factory=dict)
    dropped_measurement: int = 0
    reconciled: int = 0
    unique_pmids: int = 0
    abstracts_found: int = 0
    cooccurrences: int = 0
    by_level: dict[str, int] = field(default_factory=dict)
    by_match_type: dict[str, int] = field(default_factory=dict)
    drops: dict[str, int] = field(default_factory=dict)


def _prepare_disease_index(cfg: Config) -> DiseaseIndex:
    path = download_disease_index(cfg.disease_index_url, cfg.cache_dir / "disease.parquet")
    return load_disease_index(path, cfg.measurement_ta_id)


def _prepare_abstracts(cfg: Config, pmids: list[str]) -> dict[str, str]:
    return load_or_fetch_abstracts(pmids, cfg, cfg.cache_dir / "abstracts.parquet")


def _ontology_prefix(disease_id: str) -> str:
    return disease_id.split("_", 1)[0] if disease_id else "?"


def _resolve_disease(a: Association, idx: DiseaseIndex, cfg: Config):
    """Resolve a GWAS trait to a canonical disease ID.

    Returns (canonical_id, reconciled_from) where reconciled_from is the original
    GWAS ID if it was recovered by name match (else None), or (None, None) if the
    trait is not a resolvable disease.
    """
    if idx.contains(a.disease_id):
        return a.disease_id, None
    if cfg.reconcile_by_name:
        canonical = idx.resolve_name(a.disease_label)
        if canonical:
            return canonical, a.disease_id
    return None, None


def _write_reconciliation_log(path: Path, recs: dict[str, tuple[str, str]],
                              idx: DiseaseIndex) -> None:
    """Write recovered (superseded GWAS ID -> canonical OT ID) mappings for review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"gwas_id": gid, "gwas_label": label, "ot_canonical_id": cid,
             "ot_name": idx.terms[cid].name if idx.contains(cid) else ""}
            for gid, (cid, label) in sorted(recs.items())]
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    logger.info("wrote %d name-reconciled disease mappings to %s", len(rows), path)


def cooccurrences_to_frame(rows: list[Cooccurrence]) -> pd.DataFrame:
    records = []
    for r in rows:
        d = asdict(r)
        d["target_span"] = list(r.target_span)
        d["disease_span"] = list(r.disease_span)
        records.append(d)
    return pd.DataFrame.from_records(records)


def run(cfg: Config, today: date) -> Report:
    """Run the full pipeline and write Parquet output. Returns a Report."""
    rep = Report()
    cutoff = compute_cutoff(today, cfg.window_years)
    paths = sorted(cfg.assoc_dir.glob(cfg.assoc_glob))
    logger.info("reading %d association files (cutoff=%s)", len(paths), cutoff)

    idx = _prepare_disease_index(cfg)

    by_pmid: dict[str, list[Association]] = {}
    reconciliations: dict[str, tuple[str, str]] = {}  # gwas_id -> (canonical_id, label)
    for a in read_associations(paths, cutoff):
        rep.after_date += 1
        canonical, reconciled_from = _resolve_disease(a, idx, cfg)
        if canonical is None:
            prefix = _ontology_prefix(a.disease_id)
            rep.dropped_by_ontology[prefix] = rep.dropped_by_ontology.get(prefix, 0) + 1
            continue
        if cfg.drop_measurement and idx.is_measurement(canonical):
            rep.dropped_measurement += 1
            continue
        if reconciled_from is not None:
            rep.reconciled += 1
            reconciliations[reconciled_from] = (canonical, a.disease_label)
        a.disease_id = canonical  # canonicalize output ID
        rep.after_disease_filter += 1
        by_pmid.setdefault(a.pmid, []).append(a)

    if reconciliations:
        _write_reconciliation_log(cfg.reconciliation_log, reconciliations, idx)

    rep.unique_pmids = len(by_pmid)
    abstracts = _prepare_abstracts(cfg, list(by_pmid))
    rep.abstracts_found = len(abstracts)

    all_rows: list[Cooccurrence] = []
    totals = DropStats()
    for pmid, assocs in by_pmid.items():
        abstract = abstracts.get(pmid)
        if not abstract:
            continue
        rows, drops = build_cooccurrences(assocs, abstract, idx, cfg)
        all_rows.extend(rows)
        for k in vars(drops):
            setattr(totals, k, getattr(totals, k) + getattr(drops, k))

    rep.cooccurrences = len(all_rows)
    for r in all_rows:
        rep.by_level[r.cooccurrence_level] = rep.by_level.get(r.cooccurrence_level, 0) + 1
        rep.by_match_type[r.match_type] = rep.by_match_type.get(r.match_type, 0) + 1
    rep.drops = vars(totals)

    cfg.output_path.parent.mkdir(parents=True, exist_ok=True)
    df = cooccurrences_to_frame(all_rows)
    df.to_parquet(cfg.output_path, index=False)
    logger.info("wrote %d co-occurrences to %s", len(df), cfg.output_path)
    return rep


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build GWAS target-disease co-occurrences.")
    parser.add_argument("--config", type=Path, default=Path("config/gwas.yaml"))
    parser.add_argument("--today", type=lambda s: date.fromisoformat(s), default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    today = args.today or date.today()
    rep = run(cfg, today)
    print(json.dumps(asdict(rep), indent=2, default=str))


if __name__ == "__main__":
    main()
