"""End-to-end preprocessing pipeline.

Read:  data/raw/*.jsonl
Write: data/processed/corpus.jsonl       (one cleaned incident per line)
       data/processed/corpus_chunks.jsonl (chunked, classifier-ready)

Run: python -m data.preprocessing.run_pipeline
Optional flags:
  --no-pii   skip Presidio (faster, regex-only PII scrub)
  --sample N process only N records (for smoke testing)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from tqdm import tqdm

from data.scrapers._utils import iter_jsonl
from .chunk import chunk_record
from .cleanup import clean
from .dedup import dedupe
from .pii import scrub

log = logging.getLogger("pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-10s %(levelname)-7s %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_DIR = REPO_ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_all_raw(sample: int | None = None) -> list[dict]:
    records: list[dict] = []
    for path in sorted(RAW_DIR.glob("*.jsonl")):
        count_before = len(records)
        for rec in iter_jsonl(path):
            records.append(rec)
            if sample and len(records) >= sample:
                break
        log.info("loaded %s: +%d (total %d)", path.name, len(records) - count_before, len(records))
        if sample and len(records) >= sample:
            break
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.info("wrote %d records → %s", len(records), path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pii", action="store_true", help="skip Presidio, regex-only PII scrub")
    ap.add_argument("--sample", type=int, default=None, help="process only N records")
    args = ap.parse_args()

    log.info("stage 1/4: loading raw")
    raw = load_all_raw(sample=args.sample)
    log.info("loaded %d raw records", len(raw))

    log.info("stage 2/4: cleanup + PII scrub")
    use_presidio = not args.no_pii
    cleaned: list[dict] = []
    for rec in tqdm(raw, desc="clean+pii"):
        body = clean(rec.get("body", ""))
        if len(body) < 200:
            continue
        body = scrub(body, use_presidio=use_presidio)
        rec = dict(rec)
        rec["body"] = body
        cleaned.append(rec)
    log.info("after cleanup: %d records", len(cleaned))

    log.info("stage 3/4: dedup")
    deduped = dedupe(cleaned)

    log.info("stage 4/4: chunk")
    chunks: list[dict] = []
    for rec in deduped:
        chunks.extend(chunk_record(rec))
    log.info("produced %d chunks", len(chunks))

    write_jsonl(OUT_DIR / "corpus.jsonl", deduped)
    write_jsonl(OUT_DIR / "corpus_chunks.jsonl", chunks)

    print("\n" + "=" * 40)
    print(f"{'raw':<20}{len(raw):>10,}")
    print(f"{'after cleanup':<20}{len(cleaned):>10,}")
    print(f"{'after dedup':<20}{len(deduped):>10,}")
    print(f"{'chunks':<20}{len(chunks):>10,}")
    print("=" * 40)


if __name__ == "__main__":
    main()
