"""Stage 7: batch-score the trained relation classifier over a Cooccurrence
corpus (docs/07).

The scorer builds each model input exactly as training did — resolved
target/disease names wrapped in entity markers + the sentence — so inference
matches the fit. It loads the model + tokenizer **once** (per process / per Spark
executor) and scores in batches on the GPU.

Two entry points:
  * ``python -m litrex.inference.batch_score`` — standalone: read a Cooccurrence
    parquet (file or dir), resolve names, score, write a ScoredRelationship
    parquet. This is what runs on codon.
  * ``score_partition(text, target, disease)`` — a ``pandas_udf``-shaped function
    (load-once-per-executor) for wiring into the upstream PySpark job (docs/07).

Heavy deps (torch/transformers) are imported lazily so the module — and the
torch-free helpers — import without a GPU environment.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from litrex.labelling.entity_names import disease_names, target_names
from litrex.training.dataset import build_input_text

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = "models/stage6/model"
# Provenance columns carried straight through from the Cooccurrence contract.
_PASSTHROUGH = ["target", "disease", "text", "publication_id", "publication_date", "data_source"]


def model_version(model_dir: str | Path) -> str:
    """A stable version string from the sibling model_card.json (falls back to dir name)."""
    card_path = Path(model_dir).parent / "model_card.json"
    if card_path.exists():
        card = json.loads(card_path.read_text())
        scheme = card.get("class_weighting", {}).get("scheme", "?")
        return f"{card.get('taxonomy_version', 'stage6')}+weight-{scheme}"
    return Path(model_dir).name


def build_inputs(df: pd.DataFrame, resolve: bool = True) -> list[str]:
    """Build the marked model-input strings for a Cooccurrence frame (torch-free).

    ``resolve=True`` maps Ensembl/EFO IDs to display names (cached, same as
    training). Pass ``resolve=False`` when ``target``/``disease`` are already
    display names (e.g. pre-resolved upstream in Spark).
    """
    targets, diseases = df["target"].astype(str), df["disease"].astype(str)
    if resolve:
        tnames = target_names(sorted(targets.unique()))
        dnames = disease_names(sorted(diseases.unique()))
        tvals = [tnames.get(t, t) for t in targets]
        dvals = [dnames.get(d, d) for d in diseases]
    else:
        tvals, dvals = list(targets), list(diseases)
    return [build_input_text(t, d, x) for t, d, x in zip(tvals, dvals, df["text"].astype(str))]


class RelationScorer:
    """Loads the fine-tuned classifier once; scores lists of input strings in batches."""

    def __init__(
        self,
        model_dir: str | Path = DEFAULT_MODEL_DIR,
        batch_size: int = 64,
        max_length: int = 256,
        device: str | None = None,
    ):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.model_dir = str(model_dir)
        self.batch_size = batch_size
        self.max_length = max_length
        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_dir)
        self.model.to(self.device).eval()
        # id2label from the model config (set at training time).
        self.id2label = {int(i): lbl for i, lbl in self.model.config.id2label.items()}
        self.classes = [self.id2label[i] for i in range(len(self.id2label))]
        self.version = model_version(self.model_dir)

    def predict(self, input_texts: list[str]) -> tuple[list[str], np.ndarray]:
        """Return (predicted class per row, softmax probability matrix [n, n_classes])."""
        torch = self._torch
        all_probs: list[np.ndarray] = []
        for i in range(0, len(input_texts), self.batch_size):
            chunk = input_texts[i : i + self.batch_size]
            enc = self.tokenizer(chunk, truncation=True, max_length=self.max_length,
                                 padding=True, return_tensors="pt").to(self.device)
            with torch.no_grad():
                logits = self.model(**enc).logits
            all_probs.append(torch.softmax(logits, dim=-1).cpu().numpy())
        probs = np.concatenate(all_probs) if all_probs else np.empty((0, len(self.classes)))
        labels = [self.classes[j] for j in probs.argmax(axis=1)] if len(probs) else []
        return labels, probs

    def score_frame(self, df: pd.DataFrame, resolve: bool = True) -> pd.DataFrame:
        """Score a Cooccurrence frame → ScoredRelationship frame (docs/07 contract)."""
        inputs = build_inputs(df, resolve=resolve)
        labels, probs = self.predict(inputs)
        out = df[[c for c in _PASSTHROUGH if c in df.columns]].reset_index(drop=True).copy()
        out["relation"] = labels
        out["confidence"] = probs.max(axis=1).round(4) if len(probs) else []
        for j, cls in enumerate(self.classes):
            out[f"prob_{cls}"] = probs[:, j].round(4) if len(probs) else []
        out["model_version"] = self.version
        return out


def score_corpus(
    input_path: str | Path,
    output_path: str | Path,
    model_dir: str | Path = DEFAULT_MODEL_DIR,
    batch_size: int = 64,
    max_length: int = 256,
    limit: int | None = None,
) -> dict:
    """Read a Cooccurrence parquet (file or dir), score it, write ScoredRelationship."""
    import pyarrow.parquet as pq

    input_path, output_path = Path(input_path), Path(output_path)
    parts = sorted(input_path.glob("*.parquet")) if input_path.is_dir() else [input_path]
    df = pd.concat([pq.read_table(p).to_pandas() for p in parts], ignore_index=True)
    if limit:
        df = df.head(limit)
    logger.info("scoring %d rows from %s (%d part(s))", len(df), input_path, len(parts))

    scorer = RelationScorer(model_dir, batch_size=batch_size, max_length=max_length)
    scored = scorer.score_frame(df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(output_path, index=False)
    dist = scored["relation"].value_counts().to_dict()
    logger.info("wrote %d scored rows to %s | label dist: %s", len(scored), output_path, dist)
    return {"n_rows": len(scored), "model_version": scorer.version, "label_distribution": dist,
            "output": str(output_path)}


# --- Spark pandas_udf path (docs/07): load the model once per executor process. ---
_SCORER: RelationScorer | None = None


def _executor_scorer() -> RelationScorer:
    """Process-global scorer so a Spark worker loads the model once, not per batch."""
    global _SCORER
    if _SCORER is None:
        _SCORER = RelationScorer(os.environ.get("LITREX_MODEL_DIR", DEFAULT_MODEL_DIR))
    return _SCORER


def score_partition(text: pd.Series, target: pd.Series, disease: pd.Series) -> pd.DataFrame:
    """Batch-score one partition; signature matches a Spark ``pandas_udf``.

    Assumes ``target``/``disease`` are already display names (resolve upstream in
    Spark — per-partition network lookups don't scale). Returns a DataFrame with
    columns: relation, confidence, model_version.
    """
    scorer = _executor_scorer()
    df = pd.DataFrame({"target": target, "disease": disease, "text": text})
    scored = scorer.score_frame(df, resolve=False)
    return scored[["relation", "confidence", "model_version"]]


def _main() -> None:
    parser = argparse.ArgumentParser(description="Stage 7: batch-score a Cooccurrence corpus.")
    parser.add_argument("--input", required=True, help="Cooccurrence parquet file or directory")
    parser.add_argument("--output", default="data/processed/scored_relationships.parquet")
    parser.add_argument("--model", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, default=None, help="score only the first N rows")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    summary = score_corpus(args.input, args.output, args.model,
                           batch_size=args.batch_size, limit=args.limit)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    _main()
