"""
Embed runbooks + historical postmortems into a single Qdrant collection.

One collection: `sentinelops_docs`
Payload fields (all indexed for filtering):
  - source_type: "runbook" | "postmortem"
  - source:      "docs/runbooks/users-service-errors.md" | original postmortem URL/id
  - service:     "users-service" | "cloudflare" | ... (best-effort)
  - severity:    "critical" | "warning" | null
  - date:        ISO string if known, else null
  - url:         public link if known, else null
  - title:       runbook frontmatter title or postmortem title
  - text:        the chunk text itself (so retrieval returns the passage directly)

Embedding model: BAAI/bge-small-en-v1.5 (384-dim, cosine).

Run:
  python -m serving.rag.embed                 # embed everything
  python -m serving.rag.embed --runbooks-only # just runbooks (fast iteration)
  python -m serving.rag.embed --reset         # drop + recreate collection
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Iterable

import yaml
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_DIR = REPO_ROOT / "docs" / "runbooks"
CHUNKS_FILE = REPO_ROOT / "data" / "processed" / "corpus_chunks.jsonl"

COLLECTION = "sentinelops_docs"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
CHUNK_WORDS = 400
CHUNK_OVERLAP = 80
BATCH = 64

# Qdrant connection (compose sets QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY:-localdev})
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "localdev")


# -----------------------------------------------------------------------------
# Chunking (same 400/80 rule used in Week 1 preprocessing)
# -----------------------------------------------------------------------------
def chunk_text(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [text]
    chunks, i = [], 0
    step = size - overlap
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        if i + size >= len(words):
            break
        i += step
    return chunks


# -----------------------------------------------------------------------------
# Runbook reader: parse YAML frontmatter + body
# -----------------------------------------------------------------------------
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def load_runbooks() -> Iterable[dict]:
    for md in sorted(RUNBOOK_DIR.glob("*.md")):
        raw = md.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(raw)
        if not m:
            print(f"  [skip] no frontmatter: {md.name}")
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        body = m.group(2).strip()

        # Normalize service field (can be "users-service" or "users-service, orders-service")
        service = fm.get("service")
        if isinstance(service, str) and "," in service:
            service = [s.strip() for s in service.split(",")]

        for idx, chunk in enumerate(chunk_text(body)):
            yield {
                "text": chunk,
                "source_type": "runbook",
                "source": f"docs/runbooks/{md.name}",
                "title": fm.get("title"),
                "service": service,
                "severity": fm.get("severity"),
                "date": None,
                "url": f"https://github.com/ayushgupta07xx/observashop/blob/main/docs/runbooks/{md.name}",
                "chunk_index": idx,
            }


# -----------------------------------------------------------------------------
# Postmortem reader: corpus_chunks.jsonl from Week 1
# Expected fields per line (from preprocessing): id, text, source, date, service, url
# If schema differs, we coerce best-effort and null the rest.
# -----------------------------------------------------------------------------
def load_postmortems() -> Iterable[dict]:
    if not CHUNKS_FILE.exists():
        print(f"  [warn] {CHUNKS_FILE} not found; skipping postmortems")
        return
    with CHUNKS_FILE.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            text = row.get("body") or row.get("text") or row.get("chunk") or ""
            if not text:
                continue
            yield {
                "text": text,
                "source_type": "postmortem",
                "source": row.get("parent_id") or row.get("id") or row.get("source") or "unknown",
                "title": row.get("title"),
                "service": row.get("service"),
                "severity": row.get("severity"),
                "date": row.get("date"),
                "url": row.get("url"),
                "chunk_index": row.get("chunk_index", 0),
            }


# -----------------------------------------------------------------------------
# Qdrant setup
# -----------------------------------------------------------------------------
def ensure_collection(client: QdrantClient, reset: bool) -> None:
    exists = client.collection_exists(COLLECTION)
    if exists and reset:
        print(f"[reset] dropping existing collection {COLLECTION}")
        client.delete_collection(COLLECTION)
        exists = False
    if not exists:
        print(f"[create] {COLLECTION} (dim={EMBED_DIM}, cosine)")
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE),
        )
        # Payload indexes speed up filter-heavy retrieval later
        for field, schema in [
            ("source_type", qm.PayloadSchemaType.KEYWORD),
            ("service", qm.PayloadSchemaType.KEYWORD),
            ("severity", qm.PayloadSchemaType.KEYWORD),
        ]:
            client.create_payload_index(COLLECTION, field_name=field, field_schema=schema)


def stable_id(source: str, chunk_index: int) -> str:
    # Deterministic UUIDv5 so re-running embed is idempotent (same chunk -> same id -> upsert overwrites)
    key = f"{source}::{chunk_index}"
    return str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main(args):
    print(f"[model] loading {EMBED_MODEL}")
    model = SentenceTransformer(EMBED_MODEL)

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    ensure_collection(client, reset=args.reset)

    # Collect
    docs = list(load_runbooks())
    print(f"[runbooks] {len(docs)} chunks")
    if not args.runbooks_only:
        pm = list(load_postmortems())
        docs.extend(pm)
        print(f"[postmortems] {len(pm)} chunks")

    if not docs:
        print("[abort] nothing to embed")
        return

    # Embed + upsert in batches
    print(f"[embed] {len(docs)} chunks, batch={BATCH}")
    for i in tqdm(range(0, len(docs), BATCH)):
        batch = docs[i : i + BATCH]
        texts = [d["text"] for d in batch]
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        points = [
            qm.PointStruct(
                id=stable_id(d["source"], d["chunk_index"]),
                vector=vec.tolist(),
                payload=d,
            )
            for d, vec in zip(batch, vectors)
        ]
        client.upsert(collection_name=COLLECTION, points=points)

    count = client.count(COLLECTION, exact=True).count
    print(f"[done] collection {COLLECTION} now holds {count} points")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runbooks-only", action="store_true", help="skip postmortem corpus")
    p.add_argument("--reset", action="store_true", help="drop and recreate the collection")
    main(p.parse_args())
