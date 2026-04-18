"""Text cleanup for scraped incidents.

Raw scraped bodies have:
- Wayback Machine archive headers ('193 captures', month scroll bars)
- Repeated nav/footer fragments that slipped past BeautifulSoup
- Excessive blank lines and non-breaking spaces
- Zero-width chars, tabs, smart quotes

This stage normalizes. It's deterministic and idempotent.
"""

from __future__ import annotations

import re
import unicodedata

# Wayback Machine top-header signatures. Match once, drop everything above the match.
WAYBACK_MARKERS = (
    "The Wayback Machine - ",
    "About this capture",
    "COLLECTED BY",
)

# Lines that are always noise
NOISE_LINES = re.compile(
    r"^("
    r"\d+ captures|"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*$|"
    r"\d{4}\s*$|"                     # bare year
    r"(success|fail|Loading\.\.\.)\s*$|"
    r"TIMESTAMPS|"
    r"Collection:.*|"
    r"Skip to (main )?content|"
    r"Cookie [Ss]ettings.*|"
    r"Subscribe( to .*)?|"
    r"Share on (Twitter|LinkedIn|Facebook).*|"
    r"© \d{4}.*"
    r")$",
    re.IGNORECASE,
)

MULTISPACE = re.compile(r"[ \t\u00A0]+")
MULTI_NL = re.compile(r"\n{3,}")


def _strip_wayback_header(text: str) -> str:
    """Drop everything up to and including 'The Wayback Machine - ...' line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(marker in line for marker in WAYBACK_MARKERS):
            # skip through this line
            return "\n".join(lines[i + 1 :])
    return text


def clean(text: str) -> str:
    """Normalize one incident body. Safe to call twice."""
    if not text:
        return ""
    # unicode normalize (smart quotes → ascii, zero-width stripped)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = _strip_wayback_header(text)

    kept = []
    for raw in text.splitlines():
        line = MULTISPACE.sub(" ", raw).strip()
        if not line:
            kept.append("")
            continue
        if NOISE_LINES.match(line):
            continue
        kept.append(line)

    out = "\n".join(kept)
    out = MULTI_NL.sub("\n\n", out)
    return out.strip()
