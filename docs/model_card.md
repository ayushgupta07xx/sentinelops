---
language: en
license: apache-2.0
library_name: pytorch
tags:
  - distilbert
  - text-classification
  - multi-task
  - incident-response
  - sre
  - sentinelops
pipeline_tag: text-classification
datasets:
  - ayushgupta07xx/sentinelops-corpus
base_model: distilbert-base-uncased
---

# SentinelOps Incident Classifier

Multi-task DistilBERT classifier that predicts **severity** (P0/P1/P2/P3) and **category** (networking, database, deploy, capacity, auth, other) for SRE incident postmortems. Non-generative baseline for the [SentinelOps](https://github.com/ayushgupta07xx/sentinelops) flagship project, benchmarked against a fine-tuned Mistral-7B generation model.

## Intended use

Given an incident summary, returns `{severity, category}` predictions for routing, prioritization, or retrieval filtering inside the SentinelOps agent.

**Not intended for**: standalone production incident triage, compliance decisions, or any use case where a miscategorization has safety or financial impact.

## Training data

- **Corpus**: 2,000+ public postmortems scraped from `danluu/post-mortems`, Cloudflare blog, GitHub status (Atom feed), and AWS post-event summaries.
- **Labeled subset**: ~270 manually labeled for severity (4 classes) and category (6 classes). Remaining examples weakly labeled via regex + keyword rules.
- **Preprocessing**: HTML→text; MinHash dedup (threshold 0.85, 5-word shingles, 128 permutations); PII scrub (regex for emails/IPs/tokens + Presidio for names/phones).

Dataset: https://huggingface.co/datasets/ayushgupta07xx/sentinelops-corpus

## Training

- **Base**: `distilbert-base-uncased`
- **Architecture**: Shared DistilBERT encoder with two classification heads (severity + category), joint loss.
- **Hardware**: Kaggle T4 GPU (PyTorch).
- **Optimizer**: AdamW with cosine LR schedule.
- **Tracking**: Weights & Biases — project `sentinelops`, job_type `classifier_pt`.

Training code: https://github.com/ayushgupta07xx/sentinelops/blob/main/training/classifier/train_pt.py

## Evaluation

### ⚠️ Test set is 27 examples

This is a **small held-out set** — per-class F1 numbers have high variance and a single misclassification moves a 9-example class F1 by ~0.1. Treat these numbers as directional indicators, not population estimates. The limit reflects the labeled-data budget (~270 manually labeled examples, standard 80/10/10 split) which is the realistic ceiling for a solo 5-week project.

### Headline metrics

| Head     | Accuracy | Macro-F1 | Weighted-F1 |
|----------|----------|----------|-------------|
| Severity | 0.48     | 0.36     | 0.52        |
| Category | 0.30     | 0.36     | 0.24        |

Full per-class precision/recall/F1 is in `eval_report.json`. Confusion matrices: `assets/confusion_matrix_severity.png`, `assets/confusion_matrix_category.png`.

## Limitations

1. **Tiny test set (27)** — confidence intervals on per-class F1 are wide. Do not use these numbers to claim SOTA anything.
2. **Class imbalance** — some classes (e.g., `auth`) had fewer than 10 training examples; the model underperforms there.
3. **Weak labels** — the majority of training data uses regex/keyword rules, so the model partially learns those rules rather than semantic features. Performance on incidents whose vocabulary doesn't match the rules is likely worse.
4. **Domain drift** — trained on public postmortems from hyperscalers and open-source infra. Generalization to internal enterprise incidents without further fine-tuning is unverified.
5. **English only** — all training data is English.

## Bias considerations

- Overrepresentation of hyperscaler incidents (AWS, GitHub, Cloudflare) vs. small-org or on-prem incidents.
- "Severity" labels reflect the reporting org's conventions, which differ across companies — the model learns an average that may not match your org's definitions.
- Weak labels encode my prior about what keywords indicate each category, which may bias category boundaries.

## Files

- `model.pt` — PyTorch state dict (~253 MB)
- `tokenizer/` — HF tokenizer files
- `config.json` — model hyperparameters
- `label_mappings.json` — `severity` and `category` label lists
- `eval_report.json` — full classification reports
- `assets/confusion_matrix_{severity,category}.png` — confusion matrices

## Loading

```python
import json, torch
from transformers import DistilBertTokenizerFast
from huggingface_hub import snapshot_download

local = snapshot_download("ayushgupta07xx/sentinelops-classifier")

# Requires the DistilBertMultiTask class from:
# https://github.com/ayushgupta07xx/sentinelops/blob/main/training/classifier/model_pt.py
from model_pt import DistilBertMultiTask, Config

with open(f"{local}/label_mappings.json") as f:
    lm = json.load(f)
cfg = Config(num_severity=len(lm["severity"]), num_category=len(lm["category"]))
model = DistilBertMultiTask(cfg)
model.load_state_dict(torch.load(f"{local}/model.pt", map_location="cpu"))
model.eval()

tokenizer = DistilBertTokenizerFast.from_pretrained(f"{local}/tokenizer")
```

## Citation

Built as part of [SentinelOps](https://github.com/ayushgupta07xx/sentinelops). No paper — this is engineering, not research.

## Changelog

- **2026-04 v0.1** — Initial release; 27-example test set.
