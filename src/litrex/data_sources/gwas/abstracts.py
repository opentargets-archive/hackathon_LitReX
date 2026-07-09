"""Fetch and cache paper abstracts by PMID (Europe PMC + PubMed fallback)."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import requests

# defusedxml guards against XXE / billion-laughs in the external PubMed XML.
from defusedxml import ElementTree as ET

logger = logging.getLogger(__name__)


def fetch_abstract_europepmc(pmid: str, base: str, session: requests.Session) -> str | None:
    """Fetch an abstract from Europe PMC. Returns None if not found."""
    url = f"{base}/search"
    params = {"query": f"EXT_ID:{pmid} AND SRC:MED", "resultType": "core",
              "format": "json", "pageSize": 1}
    resp = session.get(url, params=params, timeout=60)
    if resp.status_code != 200:
        logger.error("europepmc error pmid=%s url=%s status=%s", pmid, url, resp.status_code)
        return None
    results = resp.json().get("resultList", {}).get("result", [])
    if not results:
        return None
    text = results[0].get("abstractText")
    return text or None


def fetch_abstract_pubmed(pmid: str, base: str, session: requests.Session) -> str | None:
    """Fetch an abstract from NCBI PubMed efetch (XML). Returns None if not found."""
    params = {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"}
    resp = session.get(base, params=params, timeout=60)
    if resp.status_code != 200:
        logger.error("pubmed error pmid=%s status=%s", pmid, resp.status_code)
        return None
    try:
        root = ET.fromstring(resp.text)
    except Exception as exc:  # defusedxml raises on malformed/unsafe XML
        logger.error("pubmed xml parse failed pmid=%s err=%s", pmid, exc)
        return None
    parts = [el.text or "" for el in root.iter("AbstractText")]
    text = " ".join(p.strip() for p in parts if p.strip())
    return text or None


def fetch_abstract(pmid: str, cfg, session: requests.Session) -> tuple[str | None, str]:
    """Europe PMC first, PubMed fallback. Returns (abstract, source)."""
    text = fetch_abstract_europepmc(pmid, cfg.europepmc_base, session)
    if text:
        return text, "europepmc"
    text = fetch_abstract_pubmed(pmid, cfg.pubmed_efetch_base, session)
    if text:
        return text, "pubmed"
    return None, "missing"


def _fetch_with_retry(pmid: str, cfg, session: requests.Session,
                      max_tries: int = 4) -> tuple[str | None, str]:
    delay = 1.0
    for attempt in range(1, max_tries + 1):
        try:
            return fetch_abstract(pmid, cfg, session)
        except requests.RequestException as exc:
            logger.warning("fetch retry pmid=%s attempt=%d err=%s", pmid, attempt, exc)
            if attempt == max_tries:
                return None, "missing"
            time.sleep(delay)
            delay *= 2
    return None, "missing"


def load_or_fetch_abstracts(pmids: list[str], cfg, cache_path: Path) -> dict[str, str]:
    """Return {pmid: abstract} for all pmids, using a parquet cache.

    Only PMIDs absent from cache are fetched, rate-limited to cfg.max_req_per_sec.
    Missing abstracts are cached as empty strings so they are not re-fetched.
    """
    cache_path = Path(cache_path)
    cached: dict[str, str] = {}
    if cache_path.exists():
        cdf = pd.read_parquet(cache_path)
        cached = dict(zip(cdf["pmid"].astype(str), cdf["abstract"].astype(str)))
    todo = [p for p in dict.fromkeys(pmids) if p not in cached]
    logger.info("abstracts: %d cached, %d to fetch", len(cached), len(todo))
    if todo:
        session = requests.Session()
        min_interval = 1.0 / cfg.max_req_per_sec
        for pmid in todo:
            t0 = time.monotonic()
            text, source = _fetch_with_retry(pmid, cfg, session)
            cached[pmid] = text or ""
            logger.debug("fetched pmid=%s source=%s len=%d", pmid, source, len(text or ""))
            elapsed = time.monotonic() - t0
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        out = pd.DataFrame({"pmid": list(cached), "abstract": list(cached.values())})
        out.to_parquet(cache_path, index=False)
    return {p: t for p, t in cached.items() if t}
