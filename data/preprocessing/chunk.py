"""Chunk long incidents into overlapping windows.

Rationale: DistilBERT has a 512-token limit; long postmortems need chunking
so no single example is truncated. We also use chunking to expand corpus size
for classifier training: a 3000-word postmortem → ~5 chunks.

600 words ≈ 800 tokens (rough, model-dependent). We stay under 512 after
tokenization by targeting 400 words per chunk with 80-word overlap.
"""

from __future__ import annotations

import re
from typing import Iterator

WORD_RE = re.compile(r"\S+")

CHUNK_WORDS = 400
OVERLAP_WORDS = 80


def chunk_text(text: str, chunk_words: int = CHUNK_WORDS, overlap: int = OVERLAP_WORDS) -> list[str]:
    """Split text into overlapping word windows. Short texts return as a single chunk."""
    words = WORD_RE.findall(text)
    if len(words) <= chunk_words:
        return [" ".join(words)] if words else []

    chunks: list[str] = []
    step = chunk_words - overlap
    for start in range(0, len(words), step):
        piece = words[start : start + chunk_words]
        if len(piece) < 50:  # tail scrap, skip
            break
        chunks.append(" ".join(piece))
        if start + chunk_words >= len(words):
            break
    return chunks


def chunk_record(rec: dict) -> Iterator[dict]:
    """Yield one dict per chunk, carrying parent metadata + chunk index."""
    pieces = chunk_text(rec.get("body", ""))
    for i, piece in enumerate(pieces):
        yield {
            "id": f"{rec['id']}__c{i:02d}",
            "parent_id": rec["id"],
            "chunk_index": i,
            "source": rec["source"],
            "url": rec.get("url", ""),
            "title": rec.get("title", ""),
            "body": piece,
            "published_at": rec.get("published_at"),
            "scraped_at": rec.get("scraped_at"),
        }
