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
from .fulltext import load_or_fetch_fulltext
from .cooccurrence import build_cooccurrences, Cooccurrence, DropStats

logger = logging.getLogger(__name__)

SOURCES = ("abstract", "fulltext")


@dataclass
class Report:
    text_source: str = ""
    after_date: int = 0
    after_disease_filter: int = 0
    dropped_by_ontology: dict[str, int] = field(default_factory=dict)
    dropped_measurement: int = 0
    reconciled: int = 0
    unique_pmids: int = 0
    papers_with_text: int = 0
    cooccurrences: int = 0
    by_level: dict[str, int] = field(default_factory=dict)
    by_match_type: dict[str, int] = field(default_factory=dict)
    drops: dict[str, int] = field(default_factory=dict)


def _prepare_disease_index(cfg: Config) -> DiseaseIndex:
    path = download_disease_index(cfg.disease_index_url, cfg.cache_dir / "disease.parquet")
    return load_disease_index(path, cfg.measurement_ta_id)


def _prepare_texts(cfg: Config, pmids: list[str], source: str) -> dict[str, str]:
    if source == "abstract":
        return load_or_fetch_abstracts(pmids, cfg, cfg.cache_dir / "abstracts.parquet")
    return load_or_fetch_fulltext(pmids, cfg, cfg.cache_dir / "fulltext.parquet")


def _output_path(base: Path, source: str) -> Path:
    return base.with_name(f"{base.stem}_{source}{base.suffix}")


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


def _build_pairs(cfg: Config, today: date, idx: DiseaseIndex):
    """Read associations, resolve/filter diseases, group surviving pairs by PMID.

    Returns (by_pmid, base_report) where base_report holds the shared filtering
    counts (identical across text sources).
    """
    base = Report()
    cutoff = compute_cutoff(today, cfg.window_years)
    paths = sorted(cfg.assoc_dir.glob(cfg.assoc_glob))
    logger.info("reading %d association files (cutoff=%s)", len(paths), cutoff)

    by_pmid: dict[str, list[Association]] = {}
    reconciliations: dict[str, tuple[str, str]] = {}
    for a in read_associations(paths, cutoff):
        base.after_date += 1
        canonical, reconciled_from = _resolve_disease(a, idx, cfg)
        if canonical is None:
            prefix = _ontology_prefix(a.disease_id)
            base.dropped_by_ontology[prefix] = base.dropped_by_ontology.get(prefix, 0) + 1
            continue
        if cfg.drop_measurement and idx.is_measurement(canonical):
            base.dropped_measurement += 1
            continue
        if reconciled_from is not None:
            base.reconciled += 1
            reconciliations[reconciled_from] = (canonical, a.disease_label)
        a.disease_id = canonical
        base.after_disease_filter += 1
        by_pmid.setdefault(a.pmid, []).append(a)

    if reconciliations:
        _write_reconciliation_log(cfg.reconciliation_log, reconciliations, idx)
    base.unique_pmids = len(by_pmid)
    return by_pmid, base


def _match_and_write(cfg: Config, by_pmid: dict[str, list[Association]], idx: DiseaseIndex,
                     texts: dict[str, str], source: str, base: Report) -> Report:
    """Match one text corpus, write its Parquet, return a per-source Report."""
    # Copy scalars and a fresh dict of base's shared filtering counts; by_level /
    # by_match_type / drops start empty so they never alias across corpora.
    rep = Report(
        text_source=source,
        after_date=base.after_date,
        after_disease_filter=base.after_disease_filter,
        dropped_by_ontology=dict(base.dropped_by_ontology),
        dropped_measurement=base.dropped_measurement,
        reconciled=base.reconciled,
        unique_pmids=base.unique_pmids,
        papers_with_text=len(texts),
    )

    all_rows: list[Cooccurrence] = []
    totals = DropStats()
    for pmid, assocs in by_pmid.items():
        text = texts.get(pmid)
        if not text:
            continue
        rows, drops = build_cooccurrences(assocs, text, idx, cfg, source)
        all_rows.extend(rows)
        for k in vars(drops):
            setattr(totals, k, getattr(totals, k) + getattr(drops, k))

    rep.cooccurrences = len(all_rows)
    for r in all_rows:
        rep.by_level[r.cooccurrence_level] = rep.by_level.get(r.cooccurrence_level, 0) + 1
        rep.by_match_type[r.match_type] = rep.by_match_type.get(r.match_type, 0) + 1
    rep.drops = vars(totals)

    out = _output_path(cfg.output_path, source)
    out.parent.mkdir(parents=True, exist_ok=True)
    cooccurrences_to_frame(all_rows).to_parquet(out, index=False)
    logger.info("wrote %d %s co-occurrences to %s", len(all_rows), source, out)
    return rep


def run(cfg: Config, today: date, source: str = "both") -> dict[str, Report]:
    """Run the pipeline over one or both text corpora. Returns {source: Report}."""
    sources = SOURCES if source == "both" else (source,)
    idx = _prepare_disease_index(cfg)
    by_pmid, base = _build_pairs(cfg, today, idx)
    reports: dict[str, Report] = {}
    for src in sources:
        texts = _prepare_texts(cfg, list(by_pmid), src)
        reports[src] = _match_and_write(cfg, by_pmid, idx, texts, src, base)
    return reports


def _pair_id(row) -> tuple:
    """Identity of a (target, disease) pair for cross-corpus comparison."""
    tgt = row["target_ensembl"] or row["target_rsid"] or (
        row["target_symbol"][0] if len(row["target_symbol"]) else "")
    return (row["publication_id"], tgt, row["disease"])


def compare_corpora(cfg: Config) -> dict:
    """Compare abstract vs fulltext outputs (must both exist). Returns a stats dict."""
    dfs = {s: pd.read_parquet(_output_path(cfg.output_path, s)) for s in SOURCES}
    pairs = {s: {_pair_id(r) for _, r in df.iterrows()} for s, df in dfs.items()}
    ab, ft = pairs["abstract"], pairs["fulltext"]
    return {
        "cooccurrences": {s: len(df) for s, df in dfs.items()},
        "papers_covered": {s: df["publication_id"].nunique() for s, df in dfs.items()},
        "sentence_level": {s: int((df["cooccurrence_level"] == "sentence").sum())
                           for s, df in dfs.items()},
        "unique_pairs": {s: len(p) for s, p in pairs.items()},
        "pairs_shared": len(ab & ft),
        "pairs_fulltext_only": len(ft - ab),
        "pairs_abstract_only": len(ab - ft),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build GWAS target-disease co-occurrences.")
    parser.add_argument("--config", type=Path, default=Path("config/gwas.yaml"))
    parser.add_argument("--today", type=lambda s: date.fromisoformat(s), default=None)
    parser.add_argument("--source", choices=[*SOURCES, "both"], default="both")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    today = args.today or date.today()
    reports = run(cfg, today, args.source)
    out = {s: asdict(r) for s, r in reports.items()}
    if args.source == "both":
        out["comparison"] = compare_corpora(cfg)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
