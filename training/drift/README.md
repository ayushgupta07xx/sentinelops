# Drift detector

TF/Keras MLP for SentinelOps corpus distribution shift. Standalone — no
`transformers`, no `torch` (transformers TF support is broken in our pinned
stack; this lives off-stack on purpose).

## What it computes

Five distributional features between two JSONL incident corpora:

| # | feature                                       | scale  |
|---|-----------------------------------------------|--------|
| 0 | mean token-length delta (/1000)               | [0, 1] |
| 1 | JS divergence on token-length histogram       | [0, 1] |
| 2 | Jaccard distance on top-1000 vocab            | [0, 1] |
| 3 | L1 distance on severity distribution          | [0, 1] |
| 4 | L1 distance on service distribution           | [0, 1] |

Features → `Dense(16) → Dense(8) → Dense(1, sigmoid)` → drift score in
[0, 1]. Threshold 0.5 means "drifted."

The model is trained on synthetic pairs (low-feature → 0, high-feature → 1),
not on real labeled drift data. It's effectively a learned thresholding
function — appropriate for the demo's purpose, defensible as a baseline.

## CLI

```bash
# In WSL at ~/sentinelops with .venv active.
python training/drift/drift_detector.py \
    --baseline data/processed/corpus.jsonl \
    --recent   data/processed/corpus.jsonl
# drift_score=0.0xxx  threshold=0.5  drifted=False
```

First run trains the model (~3 sec on CPU) and writes
`training/drift/drift_detector.keras`. Subsequent runs load it.

## Imported by

- `orchestration/airflow/dags/weekly_retrain_dag.py` (drift-check task,
  inside the Airflow container at `/opt/airflow/drift/drift_detector.py`).

## Why TF here

Keeps TensorFlow as a live, serving component of the system after the
Week 1 DistilBERT classifier was abandoned (see `docs/decisions.md`
ADR-001). The drift detector is the surviving TF integration point.
