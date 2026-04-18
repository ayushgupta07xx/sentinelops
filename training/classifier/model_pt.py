"""PyTorch DistilBERT multi-task classifier (severity + category).

Pivoted from the TF/Keras baseline in model.py when Hugging Face's transformers
library deprecated TF support (TFAutoModel removed from recent releases). The
TF path lives in model.py + train.py as the initial baseline; this is the
production training path that runs on Kaggle T4.
"""
from dataclasses import dataclass
import os

import torch
import torch.nn as nn
from transformers import AutoModel

SEVERITIES = ["P0", "P1", "P2", "P3"]
CATEGORIES = ["deploy", "networking", "database", "capacity", "auth", "other"]
IS_KAGGLE = os.path.exists("/kaggle/working")


@dataclass
class Config:
    model_name: str = "distilbert-base-uncased"
    max_length: int = 384
    dropout: float = 0.1
    freeze_layers: int = 4   # freeze embeddings + bottom 4 of 6 transformer blocks
    batch_size: int = 16
    epochs: int = 25
    learning_rate: float = 3e-5
    weight_decay: float = 0.01
    early_stop_patience: int = 5
    seed: int = 42
    db_path: str = (
        "/kaggle/input/datasets/ayushgupta07xx/sentinelops-corpus/corpus.db"
        if IS_KAGGLE else "data/warehouse/corpus.db"
    )
    output_dir: str = (
        "/kaggle/working/classifier" if IS_KAGGLE
        else "training/classifier/outputs_pt"
    )
    use_wandb: bool = False


class DistilBertMultiTask(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(cfg.model_name)
        if cfg.freeze_layers > 0:
            for p in self.encoder.embeddings.parameters():
                p.requires_grad = False
            for i in range(cfg.freeze_layers):
                for p in self.encoder.transformer.layer[i].parameters():
                    p.requires_grad = False
        h = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(cfg.dropout)
        self.severity_head = nn.Linear(h, len(SEVERITIES))
        self.category_head = nn.Linear(h, len(CATEGORIES))

    def forward(self, input_ids, attention_mask):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        cls = self.dropout(out.last_hidden_state[:, 0, :])
        return self.severity_head(cls), self.category_head(cls)