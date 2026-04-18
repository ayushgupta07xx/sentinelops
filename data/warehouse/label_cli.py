# data/warehouse/label_cli.py
"""Manual labeling CLI — cycle incidents, override severity + category.
Keys:  0-3 severity  |  1-6 category  |  -/Enter keep current  |  s skip  |  q quit
Run:   python data/warehouse/label_cli.py --limit 500 --mode low-conf
"""
import duckdb
import argparse
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "warehouse" / "corpus.db"
CATS = [(1, "networking"), (2, "database"), (3, "deploy"),
        (4, "capacity"), (5, "auth"), (6, "other")]
SEVS = ["P0", "P1", "P2", "P3"]


def fetch(con, mode, limit, exclude_sources=None, min_body_len=400):
    order = {
        "low-conf":  "ORDER BY COALESCE(category_confidence,0)+COALESCE(severity_confidence,0) ASC",
        "random":    "ORDER BY random()",
        "unlabeled": "ORDER BY published_date DESC NULLS LAST",
    }[mode]
    where = ["label_source='weak'" if mode != "unlabeled" else "label_source IS NULL"]
    where.append(f"LENGTH(body) >= {min_body_len}")
    if exclude_sources:
        quoted = ",".join(f"'{s}'" for s in exclude_sources)
        where.append(f"source NOT IN ({quoted})")
    # exclude GitLab incident.io auto-tickets specifically
    where.append("NOT (source='gitlab' AND title LIKE '%Severity 4%')")
    where.append("NOT (source='gitlab' AND body LIKE '%_This ticket was created to track_%' AND LENGTH(body) < 800)")
    where_sql = "WHERE " + " AND ".join(where)
    q = f"""
        SELECT i.incident_id, i.title, i.body, i.source, i.severity,
               i.severity_confidence, c.category_name, i.category_confidence
        FROM fact_incidents i
        LEFT JOIN dim_categories c ON c.category_id = i.category_id
        {where_sql} {order} LIMIT {limit}
    """
    return con.execute(q).fetchall()


def ask(prompt, valid):
    while True:
        r = input(prompt).strip().lower()
        if r in ("q", "quit"):  return "__quit__"
        if r in ("s", "skip"):  return "__skip__"
        if r in ("", "-"):      return None
        if r in valid:          return r
        print(f"  invalid. valid={list(valid)} / '-' keep / s skip / q quit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--mode", choices=["low-conf", "random", "unlabeled"], default="low-conf")
    ap.add_argument("--exclude", nargs="*", default=[], help="sources to exclude, e.g. --exclude gitlab")
    ap.add_argument("--min-body", type=int, default=400)
    args = ap.parse_args()

    con = duckdb.connect(str(DB_PATH))
    rows = fetch(con, args.mode, args.limit, args.exclude, args.min_body)
    print(f"[label-cli] loaded {len(rows)} ({args.mode})")

    sev_valid = {str(i): SEVS[i] for i in range(4)}
    cat_valid = {str(cid): name for cid, name in CATS}
    saved = 0

    try:
        for i, (inc_id, title, body, source, cur_sev, sev_c, cur_cat, cat_c) in enumerate(rows, 1):
            print("\n" + "=" * 70)
            print(f"[{i}/{len(rows)}]  {inc_id}  ({source})")
            print(f"TITLE: {title}")
            excerpt = (body or "")[:800].replace("\n", " ")
            print("BODY:  " + textwrap.shorten(excerpt, 700))
            print(f"\n  current  sev={cur_sev} (c={sev_c})  cat={cur_cat} (c={cat_c})")

            sev_in = ask("  severity [0-3 / - / s / q]: ", sev_valid)
            if sev_in == "__quit__": break
            if sev_in == "__skip__": continue

            cat_in = ask("  category [" + " ".join(f"{c}={n[:3]}" for c, n in CATS) + " / - / s / q]: ", cat_valid)
            if cat_in == "__quit__": break
            if cat_in == "__skip__": continue

            save = ask("  save? [y/n/q]: ", {"y": 1, "n": 0})
            if save == "__quit__": break
            if save != "y": continue

            new_sev = sev_valid[sev_in] if sev_in else cur_sev
            new_cat_id = int(cat_in) if cat_in else next((c for c, n in CATS if n == cur_cat), 6)
            con.execute("""
                UPDATE fact_incidents
                SET severity=?, severity_confidence=1.0,
                    category_id=?, category_confidence=1.0,
                    label_source='manual'
                WHERE incident_id=?
            """, [new_sev, new_cat_id, inc_id])
            saved += 1
    except KeyboardInterrupt:
        print("\n[label-cli] interrupted")

    n_manual = con.execute("SELECT COUNT(*) FROM fact_incidents WHERE label_source='manual'").fetchone()[0]
    print(f"\n[label-cli] session saved: {saved}  |  total manual: {n_manual}")
    con.close()


if __name__ == "__main__":
    main()