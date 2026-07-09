"""Fetch and cache Europe PMC open-access full text by PMID (JATS -> plain text)."""
from __future__ import annotations
from pathlib import Path
import logging
import time
import pandas as pd
import requests
# defusedxml guards against XXE / billion-laughs in the external JATS XML.
from defusedxml import ElementTree as ET

logger = logging.getLogger(__name__)


def resolve_pmcid(pmid: str, cfg, session: requests.Session) -> str | None:
    """Return the Europe PMC open-access PMCID for a PMID, or None if not in EPMC."""
    url = f"{cfg.europepmc_base}/search"
    params = {"query": f"EXT_ID:{pmid} AND SRC:MED", "resultType": "core",
              "format": "json", "pageSize": 1}
    resp = session.get(url, params=params, timeout=60)
    if resp.status_code != 200:
        logger.error("epmc search error pmid=%s status=%s", pmid, resp.status_code)
        return None
    results = resp.json().get("resultList", {}).get("result", [])
    if not results:
        return None
    d = results[0]
    if d.get("inEPMC") == "Y" and d.get("pmcid"):
        return d["pmcid"]
    return None


def jats_to_text(xml_str: str) -> str:
    """Extract narrative text (section titles + paragraphs) from a JATS <body>."""
    try:
        root = ET.fromstring(xml_str)
    except Exception as exc:
        logger.error("jats parse failed err=%s", exc)
        return ""
    body = root.find(".//body")
    if body is None:
        return ""
    parts: list[str] = []
    for el in body.iter():
        tag = el.tag.rsplit("}", 1)[-1]  # drop namespace if present
        if tag in ("p", "title"):
            txt = " ".join("".join(el.itertext()).split())
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def fetch_fulltext_europepmc(pmid: str, cfg, session: requests.Session) -> str | None:
    """Fetch OA full text for a PMID via Europe PMC, as plain text. None if unavailable."""
    pmcid = resolve_pmcid(pmid, cfg, session)
    if not pmcid:
        return None
    url = f"{cfg.europepmc_base}/{pmcid}/fullTextXML"
    resp = session.get(url, timeout=120)
    if resp.status_code != 200:
        logger.info("no fulltext pmid=%s pmcid=%s status=%s", pmid, pmcid, resp.status_code)
        return None
    return jats_to_text(resp.text) or None


def _fetch_with_retry(pmid: str, cfg, session: requests.Session, max_tries: int = 4) -> str | None:
    delay = 1.0
    for attempt in range(1, max_tries + 1):
        try:
            return fetch_fulltext_europepmc(pmid, cfg, session)
        except requests.RequestException as exc:
            logger.warning("fulltext retry pmid=%s attempt=%d err=%s", pmid, attempt, exc)
            if attempt == max_tries:
                return None
            time.sleep(delay)
            delay *= 2
    return None


def load_or_fetch_fulltext(pmids: list[str], cfg, cache_path: Path) -> dict[str, str]:
    """Return {pmid: full_text} for OA papers, using a parquet cache.

    Non-OA / unavailable papers are cached as empty strings so they are not
    re-fetched. Rate-limited to cfg.max_req_per_sec.
    """
    cache_path = Path(cache_path)
    cached: dict[str, str] = {}
    if cache_path.exists():
        cdf = pd.read_parquet(cache_path)
        cached = dict(zip(cdf["pmid"].astype(str), cdf["fulltext"].astype(str)))
    todo = [p for p in dict.fromkeys(pmids) if p not in cached]
    logger.info("fulltext: %d cached, %d to fetch", len(cached), len(todo))
    if todo:
        session = requests.Session()
        min_interval = 1.0 / cfg.max_req_per_sec
        for pmid in todo:
            t0 = time.monotonic()
            cached[pmid] = _fetch_with_retry(pmid, cfg, session) or ""
            elapsed = time.monotonic() - t0
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"pmid": list(cached), "fulltext": list(cached.values())}).to_parquet(
            cache_path, index=False)
    return {p: t for p, t in cached.items() if t}
