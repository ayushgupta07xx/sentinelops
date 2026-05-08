"""TF/Keras drift detector for SentinelOps corpus distribution shift.

Standalone — no transformers, no PyTorch. Imported by the Airflow
weekly_retrain_dag drift-check task; runnable directly as CLI.

Features (5-dim, computed between two JSONL incident corpora):
  0. mean token-length delta (normalized by /1000)
  1. JS divergence on token-length histograms (10 bins)
  2. Jaccard distance on top-1000 vocab
  3. L1 distance on severity distribution
  4. L1 distance on service distribution

Model: 5 -> Dense(16, relu) -> Dense(8, relu) -> Dense(1, sigmoid).
Trained on synthetic pairs:
  - "no drift": all 5 features sampled uniformly from [0.00, 0.10]  -> 0
  - "drift":    all 5 features sampled uniformly from [0.20, 1.00]  -> 1

Score >= 0.5 means "drifted." First call to score() trains and saves the
model; subsequent calls load it.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import tensorflow as tf  # noqa: F401  (registers Keras backend)
from tensorflow import keras

FEATURE_DIM = 5
DRIFT_THRESHOLD = 0.5
MODEL_PATH = Path(__file__).parent / "drift_detector.keras"


# ---------- corpus IO ----------

def _load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _text(r: dict) -> str:
    return r.get("body") or r.get("text") or r.get("content") or ""


# ---------- feature primitives ----------

def _token_lens(records: list[dict]) -> list[int]:
    return [len(_text(r).split()) for r in records]


def _hist(values: list[int], bins: int = 10, max_v: int = 2000) -> np.ndarray:
    h, _ = np.histogram(values, bins=bins, range=(0, max_v))
    return h / max(h.sum(), 1)


def _js_div(p: np.ndarray, q: np.ndarray, eps: float = 1e-10) -> float:
    p = np.asarray(p, dtype=float) + eps
    q = np.asarray(q, dtype=float) + eps
    p, q = p / p.sum(), q / q.sum()
    m = 0.5 * (p + q)
    return float(0.5 * (np.sum(p * np.log(p / m)) + np.sum(q * np.log(q / m))))


def _vocab_jaccard(a: list[dict], b: list[dict], top_k: int = 1000) -> float:
    def top(recs):
        c: Counter[str] = Counter()
        for r in recs:
            c.update(_text(r).lower().split())
        return {w for w, _ in c.most_common(top_k)}
    va, vb = top(a), top(b)
    if not va or not vb:
        return 1.0
    return 1.0 - len(va & vb) / len(va | vb)


def _categorical_l1(a: list[dict], b: list[dict], key: str) -> float:
    def dist(recs):
        c = Counter(r.get(key, "unknown") for r in recs)
        total = max(sum(c.values()), 1)
        return {k: v / total for k, v in c.items()}
    da, db = dist(a), dist(b)
    keys = set(da) | set(db)
    return sum(abs(da.get(k, 0.0) - db.get(k, 0.0)) for k in keys) / 2.0


# ---------- public API ----------

def compute_features(baseline_path: str, recent_path: str) -> np.ndarray:
    """Return the 5-dim drift feature vector between two JSONL corpora."""
    a, b = _load_jsonl(baseline_path), _load_jsonl(recent_path)
    la, lb = _token_lens(a), _token_lens(b)
    f = np.array([
        abs(np.mean(la) - np.mean(lb)) / 1000.0 if la and lb else 0.0,
        _js_div(_hist(la), _hist(lb)),
        _vocab_jaccard(a, b),
        _categorical_l1(a, b, "severity"),
        _categorical_l1(a, b, "service"),
    ], dtype=np.float32)
    return np.clip(f, 0.0, 1.0)


def build_model() -> keras.Model:
    m = keras.Sequential([
        keras.layers.Input(shape=(FEATURE_DIM,)),
        keras.layers.Dense(16, activation="relu"),
        keras.layers.Dense(8, activation="relu"),
        keras.layers.Dense(1, activation="sigmoid"),
    ])
    m.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])
    return m


def train_synthetic(seed: int = 0, n: int = 4000) -> keras.Model:
    """Train on synthetic pairs and persist to MODEL_PATH."""
    rng = np.random.default_rng(seed)
    neg = rng.uniform(0.0, 0.10, size=(n // 2, FEATURE_DIM)).astype(np.float32)
    pos = rng.uniform(0.20, 1.00, size=(n // 2, FEATURE_DIM)).astype(np.float32)
    X = np.vstack([neg, pos])
    y = np.concatenate([np.zeros(n // 2), np.ones(n // 2)]).astype(np.float32)
    idx = rng.permutation(len(X))
    X, y = X[idx], y[idx]
    model = build_model()
    model.fit(X, y, epochs=15, batch_size=64, validation_split=0.2, verbose=0)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save(MODEL_PATH)
    return model


def score(baseline_path: str, recent_path: str) -> float:
    """Drift score in [0, 1]. Trains on first call if MODEL_PATH absent."""
    if not MODEL_PATH.exists():
        train_synthetic()
    model = keras.models.load_model(MODEL_PATH)
    feats = compute_features(baseline_path, recent_path).reshape(1, -1)
    # Direct __call__ (not model.predict) — avoids the predict_function code
    # path which fails with TypeError when steps_per_execution=None on a
    # .keras file saved by a slightly different TF/Keras version (e.g. host
    # venv saves, Airflow container loads). Inference result is identical.
    return float(model(feats, training=False).numpy()[0, 0])


# ---------- CLI ----------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="SentinelOps drift detector")
    p.add_argument("--baseline", required=True, help="Path to baseline JSONL corpus")
    p.add_argument("--recent", required=True, help="Path to recent JSONL corpus")
    args = p.parse_args()
    s = score(args.baseline, args.recent)
    print(
        f"drift_score={s:.4f}  threshold={DRIFT_THRESHOLD}  "
        f"drifted={s >= DRIFT_THRESHOLD}"
    )
