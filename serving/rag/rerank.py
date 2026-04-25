"""
serving/rag/rerank.py
Two-stage retrieval: Qdrant dense top-N -> BGE cross-encoder rerank top-K.

Why two-stage:
  Dense retrieval (bi-encoder) is fast but coarse; cross-encoder rerank scores
  (query, doc) jointly and tightens the top of the list at small extra cost.
  Brief target: ~30% precision lift at top-5 vs single-stage dense.

Usage as module:
    from serving.rag.rerank import dense_then_rerank
    hits = dense_then_rerank("postgres pool exhausted", top_dense=20, top_rerank=5)

Usage as smoke test:
    python -m serving.rag.rerank
"""

from __future__ import annotations

import os
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from sentence_transformers import CrossEncoder, SentenceTransformer

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "localdev")
COLLECTION = "sentinelops_docs"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"


@lru_cache(maxsize=1)
def _embedder() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)


@lru_cache(maxsize=1)
def _reranker() -> CrossEncoder:
    # First call downloads ~280 MB to ~/.cache/huggingface/
    return CrossEncoder(RERANK_MODEL, max_length=512)


@lru_cache(maxsize=1)
def _qdrant() -> QdrantClient:
    return QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        check_compatibility=False,  # silence client/server minor mismatch warning
    )


def dense_search(
    query: str,
    top_n: int = 20,
    source_type: str | None = None,
) -> list[dict]:
    """Stage 1: dense retrieval from Qdrant. Optional source_type filter."""
    qfilter = None
    if source_type:
        qfilter = qm.Filter(
            must=[qm.FieldCondition(key="source_type", match=qm.MatchValue(value=source_type))]
        )
    vec = _embedder().encode(query, normalize_embeddings=True).tolist()
    hits = _qdrant().query_points(
        collection_name=COLLECTION,
        query=vec,
        limit=top_n,
        query_filter=qfilter,
        with_payload=True,
    ).points
    return [
        {
            "id": str(h.id),
            "dense_score": float(h.score),
            "text": h.payload.get("text", ""),
            "source_type": h.payload.get("source_type"),
            "source": h.payload.get("source"),
            "title": h.payload.get("title"),
            "service": h.payload.get("service"),
            "severity": h.payload.get("severity"),
            "url": h.payload.get("url"),
        }
        for h in hits
    ]


def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Stage 2: cross-encoder rerank. Mutates candidates by adding rerank_score."""
    if not candidates:
        return []
    pairs = [(query, c["text"]) for c in candidates]
    scores = _reranker().predict(pairs, show_progress_bar=False)
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
    return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]


def dense_then_rerank(
    query: str,
    top_dense: int = 20,
    top_rerank: int = 5,
    source_type: str | None = None,
) -> list[dict]:
    """Full two-stage pipeline."""
    candidates = dense_search(query, top_n=top_dense, source_type=source_type)
    return rerank(query, candidates, top_k=top_rerank)


# -----------------------------------------------------------------------------
# Smoke test: prints dense vs rerank ordering for 5 canned queries
# -----------------------------------------------------------------------------
QUERIES = [
    "postgres connection pool exhausted on orders-service",
    "orders-service 5xx spike after recent deploy",
    "pod stuck in CrashLoopBackOff after OOM",
    "TLS certificate expired in production",
    "high p99 latency burning the SLO budget",
]


def _smoke() -> None:
    for q in QUERIES:
        print(f"\n=== {q} ===")
        dense = dense_search(q, top_n=20)
        reranked = rerank(q, [dict(c) for c in dense], top_k=3)  # copy so dense list is unmodified
        print(f"  -- dense top-3 --")
        for i, h in enumerate(dense[:3], 1):
            title = h.get("title") or h.get("source") or "(untitled)"
            print(f"    {i}. [{h['source_type']:9s}] {h['dense_score']:.3f}  {title[:70]}")
        print(f"  -- rerank top-3 --")
        for i, h in enumerate(reranked, 1):
            title = h.get("title") or h.get("source") or "(untitled)"
            print(
                f"    {i}. [{h['source_type']:9s}] dense={h['dense_score']:.3f} "
                f"rerank={h['rerank_score']:+.3f}  {title[:70]}"
            )


if __name__ == "__main__":
    _smoke()
