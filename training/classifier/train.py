"""Train DistilBERT multi-task classifier (severity + category).

Local smoke test (from repo root, venv active):
    python -m training.classifier.train --epochs 2 --batch_size 4 --max_length 128 --freeze_layers 4

Full run on Kaggle (paths auto-detected):
    !python -m training.classifier.train --use_wandb
"""
from __future__ import annotations
import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.utils.class_weight import compute_class_weight
from transformers import AutoTokenizer

from .data import load_labeled, make_splits, tokenize
from .model import CATEGORIES, SEVERITIES, Config, build_model


def parse_args() -> Config:
    defaults = Config()
    p = argparse.ArgumentParser()
    for name, val in asdict(defaults).items():
        if isinstance(val, bool):
            p.add_argument(f"--{name}", action="store_true", default=val)
        else:
            p.add_argument(f"--{name}", type=type(val), default=val)
    return Config(**vars(p.parse_args()))


def main():
    cfg = parse_args()
    print(f"Config: {asdict(cfg)}")
    tf.keras.utils.set_random_seed(cfg.seed)

    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Load + encode labels ----
    df = load_labeled(cfg.db_path)
    print(f"Loaded {len(df)} labeled rows")
    print(f"  Severity dist: {df.severity.value_counts().to_dict()}")
    print(f"  Category dist: {df.category.value_counts().to_dict()}")

    sev_to_id = {s: i for i, s in enumerate(SEVERITIES)}
    cat_to_id = {c: i for i, c in enumerate(CATEGORIES)}
    y_sev = df.severity.map(sev_to_id).to_numpy()
    y_cat = df.category.map(cat_to_id).to_numpy()
    texts = (df.title.fillna("") + "\n\n" + df.body.fillna("")).tolist()

    # ---- Stratified split ----
    train_idx, val_idx, test_idx = make_splits(y_sev, seed=cfg.seed)
    print(f"Split sizes: train={len(train_idx)} val={len(val_idx)} test={len(test_idx)}")

    # ---- Tokenize once ----
    tokenizer = AutoTokenizer.from_pretrained(cfg.model_name)
    input_ids, attention_mask = tokenize(texts, tokenizer, cfg.max_length)

    # ---- Per-head class weights (from train split only) ----
    sev_w = compute_class_weight(
        "balanced", classes=np.arange(len(SEVERITIES)), y=y_sev[train_idx]
    )
    cat_w = compute_class_weight(
        "balanced", classes=np.arange(len(CATEGORIES)), y=y_cat[train_idx]
    )
    print(f"Severity weights: {dict(zip(SEVERITIES, sev_w.round(2)))}")
    print(f"Category weights: {dict(zip(CATEGORIES, cat_w.round(2)))}")

    # Keras doesn't support per-output class_weight with dict outputs, so we push
    # class weights through as per-example sample_weights on train only.
    sw_sev_train = sev_w[y_sev[train_idx]].astype(np.float32)
    sw_cat_train = cat_w[y_cat[train_idx]].astype(np.float32)

    def build_ds(idx, sw_sev=None, sw_cat=None, shuffle=False):
        x = {"input_ids": input_ids[idx], "attention_mask": attention_mask[idx]}
        y = {"severity": y_sev[idx], "category": y_cat[idx]}
        if sw_sev is not None:
            tensors = (x, y, {"severity": sw_sev, "category": sw_cat})
        else:
            tensors = (x, y)
        ds = tf.data.Dataset.from_tensor_slices(tensors)
        if shuffle:
            ds = ds.shuffle(1024, seed=cfg.seed)
        return ds.batch(cfg.batch_size).prefetch(tf.data.AUTOTUNE)

    train_ds = build_ds(train_idx, sw_sev=sw_sev_train, sw_cat=sw_cat_train, shuffle=True)
    val_ds = build_ds(val_idx)
    test_ds = build_ds(test_idx)

    # ---- Model ----
    model = build_model(cfg)
    try:
        optimizer = tf.keras.optimizers.AdamW(
            learning_rate=cfg.learning_rate, weight_decay=cfg.weight_decay
        )
    except AttributeError:
        print("AdamW not available — falling back to Adam (no weight decay).")
        optimizer = tf.keras.optimizers.Adam(learning_rate=cfg.learning_rate)

    model.compile(
        optimizer=optimizer,
        loss={
            "severity": tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
            "category": tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        },
        metrics={"severity": "accuracy", "category": "accuracy"},
    )
    model.summary()

    # ---- Callbacks ----
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=cfg.early_stop_patience,
            restore_best_weights=True,
        ),
    ]
    if cfg.use_wandb:
        import wandb
        from wandb.integration.keras import WandbMetricsLogger

        wandb.init(
            project="sentinelops",
            job_type="classifier",
            config=asdict(cfg),
        )
        callbacks.append(WandbMetricsLogger())

    # ---- Train ----
    model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=cfg.epochs,
        callbacks=callbacks,
        verbose=2,
    )

    # ---- Test-set loss/acc (full per-class F1 comes from eval.py on Day 7) ----
    test_results = model.evaluate(test_ds, verbose=0, return_dict=True)
    print(f"Test results: {test_results}")

    # ---- Persist artifacts (eval.py will load these) ----
    model.save_weights(str(out_dir / "model.weights.h5"))
    tokenizer.save_pretrained(str(out_dir / "tokenizer"))
    (out_dir / "label_mappings.json").write_text(
        json.dumps({"severities": SEVERITIES, "categories": CATEGORIES}, indent=2)
    )
    (out_dir / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
    np.savez(
        out_dir / "splits.npz",
        train=train_idx, val=val_idx, test=test_idx,
    )
    (out_dir / "test_results.json").write_text(json.dumps(test_results, indent=2))
    print(f"Saved artifacts to {out_dir}")


if __name__ == "__main__":
    main()