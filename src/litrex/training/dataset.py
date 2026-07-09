"""Stage 6b: build the training dataset from the classified silver labels.

Turns `labeled_triples_classified.parquet` (stage 6a) into train/val/test
parquets ready for `train.py`:

- **Entity markers:** the model input is the sentence prefixed with the marked
  target/disease pair (`[TGT] EGFR [/TGT] [DIS] NSCLC [/DIS] <text>`), so the
  classifier knows which pair to judge. (Stage 5 dropped char offsets from the
  LabeledTriple contract, so we mark the resolved names as a prefix rather than
  inline — robust and span-free.)
- **Confidence filter:** drop rows below `min_confidence` (stage-5 noise floor).
- **Weights:** per-row `sample_weight = confidence` (for a confidence-weighted
  loss) and inverse-frequency `class_weights` (heavy class imbalance).
- **Splits:** grouped + stratified 80/10/10 (`StratifiedGroupKFold`) — grouped by
  `publication_id` so a paper never straddles splits, stratified by
  `relation_class` so each split keeps the class balance. A 5-fold CV assignment
  over the train set is also emitted (`cv_fold` column).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from litrex.labelling.entity_names import disease_names, target_names

logger = logging.getLogger(__name__)

ENTITY_MARKERS = ["[TGT]", "[/TGT]", "[DIS]", "[/DIS]"]
MIN_CONFIDENCE = 0.3


def build_input_text(target_name: str, disease_name: str, text: str) -> str:
    """Marked model input: the target/disease pair as typed markers + the text."""
    return f"[TGT] {target_name} [/TGT] [DIS] {disease_name} [/DIS] {text}"


def _grouped_stratified_folds(df: pd.DataFrame, n_splits: int, seed: int) -> list:
    """Return the per-fold test-index arrays of a grouped+stratified K-fold."""
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    return [test_idx for _, test_idx in sgkf.split(df, y=df["label"], groups=df["publication_id"])]


def prepare(
    input_path: str | Path,
    output_dir: str | Path,
    min_confidence: float = MIN_CONFIDENCE,
    seed: int = 0,
    n_splits: int = 10,          # 10 folds -> 80/10/10 (train / val / test)
    cv_folds: int = 5,
) -> dict:
    """Build marked, filtered, split train/val/test parquets + `dataset_meta.json`."""
    df = pd.read_parquet(input_path)
    n0 = len(df)
    df = df[df["confidence"].astype(float) >= min_confidence].reset_index(drop=True)
    logger.info("filtered %d -> %d rows (confidence >= %.2f)", n0, len(df), min_confidence)

    tnames = target_names(sorted(df["target"].astype(str).unique()))
    dnames = disease_names(sorted(df["disease"].astype(str).unique()))
    df["input_text"] = [
        build_input_text(tnames.get(t, t), dnames.get(d, d), x)
        for t, d, x in zip(df["target"], df["disease"], df["text"])
    ]

    classes = sorted(df["relation_class"].unique())
    label2id = {c: i for i, c in enumerate(classes)}
    df["label"] = df["relation_class"].map(label2id)
    df["sample_weight"] = df["confidence"].astype(float)

    counts = df["relation_class"].value_counts()
    class_weights = {label2id[c]: round(len(df) / (len(classes) * counts[c]), 4) for c in classes}

    # 80/10/10: fold 0 -> test, fold 1 -> val, remainder -> train.
    folds = _grouped_stratified_folds(df, n_splits, seed)
    test_idx = set(folds[0])
    val_idx = set(folds[1])
    train_idx = [i for i in range(len(df)) if i not in test_idx and i not in val_idx]
    splits = {
        "train": df.iloc[sorted(train_idx)].reset_index(drop=True),
        "val": df.iloc[sorted(val_idx)].reset_index(drop=True),
        "test": df.iloc[sorted(test_idx)].reset_index(drop=True),
    }

    # sanity: no publication_id straddles splits
    pmids = {k: set(v["publication_id"]) for k, v in splits.items()}
    assert not (pmids["train"] & pmids["test"]), "PMID leak train/test"
    assert not (pmids["val"] & pmids["test"]), "PMID leak val/test"

    # 5-fold CV assignment over the train set (for robust metric estimates).
    train_df = splits["train"]
    cv_assign = [-1] * len(train_df)
    for fold, tidx in enumerate(_grouped_stratified_folds(train_df, cv_folds, seed)):
        for i in tidx:
            cv_assign[i] = fold
    splits["train"] = train_df.assign(cv_fold=cv_assign)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, sub in splits.items():
        sub.to_parquet(out / f"{name}.parquet", index=False)

    meta = {
        "label2id": label2id,
        "classes": classes,
        "class_weights": class_weights,
        "entity_markers": ENTITY_MARKERS,
        "min_confidence": min_confidence,
        "cv_folds": cv_folds,
        "sizes": {k: len(v) for k, v in splits.items()},
        "split_class_counts": {
            k: v["relation_class"].value_counts().to_dict() for k, v in splits.items()
        },
        "split_data_source": {
            k: v["data_source"].value_counts().to_dict() for k, v in splits.items()
        },
    }
    (out / "dataset_meta.json").write_text(json.dumps(meta, indent=2))
    logger.info("wrote splits %s to %s", meta["sizes"], out)
    return meta


def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Stage 6b: build training splits.")
    parser.add_argument("--input", default="data/processed/labeled_triples_classified.parquet")
    parser.add_argument("--output-dir", default="data/processed/splits")
    parser.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    meta = prepare(args.input, args.output_dir, args.min_confidence, args.seed)
    print(json.dumps({"sizes": meta["sizes"], "class_weights": meta["class_weights"],
                      "split_class_counts": meta["split_class_counts"]}, indent=2))


if __name__ == "__main__":
    _main()
