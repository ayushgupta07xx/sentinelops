"""Scrape GitLab's public production postmortem repo.

GitLab keeps recent postmortems as markdown issues in a public GitLab project:
https://gitlab.com/gitlab-com/gl-infra/production. We use GitLab's REST API
to list issues labeled ~"Incident::Active" or ~"incident" and fetch bodies.

Run: python -m data.scrapers.gitlab
Output: data/raw/gitlab.jsonl
"""

from __future__ import annotations

import logging

from ._utils import RAW_DIR, Http, Incident, JsonlWriter, make_id, now_iso

log = logging.getLogger("gitlab")

SOURCE = "gitlab"
OUTPUT = RAW_DIR / "gitlab.jsonl"

# Public repo, no auth needed for read-only issue listing
PROJECT_ID = "gitlab-com%2Fgl-infra%2Fproduction"
API = f"https://gitlab.com/api/v4/projects/{PROJECT_ID}/issues"
PER_PAGE = 100
MAX_PAGES = 10  # 1000 issue cap


def scrape() -> int:
    http = Http(delay=0.4)
    written = 0

    with JsonlWriter(OUTPUT) as out:
        for page in range(1, MAX_PAGES + 1):
            # filter to closed incidents — open issues are often noise
            url = (
                f"{API}?state=closed&labels=incident&per_page={PER_PAGE}&page={page}"
                "&order_by=created_at&sort=desc"
            )
            log.info("fetching page %d", page)
            r = http.get(url)
            if not r:
                break
            issues = r.json()
            if not issues:
                break

            for issue in issues:
                body = (issue.get("description") or "").strip()
                if len(body) < 200:
                    continue
                out.write(
                    Incident(
                        id=make_id(SOURCE, issue["web_url"]),
                        source=SOURCE,
                        url=issue["web_url"],
                        title=(issue.get("title") or "")[:500],
                        body=body,
                        published_at=issue.get("created_at"),
                        scraped_at=now_iso(),
                    )
                )
                written += 1

            if len(issues) < PER_PAGE:
                break  # last page

    http.close()
    log.info("done: %d incidents → %s", written, OUTPUT)
    return written


if __name__ == "__main__":
    scrape()
