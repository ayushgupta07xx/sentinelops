# data/warehouse/weak_label.py
"""Apply keyword/regex rules to fill severity + category for unlabeled incidents.
Run: python data/warehouse/weak_label.py
"""
import duckdb
import re
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "warehouse" / "corpus.db"

CATEGORY_KEYWORDS = {
    "networking": ["dns", "bgp", "cdn", "load balancer", "network", "connectivity",
                   "routing", "tcp", "tls", "ssl handshake", "cloudfront", "edge",
                   "ingress", "firewall", "packet loss", "latency spike"],
    "database":   ["database", "postgres", "mysql", "replication", "mongodb",
                   "redis", "dynamodb", " db ", "sql ", "query ", "deadlock",
                   "corruption", "index"],
    "deploy":     ["deploy", "release", "rollback", "config change", "feature flag",
                   "canary", "rollout", "migration", "new version"],
    "capacity":   ["oom", "out of memory", "memory leak", "cpu", "disk full",
                   "quota", "throttl", "rate limit", "autoscal", "saturation",
                   "overload"],
    "auth":       ["authentication", "authorization", "certificate", "cert expir",
                   "tls cert", "ssl cert", "sso", "oauth", "login", "credential"],
}

SEVERITY_PATTERNS = [
    ("P0", [r"\b(global|complete|total|full)\s+outage\b",
            r"\ball\s+(users|customers|regions)\b",
            r"\bworldwide\s+outage\b",
            r"\bmajor\s+incident\b"]),
    ("P1", [r"\bmajor\s+outage\b",
            r"\bsignificant\s+impact\b",
            r"\bmany\s+(users|customers)\b",
            r"\bdegraded\s+performance\b"]),
    ("P2", [r"\bpartial\s+outage\b",
            r"\bsome\s+(users|customers)\b",
            r"\bintermittent\b",
            r"\bbrief\s+outage\b"]),
    ("P3", [r"\bminor\s+issue\b", r"\bisolated\b", r"\bsingle\s+(user|customer)\b"]),
]


def score_category(text: str):
    t = text.lower()
    scores = {cat: sum(1 for k in kws if k in t) for cat, kws in CATEGORY_KEYWORDS.items()}
    best_cat, best_hits = max(scores.items(), key=lambda x: x[1])
    if best_hits == 0:
        return "other", 0.0
    total = sum(scores.values())
    return best_cat, round(best_hits / max(total, 1), 3)


def score_severity(text: str):
    t = text.lower()
    for sev, pats in SEVERITY_PATTERNS:
        for p in pats:
            if re.search(p, t):
                return sev, 0.6
    return None, 0.0


def main():
    con = duckdb.connect(str(DB_PATH))
    rows = con.execute("""
        SELECT incident_id, title, body
        FROM fact_incidents
        WHERE label_source IS NULL
    """).fetchall()
    print(f"[weak-label] candidates: {len(rows)}")

    cat_map = {r[0]: r[1] for r in
               con.execute("SELECT category_name, category_id FROM dim_categories").fetchall()}

    cat_counts, sev_counts, updates = Counter(), Counter(), []
    for inc_id, title, body in rows:
        text = f"{title or ''} {body or ''}"
        cat, cat_c = score_category(text)
        sev, sev_c = score_severity(text)
        updates.append((cat_map.get(cat, cat_map["other"]), cat_c, sev, sev_c, "weak", inc_id))
        cat_counts[cat] += 1
        sev_counts[sev or "unlabeled"] += 1

    con.executemany("""
        UPDATE fact_incidents
        SET category_id=?, category_confidence=?,
            severity=?, severity_confidence=?, label_source=?
        WHERE incident_id=?
    """, updates)

    print("\n== category ==")
    for c, n in cat_counts.most_common():
        print(f"  {c:12s} {n}")
    print("\n== severity ==")
    for s, n in sev_counts.most_common():
        print(f"  {s:12s} {n}")
    con.close()


if __name__ == "__main__":
    main()