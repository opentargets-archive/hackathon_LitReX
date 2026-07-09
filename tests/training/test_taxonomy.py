from types import SimpleNamespace

import pandas as pd

from litrex.training import taxonomy

_CLASSES = ["no_relationship", "association", "upregulation", "downregulation", "negative_finding"]


def _vec(text: str) -> list[float]:
    """A one-hot embedding over the 5 classes, by keyword — enough to test argmax."""
    t = text.lower()
    v = [0.0] * 5
    if "not found" in t or "not associated" in t:
        v[4] = 1.0
    elif any(k in t for k in ("does not", "no relationship", "co-mention", "mentions both")):
        v[0] = 1.0
    elif any(k in t for k in ("increase", "promot", "upregulat", "overexpress", "gain of")):
        v[2] = 1.0
    elif any(k in t for k in ("decreas", "loss", "reduced", "protective", "downregulat")):
        v[3] = 1.0
    else:
        v[1] = 1.0  # association / default
    return v


class _FakeEmbeddings:
    def create(self, model, input):
        return SimpleNamespace(data=[SimpleNamespace(embedding=_vec(t)) for t in input])


class FakeOpenAI:
    def __init__(self):
        self.embeddings = _FakeEmbeddings()


def test_classify_by_prototype_separates_directions():
    rels = [
        "increased expression of X promotes the disease",
        "reduced expression / loss of X drives the disease",
        "X is associated with the disease via a GWAS locus",
        "text mentions both but does not state any relationship",
        "association was tested and not found",
    ]
    assigned, sims = taxonomy.classify_by_prototype(rels, FakeOpenAI())
    assert assigned == ["upregulation", "downregulation", "association",
                        "no_relationship", "negative_finding"]
    assert sims.shape == (5, 5)


def test_derive_taxonomy_writes_class_column_and_json(tmp_path):
    df = pd.DataFrame({
        "relation": ["increased X promotes disease", "loss of X drives disease",
                     "does not state any relationship"],
        "confidence": [0.9, 0.8, 0.4],
        "target": ["a", "b", "c"],
    })
    in_p = tmp_path / "in.parquet"
    df.to_parquet(in_p)
    out_p, tax_p = tmp_path / "out.parquet", tmp_path / "tax.json"

    tax = taxonomy.derive_taxonomy(in_p, out_p, tax_p, client=FakeOpenAI())

    outdf = pd.read_parquet(out_p)
    assert list(outdf["relation_class"]) == ["upregulation", "downregulation", "no_relationship"]
    assert "class_margin" in outdf.columns
    assert {c["name"] for c in tax["classes"]} == set(_CLASSES)
    assert sum(tax["class_counts"].values()) == 3
