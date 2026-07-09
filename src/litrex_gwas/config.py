"""Configuration loading for the GWAS co-occurrence module."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import yaml


@dataclass
class Config:
    assoc_dir: Path
    assoc_glob: str
    window_years: int
    disease_index_url: str
    cache_dir: Path
    output_path: Path
    europepmc_base: str
    pubmed_efetch_base: str
    max_req_per_sec: float
    min_symbol_len: int
    min_disease_syn_len: int


def load_config(path: Path) -> Config:
    """Load a Config from a YAML file."""
    data = yaml.safe_load(Path(path).read_text())
    return Config(
        assoc_dir=Path(data["assoc_dir"]),
        assoc_glob=data["assoc_glob"],
        window_years=int(data["window_years"]),
        disease_index_url=data["disease_index_url"],
        cache_dir=Path(data["cache_dir"]),
        output_path=Path(data["output_path"]),
        europepmc_base=data["europepmc_base"],
        pubmed_efetch_base=data["pubmed_efetch_base"],
        max_req_per_sec=float(data["max_req_per_sec"]),
        min_symbol_len=int(data["min_symbol_len"]),
        min_disease_syn_len=int(data["min_disease_syn_len"]),
    )


def compute_cutoff(today: date, window_years: int) -> date:
    """Return the earliest publication date to keep (today minus window_years).

    Rolls a Feb-29 origin to Mar-1 when the target year is not a leap year.
    """
    try:
        return today.replace(year=today.year - window_years)
    except ValueError:
        return date(today.year - window_years, 3, 1)
