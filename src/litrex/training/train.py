"""Stage 6c: fine-tune PubMedBERT on the silver labels (docs/06). Runs on GPU.

Input = the splits from `dataset.py`. The model input is the marked pair +
sentence; the loss is class-weighted (imbalance) AND per-sample
confidence-weighted (silver-label reliability). Heavy deps (torch/transformers/
datasets, the `[training]` extra) are imported lazily so this module — and the
`compute_metrics_from_preds` helper — import fine without a GPU environment.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

logger = logging.getLogger(__name__)

BASE_MODEL = "microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext"


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
) -> dict:
    """Fine-tune, evaluate on the held-out test split, and save model + card.

    ``limit`` heads each split to N rows and ``use_cpu`` forces CPU — together
    they give a fast local smoke-train (see ``--smoke``) that exercises the whole
    loop before committing a GPU slot.
    """
    import pandas as pd
    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    data_dir, output_dir = Path(data_dir), Path(output_dir)
    meta = json.loads((data_dir / "dataset_meta.json").read_text())
    classes = meta["classes"]
    label2id = meta["label2id"]
    id2label = {v: k for k, v in label2id.items()}
    class_weights = torch.tensor(
        [meta["class_weights"][str(i)] for i in range(len(classes))], dtype=torch.float
    )

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    tokenizer.add_special_tokens({"additional_special_tokens": meta["entity_markers"]})
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model, num_labels=len(classes), id2label=id2label, label2id=label2id
    )
    model.resize_token_embeddings(len(tokenizer))

    def load(split: str):
        cols = ["input_text", "label", "sample_weight"]
        df = pd.read_parquet(data_dir / f"{split}.parquet")[cols]
        if limit:
            df = df.head(limit)  # smoke-train: tiny subset, whole loop still exercised
        ds = Dataset.from_pandas(df, preserve_index=False)
        return ds.map(lambda b: tokenizer(b["input_text"], truncation=True, max_length=max_length),
                      batched=True, remove_columns=["input_text"])

    train_ds, val_ds, test_ds = load("train"), load("val"), load("test")

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
                weight=class_weights.to(outputs.logits.device), reduction="none"
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
        # kwarg (safetensors is mandatory) — so only pass it on the CPU path, where
        # the pinned older transformers still accepts it.
        extra_args["save_safetensors"] = False

    args = TrainingArguments(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=lr,
        eval_strategy="epoch",
        save_strategy="epoch",
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
        model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds,
        compute_metrics=metrics, data_collator=WeightedCollator(tokenizer),
    )
    trainer.train()
    test_metrics = trainer.evaluate(test_ds, metric_key_prefix="test")

    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir / "model"))
    tokenizer.save_pretrained(str(output_dir / "model"))
    (output_dir / "metrics.json").write_text(json.dumps(test_metrics, indent=2, default=str))

    model_card = {
        "base_model": base_model,
        "classes": classes,
        "label2id": label2id,
        "taxonomy_version": "stage6a-embedding-prototype-v1",
        "input_format": "[TGT] {target} [/TGT] [DIS] {disease} [/DIS] {text}",
        "loss": "class-weighted + per-sample confidence-weighted cross-entropy",
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    preset = smoke_preset(args.smoke, args.epochs, args.limit, args.output_dir)
    use_cpu = args.cpu or preset["use_cpu"]

    metrics = train(args.data_dir, preset["output_dir"], args.base_model,
                    preset["epochs"], args.batch_size, args.lr, seed=args.seed,
                    limit=preset["limit"], use_cpu=use_cpu)
    print(json.dumps(metrics, indent=2, default=str))


if __name__ == "__main__":
    _main()
