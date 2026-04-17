# SentinelOps

Agentic LLM copilot for SRE incident response. End-to-end MLOps: fine-tuned Mistral-7B + retrieval-augmented LangGraph agent + production observability on Kubernetes.

> **Status:** 🚧 Week 1 — data platform + classifier baseline. Full README lands Week 5.

## Architecture (one-liner)

Postmortem corpus → DuckDB warehouse → DistilBERT classifier (TF) + Mistral-7B QLoRA (PyTorch) → vLLM on Modal → LangGraph agent w/ Qdrant RAG → FastAPI → kind cluster w/ Prometheus + Grafana.

## Quickstart (local dev)

```bash
# 1. Python env
uv venv && source .venv/bin/activate   # or: python -m venv .venv
uv pip install -e ".[dev]"             # or: pip install -e ".[dev]"

# 2. Secrets
cp .env.example sentinelops.env
# fill in tokens

# 3. Infra
docker compose up -d redpanda qdrant postgres prometheus grafana

# 4. Verify
docker compose ps
```

Services:
- Redpanda (Kafka) → `localhost:9092`
- Qdrant → `localhost:6333`
- Prometheus → `localhost:9090`
- Grafana → `localhost:3000` (admin/admin)
- Postgres → `localhost:5432` (airflow/airflow)

## Week-by-week

- [ ] Week 1 — Corpus in DuckDB, DistilBERT classifier (≥0.75 macro-F1)
- [ ] Week 2 — Mistral-7B QLoRA fine-tune on Kaggle
- [ ] Week 3 — LangGraph agent + Qdrant RAG + FastAPI
- [ ] Week 4 — Modal vLLM serving, K8s via Helm, Grafana dashboards, CI eval gate
- [ ] Week 5 — Kafka streaming, Airflow retraining, docs + demo
