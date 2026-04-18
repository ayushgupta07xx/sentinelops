"""Scrape the danluu/post-mortems curated list.

README.md contains ~400+ markdown links to public postmortems. We fetch the
README via GitHub's raw endpoint, extract links, then fetch each linked URL
and strip to plain text. URLs that 404 or return non-HTML are skipped.

Run: python -m data.scrapers.danluu
Output: data/raw/danluu.jsonl
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from ._utils import RAW_DIR, Http, Incident, JsonlWriter, clean_text, make_id, now_iso

log = logging.getLogger("danluu")

README_URL = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"
SOURCE = "danluu"
OUTPUT = RAW_DIR / "danluu.jsonl"

# markdown link: [title](url)
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

# skip these domains — they're navigation/meta, not postmortems
SKIP_DOMAINS = {"github.com", "twitter.com", "x.com", "youtube.com", "youtu.be"}


def extract_links(md: str) -> list[tuple[str, str]]:
    """Return [(title, url), ...] from the README."""
    seen = set()
    out: list[tuple[str, str]] = []
    for title, url in LINK_RE.findall(md):
        url = url.rstrip(".,);")
        if url in seen:
            continue
        domain = urlparse(url).netloc.lower().lstrip("www.")
        if any(skip in domain for skip in SKIP_DOMAINS):
            continue
        seen.add(url)
        out.append((title.strip(), url))
    return out


def scrape() -> int:
    http = Http(delay=0.3)
    log.info("fetching README index")
    r = http.get(README_URL)
    if not r:
        log.error("could not fetch danluu README — aborting")
        return 0

    links = extract_links(r.text)
    log.info("found %d candidate links", len(links))

    written = 0
    with JsonlWriter(OUTPUT) as out:
        for i, (title, url) in enumerate(links, 1):
            if i % 25 == 0:
                log.info("progress: %d/%d (written=%d)", i, len(links), written)
            resp = http.get(url)
            if not resp:
                continue
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype and "text" not in ctype:
                continue
            body = clean_text(resp.text)
            if len(body) < 200:  # widened — recover shorter postmortems
                continue
            incident = Incident(
                id=make_id(SOURCE, url),
                source=SOURCE,
                url=url,
                title=title[:500],
                body=body,
                published_at=None,  # danluu list has no dates
                scraped_at=now_iso(),
                raw_html=None,  # skip — corpus would balloon
            )
            out.write(incident)
            written += 1

    http.close()
    log.info("done: %d incidents → %s", written, OUTPUT)
    return written


if __name__ == "__main__":
    scrape()
