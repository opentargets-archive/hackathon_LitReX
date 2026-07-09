"""Match GWAS (target, disease) pairs against paper text to emit co-occurrences."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
import logging
import re
import pysbd

from .load import Association
from .disease_index import DiseaseIndex

logger = logging.getLogger(__name__)
_SEG = pysbd.Segmenter(language="en", clean=False)


def split_sentences(text: str) -> list[str]:
    """Segment text into sentences (PySBD)."""
    if not text:
        return []
    return [s.strip() for s in _SEG.segment(text) if s.strip()]


def _word_span(text: str, token: str, ignore_case: bool) -> tuple[int, int] | None:
    flags = re.IGNORECASE if ignore_case else 0
    pat = r"(?<![A-Za-z0-9-])" + re.escape(token) + r"(?![A-Za-z0-9-])"
    m = re.search(pat, text, flags)
    return (m.start(), m.end()) if m else None


def find_target(text: str, assoc: Association, min_symbol_len: int):
    """Cascade-match a target alias in text: Ensembl -> symbol -> rsid.

    Returns (match_type, matched_alias, (start, end)) or None.
    """
    if assoc.target_ensembl:
        sp = _word_span(text, assoc.target_ensembl, ignore_case=True)
        if sp:
            return "ensembl", assoc.target_ensembl, sp
    for sym in assoc.target_symbols:
        if len(sym) < min_symbol_len:
            continue
        sp = _word_span(text, sym, ignore_case=False)
        if sp:
            return "symbol", sym, sp
    if assoc.target_rsid:
        sp = _word_span(text, assoc.target_rsid, ignore_case=True)
        if sp:
            return "rsid", assoc.target_rsid, sp
    return None


def find_disease(text: str, synonyms: list[str], min_len: int):
    """Phrase-match the longest qualifying disease synonym in text.

    Returns (matched_alias, (start, end)) or None.
    """
    for syn in sorted((s for s in synonyms if len(s) >= min_len), key=len, reverse=True):
        sp = _word_span(text, syn, ignore_case=True)
        if sp:
            return syn, sp
    return None


_DOC_SEP = " [...] "


@dataclass
class Cooccurrence:
    target: str | None
    target_ensembl: str | None
    target_symbol: list[str]
    target_rsid: str
    match_type: str
    matched_alias: str
    disease: str
    disease_label: str
    text: str                       # co-occurring sentence, or target-sent [...] disease-sent
    text_source: str                # "abstract" | "fulltext"
    cooccurrence_level: str         # "sentence" (stronger) | "document" (weaker)
    target_span: tuple[int, int]    # char offsets within `text`
    disease_span: tuple[int, int]
    section: str                    # document section (= text_source in v1)
    publication_id: str
    publication_date: date
    source: str
    snp: str
    p_value: str


@dataclass
class DropStats:
    no_disease_syn: int = 0
    no_disease_in_text: int = 0
    no_target_in_text: int = 0
    no_cooccurrence: int = 0


def _pair_key(a: Association) -> tuple:
    return (a.disease_id, a.target_ensembl, tuple(a.target_symbols), a.target_rsid)


def _first(sentences, fn):
    """Return (sentence, match) for the first sentence where fn(sentence) hits."""
    for sent in sentences:
        m = fn(sent)
        if m:
            return sent, m
    return None, None


def build_cooccurrences(assocs: list[Association], document: str, idx: DiseaseIndex,
                        cfg, text_source: str) -> tuple[list[Cooccurrence], DropStats]:
    """Emit co-occurrence rows for a paper's unique (target, disease) pairs.

    Sentence-level match preferred; document-level fallback (target sentence +
    disease sentence, joined) otherwise; else dropped and counted. ``text_source``
    labels the corpus ("abstract" | "fulltext").
    """
    drops = DropStats()
    out: list[Cooccurrence] = []
    seen: set[tuple] = set()
    sentences = split_sentences(document)
    for a in assocs:
        key = _pair_key(a)
        if key in seen:
            continue
        seen.add(key)
        syns = idx.synonyms(a.disease_id)
        if not syns:
            drops.no_disease_syn += 1
            continue

        # sentence-level: target and disease in the same sentence
        text = mtype = malias = tspan = dspan = level = None
        for sent in sentences:
            mt = find_target(sent, a, cfg.min_symbol_len)
            md = find_disease(sent, syns, cfg.min_disease_syn_len)
            if mt and md:
                text = sent
                mtype, malias, tspan = mt
                dspan = md[1]
                level = "sentence"
                break

        if level is None:
            # document-level: target in one sentence, disease in another
            tsent, mt = _first(sentences, lambda s: find_target(s, a, cfg.min_symbol_len))
            dsent, md = _first(sentences, lambda s: find_disease(s, syns, cfg.min_disease_syn_len))
            if mt is None and md is None:
                drops.no_cooccurrence += 1
                continue
            if mt is None:
                drops.no_target_in_text += 1
                continue
            if md is None:
                drops.no_disease_in_text += 1
                continue
            text = tsent + _DOC_SEP + dsent
            mtype, malias, tspan = mt
            off = len(tsent) + len(_DOC_SEP)
            dspan = (md[1][0] + off, md[1][1] + off)
            level = "document"

        out.append(Cooccurrence(
            target=a.target_ensembl, target_ensembl=a.target_ensembl,
            target_symbol=a.target_symbols, target_rsid=a.target_rsid,
            match_type=mtype, matched_alias=malias,
            disease=a.disease_id, disease_label=a.disease_label,
            text=text, text_source=text_source, cooccurrence_level=level,
            target_span=tspan, disease_span=dspan, section=text_source,
            publication_id=a.pmid, publication_date=a.date, source="gwas_catalog",
            snp=a.snp, p_value=a.p_value,
        ))
    return out, drops
