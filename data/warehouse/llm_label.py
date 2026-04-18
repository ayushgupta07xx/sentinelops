# data/warehouse/llm_label.py
"""Auto-label incidents via Groq llama-3.3-70b-versatile.
Run: python data/warehouse/llm_label.py --limit 250 --sources danluu cloudflare github_status
"""
import duckdb
import json
import os
import time
import argparse
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "warehouse" / "corpus.db"
load_dotenv(ROOT / "sentinelops.env")

DEFAULT_MODEL = "llama-3.3-70b-versatile"
RPM = 28  # stay under 30 RPM limit
SLEEP = 60.0 / RPM

SYSTEM_PROMPT = """You are labeling SRE incident reports for a classifier. Given a title and body, output ONE JSON object and nothing else.

Schema:
{"severity": "P0|P1|P2|P3|null", "category": "networking|database|deploy|capacity|auth|other", "confidence_severity": 0.0-1.0, "confidence_category": 0.0-1.0, "rationale": "one short sentence"}

SEVERITY:
- P0: global/total outage, all users or all regions affected, or explicitly labeled "Severity 1" / "critical"
- P1: major outage, significant user impact, region-wide, multiple services degraded
- P2: partial outage, some users affected, intermittent, one service degraded
- P3: minor issue, SLO blip, single component, isolated, "Severity 4" / "low"
- null: body is garbage (nav menus, cookie banners) or severity genuinely uncertain

CATEGORY:
- networking: DNS, BGP, CDN, TLS/SSL, load balancer, routing, connectivity, packet loss
- database: DB down, replication, slow queries, Redis, MongoDB, Postgres, MySQL, data corruption
- deploy: bad release, rollback, config change, feature flag, migration, canary issue
- capacity: OOM, memory leak, CPU saturation, disk full, quota, rate limit, autoscale
- auth: certificate expiry, SSO, OAuth, login failure, token issue, credential
- other: truly doesn't fit, mixed causes, or body is uninformative

Confidence: 0.9+ when the text states it explicitly. 0.5-0.7 when inferred. <0.4 when guessing — prefer null/other instead."""


def classify(client: Groq, title: str, body: str, model: str) -> dict:
    body_excerpt = (body or "")[:1500]
    prompt = f"TITLE: {title}\n\nBODY:\n{body_excerpt}"
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=300,
    )
    return json.loads(resp.choices[0].message.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--sources", nargs="*", default=["danluu", "cloudflare", "github_status"])
    ap.add_argument("--min-body", type=int, default=400)
    ap.add_argument("--include-gitlab-long", action="store_true",
                    help="also include gitlab incidents with body>1200 chars")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="Groq model id, e.g. llama-3.1-8b-instant")
    args = ap.parse_args()

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("GROQ_API_KEY not in sentinelops.env")
    client = Groq(api_key=api_key)

    con = duckdb.connect(str(DB_PATH))
    quoted = ",".join(f"'{s}'" for s in args.sources)
    extra = ""
    if args.include_gitlab_long:
        extra = f"OR (source='gitlab' AND LENGTH(body) > 1200)"
    q = f"""
        SELECT incident_id, title, body
        FROM fact_incidents
        WHERE (source IN ({quoted}) {extra})
          AND LENGTH(body) >= {args.min_body}
          AND (label_source IS NULL OR label_source = 'weak')
        ORDER BY source, incident_id
        LIMIT {args.limit}
    """
    rows = con.execute(q).fetchall()
    print(f"[llm-label] {len(rows)} incidents to label via {args.model}")

    cat_map = {r[0]: r[1] for r in
               con.execute("SELECT category_name, category_id FROM dim_categories").fetchall()}

    ok, fail, skipped = 0, 0, 0
    for i, (inc_id, title, body) in enumerate(rows, 1):
        try:
            t0 = time.time()
            out = classify(client, title or "", body or "", args.model)
            sev = out.get("severity")
            if sev == "null":
                sev = None
            cat = out.get("category", "other")
            cat_id = cat_map.get(cat, cat_map["other"])
            sev_c = float(out.get("confidence_severity", 0.0) or 0.0)
            cat_c = float(out.get("confidence_category", 0.0) or 0.0)

            con.execute("""
                UPDATE fact_incidents
                SET severity=?, severity_confidence=?,
                    category_id=?, category_confidence=?,
                    label_source='llm'
                WHERE incident_id=?
            """, [sev, sev_c, cat_id, cat_c, inc_id])
            ok += 1
            if i % 10 == 0 or i == len(rows):
                print(f"  [{i}/{len(rows)}] ok={ok} fail={fail}  last: {cat}/{sev} ({sev_c:.2f})")

            # rate-limit
            elapsed = time.time() - t0
            if elapsed < SLEEP:
                time.sleep(SLEEP - elapsed)

        except KeyboardInterrupt:
            print("\n[llm-label] interrupted — progress saved")
            break
        except Exception as e:
            fail += 1
            print(f"  [{i}] FAIL {inc_id}: {type(e).__name__}: {e}")
            time.sleep(2)

    print(f"\n[llm-label] done: ok={ok} fail={fail} skipped={skipped}")
    con.close()


if __name__ == "__main__":
    main()