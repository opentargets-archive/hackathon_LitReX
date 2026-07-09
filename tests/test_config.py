from datetime import date
from pathlib import Path
from litrex_gwas.config import load_config, compute_cutoff


def test_package_imports():
    import litrex_gwas
    assert "load" in litrex_gwas.__all__


def test_compute_cutoff_subtracts_years():
    assert compute_cutoff(date(2026, 7, 9), 2) == date(2024, 7, 9)


def test_compute_cutoff_leap_day():
    assert compute_cutoff(date(2028, 2, 29), 2) == date(2026, 3, 1)


def test_load_config_parses_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "assoc_dir: /data\nassoc_glob: '*.tsv'\nwindow_years: 2\n"
        "disease_index_url: http://x\ncache_dir: .cache\noutput_path: out.parquet\n"
        "europepmc_base: http://e\npubmed_efetch_base: http://p\nmax_req_per_sec: 3.0\n"
        "min_symbol_len: 2\nmin_disease_syn_len: 4\n"
    )
    cfg = load_config(p)
    assert cfg.assoc_dir == Path("/data")
    assert cfg.window_years == 2
    assert cfg.max_req_per_sec == 3.0
