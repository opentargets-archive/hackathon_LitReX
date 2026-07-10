"""Stage 6c: fine-tune PubMedBERT on the silver labels (docs/06). Runs on GPU.

Input = the splits from `dataset.py`. The model input is the marked pair +
sentence; the loss is class-weighted (imbalance) AND per-sample
confidence-weighted (silver-label reliability). Heavy deps (torch/transformers/
datasets, the `[training]` extra) are imported lazily so this module — and the
torch-free helpers (`compute_metrics_from_preds`, `class_weight_vector`,
`smoke_preset`) — import fine without a GPU environment.

Two entry points via `_main`:
  * default        -> single 80/10/10 fit, saves model + card (`--output-dir`)
  * ``--cv``       -> K-fold CV over the train split's `cv_fold` column, writes
                      `cv_results.json` (mean +/- std macro-F1) — no model saved.

Class weighting is tunable with ``--weight-scheme {inverse,sqrt,uniform}`` (or a
raw ``--weight-alpha``): inverse-frequency can over-suppress the majority class,
so sqrt/uniform trade minority recall for majority recall.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

logger = logging.getLogger(__name__)

BASE_MODEL = "microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext"

# --weight-scheme sugar over the raw exponent alpha (see class_weight_vector).
WEIGHT_SCHEMES = {"inverse": 1.0, "sqrt": 0.5, "uniform": 0.0}


def compute_metrics_from_preds(labels, preds, class_names: list[str]) -> dict:
    """Macro/weighted/per-class F1 + accuracy + confusion matrix (torch-free)."""
    labels = np.asarray(labels)
    preds = np.asarray(preds)
    ids = list(range(len(class_names)))
    per_class = f1_score(labels, preds, average=None, labels=ids, zero_division=0)
    return {
        "accuracy": float(accuracy_score(labels, preds)),
        "macro_f1": float(f1_score(labels, preds, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(labels, preds, average="weighted", zero_division=0)),
        "per_class_f1": {class_names[i]: float(per_class[i]) for i in ids},
        "confusion_matrix": confusion_matrix(labels, preds, labels=ids).tolist(),
    }


def resolve_alpha(weight_scheme: str, weight_alpha: float | None) -> float:
    """A raw ``--weight-alpha`` wins; otherwise map the named scheme to an alpha."""
    if weight_alpha is not None:
        return weight_alpha
    if weight_scheme not in WEIGHT_SCHEMES:
        raise ValueError(f"unknown weight scheme {weight_scheme!r}; use {list(WEIGHT_SCHEMES)}")
    return WEIGHT_SCHEMES[weight_scheme]


def class_weight_vector(counts_by_id: dict, num_classes: int, alpha: float = 1.0) -> dict:
    """Per-class loss weights = ``(1/count)**alpha``, normalised to mean 1 (torch-free).

    ``alpha=1`` is inverse-frequency (max minority up-weighting), ``0.5`` is its
    square root (gentler), ``0`` is uniform (all 1.0). Normalising to mean 1 keeps
    the overall loss magnitude comparable as alpha changes. Absent classes are
    floored to count 1 to avoid division by zero.
    """
    raw = [(1.0 / max(int(counts_by_id.get(i, 0)), 1)) ** alpha for i in range(num_classes)]
    total = sum(raw)
    return {i: raw[i] * num_classes / total for i in range(num_classes)}


def _fit(
    train_df,
    eval_df,
    *,
    meta: dict,
    base_model: str,
    epochs: int,
    batch_size: int,
    lr: float,
    max_length: int,
    seed: int,
    class_weights: dict,
    use_cpu: bool,
    checkpoint_dir: str,
):
    """Train a fresh model on ``train_df``, evaluating on ``eval_df`` each epoch.

    Returns ``(trainer, tokenizer, eval_metrics)`` where eval_metrics are keyed
    ``eval_*`` on ``eval_df``. Heavy deps + the weighted Trainer/collator are kept
    inside so the module imports without torch.
    """
    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    classes = meta["classes"]
    label2id = meta["label2id"]
    id2label = {v: k for k, v in label2id.items()}
    cw = torch.tensor([class_weights[i] for i in range(len(classes))], dtype=torch.float)

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    tokenizer.add_special_tokens({"additional_special_tokens": meta["entity_markers"]})
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model, num_labels=len(classes), id2label=id2label, label2id=label2id
    )
    model.resize_token_embeddings(len(tokenizer))

    def to_ds(df):
        ds = Dataset.from_pandas(
            df[["input_text", "label", "sample_weight"]], preserve_index=False
        )
        return ds.map(
            lambda b: tokenizer(b["input_text"], truncation=True, max_length=max_length),
            batched=True, remove_columns=["input_text"],
        )

    train_ds, eval_ds = to_ds(train_df), to_ds(eval_df)

    class WeightedCollator(DataCollatorWithPadding):
        def __call__(self, features):
            weights = torch.tensor([f.pop("sample_weight") for f in features], dtype=torch.float)
            batch = super().__call__(features)
            batch["sample_weight"] = weights
            return batch

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels = inputs.pop("labels")
            weights = inputs.pop("sample_weight")
            outputs = model(**inputs)
            loss_fct = torch.nn.CrossEntropyLoss(
                weight=cw.to(outputs.logits.device), reduction="none"
            )
            per_sample = loss_fct(outputs.logits, labels)
            loss = (per_sample * weights.to(per_sample.device)).mean()
            return (loss, outputs) if return_outputs else loss

    def metrics(eval_pred):
        logits, labels = eval_pred
        return compute_metrics_from_preds(labels, np.asarray(logits).argmax(-1), classes)

    extra_args = {}
    if use_cpu:
        # Old CPU/smoke torch stacks choke on safetensors' contiguity check after
        # resize_token_embeddings; .bin sidesteps it. transformers>=5 dropped this
        # kwarg (safetensors is mandatory) — so only pass it on the CPU path.
        extra_args["save_safetensors"] = False

    args = TrainingArguments(
        output_dir=checkpoint_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=lr,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        seed=seed,
        logging_steps=20,
        remove_unused_columns=False,  # keep sample_weight
        report_to=[],
        use_cpu=use_cpu,
        **extra_args,
    )
    trainer = WeightedTrainer(
        model=model, args=args, train_dataset=train_ds, eval_dataset=eval_ds,
        compute_metrics=metrics, data_collator=WeightedCollator(tokenizer),
    )
    trainer.train()
    eval_metrics = trainer.evaluate(eval_ds, metric_key_prefix="eval")
    return trainer, tokenizer, eval_metrics


def _load_split(data_dir: Path, split: str, limit: int | None):
    import pandas as pd
    df = pd.read_parquet(data_dir / f"{split}.parquet")
    return df.head(limit) if limit else df


def train(
    data_dir: str | Path,
    output_dir: str | Path,
    base_model: str = BASE_MODEL,
    epochs: int = 4,
    batch_size: int = 16,
    lr: float = 2e-5,
    max_length: int = 256,
    seed: int = 0,
    limit: int | None = None,
    use_cpu: bool = False,
    weight_alpha: float = 1.0,
    weight_scheme: str = "inverse",
) -> dict:
    """Single 80/10/10 fit: train, evaluate the held-out test split, save model + card.

    ``limit`` heads each split to N rows and ``use_cpu`` forces CPU — together
    they give a fast local smoke-train (see ``--smoke``). ``weight_alpha`` tunes
    the class-weight aggressiveness (see ``class_weight_vector``).
    """
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    meta = json.loads((data_dir / "dataset_meta.json").read_text())

    train_df = _load_split(data_dir, "train", limit)
    val_df = _load_split(data_dir, "val", limit)
    test_df = _load_split(data_dir, "test", limit)

    counts = train_df["label"].value_counts().to_dict()
    class_weights = class_weight_vector(counts, len(meta["classes"]), weight_alpha)

    trainer, tokenizer, _ = _fit(
        train_df, val_df, meta=meta, base_model=base_model, epochs=epochs,
        batch_size=batch_size, lr=lr, max_length=max_length, seed=seed,
        class_weights=class_weights, use_cpu=use_cpu,
        checkpoint_dir=str(output_dir / "checkpoints"),
    )

    from datasets import Dataset
    test_ds = Dataset.from_pandas(
        test_df[["input_text", "label", "sample_weight"]], preserve_index=False
    ).map(lambda b: tokenizer(b["input_text"], truncation=True, max_length=max_length),
          batched=True, remove_columns=["input_text"])
    test_metrics = trainer.evaluate(test_ds, metric_key_prefix="test")

    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir / "model"))
    tokenizer.save_pretrained(str(output_dir / "model"))
    (output_dir / "metrics.json").write_text(json.dumps(test_metrics, indent=2, default=str))

    model_card = {
        "base_model": base_model,
        "classes": meta["classes"],
        "label2id": meta["label2id"],
        "taxonomy_version": "stage6a-embedding-prototype-v1",
        "input_format": "[TGT] {target} [/TGT] [DIS] {disease} [/DIS] {text}",
        "loss": "class-weighted + per-sample confidence-weighted cross-entropy",
        "class_weighting": {"scheme": weight_scheme, "alpha": weight_alpha,
                            "weights": class_weights},
        "min_confidence": meta["min_confidence"],
        "sizes": meta["sizes"],
        "hyperparams": {"epochs": epochs, "batch_size": batch_size, "lr": lr,
                        "max_length": max_length, "seed": seed},
        "smoke_run": bool(limit),  # true => tiny subset / CPU sanity check, not a real model
        "row_limit": limit,
        "device": "cpu" if use_cpu else "auto",
        "test_metrics": test_metrics,
    }
    (output_dir / "model_card.json").write_text(json.dumps(model_card, indent=2, default=str))
    logger.info("done: test macro-F1=%.3f -> %s",
                test_metrics.get("test_macro_f1", float("nan")), output_dir)
    return test_metrics


def cross_validate(
    data_dir: str | Path,
    output_dir: str | Path,
    base_model: str = BASE_MODEL,
    epochs: int = 4,
    batch_size: int = 16,
    lr: float = 2e-5,
    max_length: int = 256,
    seed: int = 0,
    limit: int | None = None,
    use_cpu: bool = False,
    weight_alpha: float = 1.0,
    weight_scheme: str = "inverse",
) -> dict:
    """K-fold CV over the train split's ``cv_fold`` column → mean±std macro-F1.

    Trains a fresh model per fold (train = the other folds, eval = the held-out
    fold), so no model is saved — this is a variance estimate, not a deliverable.
    Class weights are recomputed per fold from that fold's train counts. Writes
    ``cv_results.json`` and returns the aggregate dict.
    """
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    meta = json.loads((data_dir / "dataset_meta.json").read_text())
    classes = meta["classes"]

    train_full = _load_split(data_dir, "train", limit)
    if "cv_fold" not in train_full.columns:
        raise ValueError("train split has no cv_fold column — rebuild with dataset.py")
    folds = sorted(f for f in train_full["cv_fold"].unique() if f >= 0)

    fold_results = []
    for k in folds:
        tr = train_full[train_full["cv_fold"] != k]
        ev = train_full[train_full["cv_fold"] == k]
        counts = tr["label"].value_counts().to_dict()
        class_weights = class_weight_vector(counts, len(classes), weight_alpha)
        _, _, m = _fit(
            tr, ev, meta=meta, base_model=base_model, epochs=epochs,
            batch_size=batch_size, lr=lr, max_length=max_length, seed=seed,
            class_weights=class_weights, use_cpu=use_cpu,
            checkpoint_dir=str(output_dir / f"cv_fold_{k}" / "checkpoints"),
        )
        fold_results.append({"fold": int(k), "n_train": len(tr), "n_eval": len(ev),
                             "macro_f1": m["eval_macro_f1"], "accuracy": m["eval_accuracy"],
                             "weighted_f1": m["eval_weighted_f1"],
                             "per_class_f1": m["eval_per_class_f1"]})
        logger.info("fold %d: macro-F1=%.3f (n_eval=%d)", k, m["eval_macro_f1"], len(ev))

    macro = [r["macro_f1"] for r in fold_results]
    per_class_mean = {
        c: statistics.fmean(r["per_class_f1"][c] for r in fold_results) for c in classes
    }
    agg = {
        "n_folds": len(folds),
        "class_weighting": {"scheme": weight_scheme, "alpha": weight_alpha},
        "macro_f1_mean": statistics.fmean(macro),
        "macro_f1_std": statistics.pstdev(macro) if len(macro) > 1 else 0.0,
        "accuracy_mean": statistics.fmean(r["accuracy"] for r in fold_results),
        "weighted_f1_mean": statistics.fmean(r["weighted_f1"] for r in fold_results),
        "per_class_f1_mean": per_class_mean,
        "folds": fold_results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cv_results.json").write_text(json.dumps(agg, indent=2, default=str))
    logger.info("CV done: macro-F1 %.3f +/- %.3f over %d folds -> %s",
                agg["macro_f1_mean"], agg["macro_f1_std"], len(folds), output_dir)
    return agg


def smoke_preset(smoke: bool, epochs: int, limit: int | None, output_dir: str) -> dict:
    """Resolve the ``--smoke`` convenience preset (torch-free, so unit-testable).

    Explicitly-passed flags win; the preset only fills defaults: 100 rows/split,
    1 epoch, CPU, and a distinct output dir so a smoke never clobbers a real run.
    """
    if not smoke:
        return {"epochs": epochs, "limit": limit, "use_cpu": False, "output_dir": output_dir}
    return {
        "epochs": 1 if epochs == 4 else epochs,          # 4 == the CLI default
        "limit": limit or 100,
        "use_cpu": True,
        "output_dir": "models/stage6_smoke" if output_dir == "models/stage6" else output_dir,
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description="Stage 6c: fine-tune PubMedBERT.")
    parser.add_argument("--data-dir", default="data/processed/splits")
    parser.add_argument("--output-dir", default="models/stage6")
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None,
                        help="head each split to N rows (local sanity check)")
    parser.add_argument("--cpu", action="store_true", help="force CPU (no GPU/MPS)")
    parser.add_argument("--smoke", action="store_true",
                        help="fast CPU smoke-train: 100 rows/split, 1 epoch, CPU")
    parser.add_argument("--cv", action="store_true",
                        help="K-fold CV over the train split's cv_fold column (no model saved)")
    parser.add_argument("--weight-scheme", choices=list(WEIGHT_SCHEMES), default="inverse",
                        help="class-weight aggressiveness (default: inverse-frequency)")
    parser.add_argument("--weight-alpha", type=float, default=None,
                        help="raw class-weight exponent; overrides --weight-scheme")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    preset = smoke_preset(args.smoke, args.epochs, args.limit, args.output_dir)
    use_cpu = args.cpu or preset["use_cpu"]
    alpha = resolve_alpha(args.weight_scheme, args.weight_alpha)
    runner = cross_validate if args.cv else train
    out = preset["output_dir"]
    if args.cv and out == "models/stage6":
        out = "models/stage6_cv"

    result = runner(
        args.data_dir, out, args.base_model, preset["epochs"], args.batch_size, args.lr,
        seed=args.seed, limit=preset["limit"], use_cpu=use_cpu,
        weight_alpha=alpha, weight_scheme=args.weight_scheme,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    _main()
