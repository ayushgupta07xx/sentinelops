"""
Smoke test the Qdrant collection. Prints top-5 for a few canned queries.

Usage:
  python -m serving.rag.search_test
  python -m serving.rag.search_test "high latency on orders"
"""
from __future__ import annotations

import os
import sys
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

COLLECTION = "sentinelops_docs"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "localdev")

DEFAULT_QUERIES = [
    "orders-service 5xx spike after recent deploy",
    "postgres connection pool exhausted",
    "pod OOMKilled repeatedly",
    "latency p99 above SLO threshold",
    "upstream dependency returning errors",
]


def main():
    queries = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_QUERIES
    model = SentenceTransformer(EMBED_MODEL)
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

    for q in queries:
        print(f"\n=== {q} ===")
        vec = model.encode(q, normalize_embeddings=True).tolist()
        hits = client.query_points(
            collection_name=COLLECTION, query=vec, limit=5, with_payload=True
        ).points
        for h in hits:
            p = h.payload
            print(f"  [{h.score:.3f}] {p.get('source_type'):10s} {p.get('source')}")
            snippet = (p.get("text") or "")[:120].replace("\n", " ")
            print(f"         {snippet}...")


if __name__ == "__main__":
    main()
