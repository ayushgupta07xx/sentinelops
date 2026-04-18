
from __future__ import annotations
import argparse, json, random
from dataclasses import asdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight
from torch.utils.data import DataLoader, Dataset
from transformers import AutoTokenizer

from .model_pt import CATEGORIES, SEVERITIES, Config, DistilBertMultiTask

def parse_args() -> Config:
    defaults = Config()
    p = argparse.ArgumentParser()
    for name, val in asdict(defaults).items():
        if isinstance(val, bool):
            p.add_argument(f"--{name}", action="store_true", default=val)
        else:
            p.add_argument(f"--{name}", type=type(val), default=val)
    return Config(**vars(p.parse_args()))

def load_labeled(db_path):
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("""
        SELECT f.incident_id, f.title, f.body, f.severity, c.category_name AS category
        FROM fact_incidents f
        JOIN dim_categories c ON f.category_id = c.category_id
        WHERE f.severity IS NOT NULL AND f.category_id IS NOT NULL
    """).fetchdf()
    con.close()
    return df

class IncidentDS(Dataset):
    def __init__(self, input_ids, attn, y_sev, y_cat):
        self.input_ids = torch.tensor(input_ids, dtype=torch.long)
        self.attn = torch.tensor(attn, dtype=torch.long)
        self.y_sev = torch.tensor(y_sev, dtype=torch.long)
        self.y_cat = torch.tensor(y_cat, dtype=torch.long)
    def __len__(self): return len(self.y_sev)
    def __getitem__(self, i):
        return {
            "input_ids": self.input_ids[i], "attention_mask": self.attn[i],
            "y_sev": self.y_sev[i], "y_cat": self.y_cat[i],
        }

def set_seed(seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)

@torch.no_grad()
def evaluate(model, loader, device, loss_sev, loss_cat):
    model.eval()
    tot, n = {"loss": 0.0, "sev_acc": 0, "cat_acc": 0}, 0
    for b in loader:
        ids = b["input_ids"].to(device); attn = b["attention_mask"].to(device)
        ys = b["y_sev"].to(device); yc = b["y_cat"].to(device)
        s_logits, c_logits = model(ids, attn)
        loss = loss_sev(s_logits, ys) + loss_cat(c_logits, yc)
        tot["loss"] += loss.item() * len(ys)
        tot["sev_acc"] += (s_logits.argmax(-1) == ys).sum().item()
        tot["cat_acc"] += (c_logits.argmax(-1) == yc).sum().item()
        n += len(ys)
    return {k: v / n for k, v in tot.items()}

def main():
    cfg = parse_args()
    print(f"Config: {asdict(cfg)}")
    set_seed(cfg.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    out_dir = Path(cfg.output_dir); out_dir.mkdir(parents=True, exist_ok=True)

    df = load_labeled(cfg.db_path)
    print(f"Loaded {len(df)} labeled rows")
    print(f"  Severity: {df.severity.value_counts().to_dict()}")
    print(f"  Category: {df.category.value_counts().to_dict()}")

    sev2id = {s: i for i, s in enumerate(SEVERITIES)}
    cat2id = {c: i for i, c in enumerate(CATEGORIES)}
    y_sev = df.severity.map(sev2id).to_numpy()
    y_cat = df.category.map(cat2id).to_numpy()
    texts = (df.title.fillna("") + "\n\n" + df.body.fillna("")).tolist()

    idx = np.arange(len(df))
    train_idx, tmp = train_test_split(idx, test_size=0.2, stratify=y_sev, random_state=cfg.seed)
    val_idx, test_idx = train_test_split(tmp, test_size=0.5, stratify=y_sev[tmp], random_state=cfg.seed)
    print(f"Splits: train={len(train_idx)} val={len(val_idx)} test={len(test_idx)}")

    tokenizer = AutoTokenizer.from_pretrained(cfg.model_name)
    enc = tokenizer([texts[i] for i in range(len(texts))], padding="max_length",
                    truncation=True, max_length=cfg.max_length, return_tensors="np")
    input_ids, attn = enc["input_ids"], enc["attention_mask"]

    sev_w = compute_class_weight("balanced", classes=np.arange(len(SEVERITIES)), y=y_sev[train_idx])
    cat_w = compute_class_weight("balanced", classes=np.arange(len(CATEGORIES)), y=y_cat[train_idx])
    print(f"Severity weights: {dict(zip(SEVERITIES, sev_w.round(2)))}")
    print(f"Category weights: {dict(zip(CATEGORIES, cat_w.round(2)))}")

    def mk_loader(ii, shuffle=False):
        ds = IncidentDS(input_ids[ii], attn[ii], y_sev[ii], y_cat[ii])
        return DataLoader(ds, batch_size=cfg.batch_size, shuffle=shuffle, num_workers=2, pin_memory=True)

    train_loader = mk_loader(train_idx, shuffle=True)
    val_loader = mk_loader(val_idx); test_loader = mk_loader(test_idx)

    model = DistilBertMultiTask(cfg).to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Trainable params: {trainable:,} / {total:,}")

    loss_sev = nn.CrossEntropyLoss(weight=torch.tensor(sev_w, dtype=torch.float32, device=device))
    loss_cat = nn.CrossEntropyLoss(weight=torch.tensor(cat_w, dtype=torch.float32, device=device))
    optim = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=cfg.learning_rate, weight_decay=cfg.weight_decay,
    )

    if cfg.use_wandb:
        import wandb
        wandb.init(project="sentinelops", job_type="classifier_pt", config=asdict(cfg))

    best_val, best_state, patience = float("inf"), None, 0
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        tr_loss, n_tr = 0.0, 0
        for b in train_loader:
            ids = b["input_ids"].to(device); a = b["attention_mask"].to(device)
            ys = b["y_sev"].to(device); yc = b["y_cat"].to(device)
            s_logits, c_logits = model(ids, a)
            loss = loss_sev(s_logits, ys) + loss_cat(c_logits, yc)
            optim.zero_grad(); loss.backward(); optim.step()
            tr_loss += loss.item() * len(ys); n_tr += len(ys)
        tr_loss /= n_tr
        val_metrics = evaluate(model, val_loader, device, loss_sev, loss_cat)
        print(f"Epoch {epoch:2d} | train_loss={tr_loss:.4f} | "
              f"val_loss={val_metrics['loss']:.4f} "
              f"val_sev_acc={val_metrics['sev_acc']:.4f} "
              f"val_cat_acc={val_metrics['cat_acc']:.4f}")
        if cfg.use_wandb:
            import wandb
            wandb.log({"epoch": epoch, "train_loss": tr_loss, **{f"val_{k}": v for k,v in val_metrics.items()}})
        if val_metrics["loss"] < best_val - 1e-4:
            best_val = val_metrics["loss"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= cfg.early_stop_patience:
                print(f"Early stop at epoch {epoch}"); break

    if best_state is not None:
        model.load_state_dict(best_state)

    test_metrics = evaluate(model, test_loader, device, loss_sev, loss_cat)
    print(f"Test results: {test_metrics}")

    torch.save(model.state_dict(), out_dir / "model.pt")
    tokenizer.save_pretrained(str(out_dir / "tokenizer"))
    (out_dir / "label_mappings.json").write_text(
        json.dumps({"severities": SEVERITIES, "categories": CATEGORIES}, indent=2))
    (out_dir / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
    np.savez(out_dir / "splits.npz", train=train_idx, val=val_idx, test=test_idx)
    (out_dir / "test_results.json").write_text(json.dumps(test_metrics, indent=2))
    print(f"Saved artifacts to {out_dir}")

if __name__ == "__main__":
    main()
