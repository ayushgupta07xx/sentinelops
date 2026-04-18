## ADR-001 — Dual-framework classifier baseline (TF + PyTorch)

**Date:** Week 1, Day 6
**Status:** Accepted

**Context:** Original plan (Section 4) specified TensorFlow/Keras for the
DistilBERT baseline classifier. Mid-Week-1, Hugging Face's `transformers`
library on Kaggle's current image no longer exposes `TFAutoModel` — TF support
has been progressively deprecated, and pinning `transformers==4.40.2` to
restore it created cascading dependency conflicts (tokenizers, sentence-
transformers, tf-keras API drift).

**Decision:** Keep the TF/Keras implementation (`model.py`, `train.py`) as the
initial baseline artifact — it compiles, runs locally on CPU, and documents
the intended approach. Train the production baseline in PyTorch
(`model_pt.py`, `train_pt.py`) on Kaggle T4, which has no such issues. Both
live in the repo.

**Consequences:**
- Resume/interview story: "built baseline in both frameworks; selected PyTorch
  for production after HF deprecated TF in transformers."
- Week 5 Airflow DAG will include a TF/Keras drift-detection MLP to keep TF
  as a live, serving component of the system.
- Unifies Week 1 (classifier) and Week 2 (QLoRA) on a single framework for
  the main ML pipeline, simplifying the project story.