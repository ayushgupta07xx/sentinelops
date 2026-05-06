# Multi-stage build for SentinelOps FastAPI service.
# Stage 1 installs deps + pre-bakes BGE embedding/reranker so runtime is
# hermetic (no network, no writable cache; chart keeps readOnlyRootFilesystem).

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml README.md ./
COPY serving/ ./serving/
RUN pip install --upgrade pip && pip install ".[serving]"

ENV HF_HOME=/opt/cache/huggingface
RUN mkdir -p /opt/cache/huggingface && \
    python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('BAAI/bge-small-en-v1.5'); \
CrossEncoder('BAAI/bge-reranker-base', max_length=512)"

# ---- Runtime ----
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/cache/huggingface \
    PORT=8000

RUN useradd -u 1000 -m appuser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /opt/cache/huggingface /opt/cache/huggingface
COPY --from=builder /build/serving /app/serving

WORKDIR /app
USER appuser
EXPOSE 8000

CMD ["uvicorn", "serving.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
