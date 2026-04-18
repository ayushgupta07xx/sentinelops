"""Multi-task DistilBERT for SentinelOps: severity + category heads."""
from dataclasses import dataclass
import os

import tensorflow as tf
from transformers import TFAutoModel

# Keep these lists in the canonical order used throughout train/eval.
# Index = class id. Don't reorder — saved models and label_mappings.json depend on it.
SEVERITIES = ["P0", "P1", "P2", "P3"]
CATEGORIES = ["deploy", "networking", "database", "capacity", "auth", "other"]

IS_KAGGLE = os.path.exists("/kaggle/working")


@dataclass
class Config:
    # Model
    model_name: str = "distilbert-base-uncased"
    max_length: int = 256
    dropout: float = 0.1
    # 270 rows is tiny -> freeze bottom layers to curb overfitting.
    # DistilBERT has 6 transformer layers. freeze_layers=2 trains layers 2..5 + heads.
    freeze_layers: int = 2

    # Training
    batch_size: int = 8
    epochs: int = 8
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    early_stop_patience: int = 3
    seed: int = 42

    # Paths (auto-switch for Kaggle)
    db_path: str = (
        "/kaggle/input/sentinelops-corpus/corpus.db"
        if IS_KAGGLE
        else "data/warehouse/corpus.db"
    )
    output_dir: str = (
        "/kaggle/working/classifier"
        if IS_KAGGLE
        else "training/classifier/outputs"
    )

    # Tracking
    use_wandb: bool = False


def build_model(cfg: Config) -> tf.keras.Model:
    """DistilBERT encoder + two Dense heads on [CLS]."""
    encoder = TFAutoModel.from_pretrained(cfg.model_name)

    # Freeze embeddings + bottom N transformer blocks.
    if cfg.freeze_layers > 0:
        encoder.distilbert.embeddings.trainable = False
        for i in range(cfg.freeze_layers):
            encoder.distilbert.transformer.layer[i].trainable = False

    input_ids = tf.keras.Input(shape=(cfg.max_length,), dtype=tf.int32, name="input_ids")
    attention_mask = tf.keras.Input(shape=(cfg.max_length,), dtype=tf.int32, name="attention_mask")

    hidden = encoder(input_ids, attention_mask=attention_mask).last_hidden_state
    cls = hidden[:, 0, :]  # [CLS] pooled representation
    cls = tf.keras.layers.Dropout(cfg.dropout)(cls)

    severity_logits = tf.keras.layers.Dense(len(SEVERITIES), name="severity")(cls)
    category_logits = tf.keras.layers.Dense(len(CATEGORIES), name="category")(cls)

    return tf.keras.Model(
        inputs=[input_ids, attention_mask],
        outputs={"severity": severity_logits, "category": category_logits},
    )