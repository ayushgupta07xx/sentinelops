"""Run all four scrapers in sequence. Prints a count summary at the end.

Run: python -m data.scrapers.run_all
"""

from __future__ import annotations

import logging

from . import cloudflare, danluu, github_status, gitlab

log = logging.getLogger("run_all")


def main() -> None:
    results: dict[str, int] = {}
    for name, mod in [
        ("danluu", danluu),
        ("cloudflare", cloudflare),
        ("github_status", github_status),
        ("gitlab", gitlab),
    ]:
        log.info("=" * 60)
        log.info("running %s", name)
        log.info("=" * 60)
        try:
            results[name] = mod.scrape()
        except Exception as e:  # noqa: BLE001
            log.exception("%s failed: %s", name, e)
            results[name] = 0

    total = sum(results.values())
    print("\n" + "=" * 40)
    print(f"{'source':<20}{'count':>10}")
    print("-" * 40)
    for name, count in results.items():
        print(f"{name:<20}{count:>10,}")
    print("-" * 40)
    print(f"{'TOTAL':<20}{total:>10,}")
    print("=" * 40)


if __name__ == "__main__":
    main()
