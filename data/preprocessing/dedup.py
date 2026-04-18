"""Near-duplicate removal using MinHash + LSH.

Rationale: danluu links to blog posts that sometimes also appear elsewhere
(Wayback-archived copies, reposts). LSH over shingled MinHash signatures is the
standard scalable approach.

Threshold 0.85 Jaccard = 'mostly the same document, maybe different boilerplate'.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from datasketch import MinHash, MinHashLSH

log = logging.getLogger("dedup")

NUM_PERM = 128
THRESHOLD = 0.85
SHINGLE_SIZE = 5  # 5-word shingles

WORD_RE = re.compile(r"\b\w+\b")


def _shingles(text: str, k: int = SHINGLE_SIZE) -> set[str]:
    words = [w.lower() for w in WORD_RE.findall(text)]
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def _minhash(text: str) -> MinHash:
    mh = MinHash(num_perm=NUM_PERM)
    for sh in _shingles(text):
        mh.update(sh.encode())
    return mh


def dedupe(records: Iterable[dict]) -> list[dict]:
    """Return a deduplicated list, first occurrence wins."""
    lsh = MinHashLSH(threshold=THRESHOLD, num_perm=NUM_PERM)
    kept: list[dict] = []
    dropped = 0

    for rec in records:
        text = rec.get("body", "")
        if len(text) < 100:
            dropped += 1
            continue
        mh = _minhash(text)
        matches = lsh.query(mh)
        if matches:
            dropped += 1
            continue
        lsh.insert(rec["id"], mh)
        kept.append(rec)

    log.info("dedup: kept %d, dropped %d duplicates", len(kept), dropped)
    return kept
