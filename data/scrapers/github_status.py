"""Scrape GitHub's public status page incidents.

githubstatus.com exposes incident history via Atom. Each entry links to a page
with the full updates timeline.

Run: python -m data.scrapers.github_status
Output: data/raw/github_status.jsonl
"""

from __future__ import annotations

import logging

import feedparser

from ._utils import RAW_DIR, Http, Incident, JsonlWriter, clean_text, make_id, now_iso

log = logging.getLogger("github_status")

SOURCE = "github_status"
OUTPUT = RAW_DIR / "github_status.jsonl"
FEED_URL = "https://www.githubstatus.com/history.atom"


def scrape() -> int:
    log.info("fetching atom feed")
    feed = feedparser.parse(FEED_URL)
    if not feed.entries:
        log.error("empty feed")
        return 0
    log.info("feed has %d entries", len(feed.entries))

    http = Http(delay=0.5)
    written = 0
    with JsonlWriter(OUTPUT) as out:
        for i, entry in enumerate(feed.entries, 1):
            if i % 20 == 0:
                log.info("progress %d/%d", i, len(feed.entries))

            url = entry.get("link", "")
            title = entry.get("title", "").strip()
            published = entry.get("published", "") or entry.get("updated", "")

            # feed summary already contains the full timeline in HTML; use it directly
            summary_html = entry.get("summary", "")
            body = clean_text(summary_html) if summary_html else ""

            # fall back to fetching the page if summary is thin
            if len(body) < 200 and url:
                r = http.get(url)
                if r:
                    body = clean_text(r.text)

            if len(body) < 100:
                continue

            out.write(
                Incident(
                    id=make_id(SOURCE, url or title),
                    source=SOURCE,
                    url=url,
                    title=title[:500],
                    body=body,
                    published_at=published or None,
                    scraped_at=now_iso(),
                )
            )
            written += 1

    http.close()
    log.info("done: %d incidents → %s", written, OUTPUT)
    return written


if __name__ == "__main__":
    scrape()
