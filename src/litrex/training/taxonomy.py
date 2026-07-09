"""Stage 6a: close the stage-5 free-text relations into a fixed taxonomy.

Stage 5 emits free-text `relation` descriptions (open vocabulary). Before
training a classifier we must "close" them into a small label set (docs/06
step 2). We embed each description and assign it to its nearest **class
prototype** — a fixed, docs/01-aligned taxonomy that keeps direction of effect
(up- vs down-regulation) separate.

Why prototypes over LLM cluster-naming: KMeans clusters don't align with the
up/down/association axes, so a whole-cluster→class mapping repeatedly collapsed
opposite directions into one bucket. Per-row nearest-prototype assignment gives
clean, deterministic separation with no per-row LLM cost. The upstream judge
stays open-vocab; this only fixes the label set for one model version.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import openai
import pandas as pd

logger = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"

# Fixed, docs/01-aligned taxonomy. Each class has a rich prototype (definition +
# characteristic phrasings) the row embeddings are matched against.
CLASS_PROTOTYPES: dict[str, str] = {
    "no_relationship":
        "The text mentions both the gene/protein and the disease but does not "
        "state or assert any relationship between them — a co-mention, gene list, "
        "background statement, or unrelated comparison; the entity may not even "
        "appear in the excerpt.",
    "association":
        "An association, genetic link, or correlation between the gene/protein or "
        "variant and the disease is asserted, but with no clear direction of "
        "effect — a GWAS locus associated with the trait, 'linked to', "
        "'implicated in', 'associated with', 'a risk factor for'.",
    "upregulation":
        "Increased expression, activity, or level of the gene/protein is "
        "associated with the disease, or the gene promotes, drives, activates, "
        "exacerbates, or increases risk of the disease — overexpression, "
        "upregulation, gain of function, elevated levels.",
    "downregulation":
        "Decreased or reduced expression, loss of function, deficiency, or "
        "downregulation of the gene/protein is associated with the disease, or "
        "loss of the gene drives or worsens disease, or the gene is protective — "
        "reduced levels, haploinsufficiency, knockout worsens disease.",
    "negative_finding":
        "An association or effect of the gene/protein on the disease was tested "
        "for and explicitly not found — no significant association, failed to "
        "replicate, not associated.",
}


def embed_texts(texts: list[str], client: openai.OpenAI,
                model: str = EMBED_MODEL, batch: int = 256) -> np.ndarray:
    """Embed texts with the OpenAI embeddings API (batched), L2-normalised."""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        resp = client.embeddings.create(model=model, input=texts[i:i + batch])
        vectors.extend(d.embedding for d in resp.data)
    arr = np.asarray(vectors, dtype=np.float32)
    return arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-8)


def classify_by_prototype(
    relations: list[str],
    client: openai.OpenAI,
    prototypes: dict[str, str] = CLASS_PROTOTYPES,
) -> tuple[list[str], np.ndarray]:
    """Assign each relation to its nearest class prototype (cosine similarity).

    Returns (class_per_row, similarity_matrix[n_rows, n_classes]).
    """
    class_names = list(prototypes)
    proto_emb = embed_texts(list(prototypes.values()), client)  # normalised
    row_emb = embed_texts(relations, client)                    # normalised
    sims = row_emb @ proto_emb.T                                # cosine, both unit-norm
    assigned = [class_names[i] for i in sims.argmax(axis=1)]
    return assigned, sims


def derive_taxonomy(
    input_path: str | Path,
    output_path: str | Path,
    taxonomy_path: str | Path,
    client: openai.OpenAI | None = None,
    prototypes: dict[str, str] = CLASS_PROTOTYPES,
) -> dict:
    """Tag every stage-5 row with a fixed-taxonomy ``relation_class``.

    Writes the labelled parquet with ``relation_class`` (+ ``class_confidence``,
    the cosine margin between top-1 and top-2 classes) and a ``taxonomy.json``
    (class definitions + counts). Returns the taxonomy dict.
    """
    client = client or openai.OpenAI()
    df = pd.read_parquet(input_path)
    relations = df["relation"].astype(str).tolist()

    assigned, sims = classify_by_prototype(relations, client, prototypes)
    top2 = np.sort(sims, axis=1)[:, -2:]
    df["relation_class"] = assigned
    df["class_margin"] = (top2[:, 1] - top2[:, 0]).round(4)  # decisiveness of the assignment

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)

    taxonomy = {
        "classes": [{"name": n, "definition": d} for n, d in prototypes.items()],
        "class_counts": df["relation_class"].value_counts().to_dict(),
        "method": "embedding-nearest-prototype",
        "embed_model": EMBED_MODEL,
    }
    Path(taxonomy_path).parent.mkdir(parents=True, exist_ok=True)
    Path(taxonomy_path).write_text(json.dumps(taxonomy, indent=2))
    logger.info("wrote %d rows with relation_class to %s; taxonomy -> %s",
                len(df), output_path, taxonomy_path)
    return taxonomy


def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Stage 6a: close relation taxonomy.")
    parser.add_argument("--input", default="data/processed/labeled_triples.parquet")
    parser.add_argument("--output", default="data/processed/labeled_triples_classified.parquet")
    parser.add_argument("--taxonomy", default="data/processed/taxonomy.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tax = derive_taxonomy(args.input, args.output, args.taxonomy)
    print(json.dumps({"classes": [c["name"] for c in tax["classes"]],
                      "class_counts": tax["class_counts"]}, indent=2))


if __name__ == "__main__":
    _main()
