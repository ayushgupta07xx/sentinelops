"""PII scrubbing.

Two layers:
1. Regex for high-confidence structured PII: emails, IPs, URLs in specific contexts,
   credit-card-like numbers, long hex tokens (API keys / hashes).
2. Presidio for names, phones. (Presidio is heavy; we lazy-init it.)

Strategy: replace with semantic placeholders like <EMAIL>, <IP>, <PERSON>.
The LLM will learn to reproduce these placeholders when writing postmortems,
which is actually desirable behaviour.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("pii")

# Regex layer
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_RE = re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){4,7}[A-Fa-f0-9]{1,4}\b")
# Long hex tokens — 32+ chars (API keys, commit hashes, hashes)
HEX_TOKEN_RE = re.compile(r"\b[a-f0-9]{32,}\b")
# Credit-card-ish (14-19 digits, possibly separated)
CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_analyzer = None
_anonymizer = None


def _ensure_presidio():
    """Lazy import — Presidio's spaCy model takes seconds to load."""
    global _analyzer, _anonymizer
    if _analyzer is not None:
        return
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

    log.info("loading Presidio (one-time)")
    _analyzer = AnalyzerEngine()
    _anonymizer = AnonymizerEngine()


def _regex_scrub(text: str) -> str:
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = IPV4_RE.sub("<IP>", text)
    text = IPV6_RE.sub("<IP>", text)
    text = HEX_TOKEN_RE.sub("<TOKEN>", text)
    text = CC_RE.sub("<CC>", text)
    return text


def scrub(text: str, use_presidio: bool = True) -> str:
    """Redact PII. Set use_presidio=False for fast regex-only pass."""
    text = _regex_scrub(text)
    if not use_presidio:
        return text

    _ensure_presidio()
    # Presidio is slow on long docs; chunk at paragraph level
    out_parts: list[str] = []
    for para in text.split("\n\n"):
        if not para.strip():
            out_parts.append(para)
            continue
        try:
            results = _analyzer.analyze(
                text=para,
                entities=["PERSON", "PHONE_NUMBER"],
                language="en",
                score_threshold=0.6,
            )
            if results:
                anon = _anonymizer.anonymize(text=para, analyzer_results=results)
                out_parts.append(anon.text)
            else:
                out_parts.append(para)
        except Exception as e:  # noqa: BLE001
            log.warning("presidio failed on paragraph (%d chars): %s — keeping raw", len(para), e)
            out_parts.append(para)
    return "\n\n".join(out_parts)
