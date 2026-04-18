"""Scrape Cloudflare's blog post-mortem tag.

Cloudflare publishes detailed post-mortems under the 'post-mortem' tag. We walk
pagination, collect post URLs, then fetch each and extract the article body.

Run: python -m data.scrapers.cloudflare
Output: data/raw/cloudflare.jsonl
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from ._utils import RAW_DIR, Http, Incident, JsonlWriter, clean_text, make_id, now_iso

log = logging.getLogger("cloudflare")

SOURCE = "cloudflare"
OUTPUT = RAW_DIR / "cloudflare.jsonl"
TAG_URL = "https://blog.cloudflare.com/tag/post-mortem/"
BASE = "https://blog.cloudflare.com"
MAX_PAGES = 10  # safety cap


def collect_post_urls(http: Http) -> list[str]:
    """Walk paginated tag pages, return unique post URLs."""
    urls: list[str] = []
    seen = set()
    page = 1
    while page <= MAX_PAGES:
        url = TAG_URL if page == 1 else f"{TAG_URL}page/{page}/"
        log.info("listing page %d: %s", page, url)
        r = http.get(url)
        if not r or r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "lxml")
        links = soup.select("a[href]")
        found_on_page = 0
        for a in links:
            href = a.get("href", "")
            if not href.startswith(("/", "https://blog.cloudflare.com/")):
                continue
            full = href if href.startswith("http") else BASE + href
            # post URLs are single path segments off the root, not /tag/ or /author/
            path = full.replace(BASE, "").strip("/")
            if not path or "/" in path.rstrip("/"):
                continue
            if any(skip in path for skip in ("tag", "author", "page")):
                continue
            if full not in seen:
                seen.add(full)
                urls.append(full)
                found_on_page += 1
        if found_on_page == 0:
            break
        page += 1
    return urls


def extract_post(html: str) -> tuple[str, str, str | None]:
    """Return (title, body_text, published_at_iso_or_none)."""
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""
    # Cloudflare uses <article> or main content div
    article = soup.find("article") or soup.find("main") or soup
    body = clean_text(str(article))
    date = None
    time_el = soup.find("time")
    if time_el and time_el.get("datetime"):
        date = time_el["datetime"]
    return title, body, date


def scrape() -> int:
    http = Http(delay=1.0)
    urls = collect_post_urls(http)
    log.info("collected %d post URLs", len(urls))

    written = 0
    with JsonlWriter(OUTPUT) as out:
        for i, url in enumerate(urls, 1):
            if i % 10 == 0:
                log.info("progress %d/%d", i, len(urls))
            r = http.get(url)
            if not r:
                continue
            title, body, date = extract_post(r.text)
            if len(body) < 500:
                continue
            out.write(
                Incident(
                    id=make_id(SOURCE, url),
                    source=SOURCE,
                    url=url,
                    title=title[:500] or url,
                    body=body,
                    published_at=date,
                    scraped_at=now_iso(),
                )
            )
            written += 1

    http.close()
    log.info("done: %d incidents → %s", written, OUTPUT)
    return written


if __name__ == "__main__":
    scrape()
