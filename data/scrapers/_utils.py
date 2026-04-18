"""Shared helpers for all scrapers.

Every scraper uses:
- `Http` for requests (retries + polite rate limiting + consistent UA).
- `clean_text` to strip HTML to plain text.
- `make_id` for stable deterministic IDs (source + url hash).
- `JsonlWriter` as a context manager — appends one record per line.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import httpx
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-18s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

UA = "SentinelOpsScraper/0.1 (+https://github.com/ayushgupta07xx/sentinelops; research/education)"


@dataclass
class Incident:
    """One scraped incident. Schema is identical across sources."""

    id: str
    source: str
    url: str
    title: str
    body: str
    published_at: str | None  # ISO 8601, best-effort
    scraped_at: str
    raw_html: str | None = None  # kept for potential re-parse, stripped later

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_id(source: str, url: str) -> str:
    """Stable ID from source + URL (sha1, first 16 chars)."""
    h = hashlib.sha1(f"{source}::{url}".encode()).hexdigest()[:16]
    return f"{source}_{h}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean_text(html: str) -> str:
    """HTML → plaintext. Drops scripts/styles/nav, preserves paragraph breaks."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


class Http:
    """Thin httpx.Client wrapper: retries, backoff, polite default delay."""

    def __init__(self, delay: float = 0.5, timeout: float = 30.0):
        self.delay = delay
        self.client = httpx.Client(
            headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml"},
            timeout=timeout,
            follow_redirects=True,
        )
        self.log = logging.getLogger("http")

    def get(self, url: str, retries: int = 3) -> httpx.Response | None:
        for attempt in range(1, retries + 1):
            try:
                r = self.client.get(url)
                if r.status_code == 200:
                    time.sleep(self.delay)
                    return r
                if r.status_code in (429, 503):
                    wait = 2**attempt
                    self.log.warning("%s on %s — backing off %ds", r.status_code, url, wait)
                    time.sleep(wait)
                    continue
                self.log.warning("HTTP %s on %s", r.status_code, url)
                return None
            except httpx.HTTPError as e:
                self.log.warning("attempt %d failed for %s: %s", attempt, url, e)
                time.sleep(attempt)
        self.log.error("giving up on %s", url)
        return None

    def close(self) -> None:
        self.client.close()


class JsonlWriter:
    """Append-mode JSONL writer. Tracks written count."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self._fh = None

    def __enter__(self) -> "JsonlWriter":
        self._fh = self.path.open("w", encoding="utf-8")  # fresh file per run
        return self

    def write(self, incident: Incident) -> None:
        assert self._fh is not None
        self._fh.write(json.dumps(incident.to_dict(), ensure_ascii=False) + "\n")
        self.count += 1

    def __exit__(self, *exc) -> None:
        if self._fh:
            self._fh.close()


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Read a JSONL file back in. Used by preprocessing + tests."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
