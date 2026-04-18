"""Offline eval for PyTorch DistilBERT multitask classifier.

Loads model + tokenizer + test split from training/classifier/kaggle_outputs/classifier/,
produces per-class classification reports, confusion matrices, and eval_report.json.

Run from repo root with venv active:
    python -m training.classifier.eval
"""
import json
from pathlib import Path

import numpy as np
import torch
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from transformers import DistilBertTokenizerFast

from training.classifier.model_pt import DistilBertMultiTask, Config

ART_DIR = Path("training/classifier/kaggle_outputs/classifier")
REPORT_DIR = ART_DIR  # write outputs alongside artifacts


def load_model_and_tokenizer():
    with open(ART_DIR / "label_mappings.json") as f:
        label_mappings = json.load(f)
    # Handle {"severity": [...], "category": [...]} OR {"sev": {...}, "cat": {...}} shapes
    sev_labels = (label_mappings.get("severities") or label_mappings.get("severity")
                  or label_mappings.get("sev"))
    cat_labels = (label_mappings.get("categories") or label_mappings.get("category")
                  or label_mappings.get("cat"))
    if isinstance(sev_labels, dict):
        sev_labels = [sev_labels[str(i)] for i in range(len(sev_labels))]
    if isinstance(cat_labels, dict):
        cat_labels = [cat_labels[str(i)] for i in range(len(cat_labels))]

    tokenizer = DistilBertTokenizerFast.from_pretrained(str(ART_DIR / "tokenizer"))
    cfg = Config()
    model = DistilBertMultiTask(cfg)
    state = torch.load(ART_DIR / "model.pt", map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    return model, tokenizer, sev_labels, cat_labels


def get_test_tensors(tokenizer):
    import duckdb
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from training.classifier.model_pt import SEVERITIES, CATEGORIES

    # Load config to get db_path + seed + max_length
    with open(ART_DIR / "config.json") as f:
        cfg = json.load(f)
    # Kaggle's db_path won't exist locally — fall back to the standard local path
    db_path = cfg["db_path"]
    if not Path(db_path).exists():
        db_path = "data/warehouse/corpus.db"
    seed = cfg["seed"]
    max_length = cfg["max_length"]

    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("""
        SELECT f.incident_id, f.title, f.body, f.severity, c.category_name AS category
        FROM fact_incidents f
        JOIN dim_categories c ON f.category_id = c.category_id
        WHERE f.severity IS NOT NULL AND f.category_id IS NOT NULL
    """).fetchdf()
    con.close()

    sev2id = {s: i for i, s in enumerate(SEVERITIES)}
    cat2id = {c: i for i, c in enumerate(CATEGORIES)}
    y_sev = df.severity.map(sev2id).to_numpy()
    y_cat = df.category.map(cat2id).to_numpy()
    texts = (df.title.fillna("") + "\n\n" + df.body.fillna("")).tolist()

    idx = np.arange(len(df))
    train_idx, tmp = train_test_split(idx, test_size=0.2, stratify=y_sev, random_state=seed)
    val_idx, test_idx = train_test_split(tmp, test_size=0.5, stratify=y_sev[tmp], random_state=seed)

    # Sanity: match saved test indices
    saved = np.load(ART_DIR / "splits.npz", allow_pickle=True)
    saved_test = np.asarray(saved["test"], dtype=int)
    if not np.array_equal(np.sort(test_idx), np.sort(saved_test)):
        raise RuntimeError(
            f"Replayed test split does not match splits.npz. "
            f"Replayed first 5: {sorted(test_idx)[:5]}, saved first 5: {sorted(saved_test)[:5]}"
        )
    test_idx = saved_test  # preserve the exact saved order

    test_texts = [texts[i] for i in test_idx]
    enc = tokenizer(test_texts, padding="max_length", truncation=True,
                    max_length=max_length, return_tensors="pt")
    return enc["input_ids"], enc["attention_mask"], y_sev[test_idx], y_cat[test_idx]


def _extract_logits(out):
    """Handle dict / tuple / dataclass-style model output."""
    if isinstance(out, dict):
        sev = out.get("sev_logits") or out.get("severity_logits") or out.get("sev")
        cat = out.get("cat_logits") or out.get("category_logits") or out.get("cat")
        if sev is None or cat is None:
            raise KeyError(f"Could not find sev/cat logits in dict keys: {list(out.keys())}")
        return sev, cat
    if isinstance(out, (tuple, list)):
        return out[0], out[1]
    # dataclass / namedtuple
    return getattr(out, "sev_logits", None) or out.sev, getattr(out, "cat_logits", None) or out.cat


def run_inference(model, input_ids, attention_mask, batch_size=8):
    sev_preds, cat_preds = [], []
    with torch.no_grad():
        for i in range(0, input_ids.size(0), batch_size):
            ids = input_ids[i : i + batch_size]
            mask = attention_mask[i : i + batch_size]
            out = model(input_ids=ids, attention_mask=mask)
            sev_logits, cat_logits = _extract_logits(out)
            sev_preds.append(sev_logits.argmax(-1).cpu().numpy())
            cat_preds.append(cat_logits.argmax(-1).cpu().numpy())
    return np.concatenate(sev_preds), np.concatenate(cat_preds)


def save_confusion_matrix(y_true, y_pred, labels, title, out_path):
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(labels))))
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    thresh = cm.max() / 2 if cm.max() else 0
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black", fontsize=9)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    print(f"Loading artifacts from {ART_DIR}")
    model, tokenizer, sev_labels, cat_labels = load_model_and_tokenizer()
    print(f"Severity labels ({len(sev_labels)}): {sev_labels}")
    print(f"Category labels ({len(cat_labels)}): {cat_labels}")

    input_ids, attention_mask, sev_true, cat_true = get_test_tensors(tokenizer)
    print(f"Test set size: {input_ids.size(0)}")

    sev_pred, cat_pred = run_inference(model, input_ids, attention_mask)

    sev_report_dict = classification_report(
        sev_true, sev_pred, labels=list(range(len(sev_labels))),
        target_names=sev_labels, output_dict=True, zero_division=0,
    )
    cat_report_dict = classification_report(
        cat_true, cat_pred, labels=list(range(len(cat_labels))),
        target_names=cat_labels, output_dict=True, zero_division=0,
    )

    print("\n=== Severity ===")
    print(classification_report(sev_true, sev_pred, labels=list(range(len(sev_labels))),
                                 target_names=sev_labels, zero_division=0))
    print("=== Category ===")
    print(classification_report(cat_true, cat_pred, labels=list(range(len(cat_labels))),
                                 target_names=cat_labels, zero_division=0))

    save_confusion_matrix(sev_true, sev_pred, sev_labels,
                          "Severity Confusion Matrix",
                          REPORT_DIR / "confusion_matrix_severity.png")
    save_confusion_matrix(cat_true, cat_pred, cat_labels,
                          "Category Confusion Matrix",
                          REPORT_DIR / "confusion_matrix_category.png")

    report = {
        "test_size": int(input_ids.size(0)),
        "severity": {
            "macro_f1": float(f1_score(sev_true, sev_pred, average="macro", zero_division=0)),
            "micro_f1": float(f1_score(sev_true, sev_pred, average="micro", zero_division=0)),
            "weighted_f1": float(f1_score(sev_true, sev_pred, average="weighted", zero_division=0)),
            "accuracy": float((sev_true == sev_pred).mean()),
            "labels": sev_labels,
            "per_class": sev_report_dict,
        },
        "category": {
            "macro_f1": float(f1_score(cat_true, cat_pred, average="macro", zero_division=0)),
            "micro_f1": float(f1_score(cat_true, cat_pred, average="micro", zero_division=0)),
            "weighted_f1": float(f1_score(cat_true, cat_pred, average="weighted", zero_division=0)),
            "accuracy": float((cat_true == cat_pred).mean()),
            "labels": cat_labels,
            "per_class": cat_report_dict,
        },
    }

    with open(REPORT_DIR / "eval_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nSaved: {REPORT_DIR / 'eval_report.json'}")
    print(f"Saved: {REPORT_DIR / 'confusion_matrix_severity.png'}")
    print(f"Saved: {REPORT_DIR / 'confusion_matrix_category.png'}")
    print(f"\nSeverity macro-F1: {report['severity']['macro_f1']:.3f}")
    print(f"Category macro-F1: {report['category']['macro_f1']:.3f}")


if __name__ == "__main__":
    main()