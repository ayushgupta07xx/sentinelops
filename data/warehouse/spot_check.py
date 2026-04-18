# data/warehouse/spot_check.py
"""Spot-check LLM labels. Samples ~30 stratified across categories.
Run: python data/warehouse/spot_check.py --n 30
"""
import duckdb
import argparse
import textwrap
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "warehouse" / "corpus.db"
REPORT = ROOT / "data" / "warehouse" / "spot_check_report.json"
CATS = [(1, "networking"), (2, "database"), (3, "deploy"),
        (4, "capacity"), (5, "auth"), (6, "other")]
SEVS = ["P0", "P1", "P2", "P3"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    con = duckdb.connect(str(DB_PATH))
    # stratified: ~5 per category where possible, random within
    rows = con.execute(f"""
        WITH ranked AS (
            SELECT i.incident_id, i.title, i.body, i.source,
                   i.severity, c.category_name,
                   i.severity_confidence, i.category_confidence,
                   row_number() OVER (PARTITION BY c.category_name ORDER BY random()) AS rn
            FROM fact_incidents i
            LEFT JOIN dim_categories c ON c.category_id = i.category_id
            WHERE i.label_source = 'llm'
        )
        SELECT incident_id, title, body, source, severity, category_name,
               severity_confidence, category_confidence
        FROM ranked
        WHERE rn <= {max(1, args.n // 6)}
        ORDER BY random()
        LIMIT {args.n}
    """).fetchall()

    print(f"[spot-check] {len(rows)} samples\n")
    print("For each: y=correct  n=wrong  c=wrong, I'll fix it  s=skip  q=quit\n")

    results = []
    for i, (inc_id, title, body, source, sev, cat, sev_c, cat_c) in enumerate(rows, 1):
        print("=" * 70)
        print(f"[{i}/{len(rows)}] {inc_id} ({source})")
        print(f"TITLE: {title}")
        body_excerpt = (body or "")[:600].replace("\n", " ")
        print("BODY:  " + textwrap.shorten(body_excerpt, 500))
        print(f"\nLLM label:  severity={sev} (c={sev_c:.2f})  category={cat} (c={cat_c:.2f})")

        r = input("correct? [y/n/c/s/q]: ").strip().lower()
        if r == "q":
            break
        if r == "s":
            continue
        if r == "y":
            results.append({"id": inc_id, "agree": True, "llm": [sev, cat], "fixed": None})
            continue
        # n or c
        fixed = None
        if r == "c":
            print("  correct severity [0=P0 1=P1 2=P2 3=P3 - keep]: ", end="")
            s_in = input().strip()
            new_sev = SEVS[int(s_in)] if s_in in "0123" else sev
            print("  correct category [" + " ".join(f"{c}={n[:3]}" for c, n in CATS) + " - keep]: ", end="")
            c_in = input().strip()
            new_cat_id = int(c_in) if c_in in "123456" else None
            if new_cat_id:
                con.execute("""
                    UPDATE fact_incidents
                    SET severity=?, severity_confidence=1.0,
                        category_id=?, category_confidence=1.0,
                        label_source='manual'
                    WHERE incident_id=?
                """, [new_sev, new_cat_id, inc_id])
                new_cat = dict(CATS)[new_cat_id]
                fixed = [new_sev, new_cat]
                print(f"  → updated to {new_sev}/{new_cat}")
        results.append({"id": inc_id, "agree": False, "llm": [sev, cat], "fixed": fixed})

    # report
    agree = sum(1 for r in results if r["agree"])
    total = len(results)
    rate = agree / total if total else 0.0
    print(f"\n{'='*70}\nAgreement: {agree}/{total} = {rate:.0%}")

    REPORT.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "n_checked": total,
        "n_agree": agree,
        "agreement_rate": rate,
        "samples": results,
    }, indent=2))
    print(f"Report saved: {REPORT}")

    if rate >= 0.85:
        print("✅ LLM labels trustworthy — proceed to training.")
    elif rate >= 0.70:
        print("⚠️  Moderate agreement — consider re-running LLM with tighter prompt.")
    else:
        print("❌ Low agreement — labels unreliable, needs rework.")

    con.close()


if __name__ == "__main__":
    main()